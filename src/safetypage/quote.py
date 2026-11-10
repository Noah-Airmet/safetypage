"""Quote verification: does this text say these words, and where?

Deterministic, code only, no model. The same function backs the ``verify_quote`` tool, the
``check_answer`` tool, the reader's highlight and the benchmark's quote-fidelity scorer, so an
agent's in-run verdict and the scorer's verdict cannot disagree.

How it works
------------
1. **Skeleton.** Both the quote and the source are reduced to case-folded letters and digits,
   after NFKC (which folds ligatures, full-width forms and the math-italic letters PDF text layers
   are full of) and with diacritics, soft hyphens and zero-width characters dropped. Every
   skeleton character remembers the source offset it came from, so a match maps back to the
   source's own characters. This removes line breaks, hyphenation, quote and dash styles and
   spacing in one move.
2. **Whole words.** A match must start and end on a word boundary of the source. Without this,
   ``able to refuse`` would be found inside ``unable to refuse``, and ``5% of cases`` inside
   ``3.5% of cases``.
3. **Contiguous.** The quoted words must be consecutive in the source. There is no tolerance for
   skipped words: ``the model does reliably refuse`` is not in ``the model does not reliably
   refuse``. (The checker this replaces allowed three stray words between quoted words and passed
   exactly that.)
4. **Ellipses.** ``...``, ``…``, ``[...]`` and bracketed editorial insertions (``[the model]``)
   split a quote into fragments. Every fragment must be found, in order.
5. **Graded verdict.** ``exact`` and ``normalized`` pass. ``elsewhere``, ``near_miss`` and
   ``not_found`` fail; a near miss comes with the source's wording and a word diff so the quote
   can be fixed, and it is never a pass.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from array import array
from bisect import bisect_left
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Final, Literal

from rapidfuzz import fuzz

__all__ = [
    "MIN_QUOTE_CHARS",
    "NEAR_MISS_CUTOFF",
    "PASSING",
    "DiffOp",
    "QuoteResult",
    "QuoteTooShortError",
    "SegmentResult",
    "Skeleton",
    "Span",
    "Verdict",
    "skeleton",
    "split_quote",
    "verify_quote",
]


class Verdict(StrEnum):
    """The one verdict vocabulary. Only the first two pass."""

    EXACT = "exact"
    """Found where cited, character for character once runs of whitespace are collapsed."""
    NORMALIZED = "normalized"
    """Found where cited after normalisation: case, punctuation, quote marks, hyphenation,
    ligatures, line breaks. The words are the source's words."""
    ELSEWHERE = "elsewhere"
    """The words are in this document, but not at the cited anchor. Fails: the citation is wrong.
    The result says where they really are."""
    NEAR_MISS = "near_miss"
    """Something close is there, but not these words. Fails. Comes with the source's wording."""
    NOT_FOUND = "not_found"
    """Nothing close enough to report."""


PASSING: Final = frozenset({Verdict.EXACT, Verdict.NORMALIZED})

MIN_QUOTE_CHARS: Final = 10
"""A quote must have at least this many letters and digits; less is a term, not a quotation."""

NEAR_MISS_CUTOFF: Final = 80.0
"""Similarity (0-100) at which a failed fragment is reported as a near miss. Diagnostic only:
it decides which failing verdict is shown, never whether a quote passes."""

MAX_OTHER_LOCATIONS: Final = 10


class QuoteTooShortError(ValueError):
    """The quote has too few letters and digits to be checked."""


# --------------------------------------------------------------------------------------
# Skeleton
# --------------------------------------------------------------------------------------

_IGNORABLE: Final = frozenset("\u00ad\u200b\u200c\u200d\u2060\ufeff")
_HYPHENS: Final = frozenset("-\u2010\u2011")
_LINE_BREAKS: Final = frozenset("\n\r\f\v\u0085\u2028\u2029")


@lru_cache(maxsize=8192)
def _fold(ch: str) -> str:
    """The skeleton characters one source character contributes (possibly none, possibly two)."""
    out: list[str] = []
    for c in unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", ch)):
        if unicodedata.combining(c):
            continue
        out.extend(f for f in c.casefold() if f.isalnum())
    return "".join(out)


@dataclass(frozen=True, slots=True)
class Skeleton:
    """A text reduced to case-folded letters and digits, with a map back to source offsets."""

    source: str
    text: str
    offsets: array[int]
    """``offsets[i]`` is the index in ``source`` of the character ``text[i]`` came from.
    Non-decreasing; equal for neighbours that came from one source character (``ﬁ`` -> ``fi``)."""

    def __len__(self) -> int:
        return len(self.text)

    def index_at(self, source_offset: int) -> int:
        """The first skeleton index whose source offset is at or after ``source_offset``."""
        return bisect_left(self.offsets, source_offset)

    def source_span(self, start: int, end: int) -> tuple[int, int]:
        """Source offsets covered by skeleton range ``[start, end)`` (first to last character)."""
        return self.offsets[start], self.offsets[end - 1] + 1

    def joined(self, i: int) -> bool:
        """Whether skeleton characters ``i - 1`` and ``i`` belong to the same word in the source."""
        if i <= 0 or i >= len(self.text):
            return False
        a, b = self.offsets[i - 1], self.offsets[i]
        if b <= a:
            return True  # both came from one source character
        gap = [
            c
            for c in self.source[a + 1 : b]
            if c not in _IGNORABLE and not unicodedata.combining(c)
        ]
        if not gap:
            return True
        if len(gap) == 1:
            if gap[0] in _HYPHENS:
                return True  # non-trivial, state-of-the-art: one word
            # 3.5 and 1,000 are one number
            return gap[0] in ".," and self.source[a].isdigit() and self.source[b].isdigit()
        # a word hyphenated across a line or page break: "un-\nable"
        return (
            gap[0] in _HYPHENS
            and all(c.isspace() for c in gap[1:])
            and any(c in _LINE_BREAKS for c in gap[1:])
        )

    def on_word_boundaries(self, start: int, end: int) -> bool:
        return not self.joined(start) and not self.joined(end)

    def widen_to_words(self, start: int, end: int) -> tuple[int, int]:
        while self.joined(start):
            start -= 1
        while self.joined(end):
            end += 1
        return start, end


def skeleton(source: str) -> Skeleton:
    """Reduce ``source`` to its skeleton, keeping the offset of every character kept."""
    out: list[str] = []
    offsets = array("L")
    for i, ch in enumerate(source):
        if ch < "\x80":
            if ch.isalnum():
                out.append(ch.lower())
                offsets.append(i)
            continue
        if ch in _IGNORABLE:
            continue
        for f in _fold(ch):
            out.append(f)
            offsets.append(i)
    return Skeleton(source, "".join(out), offsets)


# --------------------------------------------------------------------------------------
# Splitting a quote into fragments
# --------------------------------------------------------------------------------------

_DOTS: Final = r"(?:\.(?:\s?\.){2,3}|…)"
_GAP_RE: Final = re.compile(
    rf"\[\s*{_DOTS}\s*\]"  # [...]
    rf"|\(\s*{_DOTS}\s*\)"  # (...)
    rf"|{_DOTS}"  # ... or …
    r"|\[[^\[\]]{2,80}\]"  # [the model], [sic], [emphasis added]
)


def split_quote(quote: str) -> list[str]:
    """Split a quote at ellipses and bracketed editorial insertions.

    Each returned fragment is trimmed to its first and last letter or digit, so surrounding quote
    marks and trailing punctuation are not part of what must match. A single bracketed letter
    (``[T]he``) is not a gap: the brackets simply vanish in the skeleton.
    """
    fragments: list[str] = []
    for piece in _GAP_RE.split(quote):
        sk = skeleton(piece)
        if len(sk) == 0:
            continue
        start, end = sk.source_span(0, len(sk))
        fragments.append(piece[start:end])
    return fragments


def _collapse(text: str) -> str:
    return " ".join(text.split())


# --------------------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Span:
    """A stretch of the source: ``source[start:end]``, with its own text."""

    start: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class DiffOp:
    """One difference between the quote and the nearest source wording, in words."""

    op: Literal["replace", "delete", "insert"]
    """``replace``: the quote says ``quote`` where the source says ``source``.
    ``delete``: the quote has words the source does not. ``insert``: the source has words the
    quote left out."""
    quote: str
    source: str


@dataclass(frozen=True, slots=True)
class SegmentResult:
    """How one fragment of the quote fared."""

    quote: str
    verdict: Verdict
    """``exact`` / ``normalized`` (found), ``near_miss`` or ``not_found``."""
    span: Span | None
    """Where it was found, or the nearest wording for a near miss."""
    diff: tuple[DiffOp, ...] = ()
    similarity: float | None = None


@dataclass(frozen=True, slots=True)
class QuoteResult:
    verdict: Verdict
    segments: tuple[SegmentResult, ...]
    reason: str
    """One sentence a person or an agent can act on."""
    in_scope: bool
    """Whether the match lies inside the cited scope (always true when no scope was given)."""
    other_spans: tuple[Span, ...] = ()
    """Other places a single-fragment quote also occurs (the quote is ambiguous if non-empty)."""

    @property
    def passed(self) -> bool:
        return self.verdict in PASSING

    @property
    def ambiguous(self) -> bool:
        return bool(self.other_spans)

    @property
    def spans(self) -> tuple[Span, ...]:
        return tuple(s.span for s in self.segments if s.span is not None)


# --------------------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------------------


def _find_whole(sk: Skeleton, needle: str, lo: int, hi: int) -> tuple[int, int]:
    """First whole-word occurrence of ``needle`` in skeleton range ``[lo, hi)``.

    Returns ``(found, inside_word)``: the index of the first occurrence on word boundaries (or
    -1), and the index of the first occurrence that is *not* on word boundaries (or -1), which is
    worth reporting when nothing better exists.
    """
    inside_word = -1
    pos = lo
    while True:
        i = sk.text.find(needle, pos, hi)
        if i < 0:
            return -1, inside_word
        if sk.on_word_boundaries(i, i + len(needle)):
            return i, inside_word
        if inside_word < 0:
            inside_word = i
        pos = i + 1


def _match_in_order(sk: Skeleton, needles: list[str], lo: int, hi: int) -> list[int] | None:
    """Leftmost in-order placement of every needle in ``[lo, hi)``, or None.

    Taking the earliest whole-word occurrence of each fragment is safe: an earlier placement
    never rules out a later fragment that a later placement would have allowed.
    """
    starts: list[int] = []
    pos = lo
    for needle in needles:
        i, _ = _find_whole(sk, needle, pos, hi)
        if i < 0:
            return None
        starts.append(i)
        pos = i + len(needle)
    return starts


def _span(sk: Skeleton, start: int, end: int) -> Span:
    a, b = sk.source_span(start, end)
    return Span(a, b, sk.source[a:b])


def _grade(fragment: str, span: Span) -> Verdict:
    return Verdict.EXACT if _collapse(fragment) == _collapse(span.text) else Verdict.NORMALIZED


def _word_diff(quote: str, source: str) -> tuple[DiffOp, ...]:
    q_words, s_words = quote.split(), source.split()
    q_keys = [skeleton(w).text for w in q_words]
    s_keys = [skeleton(w).text for w in s_words]
    ops: list[DiffOp] = []
    matcher = difflib.SequenceMatcher(a=q_keys, b=s_keys, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        ops.append(DiffOp(tag, " ".join(q_words[i1:i2]), " ".join(s_words[j1:j2])))
    return tuple(ops)


def _diagnose(
    sk: Skeleton, fragment: str, needle: str, ranges: list[tuple[int, int]]
) -> SegmentResult:
    """Explain a fragment that could not be placed: found out of order, near miss, or absent."""
    for lo, hi in ranges:
        found, inside_word = _find_whole(sk, needle, lo, hi)
        if found >= 0:
            span = _span(sk, found, found + len(needle))
            return SegmentResult(fragment, _grade(fragment, span), span)
        if inside_word >= 0:
            start, end = sk.widen_to_words(inside_word, inside_word + len(needle))
            span = _span(sk, start, end)
            return SegmentResult(
                fragment, Verdict.NEAR_MISS, span, _word_diff(fragment, span.text), None
            )
    for lo, hi in ranges:
        if hi - lo < len(needle):
            continue
        alignment = fuzz.partial_ratio_alignment(
            needle, sk.text[lo:hi], score_cutoff=NEAR_MISS_CUTOFF
        )
        if alignment is None or alignment.dest_end <= alignment.dest_start:
            continue
        start, end = sk.widen_to_words(lo + alignment.dest_start, lo + alignment.dest_end)
        span = _span(sk, start, end)
        return SegmentResult(
            fragment,
            Verdict.NEAR_MISS,
            span,
            _word_diff(fragment, span.text),
            round(alignment.score, 1),
        )
    return SegmentResult(fragment, Verdict.NOT_FOUND, None)


def _others(sk: Skeleton, needle: str, lo: int, hi: int, chosen: int) -> tuple[Span, ...]:
    """Every other whole-word occurrence of a single-fragment quote in ``[lo, hi)``."""
    spans: list[Span] = []
    pos = lo
    while len(spans) < MAX_OTHER_LOCATIONS:
        i, _ = _find_whole(sk, needle, pos, hi)
        if i < 0:
            break
        if i != chosen:
            spans.append(_span(sk, i, i + len(needle)))
        pos = i + 1
    return tuple(spans)


def verify_quote(
    quote: str,
    source: str | Skeleton,
    *,
    scope: tuple[int, int] | None = None,
) -> QuoteResult:
    """Check ``quote`` against ``source``.

    ``scope`` is the cited part of the source as ``(start, end)`` character offsets (a page, a
    paragraph). With a scope, a quote found only outside it gets ``elsewhere``. Without one, the
    whole source is the scope.

    Pass a prebuilt :class:`Skeleton` when checking many quotes against one document.

    Raises :class:`QuoteTooShortError` if the quote has fewer than :data:`MIN_QUOTE_CHARS`
    letters and digits.
    """
    sk = source if isinstance(source, Skeleton) else skeleton(source)
    fragments = split_quote(quote)
    needles = [skeleton(f).text for f in fragments]
    if sum(len(n) for n in needles) < MIN_QUOTE_CHARS:
        raise QuoteTooShortError(
            f"quote too short to check: it needs at least {MIN_QUOTE_CHARS} letters or digits"
        )

    whole: tuple[int, int] = (0, len(sk))
    cited = whole
    if scope is not None:
        start, end = scope
        if start < 0 or end < start or end > len(sk.source):
            raise ValueError(f"scope {scope} is outside the source (length {len(sk.source)})")
        cited = (sk.index_at(start), sk.index_at(end))

    def found(starts: list[int], search: tuple[int, int], in_scope: bool) -> QuoteResult:
        segments = tuple(
            SegmentResult(f, _grade(f, span), span)
            for f, span in (
                (f, _span(sk, s, s + len(n)))
                for f, n, s in zip(fragments, needles, starts, strict=True)
            )
        )
        others = (
            _others(sk, needles[0], search[0], search[1], starts[0]) if len(needles) == 1 else ()
        )
        if not in_scope:
            return QuoteResult(
                Verdict.ELSEWHERE,
                segments,
                "The quoted words are in this document, but not at the cited place.",
                in_scope=False,
                other_spans=others,
            )
        if all(s.verdict is Verdict.EXACT for s in segments):
            return QuoteResult(
                Verdict.EXACT, segments, "Found, word for word.", in_scope=True, other_spans=others
            )
        return QuoteResult(
            Verdict.NORMALIZED,
            segments,
            "Found. The words match; spacing, punctuation, case or hyphenation differ.",
            in_scope=True,
            other_spans=others,
        )

    def place(search: tuple[int, int]) -> list[int] | None:
        starts = _match_in_order(sk, needles, *search)
        if starts is None or len(needles) > 1:
            return starts
        # One fragment that occurs more than once: prefer a character-for-character occurrence
        # over an earlier one that only matches after normalisation.
        first = _span(sk, starts[0], starts[0] + len(needles[0]))
        if _grade(fragments[0], first) is Verdict.EXACT:
            return starts
        pos = starts[0] + 1
        for _ in range(MAX_OTHER_LOCATIONS):
            i, _inside = _find_whole(sk, needles[0], pos, search[1])
            if i < 0:
                break
            if _grade(fragments[0], _span(sk, i, i + len(needles[0]))) is Verdict.EXACT:
                return [i]
            pos = i + 1
        return starts

    starts = place(cited)
    if starts is not None:
        return found(starts, cited, in_scope=True)
    if cited != whole:
        starts = place(whole)
        if starts is not None:
            return found(starts, whole, in_scope=False)

    ranges: list[tuple[int, int]] = [cited, whole] if cited != whole else [whole]
    segments = tuple(_diagnose(sk, f, n, ranges) for f, n in zip(fragments, needles, strict=True))
    if any(s.verdict is Verdict.NOT_FOUND for s in segments):
        return QuoteResult(
            Verdict.NOT_FOUND,
            segments,
            "Not found. The quotation may be a paraphrase, a misattribution, or from another "
            "document.",
            in_scope=False,
        )
    if all(s.verdict in PASSING for s in segments):
        reason = "Every fragment is in the source, but not in the quoted order."
    else:
        reason = "Close, but not what the source says. Compare the source's wording."
    return QuoteResult(Verdict.NEAR_MISS, segments, reason, in_scope=False)
