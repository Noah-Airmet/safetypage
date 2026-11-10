"""The measures. Pure functions of (question, answer, what the tools returned, the corpus).

Deterministic checks and the judge are kept apart, as the trace format requires:

- page precision and recall against the gold units: code
- quote fidelity, with :meth:`Corpus.verify_quote` on the pinned snapshot: code
- seen-text, whether every cited unit came back from a tool during the run: code
- the verdict on a claim (``Verdict: supported`` / ``not supported``): code
- claim support: a named judge (:mod:`onthepage.bench.judge`), reported with its agreement

``correct`` is the headline and is judge-free: the verdict is right (for claim questions), at
least one cited unit is gold, and no citation is rejected by code (unresolved, unseen, or a
quote that is not on the cited unit).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from onthepage.answer import parse_answer
from onthepage.corpus import Corpus, NotFoundError
from onthepage.ids import Citation, find_citations
from onthepage.quote import QuoteTooShortError, Verdict
from onthepage.trace import (
    AnswerCitation,
    Judgement,
    ToolEvent,
    ToolReturn,
    VerifyEvent,
    citation_state,
)

from .questions import Question

__all__ = [
    "MEASURES",
    "Graded",
    "Judge",
    "claim_context",
    "grade",
    "parse_verdict",
    "tool_event",
    "units_of",
]

MEASURES = (
    "correct",
    "verdict_correct",
    "page_precision",
    "page_recall",
    "quote_fidelity",
    "quoted",
    "seen_rate",
    "support_rate",
)
"""Every per-sample measure, in the order results files list them. A measure is ``None`` on a
sample where it is undefined (no quotes, no citations, not a claim question, no judge)."""

MAX_JUDGED_UNITS = 4
"""A citation wider than this is not sent to the judge (and so cannot count as supported)."""

Judge = Callable[[str, str, str], Awaitable[Judgement]]
"""``await judge(claim, cite, unit_text) -> Judgement``."""

_VERDICT_RE = re.compile(
    r"^[\s>*_#-]*verdict[\s*_]*:[\s*_]*(not[\s_-]+supported|supported)\b", re.I | re.M
)


def parse_verdict(answer: str) -> str | None:
    """``supported``, ``not_supported``, or None. The first ``Verdict:`` line wins."""
    m = _VERDICT_RE.search(answer)
    if m is None:
        return None
    return "supported" if m.group(1).lower() == "supported" else "not_supported"


def units_of(citation: Citation) -> list[str]:
    """The single-unit cite strings a citation (or range) covers."""
    return [str(Citation(citation.doc, citation.version, a)) for a in citation.anchor.singles()]


def tool_event(
    *,
    seq: int,
    call_id: str,
    tool: str,
    args: dict[str, Any],
    result: str,
    error: str | None = None,
    t_ms: int = 0,
    latency_ms: int | None = None,
) -> ToolEvent:
    """One tool call as a trace event. ``returned`` is every unit named in the result, in
    order; a result that is an error returns nothing (an error message that lists the pages
    that do exist has not shown the agent those pages)."""
    returned: list[ToolReturn] = []
    if error is None and tool != "check_answer":  # it echoes the agent's own citations
        seen: set[str] = set()
        for found in find_citations(result):
            for unit in units_of(found.citation):
                if unit not in seen:
                    seen.add(unit)
                    returned.append(ToolReturn(cite=unit))
    verdict = None
    found_at = None
    if tool == "verify_quote" and error is None:
        m = re.search(r"\b(exact|normalized|elsewhere|near_miss|not_found)\b", result)
        verdict = Verdict(m.group(1)) if m else None
        if verdict is Verdict.ELSEWHERE and returned:
            found_at = returned[-1].cite
    return ToolEvent(
        seq=seq,
        t_ms=t_ms,
        call_id=call_id,
        tool=tool,
        args=args,
        returned=returned,
        verdict=verdict,
        found_at=found_at,
        result_tokens=max(1, len(result) // 4),
        latency_ms=latency_ms,
        error=error,
    )


def claim_context(answer: str, start: int, end: int, *, limit: int = 700) -> str:
    """The claim a citation is attached to: the sentence it is in, and the sentence before it
    on the same line (where the quotation it cites usually is), with citations removed. One
    line, not the paragraph, so each item of a list is judged on its own."""
    line_start = answer.rfind("\n", 0, start) + 1
    line_end = answer.find("\n", end)
    line = answer[line_start : line_end if line_end >= 0 else None]
    at = start - line_start
    spans = [
        (m.start(), m.end())
        for m in re.finditer(r"[^.!?]*(?:[.!?](?=\s|$)|$)", line, re.S)
        if m.end() > m.start()
    ]
    index = next((n for n, (s, e) in enumerate(spans) if s <= at < e or at < s), len(spans) - 1)
    first = max(0, index - 1)
    text = line[spans[first][0] : spans[index][1]] if spans else line
    for found in find_citations(text):
        text = text.replace(found.raw, "")
    text = re.sub(r"\[\s*\]\(\s*\)|\(\s*\)|\[\s*\]", "", text)
    return " ".join(text.split())[:limit]


@dataclass
class Graded:
    scores: dict[str, float | None]
    citations: list[AnswerCitation] = field(default_factory=list[AnswerCitation])
    verify: list[VerifyEvent] = field(default_factory=list[VerifyEvent])
    cite_quotes: dict[str, str | None] = field(default_factory=dict[str, str | None])

    @property
    def defined(self) -> dict[str, float]:
        return {k: v for k, v in self.scores.items() if v is not None}


def _worst(checks: list[Verdict]) -> Verdict | None:
    failing = [v for v in checks if v not in (Verdict.EXACT, Verdict.NORMALIZED)]
    if failing:
        return failing[0]
    if not checks:
        return None
    return Verdict.NORMALIZED if Verdict.NORMALIZED in checks else Verdict.EXACT


async def grade(
    question: Question,
    answer: str,
    seen: Iterable[str],
    corpus: Corpus,
    *,
    judge: Judge | None = None,
    first_seq: int = 0,
) -> Graded:
    """Score one answer. ``seen`` is every unit a tool returned during the run."""
    seen_set = set(seen)
    gold = set(question.gold)
    parsed = parse_answer(answer)

    # One cite id per distinct cite string, in order of first appearance.
    order: list[str] = []
    first: dict[str, Any] = {}
    for found in parsed.citations:
        key = str(found.citation)
        if key not in first:
            first[key] = found
            order.append(key)
    quotes: dict[str, list[str]] = {k: [] for k in order}
    for q in parsed.quotes:
        if q.citation is not None:
            quotes[str(q.citation.citation)].append(q.text)

    graded = Graded(scores={})
    cited_units: set[str] = set()
    quote_total = quote_passed = 0
    judged = supported = 0
    seen_count = 0
    rejected_by_code = False
    seq = first_seq
    for n, key in enumerate(order, start=1):
        found = first[key]
        cite_id = f"c{n}"
        citation: Citation = found.citation
        units = units_of(citation)
        resolves = True
        unit_text = ""
        try:
            resolved = corpus.resolve(citation)
            if resolved.scope is not None and citation.anchor.size <= MAX_JUDGED_UNITS:
                # The judge reads the whole unit, whatever the tier: this is grading, not serving.
                start, end = resolved.scope
                unit_text = corpus.private_spine_text(resolved.version)[start:end]
        except NotFoundError:
            resolves = False
        is_seen = resolves and all(u in seen_set for u in units)
        seen_count += is_seen
        if resolves:
            cited_units.update(units)

        verdicts: list[Verdict] = []
        span: tuple[int, int] | None = None
        closest: str | None = None
        if resolves:
            for text in quotes[key]:
                try:
                    check = corpus.verify_quote(text, citation)
                except QuoteTooShortError:
                    continue
                verdicts.append(check.verdict)
                quote_total += 1
                quote_passed += check.passed
                if check.locations:
                    loc = check.locations[0]
                    if check.passed and span is None:
                        span = (loc.spine_start, loc.spine_end)
                    elif not check.passed and closest is None:
                        closest = loc.cite
        else:
            quote_total += len(quotes[key])
        quote_verdict = _worst(verdicts)

        judgement: Judgement | None = None
        if judge is not None and resolves and unit_text:
            claim = claim_context(answer, found.start, found.end)
            judgement = await judge(claim, key, unit_text)
            judged += 1
            supported += judgement.label == "supported"

        state, reason = citation_state(
            resolves=resolves, seen=is_seen, quote_verdict=quote_verdict, judgement=judgement
        )
        if reason in (
            "unresolved",
            "unseen",
            "quote_elsewhere",
            "quote_near_miss",
            "quote_not_found",
        ):
            rejected_by_code = True
        graded.verify.append(
            VerifyEvent(
                seq=seq,
                t_ms=0,
                cite_id=cite_id,
                state=state,
                reason=reason,
                resolves=resolves,
                seen=is_seen,
                quote_verdict=quote_verdict,
                span=span,
                closest=closest,
                judgement=judgement,
            )
        )
        seq += 1
        graded.citations.append(
            AnswerCitation(
                cite_id=cite_id,
                cite=key,
                quote=quotes[key][0] if quotes[key] else None,
                state=state,
                reason=reason,
                gold=bool(gold.intersection(units)),
            )
        )
        graded.cite_quotes[cite_id] = quotes[key][0] if quotes[key] else None

    verdict = parse_verdict(answer)
    verdict_correct: float | None = None
    if question.kind == "claim":
        verdict_correct = float(verdict == question.expected)
    hits = cited_units & gold
    s = graded.scores
    s["verdict_correct"] = verdict_correct
    s["page_precision"] = len(hits) / len(cited_units) if cited_units else None
    s["page_recall"] = len(hits) / len(gold) if gold else None
    s["quote_fidelity"] = quote_passed / quote_total if quote_total else None
    s["quoted"] = float(quote_total > 0)
    s["seen_rate"] = seen_count / len(order) if order else None
    s["support_rate"] = supported / judged if judged else None
    s["correct"] = float(
        (verdict_correct is None or verdict_correct == 1.0) and bool(hits) and not rejected_by_code
    )
    return graded
