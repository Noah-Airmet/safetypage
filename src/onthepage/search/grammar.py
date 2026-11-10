"""The concordance grammar: what a ``search`` query string means.

    sparse autoencoder        both words, anywhere in the unit (bare words are ANDed)
    "sparse autoencoder"      the words together, in this order
    "sparse auto*"            a phrase whose last word starts with ``auto``
    eval*                     any word starting with ``eval`` (at least 3 letters before the ``*``)
    refuse NEAR/5 harmful     both words, in either order, with at most 5 other words between
    refuse NEAR harmful       the same, with at most 10 words between
    -benchmark  -"red team"   the unit must not contain this word or phrase

Matching is on words: case is ignored, accents are folded (``café`` = ``cafe``), and anything
that is not a letter or digit separates words, so ``ASL-3`` is the two-word phrase ``asl 3``.
There is no stemming: ``refuse`` does not match ``refused`` (use ``refus*``). ``OR`` and
parentheses are not operators; a query that uses them is refused with a message saying so.

The parser is pure Python and knows nothing about Tantivy. :mod:`onthepage.search.lexical`
compiles the parsed query to Tantivy query objects, and :mod:`onthepage.search.highlight` finds
the same matches in a unit's text for snippets.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final

from onthepage.search.errors import QuerySyntaxError

__all__ = [
    "DEFAULT_NEAR",
    "MAX_NEAR",
    "MIN_PREFIX",
    "Clause",
    "Near",
    "ParsedQuery",
    "Phrase",
    "Prefix",
    "QuerySyntaxError",
    "fold",
    "parse_query",
    "words",
]

DEFAULT_NEAR: Final = 10
MAX_NEAR: Final = 50
MIN_PREFIX: Final = 3
MAX_CLAUSES: Final = 12
MAX_WORD_CHARS: Final = 40
"""Tantivy drops tokens this long or longer; so does the query side."""

_WORD_RE: Final = re.compile(r"[^\W_]+")
_NEAR_RE: Final = re.compile(r"NEAR(?:/(\d+))?")


def fold(word: str) -> str:
    """Lower-case and strip accents, as the index's analyzer does (``Café`` -> ``cafe``)."""
    decomposed = unicodedata.normalize("NFKD", word.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def words(text: str) -> list[tuple[str, int, int]]:
    """``text`` split into folded words with their character offsets, as the index sees it."""
    out: list[tuple[str, int, int]] = []
    for m in _WORD_RE.finditer(text):
        folded = fold(m.group())
        # Folding can expand a character (NFKD of a ligature); re-split what it produced.
        for part in _WORD_RE.findall(folded):
            if len(part.encode()) < MAX_WORD_CHARS:
                out.append((part, m.start(), m.end()))
    return out


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(w for w, _, _ in words(text))


@dataclass(frozen=True, slots=True)
class Phrase:
    """Words in order. One word is a phrase of one. ``prefix``: the last word is a prefix."""

    words: tuple[str, ...]
    prefix: bool = False

    def describe(self) -> str:
        text = " ".join(self.words) + ("*" if self.prefix else "")
        return text if len(self.words) == 1 else f'"{text}"'


@dataclass(frozen=True, slots=True)
class Prefix:
    """Any word starting with ``stem``. Kept apart from a one-word prefix phrase for clarity."""

    stem: str

    def describe(self) -> str:
        return f"{self.stem}* (any word starting with {self.stem!r})"


@dataclass(frozen=True, slots=True)
class Near:
    """``a`` and ``b`` in either order with at most ``distance`` other words between them."""

    a: str
    b: str
    distance: int

    def describe(self) -> str:
        return f"{self.a} within {self.distance} words of {self.b} (either order)"


Clause = Phrase | Prefix | Near


@dataclass(frozen=True, slots=True)
class ParsedQuery:
    must: tuple[Clause, ...]
    must_not: tuple[Clause, ...]

    @property
    def empty(self) -> bool:
        return not self.must and not self.must_not

    @property
    def bare_words(self) -> tuple[str, ...]:
        """Every positive word, for highlighting and for the disjunctive (hybrid) reading."""
        out: list[str] = []
        for clause in self.must:
            if isinstance(clause, Phrase):
                out.extend(clause.words)
            elif isinstance(clause, Prefix):
                out.append(clause.stem)
            else:
                out.extend((clause.a, clause.b))
        return tuple(out)

    def describe(self) -> str:
        if self.empty:
            return "no query: listing by the filters alone"
        parts = [c.describe() for c in self.must]
        text = "all of: " + "; ".join(parts) if len(parts) > 1 else "; ".join(parts)
        if self.must_not:
            text += "; none of: " + "; ".join(c.describe() for c in self.must_not)
        return text


# ---------------------------------------------------------------------------------------
# Lexing
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Lexeme:
    text: str
    quoted: bool
    negated: bool


def _lex(query: str) -> list[_Lexeme]:
    out: list[_Lexeme] = []
    i, n = 0, len(query)
    while i < n:
        c = query[i]
        if c.isspace():
            i += 1
            continue
        negated = False
        if c == "-" and i + 1 < n and not query[i + 1].isspace():
            negated = True
            i += 1
        if i < n and query[i] in '"“”':
            close = re.compile(r"[\"“”]").search(query, i + 1)
            end = n if close is None else close.start()
            out.append(_Lexeme(query[i + 1 : end], quoted=True, negated=negated))
            i = end + 1
            continue
        j = i
        while j < n and not query[j].isspace() and query[j] not in '"“”':
            j += 1
        out.append(_Lexeme(query[i:j], quoted=False, negated=negated))
        i = j
    return out


# ---------------------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------------------


def _phrase(text: str, *, quoted: bool) -> Clause | None:
    prefix = text.rstrip().endswith("*")
    body = text.rstrip().rstrip("*")
    tokens = _tokens(body)
    if not tokens:
        if quoted and text.strip():
            raise QuerySyntaxError(f'"{text}" has no letters or digits to search for.')
        return None
    if prefix and len(tokens[-1]) < MIN_PREFIX:
        raise QuerySyntaxError(
            f"{text!r}: a prefix needs at least {MIN_PREFIX} letters before the *, "
            f"so it does not match most of the dictionary."
        )
    if prefix and len(tokens) == 1:
        return Prefix(tokens[0])
    return Phrase(tokens, prefix=prefix)


def _near_operand(lexeme: _Lexeme, side: str) -> str:
    if lexeme.quoted or lexeme.negated or lexeme.text.endswith("*"):
        raise QuerySyntaxError(
            f"NEAR joins two plain words; the word {side} it is {lexeme.text!r}. "
            'Phrases, prefixes and -exclusions cannot be NEAR operands: write "a NEAR/5 b".'
        )
    tokens = _tokens(lexeme.text)
    if len(tokens) != 1:
        raise QuerySyntaxError(
            f"NEAR joins two single words; {lexeme.text!r} is {len(tokens)} words. "
            'Use a phrase in quotes for words that belong together: "a phrase".'
        )
    return tokens[0]


def parse_query(query: str) -> ParsedQuery:
    """Read a query string. Raises :class:`QuerySyntaxError` with a message for the agent."""
    lexemes = _lex(query)
    must: list[Clause] = []
    must_not: list[Clause] = []
    i = 0
    while i < len(lexemes):
        lexeme = lexemes[i]
        if not lexeme.quoted and lexeme.text in {"OR", "|", "||"}:
            raise QuerySyntaxError(
                "OR is not an operator here: every word in a query must appear. "
                "Run one search per alternative, or use a prefix (refus*)."
            )
        if not lexeme.quoted and (lexeme.text in {"AND", "&&"}):
            i += 1  # AND is what bare words already mean
            continue
        if not lexeme.quoted and any(c in lexeme.text for c in "()"):
            raise QuerySyntaxError(
                "Parentheses are not operators here. Bare words are ANDed; "
                'quote a phrase ("a phrase") and use -word to exclude.'
            )
        near = None if lexeme.quoted else _NEAR_RE.fullmatch(lexeme.text)
        if near is not None:
            if i == 0 or i + 1 >= len(lexemes) or not must:
                raise QuerySyntaxError("NEAR needs a word on each side: refuse NEAR/5 harmful.")
            distance = int(near.group(1)) if near.group(1) else DEFAULT_NEAR
            if distance > MAX_NEAR:
                raise QuerySyntaxError(f"NEAR/{distance} is too wide; the most is NEAR/{MAX_NEAR}.")
            left = _near_operand(lexemes[i - 1], "before")
            right = _near_operand(lexemes[i + 1], "after")
            must.pop()  # the left word, already read as a clause of its own
            must.append(Near(left, right, distance))
            i += 2
            continue
        clause = _phrase(lexeme.text, quoted=lexeme.quoted)
        if clause is not None:
            (must_not if lexeme.negated else must).append(clause)
        i += 1
    if must_not and not must:
        raise QuerySyntaxError(
            "A query needs at least one word that must appear; -word only excludes."
        )
    if len(must) + len(must_not) > MAX_CLAUSES:
        raise QuerySyntaxError(
            f"Too many terms ({len(must) + len(must_not)}); the most is {MAX_CLAUSES}. "
            "Quote the distinctive phrase instead of listing every word."
        )
    return ParsedQuery(tuple(must), tuple(must_not))
