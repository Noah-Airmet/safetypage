"""Rewrite invisible characters in Python sources as \\uXXXX escapes.

Source files here deal in soft hyphens, zero-width joiners and bidi controls. Those must appear
as escapes, never as the characters themselves, so that a reviewer can see them.
Usage: python scripts/escape_invisibles.py [--check] FILE...
"""

import sys
import unicodedata
from pathlib import Path


def invisible(ch: str) -> bool:
    return ord(ch) > 127 and (
        unicodedata.category(ch) in {"Cf", "Cc", "Zl", "Zp", "Co", "Cn"}
        or ch == "\N{REPLACEMENT CHARACTER}"
    )


def escape(text: str) -> str:
    return "".join(
        (f"\\u{ord(c):04x}" if ord(c) < 0x10000 else f"\\U{ord(c):08x}") if invisible(c) else c
        for c in text
    )


def main(argv: list[str]) -> int:
    check = "--check" in argv
    dirty = 0
    for name in (a for a in argv if a != "--check"):
        path = Path(name)
        text = path.read_text(encoding="utf-8")
        fixed = escape(text)
        if fixed != text:
            dirty += 1
            if check:
                print(f"invisible characters in {path}", file=sys.stderr)
            else:
                path.write_text(fixed, encoding="utf-8")
    return 1 if check and dirty else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
