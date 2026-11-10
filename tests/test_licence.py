from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from safetypage.licence import (
    LicenceFact,
    Tier,
    decide_tier,
    is_open_licence,
    licence_from_url,
    normalise_licence,
)


def fact(licence: str, **changes: str) -> LicenceFact:
    fields = {
        "evidence_kind": "licence_link",
        "evidence_url": "https://arxiv.org/abs/2305.15324v2",
        "evidence_quote": "http://creativecommons.org/licenses/by/4.0/",
        "observed_at": "2026-11-10T01:55:00Z",
        "producer": "test",
    }
    fields.update(changes)
    return LicenceFact(licence=licence, **fields)  # pyright: ignore[reportArgumentType]


OPEN = [
    "CC-BY-4.0",
    "CC-BY-3.0",
    "CC-BY-2.0",
    "CC-BY-SA-4.0",
    "CC-BY-SA-3.0",
    "CC0-1.0",
    "CC-PDM-1.0",
    "public-domain",
    "public-domain-us-gov",
    "OGL-UK-3.0",
    "OGL-UK-2.0",
]
LINK_ONLY = [
    "CC-BY-NC-4.0",
    "CC-BY-NC-SA-4.0",
    "CC-BY-NC-ND-4.0",
    "CC-BY-ND-4.0",
    "arXiv-nonexclusive-1.0",
    "all-rights-reserved",
    "unknown",
]


@pytest.mark.parametrize("licence", OPEN)
def test_open_licences_with_evidence_are_open(licence: str) -> None:
    decision = decide_tier(fact(licence))
    assert decision.tier is Tier.OPEN
    assert decision.licence == licence


@pytest.mark.parametrize("licence", LINK_ONLY)
def test_everything_else_is_link_only(licence: str) -> None:
    decision = decide_tier(fact(licence))
    assert decision.tier is Tier.LINK_ONLY
    assert decision.licence == licence
    assert not is_open_licence(licence)


def test_no_fact_is_link_only() -> None:
    decision = decide_tier(None)
    assert (decision.tier, decision.licence) == (Tier.LINK_ONLY, "unknown")


@pytest.mark.parametrize("missing", ["evidence_url", "evidence_quote", "observed_at", "producer"])
def test_an_open_licence_without_evidence_is_link_only(missing: str) -> None:
    decision = decide_tier(fact("CC-BY-4.0", **{missing: "  "}))
    assert decision.tier is Tier.LINK_ONLY
    assert missing in decision.reason


@pytest.mark.parametrize("sloppy", ["cc-by-4.0", "CC BY 4.0", "CC-BY", "MIT", "open", "CC-BY-4.0 "])
def test_a_non_canonical_licence_string_is_link_only(sloppy: str) -> None:
    # decide_tier does not guess: ingestion must normalise first, and unknown stays unknown.
    assert decide_tier(fact(sloppy)).tier is Tier.LINK_ONLY


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("cc by 4.0", "CC-BY-4.0"),
        ("CC_BY_SA_4.0", "CC-BY-SA-4.0"),
        ("cc0-1.0", "CC0-1.0"),
        ("ALL-RIGHTS-RESERVED", "all-rights-reserved"),
        ("arxiv-nonexclusive-1.0", "arXiv-nonexclusive-1.0"),
        ("ogl-uk-3.0", "OGL-UK-3.0"),
        ("MIT", "unknown"),
        ("CC-BY", "unknown"),
        ("CC-BY-XX-4.0", "unknown"),
        ("", "unknown"),
    ],
)
def test_normalise_licence(raw: str, canonical: str) -> None:
    assert normalise_licence(raw) == canonical


@pytest.mark.parametrize(
    ("url", "licence"),
    [
        ("http://creativecommons.org/licenses/by/4.0/", "CC-BY-4.0"),
        ("https://creativecommons.org/licenses/by-sa/4.0/", "CC-BY-SA-4.0"),
        ("https://creativecommons.org/licenses/by-nc-sa/4.0/", "CC-BY-NC-SA-4.0"),
        ("https://creativecommons.org/licenses/by-nc-nd/4.0/", "CC-BY-NC-ND-4.0"),
        ("https://creativecommons.org/licenses/by/4.0/deed.en", "unknown"),
        ("http://creativecommons.org/publicdomain/zero/1.0/", "CC0-1.0"),
        ("https://creativecommons.org/publicdomain/mark/1.0/", "CC-PDM-1.0"),
        ("http://arxiv.org/licenses/nonexclusive-distrib/1.0/", "arXiv-nonexclusive-1.0"),
        (
            "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
            "OGL-UK-3.0",
        ),
        ("https://example.org/licence", "unknown"),
        ("https://evil.example/creativecommons.org/licenses/by/4.0/", "unknown"),
    ],
)
def test_licence_from_url(url: str, licence: str) -> None:
    assert licence_from_url(url) == licence


def test_the_arxiv_licence_menu_maps_to_the_right_tiers() -> None:
    menu = {
        "http://creativecommons.org/licenses/by/4.0/": Tier.OPEN,
        "http://creativecommons.org/licenses/by-sa/4.0/": Tier.OPEN,
        "http://creativecommons.org/publicdomain/zero/1.0/": Tier.OPEN,
        "http://creativecommons.org/licenses/by-nc-sa/4.0/": Tier.LINK_ONLY,
        "http://creativecommons.org/licenses/by-nc-nd/4.0/": Tier.LINK_ONLY,
        "http://arxiv.org/licenses/nonexclusive-distrib/1.0/": Tier.LINK_ONLY,
    }
    for url, tier in menu.items():
        assert decide_tier(fact(licence_from_url(url), evidence_quote=url)).tier is tier


@given(st.text(max_size=40))
def test_open_requires_a_known_open_licence(licence: str) -> None:
    """Fail closed: whatever string arrives, open only ever comes from the allowlist."""
    decision = decide_tier(fact(licence))
    if decision.tier is Tier.OPEN:
        assert licence in OPEN or is_open_licence(licence)
        assert normalise_licence(licence) == licence
