#!/usr/bin/env python3
"""Move a vendored reference file onto the house style token block.

The 21 vendored files declare the same handful of pigment names, so the palette
move is mechanical — but only per property. `--gray-500` is one name doing two
jobs: 154 uses paint text, where it measures 3.47:1 and fails WCAG AA, and 18
paint borders and fills, where it is fine. A name-for-name substitution either
leaves the failure in place or repaints every border. The property says which
job a use is doing, so the property drives the mapping.

Anything the table cannot place is reported and left alone. A colour this script
guesses at is a colour nobody checks, and one wrong guess lands in 19 files at
once.

Usage:
    tools/remap-palette.py path/to/file.html          # report only
    tools/remap-palette.py --apply path/to/file.html  # rewrite in place
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOKENS = REPO / "skills" / "effective-html" / "references" / "house-style-tokens.css"

# Which job a declaration is doing. A pigment's replacement depends on this and
# not on the pigment's name.
PROPERTY_CLASS = {
    "color": "text",
    "background": "surface",
    "background-color": "surface",
    "border-color": "edge",
    "border-top-color": "edge",
    "border-right-color": "edge",
    "border-bottom-color": "edge",
    "border-left-color": "edge",
    "outline-color": "edge",
    "border": "edge",
    "border-top": "edge",
    "border-right": "edge",
    "border-bottom": "edge",
    "border-left": "edge",
    "border-inline": "edge",
    "border-inline-start": "edge",
    "border-inline-end": "edge",
    "border-block": "edge",
    "border-block-start": "edge",
    "border-block-end": "edge",
    "outline": "edge",
    "fill": "mark",
    "stroke": "mark",
    # A checkbox tint and a caret are foreground UI colour, not chart paint, so
    # they follow the text mapping and a series pigment is never asked for.
    "accent-color": "text",
    "caret-color": "text",
    "text-decoration-color": "text",
    "stop-color": "mark",
    "flood-color": "mark",
    # A shadow and an underline are non-text objects that carry a colour.
    "box-shadow": "mark",
    "text-shadow": "mark",
    "text-decoration": "text",
}

# (legacy pigment, job) -> role token. Roles are mode-aware, so writing the role
# name here is what gives these files a dark mode in the next step.
#
# Deliberately incomplete. A missing cell means "report it", not "pass it
# through": `--gray-700` as a surface is a dark panel and `--gray-300` as text
# would be unreadable, and neither has an answer that holds across 21 files.
ROLE_MAP: dict[tuple[str, str], str] = {
    # A role token selects a different pigment per mode, which is right for the
    # page and wrong for anything that is one fixed colour by design. Light text
    # on a coloured badge stays light in both modes, and an always-dark code
    # panel stays dark, so these keep a reference pigment and do not flip.
    ("--ivory", "text"): "--ivory",
    ("--ivory", "edge"): "--surface",
    ("--ivory", "surface"): "--bg",
    ("--ivory", "mark"): "--bg",
    ("--white", "text"): "--white",
    ("--white", "surface"): "--surface",
    ("--white", "edge"): "--surface",
    ("--white", "mark"): "--surface",
    ("--slate", "text"): "--ink",
    ("--slate", "surface"): "--panel",
    # A near-black border on a light card is a selected or focused outline, and
    # --ink flips the way that outline should: dark on light, light on dark.
    ("--slate", "edge"): "--ink",
    ("--slate", "mark"): "--ink",
    # These pale pigments are only ever text when they sit on something dark, so
    # they keep a fixed value instead of following the mode.
    ("--oat", "text"): "--oat",
    ("--oat", "surface"): "--oat",
    ("--oat", "edge"): "--line",
    ("--oat", "mark"): "--oat",
    ("--gray-700", "text"): "--body",
    ("--gray-700", "surface"): "--panel-raised",
    ("--gray-700", "edge"): "--line-strong",
    ("--gray-700", "mark"): "--body",
    ("--gray-800", "text"): "--body",
    ("--gray-800", "surface"): "--panel-raised",
    ("--gray-800", "edge"): "--line-strong",
    ("--gray-800", "mark"): "--body",
    # The 3.47:1 failure and the legitimate border use, told apart by property.
    ("--gray-500", "text"): "--muted",
    ("--gray-500", "surface"): "--fill",
    ("--gray-500", "edge"): "--fill",
    ("--gray-500", "mark"): "--fill",
    ("--gray-300", "text"): "--panel-body",
    ("--gray-300", "surface"): "--wash",
    ("--gray-300", "edge"): "--line",
    ("--gray-300", "mark"): "--line",
    ("--gray-200", "text"): "--panel-body",
    ("--gray-200", "surface"): "--wash",
    ("--gray-200", "edge"): "--line",
    ("--gray-200", "mark"): "--line",
    ("--gray-150", "text"): "--panel-ink",
    ("--gray-150", "surface"): "--wash",
    ("--gray-150", "edge"): "--line",
    ("--gray-150", "mark"): "--wash",
    ("--gray-100", "text"): "--panel-ink",
    ("--gray-100", "surface"): "--wash",
    ("--gray-100", "edge"): "--line",
    ("--gray-100", "mark"): "--wash",
    ("--gray-50", "text"): "--panel-ink",
    ("--gray-50", "surface"): "--wash",
    ("--gray-50", "edge"): "--line",
    ("--gray-50", "mark"): "--wash",
    # Old clay is 2.96:1 and fails even the large-text floor; the new pigment
    # behind --accent is 6.35:1, so the same name is safe as text now.
    ("--clay", "text"): "--accent",
    ("--clay", "surface"): "--accent",
    ("--clay", "edge"): "--accent",
    ("--clay", "mark"): "--accent",
    ("--clay-d", "text"): "--accent",
    ("--clay-d", "surface"): "--accent",
    ("--clay-d", "edge"): "--accent",
    # Olive was the success role at 3.49:1. Positive is blue at 6.38:1. Status
    # uses map; a chart series painted olive does not, because repainting a
    # series is a decision about the figure and not about the pigment.
    ("--olive", "text"): "--positive",
    ("--olive", "surface"): "--positive",
    ("--olive", "edge"): "--positive",
    # A flow arrow painted for pass or fail is status, not a chart series, and a
    # stroke is a non-text object, so it takes the mark step.
    ("--olive", "mark"): "--positive-mark",
    ("--rust", "text"): "--critical",
    ("--rust", "surface"): "--critical",
    ("--rust", "edge"): "--critical",
    ("--rust", "mark"): "--critical-mark",
    ("--clay-d", "mark"): "--accent-mark",
}

# A changed pigment written as a tint becomes the role's tinted-surface step, by
# property: a fill takes -soft and a border takes -line. Both are opaque steps, so
# what they measure no longer depends on whatever sits behind them.
TINT_ROLE = {
    (217, 119, 87): "accent",
    (184, 92, 62): "accent",
    (120, 140, 93): "positive",
    (176, 74, 63): "critical",
    (176, 74, 74): "critical",
    (199, 142, 63): "warning",
    (92, 124, 163): "positive",
}
# An underline or decoration drawn in a tinted role reads as a border, not a fill.
TINT_SUFFIX = {"surface": "soft", "edge": "line", "mark": "soft", "text": "line"}
# Neutral tints have a token each; the second is for a row band inside a panel
# that stays dark in both modes, where --zone would invert.
NEUTRAL_TINT = {(20, 20, 19): "--zone", (255, 255, 255): "--panel-zone",
                (250, 249, 245): "--panel-zone", (0, 0, 0): "--scrim",
                (227, 218, 204): "--wash"}

# Legacy names that are not pigments. Values, not roles, so the file's own CSS
# keeps resolving without a second pass.
ALIAS_TAIL = {
    "--serif": "var(--font-display)",
    "--sans": "var(--font-prose)",
    "--mono": "var(--font-data)",
    "--radius-panel": "var(--r-12)",
    "--radius-row": "var(--r-8)",
    "--radius-chip": "var(--r-full)",
    "--border": "1px solid var(--line)",
    "--card-border": "1px solid var(--line)",
    "--card-pad": "var(--sp-20)",
    "--card-shadow": "var(--shadow-card)",
}

RE_ROOT = re.compile(r"(?P<indent>[ \t]*):root\s*\{.*?\n\s*\}\n", re.DOTALL)
# The excluded "*" is what keeps a value from running into the next declaration
# through a comment: ":root" is preceded by "/* -- role: light --- */", and
# "role:" followed by anything up to the next var() would otherwise match.
RE_DECL_WITH_VAR = re.compile(
    r"(?P<prop>-{0,2}[a-z][a-z0-9-]*)\s*:\s*(?P<value>[^;{}*]*var\(\s*--[a-z0-9-]+[^;{}*]*)"
)
RE_ONE_VAR = re.compile(r"var\(\s*(--[a-z0-9-]+)\s*(?:,[^()]*)?\)")
RE_STYLE_BLOCK = re.compile(r"(<style[^>]*>)(.*?)(</style>)", re.DOTALL | re.IGNORECASE)
RE_SVG_PAINT = re.compile(r"\b(fill|stroke|stop-color|flood-color)=\"(#[0-9a-fA-F]{3,8})\"")
# Reference pigments dark enough that text on them has to stay light. A rule
# painting one of these is an island: it holds its colour in both modes, so a
# role token used for text inside it flips underneath and the contrast inverts.
DARK_SURFACES = {"--panel", "--panel-raised", "--slate", "--gray-700"}
# The mode-aware role, and the fixed-colour one that replaces it on a panel.
PANEL_TEXT = {
    "--ink": "--panel-ink",
    "--body": "--panel-body",
    "--muted": "--panel-muted",
    "--fill": "--panel-muted",
}
RE_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")

# Tokens a one-off pigment may snap to, per job. The corpus holds 24 pale
# variations that appear once or twice each — hand-picked shades of the old
# palette — and enumerating them by value would be a table nobody can check.
# Snapping to the nearest listed token instead keeps the choice inside the closed
# set, and every snap is reported so the diff can be read.
SNAP_CANDIDATES = {
    "text": ("--ink", "--body", "--muted", "--panel-ink", "--panel-body",
             "--panel-muted", "--critical", "--warning", "--positive", "--accent"),
    "surface": ("--bg", "--surface", "--wash", "--oat", "--panel", "--panel-raised",
                "--critical-soft", "--warning-soft", "--positive-soft", "--accent-soft"),
    "edge": ("--line", "--line-strong", "--fill", "--critical-line", "--warning-line",
             "--positive-line", "--accent-line"),
    "mark": ("--s1", "--s2", "--s3", "--s4", "--s5", "--fill", "--critical-mark",
             "--warning-mark", "--positive-mark", "--accent-mark"),
}

RE_INLINE_STYLE = re.compile(r'(style=")([^"]*#[0-9a-fA-F]{3,8}[^"]*)"')
RE_RGBA = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)[^)]*\)")

# Pigments whose value changed, written as an rgba tint. A tint is unreachable by
# any var() rewrite, so a file keeps its old olive chip background while the text
# on it becomes blue. Reported rather than converted: the tinted surface needs a
# closed set of soft tokens that clears AA in both modes, and two of the eight
# candidates do not — warning text on its own 0.10 tint measures 4.26:1 and dark
# accent on its 0.16 tint measures 3.32:1. Guessing here paints 19 files wrong.
CHANGED_PIGMENT_RGB = {
    (217, 119, 87): "clay #D97757 -> #994210",
    (184, 92, 62): "clay-d #B85C3E -> #994210",
    (120, 140, 93): "olive #788C5D -> blue #2757b6",
    (176, 74, 63): "rust #B04A3F -> #971a20",
    (176, 74, 74): "danger #B04A4A -> #971a20",
    (199, 142, 63): "warning #C78E3F -> #896a00",
    (92, 124, 163): "info #5C7CA3 -> #2757b6",
}

LEGACY_PIGMENTS = {token for token, _ in ROLE_MAP}
BEGIN_MARKER = "/* @house-style-tokens:begin"
END_MARKER = "/* @house-style-tokens:end */"

# The same pigments written as literals rather than as var(). A file's own hex is
# what breaks its dark mode: `background: #fff` stays white while the text on it
# becomes light, which measures 1.2:1. Resolving the literal to a name lets the
# property table above do the rest of the work.
HEX_TO_LEGACY = {
    "#faf9f5": "--ivory",
    "#ffffff": "--white",
    "#fff": "--white",
    "#141413": "--slate",
    "#e3dacc": "--oat",
    "#f0eee6": "--gray-100",
    "#d1cfc5": "--gray-300",
    "#87867f": "--gray-500",
    "#3d3d3a": "--gray-700",
    "#d97757": "--clay",
    "#b85c3e": "--clay-d",
    "#788c5d": "--olive",
    "#b04a3f": "--rust",
    "#b04a4a": "--rust",
}

RE_HEX_DECL = re.compile(
    r"(?P<prop>-{0,2}[a-z][a-z0-9-]*)\s*:\s*(?P<value>[^;{}*]*#[0-9a-fA-F]{3,8}[^;{}*]*)"
)
RE_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


@dataclass
class Skipped:
    line: int
    kind: str
    detail: str


def canonical_block(indent: str) -> str:
    """The house style token block, indented to sit where :root was."""
    body = TOKENS.read_text(encoding="utf-8").rstrip("\n")
    return "\n".join(indent + line if line.strip() else line for line in body.split("\n"))


def alias_block(declared: dict[str, str], indent: str) -> str:
    """A :root tail aliasing the legacy names this file actually declares."""
    kept = [(name, ALIAS_TAIL[name]) for name in declared if name in ALIAS_TAIL]
    if not kept:
        return ""
    lines = [
        f"{indent}/* Legacy names this file's own CSS still resolves, pointed at the",
        f"{indent}   token block above so there is one source for every value. */",
        f"{indent}:root {{",
    ]
    lines += [f"{indent}  {name}: {value};" for name, value in kept]
    lines.append(f"{indent}}}")
    return "\n".join(lines) + "\n"


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def to_oklab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """OKLab, so "nearest colour" means nearest to the eye rather than in sRGB."""
    r, g, b = (
        c / 12.92 if (c := v / 255) <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        for v in rgb
    )
    lms = (
        0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b,
        0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b,
        0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b,
    )
    l_, m_, s_ = (v ** (1 / 3) for v in lms)
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def parse_hex(value: str) -> tuple[int, int, int] | None:
    digits = value.lstrip("#")
    if len(digits) in (3, 4):
        digits = "".join(c * 2 for c in digits[:3])
    if len(digits) not in (6, 8):
        return None
    try:
        return tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None


_SNAP_TABLE: dict[str, tuple[str, tuple[int, int, int]]] | None = None


def snap_table() -> dict[str, tuple[str, tuple[int, int, int]]]:
    """Each snap candidate resolved to a light-mode literal, read from the block."""
    global _SNAP_TABLE
    if _SNAP_TABLE is not None:
        return _SNAP_TABLE
    css = re.sub(r"/\*.*?\*/", "", TOKENS.read_text(encoding="utf-8"), flags=re.DOTALL)
    root = css[css.index(":root") : css.index("html.dark")]
    declared = dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+)", root))

    def literal(name: str, seen: frozenset[str] = frozenset()) -> str | None:
        if name in seen or name not in declared:
            return None
        value = declared[name].strip()
        ref = RE_ONE_VAR.search(value)
        return literal(ref.group(1), seen | {name}) if ref else value

    table: dict[str, tuple[str, tuple[int, int, int]]] = {}
    for names in SNAP_CANDIDATES.values():
        for name in names:
            value = literal(name)
            rgb = parse_hex(value) if value else None
            if rgb:
                table[name] = (value, rgb)
    _SNAP_TABLE = table
    return table


# Past this OKLab distance the nearest token is a different colour, not the same
# one written by hand. The corpus's one-off pales sit at a median of 3.4; what
# lands beyond the ceiling is a swatch or a semantic fill that needs a person.
SNAP_CEILING = 10.0


def snap(literal: str, job: str | None) -> tuple[str, float] | None:
    """The nearest token for this job, with the OKLab distance it snapped across."""
    rgb = parse_hex(literal)
    if rgb is None or job is None:
        return None
    table = snap_table()
    target = to_oklab(rgb)
    best: tuple[str, float] | None = None
    for name in SNAP_CANDIDATES.get(job, ()):
        entry = table.get(name)
        if entry is None:
            continue
        candidate = to_oklab(entry[1])
        distance = sum((target[i] - candidate[i]) ** 2 for i in range(3)) ** 0.5 * 100
        if best is None or distance < best[1]:
            best = (name, distance)
    return best if best and best[1] <= SNAP_CEILING else None


def in_comment(css: str, index: int) -> bool:
    """True when this offset sits inside a CSS comment.

    Comments hold prose about the CSS, and this file's own token block explains
    which pigment a role selects, so a hex or a property name written in one is
    not a declaration to rewrite.
    """
    opened = css.rfind("/*", 0, index)
    return opened != -1 and css.rfind("*/", 0, index) < opened


def role_for(token: str, job: str | None) -> str | None:
    """The role token that replaces a legacy pigment doing this job."""
    return None if job is None else ROLE_MAP.get((token, job))


def remap_hex(css: str, offset: int, text: str) -> tuple[str, list[Skipped], int]:
    """Rewrite hex literals that name a known pigment, by property."""
    skipped: list[Skipped] = []
    changed = 0

    def replace_decl(match: re.Match[str]) -> str:
        nonlocal changed
        prop = match.group("prop")
        if prop.startswith("--") or in_comment(css, match.start()):
            return match.group(0)  # the reference layer, which is where literals belong
        job = PROPERTY_CLASS.get(prop)
        line = line_of(text, offset + match.start())

        def replace_hex(ref: re.Match[str]) -> str:
            nonlocal changed
            literal = ref.group(0)
            token = HEX_TO_LEGACY.get(literal.lower())
            if token is None:
                nearest = snap(literal, job)
                if nearest is None:
                    skipped.append(Skipped(line, "unknown-pigment",
                                           f"{prop}: {literal} — not a palette pigment"))
                    return literal
                changed += 1
                skipped.append(Skipped(line, "snapped",
                                       f"{prop}: {literal} -> var({nearest[0]}), "
                                       f"OKLab {nearest[1]:.1f} away"))
                return f"var({nearest[0]})"
            role = role_for(token, job)
            if role is None:
                skipped.append(Skipped(line, "needs-judgement",
                                       f"{prop}: {literal} ({token}) as a {job or 'unknown job'} "
                                       f"has no mapping"))
                return literal
            changed += 1
            return f"var({role})"

        head, _, tail = match.group(0).partition(":")
        return head + ":" + RE_HEX.sub(replace_hex, tail)

    return RE_HEX_DECL.sub(replace_decl, css), skipped, changed


def remap_declarations(css: str, offset: int, text: str) -> tuple[str, list[Skipped], int]:
    """Rewrite every legacy pigment reference the table can place."""
    skipped: list[Skipped] = []
    changed = 0

    def replace_decl(match: re.Match[str]) -> str:
        nonlocal changed
        prop = match.group("prop")
        value = match.group("value")
        if prop.startswith("--") or in_comment(css, match.start()):
            return match.group(0)  # a custom property's own value, handled by the alias tail
        job = PROPERTY_CLASS.get(prop)

        def replace_var(ref: re.Match[str]) -> str:
            nonlocal changed
            token = ref.group(1)
            if token not in LEGACY_PIGMENTS:
                return ref.group(0)
            if job is None:
                skipped.append(
                    Skipped(
                        line_of(text, offset + match.start()),
                        "unknown-property",
                        f"{prop}: var({token}) — no job for this property",
                    )
                )
                return ref.group(0)
            role = ROLE_MAP.get((token, job))
            if role is None:
                skipped.append(
                    Skipped(
                        line_of(text, offset + match.start()),
                        "needs-judgement",
                        f"{prop}: var({token}) — {token} as a {job} has no mapping",
                    )
                )
                return ref.group(0)
            changed += 1
            return f"var({role})"

        return f"{prop}:{match.group(0).split(':', 1)[1].replace(value, RE_ONE_VAR.sub(replace_var, value))}"

    return RE_DECL_WITH_VAR.sub(replace_decl, css), skipped, changed


def declared_root_tokens(block: str) -> dict[str, str]:
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"(--[a-z0-9-]+)\s*:\s*([^;]+)", block)}


def remap(path: Path) -> tuple[str, list[Skipped], int]:
    text = path.read_text(encoding="utf-8")

    # Re-running refreshes the block rather than stacking a second copy, which is
    # what makes it safe to change a token and sweep every file again.
    if BEGIN_MARKER in text:
        start = text.index(BEGIN_MARKER)
        end = text.index(END_MARKER, start) + len(END_MARKER)
        indent = text[: start].rpartition("\n")[2]
        text = text[: start - len(indent)] + canonical_block(indent) + text[end:]
    else:
        root = RE_ROOT.search(text)
        if not root:
            raise SystemExit(f"{path}: no :root block to replace")
        indent = root.group("indent")
        declared = declared_root_tokens(root.group(0))
        replacement = canonical_block(indent) + "\n\n" + alias_block(declared, indent)
        text = text[: root.start()] + replacement + text[root.end() :]

    skipped: list[Skipped] = []
    changed = 0
    out: list[str] = []
    cursor = 0
    for style in RE_STYLE_BLOCK.finditer(text):
        css, offset = style.group(2), style.start(2)
        rewritten, var_skipped, var_changed = remap_declarations(css, offset, text)
        rewritten, hex_skipped, hex_changed = remap_hex(rewritten, offset, text)
        skipped += var_skipped + hex_skipped
        changed += var_changed + hex_changed
        out.append(text[cursor : style.start(2)])
        out.append(rewritten)
        cursor = style.end(2)
    out.append(text[cursor:])
    text = "".join(out)

    # An inline style attribute is a declaration list, so the same table applies.
    def replace_inline(match: re.Match[str]) -> str:
        nonlocal changed
        rewritten, inline_skipped, inline_changed = remap_hex(
            match.group(2), match.start(2), text
        )
        skipped.extend(inline_skipped)
        changed += inline_changed
        return f'{match.group(1)}{rewritten}"'

    text = RE_INLINE_STYLE.sub(replace_inline, text)

    # A presentation attribute is parsed as a CSS property value, and var() in one
    # resolves and follows the mode, so a chart's paint can join the role layer.
    def replace_paint(match: re.Match[str]) -> str:
        nonlocal changed
        prop, literal = match.group(1), match.group(2)
        job = PROPERTY_CLASS.get(prop)
        token = HEX_TO_LEGACY.get(literal.lower())
        role = role_for(token, job) if token else None
        if role is None:
            nearest = snap(literal, job)
            if nearest is None:
                skipped.append(
                    Skipped(
                        line_of(text, match.start()),
                        "svg-attribute",
                        f'{prop}="{literal}" — not a palette pigment, needs a token by hand',
                    )
                )
                return match.group(0)
            role = nearest[0]
            skipped.append(
                Skipped(
                    line_of(text, match.start()),
                    "snapped",
                    f'{prop}="{literal}" -> var({role}), OKLab {nearest[1]:.1f} away',
                )
            )
        changed += 1
        return f'{prop}="var({role})"'

    text = RE_SVG_PAINT.sub(replace_paint, text)

    text, island_changed = fix_island_text(text)
    changed += island_changed

    text, tint_skipped, tint_changed = remap_tints(text)
    skipped += tint_skipped
    changed += tint_changed

    return text, skipped, changed


def island_classes(text: str) -> set[str]:
    """Classes whose rule paints an always-dark surface."""
    found: set[str] = set()
    pattern = r"background[a-z-]*:\s*var\((%s)\)" % "|".join(DARK_SURFACES)
    for style in RE_STYLE_BLOCK.finditer(text):
        for rule in RE_RULE.finditer(style.group(2)):
            if re.search(pattern, rule.group(2)):
                found.update(re.findall(r"\.([a-zA-Z][\w-]*)", rule.group(1)))
    return found


def fix_island_text(text: str) -> tuple[str, int]:
    """Repoint text inside an always-dark panel at the panel's own roles.

    The property table cannot see this on its own: `color: var(--muted)` is right
    on the page and wrong inside a code listing, and which one it is depends on an
    ancestor the CSS never names. A class belongs to a panel when it is the panel's
    name or a hyphenated child of it, so `.diff-row .code` counts as inside
    `.diff` while a one-letter class captures nothing.
    """
    islands = island_classes(text)
    if not islands:
        return text, 0

    count = 0

    def swap(decl: re.Match[str]) -> str:
        nonlocal count
        replacement = PANEL_TEXT.get(decl.group(1))
        if replacement is None:
            return decl.group(0)
        count += 1
        return f"color: var({replacement})"

    def repoint(match: re.Match[str]) -> str:
        selector, body = match.group(1), match.group(2)
        classes = re.findall(r"\.([a-zA-Z][\w-]*)", selector)
        if not any(c == i or c.startswith(i + "-") for c in classes for i in islands):
            return match.group(0)
        fixed = re.sub(r"(?<![-a-z])color:\s*var\((--[a-z0-9-]+)\)", swap, body)
        return f"{selector}{{{fixed}}}"

    return RE_RULE.sub(repoint, text), count


RE_TINT_DECL = re.compile(
    r"(?P<prop>-{0,2}[a-z][a-z0-9-]*)\s*:\s*(?P<value>[^;{}*]*rgba?\([^)]*\)[^;{}*]*)"
)


def remap_tints(text: str) -> tuple[str, list[Skipped], int]:
    """Rewrite rgba tints of known pigments onto the tinted-surface tokens."""
    skipped: list[Skipped] = []
    changed = 0

    def replace_decl(match: re.Match[str]) -> str:
        nonlocal changed
        prop = match.group("prop")
        if prop.startswith("--"):
            return match.group(0)
        job = PROPERTY_CLASS.get(prop)
        line = line_of(text, match.start())

        def replace_tint(ref: re.Match[str]) -> str:
            nonlocal changed
            rgb = tuple(int(g) for g in RE_RGBA.match(ref.group(0)).groups())
            neutral = NEUTRAL_TINT.get(rgb)
            if neutral:
                changed += 1
                return f"var({neutral})"
            role = TINT_ROLE.get(rgb)
            suffix = TINT_SUFFIX.get(job or "")
            if role is None or suffix is None:
                skipped.append(Skipped(line, "unknown-tint",
                                       f"{prop}: {ref.group(0)} — no tinted-surface token"))
                return ref.group(0)
            changed += 1
            return f"var(--{role}-{suffix})"

        head, _, tail = match.group(0).partition(":")
        return head + ":" + RE_RGBA.sub(replace_tint, tail)

    text = RE_TINT_DECL.sub(replace_decl, text)

    # Text on a tinted surface is --body. Solving for role-coloured text puts
    # warning's light alpha at 0.02, which is no tint at all, so the role carries
    # the border and the icon instead and the text stays neutral.
    def neutralise(match: re.Match[str]) -> str:
        nonlocal changed
        selector, body = match.group(1), match.group(2)
        if not re.search(r"background[a-z-]*:\s*var\(--[a-z]+-soft\)", body):
            return match.group(0)
        fixed, count = re.subn(
            r"(?<![-a-z])color:\s*var\(--(?:critical|warning|positive|accent)\)",
            "color: var(--body)", body)
        changed += count
        return f"{selector}{{{fixed}}}"

    text = re.sub(r"([^{}]+)\{([^{}]*)\}", neutralise, text)
    return text, skipped, changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--apply", action="store_true", help="rewrite the files in place")
    args = parser.parse_args()

    for path in args.files:
        text, skipped, changed = remap(path)
        name = path.name
        if args.apply:
            path.write_text(text, encoding="utf-8")
        verb = "rewrote" if args.apply else "would rewrite"
        print(f"{name}: {verb} {changed} references, {len(skipped)} left for review")
        by_kind: dict[str, list[Skipped]] = {}
        for item in skipped:
            by_kind.setdefault(item.kind, []).append(item)
        for kind, items in sorted(by_kind.items()):
            print(f"  {kind} ({len(items)})")
            for item in items:
                print(f"    {name}:{item.line}: {item.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
