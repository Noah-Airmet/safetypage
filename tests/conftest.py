from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from hypothesis import settings

from onthepage.bundle import load_bundles
from onthepage.corpus import Corpus

REPO = Path(__file__).parent.parent
FIXTURES = REPO / "fixtures" / "corpus"
BASE_URL = "https://onthepage.test"

settings.register_profile("default", deadline=None, max_examples=200)
settings.register_profile("ci", deadline=None, max_examples=500)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))


@pytest.fixture(scope="session")
def fixture_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The fixture corpus as a SQLite file, built once per test session."""
    path = tmp_path_factory.mktemp("corpus") / "corpus.sqlite"
    with Corpus.open(path, base_url=BASE_URL) as corpus:
        load_bundles(corpus, FIXTURES / "bundles")
    return path


@pytest.fixture(scope="session")
def library(fixture_db: Path) -> Iterator[Corpus]:
    """The fixture corpus, read-only: real open documents and synthetic link-only ones."""
    with Corpus.open(fixture_db, readonly=True, base_url=BASE_URL) as corpus:
        yield corpus


@pytest.fixture
def empty() -> Iterator[Corpus]:
    with Corpus.memory(base_url=BASE_URL) as corpus:
        yield corpus
