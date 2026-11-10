from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from safetypage import policy
from safetypage.licence import Tier
from safetypage.search.grammar import parse_query
from safetypage.search.highlight import SNIPPET_CHARS, find_spans, snippet

PAGE = (
    "Model evaluation for extreme risks\n\nModel evaluation is not the only tool available "
    "for AI risk assessment – more theoretical approaches are also available. " * 6
)


def test_spans_are_the_matched_words() -> None:
    text = "We find that Sparse Autoencoders find sparse, interpretable features."
    spans = find_spans(text, parse_query('"sparse auto*" features'))
    assert [text[s:e] for s, e in spans] == ["Sparse Autoencoders", "features"]
    assert find_spans(text, parse_query("interpret*")) == [(46, 59)]
    assert find_spans(text, None) == []


def test_snippet_open_keeps_the_match_in_view() -> None:
    text = (
        "filler words here. " * 40 + "the only tool available for AI risk assessment" + " end." * 50
    )
    out, spans = snippet(text, Tier.OPEN, parse_query('"risk assessment"'))
    assert len(out) <= SNIPPET_CHARS
    assert out.startswith("…") and out.endswith("…")
    assert [out[s:e] for s, e in spans] == ["risk assessment"]


def test_snippet_link_only_goes_through_policy() -> None:
    out, spans = snippet(PAGE, Tier.LINK_ONLY, parse_query("theoretical"))
    access = policy.access_for(Tier.LINK_ONLY)
    assert len(out) <= access.snippet_chars
    assert len(out.split()) <= (access.excerpt_words or 0) + 1
    assert spans and all(out[s:e] == "theoretical" for s, e in spans)


def test_snippet_without_matches_is_the_opening() -> None:
    out, spans = snippet(PAGE, Tier.OPEN, None)
    assert out.startswith("Model evaluation for extreme risks Model")
    assert spans == []


@given(st.text(min_size=0, max_size=2000), st.sampled_from([Tier.OPEN, Tier.LINK_ONLY]))
def test_snippet_stays_inside_the_tier_limit(text: str, tier: Tier) -> None:
    out, spans = snippet(text, tier, parse_query("risk"))
    assert len(out) <= min(SNIPPET_CHARS, policy.access_for(tier).snippet_chars)
    assert all(0 <= s < e <= len(out) for s, e in spans)
