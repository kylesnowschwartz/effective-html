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
