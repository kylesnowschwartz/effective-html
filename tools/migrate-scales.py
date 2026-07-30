#!/usr/bin/env python3
"""Move a reference file's sizes onto the house style's closed scales.

Colour is a lookup — a pigment either is in the palette or is not. Size is a
rounding: the corpus holds about 14 font sizes massed between 10 and 13px and 20
spacing values, and each one has a nearest rung. Doing that by hand across 21
files is where transcription errors live, so it is done here and read as a diff.

Sizes and gaps round up to the next rung, which is the density decision rather
than arithmetic: nearest would turn 14px type into 13 and a 5px gap into 4, where
the plan calls for 16 and 8. One value goes the other way, 36px down to 32.
Radius rounds to the nearest rung instead, because a corner is a shape and owes
nothing to density.

Usage:
    tools/migrate-scales.py path/to/file.html          # report only
    tools/migrate-scales.py --apply path/to/file.html  # rewrite in place
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

TYPE_SCALE = (11, 13, 16, 18, 21, 24, 30, 38, 52)
TYPE_TOKEN = {
    11: "--text-micro",
    13: "--text-meta",
    16: "--text-body",
    18: "--text-lead",
    21: "--text-h4",
    24: "--text-h3",
    30: "--text-h2",
    38: "--text-h1",
    52: "--text-display",
}
BODY_FLOOR = 16
PROSE_SELECTOR = re.compile(r"\b(?:body|p|li|dd|blockquote)\b")

SPACING = (0, 2, 4, 8, 12, 16, 20, 24, 32, 48, 64, 96)
SPACING_TOKEN = {v: f"--sp-{v}" for v in SPACING}
# The one rounding that goes down. 36 sits between 32 and 48, and 48 is a
# different kind of gap — a section break rather than a card's inner padding.
SPACING_EXCEPTIONS = {36: 32}

RADII = (4, 8, 12, 999)
RADIUS_TOKEN = {4: "--r-4", 8: "--r-8", 12: "--r-12", 999: "--r-full"}

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
# Past this the nearest token is a different layout, not the same one rounded.
WIDTH_TOLERANCE = 0.12

INERT_PROPERTIES = (
    "-webkit-font-smoothing",
    "-moz-osx-font-smoothing",
    "text-rendering",
    "font-optical-sizing",
)

# 500 renders as 400 and 600 as full bold on Georgia, Segoe UI, DejaVu and
# Liberation, so this is what these files already look like on most platforms.
WEIGHT_MAP = {100: 400, 200: 400, 300: 400, 430: 400, 500: 400, 600: 700, 800: 700, 900: 700}

SPACING_PROPS = ("gap", "row-gap", "column-gap", "padding", "margin")
RE_SPACING = re.compile(
    r"(?<![-a-z])((?:%s)(?:-(?:top|right|bottom|left|inline|block))?(?:-(?:start|end))?)"
    r":\s*([^;}]+)" % "|".join(SPACING_PROPS)
)
RE_FONT_SIZE = re.compile(r"(?<![-a-z])font-size:\s*([0-9.]+)px")
RE_WEIGHT = re.compile(r"(?<![-a-z])font-weight:\s*([0-9]+)")
RE_RADIUS = re.compile(r"(?<![-a-z])border-radius:\s*([^;}]+)")
RE_MAX_WIDTH = re.compile(r"(?<!\()max-width:\s*([0-9.]+)px")
RE_STYLE_BLOCK = re.compile(r"(<style[^>]*>)(.*?)(</style>)", re.DOTALL | re.IGNORECASE)
RE_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
RE_PX = re.compile(r"(-?[0-9.]+)px")
BEGIN_MARKER = "/* @house-style-tokens:begin"
END_MARKER = "/* @house-style-tokens:end */"


def nearest(value: float, scale: tuple[int, ...]) -> int:
    """The closest rung. Used where the value is a shape rather than a density."""
    return min(scale, key=lambda rung: (abs(rung - value), -rung))


def round_up(value: float, scale: tuple[int, ...]) -> int:
    """The next rung at or above the value, clamped to the top of the scale.

    Rounding up rather than to the nearest is the density decision, and it is what
    the plan's two worked examples both do: 14 becomes 16 and 5 becomes 8, where
    nearest would give 13 and 4. Only 36 goes the other way, and it is listed as
    an exception because 48 is a section break rather than a card's inner padding.
    """
    return next((rung for rung in scale if rung >= value - 0.001), scale[-1])


def snap_spacing(value: float) -> int:
    whole = round(value)
    if whole in SPACING_EXCEPTIONS:
        return SPACING_EXCEPTIONS[whole]
    return round_up(value, SPACING)


def token_region(css: str) -> tuple[int, int] | None:
    """Span of the generated token block, which is already on every scale."""
    if BEGIN_MARKER not in css:
        return None
    start = css.index(BEGIN_MARKER)
    return start, css.index(END_MARKER, start) + len(END_MARKER)


def migrate_css(css: str, counts: Counter) -> str:
    skip = token_region(css)

    def outside_block(index: int) -> bool:
        return skip is None or not (skip[0] <= index < skip[1])

    def rewrite_rule(match: re.Match[str]) -> str:
        if not outside_block(match.start()):
            return match.group(0)
        selector, body = match.group(1), match.group(2)
        is_prose = bool(PROSE_SELECTOR.search(selector))

        def font_size(m: re.Match[str]) -> str:
            size = float(m.group(1))
            step = round_up(size, TYPE_SCALE)
            if is_prose and step < BODY_FLOOR:
                step = BODY_FLOOR
            counts[f"type {size:g}px -> {step}px"] += 1
            return f"font-size: var({TYPE_TOKEN[step]})"

        def weight(m: re.Match[str]) -> str:
            value = int(m.group(1))
            mapped = WEIGHT_MAP.get(value, value)
            if mapped not in (400, 700):
                mapped = 400 if mapped < 550 else 700
            if mapped != value:
                counts[f"weight {value} -> {mapped}"] += 1
            name = "--weight-normal" if mapped == 400 else "--weight-bold"
            return f"font-weight: var({name})"

        def spacing(m: re.Match[str]) -> str:
            prop, value = m.group(1), m.group(2)
            if "var(" in value or "%" in value or "calc(" in value:
                return m.group(0)

            def one(px: re.Match[str]) -> str:
                raw = float(px.group(1))
                if raw < 0:
                    return px.group(0)
                step = snap_spacing(raw)
                if step != raw:
                    counts[f"spacing {raw:g}px -> {step}px"] += 1
                return f"var({SPACING_TOKEN[step]})"

            return f"{prop}: {RE_PX.sub(one, value)}"

        def radius(m: re.Match[str]) -> str:
            value = m.group(1)
            if "var(" in value or "%" in value:
                return m.group(0)

            def one(px: re.Match[str]) -> str:
                raw = float(px.group(1))
                step = nearest(raw, RADII)
                if step != raw:
                    counts[f"radius {raw:g}px -> {step}px"] += 1
                return f"var({RADIUS_TOKEN[step]})"

            return f"border-radius: {RE_PX.sub(one, value)}"

        def max_width(m: re.Match[str]) -> str:
            raw = float(m.group(1))
            name, px = min(WIDTH_TOKENS.items(), key=lambda kv: abs(kv[1] - raw))
            if abs(px - raw) / max(raw, 1) > WIDTH_TOLERANCE:
                counts[f"width {raw:g}px left alone, nearest {name} is {px}px"] += 1
                return m.group(0)
            if px != raw:
                counts[f"width {raw:g}px -> {name} ({px}px)"] += 1
            return f"max-width: var({name})"

        body = RE_FONT_SIZE.sub(font_size, body)
        body = RE_WEIGHT.sub(weight, body)
        body = RE_SPACING.sub(spacing, body)
        body = RE_RADIUS.sub(radius, body)
        body = RE_MAX_WIDTH.sub(max_width, body)
        for prop in INERT_PROPERTIES:
            body, dropped = re.subn(rf"\s*{re.escape(prop)}:\s*[^;}}]+;?", "", body)
            if dropped:
                counts[f"dropped {prop}"] += dropped
        return f"{selector}{{{body}}}"

    return RE_RULE.sub(rewrite_rule, css)


def migrate(path: Path) -> tuple[str, Counter]:
    text = path.read_text(encoding="utf-8")
    counts: Counter = Counter()
    out, cursor = [], 0
    for style in RE_STYLE_BLOCK.finditer(text):
        out.append(text[cursor : style.start(2)])
        out.append(migrate_css(style.group(2), counts))
        cursor = style.end(2)
    out.append(text[cursor:])
    return "".join(out), counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--summary", action="store_true", help="one line per file")
    args = parser.parse_args()

    total: Counter = Counter()
    for path in args.files:
        text, counts = migrate(path)
        if args.apply:
            path.write_text(text, encoding="utf-8")
        total.update(counts)
        print(f"{path.name}: {sum(counts.values())} changes")
        if not args.summary:
            for what, n in counts.most_common():
                print(f"    {n:4}  {what}")
    if len(args.files) > 1:
        print(f"\ntotal {sum(total.values())} changes")
        for what, n in total.most_common(20):
            print(f"    {n:4}  {what}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
