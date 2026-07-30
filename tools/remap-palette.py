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
    ("--ivory", "surface"): "--bg",
    ("--ivory", "mark"): "--bg",
    ("--white", "text"): "--white",
    ("--white", "surface"): "--surface",
    ("--white", "edge"): "--surface",
    ("--white", "mark"): "--surface",
    ("--slate", "text"): "--ink",
    ("--slate", "surface"): "--slate",
    ("--slate", "mark"): "--ink",
    ("--oat", "surface"): "--oat",
    ("--oat", "edge"): "--line",
    ("--oat", "mark"): "--oat",
    ("--gray-700", "text"): "--body",
    ("--gray-700", "surface"): "--gray-700",
    ("--gray-700", "edge"): "--line-strong",
    ("--gray-700", "mark"): "--body",
    ("--gray-800", "text"): "--body",
    ("--gray-800", "surface"): "--gray-700",
    ("--gray-800", "edge"): "--line-strong",
    ("--gray-800", "mark"): "--body",
    # The 3.47:1 failure and the legitimate border use, told apart by property.
    ("--gray-500", "text"): "--muted",
    ("--gray-500", "surface"): "--fill",
    ("--gray-500", "edge"): "--fill",
    ("--gray-500", "mark"): "--fill",
    ("--gray-300", "surface"): "--wash",
    ("--gray-300", "edge"): "--line",
    ("--gray-300", "mark"): "--line",
    ("--gray-200", "surface"): "--wash",
    ("--gray-200", "edge"): "--line",
    ("--gray-200", "mark"): "--line",
    ("--gray-150", "surface"): "--wash",
    ("--gray-150", "edge"): "--line",
    ("--gray-150", "mark"): "--wash",
    ("--gray-100", "surface"): "--wash",
    ("--gray-100", "edge"): "--line",
    ("--gray-100", "mark"): "--wash",
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
    ("--rust", "text"): "--critical",
    ("--rust", "surface"): "--critical",
    ("--rust", "edge"): "--critical",
}

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
DARK_SURFACES = {"--slate", "--gray-700", "--slate-900", "--slate-800"}
# Roles that resolve dark in light mode, which is unreadable on an island.
FLIPPING_TEXT_ROLES = {"--ink", "--body", "--muted", "--fill"}
RE_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")

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
        if prop.startswith("--"):
            return match.group(0)  # the reference layer, which is where literals belong
        job = PROPERTY_CLASS.get(prop)
        line = line_of(text, offset + match.start())

        def replace_hex(ref: re.Match[str]) -> str:
            nonlocal changed
            literal = ref.group(0)
            token = HEX_TO_LEGACY.get(literal.lower())
            if token is None:
                skipped.append(Skipped(line, "unknown-pigment",
                                       f"{prop}: {literal} — not a palette pigment"))
                return literal
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
        if prop.startswith("--"):
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
        token = HEX_TO_LEGACY.get(literal.lower())
        role = role_for(token, PROPERTY_CLASS.get(prop)) if token else None
        if role is None:
            skipped.append(
                Skipped(
                    line_of(text, match.start()),
                    "svg-attribute",
                    f'{prop}="{literal}" — not a palette pigment, needs a token by hand',
                )
            )
            return match.group(0)
        changed += 1
        return f'{prop}="var({role})"'

    text = RE_SVG_PAINT.sub(replace_paint, text)

    skipped += island_text(text)

    for match in RE_RGBA.finditer(text):
        rgb = tuple(int(g) for g in match.groups())
        if rgb in CHANGED_PIGMENT_RGB:
            skipped.append(
                Skipped(
                    line_of(text, match.start()),
                    "stale-tint",
                    f"{match.group(0)} — {CHANGED_PIGMENT_RGB[rgb]}, so this tint no "
                    f"longer matches the text on it",
                )
            )

    return text, skipped, changed


def island_text(text: str) -> list[Skipped]:
    """Text inside an always-dark panel that is painted with a flipping role.

    The property table cannot see this: `color: var(--muted)` is right on the page
    and wrong inside a dark code panel, and which one it is depends on an ancestor
    the CSS does not name. Classes are matched by prefix, so `.diff-row .code`
    counts as inside `.diff`.
    """
    islands: set[str] = set()
    for _, css in [(0, m.group(2)) for m in RE_STYLE_BLOCK.finditer(text)]:
        for rule in RE_RULE.finditer(css):
            body = rule.group(2)
            if not re.search(r"background[a-z-]*:\s*var\((%s)\)" % "|".join(DARK_SURFACES), body):
                continue
            islands.update(re.findall(r"\.([a-zA-Z][\w-]*)", rule.group(1)))
    if not islands:
        return []

    out: list[Skipped] = []
    for style in RE_STYLE_BLOCK.finditer(text):
        for rule in RE_RULE.finditer(style.group(2)):
            classes = re.findall(r"\.([a-zA-Z][\w-]*)", rule.group(1))
            if not any(c.startswith(i) for c in classes for i in islands):
                continue
            for decl in re.finditer(r"(?<![-a-z])color:\s*var\((--[a-z0-9-]+)\)", rule.group(2)):
                if decl.group(1) in FLIPPING_TEXT_ROLES:
                    out.append(
                        Skipped(
                            line_of(text, style.start(2) + rule.start()),
                            "island-text",
                            f"{rule.group(1).strip()} sets color: var({decl.group(1)}) inside an "
                            f"always-dark panel, so light mode paints dark on dark",
                        )
                    )
    return out


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
