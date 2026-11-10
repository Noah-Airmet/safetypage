"""End to end on real documents: model, anchors, citations and the quote checker together.

The fixture corpus is two CC BY arXiv papers (one in two versions), a Distill article, NIST AI
100-1, and two synthetic documents that stand in for the link-only tier.
"""

from __future__ import annotations

import pytest

from safetypage.corpus import Corpus, NotFoundError
from safetypage.ids import Anchor, parse_citation
from safetypage.licence import Tier
from safetypage.quote import Verdict

PAPER = "arxiv:2305.15324"


def test_the_corpus_passes_its_own_gates(library: Corpus) -> None:
    assert library.validate() == []
    counts = library.counts()
    assert counts["documents"] == 6
    assert counts["versions"] == 7
    assert counts["by_tier"]["open"]["versions"] == 5
    assert counts["by_tier"]["link_only"]["versions"] == 2


def test_documents_and_versions(library: Corpus) -> None:
    doc = library.document(PAPER)
    assert doc is not None
    assert doc.title == "Model evaluation for extreme risks"
    assert doc.authors[0] == "Toby Shevlane"
    assert [v.label for v in library.versions(PAPER)] == ["v1", "v2"]
    assert library.resolve(PAPER).version.label == "v2"  # no version named: the latest
    assert library.resolve(f"{PAPER}/v1").version.label == "v1"
    assert {v.tier for v in library.versions(PAPER)} == {Tier.OPEN}


def test_every_open_version_carries_its_evidence(library: Corpus) -> None:
    for version in library.all_versions():
        fact = library.licence_fact(version.version_id)
        if version.tier is Tier.OPEN:
            assert fact is not None
            assert fact.evidence_url.startswith("https://")
            assert fact.evidence_quote
            assert fact.observed_at
    v2 = library.resolve(f"{PAPER}/v2").version
    fact = library.licence_fact(v2.version_id)
    assert fact is not None
    assert (fact.licence, fact.evidence_kind) == ("CC-BY-4.0", "licence_link")
    assert fact.evidence_url == "https://arxiv.org/abs/2305.15324v2"
    nist = library.licence_fact(library.resolve("nist:ai-100-1").version.version_id)
    assert nist is not None
    assert (nist.licence, nist.evidence_kind) == ("public-domain-us-gov", "statute")


# ------------------------------------------------------------------ quotes on a real PDF


@pytest.mark.parametrize(
    ("quote", "cite", "verdict", "found_at"),
    [
        # verbatim on the cited page
        (
            "model evaluation is one of the main tools we have for AI risk assessment",
            f"{PAPER}/v2/p6",
            Verdict.EXACT,
            f"{PAPER}/v2/p6",
        ),
        # a word hyphenated across a line break in the PDF ("capabil-\nities")
        (
            "AI systems with dangerous capabilities",
            f"{PAPER}/v2/p5",
            Verdict.NORMALIZED,
            f"{PAPER}/v2/p5",
        ),
        # a compound hyphenated at a line end ("hard-to-\nforecast")
        (
            "tended to display new and hard-to-forecast capabilities",
            f"{PAPER}/v2/p1",
            Verdict.NORMALIZED,
            f"{PAPER}/v2/p1",
        ),
        # right words, wrong page: the citation fails and says where the words are
        (
            "model evaluation is one of the main tools we have for AI risk assessment",
            f"{PAPER}/v2/p3",
            Verdict.ELSEWHERE,
            f"{PAPER}/v2/p6",
        ),
        # the page says "is not the only tool": deleting "not" must fail
        (
            "Model evaluation is the only tool available for AI risk assessment",
            f"{PAPER}/v2/p6",
            Verdict.NEAR_MISS,
            f"{PAPER}/v2/p6",
        ),
        # v2 fixed a typo that v1 has ("hardwares"): the quote is v2's, not v1's
        (
            "discover vulnerabilities in systems (hardware, software, data)",
            f"{PAPER}/v2/p5",
            Verdict.EXACT,
            f"{PAPER}/v2/p5",
        ),
        (
            "discover vulnerabilities in systems (hardware, software, data)",
            f"{PAPER}/v1/p5",
            Verdict.NEAR_MISS,
            f"{PAPER}/v1/p5",
        ),
        # a range of pages is a scope like any other
        (
            "model evaluation is one of the main tools we have for AI risk assessment",
            f"{PAPER}/v2/p5-p7",
            Verdict.EXACT,
            f"{PAPER}/v2/p6",
        ),
        (
            "an entirely different sentence about protein folding benchmarks",
            f"{PAPER}/v2/p6",
            Verdict.NOT_FOUND,
            None,
        ),
    ],
)
def test_quotes_against_the_paper(
    library: Corpus, quote: str, cite: str, verdict: Verdict, found_at: str | None
) -> None:
    check = library.verify_quote(quote, cite)
    assert check.verdict is verdict
    assert check.passed is (verdict in {Verdict.EXACT, Verdict.NORMALIZED})
    assert check.cite == cite
    assert check.tier is Tier.OPEN
    assert check.fidelity == "text_layer"
    if found_at is None:
        assert check.locations == []
    else:
        assert check.locations[0].cite == found_at
        assert (
            check.locations[0].url == f"https://safetypage.test/d/{found_at.replace(':', '/', 1)}"
        )


def test_the_not_deleted_near_miss_shows_the_missing_word(library: Corpus) -> None:
    check = library.verify_quote(
        "Model evaluation is the only tool available for AI risk assessment", f"{PAPER}/v2/p6"
    )
    (segment,) = check.segments
    assert [(d.op, d.source) for d in segment.diff] == [("insert", "not")]
    assert segment.location is not None
    assert "is\nnot the only tool" in segment.location.text


def test_a_quote_across_a_page_break_needs_an_ellipsis(library: Corpus) -> None:
    """A sentence runs from p12 to p13, with the page number and running head between. The text
    of record is the page's text layer as it is, so the honest quote marks the gap."""
    joined = "researchers demonstrated that chain-of-thought prompting"
    assert library.verify_quote(joined, f"{PAPER}/v2/p12-p13").verdict is Verdict.NEAR_MISS
    check = library.verify_quote(
        "researchers ... demonstrated that chain-of-thought prompting", f"{PAPER}/v2/p12-p13"
    )
    assert check.passed
    assert [loc.cite for loc in check.locations] == [f"{PAPER}/v2/p12", f"{PAPER}/v2/p13"]


def test_locations_point_into_the_spine(library: Corpus) -> None:
    check = library.verify_quote("AI systems with dangerous capabilities", f"{PAPER}/v2/p5")
    location = check.locations[0]
    version = library.resolve(f"{PAPER}/v2").version
    spine = library.private_spine_text(version)
    assert spine[location.spine_start : location.spine_end] == location.text
    assert location.text == "AI systems with dangerous capabil-\nities"
    page = library.pages(version.version_id)[4]
    assert page.spine_start <= location.spine_start < location.spine_end <= page.spine_end


def test_whole_document_search_without_an_anchor(library: Corpus) -> None:
    check = library.verify_quote("Science zoomed in.", "distill:zoom-in")
    assert check.verdict is Verdict.EXACT
    assert check.cite is None
    assert check.ambiguous  # the article says it four times
    assert len(check.other_locations) == 3
    assert check.locations[0].cite == "distill:zoom-in/r1/b2"


# ------------------------------------------------------------------ blocks


def test_unpaged_documents_are_cited_by_block(library: Corpus) -> None:
    check = library.verify_quote(
        "cellular biology isn't just more careful zoology", "distill:zoom-in/r1/b3"
    )
    assert check.verdict is Verdict.NORMALIZED  # the page has a typographic apostrophe
    assert check.fidelity == "html"
    wrong = library.verify_quote(
        "cellular biology isn't just more careful zoology", "distill:zoom-in/r1/b4"
    )
    assert wrong.verdict is Verdict.ELSEWHERE
    assert wrong.locations[0].cite == "distill:zoom-in/r1/b3"
    with pytest.raises(NotFoundError, match="cited by block"):
        library.resolve("distill:zoom-in/r1/p1")


def test_blocks_overlay_pages_on_a_paged_document(library: Corpus) -> None:
    version = library.resolve(f"{PAPER}/v2").version
    blocks = library.blocks(version.version_id)
    by_source = {b.source_id: b for b in blocks if b.source_id}
    first = by_source["S1.p1"]  # arXiv's own paragraph id, kept as an alias
    assert first.kind == "paragraph"
    assert first.section[-1] == "1 Introduction"
    assert (first.page_start, first.page_end) == (1, 1)
    placed = [b for b in blocks if b.spine_start is not None]
    assert len(placed) / len(blocks) > 0.85
    # a block is a narrower scope than its page
    quote = (
        "general-purpose AI systems have tended to display new and hard-to-forecast capabilities"
    )
    assert library.verify_quote(quote, f"{PAPER}/v2/b{first.anchor}").passed
    other = by_source["S1.p3"]
    assert library.verify_quote(quote, f"{PAPER}/v2/b{other.anchor}").verdict is Verdict.ELSEWHERE
    # still located by page, because pages are this version's citation unit
    assert library.verify_quote(quote, f"{PAPER}/v2/b{first.anchor}").locations[0].anchor == "p1"


def test_units_view_is_the_citation_unit(library: Corpus) -> None:
    rows = library.conn.execute(
        "SELECT cite, kind, tier FROM units WHERE doc_id = ? AND version = 'v2' ORDER BY seq",
        (PAPER,),
    ).fetchall()
    assert len(rows) == 20  # pages, not the overlay blocks
    assert rows[5]["cite"] == f"{PAPER}/v2/p6"
    assert {r["kind"] for r in rows} == {"page"}
    distill = library.conn.execute(
        "SELECT cite FROM units WHERE doc_id = 'distill:zoom-in' ORDER BY seq LIMIT 2"
    ).fetchall()
    assert [r["cite"] for r in distill] == ["distill:zoom-in/r1/b1", "distill:zoom-in/r1/b2"]
    for row in library.conn.execute("SELECT cite FROM units"):
        parse_citation(row["cite"])  # every unit id is a valid cite string


# ------------------------------------------------------------------ reading


def test_reading_an_open_document_returns_the_page(library: Corpus) -> None:
    (unit,) = library.read_units(f"{PAPER}/v2/p6")
    assert unit.tier is Tier.OPEN
    assert unit.text is not None
    assert unit.text.startswith(
        "Model evaluation for extreme risks\n3. Model evaluation as critical"
    )
    assert unit.excerpt is None
    assert unit.anchor_label == "p. 6"
    assert unit.url == "https://safetypage.test/d/arxiv/2305.15324/v2/p6"
    assert unit.source_url == "https://arxiv.org/pdf/2305.15324v2#page=6"
    units = library.read_units(f"{PAPER}/v2/p6-p8")
    assert [u.anchor for u in units] == ["p6", "p7", "p8"]
    blocks = library.read_units("distill:zoom-in/r1/b12-b14")
    assert [u.anchor for u in blocks] == ["b12", "b13", "b14"]
    assert blocks[0].text == "Three Speculative Claims"


def test_printed_page_labels_are_shown_but_never_used_in_anchors(library: Corpus) -> None:
    nist = library.resolve("nist:ai-100-1").version
    assert library.anchor_label(nist, Anchor.page(3)) == "p. i (PDF p. 3)"
    assert library.anchor_label(nist, Anchor.page(9)) == "p. 4 (PDF p. 9)"
    (unit,) = library.read_units("nist:ai-100-1/r1/p9")
    assert unit.text is not None
    assert "Framing Risk" in unit.text
    assert unit.source_url.endswith("NIST.AI.100-1.pdf#page=9")  # the physical index


def test_document_card(library: Corpus) -> None:
    card = library.document_card(PAPER)
    assert card.version == "v2"
    assert [(v.version, v.latest) for v in card.versions] == [("v1", False), ("v2", True)]
    assert card.unit_count == 20
    assert card.anchor_kind == "page"
    assert card.url == "https://safetypage.test/d/arxiv/2305.15324"
    assert card.outline[0].title == "Introduction"
    assert card.outline[0].cite == f"{PAPER}/v2/p1"
    assert library.document_card(f"{PAPER}/v1").version == "v1"
    distill = library.document_card("distill:zoom-in")
    assert distill.anchor_kind == "block"
    assert distill.outline[0].title == "Three Speculative Claims"
    assert distill.outline[0].anchor == "b12"


# ------------------------------------------------------------------ errors that teach


@pytest.mark.parametrize(
    ("ref", "message"),
    [
        ("arxiv:2305.15342/v2/p6", "Did you mean arxiv:2305.15324?"),
        ("arxiv:2305.15324/v9/p6", "Versions: v1, v2"),
        ("arxiv:2305.15324/v2/p21", "has 20 pages"),
        ("arxiv:2305.15324/v2/p19-p25", "has 20 pages"),
        ("arxiv:2305.15324/v2/b9999", "there is no b9999"),
        ("nist:ai-100-1/r1/b1", "no blocks"),
        ("nope:missing", "Unknown document"),
    ],
)
def test_unresolvable_refs_say_what_exists(library: Corpus, ref: str, message: str) -> None:
    with pytest.raises(NotFoundError) as excinfo:
        library.resolve(ref)
    assert message in str(excinfo.value)


def test_an_unplaced_overlay_block_cannot_be_cited(library: Corpus) -> None:
    version = library.resolve(f"{PAPER}/v2").version
    unplaced = next(b for b in library.blocks(version.version_id) if b.spine_start is None)
    with pytest.raises(NotFoundError, match="cite the page instead"):
        library.resolve(f"{PAPER}/v2/b{unplaced.anchor}")


def test_layout_is_only_returned_when_asked_and_only_for_open_pages(library: Corpus) -> None:
    plain = library.read_units(f"{PAPER}/v2/p6")[0]
    assert plain.words is None and plain.width is None
    assert plain.kind == "page" and plain.spine_start is not None

    page = library.read_units(f"{PAPER}/v2/p6", layout=True)[0]
    assert page.text is not None and page.words and page.width and page.height
    start, end, x0, y0, x1, y1 = page.words[0]
    assert page.text[start:end] == "Model"
    assert 0 <= x0 < x1 <= page.width and 0 <= y0 < y1 <= page.height

    closed = library.read_units("example:link-only-eval-report/r1/p1", layout=True)[0]
    assert closed.text is None and closed.words is None and closed.width is None


def test_the_document_card_carries_the_licence_evidence(library: Corpus) -> None:
    evidence = library.document_card(PAPER).licence_evidence
    assert evidence is not None and evidence.kind == "licence_link"
    assert evidence.url == "https://arxiv.org/abs/2305.15324v2"
    assert library.document_card("example:unlicensed-post").licence_evidence is None
