"""Licence facts: the inventory's finding, checked by machine where it can be."""

from __future__ import annotations

from typing import Any

from safetypage.ingest.items import Item
from safetypage.ingest.licence import licence_for
from safetypage.licence import Tier, decide_tier

NOW = "2026-11-10T00:00:00Z"


def item(**overrides: Any) -> Item:
    fields: dict[str, Any] = {
        "key": "https://example.org/doc",
        "shelf": "evaluators",
        "doc_id": "example:doc",
        "adapter": "web",
        "url": "https://example.org/doc",
        "source_url": "https://example.org/doc",
        "kind": "article",
        "title": "A document",
        "authors": [],
        "org": None,
        "published": None,
        "licence": "CC-BY-4.0",
        "licence_evidence": "Footer says CC BY 4.0.",
    }
    fields.update(overrides)
    return Item(**fields)


def tier(fact: Any) -> Tier:
    return decide_tier(fact.fact()).tier


def test_arxiv_licence_comes_from_the_metadata_deed() -> None:
    paper = item(
        adapter="arxiv",
        url="2305.15324",
        doc_id="arxiv:2305.15324",
        licence="CC-BY-4.0",
        licence_evidence="arXiv metadata licence field = http://creativecommons.org/licenses/by/4.0/ (OAI-PMH)",
    )
    fact = licence_for(paper, observed_at=NOW)
    assert (fact.licence, fact.evidence_kind) == ("CC-BY-4.0", "licence_link")
    assert "oai:arXiv.org:2305.15324" in fact.evidence_url
    assert tier(fact) is Tier.OPEN


def test_arxiv_default_licence_is_link_only() -> None:
    paper = item(
        adapter="arxiv",
        url="1210.4915",
        licence="arxiv-default",
        licence_evidence="licence field = http://arxiv.org/licenses/nonexclusive-distrib/1.0/ (OAI)",
    )
    fact = licence_for(paper, observed_at=NOW)
    assert fact.licence == "arXiv-nonexclusive-1.0"
    assert tier(fact) is Tier.LINK_ONLY


def test_arxiv_disagreement_fails_closed() -> None:
    paper = item(
        adapter="arxiv",
        url="1",
        licence="CC-BY-4.0",
        licence_evidence="licence field = http://creativecommons.org/licenses/by-nc-nd/4.0/",
    )
    assert tier(licence_for(paper, observed_at=NOW)) is Tier.LINK_ONLY


def test_acl_year_rule() -> None:
    new = licence_for(item(doc_id="acl:2024.acl-long.787"), observed_at=NOW)
    old = licence_for(item(doc_id="acl:W15-1234"), observed_at=NOW)
    assert (new.licence, new.evidence_kind) == ("CC-BY-4.0", "publisher_rule")
    assert old.licence == "CC-BY-NC-SA-3.0"
    assert tier(old) is Tier.LINK_ONLY


def test_the_page_deed_wins_over_the_inventory() -> None:
    page = (
        "<p>Diagrams and text are licensed under Creative Commons Attribution "
        '<a href="https://creativecommons.org/licenses/by/2.0/">CC-BY 2.0</a></p>'
    )
    fact = licence_for(item(), observed_at=NOW, content=page, content_sha256="a" * 64)
    assert (fact.licence, fact.evidence_kind) == ("CC-BY-2.0", "page_statement")
    assert "licensed under Creative Commons Attribution" in fact.evidence_quote
    assert "<a" not in fact.evidence_quote
    assert fact.evidence_sha256 == "a" * 64


def test_ogl_statement_is_found() -> None:
    page = "All content is available under the Open Government Licence v3.0, except..."
    fact = licence_for(item(licence="LicenseRef-OGL-UK-3.0"), observed_at=NOW, content=page)
    assert (fact.licence, fact.evidence_kind) == ("OGL-UK-3.0", "page_statement")
    assert tier(fact) is Tier.OPEN


def test_an_open_claim_not_found_on_the_page_keeps_the_inventory_evidence() -> None:
    fact = licence_for(item(), observed_at=NOW, content="<p>No statement here.</p>")
    assert fact.evidence_kind == "manual"
    assert "not found in the fetched file" in fact.evidence_quote
    assert fact.producer.startswith("inventory:")


def test_us_government_works_by_statute() -> None:
    fact = licence_for(item(licence="LicenseRef-US-Gov-PD"), observed_at=NOW)
    assert (fact.licence, fact.evidence_kind) == ("public-domain-us-gov", "statute")
    assert tier(fact) is Tier.OPEN


def test_unrecognised_inventory_licence_is_unknown() -> None:
    fact = licence_for(item(licence="LicenseRef-Llama-Community-License"), observed_at=NOW)
    assert fact.licence == "unknown"
    assert "Llama" in fact.evidence_quote
    assert tier(fact) is Tier.LINK_ONLY


def _post(**overrides: Any) -> Item:
    base: dict[str, Any] = {
        "adapter": "lw",
        "doc_id": "lw:abc",
        "url": "abc",
        "licence": "CC-BY-4.0",
        "extra": {"crosspost": {"eaf_post_id": "xyz", "hosted_on_lw": False}},
    }
    base.update(overrides)
    return item(**base)


def test_ea_forum_crosspost_after_the_rule_is_cc_by() -> None:
    record = {"postedAt": "2023-01-16T00:00:00Z", "url": None}
    fact = licence_for(_post(), observed_at=NOW, post=record)
    assert (fact.licence, fact.evidence_kind) == ("CC-BY-4.0", "publisher_rule")


def test_forum_posts_otherwise_link_only() -> None:
    before = licence_for(_post(), observed_at=NOW, post={"postedAt": "2022-06-01", "url": None})
    linkpost = licence_for(
        _post(), observed_at=NOW, post={"postedAt": "2024-01-01", "url": "https://x"}
    )
    plain = licence_for(_post(licence="unknown", extra={}), observed_at=NOW, post={})
    assert {before.licence, linkpost.licence, plain.licence} == {"unknown"}
