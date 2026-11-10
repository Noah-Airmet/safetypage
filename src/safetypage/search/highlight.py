"""Snippets with exact highlight offsets.

The index says *which* units match; this module finds *where* in a unit's text, by applying the
parsed query to the unit's words (:func:`safetypage.search.grammar.words`, the same word split
and folding the index uses). Offsets are Python string indices into the snippet that is
returned, so ``snippet[start:end]`` is the matched text.

Snippet length is :data:`SNIPPET_CHARS`, inside both tiers' limits. A link-only unit's snippet
is cut by :func:`safetypage.policy.clip`, the one function that decides how much of a link-only
document may be shown.
"""

from __future__ import annotations

import re
from typing import Final

from safetypage import policy
from safetypage.licence import Tier
from safetypage.search.grammar import ParsedQuery, Phrase, Prefix, words

__all__ = ["SNIPPET_CHARS", "find_spans", "snippet"]

SNIPPET_CHARS: Final = 300
LEAD_CHARS: Final = 60
"""Context kept before the first match in the window."""

_SPACE_RE: Final = re.compile(r"\s+")


def find_spans(text: str, query: ParsedQuery | None) -> list[tuple[int, int]]:
    """Character ranges in ``text`` that the query's positive clauses match, merged, in order."""
    if query is None or not query.must:
        return []
    tokens = words(text)
    folded = [t[0] for t in tokens]
    spans: list[tuple[int, int]] = []
    for clause in query.must:
        if isinstance(clause, Prefix):
            spans.extend((s, e) for w, s, e in tokens if w.startswith(clause.stem))
        elif isinstance(clause, Phrase):
            n = len(clause.words)
            for i in range(len(tokens) - n + 1):
                head = folded[i : i + n - 1] == list(clause.words[:-1])
                last = folded[i + n - 1]
                tail = (
                    last.startswith(clause.words[-1]) if clause.prefix else last == clause.words[-1]
                )
                if head and tail:
                    spans.append((tokens[i][1], tokens[i + n - 1][2]))
        else:
            a = [i for i, w in enumerate(folded) if w == clause.a]
            b = [i for i, w in enumerate(folded) if w == clause.b]
            for i in a:
                for j in b:
                    if i != j and abs(i - j) - 1 <= clause.distance:
                        spans.extend((tokens[k][1], tokens[k][2]) for k in (i, j))
    return _merge(spans)


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for start, end in sorted(set(spans)):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def _window_start(flat: str, spans: list[tuple[int, int]]) -> int:
    """Where the window should start: before the stretch holding the most matches."""
    if not spans:
        return 0
    best, best_count = spans[0][0], 0
    for start, _ in spans:
        count = sum(1 for s, e in spans if s >= start and e <= start + SNIPPET_CHARS - LEAD_CHARS)
        if count > best_count:
            best, best_count = start, count
    begin = max(0, best - LEAD_CHARS)
    if begin > 0:  # start on a word
        space = flat.find(" ", begin)
        begin = space + 1 if 0 <= space < best else begin
    return begin


def _open_window(flat: str, begin: int) -> str:
    budget = SNIPPET_CHARS - 2  # room for the ellipses
    end = min(len(flat), begin + budget)
    if end < len(flat):
        space = flat.rfind(" ", begin, end)
        end = space if space > begin else end
    body = flat[begin:end].strip()
    return ("…" if begin > 0 else "") + body + ("…" if end < len(flat) else "")


def snippet(
    text: str, tier: Tier | str, query: ParsedQuery | None
) -> tuple[str, list[tuple[int, int]]]:
    """A short excerpt of ``text`` around the query's matches, and the matches' offsets in it."""
    flat = _SPACE_RE.sub(" ", text).strip()
    begin = _window_start(flat, find_spans(flat, query))
    if Tier(tier) is Tier.OPEN:
        excerpt = _open_window(flat, begin)
    else:
        excerpt = policy.clip(flat, tier, around=(begin, begin))
    limit = min(SNIPPET_CHARS, policy.access_for(tier).snippet_chars)
    if len(excerpt) > limit:  # pragma: no cover - both paths stay inside it
        excerpt = excerpt[: limit - 1] + "…"
    return excerpt, find_spans(excerpt, query)
