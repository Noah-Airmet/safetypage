"""The measures, the miners and the statistics, on the fixture corpus. No model calls."""

from __future__ import annotations

import asyncio

from onthepage.bench.judge import agreement, parse_label
from onthepage.bench.mine import citing_contexts, split_sentences, version_diffs
from onthepage.bench.questions import Made, Question, assign_split
from onthepage.bench.results import bootstrap
from onthepage.bench.score import grade, parse_verdict, tool_event
from onthepage.bench.task import open_corpus
from onthepage.trace import Judgement

GOLD = "arxiv:2305.15324/v2/p6"
QUOTE = "Model evaluation is not the only tool available for AI risk assessment"


def _q(expected: str = "not_supported") -> Question:
    return Question(
        id="pc-t",
        kind="claim",
        question="?",
        expected=expected,  # type: ignore[arg-type]
        gold=[GOLD],
        cluster="arxiv:2305.15324",
        made=Made(method="perturbed_claim"),
    )


def _grade(answer: str, seen: set[str], **kw: object):  # type: ignore[no-untyped-def]
    return asyncio.run(grade(_q(), answer, seen, open_corpus("fixtures"), **kw))  # type: ignore[arg-type]


def test_a_correct_cited_answer() -> None:
    g = _grade(f'Verdict: not supported\n\nThe paper says "{QUOTE}" {GOLD}.', {GOLD})
    assert g.scores["correct"] == 1.0
    assert g.scores["page_precision"] == g.scores["page_recall"] == 1.0
    assert g.scores["quote_fidelity"] == 1.0
    assert g.citations[0].state == "verified" and g.citations[0].gold


def test_dropping_not_fails_the_quote_and_the_answer() -> None:
    wrong = "Model evaluation is the only tool available for AI risk assessment"
    g = _grade(f'Verdict: not supported\n\n"{wrong}" {GOLD}', {GOLD})
    assert g.scores["quote_fidelity"] == 0.0
    assert g.scores["correct"] == 0.0
    assert g.citations[0].reason == "quote_near_miss"


def test_unseen_citation_is_rejected() -> None:
    g = _grade(f"Verdict: not supported\n\nSee {GOLD}.", set())
    assert g.scores["seen_rate"] == 0.0
    assert g.citations[0].reason == "unseen"
    assert g.scores["correct"] == 0.0


def test_unresolved_and_wrong_verdict() -> None:
    g = _grade("Verdict: supported\n\nSee arxiv:2305.15324/v2/p99.", {GOLD})
    assert g.citations[0].reason == "unresolved"
    assert g.scores["verdict_correct"] == 0.0
    assert g.scores["page_precision"] is None


def test_range_citation_counts_its_pages() -> None:
    g = _grade(
        "Verdict: not supported\n\nSee arxiv:2305.15324/v2/p5-p6.",
        {"arxiv:2305.15324/v2/p5", GOLD},
    )
    assert g.scores["page_precision"] == 0.5
    assert g.scores["page_recall"] == 1.0


def test_judge_is_kept_apart_from_code() -> None:
    async def judge(claim: str, cite: str, text: str) -> Judgement:
        assert "not the only tool" in text
        return Judgement(judge="j", label="unsupported")

    g = _grade(f'Verdict: not supported\n\n"{QUOTE}" {GOLD}', {GOLD}, judge=judge)
    assert g.scores["support_rate"] == 0.0
    assert g.citations[0].reason == "unsupported"
    assert g.scores["correct"] == 1.0  # the headline is judge-free


def test_parse_verdict() -> None:
    assert parse_verdict("**Verdict:** Not supported. The page says...") == "not_supported"
    assert parse_verdict("Verdict: supported") == "supported"
    assert parse_verdict("I think it is supported") is None


def test_tool_event_ignores_errors() -> None:
    ok = tool_event(seq=0, call_id="a", tool="fetch", args={}, result=f"## {GOLD}\ntext")
    assert [r.cite for r in ok.returned] == [GOLD]
    err = tool_event(seq=1, call_id="b", tool="fetch", args={}, result=GOLD, error="no p21")
    assert err.returned == []


def test_miners_on_the_fixtures() -> None:
    corpus = open_corpus("fixtures")
    contexts = citing_contexts(corpus)
    assert {c.cluster for c in contexts} == {"distill:zoom-in"}
    assert any("polysemantic" in c.source_text for c in contexts)
    [diff] = version_diffs(corpus)
    assert diff.source_cite == GOLD and diff.targets == ("arxiv:2305.15324/v1/p6",)
    assert "Khlaaf" in diff.source_text and "Khlaaf" not in diff.target_texts[0]


def test_sentences_do_not_break_at_et_al() -> None:
    text = "Prior work (Olah et al. 2020) found this. A second sentence follows."
    spans = split_sentences(text)
    assert next(text[s:e] for s, e in spans) == "Prior work (Olah et al. 2020) found this."


def test_split_is_by_cluster_and_stable() -> None:
    assert assign_split("arxiv:2305.15324") == assign_split("arxiv:2305.15324")


def test_bootstrap_and_agreement() -> None:
    est = bootstrap([1.0, 0.0, None, 1.0], ["a", "a", "b", "c"])
    assert est.n == 3 and est.mean is not None and abs(est.mean - 2 / 3) < 1e-9
    assert est.ci_low is not None and est.ci_high is not None
    assert est.ci_low <= est.mean <= est.ci_high
    agree = agreement(
        [("supported", "supported"), ("unsupported", "unsupported"), ("supported", "unsupported")],
        "j",
    )
    assert agree["n"] == 3 and agree["unsupported_recall"] == 1.0
    assert agree["unsupported_precision"] == 0.5
    assert parse_label("Fine.\nLABEL: partially_supported") == "partially_supported"
