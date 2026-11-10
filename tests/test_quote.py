"""The quote checker's published test table. Every row is a claim about strictness."""

from __future__ import annotations

import re

import pytest

from onthepage.quote import (
    MIN_QUOTE_CHARS,
    PASSING,
    QuoteTooShortError,
    Verdict,
    skeleton,
    split_quote,
    verify_quote,
)

SOURCE = (
    "3. Results\n"
    "We find that the model does not reliably refuse harmful requests. It is un-\n"
    "able to comply in 3.5% of cases, a non-trivial rate, and state-of-the-art\n"
    "ﬁlters were ineffective. “Sandbagging,” the authors write, was not observed—\n"
    "but DeepSeek-\nR1-Zero was ﬁne. Reward hacking was observed in 12 of 1,000 runs.\n"
    "The model does not reliably refuse when requests are split across turns.\n"
)

E, N, X, M = Verdict.EXACT, Verdict.NORMALIZED, Verdict.NOT_FOUND, Verdict.NEAR_MISS


@pytest.mark.parametrize(
    ("quote", "verdict"),
    [
        # --- passes
        ("the model does not reliably refuse harmful requests", E),
        ("We find that the model does not reliably refuse harmful requests.", E),
        ("The Model Does NOT reliably refuse", N),  # case
        ("the model does not  reliably\nrefuse", E),  # whitespace only: still exact
        ("unable to comply in 3.5% of cases", N),  # hyphenated across a line break
        ("DeepSeek-R1-Zero was fine", N),  # line break + ligature
        ('"Sandbagging," the authors write, was not observed', N),  # straight for curly quotes
        ("filters were ineffective", N),  # ligature
        ("a non-trivial rate, and state-of-the-art", E),
        ("a nontrivial rate", N),  # hyphenation style
        ("was not observed - but DeepSeek-R1-Zero", N),  # dash style
        ("was not observed - but DeepSeek", M),  # ends inside "DeepSeek-R1-Zero"
        ("observed in 12 of 1,000 runs", E),
        # --- ellipses and editorial brackets
        ("the model does not reliably refuse ... Reward hacking was observed", E),
        ("the model does not reliably refuse […] Reward hacking was observed", E),
        ("the model does not reliably refuse [...] in 12 of 1,000 runs.", E),
        ("[T]he model does not reliably refuse", N),
        ("the model [Meridian-2] does not reliably refuse", E),
        # --- the word "not", and its relatives: every one of these changes the meaning
        ("the model does reliably refuse harmful requests", M),  # "not" deleted
        ("the model does not not reliably refuse", M),  # a word inserted
        ("able to comply in 3.5% of cases", M),  # starts inside "un-able"
        ("It is able to comply", M),
        ("a trivial rate, and state-of-the-art", M),  # starts inside "non-trivial"
        ("state-of-the-art filters were effective", M),
        ("to comply in 5% of cases", M),  # starts inside "3.5%"
        ("observed in 12 of 1,00", M),  # ends inside "1,000"
        ("hacking was observed in 2 of 1,000 runs", M),  # starts inside "12"
        ("the model does not reliably reuse harmful requests", M),  # one letter
        ("the model reliably does not refuse harmful requests", M),  # word order
        # --- fragments out of order
        ("Reward hacking was observed ... the model does not reliably refuse harmful", M),
        # --- nothing like it
        ("gradient descent converges to a global optimum", X),
        ("the model does not reliably refuse ... gradient descent converges", X),
    ],
)
def test_verdict_table(quote: str, verdict: Verdict) -> None:
    result = verify_quote(quote, SOURCE)
    assert result.verdict is verdict, result
    assert result.passed is (verdict in PASSING)


def test_a_near_miss_reports_the_source_wording_and_a_word_diff() -> None:
    result = verify_quote("the model does reliably refuse harmful requests", SOURCE)
    assert result.verdict is Verdict.NEAR_MISS
    assert not result.passed
    (segment,) = result.segments
    assert segment.span is not None
    assert segment.span.text == "the model does not reliably refuse harmful requests"
    assert [(d.op, d.quote, d.source) for d in segment.diff] == [("insert", "", "not")]

    result = verify_quote("state-of-the-art filters were effective", SOURCE)
    (segment,) = result.segments
    assert segment.verdict is Verdict.NEAR_MISS
    assert segment.similarity is not None
    assert segment.similarity >= 80
    assert [(d.op, d.quote, d.source) for d in segment.diff] == [
        ("replace", "effective", "ineffective")
    ]


def test_a_match_inside_a_word_is_a_near_miss_that_shows_the_whole_word() -> None:
    result = verify_quote("able to comply in 3.5% of cases", SOURCE)
    (segment,) = result.segments
    assert segment.verdict is Verdict.NEAR_MISS
    assert segment.span is not None
    assert segment.span.text.startswith("un-\nable to comply")


def test_spans_are_the_sources_own_characters() -> None:
    result = verify_quote("DEEPSEEK-R1-ZERO WAS FINE", SOURCE)
    (span,) = result.spans
    assert span.text == "DeepSeek-\nR1-Zero was ﬁne"
    assert SOURCE[span.start : span.end] == span.text


def test_scope_distinguishes_here_from_elsewhere() -> None:
    first_line_end = SOURCE.index("\n", SOURCE.index("We find"))
    here = (0, first_line_end)
    assert verify_quote("the model does not reliably refuse", SOURCE, scope=here).verdict is E
    elsewhere = verify_quote("Reward hacking was observed", SOURCE, scope=here)
    assert elsewhere.verdict is Verdict.ELSEWHERE
    assert not elsewhere.passed
    assert not elsewhere.in_scope
    assert elsewhere.spans[0].text == "Reward hacking was observed"
    # every fragment must be in scope, not just the first
    split = verify_quote(
        "the model does not reliably refuse ... Reward hacking", SOURCE, scope=here
    )
    assert split.verdict is Verdict.ELSEWHERE


def test_scope_must_lie_inside_the_source() -> None:
    with pytest.raises(ValueError, match="outside the source"):
        verify_quote("the model does not reliably refuse", SOURCE, scope=(0, len(SOURCE) + 1))


def test_ambiguity_is_reported_not_hidden() -> None:
    result = verify_quote("does not reliably refuse", SOURCE)
    assert result.passed
    assert result.ambiguous
    assert len(result.other_spans) == 1
    assert result.other_spans[0].start > result.spans[0].start
    # an exact occurrence is preferred over an earlier one that needs normalising
    twice = "He said the Model Refuses. Later: the model refuses."
    result = verify_quote("the model refuses", twice)
    assert result.verdict is Verdict.EXACT
    assert result.spans[0].start == twice.index("the model refuses")
    assert [s.text for s in result.other_spans] == ["the Model Refuses"]
    assert not verify_quote("Reward hacking was observed", SOURCE).ambiguous


def test_fragments_must_appear_in_order_and_not_overlap() -> None:
    assert verify_quote("refuse harmful requests ... refuse when requests", SOURCE).passed
    result = verify_quote("split across turns ... We find that the model", SOURCE)
    assert result.verdict is Verdict.NEAR_MISS
    assert "order" in result.reason


def test_split_quote() -> None:
    assert split_quote(
        '"In order to [really] save … costs," [...] he said. . . finally....done'
    ) == [
        "In order to",
        "save",
        "costs",
        "he said",
        "finally",
        "done",
    ]
    assert split_quote("[T]he model") == ["T]he model"]
    assert split_quote("… ... [...]") == []


@pytest.mark.parametrize("quote", ["", "   ", "the", "a b c d", "…", "sandbag", "(1) [2]"])
def test_too_short_to_check(quote: str) -> None:
    with pytest.raises(QuoteTooShortError):
        verify_quote(quote, SOURCE)
    assert len(skeleton(quote)) < MIN_QUOTE_CHARS


def test_math_italic_and_full_width_text_layers() -> None:
    # PDF text layers set maths in Mathematical Alphanumeric Symbols; NFKC folds them.
    source = "the policy 𝜋𝜃 maximises 𝐽𝐺𝑅𝑃𝑂 over ｆｕｌｌ－ｗｉｄｔｈ text and naïve Ｂａｙｅｓ"
    assert verify_quote("maximises JGRPO over full-width text", source).verdict is N
    assert verify_quote("naive Bayes classifier", source + " classifier").verdict is N


def test_skeleton_maps_back_to_source_offsets() -> None:
    sk = skeleton("Co-\nop: ﬁx “it”")
    assert sk.text == "coopfixit"
    assert [sk.source[i] for i in sk.offsets] == ["C", "o", "o", "p", "ﬁ", "ﬁ", "x", "i", "t"]
    assert sk.source_span(4, 7) == (8, 10)
    assert sk.index_at(8) == 4


# ---------------------------------------------------------------------------------------
# Regression: the checker this replaces
# ---------------------------------------------------------------------------------------


def _old_quote_found(quote: str, page_text: str, gap: int = 3) -> bool:
    """The rule of the checker this library replaces, restated: every quoted word must appear in
    order, with up to ``gap`` stray source words allowed between neighbours. The tolerance was
    there to forgive margin notes wedged into sentences by PDF text layers."""
    words = re.findall(r"[a-z0-9]+", quote.lower())
    page = re.findall(r"[a-z0-9]+", page_text.lower())
    for start in (i for i, w in enumerate(page) if w == words[0]):
        j, ok = start, True
        for word in words[1:]:
            nxt = next(
                (k for k in range(j + 1, min(j + 2 + gap, len(page))) if page[k] == word), None
            )
            if nxt is None:
                ok = False
                break
            j = nxt
        if ok:
            return True
    return False


@pytest.mark.parametrize(
    ("source", "quote"),
    [
        ("the model does not reliably refuse", "the model does reliably refuse"),
        (
            "smaller models do not require enormous computational power",
            "smaller models do require enormous computational power",
        ),
        (
            "we found no evidence of deliberate sandbagging on the evaluations",
            "we found evidence of deliberate sandbagging on the evaluations",
        ),
        (
            "the safeguards were never bypassed during testing",
            "the safeguards were bypassed during testing",
        ),
    ],
)
def test_regression_a_quote_with_not_deleted_fails(source: str, quote: str) -> None:
    """A gap-tolerant matcher accepts a quotation with the negation removed. This one must not."""
    assert _old_quote_found(quote, source), (
        "the old rule is expected to pass this (that is the bug)"
    )
    result = verify_quote(quote, source)
    assert result.verdict is Verdict.NEAR_MISS
    assert not result.passed
    dropped = [d.source for s in result.segments for d in s.diff if d.op == "insert"]
    assert dropped
    assert dropped[0] in {"not", "no", "never"}
