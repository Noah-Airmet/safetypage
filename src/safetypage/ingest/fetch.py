"""Fetching, politely, with every response kept.

Each successful response body goes into the blob store, and a row in ``fetches`` (in the ingest
state database) records the URL, the final URL, status, media type and hash. A URL fetched once
is not fetched again unless asked, so re-running the pipeline costs no network.

Politeness: one request at a time per host, at least ``min_interval`` seconds apart, longer if the
host's robots.txt sets a ``Crawl-delay``; paths robots.txt disallows are not fetched.
"""

from __future__ import annotations

import sqlite3
import threading
import time
import urllib.robotparser
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

import httpx

from safetypage.blobs import BlobStore
from safetypage.corpus import utc_now

__all__ = ["PARALLEL", "USER_AGENT", "FetchError", "Fetched", "Fetcher"]

USER_AGENT: Final = "Mozilla/5.0 (compatible; corpus-ingest/0.1)"
_INTERVALS: Final = {"www.lesswrong.com": 3.0, "arxiv.org": 15.0}
PARALLEL: Final = {"storage.googleapis.com": 6}
"""Hosts built for bulk download (arXiv's public bucket): several at once, no pacing."""

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS fetches (
    url TEXT PRIMARY KEY, final_url TEXT, status INTEGER, media_type TEXT,
    sha256 TEXT, bytes INTEGER, fetched_at TEXT NOT NULL, error TEXT
)
"""


class FetchError(Exception):
    def __init__(self, url: str, reason: str, status: int | None = None) -> None:
        super().__init__(f"{url}: {reason}")
        self.url, self.reason, self.status = url, reason, status


@dataclass(frozen=True)
class Fetched:
    url: str
    final_url: str
    media_type: str
    sha256: str
    bytes: int
    fetched_at: str


class Fetcher:
    def __init__(self, db: sqlite3.Connection, blobs: BlobStore, *, min_interval: float = 1.0):
        self.db, self.blobs, self.min_interval = db, blobs, min_interval
        self.db.execute(_SCHEMA)
        self.db.commit()
        self._db_lock = threading.Lock()
        self._host_locks: dict[str, threading.Semaphore] = {}
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._guard = threading.Lock()
        self.client = httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(60.0, connect=20.0),
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        )

    # ---------------------------------------------------------------- cache

    def cached(self, url: str) -> Fetched | None:
        with self._db_lock:
            row = self.db.execute(
                "SELECT url, final_url, media_type, sha256, bytes, fetched_at FROM fetches "
                "WHERE url = ? AND sha256 IS NOT NULL",
                (url,),
            ).fetchone()
        if row is None or not self.blobs.has(row[3]):
            return None
        return Fetched(*row)

    def record(
        self, url: str, data: bytes, media_type: str, final_url: str | None = None
    ) -> Fetched:
        """Store a body as the response for ``url`` (also how a browser session hands in pages)."""
        digest = self.blobs.put(data)
        fetched = Fetched(url, final_url or url, media_type, digest, len(data), utc_now())
        with self._db_lock:
            self.db.execute(
                "INSERT OR REPLACE INTO fetches VALUES (?,?,?,?,?,?,?,NULL)",
                (url, fetched.final_url, 200, media_type, digest, len(data), fetched.fetched_at),
            )
            self.db.commit()
        return fetched

    def _record_error(self, url: str, status: int | None, error: str) -> None:
        with self._db_lock:
            self.db.execute(
                "INSERT OR REPLACE INTO fetches VALUES (?,?,?,?,?,?,?,?)",
                (url, None, status, None, None, None, utc_now(), error),
            )
            self.db.commit()

    # ---------------------------------------------------------------- politeness

    def _host_lock(self, host: str) -> threading.Semaphore:
        with self._guard:
            return self._host_locks.setdefault(host, threading.Semaphore(PARALLEL.get(host, 1)))

    def _robots_for(self, scheme: str, host: str) -> urllib.robotparser.RobotFileParser | None:
        if host in self._robots:
            return self._robots[host]
        parser: urllib.robotparser.RobotFileParser | None = None
        try:
            r = self.client.get(f"{scheme}://{host}/robots.txt", timeout=20.0)
            if r.status_code == 200 and "html" not in r.headers.get("content-type", ""):
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(r.text.splitlines())
        except httpx.HTTPError:
            parser = None
        self._robots[host] = parser
        return parser

    def _interval(self, host: str, robots: urllib.robotparser.RobotFileParser | None) -> float:
        interval = _INTERVALS.get(host, self.min_interval)
        if robots is not None:
            delay = robots.crawl_delay(USER_AGENT)
            if delay is not None:
                interval = max(interval, float(delay))
        return min(interval, 30.0)

    # ---------------------------------------------------------------- fetching

    def get(self, url: str, *, refresh: bool = False, robots: bool = True) -> Fetched:
        if not refresh and (hit := self.cached(url)) is not None:
            return hit
        parts = urlsplit(url)
        host = parts.netloc.lower()
        with self._host_lock(host):
            rules = self._robots_for(parts.scheme, host) if robots else None
            if rules is not None and not rules.can_fetch(USER_AGENT, url):
                self._record_error(url, None, "robots.txt disallows this path")
                raise FetchError(url, "robots.txt disallows this path")
            if host not in PARALLEL:
                wait = self._last.get(host, 0.0) + self._interval(host, rules) - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
            try:
                response = self._request(url)
            finally:
                self._last[host] = time.monotonic()
        if response.status_code != 200:
            reason = f"HTTP {response.status_code}"
            self._record_error(url, response.status_code, reason)
            raise FetchError(url, reason, response.status_code)
        media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        return self.record(url, response.content, media_type, str(response.url))

    def _request(self, url: str) -> httpx.Response:
        last: Exception | None = None
        for attempt in range(3):
            try:
                response = self.client.get(url)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    time.sleep(5 * (attempt + 1))
                    continue
                return response
            except httpx.HTTPError as exc:
                last = exc
                time.sleep(3 * (attempt + 1))
        self._record_error(url, None, f"network error: {last}")
        raise FetchError(url, f"network error: {last}")

    def post_json(self, url: str, payload: object) -> object:
        """A paced JSON POST (GraphQL). Not cached here; callers store what they keep."""
        host = urlsplit(url).netloc.lower()
        with self._host_lock(host):
            rules = self._robots_for(urlsplit(url).scheme, host)
            wait = self._last.get(host, 0.0) + self._interval(host, rules) - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                for attempt in range(3):
                    try:
                        response = self.client.post(url, json=payload, timeout=120.0)
                    except httpx.HTTPError as exc:
                        if attempt == 2:
                            raise FetchError(url, f"network error: {exc}") from exc
                        time.sleep(10 * (attempt + 1))
                        continue
                    if response.status_code == 200:
                        return response.json()
                    if attempt == 2:
                        raise FetchError(url, f"HTTP {response.status_code}", response.status_code)
                    time.sleep(10 * (attempt + 1))
            finally:
                self._last[host] = time.monotonic()
        raise FetchError(url, "unreachable")  # pragma: no cover
