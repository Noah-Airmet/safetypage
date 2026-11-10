"""The keyword index: Tantivy over the ``units`` view, one Tantivy document per page or block.

Only ``text`` is analysed. The analyzer splits on anything that is not a letter or digit,
lower-cases, folds accents and drops words of 40 bytes or more; no stemming and no stop words,
because this is a concordance. Catalogue fields are indexed raw for filtering and stored as fast
fields for facets. The unit text itself is not stored in the index: hits are looked up in the
snapshot's ``corpus.sqlite`` by ``version_id`` and anchor.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import tantivy
from tantivy import Occur, Query

from safetypage.corpus import Corpus
from safetypage.search.grammar import Near, ParsedQuery, Phrase, Prefix, words

__all__ = [
    "ANALYZER",
    "EXACT_TITLE_SCORE",
    "FACET_FIELDS",
    "LEXICAL_DIR",
    "RECORD_CLAUSE_SCORE",
    "UnitRow",
    "analyzer",
    "build_lexical_index",
    "compile_query",
    "date_key",
    "iter_unit_rows",
    "open_index",
    "record_query",
    "schema",
    "title_keys",
]

LEXICAL_DIR: Final = "lexical"
ANALYZER: Final = "otp"
FACET_FIELDS: Final = ("kind", "collection", "org", "tier")


def analyzer() -> tantivy.TextAnalyzer:
    return (
        tantivy.TextAnalyzerBuilder(tantivy.Tokenizer.simple())
        .filter(tantivy.Filter.remove_long(40))
        .filter(tantivy.Filter.lowercase())
        .filter(tantivy.Filter.ascii_fold())
        .build()
    )


def schema() -> tantivy.Schema:
    builder = tantivy.SchemaBuilder()
    builder.add_text_field("text", tokenizer_name=ANALYZER, index_option="position")
    # The catalogue record, on the first unit of each version only (see record_query).
    builder.add_text_field("title", tokenizer_name=ANALYZER, index_option="position")
    builder.add_text_field("byline", tokenizer_name=ANALYZER, index_option="position")
    builder.add_text_field("title_key", tokenizer_name="raw", index_option="basic")
    builder.add_text_field("cite", stored=True, tokenizer_name="raw")
    for name in ("doc_id", "ref", *FACET_FIELDS):
        builder.add_text_field(name, stored=False, fast=True, tokenizer_name="raw")
    builder.add_integer_field("version_id", stored=True, indexed=False, fast=False)
    builder.add_integer_field("date", indexed=True, fast=True)
    builder.add_integer_field("latest", indexed=True, fast=True)
    return builder.build()


def open_index(directory: Path) -> tantivy.Index:
    index = tantivy.Index.open(str(directory))
    index.register_tokenizer(ANALYZER, analyzer())
    return index


def date_key(date: str | None, *, end: bool = False) -> int:
    """``2023``, ``2023-05`` or ``2023-05-24`` as a sortable integer (``20230524``).

    Missing parts are 0, or 99 with ``end=True`` (the inclusive end of a month or year).
    Undated documents are 0, which no date filter matches.
    """
    if not date:
        return 0
    parts = [int(p) for p in date[:10].split("-")]
    year = parts[0]
    month = parts[1] if len(parts) > 1 else (99 if end else 0)
    day = parts[2] if len(parts) > 2 else (99 if end else 0)
    return year * 10_000 + month * 100 + day


@dataclass(frozen=True, slots=True)
class UnitRow:
    """One unit with the catalogue fields every arm filters on."""

    cite: str
    version_id: int
    text: str
    doc_id: str
    ref: str
    kind: str
    collection: str | None
    org: str | None
    tier: str
    date: int
    latest: bool
    title: str = ""
    byline: str = ""
    """Publisher and authors. ``title`` and ``byline`` are set on each version's first unit
    only, and only when the rows are read ``with_text``."""


def iter_unit_rows(corpus: Corpus, *, with_text: bool = True) -> Iterator[UnitRow]:
    """Every unit of the corpus, in a fixed order (document, version, unit order).

    This is the row order of the dense vectors as well, so both arms see the same units.
    """
    text = "u.text" if with_text else "'' AS text"
    rows = corpus.conn.execute(
        f"""
        SELECT u.cite, u.version_id, {text}, u.doc_id, u.doc_id || '/' || u.version AS ref,
               d.kind, d.collection, d.org, u.tier, d.published, d.title, d.authors,
               v.seq = (SELECT max(seq) FROM versions WHERE doc_id = u.doc_id) AS latest
          FROM units u
          JOIN versions v ON v.version_id = u.version_id
          JOIN documents d ON d.doc_id = u.doc_id
         ORDER BY u.doc_id, v.seq, u.seq
        """  # noqa: S608
    )
    previous = None
    for r in rows:
        first = with_text and r["version_id"] != previous
        previous = r["version_id"]
        authors: list[str] = json.loads(r["authors"] or "[]") if first else []
        yield UnitRow(
            cite=r["cite"],
            version_id=r["version_id"],
            text=r["text"],
            doc_id=r["doc_id"],
            ref=r["ref"],
            kind=r["kind"],
            collection=r["collection"],
            org=r["org"],
            tier=r["tier"],
            date=date_key(r["published"]),
            latest=bool(r["latest"]),
            title=r["title"] if first else "",
            byline=" ; ".join([r["org"] or "", *authors]).strip(" ;") if first else "",
        )


def build_lexical_index(corpus: Corpus, directory: Path, *, threads: int = 0) -> dict[str, Any]:
    """Write the index for every unit into ``directory``. Returns counts for the manifest."""
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    index = tantivy.Index(schema(), path=str(directory))
    index.register_tokenizer(ANALYZER, analyzer())
    writer = index.writer(heap_size=512_000_000, num_threads=threads)
    count = 0
    for row in iter_unit_rows(corpus):
        doc = tantivy.Document()
        doc.add_text("text", row.text)
        if row.title:
            doc.add_text("title", row.title)
        if row.byline:
            doc.add_text("byline", row.byline)
        for key in title_keys(row.title):
            doc.add_text("title_key", key)
        doc.add_text("cite", row.cite)
        doc.add_text("doc_id", row.doc_id)
        doc.add_text("ref", row.ref)
        doc.add_text("kind", row.kind)
        doc.add_text("tier", row.tier)
        if row.collection:
            doc.add_text("collection", row.collection)
        if row.org:
            doc.add_text("org", row.org)
        doc.add_integer("version_id", row.version_id)
        doc.add_integer("date", row.date)
        doc.add_integer("latest", int(row.latest))
        writer.add_document(doc)
        count += 1
    writer.commit()
    writer.wait_merging_threads()
    return {"units": count, "analyzer": "simple+remove_long(40)+lowercase+ascii_fold"}


# ---------------------------------------------------------------------------------------
# Compiling a parsed query
# ---------------------------------------------------------------------------------------


RECORD_CLAUSE_SCORE: Final = 8.0
"""What each query term found in a document's record (title, publisher, authors) adds to the
score of the document's first unit. A fixed score, not BM25: only first units carry a record,
so BM25's length normalisation, averaged over every unit, would make every title look long."""
EXACT_TITLE_SCORE: Final = 20.0
"""Added when the query is the whole title, or the main title (before a colon, a dash or a
parenthesis). Ties between records are broken by the title's own BM25, which is small (its
length normalisation is skewed, as above) but prefers the shorter, closer title."""
_MAIN_TITLE_RE: Final = re.compile(r":|\s[—–-]\s|\s\(")


def title_keys(title: str) -> list[str]:
    """The title and its main title, as folded words: what an exact-title query must equal."""
    keys = [" ".join(w for w, _, _ in words(title))]
    main = _MAIN_TITLE_RE.split(title, maxsplit=1)[0]
    keys.append(" ".join(w for w, _, _ in words(main)))
    return [k for k in dict.fromkeys(keys) if k]


def _clause(s: tantivy.Schema, clause: Phrase | Prefix | Near, field: str = "text") -> Query:
    if isinstance(clause, Prefix):
        return Query.regex_query(s, field, clause.stem + ".*")
    if isinstance(clause, Near):
        # Tantivy's slop is ordered (and charges 2 for a swap), so "either order, at most n
        # words between" is the union of both orders, each with slop n.
        return Query.boolean_query(
            [
                (
                    Occur.Should,
                    Query.phrase_query(s, field, [clause.a, clause.b], clause.distance),
                ),
                (
                    Occur.Should,
                    Query.phrase_query(s, field, [clause.b, clause.a], clause.distance),
                ),
            ]
        )
    if len(clause.words) == 1:
        return Query.term_query(s, field, clause.words[0])
    if clause.prefix:
        return Query.phrase_prefix_query(s, field, list(clause.words))
    return Query.phrase_query(s, field, list(clause.words))


def _text_part(s: tantivy.Schema, parsed: ParsedQuery, *, disjunctive: bool) -> Query:
    clauses: list[tuple[Occur, Query]] = []
    for clause in parsed.must:
        single_word = isinstance(clause, Phrase) and len(clause.words) == 1
        occur = Occur.Should if disjunctive and single_word else Occur.Must
        clauses.append((occur, _clause(s, clause)))
        if isinstance(clause, Phrase) and clause.prefix:
            # A phrase-prefix query scores every match the same; its whole words give BM25
            # something to rank by. They are present whenever the phrase matches.
            clauses.extend(
                (Occur.Should, Query.term_query(s, "text", w)) for w in clause.words[:-1]
            )
    if any(o is Occur.Should for o, _ in clauses):
        return Query.boolean_query(clauses, minimum_number_should_match=1)
    return Query.boolean_query(clauses)


def record_query(s: tantivy.Schema, parsed: ParsedQuery) -> Query:
    """Every positive clause found in the catalogue record (title, or publisher and authors),
    scored :data:`RECORD_CLAUSE_SCORE` a clause, plus :data:`EXACT_TITLE_SCORE` when the query
    is the title. Only first units carry a record: at most one match per version."""
    clauses: list[tuple[Occur, Query]] = [
        (
            Occur.Must,
            Query.const_score_query(
                Query.boolean_query(
                    [
                        (Occur.Should, _clause(s, clause, "title")),
                        (Occur.Should, _clause(s, clause, "byline")),
                    ]
                ),
                RECORD_CLAUSE_SCORE,
            ),
        )
        for clause in parsed.must
    ]
    clauses.extend((Occur.Should, _clause(s, clause, "title")) for clause in parsed.must)
    if all(isinstance(c, Phrase) and not c.prefix for c in parsed.must):
        exact = Query.term_query(s, "title_key", " ".join(parsed.bare_words))
        clauses.append((Occur.Should, Query.const_score_query(exact, EXACT_TITLE_SCORE)))
    return Query.boolean_query(clauses)


def compile_query(
    s: tantivy.Schema,
    parsed: ParsedQuery,
    filters: list[Query],
    *,
    disjunctive: bool = False,
    record_only: bool = False,
) -> Query:
    """The Tantivy query for a parsed concordance query plus filter queries.

    By default the query is matched against unit text. ``record_only`` matches it against the
    catalogue record instead (:func:`record_query`): the documents the query names. The backend
    puts a few of those ahead of the text ranking; see ``NAMED_FIRST`` there.
    ``disjunctive`` reads single words in the text as "any of" rather than "all of" (the lexical
    half of the hybrid arm, where the query is often a question); the record match stays "all
    of". Exclusions apply to the text. Filters never change the score.
    """
    clauses: list[tuple[Occur, Query]] = []
    if parsed.must and record_only:
        clauses.append((Occur.Must, record_query(s, parsed)))
    elif parsed.must:
        clauses.append((Occur.Must, _text_part(s, parsed, disjunctive=disjunctive)))
    else:
        clauses.append((Occur.Must, Query.all_query()))
    clauses.extend((Occur.MustNot, _clause(s, c)) for c in parsed.must_not)
    clauses.extend((Occur.Must, Query.const_score_query(f, 0.0)) for f in filters)
    return Query.boolean_query(clauses)
