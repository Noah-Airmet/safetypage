"""What each licence tier may be served. Enforced here, on the server side, for every surface.

The private copy of a link-only document exists so it can be searched and so quotes can be checked
against it. These limits are what keeps it private: no public function in this package returns
more of a link-only document than a snippet, and the snapshot gate fails a build that tries to
publish more.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from onthepage.licence import Tier

__all__ = ["ACCESS", "Access", "TierViolationError", "access_for", "clip", "full_text"]


class TierViolationError(PermissionError):
    """Something tried to serve link-only content in full."""


@dataclass(frozen=True, slots=True)
class Access:
    tier: Tier
    full_text: bool
    """May a unit's whole text be returned (``fetch``, the reader, the static export)?"""
    page_images: bool
    source_files: bool
    """May the PDF or HTML itself be served?"""
    snippet_chars: int
    """Longest search snippet, in characters."""
    excerpt_words: int | None
    """Most source words returned around a quote check or a fetch stub. None: no limit."""


ACCESS: Final = {
    Tier.OPEN: Access(
        Tier.OPEN,
        full_text=True,
        page_images=True,
        source_files=True,
        snippet_chars=600,
        excerpt_words=None,
    ),
    Tier.LINK_ONLY: Access(
        Tier.LINK_ONLY,
        full_text=False,
        page_images=False,
        source_files=False,
        snippet_chars=300,
        excerpt_words=40,
    ),
}


def access_for(tier: Tier | str) -> Access:
    return ACCESS[Tier(tier)]


def full_text(text: str, tier: Tier | str) -> str:
    """Pass ``text`` through if the tier allows full text; refuse loudly otherwise."""
    if not access_for(tier).full_text:
        raise TierViolationError("full text of a link-only document cannot be served")
    return text


def clip(text: str, tier: Tier | str, *, around: tuple[int, int] | None = None) -> str:
    """An excerpt of ``text`` that the tier allows: everything for open, a few words otherwise.

    ``around`` is a ``(start, end)`` stretch to keep in view (a matched quote); without it the
    excerpt is the opening words. Cuts are marked with an ellipsis.
    """
    access = access_for(tier)
    if access.excerpt_words is None:
        return text
    limit_words, limit_chars = access.excerpt_words, access.snippet_chars
    start = 0 if around is None else max(0, min(around[0], len(text)))
    words: list[str] = []
    length = 0
    for word in text[start:].split():
        if len(words) >= limit_words or length + len(word) + 1 > limit_chars:
            break
        words.append(word)
        length += len(word) + 1
    excerpt = " ".join(words)
    if not excerpt and text[start:].strip():
        excerpt = text[start:].strip()[:limit_chars]
    whole = " ".join(text.split())
    if excerpt == whole:
        return excerpt
    prefix = "…" if text[:start].strip() else ""
    suffix = "…" if len(prefix) + len(excerpt) < len(whole) else ""
    return f"{prefix}{excerpt}{suffix}"
