"""The compiled Tantivy queries mean what the grammar says, and the highlighter agrees."""

from __future__ import annotations

from pathlib import Path

import pytest
import tantivy

from safetypage.search.grammar import parse_query
from safetypage.search.highlight import find_spans
from safetypage.search.lexical import (
    ANALYZER,
    analyzer,
    compile_query,
    date_key,
    schema,
    title_keys,
)

TEXTS = {
    "gap0": "alpha beta",
    "gap1": "alpha x beta",
    "gap2": "alpha x y beta",
    "gap3": "alpha x y z beta",
    "gap5": "alpha x y z w v beta",
    "rev0": "beta alpha",
    "rev1": "beta x alpha",
    "rev3": "beta x y z alpha",
    "fold": "Café naïve ASL-3 sparse autoencoders sparsity",
    "hyph": "a well-known fact; un-able to refuse",
}


@pytest.fixture(scope="module")
def index(tmp_path_factory: pytest.TempPathFactory) -> tantivy.Index:
    directory: Path = tmp_path_factory.mktemp("lexical")
    built = tantivy.Index(schema(), path=str(directory))
    built.register_tokenizer(ANALYZER, analyzer())
    writer = built.writer(num_threads=1)
    for cite, text in TEXTS.items():
        doc = tantivy.Document()
        doc.add_text("text", text)
        doc.add_text("cite", cite)
        doc.add_integer("version_id", 1)
        doc.add_integer("date", 0)
        doc.add_integer("latest", 1)
        writer.add_document(doc)
    writer.commit()
    writer.wait_merging_threads()
    built.reload()
    return built


def run(index: tantivy.Index, query: str) -> set[str]:
    compiled = compile_query(index.schema, parse_query(query), [])
    searcher = index.searcher()
    return {str(searcher.doc(a)["cite"][0]) for _, a in searcher.search(compiled, 50).hits}


def highlighted(query: str) -> set[str]:
    parsed = parse_query(query)
    return {cite for cite, text in TEXTS.items() if find_spans(text, parsed)}


# NEAR/n: both words, either order, at most n other words between them.
@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (0, {"gap0", "rev0"}),
        (1, {"gap0", "gap1", "rev0", "rev1"}),
        (2, {"gap0", "gap1", "gap2", "rev0", "rev1"}),
        (3, {"gap0", "gap1", "gap2", "gap3", "rev0", "rev1", "rev3"}),
        (5, {"gap0", "gap1", "gap2", "gap3", "gap5", "rev0", "rev1", "rev3"}),
    ],
)
def test_near_golden(index: tantivy.Index, n: int, expected: set[str]) -> None:
    query = f"alpha NEAR/{n} beta"
    assert run(index, query) == expected
    assert highlighted(query) == expected


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ('"alpha beta"', {"gap0"}),
        ("alpha beta", {"gap0", "gap1", "gap2", "gap3", "gap5", "rev0", "rev1", "rev3"}),
        ("cafe NAIVE", {"fold"}),
        ('"ASL-3"', {"fold"}),
        ("asl-3", {"fold"}),
        ("spars*", {"fold"}),
        ('"sparse auto*"', {"fold"}),
        ('"well known"', {"hyph"}),
        (
            '"able to refuse"',
            {"hyph"},
        ),  # the word split is the engine's; the quote checker is stricter
    ],
)
def test_engine_and_highlighter_agree(index: tantivy.Index, query: str, expected: set[str]) -> None:
    assert run(index, query) == expected
    assert highlighted(query) == expected


def test_exclusion(index: tantivy.Index) -> None:
    assert run(index, "alpha -x") == {"gap0", "rev0"}
    assert run(index, 'alpha -"x y"') == {"gap0", "gap1", "rev0", "rev1"}


def test_disjunctive_reading(index: tantivy.Index) -> None:
    compiled = compile_query(index.schema, parse_query("alpha cafe"), [], disjunctive=True)
    searcher = index.searcher()
    found = {str(searcher.doc(a)["cite"][0]) for _, a in searcher.search(compiled, 50).hits}
    assert found == {c for c in TEXTS if c != "hyph"}


def test_date_key() -> None:
    assert date_key("2023-05-24") == 20230524
    assert date_key("2023-05") == 20230500
    assert date_key("2023-05", end=True) == 20230599
    assert date_key("2023", end=True) == 20239999
    assert date_key(None) == 0


def test_title_keys() -> None:
    assert title_keys("Zoom In: An Introduction to Circuits") == [
        "zoom in an introduction to circuits",
        "zoom in",
    ]
    assert title_keys("Artificial Intelligence Risk Management Framework (AI RMF 1.0)")[1] == (
        "artificial intelligence risk management framework"
    )
    assert title_keys("GPT-5 System Card") == ["gpt 5 system card"]
    assert title_keys("") == []
