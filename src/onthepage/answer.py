"""Reading a written answer: which citations it makes, which quotations, and which go together.

``check_answer`` (the tool) and the benchmark's scorers both go through :func:`parse_answer`, so
"the quotation attached to this citation" means the same thing to an agent checking its draft and
to the leaderboard.

The rules, in full:

* A citation is a canonical URL or a bare cite string (:func:`onthepage.ids.find_citations`).
* A quotation is a markdown blockquote (lines starting with ``>``) or text inside double quotation
  marks (``"..."`` or ``“...”``) with at least :data:`onthepage.quote.MIN_QUOTE_CHARS` letters
  and digits. Inline quotation marks around one or two words are a term, not a quotation.
* A blockquote belongs to the first citation inside it; failing that, to the first citation on
  the next non-blank line.
* An inline quotation belongs to the nearest citation after it in the same paragraph; failing
  that, to the nearest one before it in the same paragraph.
* Anything else is an unattached quotation: reported, and not counted as verified.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from onthepage.ids import FoundCitation, find_citations
from onthepage.quote import MIN_QUOTE_CHARS, skeleton

__all__ = ["AnswerQuote", "ParsedAnswer", "parse_answer"]

MIN_INLINE_WORDS: Final = 3
_INLINE_RE: Final = re.compile(r"“([^“”]{1,4000})”|\"([^\"]{1,4000})\"")
_MD_LINK_RE: Final = re.compile(r"\[([^\]]*)\]\([^)\s]*\)")
_URL_RE: Final = re.compile(r"https?://\S+")
_BLOCKQUOTE_RE: Final = re.compile(r"^[ \t]{0,3}>[ \t]?", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class AnswerQuote:
    text: str
    start: int
    end: int
    citation: FoundCitation | None


@dataclass(frozen=True, slots=True)
class ParsedAnswer:
    citations: tuple[FoundCitation, ...]
    quotes: tuple[AnswerQuote, ...]


def _lines(text: str) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    pos = 0
    for line in text.split("\n"):
        out.append((pos, pos + len(line), line))
        pos += len(line) + 1
    return out


def _clean(quote: str) -> str:
    quote = _MD_LINK_RE.sub(r"\1", quote)
    quote = _URL_RE.sub(" ", quote)
    return " ".join(quote.split())


def _long_enough(quote: str) -> bool:
    return len(skeleton(quote)) >= MIN_QUOTE_CHARS


def parse_answer(text: str) -> ParsedAnswer:
    citations = find_citations(text)
    lines = _lines(text)
    quotes: list[AnswerQuote] = []
    block_ranges: list[tuple[int, int]] = []

    def first_in(start: int, end: int) -> FoundCitation | None:
        return next((c for c in citations if start <= c.start < end), None)

    # Blockquotes.
    i = 0
    while i < len(lines):
        if not _BLOCKQUOTE_RE.match(lines[i][2]):
            i += 1
            continue
        j = i
        while j < len(lines) and _BLOCKQUOTE_RE.match(lines[j][2]):
            j += 1
        start, end = lines[i][0], lines[j - 1][1]
        block_ranges.append((start, end))
        body = _BLOCKQUOTE_RE.sub("", text[start:end])
        for found in find_citations(body):
            body = body.replace(found.raw, " ")
        body = _clean(body).strip('"“” ')
        citation = first_in(start, end)
        if citation is None:
            following = next((ln for ln in lines[j:] if ln[2].strip()), None)
            if following is not None:
                citation = first_in(following[0], following[1])
        if _long_enough(body):
            quotes.append(AnswerQuote(body, start, end, citation))
        i = j

    # Inline quotations, paragraph by paragraph.
    paragraphs: list[tuple[int, int]] = []
    para_start: int | None = None
    para_end = 0
    for start, end, line in lines:
        if line.strip():
            if para_start is None:
                para_start = start
            para_end = end
        else:
            if para_start is not None:
                paragraphs.append((para_start, para_end))
            para_start = None
    if para_start is not None:
        paragraphs.append((para_start, para_end))

    for p_start, p_end in paragraphs:
        in_para = [c for c in citations if p_start <= c.start < p_end]
        for m in _INLINE_RE.finditer(text, p_start, p_end):
            if any(s <= m.start() < e for s, e in block_ranges):
                continue
            if any(c.start <= m.start() < c.end for c in in_para):
                continue  # a quotation mark inside a URL
            body = _clean(m.group(1) or m.group(2) or "")
            if not _long_enough(body) or len(body.split()) < MIN_INLINE_WORDS:
                continue
            after = next((c for c in in_para if c.start >= m.end()), None)
            before = next((c for c in reversed(in_para) if c.end <= m.start()), None)
            quotes.append(AnswerQuote(body, m.start(), m.end(), after or before))

    quotes.sort(key=lambda q: q.start)
    return ParsedAnswer(tuple(citations), tuple(quotes))
