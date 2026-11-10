"""Stand-ins the site develops against until the search and server tracks land.

`library()` loads the fixture corpus through the core library. `search()` is a naive
keyword search that returns the documented `SearchResponse` shape. Neither is the real
index: the site reads the documented layout and API, so the real ones drop in.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from onthepage import policy  # noqa: E402
from onthepage.bundle import load_bundles  # noqa: E402
from onthepage.corpus import Corpus  # noqa: E402

FIXTURES = REPO / "fixtures" / "corpus"
SNAPSHOT = "fixture"


def library(base_url: str = "") -> Corpus:
    corpus = Corpus.memory(base_url=base_url)
    load_bundles(corpus, FIXTURES / "bundles")
    return corpus


def add_missing_words(corpus: Corpus) -> None:
    """Most fixture bundles carry no word boxes. Read them from the fixture PDFs so every
    open page gets a text layer, as ingestion will supply for the real corpus."""
    from fixtures.build import pdf_pages  # needs the `fixtures` dependency group

    sources = json.loads((FIXTURES / "sources.json").read_text())["versions"]
    for entry in sources:
        pdf = entry.get("files", {}).get("pdf")
        if not pdf:
            continue
        ref = f"{entry['document']['doc_id']}/{entry['version']['label']}"
        version = corpus.resolve(ref).version
        have = corpus.conn.execute(
            "SELECT count(*) FROM page_words WHERE version_id = ?", (version.version_id,)
        ).fetchone()[0]
        if have or version.tier != "open":
            continue
        stored = {p.page: p.text for p in corpus.pages(version.version_id)}
        for number, page in enumerate(
            pdf_pages(FIXTURES / "sources" / pdf["name"], with_words=True), 1
        ):
            if page.words is not None and stored.get(number) == page.text:
                corpus.conn.execute(
                    "INSERT INTO page_words (version_id, page, words) VALUES (?,?,?)",
                    (version.version_id, number, json.dumps(page.words, separators=(",", ":"))),
                )
    corpus.conn.commit()


def _terms(query: str) -> tuple[list[str], list[str]]:
    phrases = [p.lower() for p in re.findall(r'"([^"]+)"', query)]
    rest = re.sub(r'"[^"]+"', " ", query)
    words = [w.lower() for w in re.findall(r"[\w'-]+", rest) if not w.upper().startswith("NEAR")]
    return phrases, words


def search(corpus: Corpus, query: str, *, limit: int = 10, doc: str | None = None) -> dict[str, Any]:
    phrases, words = _terms(query)
    needles = phrases + words
    hits: list[dict[str, Any]] = []
    if needles:
        latest = {d: corpus.resolve(d).version.label for d in corpus.doc_ids()}
        rows = corpus.conn.execute(
            "SELECT cite, doc_id, version, anchor, text, tier FROM units ORDER BY cite"
        ).fetchall()
        for row in rows:
            if latest[row["doc_id"]] != row["version"] or (doc and not row["cite"].startswith(doc)):
                continue
            text = row["text"]
            low = text.lower()
            if not all(n in low for n in needles):
                continue
            score = sum(low.count(n) * (3 if " " in n else 1) for n in needles)
            first = min(low.find(n) for n in needles)
            limit_chars = policy.access_for(row["tier"]).snippet_chars
            start = max(0, first - limit_chars // 3)
            if start:
                start = text.find(" ", start) + 1
            snippet = text[start : start + limit_chars].replace("\n", " ")
            spans = sorted(
                (m.start(), m.end())
                for n in needles
                for m in re.finditer(re.escape(n), snippet.lower())
            )
            card = corpus.document_card(row["doc_id"])
            resolved = corpus.resolve(row["cite"])
            hits.append(
                {
                    "id": row["cite"],
                    "title": f"{card.title}, {corpus.anchor_label(resolved.version, resolved.anchor)}",
                    "url": f"{corpus.base_url}/d/{row['cite'].replace(':', '/', 1)}",
                    "cite": row["cite"],
                    "doc_id": row["doc_id"],
                    "version": row["version"],
                    "anchor": row["anchor"],
                    "anchor_label": corpus.anchor_label(resolved.version, resolved.anchor),
                    "doc_title": card.title,
                    "org": card.org,
                    "kind": card.kind,
                    "date": card.published,
                    "tier": row["tier"],
                    "licence": card.licence,
                    "score": float(score),
                    "snippet": snippet,
                    "match_spans": [list(s) for s in spans],
                    "source_url": corpus.read_units(row["cite"])[0].source_url,
                }
            )
    hits.sort(key=lambda h: (-h["score"], h["cite"]))
    return {
        "query": query,
        "interpretation": " AND ".join(f'"{p}"' for p in phrases) + (" " if phrases and words else "") + " AND ".join(words),
        "arm": "standin-keyword",
        "snapshot": SNAPSHOT,
        "mode": "units",
        "total": len(hits),
        "hits": hits[:limit],
        "documents": [],
        "facets": {},
        "next_cursor": None,
    }
