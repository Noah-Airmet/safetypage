"""A small in-memory :class:`~onthepage.api.SearchBackend` over a corpus's ``units`` view.

For tests and local development over the fixture corpus, until a snapshot's Tantivy index is
available. It reads every unit into memory, so it is for small corpora only. It speaks the same
query grammar as the real backend, except that ``a NEAR/n b`` is read as ``a b`` (both words,
anywhere in the unit), and says so in the interpretation.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from onthepage import policy
from onthepage.api import DocumentHit, Hit, SearchRequest, SearchResponse
from onthepage.corpus import Corpus
from onthepage.ids import Anchor, Ref, parse_ref, source_link
from onthepage.licence import Tier
from onthepage.model import Document, Version

__all__ = ["MemoryBackend", "QueryError"]

_WORD = re.compile(r"\w+")
_TOKEN = re.compile(r'(-?)"([^"]*)"|(\S+)')
_NEAR = re.compile(r"NEAR(?:/\d+)?")
_SNIPPET_CHARS = 280


class QueryError(ValueError):
    """A query the grammar cannot read. The message says how to write it."""


@dataclass(slots=True)
class _Query:
    words: list[str] = field(default_factory=list[str])
    prefixes: list[str] = field(default_factory=list[str])
    phrases: list[str] = field(default_factory=list[str])
    excluded: list[str] = field(default_factory=list[str])
    near: bool = False

    @property
    def empty(self) -> bool:
        return not (self.words or self.prefixes or self.phrases)


def _parse(query: str) -> _Query:
    q = _Query()
    for m in _TOKEN.finditer(query):
        negate, phrase, bare = m.group(1), m.group(2), m.group(3)
        if phrase is not None:
            words = _WORD.findall(phrase.lower())
            if not words:
                continue
            if negate:
                q.excluded.append(" ".join(words))
            elif len(words) == 1:
                q.words.append(words[0])
            else:
                q.phrases.append(" ".join(words))
            continue
        if _NEAR.fullmatch(bare):
            q.near = True
            continue
        if bare in {"OR", "|", "||"}:
            raise QueryError(
                "OR is not an operator here: every word in a query must appear. Run one search "
                "per alternative instead."
            )
        negative = bare.startswith("-") and len(bare) > 1
        text = bare[1:] if negative else bare
        prefix = text.endswith("*")
        words = _WORD.findall(text.lower())
        if not words:
            continue
        if negative:
            q.excluded.append(" ".join(words))
        elif prefix and len(words) == 1:
            if len(words[0]) < 3:
                raise QueryError(
                    f"prefix {text!r} is too short: give at least 3 letters, e.g. evaluat*"
                )
            q.prefixes.append(words[0])
        else:
            q.words.extend(words)
    return q


def _interpretation(q: _Query, request: SearchRequest) -> str:
    parts: list[str] = []
    if q.words:
        parts.append("all of: " + ", ".join(q.words))
    if q.prefixes:
        parts.append("words starting: " + ", ".join(f"{p}*" for p in q.prefixes))
    if q.phrases:
        parts.append("phrases: " + ", ".join(f'"{p}"' for p in q.phrases))
    if q.excluded:
        parts.append("excluding: " + ", ".join(q.excluded))
    if q.near:
        parts.append("NEAR read as AND by this backend")
    filters = [
        f"{name}={value}"
        for name in ("collection", "org", "kind", "date_from", "date_to", "doc", "tier")
        if (value := getattr(request, name)) is not None
    ]
    if filters:
        parts.append("filters: " + ", ".join(filters))
    return "; ".join(parts) if parts else "no query words: listing documents"


@dataclass(frozen=True, slots=True)
class _Row:
    cite: str
    doc_id: str
    version: str
    anchor: str
    text: str
    lower: str
    words: tuple[str, ...]
    joined: str
    counts: Counter[str]


class MemoryBackend:
    """Implements :class:`onthepage.api.SearchBackend` for small corpora. bm25 arm only.

    Everything is read from the corpus at construction, so searching touches no database and is
    safe from any thread."""

    def __init__(self, corpus: Corpus, *, snapshot: str = "fixtures") -> None:
        self._snapshot = snapshot
        self._base_url = corpus.base_url
        self._documents: dict[str, Document] = {}
        self._versions: dict[tuple[str, str], Version] = {}
        self._latest: dict[str, str] = {}
        for doc_id in corpus.doc_ids():
            document = corpus.document(doc_id)
            if document is None:
                continue
            self._documents[doc_id] = document
            versions = corpus.versions(doc_id)
            for v in versions:
                self._versions[(doc_id, v.label)] = v
            if versions:
                self._latest[doc_id] = versions[-1].label
        self._rows: list[_Row] = []
        self._labels: dict[str, str] = {}
        for r in corpus.conn.execute(
            "SELECT cite, doc_id, version, anchor, text FROM units ORDER BY doc_id, version, seq"
        ):
            text = str(r["text"])
            version = self._versions[(str(r["doc_id"]), str(r["version"]))]
            self._labels[str(r["cite"])] = corpus.anchor_label(version, Anchor.parse(r["anchor"]))
            words = tuple(_WORD.findall(text.lower()))
            self._rows.append(
                _Row(
                    str(r["cite"]),
                    str(r["doc_id"]),
                    str(r["version"]),
                    str(r["anchor"]),
                    text,
                    text.lower(),
                    words,
                    " " + " ".join(words) + " ",
                    Counter(words),
                )
            )
        self._df: Counter[str] = Counter()
        for row in self._rows:
            self._df.update(row.counts.keys())

    @property
    def snapshot(self) -> str:
        return self._snapshot

    @property
    def arms(self) -> tuple[str, ...]:
        return ("bm25",)

    # ------------------------------------------------------------------ filtering

    def _keep(self, row: _Row, request: SearchRequest) -> bool:
        document = self._documents[row.doc_id]
        version = self._versions[(row.doc_id, row.version)]
        pinned = request.doc is not None and "/" in request.doc
        if not (request.all_versions or pinned) and self._latest.get(row.doc_id) != row.version:
            return False
        if request.doc is not None:
            ref = parse_ref(request.doc)
            if str(ref.doc) != row.doc_id:
                return False
            if ref.version is not None and ref.version != row.version:
                return False
        date = document.published or ""
        checks = (
            request.collection is None or document.collection == request.collection,
            request.org is None or (document.org or "").lower() == request.org.lower(),
            request.kind is None or document.kind == request.kind,
            request.tier is None or version.tier == request.tier,
            request.date_from is None or (date != "" and date >= request.date_from),
            request.date_to is None
            or (date != "" and date[: len(request.date_to)] <= request.date_to),
        )
        return all(checks)

    def _score(self, row: _Row, q: _Query) -> float | None:
        n = len(self._rows) or 1
        score = 0.0
        for w in q.words:
            tf = row.counts.get(w, 0)
            if not tf:
                return None
            score += (1 + math.log(tf)) * math.log(1 + n / self._df[w])
        for p in q.prefixes:
            tf = sum(c for w, c in row.counts.items() if w.startswith(p))
            if not tf:
                return None
            score += 1 + math.log(tf)
        for phrase in q.phrases:
            tf = row.joined.count(f" {phrase} ")
            if not tf:
                return None
            score += 2 * (1 + math.log(tf))
        for x in q.excluded:
            if f" {x} " in row.joined:
                return None
        return round(score, 4)

    # ------------------------------------------------------------------ hits

    def _first_match(self, row: _Row, q: _Query) -> int:
        targets = [*q.phrases, *q.words, *q.prefixes]
        positions: list[int] = []
        for t in targets:
            first = t.split()[0]
            m = re.search(rf"\b{re.escape(first)}", row.lower)
            if m:
                positions.append(m.start())
        return min(positions) if positions else 0

    def _snippet(self, row: _Row, q: _Query, tier: Tier) -> tuple[str, list[tuple[int, int]]]:
        at = self._first_match(row, q)
        start = max(0, at - 80)
        if start:
            space = row.text.find(" ", start)
            start = space + 1 if 0 <= space < at else start
        window = row.text[start : start + _SNIPPET_CHARS]
        if start + _SNIPPET_CHARS < len(row.text) and " " in window:
            window = window[: window.rfind(" ")]
        window = " ".join(window.split())
        snippet = policy.clip(window, tier)
        if tier == Tier.OPEN:
            snippet = (
                ("…" if start else "")
                + snippet
                + ("…" if start + len(window) < len(row.text) else "")
            )
        snippet = snippet[: policy.access_for(tier).snippet_chars]
        spans: list[tuple[int, int]] = []
        lower = snippet.lower()
        for t in [*q.phrases, *q.words, *q.prefixes]:
            pattern = r"\b" + r"\W+".join(re.escape(w) for w in t.split())
            pattern += r"\w*" if t in q.prefixes else r"\b"
            spans.extend((m.start(), m.end()) for m in re.finditer(pattern, lower))
        return snippet, sorted(set(spans))

    def _hit(self, row: _Row, q: _Query, score: float) -> Hit:
        document = self._documents[row.doc_id]
        version = self._versions[(row.doc_id, row.version)]
        anchor = Anchor.parse(row.anchor)
        label = self._labels[row.cite]
        url = parse_ref(row.cite).url(self._base_url)
        snippet, spans = self._snippet(row, q, version.tier)
        return Hit(
            id=row.cite,
            title=f"{document.title} — {label}",
            url=url,
            cite=row.cite,
            doc_id=row.doc_id,
            version=row.version,
            anchor=row.anchor,
            anchor_label=label,
            doc_title=document.title,
            org=document.org,
            kind=document.kind,
            date=document.published,
            tier=version.tier,
            licence=version.licence,
            score=score,
            snippet=snippet,
            match_spans=spans,
            source_url=source_link(version.source_url, anchor, paged=version.paged),
        )

    def _document_hit(
        self, doc_id: str, version_label: str, count: int, top: list[Hit]
    ) -> DocumentHit:
        document = self._documents[doc_id]
        version = self._versions[(doc_id, version_label)]
        ref = Ref(parse_ref(doc_id).doc, version_label)
        return DocumentHit(
            doc_id=doc_id,
            version=version_label,
            title=document.title,
            url=ref.url(self._base_url),
            org=document.org,
            kind=document.kind,
            date=document.published,
            tier=version.tier,
            licence=version.licence,
            hit_count=count,
            top=top,
        )

    # ------------------------------------------------------------------ search

    def search(self, request: SearchRequest) -> SearchResponse:
        if request.arm not in self.arms:
            raise QueryError(f"arm {request.arm!r} is not built into this backend; arms: bm25")
        q = _parse(request.query)
        offset = int(request.cursor) if request.cursor and request.cursor.isdigit() else 0
        matched: list[tuple[float, _Row]] = []
        for row in self._rows:
            if not self._keep(row, request):
                continue
            if q.empty:
                matched.append((0.0, row))
                continue
            score = self._score(row, q)
            if score is not None:
                matched.append((score, row))

        def date_of(row: _Row) -> str:
            return self._documents[row.doc_id].published or ""

        if request.sort == "date":
            matched.sort(key=lambda m: (date_of(m[1]), m[0], m[1].cite), reverse=True)
        else:
            matched.sort(key=lambda m: (-m[0], m[1].cite))

        facets: dict[str, dict[str, int]] = {"org": {}, "kind": {}, "collection": {}}
        by_doc: dict[tuple[str, str], list[tuple[float, _Row]]] = defaultdict(list)
        for score, row in matched:
            by_doc[(row.doc_id, row.version)].append((score, row))
        for doc_id, _ in by_doc:
            document = self._documents[doc_id]
            for name, value in (
                ("org", document.org),
                ("kind", document.kind),
                ("collection", document.collection),
            ):
                if value:
                    facets[name][value] = facets[name].get(value, 0) + 1
        facets = {
            k: dict(sorted(v.items(), key=lambda kv: (-kv[1], kv[0])))
            for k, v in facets.items()
            if v
        }

        mode = "documents" if q.empty else request.mode
        hits: list[Hit] = []
        documents: list[DocumentHit] = []
        if mode == "units":
            total = len(matched)
            page = matched[offset : offset + request.limit]
            hits = [self._hit(row, q, score) for score, row in page]
        else:
            ranked = list(by_doc.items())
            if request.sort == "date":
                ranked.sort(
                    key=lambda kv: (self._documents[kv[0][0]].published or "", kv[0]), reverse=True
                )
            else:
                ranked.sort(key=lambda kv: (-sum(s for s, _ in kv[1]), kv[0]))
            total = len(ranked)
            for (doc_id, version_label), rows in ranked[offset : offset + request.limit]:
                top = [] if q.empty else [self._hit(r, q, s) for s, r in rows[:3]]
                documents.append(
                    self._document_hit(doc_id, version_label, 0 if q.empty else len(rows), top)
                )
        end = offset + request.limit
        return SearchResponse(
            query=request.query,
            interpretation=_interpretation(q, request),
            arm=request.arm,
            snapshot=self._snapshot,
            mode=mode,
            total=total,
            hits=hits,
            documents=documents,
            facets=facets,
            next_cursor=str(end) if end < total else None,
        )
