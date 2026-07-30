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
    "--w-measure": 540,
    "--shell": 1100,
    "--shell-read": 808,
    "--shell-wide": 1320,
    "--w-steps": 320,
    "--w-pane": 840,
    "--w-card": 344,
    "--w-card-wide": 464,
}
# SC 2.5.8 Target Size (Minimum) is the AA floor at 24x24 CSS px, and AA is the
# conformance target throughout this style. SC 2.5.5's 44x44 is AAA; treat it as
# a recommendation for primary actions rather than a gate.
CONTROL_TARGET = 24

# Text roles must clear WCAG AA at body size. Ratios are against the mode's own
# --bg, which is why one shared muted pigment cannot serve both modes.
AA_BODY = 4.5
TEXT_ROLES = ("--ink", "--body", "--muted")

# Status colour never carries meaning alone; one of these must sit beside it.
REDUNDANT_ENCODING = re.compile(
    r"aria-label|role=\"img\"|<title>|↑|↓|→|▲|▼|&(?:uarr|darr|rarr);"
    # aria-hidden says the element carries no information, so there is no meaning
    # for colour to be carrying alone. Confetti is the case in point.
    r"|aria-hidden=\"true\""
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
# A leading "(" means this is a media-query breakpoint, which is a condition
# rather than a layout width and answers to the viewport, not the width set.
RE_MAX_WIDTH = re.compile(r"(?<!\()max-width:\s*([0-9.]+)px")
RE_RADIUS = re.compile(r"border-radius:\s*([^;}]+)")
# A dark mode is a styling construct, not a mention. Matching the bare string
# anywhere would pass on a file whose only reference is the theme-detection
# script's matchMedia('(prefers-color-scheme: dark)') call, with no dark styles
# at all — which is exactly the state of the 20 vendored files.
RE_DARK_SELECTOR = re.compile(
    r"(?:html|:root|body)\s*\.dark\b"
    r"|\.dark\s+(?:html|:root|body)\b"
    r"|\[data-theme\s*[~|^$*]?=\s*[\"']?dark"
    r"|@media[^{]*prefers-color-scheme\s*:\s*dark"
)
# The script that makes a class-keyed dark mode reachable.
RE_DARK_APPLY = re.compile(
    r"documentElement\.classList\.(?:toggle|add)\(\s*['\"]dark['\"]"
    r"|documentElement\.className\s*=[^;]*dark"
)
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


RE_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def blank_comments(css: str) -> str:
    """Replace comment bodies with spaces, preserving length and line breaks.

    Comments are prose about the CSS, so a hex code or a size named in one is not
    a declaration. Blanking rather than deleting keeps every offset intact, which
    the reported line numbers depend on.
    """
    return RE_CSS_COMMENT.sub(
        lambda m: "".join("\n" if c == "\n" else " " for c in m.group(0)), css
    )


def stylesheets(text: str) -> list[tuple[int, str]]:
    """Every <style> block as (offset, css), with comments blanked."""
    return [(m.start(1), blank_comments(m.group(1))) for m in RE_STYLE_BLOCK.finditer(text)]


RE_INLINE_STYLE = re.compile(r'style="([^"]*)"', re.IGNORECASE)


def styled_regions(text: str) -> list[tuple[int, str]]:
    """Every <style> block plus every inline style attribute.

    A `style="padding:14px"` is a declaration like any other, and it is the shape a
    model reaches for most often when generating a single file, so the value rules
    read it too. Each attribute arrives wrapped in a placeholder rule so the same
    selector-and-body regexes apply; the offset is backed up by the two characters
    the wrapper adds, which keeps `offset + match.start()` pointing at the real
    character in the file.

    The rules that resolve selectors — contrast, panel ancestry, status encoding —
    deliberately stay on `stylesheets()`: a placeholder selector names no element,
    so feeding it to them would invent surfaces and classes that do not exist.
    """
    regions = stylesheets(text)
    regions += [
        (m.start(1) - 2, "x{" + m.group(1) + "}") for m in RE_INLINE_STYLE.finditer(text)
    ]
    return regions


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
    """Custom properties declared under a given selector, later wins.

    The print block is removed first. It resets the role layer to light and names
    `html.dark` to do it, and it sits last in the file — so leaving it in would let
    the print values win the later-wins race and make every dark-mode measurement a
    second copy of the light one.
    """
    table: dict[str, str] = {}
    # Comments are blanked first. A comment that names a token and follows it with a
    # colon — "--positive-soft: that tint is solved against the page" — otherwise
    # reads as a declaration and silently redefines the role for every measurement.
    text = strip_print(blank_comments(text))
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
    for offset, css in styled_regions(text):
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
    for offset, css in styled_regions(text):
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
    for offset, css in styled_regions(text):
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
    for offset, css in styled_regions(text):
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


def strip_print(css: str) -> str:
    """CSS with @media print removed.

    The print block resets the role layer to light and names html.dark to do it,
    so leaving it in would let a file with no screen dark mode pass on its print
    reset alone.
    """
    out, index = [], 0
    for match in re.finditer(r"@media[^{]*\bprint\b[^{]*\{", css):
        if match.start() < index:
            continue
        out.append(css[index : match.start()])
        depth, i = 1, match.end()
        while depth and i < len(css):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        index = i
    out.append(css[index:])
    return "".join(out)


def rule_dark_mode(path: Path, text: str) -> list[Violation]:
    """Both modes are first-class, so a dark block has to exist and be reachable.

    Two halves, because either one alone is a dark mode that never appears. A
    `html.dark` block with nothing to put the class on renders as light forever;
    the whole corpus was in that state, styles present and unreachable.
    """
    out = []
    if not any(RE_DARK_SELECTOR.search(strip_print(css)) for _, css in stylesheets(text)):
        out.append(
            Violation(
                path,
                1,
                "dark-mode",
                "no dark-mode styles: needs an html.dark, [data-theme=dark] or "
                "prefers-color-scheme: dark block in the stylesheet",
            )
        )
    class_selector = bool(re.search(r"(?:html|:root|body)\s*\.dark\b", text))
    # Reachability only. Whether the setter runs before the first paint or inside a
    # click handler is a question about when the script executes, which reading the
    # source cannot answer without interpreting it — that half stays an instruction
    # in SKILL.md rather than a rule that would pass on the wrong shape.
    if class_selector and not RE_DARK_APPLY.search(text):
        out.append(
            Violation(
                path,
                1,
                "dark-mode",
                "dark styles are keyed on a class that nothing sets: needs a script "
                "putting 'dark' on documentElement",
            )
        )
    return out


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


# A surface that carries its own text is declared, not inferred. Only these tokens
# mark one; inferring it from "darker than the page" catches a 12px accent dot
# whose labels are positioned outside it, and an accent button whose siblings sit
# on the page. Two kinds qualify: a panel, which holds one colour in both modes,
# and an inverted band, which flips with the page. Either way the text inside
# answers to the surface.
PANEL_TOKENS = (
    "--panel", "--panel-raised", "--slate", "--gray-700", "--ink", "--invert",
)


def panel_surfaces(css: str, table: dict[str, str]) -> dict[str, tuple[str, tuple[int, int, int]]]:
    """Class -> background colour, for every rule that paints an always-dark panel.

    A code listing holds its own colour, so text inside it answers to that panel
    and not to the page. Without this a correct pale-on-dark colour reads as a
    failure, and dark-on-dark reads as passing because it was compared to ivory.
    """
    out: dict[str, tuple[str, tuple[int, int, int]]] = {}
    for rule_match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        bg_decl = RE_BG_DECL.search(rule_match.group(2))
        if not bg_decl:
            continue
        if not any(f"var({name})" in bg_decl.group(1) for name in PANEL_TOKENS):
            continue
        colour = literal_colour(bg_decl.group(1), table)
        if not colour:
            continue
        # Only the last compound is painted. `.es-b .btn { background: accent }`
        # paints the button, and reading `.es-b` as an accent panel makes every
        # paragraph inside it look like body text on a solid orange block.
        for part in rule_match.group(1).split(","):
            last = re.split(r"[\s>+~]+", part.strip())[-1]
            for cls in re.findall(r"\.([a-zA-Z][\w-]*)", last):
                out.setdefault(cls, colour)
            tag = re.match(r"([a-z][a-z0-9]*)", last)
            if tag:
                out.setdefault(tag.group(1), colour)
    return out


def enclosing_surface(
    selector: str, panels: dict[str, tuple[str, tuple[int, int, int]]]
) -> tuple[str, tuple[int, int, int]] | None:
    """The surface a selector's target sits on, when an ancestor names one.

    A panel counts as an ancestor in two shapes only: a hyphenated child of its
    name (`.diff-row` sits inside `.diff`), or the name itself in a compound
    before the last one (`.diff .code`). The exclusion matters — `.chip.active`
    paints a selected chip dark, and reading that as a panel would measure every
    other `.chip` rule against it.
    """
    best: tuple[int, tuple[str, tuple[int, int, int]]] | None = None
    for part in selector.split(","):
        compounds = re.split(r"[\s>+~]+", part.strip())
        for position, compound in enumerate(compounds):
            is_last = position == len(compounds) - 1
            names = re.findall(r"\.([a-zA-Z][\w-]*)", compound)
            tag = re.match(r"([a-z][a-z0-9]*)", compound)
            if tag:
                names.append(tag.group(1))
            for cls in names:
                for panel, colour in panels.items():
                    child = cls.startswith(panel + "-")
                    ancestor = cls == panel and not is_last
                    if not (child or ancestor):
                        continue
                    if best is None or len(panel) > best[0]:
                        best = (len(panel), colour)
    return best[1] if best else None


def rule_contrast(path: Path, text: str) -> list[Violation]:
    """Every text colour must clear AA against the surface it sits on.

    Naming-agnostic on purpose: the corpus files paint text with pigment names
    (--gray-500) while the authored files use role names (--muted), and the same
    failing pigment has to be caught either way. The surface is the block's own
    background if it sets one, then an enclosing panel's, then the page.
    """
    out: list[Violation] = []
    light = declared_tokens(text, ":root")
    dark = dict(light)
    dark_overrides = declared_tokens(text, "html.dark")
    dark.update(dark_overrides)

    modes = [("light", light)]
    if dark_overrides:
        modes.append(("dark", dark))

    panels = {mode: {} for mode, _ in modes}
    for _, css in stylesheets(text):
        for mode, table in modes:
            panels[mode].update(panel_surfaces(css, table))

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
                panel_bg = enclosing_surface(selector, panels[mode])
                known = own_bg is not None or panel_bg is not None
                if own_bg is not None:
                    surface = own_bg
                elif panel_bg is not None:
                    surface = panel_bg
                else:
                    surface = page_bg
                fg = literal_colour(colour_decl.group(1), table)
                if not fg or not surface:
                    continue
                # With no surface named by this block or an ancestor, a colour
                # lighter than the page sits on something a sibling rule paints
                # (.chip and .chip.critical), and measuring against the page
                # would invent a failure.
                if not known and luminance(fg[1]) >= luminance(surface[1]):
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


RE_CONTROL = re.compile(
    r"(?:\bbutton\b|\bselect\b|\bsummary\b|\binput\b|\btextarea\b"
    r"|\[role=[\"']?button|\.btn\b|\.chip\b|\.pill\b|\.control\b|\.tab\b|\.toggle\b)"
)
RE_SLIDER_THUMB = re.compile(r"::(?:-webkit-slider-thumb|-moz-range-thumb)")


ROOT_FONT_PX = 16.0


def lengths_in(value: str, tokens: dict[str, str]) -> list[float]:
    """Every length in a declaration value, in px, resolving var() first.

    Controls are sized with tokens, so a reader that only understands px
    literals measures nothing at all.
    """
    resolved = value
    for ref in RE_VAR_REF.finditer(value):
        literal = resolve(ref.group(1), tokens)
        if literal is None and ref.group(2):
            literal = ref.group(2).strip()
        if literal is not None:
            resolved = resolved.replace(ref.group(0), literal)
    out = [float(v) for v in RE_PX_VALUE.findall(resolved)]
    out += [float(v) * ROOT_FONT_PX for v in re.findall(r"(-?[0-9.]+)rem", resolved)]
    return out


def control_height(body: str, tokens: dict[str, str]) -> tuple[float, str] | None:
    """Static estimate of a control's rendered height, and how it was derived.

    An explicit height wins. Otherwise the height comes from vertical padding
    plus a line box, which is how almost every control here is sized — very few
    declare a height at all.
    """
    for dimension in ("min-height", "height"):
        match = re.search(rf"(?<![-\w]){dimension}:\s*([^;}}]+)", body)
        if match:
            values = lengths_in(match.group(1), tokens)
            if values:
                return values[0], dimension

    padding = re.search(r"(?<![-\w])padding:\s*([^;}]+)", body)
    if not padding:
        return None
    values = lengths_in(padding.group(1), tokens)
    if not values:
        return None
    vertical = values[0]  # 1-, 2- and 3-value forms all put the block edge first
    size_match = re.search(r"font-size:\s*([^;}]+)", body)
    sizes = lengths_in(size_match.group(1), tokens) if size_match else []
    line_box = (sizes[0] if sizes else ROOT_FONT_PX) * 1.4
    return 2 * vertical + line_box, "padding + line box"


RE_LABEL_CLASS = re.compile(r"<label[^>]*\bclass=\"([^\"]+)\"", re.IGNORECASE)
RE_LABEL_FOR = re.compile(r"<label[^>]*\bfor=\"([^\"]+)\"", re.IGNORECASE)
RE_FIELD_TAG = re.compile(
    r"<input\b[^>]*type=\"(checkbox|radio)\"[^>]*>|<input\b(?![^>]*\btype=)[^>]*>",
    re.IGNORECASE,
)
RE_ID_ATTR = re.compile(r"\bid=\"([^\"]+)\"")
# Markup that makes an element a hit target. A class name does not: this corpus
# uses .chip for legend swatches and for buttons, and only the HTML says which.
RE_INTERACTIVE_TAG = re.compile(
    # A label is a hit target too: clicking one activates the field it names.
    r"<(?:button|summary|label|a\b[^>]*\bhref)\b[^>]*\bclass=\"([^\"]+)\""
    r"|<[a-z][a-z0-9]*[^>]*(?:\brole=\"button\"|\btabindex=|\bonclick=)[^>]*"
    r"\bclass=\"([^\"]+)\"",
    re.IGNORECASE,
)


def interactive_classes(text: str) -> set[str]:
    """Classes the markup puts on something clickable or focusable."""
    found: set[str] = set()
    for match in RE_INTERACTIVE_TAG.finditer(text):
        for group in match.groups():
            if group:
                found.update(group.split())
    return found


def every_field_is_labelled(text: str) -> bool:
    """True when each checkbox and radio has a label, wrapping it or pointing at it.

    A labelled checkbox's target is the label, which is why a 17px box is not a
    failure. Both shapes count: nested inside a <label>, and a sibling
    <label for> naming its id.
    """
    ids = set(RE_LABEL_FOR.findall(text))
    for match in RE_FIELD_TAG.finditer(text):
        tag = match.group(0)
        own_id = RE_ID_ATTR.search(tag)
        if own_id and own_id.group(1) in ids:
            continue
        before = text[: match.start()]
        if before.rfind("<label") > before.rfind("</label>"):
            continue
        return False
    return True
RE_FORM_FIELD = re.compile(r"^(?:input|textarea)\b")
# A real control element, whose interactivity is not in question.
RE_TAG_CONTROL = re.compile(r"^(?:button|select|summary)\b")


def label_classes(text: str) -> set[str]:
    """Every class that appears on a <label> element in the document."""
    return {cls for m in RE_LABEL_CLASS.finditer(text) for cls in m.group(1).split()}


def wraps_field(compound: str, labels: set[str]) -> bool:
    """True when this selector compound targets a <label>.

    The tag and the classes are read separately, so `label.row` counts on its tag
    and `.checkbox` counts on a class the document puts on a label.
    """
    tag, _, classes = compound.partition(".")
    if tag == "label":
        return True
    return any(cls in labels for cls in classes.split(".") if cls)


def is_control_selector(selector: str, text: str) -> bool:
    """True when the selector's own target is a control, not something inside one.

    Only the last compound counts. `.chip .dot` styles a decorative dot inside a
    chip and `.toggle .track::after` styles a thumb; neither is the hit target,
    and measuring them reports the control as too small when it is not.

    A checkbox or radio inside its own <label> is the exception: clicking the
    label activates the field, so the target is the label's box and the field's
    own 16px square is not the measurement. The wrapper is usually written as a
    class, so whether it is a label is a fact about the HTML, not the selector.

    Scope limit: the class-to-label lookup is document-wide, so a file that uses
    one class on a <label> in one component and on a <div> in another exempts
    both. Narrowing that needs real DOM matching.
    """
    labels = None
    interactive = None
    for part in selector.split(","):
        compounds = re.split(r"[\s>+~]+", part.strip())
        last = compounds[-1]
        if RE_SLIDER_THUMB.search(last):
            return True  # the thumb is the slider's target, so it is measured
        if "::" in last:
            continue
        if not RE_CONTROL.search(last):
            continue
        if RE_FORM_FIELD.match(last):
            if "range" in last:
                continue  # the track is not the target; the thumb rule is measured
            if labels is None:
                labels = label_classes(text)
            if any(wraps_field(a, labels) for a in compounds[:-1]):
                continue
            if every_field_is_labelled(text):
                continue
        elif not RE_TAG_CONTROL.match(last):
            # A class-named control has to be interactive in the markup.
            if interactive is None:
                interactive = interactive_classes(text)
            classes = re.findall(r"\.([a-zA-Z][\w-]*)", last)
            if not any(c in interactive for c in classes):
                continue
        return True
    return False


def rule_control_target(path: Path, text: str) -> list[Violation]:
    """Interactive controls need to clear the AA target-size floor."""
    tokens = declared_tokens(text, ":root")
    out = []
    for offset, css in stylesheets(text):
        for rule_match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
            selector, body = rule_match.group(1).strip(), rule_match.group(2)
            if not is_control_selector(selector, text):
                continue
            estimate = control_height(body, tokens)
            if estimate is None:
                continue
            height, basis = estimate
            if height < CONTROL_TARGET:
                out.append(
                    Violation(
                        path,
                        line_of(text, offset + rule_match.start()),
                        "control-target",
                        f"control {selector!r} is ~{height:g}px tall ({basis}), under the "
                        f"{CONTROL_TARGET}px AA floor of WCAG 2.2 SC 2.5.8",
                    )
                )
    return out


RE_WEIGHT = re.compile(r"font-weight:\s*([0-9]+)")
RE_PRINT_BLOCK = re.compile(r"@media\s+print")


def rule_weight(path: Path, text: str) -> list[Violation]:
    """Only 400 and 700 render as written across platforms."""
    out = []
    for offset, css in styled_regions(text):
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
    for offset, css in styled_regions(text):
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
    """Digits set in the serif face jump 39% in width and cannot be corrected.

    Scope limit: an element is only checked when it carries the serif-styled
    class itself. A descendant selector such as `.bar h1` is not resolved, since
    that needs real DOM matching. The shape this rule exists to catch — a stat
    tile's number — names its own class in practice, so the gap is narrow rather
    than absent.
    """
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


# A var() with no fallback and no declaration is invalid at computed-value time, so
# the property falls back to inherited or initial rather than erroring. That is
# silent for a margin and catastrophic for a background: the corpus had a card
# painted with an undeclared token, which left the surface unpainted and its own
# ink invisible against the page.
RE_VAR_NO_FALLBACK = re.compile(r"var\(\s*(--[a-z0-9-]+)\s*\)")
RE_CUSTOM_DECL = re.compile(r"(--[a-z0-9-]+)\s*:")


def rule_undefined_token(path: Path, text: str) -> list[Violation]:
    """Every token a document reaches for has to be declared in that document."""
    declared = set(RE_CUSTOM_DECL.findall(blank_comments(text)))
    out = []
    for offset, css in styled_regions(text):
        for match in RE_VAR_NO_FALLBACK.finditer(css):
            if match.group(1) in declared:
                continue
            out.append(Violation(path, line_of(text, offset + match.start()), "undefined-token",
                f"{match.group(1)} is used but never declared: the property resolves to "
                f"inherited or initial, not to a value"))
    return out


RULES = {
    "undefined-token": rule_undefined_token,
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


# A shared fragment is a piece of a document, not a document. It has no <style>
# block, no body and no dark-mode block of its own, so every whole-file rule reads
# it as broken.
FRAGMENTS = ("house-style-theme.html",)


def targets(paths: list[str]) -> list[Path]:
    if paths:
        return [Path(p).resolve() for p in paths]
    return sorted(p for p in REFERENCES.rglob("*.html") if p.name not in FRAGMENTS)


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
