from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from onthepage import policy
from onthepage.api import SearchBackend, SearchRequest, SearchResponse
from onthepage.corpus import Corpus
from onthepage.licence import Tier
from onthepage.search.backend import Limits, SnapshotSearch
from onthepage.search.dense import Embedder, embed_units
from onthepage.search.errors import (
    ArmUnavailableError,
    FilterError,
    QuerySyntaxError,
    SearchBusyError,
    SearchTimeoutError,
)


def cites(response: SearchResponse) -> list[str]:
    return [h.cite for h in response.hits]


def test_is_a_search_backend(
    lexical_backend: SnapshotSearch, dense_backend: SnapshotSearch
) -> None:
    backend: SearchBackend = lexical_backend
    assert backend.snapshot == "2026.11.0"
    assert backend.arms == ("bm25",)
    assert dense_backend.arms == ("bm25", "dense", "hybrid")


def test_phrase_hit_is_the_page_with_offsets(lexical_backend: SnapshotSearch) -> None:
    response = lexical_backend.search(SearchRequest(query='"is not the only tool"'))
    assert response.arm == "bm25" and response.snapshot == "2026.11.0"
    assert cites(response) == ["arxiv:2305.15324/v2/p6"]
    hit = response.hits[0]
    assert hit.id == hit.cite and hit.url == "https://onthepage.test/d/arxiv/2305.15324/v2/p6"
    assert hit.title.endswith("— p. 6") and hit.anchor_label == "p. 6"
    assert hit.tier is Tier.OPEN and hit.licence == "CC-BY-4.0" and hit.kind == "paper"
    assert hit.source_url.endswith("#page=6")
    assert [hit.snippet[s:e].lower() for s, e in hit.match_spans] == ["is not the only tool"]
    assert '"is not the only tool"' in response.interpretation


def test_blocks_are_units_too(lexical_backend: SnapshotSearch) -> None:
    response = lexical_backend.search(SearchRequest(query='"rigorously studied"'))
    assert cites(response) and all(c.startswith("distill:zoom-in/r1/b") for c in cites(response))


def test_latest_version_by_default(lexical_backend: SnapshotSearch) -> None:
    query = '"model evaluation"'
    latest = lexical_backend.search(SearchRequest(query=query, limit=25))
    assert not any("/v1/" in c for c in cites(latest))
    every = lexical_backend.search(SearchRequest(query=query, all_versions=True))
    assert every.total > latest.total
    v1 = lexical_backend.search(SearchRequest(query=query, doc="arxiv:2305.15324/v1"))
    assert v1.total and all(c.startswith("arxiv:2305.15324/v1/") for c in cites(v1))
    one = lexical_backend.search(SearchRequest(query=query, doc="arxiv:2305.15324"))
    assert all(c.startswith("arxiv:2305.15324/v2/") for c in cites(one))


def test_filters(lexical_backend: SnapshotSearch) -> None:
    def total(**kwargs: object) -> int:
        return lexical_backend.search(SearchRequest(query="risk", **kwargs)).total  # type: ignore[arg-type]

    everything = total()
    assert total(kind="government") == total(org="nist") == total(org="NIST") > 0
    assert total(collection="evals") + total(collection="government") <= everything
    assert total(date_from="2023-06") < everything
    assert total(date_to="2023-01") == total(kind="government")  # NIST is dated 2023-01
    assert total(date_from="2030") == 0
    assert total(tier=Tier.LINK_ONLY) + total(tier=Tier.OPEN) == everything
    with pytest.raises(FilterError, match="No document has org 'Anthropic'"):
        total(org="Anthropic")
    with pytest.raises(FilterError, match="YYYY"):
        total(date_from="May 2023")
    with pytest.raises(FilterError, match="Unknown document"):
        total(doc="arxiv:9999.99999")
    with pytest.raises(FilterError, match="names a place"):
        total(doc="arxiv:2305.15324/v2/p6")


def test_facets_count_the_matches(lexical_backend: SnapshotSearch) -> None:
    response = lexical_backend.search(SearchRequest(query="risk"))
    assert sum(response.facets["tier"].values()) == response.total
    assert sum(response.facets["kind"].values()) == response.total


def test_link_only_snippets_are_clipped(lexical_backend: SnapshotSearch) -> None:
    response = lexical_backend.search(SearchRequest(query="refusal", tier=Tier.LINK_ONLY))
    assert response.hits
    access = policy.access_for(Tier.LINK_ONLY)
    for hit in response.hits:
        assert hit.tier is Tier.LINK_ONLY
        assert len(hit.snippet) <= access.snippet_chars
        assert len(hit.snippet.split()) <= (access.excerpt_words or 0) + 1


def test_deterministic_and_paged(lexical_backend: SnapshotSearch) -> None:
    request = SearchRequest(query="model", limit=5)
    first = lexical_backend.search(request)
    assert lexical_backend.search(request) == first
    assert first.next_cursor == "5"
    second = lexical_backend.search(request.model_copy(update={"cursor": first.next_cursor}))
    assert not set(cites(first)) & set(cites(second))
    scores = [h.score for h in first.hits + second.hits]
    assert scores == sorted(scores, reverse=True)
    with pytest.raises(FilterError, match="Paging stops"):
        lexical_backend.search(request.model_copy(update={"cursor": "248"}))
    with pytest.raises(FilterError, match="not a cursor"):
        lexical_backend.search(request.model_copy(update={"cursor": "abc"}))


def test_sort_by_date(lexical_backend: SnapshotSearch) -> None:
    response = lexical_backend.search(SearchRequest(query="risk", sort="date", limit=25))
    dates = [h.date or "" for h in response.hits]
    assert dates == sorted(dates, reverse=True)
    assert "newest first" in response.interpretation


def test_documents_mode(lexical_backend: SnapshotSearch) -> None:
    units = lexical_backend.search(SearchRequest(query="risk"))
    docs = lexical_backend.search(SearchRequest(query="risk", mode="documents", limit=25))
    assert docs.mode == "documents" and not docs.hits
    assert sum(d.hit_count for d in docs.documents) == units.total
    counts = [d.hit_count for d in docs.documents]
    assert counts == sorted(counts, reverse=True)
    for document in docs.documents:
        assert 0 < len(document.top) <= 3
        assert all(h.doc_id == document.doc_id for h in document.top)


def test_empty_query_lists_documents(lexical_backend: SnapshotSearch) -> None:
    listing = lexical_backend.search(SearchRequest())
    assert listing.mode == "documents" and listing.total == 6
    assert [d.doc_id for d in listing.documents] == sorted(d.doc_id for d in listing.documents)
    newest = lexical_backend.search(SearchRequest(sort="date", limit=1))
    assert newest.documents[0].doc_id == "example:unlicensed-post"
    papers = lexical_backend.search(SearchRequest(kind="paper", all_versions=True))
    assert [(d.doc_id, d.version) for d in papers.documents] == [
        ("arxiv:2305.15324", "v1"),
        ("arxiv:2305.15324", "v2"),
        ("arxiv:2309.08600", "v3"),
    ]


def test_syntax_errors_teach(lexical_backend: SnapshotSearch) -> None:
    with pytest.raises(QuerySyntaxError, match="OR is not an operator"):
        lexical_backend.search(SearchRequest(query="refusal OR refuse"))


def test_arms(lexical_backend: SnapshotSearch) -> None:
    with pytest.raises(ArmUnavailableError, match="hybrid-rerank arm is not available"):
        lexical_backend.search(SearchRequest(query="risk", arm="hybrid-rerank"))
    with pytest.raises(ArmUnavailableError, match="contextual"):
        lexical_backend.search(SearchRequest(query="risk", arm="contextual"))
    fallback = lexical_backend.search(SearchRequest(query="risk", arm="hybrid"))
    assert fallback.arm == "bm25" and "fell back to bm25" in fallback.interpretation
    assert cites(fallback) == cites(lexical_backend.search(SearchRequest(query="risk")))


def test_dense_and_hybrid(dense_backend: SnapshotSearch) -> None:
    question = "dangerous capability evaluations for extreme risks"
    dense = dense_backend.search(SearchRequest(query=question, arm="dense"))
    assert dense.arm == "dense" and dense.hits
    assert dense.hits[0].doc_id == "arxiv:2305.15324"
    hybrid = dense_backend.search(SearchRequest(query=question, arm="hybrid"))
    assert hybrid.arm == "hybrid" and hybrid.hits
    assert hybrid == dense_backend.search(SearchRequest(query=question, arm="hybrid"))
    # natural language with an OR still works in hybrid, read as words
    assert dense_backend.search(SearchRequest(query="refuse OR refusal", arm="hybrid")).hits
    nist = dense_backend.search(SearchRequest(query=question, arm="dense", org="NIST"))
    assert {h.doc_id for h in nist.hits} == {"nist:ai-100-1"}
    docs = dense_backend.search(SearchRequest(query=question, arm="hybrid", mode="documents"))
    assert docs.documents and all(d.top for d in docs.documents)


def test_time_limit(search_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = SnapshotSearch(
        search_root / "snapshots" / "2026.11.0",
        limits=Limits(time_limit_s=0.05, max_concurrent=1, queue_wait_s=0.01),
    )
    original = backend._run  # pyright: ignore[reportPrivateUsage]
    release = threading.Event()

    def slow(request: SearchRequest) -> SearchResponse:
        release.wait(5)
        return original(request)

    monkeypatch.setattr(backend, "_run", slow)
    try:
        with pytest.raises(SearchTimeoutError, match=r"longer than 0\.05 s"):
            backend.search(SearchRequest(query="risk"))
        # the timed-out query still holds the only slot until it really finishes
        with pytest.raises(SearchBusyError):
            backend.search(SearchRequest(query="risk"))
        release.set()
        time.sleep(0.2)
        assert backend.search(SearchRequest(query="risk")).total
    finally:
        release.set()
        backend.close()


def test_embedding_job_resumes(fixture_db: Path, tmp_path: Path, fake_embedder: Embedder) -> None:
    cache = tmp_path / "cache"
    embedder = fake_embedder
    with Corpus.open(fixture_db, readonly=True) as corpus:
        calls = iter([False, True])
        first = embed_units(corpus, cache, embedder, part_rows=50, stop=lambda: next(calls))
        assert first.stopped_early and first.embedded == 50 and first.remaining > 0
        second = embed_units(corpus, cache, embedder, part_rows=50)
        assert second.cached_before == 50 and second.remaining == 0
        assert getattr(embedder, "calls") == first.embedded + second.embedded  # noqa: B009
        third = embed_units(corpus, cache, embedder, part_rows=50)
        assert third.embedded == 0 and third.units == first.units
