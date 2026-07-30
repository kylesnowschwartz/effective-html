#!/usr/bin/env python3
"""Resolve the token block statically and check every role in every mode.

The house style's role layer is a chain of var() references, so a typo yields a
token that silently resolves to nothing rather than an error. This walks each
chain to a literal and measures contrast per mode, which is the only way to know
that dark mode and print actually select the steps they claim to.

Usage:
    tools/check-tokens.py [path/to/tokens.css]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT = REPO / "skills" / "effective-html" / "references" / "house-style-tokens.css"

AA_BODY = 4.5
MARK_MIN = 3.0  # WCAG contrast for a non-text graphical object

# --accent belongs here, not with the marks. It is painted onto text 30 times in
# the corpus, and checking it at the 3:1 mark floor is what let dark accent sit at
# 3.81:1 unnoticed.
TEXT_ROLES = ("ink", "body", "muted", "critical", "warning", "positive", "accent")
MARK_ROLES = (
    "s1", "s2", "s3", "s4", "s5",
    "critical-mark", "warning-mark", "positive-mark", "accent-mark",
    "critical-line", "warning-line", "positive-line", "accent-line",
)
# A tinted surface is measured the other way round: --body has to clear AA on it.
TINT_ROLES = ("critical-soft", "warning-soft", "positive-soft", "accent-soft")
# A solid fill is two floors at once: the fill is a non-text object against the
# page, and its own label is text on the fill. The pairing is the point — warning's
# label is white in light mode and slate in dark, because amber is light enough
# that white fails on it, so neither floor can be checked without the other.
SOLID_PAIRS = (
    ("critical-solid", "on-critical"),
    ("warning-solid", "on-warning"),
    ("positive-solid", "on-positive"),
    ("accent-solid", "on-accent"),
)
# A surface used directly as a background, paired with the weakest text tier that
# lands on it. Checking the weakest one covers the tiers above it. The panels take
# their own tier: they hold one colour in both modes, so the mode-aware tiers are
# the wrong measurement there.
SURFACE_TEXT = {
    "surface": ("muted",),
    "wash": ("muted",),
    "oat": ("muted",),
    "invert": ("on-invert-muted", "on-invert-accent"),
    "panel": ("panel-muted", "panel-critical", "panel-positive", "panel-accent"),
    "panel-raised": ("panel-muted",),
    "panel-critical-soft": ("panel-ink", "panel-body", "panel-accent"),
    "panel-positive-soft": ("panel-ink", "panel-body", "panel-accent"),
}

# A surface has to be findable against the page it sits on, by its own fill or by
# its edge. --panel is the case that needs saying: it holds one colour in both
# modes and that colour is the dark page's background, so in dark mode a code
# block with no edge has no boundary. The floor is the separation --line already
# provides at its weakest, not the 3:1 non-text floor — a seam between two
# surfaces marks where one ends, it does not carry meaning of its own.
SEAM_MIN = 1.4
SURFACE_EDGE = {"panel": "panel-edge"}

RE_VAR = re.compile(r"var\(\s*(--[a-z0-9-]+)\s*(?:,([^)]*))?\)")
RE_DECL = re.compile(r"(--[a-z0-9-]+)\s*:\s*([^;]+)")
RE_HEX6 = re.compile(r"#[0-9A-Fa-f]{6}")


def matching_brace(source: str, open_index: int) -> int:
    """Index just past the block opened at open_index."""
    depth, i = 1, open_index + 1
    while depth and i < len(source):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
        i += 1
    return i


def split_print(css: str) -> tuple[str, str]:
    """Separate the print at-rule, so its nested selectors are not read as screen rules."""
    match = re.search(r"@media\s+print\s*\{", css)
    if not match:
        return css, ""
    end = matching_brace(css, match.end() - 1)
    return css[: match.start()] + css[end:], css[match.end() : end - 1]


def declarations(source: str, selector: str) -> dict[str, str]:
    """Custom properties declared under a selector, including in a selector list."""
    out: dict[str, str] = {}
    for match in re.finditer(r"(?m)^\s*" + selector + r"\s*(?:,\s*[^{]+?)?\{", source):
        end = matching_brace(source, match.end() - 1)
        for decl in RE_DECL.finditer(source[match.end() : end - 1]):
            out[decl.group(1)] = decl.group(2).strip()
    return out


def resolve(name: str, table: dict[str, str], seen: frozenset[str] = frozenset()) -> str | None:
    if name in seen or name not in table:
        return None
    value = table[name].strip()
    ref = RE_VAR.search(value)
    if not ref:
        return value
    resolved = resolve(ref.group(1), table, seen | {name})
    if resolved is not None:
        return resolved
    return ref.group(2).strip() if ref.group(2) else None


def luminance(hex_colour: str) -> float:
    digits = hex_colour.lstrip("#")
    channels = [int(digits[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
    screen, printed = split_print(css)

    root = declarations(screen, r":root")
    modes = {
        "light": root,
        "dark": {**root, **declarations(screen, r"html\.dark")},
        "print": {**root, **declarations(printed, r":root")},
    }

    failures: list[str] = []
    for mode, table in modes.items():
        background = resolve("--bg", table)
        if background is None or not RE_HEX6.fullmatch(background):
            failures.append(f"{mode}: --bg does not resolve to a hex literal")
            continue
        print(f"--- {mode}  bg {background} ---")
        for role, floor, kind in (
            *((r, AA_BODY, "text") for r in TEXT_ROLES),
            *((r, MARK_MIN, "mark") for r in MARK_ROLES),
        ):
            value = resolve(f"--{role}", table)
            if value is None:
                failures.append(f"{mode}: --{role} is undefined")
                print(f"  {kind}  --{role:15s} UNDEFINED")
                continue
            if not RE_HEX6.fullmatch(value):
                print(f"  {kind}  --{role:15s} {value}")
                continue
            ratio = contrast(value, background)
            verdict = "ok" if ratio >= floor else "FAIL"
            if ratio < floor:
                failures.append(f"{mode}: --{role} is {ratio:.2f}:1, under {floor}:1")
            print(f"  {kind}  --{role:15s} {value}  {ratio:5.2f}:1  {verdict}")

        body = resolve("--body", table)
        for role in TINT_ROLES:
            tint = resolve(f"--{role}", table)
            if tint is None:
                failures.append(f"{mode}: --{role} is undefined")
                continue
            if not (RE_HEX6.fullmatch(tint) and body and RE_HEX6.fullmatch(body)):
                continue
            ratio = contrast(body, tint)
            verdict = "ok" if ratio >= AA_BODY else "FAIL"
            if ratio < AA_BODY:
                failures.append(f"{mode}: --body on --{role} is {ratio:.2f}:1")
            print(f"  tint  --{role:15s} {tint}  body {ratio:5.2f}:1  {verdict}")

        for fill_role, label_role in SOLID_PAIRS:
            fill = resolve(f"--{fill_role}", table)
            label = resolve(f"--{label_role}", table)
            if fill is None or label is None:
                failures.append(f"{mode}: --{fill_role} or --{label_role} is undefined")
                continue
            if not (RE_HEX6.fullmatch(fill) and RE_HEX6.fullmatch(label)):
                continue
            edge = contrast(fill, background)
            text = contrast(label, fill)
            if edge < MARK_MIN:
                failures.append(f"{mode}: --{fill_role} is {edge:.2f}:1 on the page")
            if text < AA_BODY:
                failures.append(f"{mode}: --{label_role} on --{fill_role} is {text:.2f}:1")
            verdict = "ok" if edge >= MARK_MIN and text >= AA_BODY else "FAIL"
            print(
                f"  solid --{fill_role:15s} {fill}  page {edge:5.2f}:1  "
                f"label {text:5.2f}:1  {verdict}"
            )

        for surface_role, text_roles in SURFACE_TEXT.items():
          for text_role in text_roles:
            surface = resolve(f"--{surface_role}", table)
            ink = resolve(f"--{text_role}", table)
            if surface is None or ink is None:
                failures.append(f"{mode}: --{surface_role} or --{text_role} is undefined")
                continue
            if not (RE_HEX6.fullmatch(surface) and RE_HEX6.fullmatch(ink)):
                continue
            ratio = contrast(ink, surface)
            verdict = "ok" if ratio >= AA_BODY else "FAIL"
            if ratio < AA_BODY:
                failures.append(
                    f"{mode}: --{text_role} on --{surface_role} is {ratio:.2f}:1"
                )
            print(
                f"  surf  --{surface_role:15s} {surface}  --{text_role} "
                f"{ratio:5.2f}:1  {verdict}"
            )

        for surface_role, edge_role in SURFACE_EDGE.items():
            surface = resolve(f"--{surface_role}", table)
            edge = resolve(f"--{edge_role}", table)
            if surface is None or edge is None:
                failures.append(f"{mode}: --{surface_role} or --{edge_role} is undefined")
                continue
            if not (RE_HEX6.fullmatch(surface) and RE_HEX6.fullmatch(edge)):
                continue
            seam = max(contrast(surface, background), contrast(edge, background))
            verdict = "ok" if seam >= SEAM_MIN else "FAIL"
            if seam < SEAM_MIN:
                failures.append(
                    f"{mode}: --{surface_role} is {seam:.2f}:1 from the page by fill or edge, "
                    f"under {SEAM_MIN}:1 — it has no visible boundary"
                )
            print(f"  seam  --{surface_role:15s} {surface}  edge {edge}  {seam:5.2f}:1  {verdict}")

    referenced = {m.group(1) for m in RE_VAR.finditer(css)}
    for mode, table in modes.items():
        unresolved = sorted(r for r in referenced if resolve(r, table) is None)
        if unresolved:
            failures.append(f"{mode}: unresolved {', '.join(unresolved)}")
        print(f"{mode}: {len(referenced)} var() references, unresolved: {unresolved or 'none'}")

    if failures:
        print("\n" + "\n".join(failures), file=sys.stderr)
        return 1
    print("\nclean: every role resolves and clears its floor in all three modes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
