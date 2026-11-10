"""The ingest run: inventory in, one bundle per version out, stored with ``import_bundle``.

For each document (inventory rows sharing a ``doc_id``, oldest first) every row is fetched,
its text of record extracted (PDF: pages with word boxes; HTML: blocks), its licence fact made,
and the version imported. Network work runs in one thread per host (a few for arXiv's bucket);
parsing and database writes run on the main thread (pdfium is not thread-safe, and the corpus has
one writer).

Re-runnable: fetched files are kept by hash, every inventory row's outcome is recorded in
``ingest.sqlite``, and a row that is done is not touched again. Identical bytes or identical
extracted text under one document are one version, not two. A row that fails is set aside with
its reason and the run goes on; ``write_status`` lists them for a later browser session.
"""

from __future__ import annotations

import email.utils
import hashlib
import json
import queue
import sqlite3
import threading
from collections import OrderedDict, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

from onthepage.blobs import BlobStore
from onthepage.bundle import Bundle, BundleVersion, import_bundle
from onthepage.corpus import Corpus, utc_now
from onthepage.ingest.fetch import PARALLEL, Fetched, Fetcher, FetchError
from onthepage.ingest.html import ExtractError, blocks_from_html, outline_of, page_blocks
from onthepage.ingest.items import Item, load_items
from onthepage.ingest.licence import licence_for
from onthepage.ingest.lw import fetch_posts
from onthepage.ingest.pdf import NeedsOcrError, PdfError, pdf_outline, pdf_pages
from onthepage.model import Document, Rendition

__all__ = ["DONE", "Pipeline", "Result"]

DONE: Final = ("ok", "duplicate")

type _Work = tuple[list[Item], list[Item]]
"""One document's rows, and those of them still to do."""

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS items (
    key TEXT PRIMARY KEY, shelf TEXT, doc_id TEXT, url TEXT, title TEXT,
    status TEXT NOT NULL, reason TEXT, http_status INTEGER,
    version_ref TEXT, text_sha256 TEXT, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS items_doc ON items (doc_id, text_sha256);
"""


@dataclass(frozen=True)
class Result:
    status: str
    """ok | duplicate | fetch_failed | needs_browser | needs_ocr | unsupported | error"""
    reason: str | None = None
    version_ref: str | None = None
    http_status: int | None = None
    text_sha256: str | None = None


def _gcs_url(arxiv_id: str, label: str) -> str:
    if "/" in arxiv_id:  # old style: cs/0112001
        archive, number = arxiv_id.split("/", 1)
        return (
            f"https://storage.googleapis.com/arxiv-dataset/arxiv/{archive}/pdf/"
            f"{number[:4]}/{number}{label}.pdf"
        )
    return (
        f"https://storage.googleapis.com/arxiv-dataset/arxiv/arxiv/pdf/"
        f"{arxiv_id.split('.', maxsplit=1)[0]}/{arxiv_id}{label}.pdf"
    )


def _rfc_date(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return email.utils.parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return None


def _is_pdf(data: bytes) -> bool:
    return b"%PDF-" in data[:1024]


def _host(item: Item) -> str:
    if item.adapter == "lw":
        return "lw"
    if item.adapter == "arxiv":
        return "storage.googleapis.com"
    return urlsplit(item.url).netloc


class Pipeline:
    def __init__(self, data: Path, scope: Path) -> None:
        data.mkdir(parents=True, exist_ok=True)
        self.data, self.scope = data, scope
        self.corpus = Corpus.open(data / "corpus.sqlite")
        self.corpus.conn.execute("PRAGMA journal_mode=WAL")
        self.blobs = BlobStore(data / "blobs")
        fetch_db = sqlite3.connect(data / "ingest.sqlite", check_same_thread=False)
        fetch_db.execute("PRAGMA journal_mode=WAL")
        self.fetcher = Fetcher(fetch_db, self.blobs)
        self.state = sqlite3.connect(data / "ingest.sqlite", timeout=60)
        self.state.executescript(_SCHEMA)
        self.log: Callable[[str], None] = print

    # ------------------------------------------------------------------ state

    def status_of(self, key: str) -> str | None:
        row = self.state.execute("SELECT status FROM items WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def _record(self, item: Item, result: Result) -> None:
        self.state.execute(
            "INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                item.key,
                item.shelf,
                item.doc_id,
                item.url,
                item.title,
                result.status,
                result.reason,
                result.http_status,
                result.version_ref,
                result.text_sha256,
                utc_now(),
            ),
        )
        self.state.commit()

    # ------------------------------------------------------------------ fetching

    def _fetch(self, item: Item, refresh: bool) -> Fetched:
        if item.adapter == "lw":
            hit = self.fetcher.cached(item.key)
            if hit is None:
                raise FetchError(item.key, "post body not fetched from the GraphQL API")
            return hit
        if item.adapter == "arxiv":
            label = item.label or "v1"
            try:
                return self.fetcher.get(_gcs_url(item.url, label), refresh=refresh, robots=False)
            except FetchError as exc:
                if exc.status != 404:
                    raise
            return self.fetcher.get(
                f"https://export.arxiv.org/pdf/{item.url}{label}", refresh=refresh
            )
        return self.fetcher.get(item.url, refresh=refresh)

    def _todo(self, group: list[Item], refresh: bool) -> list[Item]:
        return [i for i in group if refresh or self.status_of(i.key) not in DONE]

    def _fetch_group(
        self, todo: list[Item], refresh: bool
    ) -> list[tuple[Item, Fetched | FetchError]]:
        out: list[tuple[Item, Fetched | FetchError]] = []
        for item in todo:
            try:
                out.append((item, self._fetch(item, refresh)))
            except FetchError as exc:
                out.append((item, exc))
            except Exception as exc:  # a lane must never die: the main thread waits on it
                out.append((item, FetchError(item.url, f"{type(exc).__name__}: {exc}")))
        return out

    # ------------------------------------------------------------------ one version

    def _ingest(self, item: Item, fetched: Fetched, document: Document) -> Result:
        data = self.blobs.get(fetched.sha256)
        post: dict[str, Any] | None = None
        if item.adapter == "lw":
            post = json.loads(data)
            html = str((post or {}).get("contents", {}).get("html") or "")
            blocks = blocks_from_html(html)
            data = html.encode("utf-8")
            sha = self.blobs.put(data)
            rendition = Rendition(
                kind="html",
                sha256=sha,
                bytes=len(data),
                media_type="text/html",
                source_url=item.source_url,
                fetched_at=fetched.fetched_at,
            )
            pages, outline, check_text = [], outline_of(blocks), ""
            if sum(len(b.text) for b in blocks) == 0:
                return Result("unsupported", "the post has no text")
        elif _is_pdf(data):
            try:
                pages = pdf_pages(data)
            except NeedsOcrError as exc:
                return Result("needs_ocr", str(exc))
            except PdfError as exc:
                return Result("unsupported", str(exc))
            blocks, outline = [], pdf_outline(data, pages)
            sha = fetched.sha256
            rendition = Rendition(
                kind="pdf",
                sha256=sha,
                bytes=len(data),
                media_type="application/pdf",
                source_url=fetched.final_url,
                fetched_at=fetched.fetched_at,
            )
            check_text = "\n".join(p.text for p in pages)
        elif "html" in fetched.media_type or data.lstrip()[:1] == b"<":
            try:
                blocks = page_blocks(data, fetched.final_url)
            except ExtractError as exc:
                return Result("needs_browser", str(exc))
            pages, outline = [], outline_of(blocks)
            sha = fetched.sha256
            rendition = Rendition(
                kind="html",
                sha256=sha,
                bytes=len(data),
                media_type="text/html",
                source_url=fetched.final_url,
                fetched_at=fetched.fetched_at,
            )
            check_text = data.decode("utf-8", errors="replace")
        else:
            return Result("unsupported", f"media type {fetched.media_type or 'unknown'}")

        units = [p.text for p in pages] or [b.text for b in blocks]
        text_sha = hashlib.sha256("\n".join(units).encode("utf-8")).hexdigest()
        existing = {v.content_sha256: v for v in self.corpus.versions(item.doc_id)}
        if sha in existing:
            return Result(
                "duplicate",
                "same bytes as an earlier version",
                existing[sha].ref,
                text_sha256=text_sha,
            )
        row = self.state.execute(
            "SELECT version_ref FROM items WHERE doc_id = ? AND text_sha256 = ? AND status = 'ok'",
            (item.doc_id, text_sha),
        ).fetchone()
        if row is not None:
            return Result(
                "duplicate", "same text as an earlier version", row[0], text_sha256=text_sha
            )

        label = item.label
        if label is None:
            observed = sum(1 for v in existing.values() if v.label.startswith("r"))
            label = f"r{observed + 1}"
        elif any(v.label == label for v in existing.values()):
            return Result(
                "duplicate",
                f"{label} is already stored",
                f"{item.doc_id}/{label}",
                text_sha256=text_sha,
            )
        published = item.published
        if item.adapter == "arxiv":
            published = _rfc_date(item.extra.get("version_date")) or published
        bundle = Bundle(
            document=document,
            version=BundleVersion(
                label=label,
                anchor_kind="page" if pages else "block",
                fidelity="text_layer" if pages else "html",
                source_url=rendition.source_url if item.adapter != "lw" else item.source_url,
                content_sha256=sha,
                observed_at=fetched.fetched_at,
                published=published,
            ),
            licence=licence_for(
                item,
                observed_at=fetched.fetched_at,
                content=check_text,
                content_sha256=sha,
                post=post,
            ),
            renditions=[rendition],
            pages=pages,
            blocks=blocks,
            outline=outline,
        )
        try:
            version = import_bundle(self.corpus, bundle)
        except Exception:
            self._discard(item.doc_id, label)
            raise
        return Result("ok", None, version.ref, text_sha256=text_sha)

    def _discard(self, doc_id: str, label: str) -> None:
        """Remove a half-written version (import_bundle writes in several transactions)."""
        conn = self.corpus.conn
        row = conn.execute(
            "SELECT version_id FROM versions WHERE doc_id = ? AND label = ?", (doc_id, label)
        ).fetchone()
        with conn:
            if row is not None:
                for table in (
                    "page_words",
                    "pages",
                    "blocks",
                    "outline",
                    "renditions",
                    "licence_facts",
                    "versions",
                ):
                    conn.execute(f"DELETE FROM {table} WHERE version_id = ?", (row[0],))  # noqa: S608
            if not conn.execute("SELECT 1 FROM versions WHERE doc_id = ?", (doc_id,)).fetchone():
                conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        if row is not None:
            self.corpus._forget(int(row[0]))  # pyright: ignore[reportPrivateUsage]

    # ------------------------------------------------------------------ one document

    @staticmethod
    def _document(group: list[Item]) -> Document:
        newest = group[-1]
        dates = [i.published for i in group if i.published]
        return Document(
            doc_id=newest.doc_id,
            kind=newest.kind,
            title=newest.title,
            authors=newest.authors,
            org=newest.org,
            collection=newest.shelf,
            published=min(dates) if dates else None,
            source_url=newest.source_url,
        )

    def _ingest_group(
        self, group: list[Item], fetched: list[tuple[Item, Fetched | FetchError]]
    ) -> None:
        document = self._document(group)
        for item, got in fetched:
            if isinstance(got, FetchError):
                result = Result("fetch_failed", got.reason, http_status=got.status)
            else:
                try:
                    result = self._ingest(item, got, document)
                except Exception as exc:  # set aside, never stop the run
                    result = Result("error", f"{type(exc).__name__}: {exc}"[:500])
            self._record(item, result)

    # ------------------------------------------------------------------ the run

    def run(
        self,
        *,
        shelves: tuple[str, ...] | None = None,
        only: Iterable[str] = (),
        limit: int | None = None,
        retry: bool = True,
        refresh: bool = False,
    ) -> dict[str, int]:
        items, unfetchable = load_items(self.scope, shelves)
        only = tuple(only)
        if only:
            items = [i for i in items if any(i.doc_id.startswith(o) or i.key == o for o in only)]
        groups: OrderedDict[str, list[Item]] = OrderedDict()
        for item in items:
            groups.setdefault(item.doc_id, []).append(item)
        pending: list[list[Item]] = []
        for group in groups.values():
            group.sort(key=lambda i: i.published or "9999")
            states = [self.status_of(i.key) for i in group]
            if refresh or any(s not in DONE and (retry or s is None) for s in states):
                pending.append(group)
        if limit is not None:
            pending = pending[:limit]
        # One lane per host, so a slow or heavily paced host never holds up the others. The
        # lanes only fetch; parsing and writing happen here, on the main thread.
        by_host: dict[str, list[list[Item]]] = defaultdict(list)
        for group in pending:
            by_host[_host(group[0])].append(group)
        lw_groups = by_host.pop("lw", [])
        self.log(
            f"{len(items)} items, {len(groups)} documents; {len(pending)} to do "
            f"({len(lw_groups)} forum posts); {len(unfetchable)} papers have no URL"
        )
        lanes: list[list[_Work]] = []
        for host, host_groups in by_host.items():
            work = [(g, self._todo(g, refresh)) for g in host_groups]
            n = PARALLEL.get(host, 1)
            lanes += [work[k::n] for k in range(n)]
        results: queue.Queue[tuple[list[Item], list[tuple[Item, Fetched | FetchError]]]] = (
            queue.Queue()
        )

        def lane(work: list[_Work]) -> None:
            for group, todo in work:
                results.put((group, self._fetch_group(todo, refresh)))

        def forum_lane(work: list[_Work]) -> None:
            ids = [g[0].url for g, _ in work]
            failed = fetch_posts(
                self.fetcher,
                ids,
                refresh=refresh,
                progress=lambda n, t: self.log(f"  forum bodies {n}/{t}") if n % 500 < 10 else None,
            )
            for group, todo in work:
                fetched = self._fetch_group(todo, False)
                results.put(
                    (
                        group,
                        [
                            (i, FetchError(i.key, failed[i.url]) if i.url in failed else f)
                            for i, f in fetched
                        ],
                    )
                )

        threads = [threading.Thread(target=lane, args=(w,), daemon=True) for w in lanes if w]
        if lw_groups:
            work = [(g, self._todo(g, refresh)) for g in lw_groups]
            threads.append(threading.Thread(target=forum_lane, args=(work,), daemon=True))
        for thread in threads:
            thread.start()
        for done in range(1, len(pending) + 1):
            group, fetched = results.get()
            self._ingest_group(group, fetched)
            if done % 200 == 0:
                self.log(f"  {done}/{len(pending)} documents")
        for thread in threads:
            thread.join()
        counts: dict[str, int] = defaultdict(int)
        for (status,) in self.state.execute("SELECT status FROM items"):
            counts[status] += 1
        return dict(counts)

    # ------------------------------------------------------------------ reporting

    def write_status(self, out: Path) -> dict[str, Any]:
        """Machine-readable lists of what is not in, and why, plus a summary. No content."""
        out.mkdir(parents=True, exist_ok=True)
        _, unfetchable = load_items(self.scope)
        rows = self.state.execute(
            "SELECT key, shelf, doc_id, url, title, status, reason, http_status FROM items "
            "WHERE status NOT IN ('ok', 'duplicate') ORDER BY shelf, doc_id"
        ).fetchall()
        names = ("key", "shelf", "doc_id", "url", "title", "status", "reason", "http_status")
        browser: list[dict[str, Any]] = [
            dict(zip(names, r, strict=True))
            for r in rows
            if r[5] in ("fetch_failed", "needs_browser")
        ]
        aside: list[dict[str, Any]] = [
            dict(zip(names, r, strict=True))
            for r in rows
            if r[5] not in ("fetch_failed", "needs_browser")
        ]
        browser += [
            {
                "shelf": "papers",
                "title": t,
                "status": "no_url",
                "reason": "the inventory has no fetchable URL for this paper",
            }
            for t in unfetchable
        ]

        def dump(name: str, records: Sequence[Mapping[str, Any]]) -> None:
            (out / name).write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                encoding="utf-8",
            )

        dump("unfetched.jsonl", browser)
        dump("set-aside.jsonl", aside)
        summary = self.summary()
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return summary

    def summary(self) -> dict[str, Any]:
        conn = self.corpus.conn
        by_shelf: dict[str, dict[str, int]] = {}
        for shelf, tier, docs, versions in conn.execute(
            "SELECT d.collection, v.tier, count(DISTINCT d.doc_id), count(*) FROM versions v "
            "JOIN documents d USING (doc_id) GROUP BY d.collection, v.tier"
        ):
            entry = by_shelf.setdefault(shelf, {})
            entry[f"{tier}_documents"] = docs
            entry[f"{tier}_versions"] = versions
        statuses: dict[str, dict[str, int]] = {}
        for shelf, status, n in self.state.execute(
            "SELECT shelf, status, count(*) FROM items GROUP BY shelf, status"
        ):
            statuses.setdefault(shelf, {})[status] = n
        evidence = dict(
            conn.execute(
                "SELECT evidence_kind || ' / ' || producer, count(*) FROM licence_facts "
                "GROUP BY 1 ORDER BY 2 DESC"
            ).fetchall()
        )
        return {
            "documents": conn.execute("SELECT count(*) FROM documents").fetchone()[0],
            "versions": conn.execute("SELECT count(*) FROM versions").fetchone()[0],
            "pages": conn.execute("SELECT count(*) FROM pages").fetchone()[0],
            "blocks": conn.execute("SELECT count(*) FROM blocks").fetchone()[0],
            "by_tier": dict(conn.execute("SELECT tier, count(*) FROM versions GROUP BY tier")),
            "by_licence": dict(
                conn.execute(
                    "SELECT licence, count(*) FROM versions GROUP BY licence ORDER BY 2 DESC"
                )
            ),
            "licence_evidence": evidence,
            "by_shelf": by_shelf,
            "inventory_rows_by_status": statuses,
        }
