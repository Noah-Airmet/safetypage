from __future__ import annotations

import pytest

from safetypage.search.grammar import (
    DEFAULT_NEAR,
    Near,
    ParsedQuery,
    Phrase,
    Prefix,
    QuerySyntaxError,
    fold,
    parse_query,
    words,
)


@pytest.mark.parametrize(
    ("query", "must", "must_not"),
    [
        ("sparse autoencoder", (Phrase(("sparse",)), Phrase(("autoencoder",))), ()),
        ('"sparse autoencoder"', (Phrase(("sparse", "autoencoder")),), ()),
        ("“sparse autoencoder”", (Phrase(("sparse", "autoencoder")),), ()),
        ('"sparse auto*"', (Phrase(("sparse", "auto"), prefix=True),), ()),
        ("eval*", (Prefix("eval"),), ()),
        ('"eval*"', (Prefix("eval"),), ()),
        ("ASL-3", (Phrase(("asl", "3")),), ()),
        ("Café", (Phrase(("cafe",)),), ()),
        ("refuse NEAR/5 harmful", (Near("refuse", "harmful", 5),), ()),
        ("refuse NEAR harmful", (Near("refuse", "harmful", DEFAULT_NEAR),), ()),
        (
            "a refuse NEAR/2 harmful b",
            (Phrase(("a",)), Near("refuse", "harmful", 2), Phrase(("b",))),
            (),
        ),
        ("circuits -neuron", (Phrase(("circuits",)),), (Phrase(("neuron",)),)),
        ('circuits -"red team"', (Phrase(("circuits",)),), (Phrase(("red", "team")),)),
        ("risk AND assessment", (Phrase(("risk",)), Phrase(("assessment",))), ()),
        ("well-known", (Phrase(("well", "known")),), ()),
        ('"unclosed phrase', (Phrase(("unclosed", "phrase")),), ()),
        ("", (), ()),
        ("   ", (), ()),
        ("— …", (), ()),
    ],
)
def test_parse(query: str, must: tuple[object, ...], must_not: tuple[object, ...]) -> None:
    assert parse_query(query) == ParsedQuery(must, must_not)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("refusal OR refuse", "OR is not an operator"),
        ("(refusal)", "Parentheses"),
        ("ev*", "at least 3 letters"),
        ("NEAR/5 harmful", "a word on each side"),
        ("refuse NEAR/5", "a word on each side"),
        ('"refuse it" NEAR/5 harmful', "two plain words"),
        ("refuse NEAR/5 harm*", "two plain words"),
        ("refuse NEAR/99 harmful", "too wide"),
        ("ASL-3 NEAR/2 harmful", "single words"),
        ("-neuron", "at least one word"),
        ('""', None),
        ('"—"', "no letters or digits"),
        (" ".join(f"w{i}" for i in range(13)), "Too many terms"),
    ],
)
def test_parse_errors(query: str, message: str | None) -> None:
    if message is None:
        assert parse_query(query).empty
        return
    with pytest.raises(QuerySyntaxError, match=message):
        parse_query(query)


def test_describe_says_how_the_query_was_read() -> None:
    text = parse_query('"sparse autoencoder" eval* refuse NEAR/3 harm -benchmark').describe()
    assert text == (
        "all of: \"sparse autoencoder\"; eval* (any word starting with 'eval'); "
        "refuse within 3 words of harm (either order); none of: benchmark"
    )
    assert parse_query("").describe().startswith("no query")


def test_words_fold_like_the_index() -> None:
    assert fold("Naïve CAFÉ") == "naive cafe"
    assert [w for w, _, _ in words("The ﬁnal ASL-3 model_card")] == [
        "the",
        "final",
        "asl",
        "3",
        "model",
        "card",
    ]
    text = "x Résumé y"
    (_, (word, start, end), _) = words(text)
    assert word == "resume" and text[start:end] == "Résumé"
    assert words("a" * 40 + " b") == [("b", 41, 42)]  # over-long words are dropped, as indexed


def test_bare_words() -> None:
    assert parse_query('"a b" ccc* d NEAR/2 e -f').bare_words == ("a", "b", "ccc", "d", "e")
