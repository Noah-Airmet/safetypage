from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from pathlib import Path

import numpy as np
import pytest

from safetypage.build.snapshot import build_snapshot
from safetypage.corpus import Corpus
from safetypage.search.backend import SnapshotSearch
from safetypage.search.dense import Matrix, embed_units, model_slug
from safetypage.search.grammar import words

FAKE_MODEL = "test/fake-embedding"


class FakeEmbedder:
    """Bag of hashed words, normalised: texts sharing words are near. Deterministic."""

    name = FAKE_MODEL
    dim = 64

    def __init__(self) -> None:
        self.calls = 0

    def _one(self, text: str) -> Matrix:
        vector = np.zeros(self.dim, dtype=np.float32)
        for word, _, _ in words(text):
            vector[int(hashlib.sha256(word.encode()).hexdigest(), 16) % self.dim] += 1.0
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector

    def encode_documents(self, texts: Sequence[str]) -> Matrix:
        self.calls += len(texts)
        return (
            np.stack([self._one(t) for t in texts])
            if texts
            else np.zeros((0, self.dim), dtype=np.float32)
        )

    def encode_query(self, text: str) -> Matrix:
        return self._one(text)


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture(scope="session")
def search_root(fixture_db: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A data root with two sealed fixture snapshots: 2026.11.0 (no vectors) and 2026.11.1
    (vectors from the fake embedder). No page images; tests/build covers those."""
    root = tmp_path_factory.mktemp("search-root")
    build_snapshot(fixture_db, root, "2026.11.0", images=False, dense_model=None)
    with Corpus.open(fixture_db, readonly=True) as corpus:
        embed_units(corpus, root / "embeddings" / model_slug(FAKE_MODEL), FakeEmbedder())
    build_snapshot(fixture_db, root, "2026.11.1", images=False, dense_model=FAKE_MODEL)
    return root


@pytest.fixture(scope="session")
def lexical_backend(search_root: Path) -> Iterator[SnapshotSearch]:
    backend = SnapshotSearch(
        search_root / "snapshots" / "2026.11.0", base_url="https://safetypage.test"
    )
    yield backend
    backend.close()


@pytest.fixture(scope="session")
def dense_backend(search_root: Path) -> Iterator[SnapshotSearch]:
    backend = SnapshotSearch(
        search_root / "snapshots" / "2026.11.1",
        base_url="https://safetypage.test",
        embedder=FakeEmbedder(),
    )
    yield backend
    backend.close()
