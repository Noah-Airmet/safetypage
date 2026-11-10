"""The corpus database: the one way in and out of the SQLite document store.

Writes go through methods that keep the invariants (anchors are minted here, spine offsets are
computed here, the tier is computed here from the licence fact). Reads that leave the process go
through methods that apply the licence tier, so a caller cannot forget to.

The spine
---------
A version's *spine* is its text of record as one string: its units joined by a single newline.
Units are the pages of a paged version, or the blocks of an unpaged one, in order. Every offset
this package reports (``spine_start``, ``spine_end``) indexes that string, and quote checking
runs against it, which is why a quote may run across a page break and still be found.
"""

from __future__ import annotations

import difflib
import json
import sqlite3
from bisect import bisect_right
from collections import Counter, OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from onthepage import policy
from onthepage.answer import parse_answer
from onthepage.api import (
    AnswerAudit,
    CitationAudit,
    DocumentCard,
    OutlineItem,
    QuoteAudit,
    QuoteCheck,
    QuoteDiff,
    QuoteLocation,
    QuoteSegment,
    UnitText,
    VersionSummary,
)
from onthepage.ids import Anchor, Citation, DocId, IdError, Ref, parse_ref, source_link
from onthepage.ids import version_number as _version_number
from onthepage.licence import LicenceFact, Tier, decide_tier
from onthepage.migrate import current_version, load_migrations, migrate
from onthepage.model import (
    AnchorKindName,
    Block,
    Document,
    Fidelity,
    NewBlock,
    NewPage,
    OutlineEntry,
    Page,
    Rendition,
    Version,
)
from onthepage.quote import (
    QuoteResult,
    QuoteTooShortError,
    Skeleton,
    Span,
    skeleton,
    verify_quote,
)
from onthepage.text import is_clean

__all__ = [
    "MAX_UNITS_PER_READ",
    "SPINE_SEPARATOR",
    "Corpus",
    "CorpusError",
    "NotFoundError",
    "Resolved",
    "utc_now",
]

SPINE_SEPARATOR: Final = "\n"
MAX_UNITS_PER_READ: Final = 8
_SPINE_CACHE_SIZE: Final = 32


class CorpusError(Exception):
    pass


class NotFoundError(CorpusError, LookupError):
    """A document, version or anchor that is not in the corpus. The message says what would be."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True, slots=True)
class Resolved:
    """A ref checked against the corpus."""

    document: Document
    version: Version
    anchor: Anchor | None
    scope: tuple[int, int] | None
    """The anchor's stretch of the spine."""

    @property
    def ref(self) -> Ref:
        return Ref(DocId.parse(self.document.doc_id), self.version.label, self.anchor)


@dataclass(frozen=True, slots=True)
class _Unit:
    n: int
    start: int
    end: int
    label: str | None
    kind: str
    section: tuple[str, ...]


class Corpus:
    def __init__(
        self, conn: sqlite3.Connection, *, base_url: str = "http://localhost:8000"
    ) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.base_url = base_url.rstrip("/")
        self._spines: OrderedDict[int, Skeleton] = OrderedDict()
        self._units_cache: OrderedDict[int, list[_Unit]] = OrderedDict()

    # ------------------------------------------------------------------ opening

    @classmethod
    def open(
        cls, path: Path, *, readonly: bool = False, base_url: str = "http://localhost:8000"
    ) -> Corpus:
        """Open a corpus database. Writable databases are migrated; read-only ones must already
        be at this code's schema version (snapshots are rebuilt, never migrated)."""
        if readonly:
            conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
            expected = len(load_migrations("corpus"))
            found = current_version(conn)
            if found != expected:
                conn.close()
                raise CorpusError(
                    f"{path} is at schema version {found}; this code reads version {expected}. "
                    "Rebuild the snapshot."
                )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path)
            migrate(conn, "corpus")
        return cls(conn, base_url=base_url)

    @classmethod
    def memory(cls, *, base_url: str = "http://localhost:8000") -> Corpus:
        conn = sqlite3.connect(":memory:")
        migrate(conn, "corpus")
        return cls(conn, base_url=base_url)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Corpus:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ writing

    def add_document(self, document: Document) -> Document:
        doc = DocId.parse(document.doc_id)
        added_at = document.added_at or utc_now()
        with self.conn:
            self.conn.execute(
                "INSERT INTO documents (doc_id, ns, local_id, kind, title, authors, org, "
                "collection, published, source_url, added_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(doc),
                    doc.ns,
                    doc.local,
                    document.kind,
                    document.title,
                    json.dumps(document.authors, ensure_ascii=False),
                    document.org,
                    document.collection,
                    document.published,
                    document.source_url,
                    added_at,
                ),
            )
        return document.model_copy(update={"added_at": added_at})

    def add_version(
        self,
        doc_id: str,
        label: str,
        *,
        anchor_kind: AnchorKindName,
        fidelity: Fidelity,
        source_url: str,
        content_sha256: str,
        licence: LicenceFact | None,
        observed_at: str | None = None,
        published: str | None = None,
    ) -> Version:
        """Add an immutable version. The tier is computed here from ``licence``; pass None when
        the licence is not known, and the version is link-only until a fact says otherwise."""
        if self.document(doc_id) is None:
            raise NotFoundError(f"no document {doc_id!r}: add the document before its versions")
        decision = decide_tier(licence)
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO versions (doc_id, label, seq, anchor_kind, fidelity, published, "
                "observed_at, source_url, content_sha256, licence, tier) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    doc_id,
                    label,
                    _version_number(label),
                    anchor_kind,
                    fidelity,
                    published,
                    observed_at or utc_now(),
                    source_url,
                    content_sha256,
                    decision.licence,
                    decision.tier.value,
                ),
            )
            version_id = cursor.lastrowid
            if version_id is None:  # pragma: no cover
                raise CorpusError("insert returned no row id")
            if licence is not None:
                self._insert_licence_fact(version_id, licence)
        return self._version_by_id(version_id)

    def _insert_licence_fact(self, version_id: int, fact: LicenceFact) -> None:
        self.conn.execute(
            "INSERT INTO licence_facts (version_id, licence, evidence_kind, evidence_url, "
            "evidence_quote, evidence_sha256, observed_at, producer) VALUES (?,?,?,?,?,?,?,?)",
            (
                version_id,
                fact.licence,
                fact.evidence_kind,
                fact.evidence_url,
                fact.evidence_quote,
                fact.evidence_sha256,
                fact.observed_at,
                fact.producer,
            ),
        )

    def record_licence(self, version_id: int, fact: LicenceFact) -> Version:
        """Append a licence fact. The newest fact is the one in force; the tier follows it."""
        decision = decide_tier(fact)
        with self.conn:
            self._insert_licence_fact(version_id, fact)
            self.conn.execute(
                "UPDATE versions SET licence = ?, tier = ? WHERE version_id = ?",
                (decision.licence, decision.tier.value, version_id),
            )
        return self._version_by_id(version_id)

    def licence_fact(self, version_id: int) -> LicenceFact | None:
        """The licence fact in force for a version (the newest), with its evidence."""
        row = self.conn.execute(
            "SELECT * FROM licence_facts WHERE version_id = ? ORDER BY fact_id DESC LIMIT 1",
            (version_id,),
        ).fetchone()
        if row is None:
            return None
        return LicenceFact(
            licence=row["licence"],
            evidence_kind=row["evidence_kind"],
            evidence_url=row["evidence_url"],
            evidence_quote=row["evidence_quote"],
            observed_at=row["observed_at"],
            producer=row["producer"],
            evidence_sha256=row["evidence_sha256"],
        )

    def add_rendition(self, version_id: int, rendition: Rendition) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO renditions (version_id, kind, sha256, bytes, media_type, source_url, "
                "fetched_at) VALUES (?,?,?,?,?,?,?)",
                (
                    version_id,
                    rendition.kind,
                    rendition.sha256,
                    rendition.bytes,
                    rendition.media_type,
                    rendition.source_url,
                    rendition.fetched_at,
                ),
            )

    def renditions(self, version_id: int) -> list[Rendition]:
        rows = self.conn.execute(
            "SELECT kind, sha256, bytes, media_type, source_url, fetched_at FROM renditions "
            "WHERE version_id = ? ORDER BY kind",
            (version_id,),
        ).fetchall()
        return [Rendition(**dict(row)) for row in rows]

    def add_pages(self, version_id: int, pages: Sequence[NewPage]) -> None:
        """Write a paged version's text of record, once. Pages are numbered from 1 in order."""
        version = self._version_by_id(version_id)
        if not version.paged:
            raise CorpusError(f"{version.ref} is cited by block; it has no pages")
        if self.conn.execute(
            "SELECT 1 FROM pages WHERE version_id = ? LIMIT 1", (version_id,)
        ).fetchone():
            raise CorpusError(f"{version.ref} already has pages; a version's text is written once")
        if not pages:
            raise CorpusError("a paged version needs at least one page")
        offset = 0
        with self.conn:
            for number, page in enumerate(pages, start=1):
                end = offset + len(page.text)
                self.conn.execute(
                    "INSERT INTO pages (version_id, page, label, width, height, text, "
                    "spine_start, spine_end) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        version_id,
                        number,
                        page.label,
                        page.width,
                        page.height,
                        page.text,
                        offset,
                        end,
                    ),
                )
                if page.words is not None:
                    self.conn.execute(
                        "INSERT INTO page_words (version_id, page, words) VALUES (?,?,?)",
                        (version_id, number, json.dumps(page.words, separators=(",", ":"))),
                    )
                offset = end + len(SPINE_SEPARATOR)
        self._forget(version_id)

    def add_blocks(self, version_id: int, blocks: Sequence[NewBlock]) -> list[Block]:
        """Append blocks, minting their anchors. Returns them with anchors and offsets filled in.

        For an unpaged version the blocks are the text of record, and their spine offsets are
        computed. For a paged version they are an overlay: pass ``spine_start``/``spine_end`` for
        each block that was placed on the page text (pages must be written first), and the pages
        it touches are derived.
        """
        version = self._version_by_id(version_id)
        row = self.conn.execute(
            "SELECT next_block FROM versions WHERE version_id = ?", (version_id,)
        ).fetchone()
        next_anchor = int(row["next_block"])
        last = self.conn.execute(
            "SELECT max(seq) AS seq, max(spine_end) AS spine_end FROM blocks WHERE version_id = ?",
            (version_id,),
        ).fetchone()
        seq = int(last["seq"] or 0)
        pages = self._pages_index(version_id) if version.paged else []
        spine_length = pages[-1].end if pages else 0
        offset = 0 if last["spine_end"] is None else int(last["spine_end"]) + len(SPINE_SEPARATOR)
        with self.conn:
            for block in blocks:
                seq += 1
                page_start: int | None = None
                page_end: int | None = None
                if version.paged:
                    start, end = block.spine_start, block.spine_end
                    if (start is None) != (end is None):
                        raise CorpusError("give both spine_start and spine_end, or neither")
                    if start is not None and end is not None:
                        if not 0 <= start < end <= spine_length:
                            raise CorpusError(
                                f"block span {start}-{end} is outside the spine (0-{spine_length})"
                            )
                        page_start = self._unit_at(pages, start).n
                        page_end = self._unit_at(pages, end - 1).n
                else:
                    if block.spine_start is not None or block.spine_end is not None:
                        raise CorpusError(
                            "spine offsets of an unpaged version's blocks are computed, not given"
                        )
                    start, end = offset, offset + len(block.text)
                    offset = end + len(SPINE_SEPARATOR)
                self.conn.execute(
                    "INSERT INTO blocks (version_id, anchor, seq, kind, level, label, section, "
                    "text, spine_start, spine_end, page_start, page_end, source_id, bbox) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        version_id,
                        next_anchor,
                        seq,
                        block.kind,
                        block.level,
                        block.label,
                        json.dumps(block.section, ensure_ascii=False),
                        block.text,
                        start,
                        end,
                        page_start,
                        page_end,
                        block.source_id,
                        None if block.bbox is None else json.dumps(block.bbox),
                    ),
                )
                next_anchor += 1
            self.conn.execute(
                "UPDATE versions SET next_block = ? WHERE version_id = ?", (next_anchor, version_id)
            )
        self._forget(version_id)
        first = next_anchor - len(blocks)
        return [b for b in self.blocks(version_id) if b.anchor >= first]

    def set_outline(self, version_id: int, entries: Sequence[OutlineEntry]) -> None:
        version = self._version_by_id(version_id)
        for entry in entries:
            self._scope(version, Anchor.parse(entry.anchor))
        with self.conn:
            self.conn.execute("DELETE FROM outline WHERE version_id = ?", (version_id,))
            self.conn.executemany(
                "INSERT INTO outline (version_id, seq, level, title, anchor) VALUES (?,?,?,?,?)",
                [(version_id, i, e.level, e.title, e.anchor) for i, e in enumerate(entries, 1)],
            )

    def add_fact(
        self,
        subject: str,
        field: str,
        value: Any,
        *,
        source: str,
        producer: str,
        input_sha256: str | None = None,
        retrieved_at: str | None = None,
        confidence: float | None = None,
    ) -> None:
        """Record where a metadata value came from. Appends; never overwrites."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO facts (subject, field, value, source, producer, input_sha256, "
                "retrieved_at, confidence) VALUES (?,?,?,?,?,?,?,?)",
                (
                    subject,
                    field,
                    json.dumps(value, ensure_ascii=False),
                    source,
                    producer,
                    input_sha256,
                    retrieved_at or utc_now(),
                    confidence,
                ),
            )

    def map_anchor(
        self,
        source: Citation,
        target: Citation,
        *,
        relation: str,
        method: str,
        confidence: float | None = None,
    ) -> None:
        """Record where an anchor went (in a later version, or after a re-parse)."""
        from_version = self.resolve(source.ref).version
        to_version = self.resolve(target.ref).version
        with self.conn:
            self.conn.execute(
                "INSERT INTO anchor_map (from_version_id, from_anchor, to_version_id, to_anchor, "
                "relation, method, confidence) VALUES (?,?,?,?,?,?,?)",
                (
                    from_version.version_id,
                    str(source.anchor),
                    to_version.version_id,
                    str(target.anchor),
                    relation,
                    method,
                    confidence,
                ),
            )

    def follow_anchor(self, citation: Citation) -> list[tuple[Citation, str]]:
        """Where a cited anchor went, as ``(new citation, relation)`` pairs."""
        version = self.resolve(citation.ref).version
        rows = self.conn.execute(
            "SELECT v.doc_id, v.label, m.to_anchor, m.relation FROM anchor_map m "
            "JOIN versions v ON v.version_id = m.to_version_id "
            "WHERE m.from_version_id = ? AND m.from_anchor = ? ORDER BY v.seq, m.to_anchor",
            (version.version_id, str(citation.anchor)),
        ).fetchall()
        return [
            (
                Citation(DocId.parse(r["doc_id"]), r["label"], Anchor.parse(r["to_anchor"])),
                str(r["relation"]),
            )
            for r in rows
        ]

    # ------------------------------------------------------------------ reading: catalogue

    def document(self, doc_id: str) -> Document | None:
        row = self.conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["authors"] = json.loads(data["authors"])
        del data["ns"], data["local_id"]
        return Document(**data)

    def doc_ids(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT doc_id FROM documents ORDER BY doc_id")]

    @staticmethod
    def _version(row: sqlite3.Row) -> Version:
        data = dict(row)
        del data["next_block"]
        return Version(**data)

    def _version_by_id(self, version_id: int) -> Version:
        row = self.conn.execute(
            "SELECT * FROM versions WHERE version_id = ?", (version_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no version with id {version_id}")
        return self._version(row)

    def versions(self, doc_id: str) -> list[Version]:
        """A document's versions, oldest first. The last one is the latest."""
        rows = self.conn.execute(
            "SELECT * FROM versions WHERE doc_id = ? ORDER BY seq", (doc_id,)
        ).fetchall()
        return [self._version(row) for row in rows]

    def all_versions(self) -> list[Version]:
        rows = self.conn.execute("SELECT * FROM versions ORDER BY doc_id, seq").fetchall()
        return [self._version(row) for row in rows]

    def outline(self, version_id: int) -> list[OutlineEntry]:
        rows = self.conn.execute(
            "SELECT level, title, anchor FROM outline WHERE version_id = ? ORDER BY seq",
            (version_id,),
        ).fetchall()
        return [OutlineEntry(**dict(row)) for row in rows]

    def unit_count(self, version_id: int) -> int:
        return len(self._units(self._version_by_id(version_id)))

    # ------------------------------------------------------------------ resolving

    def resolve(self, ref: Ref | Citation | str) -> Resolved:
        """Check a ref against the corpus. Raises :class:`NotFoundError` with a message that
        says what exists instead (these messages are shown to agents as tool errors)."""
        if isinstance(ref, str):
            ref = parse_ref(ref)
        elif isinstance(ref, Citation):
            ref = ref.ref
        doc_id = str(ref.doc)
        document = self.document(doc_id)
        if document is None:
            raise NotFoundError(self._unknown_document(doc_id))
        versions = self.versions(doc_id)
        if not versions:
            raise NotFoundError(f"{doc_id} has no versions yet")
        if ref.version is None:
            version = versions[-1]
        else:
            match = next((v for v in versions if v.label == ref.version), None)
            if match is None:
                labels = ", ".join(v.label for v in versions)
                raise NotFoundError(
                    f"{doc_id} has no version {ref.version}. Versions: {labels}. "
                    f"The latest is {doc_id}/{versions[-1].label}."
                )
            version = match
        scope = None if ref.anchor is None else self._scope(version, ref.anchor)
        return Resolved(document, version, ref.anchor, scope)

    def _unknown_document(self, doc_id: str) -> str:
        ns = doc_id.split(":", 1)[0]
        candidates = [
            r[0]
            for r in self.conn.execute(
                "SELECT doc_id FROM documents WHERE ns = ? ORDER BY doc_id LIMIT 5000", (ns,)
            )
        ]
        close = difflib.get_close_matches(doc_id, candidates, n=1, cutoff=0.6)
        hint = f" Did you mean {close[0]}?" if close else ""
        return (
            f"Unknown document {doc_id!r}. Ids look like arxiv:2305.15324 (<source>:<id>); "
            f"search returns them.{hint}"
        )

    def _scope(self, version: Version, anchor: Anchor) -> tuple[int, int]:
        if anchor.kind == "p":
            if not version.paged:
                raise NotFoundError(
                    f"{version.ref} has no pages: it is cited by block, e.g. {version.ref}/b1"
                )
            pages = self._units(version)
            if anchor.end > len(pages):
                raise NotFoundError(
                    f"{version.ref} has {len(pages)} pages; there is no {anchor}. "
                    f"Pages run {version.ref}/p1 to {version.ref}/p{len(pages)}."
                )
            return pages[anchor.start - 1].start, pages[anchor.end - 1].end
        rows = self.conn.execute(
            "SELECT anchor, spine_start, spine_end FROM blocks "
            "WHERE version_id = ? AND anchor IN (?, ?)",
            (version.version_id, anchor.start, anchor.end),
        ).fetchall()
        spans = {int(r["anchor"]): (r["spine_start"], r["spine_end"]) for r in rows}
        for n in (anchor.start, anchor.end):
            if n not in spans:
                count = self.conn.execute(
                    "SELECT count(*) FROM blocks WHERE version_id = ?", (version.version_id,)
                ).fetchone()[0]
                what = f"{count} blocks" if count else "no blocks"
                raise NotFoundError(f"{version.ref} has {what}; there is no b{n}.")
            if spans[n][0] is None:
                raise NotFoundError(
                    f"{version.ref}/b{n} was not placed on a page, so it cannot be cited; "
                    "cite the page instead."
                )
        start, end = int(spans[anchor.start][0]), int(spans[anchor.end][1])
        if end <= start:
            raise NotFoundError(f"{version.ref}/{anchor} does not run forwards in the text")
        return start, end

    # ------------------------------------------------------------------ the spine (private)

    def _forget(self, version_id: int) -> None:
        self._spines.pop(version_id, None)
        self._units_cache.pop(version_id, None)

    def _pages_index(self, version_id: int) -> list[_Unit]:
        rows = self.conn.execute(
            "SELECT page, spine_start, spine_end, label FROM pages WHERE version_id = ? "
            "ORDER BY page",
            (version_id,),
        ).fetchall()
        return [
            _Unit(r["page"], r["spine_start"], r["spine_end"], r["label"], "page", ()) for r in rows
        ]

    def _units(self, version: Version) -> list[_Unit]:
        """The version's citation units in order: pages, or the blocks of an unpaged version."""
        cached = self._units_cache.get(version.version_id)
        if cached is not None:
            return cached
        if version.paged:
            units = self._pages_index(version.version_id)
        else:
            rows = self.conn.execute(
                "SELECT anchor, spine_start, spine_end, label, kind, section FROM blocks "
                "WHERE version_id = ? ORDER BY seq",
                (version.version_id,),
            ).fetchall()
            units = [
                _Unit(
                    r["anchor"],
                    r["spine_start"],
                    r["spine_end"],
                    r["label"],
                    r["kind"],
                    tuple(json.loads(r["section"])),
                )
                for r in rows
            ]
        self._units_cache[version.version_id] = units
        while len(self._units_cache) > _SPINE_CACHE_SIZE:
            self._units_cache.popitem(last=False)
        return units

    @staticmethod
    def _unit_at(units: list[_Unit], offset: int) -> _Unit:
        index = bisect_right([u.start for u in units], offset) - 1
        return units[max(index, 0)]

    def private_spine_text(self, version: Version) -> str:
        """A version's whole text of record. PRIVATE: for indexing and quote checking only.

        Never return this, or a slice of it, from anything a client can call; use
        :meth:`read_units`, which applies the licence tier.
        """
        table, order = ("pages", "page") if version.paged else ("blocks", "seq")
        rows = self.conn.execute(
            f"SELECT text FROM {table} WHERE version_id = ? ORDER BY {order}",  # noqa: S608
            (version.version_id,),
        )
        return SPINE_SEPARATOR.join(r[0] for r in rows)

    def private_skeleton(self, version: Version) -> Skeleton:
        """The spine's skeleton, cached. PRIVATE, like :meth:`private_spine_text`."""
        cached = self._spines.get(version.version_id)
        if cached is not None:
            self._spines.move_to_end(version.version_id)
            return cached
        built = skeleton(self.private_spine_text(version))
        self._spines[version.version_id] = built
        while len(self._spines) > _SPINE_CACHE_SIZE:
            self._spines.popitem(last=False)
        return built

    def locate(self, version: Version, start: int, end: int) -> Anchor:
        """The unit anchor (or range) that spine stretch ``[start, end)`` falls in."""
        units = self._units(version)
        first = self._unit_at(units, start)
        last = self._unit_at(units, max(start, end - 1))
        kind = "p" if version.paged else "b"
        if not version.paged and last.n < first.n:
            last = first  # blocks are in reading order, which need not be anchor order
        return Anchor(kind, first.n, max(first.n, last.n))

    # ------------------------------------------------------------------ reading: text

    def pages(self, version_id: int) -> list[Page]:
        """PRIVATE: full page rows, whatever the tier. For indexing and snapshot builds."""
        rows = self.conn.execute(
            "SELECT * FROM pages WHERE version_id = ? ORDER BY page", (version_id,)
        ).fetchall()
        return [Page(**dict(row)) for row in rows]

    def blocks(self, version_id: int) -> list[Block]:
        """PRIVATE: full block rows, whatever the tier. For indexing and snapshot builds."""
        rows = self.conn.execute(
            "SELECT version_id, anchor, seq, kind, level, label, section, text, spine_start, "
            "spine_end, page_start, page_end, source_id FROM blocks WHERE version_id = ? "
            "ORDER BY seq",
            (version_id,),
        ).fetchall()
        out: list[Block] = []
        for row in rows:
            data = dict(row)
            data["section"] = json.loads(data["section"])
            out.append(Block(**data))
        return out

    def anchor_label(self, version: Version, anchor: Anchor) -> str:
        """What a person calls this place: ``p. 6``, ``p. xii (PDF p. 14)``, ``Figure 3``."""
        if anchor.kind == "p":
            labels = {u.n: u.label for u in self._units(version)} if version.paged else {}

            def one(n: int) -> str:
                label = labels.get(n)
                return f"{label} (PDF p. {n})" if label and label != str(n) else str(n)

            if anchor.is_range:
                return f"pp. {one(anchor.start)}-{one(anchor.end)}"
            return f"p. {one(anchor.start)}"
        if anchor.is_range:
            return f"¶{anchor.start}-{anchor.end}"
        row = self.conn.execute(
            "SELECT label, section FROM blocks WHERE version_id = ? AND anchor = ?",
            (version.version_id, anchor.start),
        ).fetchone()
        if row is None:
            return f"¶{anchor.start}"
        if row["label"]:
            return str(row["label"])
        section = json.loads(row["section"])
        return f"{section[-1]} ¶{anchor.start}" if section else f"¶{anchor.start}"

    def _cite(self, version: Version, anchor: Anchor) -> Citation:
        return Citation(DocId.parse(version.doc_id), version.label, anchor)

    def read_units(self, ref: Ref | Citation | str) -> list[UnitText]:
        """The cited units as a client may see them: full text for an open document, the
        opening words and a link to the source for a link-only one.

        This is the public read path. At most :data:`MAX_UNITS_PER_READ` units per call.
        """
        resolved = self.resolve(ref)
        version, anchor = resolved.version, resolved.anchor
        if anchor is None:
            raise CorpusError(f"{resolved.ref} names no anchor; nothing to read")
        if anchor.size > MAX_UNITS_PER_READ:
            raise CorpusError(
                f"range too large: {anchor} is {anchor.size} units, the most per call is "
                f"{MAX_UNITS_PER_READ}. The document card's outline lists sections with their "
                "anchors."
            )
        if anchor.kind == "p":
            rows = self.conn.execute(
                "SELECT page AS n, text FROM pages WHERE version_id = ? AND page BETWEEN ? AND ? "
                "ORDER BY page",
                (version.version_id, anchor.start, anchor.end),
            ).fetchall()
        else:
            bounds = self.conn.execute(
                "SELECT min(seq), max(seq) FROM blocks WHERE version_id = ? AND anchor IN (?, ?)",
                (version.version_id, anchor.start, anchor.end),
            ).fetchone()
            rows = self.conn.execute(
                "SELECT anchor AS n, text FROM blocks WHERE version_id = ? AND seq BETWEEN ? AND ? "
                "ORDER BY seq",
                (version.version_id, bounds[0], bounds[1]),
            ).fetchall()
            if len(rows) > MAX_UNITS_PER_READ:
                raise CorpusError(
                    f"range too large: {anchor} covers {len(rows)} blocks, the most per call is "
                    f"{MAX_UNITS_PER_READ}."
                )
        access = policy.access_for(version.tier)
        units: list[UnitText] = []
        for row in rows:
            single = Anchor(anchor.kind, int(row["n"]), int(row["n"]))
            cite = self._cite(version, single)
            text = str(row["text"])
            units.append(
                UnitText(
                    cite=str(cite),
                    url=cite.url(self.base_url),
                    anchor=str(single),
                    anchor_label=self.anchor_label(version, single),
                    tier=version.tier,
                    text=policy.full_text(text, version.tier) if access.full_text else None,
                    excerpt=None if access.full_text else policy.clip(text, version.tier),
                    source_url=source_link(version.source_url, single, paged=version.paged),
                )
            )
        return units

    def document_card(self, ref: Ref | str) -> DocumentCard:
        """A document's record: metadata, versions, licence and outline. Same for both tiers."""
        resolved = self.resolve(ref if isinstance(ref, str) else Ref(ref.doc, ref.version))
        document, version = resolved.document, resolved.version
        doc = DocId.parse(document.doc_id)
        versions = self.versions(document.doc_id)
        outline: list[OutlineItem] = []
        for entry in self.outline(version.version_id):
            cite = self._cite(version, Anchor.parse(entry.anchor))
            outline.append(
                OutlineItem(
                    level=entry.level,
                    title=entry.title,
                    anchor=entry.anchor,
                    cite=str(cite),
                    url=cite.url(self.base_url),
                )
            )
        return DocumentCard(
            doc_id=document.doc_id,
            title=document.title,
            url=Ref(doc).url(self.base_url),
            authors=document.authors,
            org=document.org,
            kind=document.kind,
            collection=document.collection,
            published=document.published,
            source_url=document.source_url,
            version=version.label,
            versions=[
                VersionSummary(
                    version=v.label,
                    published=v.published,
                    observed_at=v.observed_at,
                    tier=v.tier,
                    licence=v.licence,
                    url=Ref(doc, v.label).url(self.base_url),
                    latest=v.version_id == versions[-1].version_id,
                )
                for v in versions
            ],
            tier=version.tier,
            licence=version.licence,
            anchor_kind=version.anchor_kind,
            fidelity=version.fidelity,
            unit_count=len(self._units(version)),
            outline=outline,
        )

    # ------------------------------------------------------------------ quote checking

    def _location(self, version: Version, span: Span) -> QuoteLocation:
        anchor = self.locate(version, span.start, span.end)
        cite = self._cite(version, anchor)
        return QuoteLocation(
            cite=str(cite),
            url=cite.url(self.base_url),
            anchor=str(anchor),
            spine_start=span.start,
            spine_end=span.end,
            text=policy.clip(span.text, version.tier),
        )

    def _quote_check(
        self, quote: str, cite: str | None, version: Version, result: QuoteResult
    ) -> QuoteCheck:
        segments = [
            QuoteSegment(
                quote=s.quote,
                verdict=s.verdict,
                location=None if s.span is None else self._location(version, s.span),
                diff=[QuoteDiff(op=d.op, quote=d.quote, source=d.source) for d in s.diff],
                similarity=s.similarity,
            )
            for s in result.segments
        ]
        return QuoteCheck(
            quote=quote,
            cite=cite,
            verdict=result.verdict,
            passed=result.passed,
            reason=result.reason,
            tier=version.tier,
            fidelity=version.fidelity,
            locations=[s.location for s in segments if s.location is not None],
            segments=segments,
            ambiguous=result.ambiguous,
            other_locations=[self._location(version, s) for s in result.other_spans],
        )

    def verify_quote(self, quote: str, ref: Ref | Citation | str) -> QuoteCheck:
        """Check a quote against one document.

        With an anchor, the anchor is the scope: found there is ``exact`` or ``normalized``;
        found only elsewhere in the same version is ``elsewhere``. Without an anchor the whole
        version is searched (the latest version, if none is named).

        Works the same for both tiers; a link-only document's source text comes back as a short
        excerpt. Raises :class:`NotFoundError` for a ref that does not resolve and
        :class:`onthepage.quote.QuoteTooShortError` for a quote too short to check.
        """
        resolved = self.resolve(ref)
        result = verify_quote(quote, self.private_skeleton(resolved.version), scope=resolved.scope)
        cite = str(resolved.ref) if resolved.anchor is not None else None
        return self._quote_check(quote, cite, resolved.version, result)

    def check_answer(self, text: str) -> AnswerAudit:
        """Audit a draft answer: does every citation resolve, and is every quotation on the page
        it is attached to? Deterministic. Says nothing about whether a page supports a claim."""
        parsed = parse_answer(text)
        audits: list[CitationAudit] = []
        by_position: dict[int, CitationAudit] = {}
        for found in parsed.citations:
            citation = found.citation
            audit = CitationAudit(
                raw=found.raw, cite=str(citation), url=citation.url(self.base_url), resolves=True
            )
            try:
                audit.tier = self.resolve(citation).version.tier
            except NotFoundError as exc:
                audit.resolves = False
                audit.error = str(exc)
            audits.append(audit)
            by_position[found.start] = audit

        unattached: list[str] = []
        verdicts: Counter[str] = Counter()
        quote_count = 0
        passed = 0
        for quote in parsed.quotes:
            if quote.citation is None:
                unattached.append(quote.text)
                continue
            audit = by_position[quote.citation.start]
            quote_count += 1
            if not audit.resolves:
                audit.quotes.append(
                    QuoteAudit(quote=quote.text, check=None, error="the citation does not resolve")
                )
                verdicts["unchecked"] += 1
                continue
            try:
                check = self.verify_quote(quote.text, quote.citation.citation)
            except QuoteTooShortError as exc:
                audit.quotes.append(QuoteAudit(quote=quote.text, check=None, error=str(exc)))
                verdicts["unchecked"] += 1
                continue
            audit.quotes.append(QuoteAudit(quote=quote.text, check=check))
            verdicts[check.verdict.value] += 1
            passed += check.passed

        resolved_count = sum(a.resolves for a in audits)
        parts = [f"{len(audits)} citations: {resolved_count} resolve"]
        if quote_count:
            detail = ", ".join(f"{n} {name}" for name, n in sorted(verdicts.items()))
            parts.append(f"{quote_count} quotations: {detail}")
        if unattached:
            parts.append(f"{len(unattached)} quotations with no citation")
        return AnswerAudit(
            citations=audits,
            unattached_quotes=unattached,
            citation_count=len(audits),
            resolved_count=resolved_count,
            quote_count=quote_count,
            passed_count=passed,
            verdict_counts=dict(sorted(verdicts.items())),
            summary="; ".join(parts) + ". Support is not checked: read the cited pages.",
        )

    # ------------------------------------------------------------------ gates

    def counts(self) -> dict[str, Any]:
        tiers: dict[str, dict[str, int]] = {t.value: {"versions": 0, "units": 0} for t in Tier}
        for version in self.all_versions():
            tiers[version.tier.value]["versions"] += 1
            tiers[version.tier.value]["units"] += len(self._units(version))
        return {
            "documents": self.conn.execute("SELECT count(*) FROM documents").fetchone()[0],
            "versions": sum(t["versions"] for t in tiers.values()),
            "units": sum(t["units"] for t in tiers.values()),
            "by_tier": tiers,
        }

    def validate(self) -> list[str]:
        """Mechanical invariants. Returns the problems found; an empty list is a pass.

        A snapshot is not sealed unless this is empty.
        """
        problems: list[str] = []
        for doc_id in self.doc_ids():
            try:
                DocId.parse(doc_id)
            except IdError as exc:
                problems.append(f"{doc_id}: {exc}")
            if not self.versions(doc_id):
                problems.append(f"{doc_id}: no versions")
        for version in self.all_versions():
            where = version.ref
            decision = decide_tier(self.licence_fact(version.version_id))
            if (decision.tier, decision.licence) != (version.tier, version.licence):
                problems.append(
                    f"{where}: stored tier {version.tier.value} ({version.licence}) does not "
                    f"follow from its licence fact, which gives {decision.tier.value} "
                    f"({decision.licence})"
                )
            pages = self.pages(version.version_id)
            blocks = self.blocks(version.version_id)
            if version.paged:
                if not pages:
                    problems.append(f"{where}: paged version with no pages")
                if [p.page for p in pages] != list(range(1, len(pages) + 1)):
                    problems.append(f"{where}: pages are not numbered 1..N without gaps")
                texts = [p.text for p in pages]
                spans = [(p.spine_start, p.spine_end) for p in pages]
            else:
                if pages:
                    problems.append(f"{where}: unpaged version has pages")
                if not blocks:
                    problems.append(f"{where}: unpaged version with no blocks")
                texts = [b.text for b in blocks]
                spans = [(b.spine_start, b.spine_end) for b in blocks]
            offset = 0
            for i, (text, span) in enumerate(zip(texts, spans, strict=True), start=1):
                if span != (offset, offset + len(text)):
                    problems.append(
                        f"{where}: unit {i} has spine offsets {span}, expected "
                        f"({offset}, {offset + len(text)})"
                    )
                    break
                offset += len(text) + len(SPINE_SEPARATOR)
            spine_length = max(offset - len(SPINE_SEPARATOR), 0)
            if not all(is_clean(text) for text in texts):
                problems.append(
                    f"{where}: text holds control, tag or bidi characters; it did not go "
                    "through onthepage.text.clean_text"
                )
            if version.paged:
                spine = self.private_spine_text(version)
                for block in blocks:
                    if block.spine_start is None or block.spine_end is None:
                        continue
                    if not 0 <= block.spine_start < block.spine_end <= spine_length:
                        problems.append(f"{where}/b{block.anchor}: span outside the spine")
                    elif not spine[block.spine_start : block.spine_end].strip():
                        problems.append(f"{where}/b{block.anchor}: span covers no text")
            anchors = [b.anchor for b in blocks]
            next_block = self.conn.execute(
                "SELECT next_block FROM versions WHERE version_id = ?", (version.version_id,)
            ).fetchone()[0]
            if anchors and max(anchors) >= next_block:
                problems.append(f"{where}: next_block {next_block} would re-mint an anchor")
            for entry in self.outline(version.version_id):
                try:
                    self._scope(version, Anchor.parse(entry.anchor))
                except (NotFoundError, IdError) as exc:
                    problems.append(f"{where}: outline entry {entry.title!r}: {exc}")
        return problems
