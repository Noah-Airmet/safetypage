"""The link-only tier: searchable and checkable, never served.

The two documents here are synthetic (written for this suite), because a document that cannot
be redistributed cannot be a test fixture either.
"""

from __future__ import annotations

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from safetypage import policy
from safetypage.corpus import Corpus
from safetypage.licence import Tier
from safetypage.policy import TierViolationError
from safetypage.quote import QuoteTooShortError, Verdict

REPORT = "example:link-only-eval-report"
POST = "example:unlicensed-post"
LIMIT = policy.ACCESS[Tier.LINK_ONLY]


def test_tiers(library: Corpus) -> None:
    report = library.resolve(REPORT).version
    assert (report.tier, report.licence) == (Tier.LINK_ONLY, "all-rights-reserved")
    post = library.resolve(POST).version
    assert (post.tier, post.licence) == (Tier.LINK_ONLY, "unknown")  # no licence fact at all
    assert library.licence_fact(post.version_id) is None


def test_reading_returns_an_excerpt_and_a_link_never_the_text(library: Corpus) -> None:
    units = library.read_units(f"{REPORT}/r1/p1-p3")
    assert len(units) == 3
    for unit in units:
        assert unit.tier is Tier.LINK_ONLY
        assert unit.text is None
        assert unit.excerpt is not None
        assert len(unit.excerpt.split()) <= LIMIT.excerpt_words  # pyright: ignore[reportOperatorIssue]
        assert len(unit.excerpt) <= LIMIT.snippet_chars + 1
        assert unit.excerpt.endswith("…")
    assert units[1].source_url == "https://example.org/reports/meridian-2-refusal.pdf#page=2"
    (block,) = library.read_units(f"{POST}/r1/b3")
    assert block.text is None
    assert block.source_url == "https://example.org/posts/reading-system-cards"


def test_the_record_is_the_same_for_both_tiers(library: Corpus) -> None:
    card = library.document_card(REPORT)
    assert card.tier is Tier.LINK_ONLY
    assert card.unit_count == 3
    assert card.source_url == "https://example.org/reports/meridian-2-refusal"
    assert [o.title for o in library.document_card(POST).outline] == [
        "Notes on reading system cards",
        "What to look for",
    ]


@pytest.mark.parametrize(
    ("quote", "cite", "verdict"),
    [
        (
            "the model does not reliably refuse requests that are split across several turns",
            f"{REPORT}/r1/p1",
            Verdict.EXACT,
        ),
        ("the model does reliably refuse requests", f"{REPORT}/r1/p1", Verdict.NEAR_MISS),
        ("disagreements were resolved by a third grader", f"{REPORT}/r1/p2", Verdict.NORMALIZED),
        ("agreements were resolved by a third grader", f"{REPORT}/r1/p2", Verdict.NEAR_MISS),
        (
            "a third grader who was unable to see the condition label",
            f"{REPORT}/r1/p2",
            Verdict.EXACT,
        ),
        (
            "a third grader who was able to see the condition label",
            f"{REPORT}/r1/p2",
            Verdict.NEAR_MISS,
        ),
        ("The evaluation is non-exhaustive by design", f"{REPORT}/r1/p2", Verdict.NORMALIZED),
        ("The evaluation is exhaustive by design", f"{REPORT}/r1/p2", Verdict.NEAR_MISS),
        ("matched its behaviour in 3.5% fewer cases", f"{REPORT}/r1/p3", Verdict.EXACT),
        ("matched its behaviour in 5% fewer cases", f"{REPORT}/r1/p3", Verdict.NEAR_MISS),
        (
            "The model sandbagged on none of the capability probes",
            f"{REPORT}/r1/p1",
            Verdict.ELSEWHERE,
        ),
        ('the model "showed no evidence of sandbagging"', f"{POST}/r1/b6", Verdict.NORMALIZED),
        ("the model showed evidence of sandbagging", f"{POST}/r1/b6", Verdict.NEAR_MISS),
    ],
)
def test_quotes_are_checked_against_the_private_copy(
    library: Corpus, quote: str, cite: str, verdict: Verdict
) -> None:
    check = library.verify_quote(quote, cite)
    assert check.verdict is verdict
    assert check.tier is Tier.LINK_ONLY


def test_quote_results_carry_excerpts_only(library: Corpus) -> None:
    long_quote = (
        "Each prompt was presented under three conditions: a single turn, a two-turn split, and a "
        "decomposition into three or more turns. Two independent graders labelled every response "
        "as a refusal, a partial compliance, or a full compliance. Inter-grader agreement was "
        "high, and disagreements were resolved by a third grader who was unable to see the "
        "condition label."
    )
    check = library.verify_quote(long_quote, f"{REPORT}/r1/p2")
    assert check.passed  # a long quote still verifies
    (location,) = check.locations
    assert len(location.text.split()) <= 40  # but what comes back is an excerpt
    assert location.text.endswith("…")


def test_policy_refuses_full_text_for_link_only() -> None:
    assert policy.full_text("abc", Tier.OPEN) == "abc"
    with pytest.raises(TierViolationError):
        policy.full_text("abc", Tier.LINK_ONLY)
    assert policy.access_for("link_only").page_images is False
    assert policy.access_for(Tier.LINK_ONLY).source_files is False
    assert policy.access_for(Tier.OPEN).excerpt_words is None


def test_clip() -> None:
    text = " ".join(f"word{i}" for i in range(200))
    assert policy.clip(text, Tier.OPEN) == text
    clipped = policy.clip(text, Tier.LINK_ONLY)
    assert clipped == " ".join(f"word{i}" for i in range(40)) + "…"
    middle = policy.clip(
        text, Tier.LINK_ONLY, around=(text.index("word100"), text.index("word101"))
    )
    assert middle.startswith("…word100 ") and middle.endswith("…")
    assert policy.clip("short text", Tier.LINK_ONLY) == "short text"
    assert len(policy.clip("x" * 5000, Tier.LINK_ONLY)) <= LIMIT.snippet_chars + 1


def _longest_shared_run(result_text: str, private_text: str) -> int:
    """The longest run of consecutive source words that also appears in ``result_text``."""
    words = private_text.split()
    haystack = " ".join(result_text.split())
    best = 0
    i = 0
    while i < len(words):
        n = 0
        while i + n < len(words) and " ".join(words[i : i + n + 1]) in haystack:
            n += 1
        best = max(best, n)
        i += max(n, 1)
    return best


@given(data=st.data())
def test_no_public_call_returns_more_than_an_excerpt_of_a_link_only_document(
    library: Corpus, data: st.DataObject
) -> None:
    """Whatever is asked, nothing the public methods return holds a run of the private text longer
    than the tier's excerpt limit (plus the caller's own quote, which they already had)."""
    doc, anchors = data.draw(
        st.sampled_from(
            [(REPORT, ["p1", "p2", "p3", "p1-p3"]), (POST, ["b1", "b3", "b6", "b1-b6"])]
        )
    )
    anchor = data.draw(st.sampled_from(anchors))
    version = library.resolve(doc).version
    private = library.private_spine_text(version)
    limit = LIMIT.excerpt_words
    assert limit is not None

    units = library.read_units(f"{doc}/r1/{anchor}")
    card = library.document_card(doc)
    served = json.dumps([u.model_dump(mode="json") for u in units]) + card.model_dump_json()
    assert all(u.text is None for u in units)
    for unit in units:
        assert _longest_shared_run(unit.excerpt or "", private) <= limit

    # A quote check: the caller supplies some text; what comes back is clipped all the same.
    start = data.draw(st.integers(0, len(private) - 1))
    length = data.draw(st.integers(1, 900))
    guess = private[start : start + length]
    if data.draw(st.booleans()):
        guess = guess.replace(" the ", " a ", 1)  # a near miss must not leak the correction
    try:
        check = library.verify_quote(guess, f"{doc}/r1/{anchor}")
    except QuoteTooShortError:
        return
    for location in [*check.locations, *check.other_locations]:
        assert len(location.text.split()) <= limit
        assert len(location.text) <= LIMIT.snippet_chars + 1
    diff_words = sum(len(d.source.split()) for s in check.segments for d in s.diff)
    assert diff_words <= limit
    served += check.model_dump_json()
    assert private not in served
