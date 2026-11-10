"""Loading the server from sealed snapshots."""

from __future__ import annotations

from pathlib import Path

import pytest

from onthepage.server.library import Library, ToolError
from onthepage.server.run import load_server
from onthepage.snapshot import resolve_snapshot, seal_snapshot, set_current, stage_snapshot

from .conftest import BASE_URL


def test_load_from_a_data_root_and_from_one_snapshot(lib: Library, tmp_path: Path) -> None:
    root = tmp_path / "data"
    seal_snapshot(stage_snapshot(lib.corpus_path, root, "2026.11.0"))
    set_current(root, "2026.11.0")

    server = load_server(data=root, fixtures=False, base_url=BASE_URL)
    assert set(server.libraries) == {"2026.11.0", "current"}
    assert server.library().snapshot == "2026.11.0"
    hits = server.library().search("bm25", query="risk assessment").hits
    assert hits[0].cite == "arxiv:2305.15324/v2/p6"

    single = load_server(
        data=None, fixtures=False, snapshot=resolve_snapshot(root), base_url=BASE_URL
    )
    assert single.library("2026.11.0") is single.library("current")
    assert single.library().fetch("arxiv:2305.15324/v2/p6").units[0].text


def test_tantivy_snapshot(lib: Library, tmp_path: Path) -> None:
    """With a lexical index the server uses the search track's backend; the tools work the same."""
    lexical = pytest.importorskip("onthepage.search.lexical")
    from onthepage.corpus import Corpus  # noqa: PLC0415

    root = tmp_path / "data"
    staging = stage_snapshot(lib.corpus_path, root, "2026.11.1")
    with Corpus.open(staging / "corpus.sqlite", readonly=True) as corpus:
        lexical.build_lexical_index(corpus, staging / "lexical")
    seal_snapshot(staging)
    sealed = resolve_snapshot(root, "2026.11.1")
    server = load_server(data=None, fixtures=False, snapshot=sealed, base_url=BASE_URL)
    library = server.library()
    assert type(library.backend).__name__ == "SnapshotSearch"
    hits = library.search("bm25", query='"risk assessment"').hits
    assert "arxiv:2305.15324/v2/p6" in {h.cite for h in hits}
    assert library.verify_quote("Model evaluation is not the only tool available").passed
    with pytest.raises(ToolError, match="OR"):
        library.search("bm25", query="refusal OR refuse")
