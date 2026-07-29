#!/usr/bin/env python3
"""House style conformance checker for the effective-html reference files.

Each reference file is a self-contained HTML document that teaches the skill's
visual style by example, so a violation here propagates into every artifact the
skill generates. The checks below encode the house style's closed value sets.

Usage:
    tools/check-house-style.py                     # check every reference file
    tools/check-house-style.py path/to/one.html    # check specific files
    tools/check-house-style.py --rule spacing      # run one rule everywhere
    tools/check-house-style.py --baseline          # summary counts, exit 0

Exit status is 1 when any violation is found, so this works as a commit gate.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REFERENCES = REPO / "skills" / "effective-html" / "references"

# ---------------------------------------------------------------------------
# The house style's closed value sets.
#
# These are the single source of truth for the checker. A value absent from a
# set is a violation, not a judgement call — that is the point of closing them.
# ---------------------------------------------------------------------------

TYPE_SCALE = (11, 13, 16, 18, 21, 24, 30, 38, 52)
BODY_FLOOR = 16  # smallest size legal for sustained reading

# Georgia, Menlo, Consolas, DejaVu and Liberation each ship two weights, and
# Segoe UI has no 500 face, so 500 renders as 400 and 600 renders as full bold
# on most platforms. Only these two values mean what they say everywhere.
WEIGHTS = (400, 700)

# Properties that thin stems on one platform, or do nothing anywhere.
INERT_PROPERTIES = (
    "-webkit-font-smoothing",
    "-moz-osx-font-smoothing",
    "text-rendering",
    "font-optical-sizing",
)

# The serif face ships oldstyle figures with no lining or tabular alternates,
# so its digits vary 39% in width and no CSS corrects it.
SERIF_TOKENS = ("--font-display", "--serif")
RE_FIGURE_ONLY = re.compile(r"^[\s$€£+\-−]*[\d][\d,.\s%×x/:–—-]*[a-zA-Z%]{0,3}$")
SPACING = (0, 2, 4, 8, 12, 16, 20, 24, 32, 48, 64, 96)
RADII = (4, 8, 12, 999)
WIDTH_TOKENS = {
    "--w-rail": 278,
    "--w-text": 726,
    "--w-measure": 680,
    "--shell": 1100,
    "--shell-read": 808,
    "--shell-wide": 1320,
    "--w-steps": 320,
    "--w-pane": 840,
}
CONTROL_TARGET = 48  # the spacing rung that clears WCAG 2.2 SC 2.5.5's 44px

# Text roles must clear WCAG AA at body size. Ratios are against the mode's own
# --bg, which is why one shared muted pigment cannot serve both modes.
AA_BODY = 4.5
TEXT_ROLES = ("--ink", "--body", "--muted")

# Status colour never carries meaning alone; one of these must sit beside it.
REDUNDANT_ENCODING = re.compile(
    r"aria-label|role=\"img\"|<title>|↑|↓|→|▲|▼|&(?:uarr|darr|rarr);"
    r"|class=\"[^\"]*\b(?:icon|arrow|glyph|badge-label|status-label)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Pattern library
# ---------------------------------------------------------------------------

RE_FONT_SIZE = re.compile(r"font-size:\s*([0-9.]+)px")
RE_ROOT_BLOCK = re.compile(r"(?::root|html\.dark)\s*\{(.*?)\}", re.DOTALL)
RE_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
RE_FUNC_COLOUR = re.compile(r"\b(?:rgba?|hsla?|oklch|oklab|lab|lch)\s*\(", re.IGNORECASE)
RE_SVG_PAINT = re.compile(r"\b(?:fill|stroke|stop-color|flood-color)=\"([^\"]+)\"")
RE_MAX_WIDTH = re.compile(r"max-width:\s*([0-9.]+)px")
RE_RADIUS = re.compile(r"border-radius:\s*([^;}]+)")
RE_DARK_MODE = re.compile(r"html\.dark|\[data-theme|prefers-color-scheme")
RE_STYLE_BLOCK = re.compile(r"<style[^>]*>(.*?)</style>", re.DOTALL | re.IGNORECASE)
RE_CUSTOM_PROP = re.compile(r"(--[a-z0-9-]+)\s*:\s*([^;]+)")
RE_VAR_REF = re.compile(r"var\(\s*(--[a-z0-9-]+)\s*(?:,([^)]*))?\)")

# Spacing-bearing properties. Deliberately excludes component dimensions —
# row heights, icon boxes and chart geometry answer to content, not the scale.
SPACING_PROPS = ("gap", "row-gap", "column-gap", "padding", "margin")
RE_SPACING = re.compile(
    r"(?<![-a-z])((?:%s)(?:-(?:top|right|bottom|left|inline|block))?"
    r"(?:-(?:start|end))?):\s*([^;}]+)" % "|".join(SPACING_PROPS)
)
RE_PX_VALUE = re.compile(r"(-?[0-9.]+)px")


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    rule: str
    message: str

    @property
    def label(self) -> str:
        """Repo-relative where possible, absolute otherwise (probe files live in /tmp)."""
        try:
            return str(self.path.relative_to(REPO))
        except ValueError:
            return str(self.path)

    def render(self) -> str:
        return f"{self.label}:{self.line}: [{self.rule}] {self.message}"


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def stylesheets(text: str) -> list[tuple[int, str]]:
    """Every <style> block as (offset, css)."""
    return [(m.start(1), m.group(1)) for m in RE_STYLE_BLOCK.finditer(text)]


def token_blocks(text: str) -> list[tuple[int, int]]:
    """Character spans of :root / html.dark blocks — the only place colour literals live."""
    return [(m.start(1), m.end(1)) for m in RE_ROOT_BLOCK.finditer(text)]


def inside(spans: list[tuple[int, int]], index: int) -> bool:
    return any(start <= index < end for start, end in spans)


# ---------------------------------------------------------------------------
# Colour maths. WCAG 2.x relative luminance, sRGB.
# ---------------------------------------------------------------------------


def parse_hex(value: str) -> tuple[int, int, int] | None:
    digits = value.lstrip("#")
    if len(digits) in (3, 4):
        digits = "".join(c * 2 for c in digits[:3])
    if len(digits) in (6, 8):
        digits = digits[:6]
    else:
        return None
    try:
        return tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None


def luminance(rgb: tuple[int, int, int]) -> float:
    def channel(raw: int) -> float:
        c = raw / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = luminance(a), luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def resolve(name: str, table: dict[str, str], seen: frozenset[str] = frozenset()) -> str | None:
    """Follow a var() chain to a literal. Returns None on a cycle or dead end."""
    if name in seen or name not in table:
        return None
    value = table[name].strip()
    ref = RE_VAR_REF.search(value)
    if not ref:
        return value
    resolved = resolve(ref.group(1), table, seen | {name})
    if resolved is None and ref.group(2):
        return ref.group(2).strip()
    return resolved


def declared_tokens(text: str, selector: str) -> dict[str, str]:
    """Custom properties declared under a given selector, later wins."""
    table: dict[str, str] = {}
    for match in re.finditer(re.escape(selector) + r"\s*\{(.*?)\}", text, re.DOTALL):
        for prop in RE_CUSTOM_PROP.finditer(match.group(1)):
            table[prop.group(1)] = prop.group(2)
    return table


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def rule_type(path: Path, text: str) -> list[Violation]:
    out = []
    for match in RE_FONT_SIZE.finditer(text):
        raw = float(match.group(1))
        size = int(raw) if raw.is_integer() else raw
        if size not in TYPE_SCALE:
            nearest = min(TYPE_SCALE, key=lambda s: abs(s - raw))
            out.append(
                Violation(
                    path,
                    line_of(text, match.start()),
                    "type",
                    f"font-size {size}px is off the scale; nearest rung is {nearest}px",
                )
            )
    return out


def rule_spacing(path: Path, text: str) -> list[Violation]:
    out = []
    for offset, css in stylesheets(text):
        for match in RE_SPACING.finditer(css):
            prop, value = match.group(1), match.group(2)
            if "var(" in value or "calc(" in value:
                continue
            for px in RE_PX_VALUE.finditer(value):
                magnitude = abs(float(px.group(1)))
                if magnitude not in SPACING:
                    nearest = min(SPACING, key=lambda s: abs(s - magnitude))
                    out.append(
                        Violation(
                            path,
                            line_of(text, offset + match.start()),
                            "spacing",
                            f"{prop}: {px.group(0)} is off the spacing set; nearest rung is {nearest}px",
                        )
                    )
    return out


def rule_radius(path: Path, text: str) -> list[Violation]:
    out = []
    for offset, css in stylesheets(text):
        for match in RE_RADIUS.finditer(css):
            value = match.group(1)
            if "var(" in value or "%" in value:
                continue
            for px in RE_PX_VALUE.finditer(value):
                magnitude = abs(float(px.group(1)))
                if magnitude not in RADII:
                    out.append(
                        Violation(
                            path,
                            line_of(text, offset + match.start()),
                            "radius",
                            f"border-radius {px.group(0)} is not one of {RADII}",
                        )
                    )
    return out


def rule_width(path: Path, text: str) -> list[Violation]:
    legal = set(WIDTH_TOKENS.values())
    out = []
    for offset, css in stylesheets(text):
        for match in RE_MAX_WIDTH.finditer(css):
            value = float(match.group(1))
            if value not in legal:
                out.append(
                    Violation(
                        path,
                        line_of(text, offset + match.start()),
                        "width",
                        f"max-width {match.group(1)}px is not a shell or measure token",
                    )
                )
    return out


def rule_colour_literal(path: Path, text: str) -> list[Violation]:
    """Colour literals belong in the reference palette, nowhere else."""
    spans = token_blocks(text)
    out = []
    for offset, css in stylesheets(text):
        for match in RE_HEX.finditer(css):
            index = offset + match.start()
            if inside(spans, index):
                continue
            out.append(
                Violation(
                    path,
                    line_of(text, index),
                    "colour-literal",
                    f"hex {match.group(0)} outside the reference palette; use a role token",
                )
            )
        for match in RE_FUNC_COLOUR.finditer(css):
            index = offset + match.start()
            if inside(spans, index):
                continue
            out.append(
                Violation(
                    path,
                    line_of(text, index),
                    "colour-literal",
                    f"{match.group(0)}…) outside the reference palette; use a role token",
                )
            )
    return out


def rule_svg_paint(path: Path, text: str) -> list[Violation]:
    """An inline SVG that hard-codes paint cannot follow the theme."""
    out = []
    for match in RE_SVG_PAINT.finditer(text):
        value = match.group(1).strip()
        if RE_HEX.fullmatch(value) or RE_FUNC_COLOUR.match(value):
            out.append(
                Violation(
                    path,
                    line_of(text, match.start()),
                    "svg-paint",
                    f"SVG paint {value!r} is hard-coded; use var(--token)",
                )
            )
    return out


def rule_dark_mode(path: Path, text: str) -> list[Violation]:
    if RE_DARK_MODE.search(text):
        return []
    return [Violation(path, 1, "dark-mode", "no dark mode: both modes are first-class")]


RE_COLOUR_DECL = re.compile(r"(?<![-a-z])color:\s*([^;}]+)")
RE_BG_DECL = re.compile(r"(?<![-a-z])background(?:-color)?:\s*([^;}]+)")


def literal_colour(value: str, table: dict[str, str]) -> tuple[str, tuple[int, int, int]] | None:
    """Resolve a declaration value to a hex literal and its RGB, or None."""
    value = value.strip()
    ref = RE_VAR_REF.search(value)
    if ref:
        resolved = resolve(ref.group(1), table)
        if resolved is None:
            return None
        value = resolved.strip()
    match = RE_HEX.search(value)
    if not match:
        return None
    rgb = parse_hex(match.group(0))
    return (match.group(0), rgb) if rgb else None


def rule_contrast(path: Path, text: str) -> list[Violation]:
    """Every text colour must clear AA against the surface it sits on.

    Naming-agnostic on purpose: the corpus files paint text with pigment names
    (--gray-500) while the authored files use role names (--muted), and the same
    failing pigment has to be caught either way. A rule block that sets its own
    background is measured against that instead of the page.
    """
    out: list[Violation] = []
    light = declared_tokens(text, ":root")
    dark = dict(light)
    dark_overrides = declared_tokens(text, "html.dark")
    dark.update(dark_overrides)

    modes = [("light", light)]
    if dark_overrides:
        modes.append(("dark", dark))

    for offset, css in stylesheets(text):
        for rule_match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
            selector, body = rule_match.group(1).strip(), rule_match.group(2)
            colour_decl = RE_COLOUR_DECL.search(body)
            if not colour_decl:
                continue
            bg_decl = RE_BG_DECL.search(body)
            for mode, table in modes:
                page_bg = literal_colour("var(--bg)", table) or literal_colour(
                    "var(--ivory)" if mode == "light" else "var(--slate)", table
                )
                own_bg = literal_colour(bg_decl.group(1), table) if bg_decl else None
                surface = own_bg or page_bg
                fg = literal_colour(colour_decl.group(1), table)
                if not fg or not surface:
                    continue
                # A block painting text lighter than the page, without declaring its
                # own background, sits on a surface set by a sibling rule (.chip and
                # .chip.critical). The surface is unknowable from one block, so
                # measuring against the page would invent a failure.
                if own_bg is None and luminance(fg[1]) >= luminance(surface[1]):
                    continue
                ratio = contrast(fg[1], surface[1])
                if ratio < AA_BODY:
                    out.append(
                        Violation(
                            path,
                            line_of(text, offset + rule_match.start()),
                            "contrast",
                            f"{mode}: {selector!r} paints {colour_decl.group(1).strip()} "
                            f"({fg[0]}) on {surface[0]} at {ratio:.2f}:1, under AA's {AA_BODY}:1",
                        )
                    )
    return out


def rule_body_floor(path: Path, text: str) -> list[Violation]:
    """Sustained reading below the body floor is the corpus's oldest defect."""
    out = []
    for offset, css in stylesheets(text):
        for rule_match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
            selector, body = rule_match.group(1).strip(), rule_match.group(2)
            if not re.search(r"\b(?:body|p|li|dd|blockquote)\b", selector):
                continue
            if re.search(r"\.(?:meta|label|caption|badge|chip|note|micro)", selector):
                continue
            for size_match in RE_FONT_SIZE.finditer(body):
                size = float(size_match.group(1))
                if size < BODY_FLOOR:
                    out.append(
                        Violation(
                            path,
                            line_of(text, offset + rule_match.start()),
                            "body-floor",
                            f"prose selector {selector!r} sets {size:g}px, "
                            f"under the {BODY_FLOOR}px body floor",
                        )
                    )
    return out


RE_STATUS_TOKEN = re.compile(r"critical|warning|positive|danger|success|error")


def rule_redundant_encoding(path: Path, text: str) -> list[Violation]:
    """Status colour must never be the only carrier of meaning.

    Scoped to the elements that actually wear a status colour, because a
    document-wide search for a marker passes trivially — every long file in this
    corpus contains at least one <title> in some SVG. An element painted with a
    status token must carry its own text or marker inside it.
    """
    light = declared_tokens(text, ":root")
    if not any(RE_STATUS_TOKEN.search(name) for name in light):
        return []

    # Classes whose rule block paints with a status token.
    painted: set[str] = set()
    for _, css in stylesheets(text):
        for rule_match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
            selector, body = rule_match.group(1), rule_match.group(2)
            refs = [r.group(1) for r in RE_VAR_REF.finditer(body)]
            if not any(RE_STATUS_TOKEN.search(name) for name in refs):
                continue
            painted.update(re.findall(r"\.([A-Za-z][\w-]*)", selector))
    if not painted:
        return []

    out: list[Violation] = []
    for element in re.finditer(
        r"<(\w+)([^>]*\bclass=\"([^\"]*)\"[^>]*)>(.*?)</\1>", text, re.DOTALL
    ):
        classes = set(element.group(3).split())
        if not classes & painted:
            continue
        attrs, inner = element.group(2), element.group(4)
        stripped = re.sub(r"<[^>]+>", "", inner).strip()
        if stripped or REDUNDANT_ENCODING.search(attrs) or REDUNDANT_ENCODING.search(inner):
            continue
        out.append(
            Violation(
                path,
                line_of(text, element.start()),
                "redundant-encoding",
                f"<{element.group(1)} class=\"{element.group(3)}\"> is painted with a status "
                "colour but carries no text, icon or label; colour must not carry meaning alone",
            )
        )
    return out


RE_CONTROL = re.compile(r"\b(?:button|\.btn|\[role=\"button\"\]|\.control|\.tab|\.chip-btn)\b")


def control_height(body: str) -> tuple[float, str] | None:
    """Static estimate of a control's rendered height, and how it was derived.

    An explicit height wins. Otherwise most controls in this corpus size by
    padding, so the estimate is vertical padding plus a line box; ignoring that
    case is what let the rule pass on every real button.
    """
    for dimension in ("min-height", "height"):
        match = re.search(rf"(?<![-\w]){dimension}:\s*([0-9.]+)px", body)
        if match:
            return float(match.group(1)), dimension

    padding = re.search(r"(?<![-\w])padding:\s*([^;}]+)", body)
    if not padding:
        return None
    values = [float(v) for v in RE_PX_VALUE.findall(padding.group(1))]
    if not values:
        return None
    vertical = values[0]  # 1-, 2- and 3-value forms all put the block edge first
    size_match = RE_FONT_SIZE.search(body)
    line_box = float(size_match.group(1)) * 1.4 if size_match else 16 * 1.4
    return 2 * vertical + line_box, "padding + line box"


def rule_control_target(path: Path, text: str) -> list[Violation]:
    """Interactive controls need a 44px target; 48 is the rung that clears it."""
    out = []
    for offset, css in stylesheets(text):
        for rule_match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
            selector, body = rule_match.group(1).strip(), rule_match.group(2)
            if not RE_CONTROL.search(selector):
                continue
            estimate = control_height(body)
            if estimate is None:
                continue
            height, basis = estimate
            if height < 44:
                out.append(
                    Violation(
                        path,
                        line_of(text, offset + rule_match.start()),
                        "control-target",
                        f"control {selector!r} is ~{height:g}px tall ({basis}), under the 44px "
                        f"target of WCAG 2.2 SC 2.5.5; use the {CONTROL_TARGET}px rung",
                    )
                )
    return out


RE_WEIGHT = re.compile(r"font-weight:\s*([0-9]+)")
RE_PRINT_BLOCK = re.compile(r"@media\s+print")


def rule_weight(path: Path, text: str) -> list[Violation]:
    """Only 400 and 700 render as written across platforms."""
    out = []
    for offset, css in stylesheets(text):
        for match in RE_WEIGHT.finditer(css):
            weight = int(match.group(1))
            if weight not in WEIGHTS:
                intended = "400" if weight < 600 else "700"
                out.append(
                    Violation(
                        path,
                        line_of(text, offset + match.start()),
                        "weight",
                        f"font-weight {weight} is not one of {WEIGHTS}; it renders as "
                        f"{intended} on most platforms. Change family or size for emphasis",
                    )
                )
    return out


def rule_inert_property(path: Path, text: str) -> list[Violation]:
    """Properties that thin stems on macOS only, or do nothing at all."""
    out = []
    for offset, css in stylesheets(text):
        for prop in INERT_PROPERTIES:
            for match in re.finditer(re.escape(prop) + r"\s*:", css):
                out.append(
                    Violation(
                        path,
                        line_of(text, offset + match.start()),
                        "inert-property",
                        f"{prop} thins stems on macOS only or is inert everywhere; remove it",
                    )
                )
    return out


def rule_print_block(path: Path, text: str) -> list[Violation]:
    """These documents get printed, and dark mode prints black without this."""
    if RE_PRINT_BLOCK.search(text):
        return []
    return [
        Violation(
            path,
            1,
            "print-block",
            "no @media print block; prefers-color-scheme is not suppressed for print, "
            "so a dark-mode reader exports a black page",
        )
    ]


def rule_serif_figures(path: Path, text: str) -> list[Violation]:
    """Digits set in the serif face jump 39% in width and cannot be corrected."""
    serif_classes: set[str] = set()
    for _, css in stylesheets(text):
        for rule_match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
            selector, body = rule_match.group(1), rule_match.group(2)
            refs = [r.group(1) for r in RE_VAR_REF.finditer(body)]
            if "font-family" not in body or not any(t in refs for t in SERIF_TOKENS):
                continue
            serif_classes.update(re.findall(r"\.([A-Za-z][\w-]*)", selector))
    if not serif_classes:
        return []

    out = []
    for element in re.finditer(
        r"<(\w+)[^>]*\bclass=\"([^\"]*)\"[^>]*>([^<]*)</\1>", text
    ):
        if not set(element.group(2).split()) & serif_classes:
            continue
        content = element.group(3).strip()
        if content and RE_FIGURE_ONLY.match(content):
            out.append(
                Violation(
                    path,
                    line_of(text, element.start()),
                    "serif-figures",
                    f"{content!r} is a figure set in the serif face, whose oldstyle digits "
                    "vary 39% in width with no lining or tabular alternate; use the data face",
                )
            )
    return out


RULES = {
    "type": rule_type,
    "weight": rule_weight,
    "inert-property": rule_inert_property,
    "print-block": rule_print_block,
    "serif-figures": rule_serif_figures,
    "body-floor": rule_body_floor,
    "spacing": rule_spacing,
    "radius": rule_radius,
    "width": rule_width,
    "colour-literal": rule_colour_literal,
    "svg-paint": rule_svg_paint,
    "dark-mode": rule_dark_mode,
    "contrast": rule_contrast,
    "redundant-encoding": rule_redundant_encoding,
    "control-target": rule_control_target,
}


def targets(paths: list[str]) -> list[Path]:
    if paths:
        return [Path(p).resolve() for p in paths]
    return sorted(REFERENCES.rglob("*.html"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="files to check (default: every reference file)")
    parser.add_argument("--rule", action="append", choices=sorted(RULES), help="run only this rule")
    parser.add_argument("--baseline", action="store_true", help="summary counts only, always exit 0")
    args = parser.parse_args()

    active = {name: RULES[name] for name in (args.rule or RULES)}
    files = targets(args.paths)
    if not files:
        print("no files to check", file=sys.stderr)
        return 1

    violations: list[Violation] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for check in active.values():
            violations.extend(check(path, text))

    if args.baseline:
        by_rule: dict[str, int] = {}
        by_file: dict[str, int] = {}
        for v in violations:
            by_rule[v.rule] = by_rule.get(v.rule, 0) + 1
            by_file[v.label] = by_file.get(v.label, 0) + 1
        print(f"{len(files)} files, {len(violations)} violations\n")
        print("by rule")
        for rule, count in sorted(by_rule.items(), key=lambda kv: -kv[1]):
            print(f"  {count:5d}  {rule}")
        print("\nby file")
        for name, count in sorted(by_file.items(), key=lambda kv: -kv[1]):
            print(f"  {count:5d}  {name}")
        return 0

    for v in sorted(violations, key=lambda v: (str(v.path), v.line, v.rule)):
        print(v.render())

    if violations:
        print(f"\n{len(violations)} violations across {len(files)} files", file=sys.stderr)
        return 1
    print(f"clean: {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
