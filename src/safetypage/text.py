"""Making extracted text safe to store, without changing what it says.

The text of record is the source's own characters. The only things removed are characters a
reader cannot see and that have been used to smuggle instructions to language models (Unicode tag
characters, bidirectional overrides), control characters, and Windows line endings. Nothing is
re-spelled, re-ordered or normalised: quote checking does its own normalisation at match time, and
keeps a map back to these characters.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = ["clean_text", "is_clean"]

# U+E0000-E007F: tag characters. U+202A-202E, U+2066-2069: bidi embeddings, overrides, isolates.
# C0/C1 controls except tab and newline. U+FEFF: byte-order mark.
_HAZARD_RE: Final = re.compile(
    "[\U000e0000-\U000e007f\u202a-\u202e\u2066-\u2069\ufeff"
    "\x00-\x08\x0b\x0e-\x1f\x7f\x80-\x84\x86-\x9f]"
)
_LINE_END_RE: Final = re.compile("\r\n?|\x0c|\x85|\u2028|\u2029")


def clean_text(text: str) -> str:
    """Remove invisible hazards and unify line endings. Idempotent."""
    return _HAZARD_RE.sub("", _LINE_END_RE.sub("\n", text))


def is_clean(text: str) -> bool:
    return clean_text(text) == text
