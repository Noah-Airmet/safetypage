"""Search over one sealed snapshot: :class:`SnapshotSearch` implements ``SearchBackend``.

Arms:

- ``bm25``: the concordance (:mod:`safetypage.search.grammar`) over the Tantivy index, ranked
  by BM25. Always available.
- ``dense``: the query's embedding against every unit's vector (exact search).
- ``hybrid``: reciprocal rank fusion (k = 60) of the top 100 of each: ``bm25`` with single
  words read as "any of", and ``dense``.

``dense`` and ``hybrid`` need ``dense/<model>/`` in the snapshot. Without it they fall back to
``bm25``, and the response says so (its ``arm`` is ``bm25`` and its ``interpretation`` names
the fallback). ``hybrid-rerank`` and ``contextual`` are not built in this version; asking for
them raises :class:`ArmUnavailableError`.

Every search runs on a small thread pool with a concurrency cap and a per-query time limit
(:class:`Limits`). A query over the limit gets :class:`SearchTimeoutError`; its work runs to
the end in the background but keeps its slot until then, so slow queries cannot pile up past
the cap.
"""

from __future__ import annotations

import concurrent.futures
import re
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final, cast

import numpy as np
import numpy.typing as npt
import tantivy
from tantivy import Occur, Query

from safetypage.api import DocumentHit, Hit, SearchRequest, SearchResponse
from safetypage.corpus import Corpus, NotFoundError
from safetypage.ids import Anchor, Citation, DocId, IdError, Ref, parse_ref, source_link
from safetypage.model import Document, Version
from safetypage.search.dense import DenseIndex, Embedder, SentenceTransformerEmbedder
from safetypage.search.errors import (
    ArmUnavailableError,
    FilterError,
    QuerySyntaxError,
    SearchBusyError,
    SearchTimeoutError,
)
from safetypage.search.grammar import ParsedQuery, Phrase, parse_query, words
from safetypage.search.highlight import snippet
from safetypage.search.lexical import (
    FACET_FIELDS,
    LEXICAL_DIR,
    compile_query,
    date_key,
    iter_unit_rows,
    open_index,
)
from safetypage.snapshot import CORPUS_DB, load_manifest

__all__ = ["RRF_K", "Limits", "SnapshotSearch"]

RRF_K: Final = 60
FUSION_DEPTH: Final = 100
DOCUMENT_DEPTH: Final = 200
"""``documents`` mode for dense and hybrid groups this many top units by document."""
TOP_PER_DOCUMENT: Final = 3
NAMED_FIRST: Final = 3
"""bm25 and hybrid put up to this many documents whose title, publisher or authors hold the
whole query ahead of the text ranking, each at its first page or block. Few, so a topic query
("reward hacking") still shows passages, not a page of title pages."""
_DATE_RE: Final = re.compile(r"[0-9]{4}(-[0-9]{2}(-[0-9]{2})?)?")
_NOT_BUILT: Final = {"hybrid-rerank", "contextual"}


@dataclass(frozen=True, slots=True)
class Limits:
    time_limit_s: float = 2.0
    """Longest a query may run before the caller gets :class:`SearchTimeoutError`."""
    max_concurrent: int = 8
    """Searches running at once, per snapshot."""
    queue_wait_s: float = 1.0
    """How long a search waits for a free slot before :class:`SearchBusyError`."""
    max_results: int = 250
    """How deep paging may go (``offset + limit``)."""


@dataclass(frozen=True, slots=True)
class _Filters:
    doc_id: str | None = None
    ref: str | None = None
    kind: str | None = None
    collection: str | None = None
    org: str | None = None
    tier: str | None = None
    date_lo: int | None = None
    date_hi: int | None = None
    latest_only: bool = True

    def describe(self) -> str:
        parts = [
            f"{name} = {value}"
            for name, value in (
                ("document", self.ref or self.doc_id),
                ("kind", self.kind),
                ("collection", self.collection),
                ("org", self.org),
                ("tier", self.tier),
            )
            if value
        ]
        if self.date_lo or self.date_hi:
            parts.append(f"dated {self.date_lo or '…'} to {self.date_hi or '…'} (YYYYMMDD)")
        parts.append("latest versions only" if self.latest_only else "all versions")
        return "Filters: " + ", ".join(parts)

    def queries(self, s: tantivy.Schema) -> list[Query]:
        out = [
            Query.term_query(s, name, value)
            for name, value in (
                ("doc_id", self.doc_id),
                ("ref", self.ref),
                ("kind", self.kind),
                ("collection", self.collection),
                ("org", self.org),
                ("tier", self.tier),
            )
            if value is not None
        ]
        if self.date_lo is not None or self.date_hi is not None:
            out.append(
                Query.range_query(
                    s, "date", tantivy.FieldType.Integer, self.date_lo or 1, self.date_hi
                )
            )
        if self.latest_only:
            out.append(Query.term_query(s, "latest", 1))
        return out


class _Columns:
    """Catalogue fields per dense row, as arrays, so filters become masks."""

    def __init__(self, corpus: Corpus, cites: list[str]) -> None:
        rows = {r.cite: r for r in iter_unit_rows(corpus, with_text=False)}
        ordered = [rows[c] for c in cites]
        self.version_id = np.array([r.version_id for r in ordered], dtype=np.int64)
        self.date = np.array([r.date for r in ordered], dtype=np.int64)
        self.latest = np.array([r.latest for r in ordered], dtype=np.bool_)
        self.codes: dict[str, tuple[dict[str, int], npt.NDArray[np.int32]]] = {}
        for name in ("doc_id", "ref", "kind", "collection", "org", "tier"):
            values = [getattr(r, name) or "" for r in ordered]
            table: dict[str, int] = {}
            codes = np.array([table.setdefault(v, len(table)) for v in values], dtype=np.int32)
            self.codes[name] = (table, codes)

    def mask(self, f: _Filters) -> npt.NDArray[np.bool_]:
        out = np.ones(len(self.date), dtype=np.bool_)
        for name in ("doc_id", "ref", "kind", "collection", "org", "tier"):
            value = getattr(f, name)
            if value is not None:
                table, codes = self.codes[name]
                out &= codes == table.get(value, -1)
        if f.date_lo is not None or f.date_hi is not None:
            out &= self.date >= (f.date_lo or 1)
            if f.date_hi is not None:
                out &= self.date <= f.date_hi
        if f.latest_only:
            out &= self.latest
        return out


@dataclass(frozen=True, slots=True)
class _Ranked:
    cite: str
    version_id: int
    score: float


def _lenient(query: str) -> ParsedQuery | None:
    """The query as a concordance if it parses, else its words; for highlighting and hybrid."""
    try:
        return parse_query(query)
    except QuerySyntaxError:
        unique = dict.fromkeys(w for w, _, _ in words(query))
        return ParsedQuery(tuple(Phrase((w,)) for w in unique), ()) if unique else None


class SnapshotSearch:
    """The ``SearchBackend`` for one sealed snapshot directory."""

    def __init__(
        self,
        directory: Path,
        *,
        base_url: str = "http://localhost:8000",
        limits: Limits | None = None,
        embedder: Embedder | None = None,
        dense_model: str | None = None,
    ) -> None:
        self.directory = directory
        self.base_url = base_url.rstrip("/")
        self.limits = limits or Limits()
        self._snapshot = load_manifest(directory).snapshot_id
        self._index = open_index(directory / LEXICAL_DIR)
        self._schema = self._index.schema
        self._searcher = self._index.searcher()
        # Indexes built before titles were indexed have no record fields; search them as text.
        try:
            Query.term_query(self._schema, "title_key", "")
            self._has_record = True
        except ValueError:
            self._has_record = False
        self._local = threading.local()
        self._opened: list[Corpus] = []
        self._opened_lock = threading.Lock()
        Corpus.open(directory / CORPUS_DB, readonly=True).close()  # refuses a stale schema
        self._versions: dict[str, tuple[Document, Version]] = {}
        corpus = self._corpus()
        self._known = {
            name: {
                str(v).casefold(): str(v)
                for (v,) in corpus.conn.execute(
                    f"SELECT DISTINCT {name} FROM documents WHERE {name} IS NOT NULL"  # noqa: S608
                )
            }
            for name in ("collection", "org")
        }
        self._dense: DenseIndex | None = None
        self._columns: _Columns | None = None
        self._embedder: Embedder | None = None
        dense_dirs = sorted(p.parent for p in (directory / "dense").glob("*/model.json"))
        if dense_model is not None:
            dense_dirs = [d for d in dense_dirs if d.name == dense_model]
        if dense_dirs:
            self._dense = DenseIndex(dense_dirs[0])
            self._columns = _Columns(corpus, self._dense.cites)
            self._embedder = embedder or SentenceTransformerEmbedder(
                self._dense.model, device="cpu"
            )
        self._slots = threading.BoundedSemaphore(self.limits.max_concurrent)
        self._pool = concurrent.futures.ThreadPoolExecutor(
            self.limits.max_concurrent, thread_name_prefix=f"search-{self._snapshot}"
        )

    # ------------------------------------------------------------------ the protocol

    @property
    def snapshot(self) -> str:
        return self._snapshot

    @property
    def arms(self) -> tuple[str, ...]:
        return ("bm25", "dense", "hybrid") if self._dense is not None else ("bm25",)

    def search(self, request: SearchRequest) -> SearchResponse:
        """Answer ``request`` within the time limit, or raise a :class:`SearchError`."""
        if not self._slots.acquire(timeout=self.limits.queue_wait_s):
            raise SearchBusyError("The search service is busy; try again in a few seconds.")
        try:
            future = self._pool.submit(self._run, request)
        except BaseException:
            self._slots.release()
            raise
        future.add_done_callback(lambda _: self._slots.release())
        try:
            return future.result(timeout=self.limits.time_limit_s)
        except concurrent.futures.TimeoutError:
            raise SearchTimeoutError(
                f"The query took longer than {self.limits.time_limit_s:g} s and was stopped. "
                "Phrases of very common words are slow: add a rarer word, or filter by "
                "document, kind or date."
            ) from None

    def close(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=True)
        with self._opened_lock:
            for corpus in self._opened:
                corpus.close()
            self._opened.clear()

    # ------------------------------------------------------------------ plumbing

    def _corpus(self) -> Corpus:
        corpus: Corpus | None = getattr(self._local, "corpus", None)
        if corpus is None:
            # One read-only connection per thread. check_same_thread is off only so close()
            # can shut every thread's connection; each is used by its own thread alone.
            uri = f"{(self.directory / CORPUS_DB).resolve().as_uri()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
            corpus = Corpus(conn, base_url=self.base_url)
            self._local.corpus = corpus
            with self._opened_lock:
                self._opened.append(corpus)
        return corpus

    def _version(self, ref: str) -> tuple[Document, Version]:
        found = self._versions.get(ref)
        if found is None:
            resolved = self._corpus().resolve(ref)
            found = (resolved.document, resolved.version)
            self._versions[ref] = found
        return found

    def _arm(self, arm: str) -> tuple[str, str]:
        if arm in _NOT_BUILT:
            raise ArmUnavailableError(
                f"The {arm} arm is not available in snapshot {self._snapshot}. "
                f"Arms here: {', '.join(self.arms)}."
            )
        if arm in {"dense", "hybrid"} and self._dense is None:
            return "bm25", f" No vectors are built for this snapshot, so {arm} fell back to bm25."
        return arm, ""

    def _filters(self, request: SearchRequest) -> _Filters:
        doc_id = ref = None
        if request.doc:
            try:
                given = parse_ref(request.doc)
            except IdError as exc:
                raise FilterError(f"doc={request.doc!r}: {exc}") from None
            if given.anchor is not None:
                raise FilterError(
                    f"doc={request.doc!r} names a place; give a document "
                    f"({given.doc}) or a version ({given.doc}/{given.version})."
                )
            try:
                document, version = self._version(str(given))
            except NotFoundError as exc:
                raise FilterError(str(exc)) from None
            doc_id = document.doc_id
            ref = version.ref if given.version else None
        for name, value in (("date_from", request.date_from), ("date_to", request.date_to)):
            if value is not None and not _DATE_RE.fullmatch(value):
                raise FilterError(f"{name}={value!r}: write YYYY, YYYY-MM or YYYY-MM-DD.")
        return _Filters(
            doc_id=doc_id,
            ref=ref,
            kind=request.kind,
            collection=self._known_value("collection", request.collection),
            org=self._known_value("org", request.org),
            tier=None if request.tier is None else request.tier.value,
            date_lo=date_key(request.date_from) if request.date_from else None,
            date_hi=date_key(request.date_to, end=True) if request.date_to else None,
            latest_only=not request.all_versions and ref is None,
        )

    def _known_value(self, name: str, value: str | None) -> str | None:
        if value is None:
            return None
        known = self._known[name]
        found = known.get(value.casefold())
        if found is None:
            listing = ", ".join(sorted(known.values())[:30])
            raise FilterError(f"No document has {name} {value!r}. Values: {listing}.")
        return found

    def _offset(self, request: SearchRequest) -> int:
        if request.cursor is None:
            return 0
        if not request.cursor.isdigit():
            raise FilterError(f"cursor={request.cursor!r} is not a cursor this search returned.")
        offset = int(request.cursor)
        if offset + request.limit > self.limits.max_results:
            raise FilterError(
                f"Paging stops at {self.limits.max_results} results. Narrow the query or add "
                "a filter instead."
            )
        return offset

    def _next(self, offset: int, limit: int, total: int) -> str | None:
        end = offset + limit
        return str(end) if end < total and end + 1 <= self.limits.max_results else None

    # ------------------------------------------------------------------ running

    def _run(self, request: SearchRequest) -> SearchResponse:
        arm, note = self._arm(request.arm)
        filters = self._filters(request)
        offset = self._offset(request)
        if not request.query.strip():
            return self._listing(request, filters, offset, arm)
        if arm == "bm25":
            return self._bm25(request, filters, offset, note)
        parsed = _lenient(request.query)
        if arm == "dense":
            ranked, total = self._dense_ranked(request.query, filters, offset + request.limit)
            how = "dense: units nearest the query in meaning (cosine similarity)"
        else:
            ranked, total = self._hybrid_ranked(request.query, parsed, filters)
            how = (
                f"hybrid: reciprocal rank fusion (k={RRF_K}) of the top {FUSION_DEPTH} by "
                "bm25 (any of the words) and by dense"
            )
        interpretation = f"{how}. {filters.describe()}.{note}"
        if request.mode == "documents":
            return self._grouped(
                request, ranked=ranked, parsed=parsed, offset=offset, arm=arm, note=interpretation
            )
        page = ranked[offset : offset + request.limit]
        return SearchResponse(
            query=request.query,
            interpretation=interpretation,
            arm=arm,
            snapshot=self._snapshot,
            mode="units",
            total=total,
            hits=self._hits(page, parsed),
            next_cursor=self._next(offset, request.limit, min(total, len(ranked))),
        )

    def _bm25(
        self, request: SearchRequest, filters: _Filters, offset: int, note: str
    ) -> SearchResponse:
        parsed = parse_query(request.query)
        query = compile_query(self._schema, parsed, filters.queries(self._schema))
        by_date = request.sort == "date"
        interpretation = (
            f"{parsed.describe()}. {filters.describe()}. "
            + (
                "Sorted by date, newest first."
                if by_date
                else f"Ranked by BM25, after up to {NAMED_FIRST} documents whose title,"
                " publisher or authors hold the whole query (each at its first page or block)."
            )
            + note
        )
        facets = self._facets(query)
        if request.mode == "documents":
            return self._bm25_documents(
                request,
                parsed=parsed,
                filters=filters,
                query=query,
                offset=offset,
                interpretation=interpretation,
            )
        if by_date:
            result = self._searcher.search(
                query, limit=request.limit, offset=offset, count=True, order_by_field="date"
            )
            ranked = [self._ranked(key, address, True) for key, address in result.hits]
            total = int(getattr(result, "count", 0) or 0)
        else:
            ranked, total = self._named_then_text(parsed, filters, query, offset + request.limit)
            ranked = ranked[offset:]
        return SearchResponse(
            query=request.query,
            interpretation=interpretation,
            arm="bm25",
            snapshot=self._snapshot,
            mode="units",
            total=total,
            hits=self._hits(ranked, parsed),
            facets=facets,
            next_cursor=self._next(offset, request.limit, total),
        )

    def _named(self, parsed: ParsedQuery, filters: _Filters, text_query: Query) -> list[_Ranked]:
        """Up to :data:`NAMED_FIRST` first units of documents whose record holds the query.

        Equal record scores (a crosspost under the same title) go to the document with more
        units matching the text, then by cite.
        """
        if not parsed.must or not self._has_record:
            return []
        query = compile_query(self._schema, parsed, filters.queries(self._schema), record_only=True)
        found = self._searcher.search(query, limit=NAMED_FIRST + 7, count=False)
        ranked = [self._ranked(key, address, False) for key, address in found.hits]
        if not ranked:
            return []
        refs = sorted({r.cite.rsplit("/", 1)[0] for r in ranked})
        among = Query.boolean_query(
            [
                (Occur.Must, text_query),
                (Occur.Must, Query.term_set_query(self._schema, "ref", refs)),
            ]
        )
        spec = {"docs": {"terms": {"field": "ref", "size": len(refs)}}}
        counts = {
            str(b["key"]): int(b["doc_count"])
            for b in self._aggregate(among, spec)["docs"]["buckets"]
        }
        ranked.sort(
            key=lambda r: (-round(r.score, 4), -counts.get(r.cite.rsplit("/", 1)[0], 0), r.cite)
        )
        return ranked[:NAMED_FIRST]

    def _named_then_text(
        self, parsed: ParsedQuery, filters: _Filters, text_query: Query, k: int
    ) -> tuple[list[_Ranked], int]:
        """The first ``k`` of: the documents the query names, then the text ranking (BM25,
        ties by cite) without them. Returns those and the total number of matches."""
        named = self._named(parsed, filters, text_query)
        named_cites = {r.cite for r in named}
        result = self._searcher.search(text_query, limit=k + len(named), count=True)
        text = sorted(
            (self._ranked(key, address, False) for key, address in result.hits),
            key=lambda r: (-r.score, r.cite),
        )
        kept = [r for r in text if r.cite not in named_cites]
        total = int(getattr(result, "count", 0) or 0) + len(named) - (len(text) - len(kept))
        return (named + kept)[:k], total

    def _ranked(self, key: Any, address: tantivy.DocAddress, by_date: bool) -> _Ranked:
        doc = self._searcher.doc(address)
        return _Ranked(
            cite=str(doc["cite"][0]),
            version_id=int(doc["version_id"][0]),
            score=0.0 if by_date else float(key),
        )

    def _aggregate(self, query: Query, spec: dict[str, Any]) -> dict[str, Any]:
        searcher: Any = self._searcher  # the binding's stub leaves the dict types open
        return cast("dict[str, Any]", searcher.aggregate(query, spec))

    def _facets(self, query: Query) -> dict[str, dict[str, int]]:
        spec = {name: {"terms": {"field": name, "size": 50}} for name in FACET_FIELDS}
        result = self._aggregate(query, spec)
        return {
            name: {str(b["key"]): int(b["doc_count"]) for b in result[name]["buckets"]}
            for name in FACET_FIELDS
            if result.get(name, {}).get("buckets")
        }

    def _bm25_documents(
        self,
        request: SearchRequest,
        *,
        parsed: ParsedQuery,
        filters: _Filters,
        query: Query,
        offset: int,
        interpretation: str,
    ) -> SearchResponse:
        spec = {"docs": {"terms": {"field": "ref", "size": 65_000}}}
        result = self._aggregate(query, spec)
        buckets = sorted(
            ((str(b["key"]), int(b["doc_count"])) for b in result["docs"]["buckets"]),
            key=lambda kc: (-kc[1], kc[0]),
        )
        # Up to NAMED_FIRST documents whose record (title, publisher, authors) holds the query
        # come first; then the rest by how many of their units match.
        counts = dict(buckets)
        named = {r.cite.rsplit("/", 1)[0]: r for r in self._named(parsed, filters, query)}
        rest = [(ref, n) for ref, n in buckets if ref not in named]
        buckets = [(ref, counts.get(ref, 0)) for ref in named] + rest
        documents: list[DocumentHit] = []
        for ref, count in buckets[offset : offset + request.limit]:
            narrowed = compile_query(
                self._schema, parsed, replace(filters, ref=ref).queries(self._schema)
            )
            top = self._searcher.search(narrowed, limit=TOP_PER_DOCUMENT, count=False)
            ranked = sorted(
                (self._ranked(key, address, False) for key, address in top.hits),
                key=lambda r: (-r.score, r.cite),
            )
            if ref in named and named[ref].cite not in {r.cite for r in ranked}:
                ranked = [named[ref], *ranked][:TOP_PER_DOCUMENT]
            documents.append(self._document_hit(ref, count, self._hits(ranked, parsed)))
        return SearchResponse(
            query=request.query,
            interpretation=interpretation
            + f" Up to {NAMED_FIRST} documents whose title, publisher or authors hold the query"
            " first; the rest by how many of their units match.",
            arm="bm25",
            snapshot=self._snapshot,
            mode="documents",
            total=len(buckets),
            documents=documents,
            facets=self._facets(query),
            next_cursor=self._next(offset, request.limit, len(buckets)),
        )

    def _dense_ranked(self, query: str, filters: _Filters, k: int) -> tuple[list[_Ranked], int]:
        if self._dense is None or self._columns is None or self._embedder is None:
            raise ArmUnavailableError(f"No vectors are built for snapshot {self._snapshot}.")
        mask = self._columns.mask(filters)
        vector = self._embedder.encode_query(query)
        rows = self._dense.top(vector, mask, k)
        ranked = [
            _Ranked(self._dense.cites[r], int(self._columns.version_id[r]), score)
            for r, score in rows
        ]
        return ranked, int(mask.sum())

    def _hybrid_ranked(
        self, query: str, parsed: ParsedQuery | None, filters: _Filters
    ) -> tuple[list[_Ranked], int]:
        lexical: list[_Ranked] = []
        if parsed is not None and parsed.must:
            compiled = compile_query(
                self._schema, parsed, filters.queries(self._schema), disjunctive=True
            )
            lexical, _ = self._named_then_text(parsed, filters, compiled, FUSION_DEPTH)
        dense, _ = self._dense_ranked(query, filters, FUSION_DEPTH)
        fused: dict[str, float] = {}
        version_of: dict[str, int] = {}
        for ranking in (lexical, dense):
            for rank, item in enumerate(ranking, start=1):
                fused[item.cite] = fused.get(item.cite, 0.0) + 1.0 / (RRF_K + rank)
                version_of[item.cite] = item.version_id
        ranked = sorted(
            (_Ranked(c, version_of[c], s) for c, s in fused.items()),
            key=lambda r: (-r.score, r.cite),
        )
        return ranked, len(ranked)

    def _grouped(
        self,
        request: SearchRequest,
        *,
        ranked: list[_Ranked],
        parsed: ParsedQuery | None,
        offset: int,
        arm: str,
        note: str,
    ) -> SearchResponse:
        groups: dict[str, list[_Ranked]] = {}
        for item in ranked[:DOCUMENT_DEPTH]:
            groups.setdefault(item.cite.rsplit("/", 1)[0], []).append(item)
        refs = list(groups)
        documents = [
            self._document_hit(
                ref, len(groups[ref]), self._hits(groups[ref][:TOP_PER_DOCUMENT], parsed)
            )
            for ref in refs[offset : offset + request.limit]
        ]
        return SearchResponse(
            query=request.query,
            interpretation=note
            + f" Documents ranked by their best unit among the top {DOCUMENT_DEPTH}.",
            arm=arm,
            snapshot=self._snapshot,
            mode="documents",
            total=len(refs),
            documents=documents,
            next_cursor=self._next(offset, request.limit, len(refs)),
        )

    # ------------------------------------------------------------------ results

    def _unit_text(self, version_id: int, anchor: Anchor) -> str:
        table, column = ("pages", "page") if anchor.kind == "p" else ("blocks", "anchor")
        row = (
            self._corpus()
            .conn.execute(
                f"SELECT text FROM {table} WHERE version_id = ? AND {column} = ?",  # noqa: S608
                (version_id, anchor.start),
            )
            .fetchone()
        )
        return str(row[0]) if row else ""

    def _hits(self, ranked: list[_Ranked], parsed: ParsedQuery | None) -> list[Hit]:
        corpus = self._corpus()
        out: list[Hit] = []
        for item in ranked:
            ref, anchor_text = item.cite.rsplit("/", 1)
            document, version = self._version(ref)
            anchor = Anchor.parse(anchor_text)
            text, spans = snippet(self._unit_text(item.version_id, anchor), version.tier, parsed)
            label = corpus.anchor_label(version, anchor)
            cite = Citation(DocId.parse(document.doc_id), version.label, anchor)
            out.append(
                Hit(
                    id=item.cite,
                    title=f"{document.title} — {label}",
                    url=cite.url(self.base_url),
                    cite=item.cite,
                    doc_id=document.doc_id,
                    version=version.label,
                    anchor=anchor_text,
                    anchor_label=label,
                    doc_title=document.title,
                    org=document.org,
                    kind=document.kind,
                    date=document.published,
                    tier=version.tier,
                    licence=version.licence,
                    score=round(item.score, 6),
                    snippet=text,
                    match_spans=spans,
                    source_url=source_link(version.source_url, anchor, paged=version.paged),
                )
            )
        return out

    def _document_hit(self, ref: str, count: int, top: list[Hit]) -> DocumentHit:
        document, version = self._version(ref)
        return DocumentHit(
            doc_id=document.doc_id,
            version=version.label,
            title=document.title,
            url=Ref(DocId.parse(document.doc_id), version.label).url(self.base_url),
            org=document.org,
            kind=document.kind,
            date=document.published,
            tier=version.tier,
            licence=version.licence,
            hit_count=count,
            top=top,
        )

    def _listing(
        self, request: SearchRequest, filters: _Filters, offset: int, arm: str
    ) -> SearchResponse:
        """No query: the documents the filters select, newest first or by id."""
        conditions = ["1 = 1"]
        params: list[Any] = []
        for column, value in (
            ("d.doc_id", filters.doc_id),
            ("d.doc_id || '/' || v.label", filters.ref),
            ("d.kind", filters.kind),
            ("d.collection", filters.collection),
            ("d.org", filters.org),
            ("v.tier", filters.tier),
        ):
            if value is not None:
                conditions.append(f"{column} = ?")
                params.append(value)
        if filters.latest_only:
            conditions.append("v.seq = (SELECT max(seq) FROM versions WHERE doc_id = d.doc_id)")
        where = " AND ".join(conditions)  # fixed column names; the values are parameters
        sql = (
            "SELECT d.doc_id || '/' || v.label AS ref, d.published FROM documents d "  # noqa: S608
            f"JOIN versions v ON v.doc_id = d.doc_id WHERE {where}"
        )
        rows = self._corpus().conn.execute(sql, params).fetchall()
        keep: Callable[[int], bool] = lambda d: (  # noqa: E731
            (filters.date_lo is None or d >= filters.date_lo)
            and (filters.date_hi is None or d <= filters.date_hi)
        )
        found = [(str(r[0]), date_key(r[1])) for r in rows if keep(date_key(r[1]))]
        if request.sort == "date":
            found.sort(key=lambda rd: (-rd[1], rd[0]))
        else:
            found.sort()
        documents = [self._document_hit(ref, 0, []) for ref, _ in found[offset:][: request.limit]]
        order = "newest first" if request.sort == "date" else "by document id"
        return SearchResponse(
            query=request.query,
            interpretation=f"No query: listing documents {order}. {filters.describe()}.",
            arm=arm,
            snapshot=self._snapshot,
            mode="documents",
            total=len(found),
            documents=documents,
            next_cursor=self._next(offset, request.limit, len(found)),
        )
