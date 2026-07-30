#!/usr/bin/env python3
"""Push the shared fragments into every reference file.

`references/house-style-tokens.css` is the authority for every value and
`references/house-style-theme.html` for how a document enters dark mode. That is
only true if a change to either reaches the files. Each file carries a fragment
between two markers; this replaces the marked region with the current source,
re-indented to match the marker.

The theme fragment is inserted where it is missing, immediately before `</head>` —
the token block is not, because where a document's CSS starts is a decision about
that document.

Usage:
    tools/sync-tokens.py            # report which files would change
    tools/sync-tokens.py --apply    # rewrite them
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REFERENCES = REPO / "skills" / "effective-html" / "references"


@dataclass(frozen=True)
class Fragment:
    source: Path
    begin: str
    end: str
    insert_before: str | None = None

    def text(self) -> str:
        return self.source.read_text(encoding="utf-8").strip()


FRAGMENTS = (
    Fragment(
        REFERENCES / "house-style-tokens.css",
        "/* @house-style-tokens:begin",
        "/* @house-style-tokens:end */",
    ),
    Fragment(
        REFERENCES / "house-style-theme.html",
        "<!-- @house-style-theme:begin",
        "<!-- @house-style-theme:end -->",
        insert_before="</head>",
    ),
)


# A document that already puts the dark class on <html> switches itself. The
# element matters: one file toggles `dark` on preview stages inside the page, which
# is a swatch of dark styling rather than the page's own mode.
RE_DARK_CLASS = re.compile(r"documentElement\.classList\.(?:toggle|add)\(\s*['\"]dark['\"]")


def reindent(block: str, indent: str) -> str:
    """The block with `indent` prepended to every non-blank line."""
    return "\n".join(indent + line if line.strip() else line for line in block.split("\n"))


def apply_fragment(text: str, fragment: Fragment) -> str | None:
    """The text with this fragment refreshed or inserted, or None when unchanged."""
    block = fragment.text()
    match = re.search(r"^([ \t]*)" + re.escape(fragment.begin), text, re.MULTILINE)
    if match:
        start = match.start()
        end = text.index(fragment.end, start) + len(fragment.end)
        replacement = reindent(block, match.group(1)).lstrip()
        if text[start:end] == replacement:
            return None
        return text[:start] + replacement + text[end:]
    if fragment.insert_before is None or fragment.insert_before not in text:
        return None
    if RE_DARK_CLASS.search(text):
        # The document already switches itself. The two authored examples build the
        # toggle into their own top bar, and a second one would sit over it.
        return None
    at = text.index(fragment.insert_before)
    return text[:at] + block + "\n" + text[at:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    sources = {f.source for f in FRAGMENTS}
    changed: dict[Path, list[str]] = {}
    missing: list[str] = []

    for path in sorted(REFERENCES.rglob("*.html")):
        if path in sources:
            continue
        text = original = path.read_text(encoding="utf-8")
        for fragment in FRAGMENTS:
            if fragment.begin not in text and fragment.insert_before is None:
                missing.append(f"{path.relative_to(REPO)}: no {fragment.begin} marker")
                continue
            new = apply_fragment(text, fragment)
            if new is not None:
                text = new
                changed.setdefault(path, []).append(fragment.source.name)
        if text != original and args.apply:
            path.write_text(text, encoding="utf-8")

    verb = "updated" if args.apply else "would update"
    for path, names in changed.items():
        print(f"{verb} {path.relative_to(REPO)} ({', '.join(names)})")
    for line in missing:
        print(line, file=sys.stderr)
    print(f"{len(changed)} {verb}, {len(missing)} missing a marker")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
