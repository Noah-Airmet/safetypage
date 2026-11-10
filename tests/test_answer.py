from __future__ import annotations

from onthepage.answer import parse_answer
from onthepage.corpus import Corpus
from onthepage.quote import Verdict

BASE = "https://onthepage.test"
PAPER = "arxiv:2305.15324"

ANSWER = f"""\
Shevlane et al. argue that "model evaluation is one of the main tools we have for AI risk
assessment" ([p. 6]({BASE}/d/arxiv/2305.15324/v2/p6)), and that frontier systems show
“new and hard-to-forecast capabilities” ({PAPER}/v2/p1).

They also claim that "Model evaluation is the only tool available for AI risk assessment"
({PAPER}/v2/p6), and that models can "discover vulnerabilities in systems" ({PAPER}/v2/p3).

> Many important transition points in the history of science have been moments when
> science “zoomed in.”

distill:zoom-in/r1/b1

The NIST framework agrees (nist:ai-100-1/r1/p9), as does a page that does not exist
({PAPER}/v2/p99) and "a quotation with nothing after it to attach to".

A term in "scare quotes" is not a quotation.
"""


def test_parse_answer_pairs_quotes_with_citations() -> None:
    parsed = parse_answer(ANSWER)
    assert [str(c.citation) for c in parsed.citations] == [
        f"{PAPER}/v2/p6",
        f"{PAPER}/v2/p1",
        f"{PAPER}/v2/p6",
        f"{PAPER}/v2/p3",
        "distill:zoom-in/r1/b1",
        "nist:ai-100-1/r1/p9",
        f"{PAPER}/v2/p99",
    ]
    pairs = [
        (q.text[:24], None if q.citation is None else str(q.citation.citation))
        for q in parsed.quotes
    ]
    assert pairs == [
        ("model evaluation is one ", f"{PAPER}/v2/p6"),
        ("new and hard-to-forecast", f"{PAPER}/v2/p1"),
        ("Model evaluation is the ", f"{PAPER}/v2/p6"),
        ("discover vulnerabilities", f"{PAPER}/v2/p3"),
        ("Many important transitio", "distill:zoom-in/r1/b1"),
        # no citation follows it in its paragraph, so it falls back to the one before it
        ("a quotation with nothing", f"{PAPER}/v2/p99"),
    ]


def test_a_quote_before_its_citation_and_an_unattached_quote() -> None:
    parsed = parse_answer(
        f'According to {PAPER}/v2/p6, "model evaluation is one of the main tools".\n\n'
        '"An orphaned quotation, alone in its paragraph."\n\n'
        f"> a blockquote with the citation inside it {PAPER}/v2/p2\n"
    )
    first, orphan, block = parsed.quotes
    assert first.citation is not None and str(first.citation.citation) == f"{PAPER}/v2/p6"
    assert orphan.citation is None
    assert block.text == "a blockquote with the citation inside it"
    assert block.citation is not None and str(block.citation.citation) == f"{PAPER}/v2/p2"


def test_check_answer_audits_links_and_quotes(library: Corpus) -> None:
    audit = library.check_answer(ANSWER)
    assert audit.citation_count == 7
    assert audit.resolved_count == 6
    assert audit.quote_count == 6
    assert audit.passed_count == 3
    assert audit.verdict_counts == {
        "elsewhere": 1,
        "exact": 2,
        "near_miss": 1,
        "normalized": 1,
        "unchecked": 1,
    }
    assert audit.support_checked is False
    assert "Support is not checked" in audit.summary
    assert audit.summary.startswith("7 citations: 6 resolve; 6 quotations: ")

    by_cite = [
        (a.cite, [q.check.verdict if q.check else None for q in a.quotes]) for a in audit.citations
    ]
    assert by_cite == [
        (f"{PAPER}/v2/p6", [Verdict.EXACT]),
        (f"{PAPER}/v2/p1", [Verdict.NORMALIZED]),
        (f"{PAPER}/v2/p6", [Verdict.NEAR_MISS]),  # "not" was deleted
        (f"{PAPER}/v2/p3", [Verdict.ELSEWHERE]),  # it is on p5
        ("distill:zoom-in/r1/b1", [Verdict.EXACT]),
        ("nist:ai-100-1/r1/p9", []),  # a bare citation: resolves, nothing to check
        (f"{PAPER}/v2/p99", [None]),
    ]
    wrong_page = audit.citations[3].quotes[0].check
    assert wrong_page is not None
    assert wrong_page.locations[0].cite == f"{PAPER}/v2/p5"
    missing = audit.citations[-1]
    assert not missing.resolves
    assert missing.error is not None and "has 20 pages" in missing.error
    assert missing.quotes[0].error == "the citation does not resolve"
    assert audit.citations[0].url == f"{BASE}/d/arxiv/2305.15324/v2/p6"


def test_check_answer_on_text_without_citations(library: Corpus) -> None:
    audit = library.check_answer(
        'Nothing cited here, only "an unattached quotation of some length".'
    )
    assert audit.citation_count == 0
    assert audit.unattached_quotes == ["an unattached quotation of some length"]
    assert "1 quotations with no citation" in audit.summary
