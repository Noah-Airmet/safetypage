"""The ingest run end to end, offline: inventory rows in, a valid corpus out, re-runnable."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from safetypage.ingest.fetch import FetchError
from safetypage.ingest.items import load_items
from safetypage.ingest.pipeline import Pipeline, _version_source  # pyright: ignore[reportPrivateUsage]
from safetypage.model import Rendition

FIXTURES = Path(__file__).parents[2] / "fixtures" / "corpus" / "sources"


def _row(doc_id: str, url: str, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "doc_id": doc_id,
        "title": doc_id,
        "publisher": "Example Lab (Blog)",
        "authors": [],
        "date": None,
        "doc_type": "report",
        "url": url,
        "licence": "all-rights-reserved",
        "licence_evidence": "no licence on the page",
    }
    row.update(extra)
    return row


def _scope(tmp: Path) -> Path:
    scope = tmp / "scope"
    scope.mkdir()
    rows = [
        _row("example:paper", "https://example.org/v1.pdf", date="2023-05-01"),
        _row("example:paper", "https://example.org/v2.pdf", date="2023-06-01"),
        _row("example:paper", "https://example.org/v2-copy.pdf", date="2023-06-02"),
        _row(
            "nist:ai-100-1",
            "https://example.org/nist.pdf",
            licence="LicenseRef-US-Gov-PD",
            doc_type="framework",
        ),
        _row("distill:zoom-in", "https://example.org/zoom-in/", licence="CC-BY-4.0"),
        _row("example:broken", "https://example.org/broken"),
        _row("example:missing", "https://example.org/missing"),
    ]
    (scope / "evaluators.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    for shelf in ("labs", "lab-research-web", "government", "welfare"):
        (scope / f"{shelf}.jsonl").write_text("", encoding="utf-8")
    return scope


def test_ingest_run(tmp_path: Path) -> None:
    pipeline = Pipeline(tmp_path / "data", _scope(tmp_path))
    pipeline.log = lambda _message: None
    record = pipeline.fetcher.record
    record(
        "https://example.org/v1.pdf",
        (FIXTURES / "arxiv-2305.15324v1.pdf").read_bytes(),
        "application/pdf",
    )
    v2 = (FIXTURES / "arxiv-2305.15324v2.pdf").read_bytes()
    record("https://example.org/v2.pdf", v2, "application/pdf")
    record("https://example.org/v2-copy.pdf", v2, "application/pdf")
    record(
        "https://example.org/nist.pdf",
        (FIXTURES / "nist-ai-100-1.pdf").read_bytes(),
        "application/pdf",
    )
    record(
        "https://example.org/zoom-in/",
        (FIXTURES / "distill-zoom-in.reduced.html").read_bytes(),
        "text/html",
    )
    record("https://example.org/broken", b"\x00\x01binary", "application/octet-stream")

    # Offline: a URL not handed in above fails as a 404, and the run goes on.
    items, _ = load_items(pipeline.scope)
    assert len(items) == 7

    def offline(url: str, **_kwargs: Any) -> Any:
        hit = pipeline.fetcher.cached(url)
        if hit is None:
            raise FetchError(url, "HTTP 404", 404)
        return hit

    pipeline.fetcher.get = offline  # type: ignore[method-assign]
    counts = pipeline.run()
    assert counts == {"ok": 4, "duplicate": 1, "unsupported": 1, "fetch_failed": 1}

    corpus = pipeline.corpus
    assert corpus.validate() == []
    versions = corpus.versions("example:paper")
    assert [v.label for v in versions] == ["r1", "r2"]
    assert all(v.anchor_kind == "page" for v in versions)
    assert corpus.versions("nist:ai-100-1")[0].tier.value == "open"
    zoom = corpus.versions("distill:zoom-in")[0]
    assert zoom.anchor_kind == "block"
    assert zoom.licence == "CC-BY-4.0"
    assert corpus.outline(zoom.version_id)
    check = corpus.verify_quote(
        "Model evaluation is not the only tool available", "example:paper/r2"
    )
    assert check.passed

    # Re-running does nothing new; the failures are listed with their reasons.
    again = pipeline.run(retry=False)
    assert again == counts
    assert len(corpus.all_versions()) == 4
    summary = pipeline.write_status(tmp_path / "status")
    assert summary["versions"] == 4
    unfetched = (tmp_path / "status" / "unfetched.jsonl").read_text(encoding="utf-8")
    assert "example:missing" in unfetched
    aside = (tmp_path / "status" / "set-aside.jsonl").read_text(encoding="utf-8")
    assert "example:broken" in aside

    # A row moved out of the inventory leaves the corpus; a refetched document comes back.
    evaluators = pipeline.scope / "evaluators.jsonl"
    rows = evaluators.read_text(encoding="utf-8").splitlines(keepends=True)
    evaluators.write_text("".join(r for r in rows if "nist.pdf" not in r), encoding="utf-8")
    assert pipeline.prune(["distill:zoom-in"]) == ["distill:zoom-in", "nist:ai-100-1"]
    assert corpus.document("nist:ai-100-1") is None
    assert corpus.validate() == []
    assert pipeline.run(retry=False)["ok"] == 3
    assert corpus.versions("distill:zoom-in")[0].label == "r1"
    assert corpus.validate() == []


def test_paper_and_forum_items(tmp_path: Path) -> None:
    scope = tmp_path / "scope"
    scope.mkdir()
    papers: list[dict[str, Any]] = [
        {
            "title": "New",
            "authors": [],
            "date": "2023-05-24",
            "arxiv_id": "2305.15324",
            "versions": [{"version": "v1"}, {"version": "v2", "date": "Thu, 25 May 2023 GMT"}],
            "licence": "CC-BY-4.0",
            "licence_evidence": "x",
            "pdf_url": None,
        },
        {
            "title": "Old",
            "authors": [],
            "date": "2001",
            "arxiv_id": "cs/0112001",
            "versions": [{"version": "v1"}],
            "licence": "arxiv-default",
            "licence_evidence": "x",
        },
        {
            "title": "ACL",
            "authors": [],
            "date": "2024",
            "arxiv_id": None,
            "versions": [],
            "acl_id": "2024.acl-long.787",
            "pdf_url": "https://aclanthology.org/2024.acl-long.787.pdf",
            "licence": "CC-BY-4.0",
            "licence_evidence": "ACL Anthology rule",
        },
        {
            "title": "OR",
            "authors": [],
            "date": "2020",
            "arxiv_id": None,
            "versions": [],
            "pdf_url": "https://openreview.net/pdf?id=SJlKrkSFPH",
            "licence": "unknown",
            "licence_evidence": "",
        },
        {
            "title": "Nothing",
            "authors": [],
            "date": "2020",
            "arxiv_id": None,
            "versions": [],
            "pdf_url": None,
            "url": None,
            "licence": "unknown",
            "licence_evidence": "",
        },
    ]
    (scope / "papers.jsonl").write_text("".join(json.dumps(p) + "\n" for p in papers))
    post = {
        "post_id": "aiQabnugDhcrFtr9n",
        "url": "https://www.lesswrong.com/posts/x/y",
        "title": "T",
        "authors": ["A"],
        "date": "2007-01-01",
        "af": False,
        "licence": "unknown",
        "licence_evidence": "terms",
        "crosspost": None,
    }
    (scope / "forum-posts.jsonl").write_text(json.dumps(post) + "\n")
    items, unfetchable = load_items(scope, ("papers", "forum"))
    by_id = {i.doc_id: i for i in items}
    assert by_id["arxiv:2305.15324"].label == "v2"
    assert by_id["arxiv:cs.0112001"].url == "cs/0112001"
    assert by_id["acl:2024.acl-long.787"].adapter == "web"
    assert by_id["openreview:SJlKrkSFPH"].kind == "paper"
    assert by_id["lw:aiQabnugDhcrFtr9n"].adapter == "lw"
    assert unfetchable == ["Nothing"]

    # An arXiv version opens on arxiv.org; the mirror it was fetched from stays the fetch record.
    new = by_id["arxiv:2305.15324"]
    rendition = Rendition(
        kind="pdf",
        sha256="0" * 64,
        bytes=1,
        media_type="application/pdf",
        source_url="https://storage.googleapis.com/arxiv-dataset/arxiv/arxiv/pdf/2305/2305.15324v2.pdf",
        fetched_at="2026-11-09T00:00:00Z",
    )
    assert _version_source(new, rendition, "v2") == "https://arxiv.org/pdf/2305.15324v2"
    assert new.source_url == "https://arxiv.org/abs/2305.15324v2"


def test_surname_first_names_are_turned_round() -> None:
    from safetypage.ingest.items import _authors  # noqa: PLC0415  # pyright: ignore[reportPrivateUsage]

    row = {"authors": ["Olah, Chris", "Lubana, Ekdeep Singh", "Anthropic", "Jacy Reese Anthis"]}
    assert _authors(row) == ["Chris Olah", "Ekdeep Singh Lubana", "Anthropic", "Jacy Reese Anthis"]
