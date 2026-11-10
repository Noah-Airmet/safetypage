"""Turning mined candidates into questions: a model drafts, code checks, a second model or a
person confirms.

For a citing sentence the drafter reads the cited document and names the units that bear on
the sentence, each with a verbatim quote, and says whether the source supports what the sentence
attributes to it. Code keeps only units whose quote :meth:`Corpus.verify_quote` passes there:
those are the gold. A supported claim also yields a *perturbed* claim, the same sentence changed
so the source does not say it, with the same gold pages (what the source does say).

For a version diff and a shared section, code has already located both units; the drafter only
writes the question text.

Every question records the drafter's model and prompt id, its evidence and the code's verdict on
each quote (``made``), and each check it has passed (``checks``).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any, cast

from inspect_ai.model import GenerateConfig, Model, get_model

from onthepage.corpus import Corpus, NotFoundError
from onthepage.quote import QuoteTooShortError

from .agents import complete, is_cli_model
from .mine import Candidate
from .questions import Check, Made, Question, question_id

__all__ = ["CLAIM_TEMPLATE", "check_question", "draft"]

CLAIM_TEMPLATE = (
    "A document in the library contains this sentence:\n\n> {sentence}\n\n"
    "Check what the sentence says about the work it cites against that work in the library. "
    "Does the cited source support it? Cite the page(s) of the cited source that show what it "
    "actually says."
)

CLAIM_PROMPT = """\
A sentence in one document cites another document. You have the full text of the cited
document below, unit by unit; each unit starts with its cite string in square brackets.

SENTENCE (from {citing_doc}):
{sentence}

CITED DOCUMENT: {cited_title}

1. State, in one sentence, what the SENTENCE attributes to the cited document.
2. Decide whether the cited document supports that: "supported", "partially_supported" or
   "not_supported" (it says something different, or does not say it).
3. Give 1 to 3 pieces of evidence: the cite string of a unit and an exact quotation from that
   unit (copied character for character, 8 to 40 words) that shows what the document says on
   this point. For "not_supported", quote what it says instead.
4. If the verdict is "supported", write PERTURBED: the same sentence changed in one specific
   way (a number, a negation, a stronger scope, a different cause) so that the cited document
   clearly does not support it. Keep the citation marker.

Answer with JSON only:
{{"attributed": "...", "verdict": "...", "evidence": [{{"cite": "...", "quote": "..."}}],
  "perturbed": "..." or null, "change": "what you changed" or null}}

DOCUMENT TEXT:
{units}
"""

COMPARE_PROMPT = """\
Write one question for a research-literature benchmark. The answer must need BOTH passages
below. Do not quote them; ask about the substance, and name the document(s) and the
version(s) or edition(s) so the question is answerable from a library of many documents.

{context}

Answer with JSON only: {{"question": "..."}}
"""

CHECK_PROMPT = """\
You are checking one question in a benchmark. Below are the question, the answer the benchmark
expects ("supported" / "not_supported" for a claim check, "answer" for an open question), and
the text of the gold pages.

QUESTION:
{question}

EXPECTED: {expected}

GOLD PAGES:
{gold}

Is the expected answer right and do the gold pages contain what is needed to show it? Reply
with a short reason and then a last line "OK: yes" or "OK: no".
"""

PROMPT_ID = "draft@" + hashlib.sha256((CLAIM_PROMPT + COMPARE_PROMPT).encode()).hexdigest()[:6]
MAX_DOC_CHARS = 150_000


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _units_text(corpus: Corpus, doc_id: str, focus: str) -> str:
    """The cited document's units, each prefixed by its cite string. A long document is cut to
    the units sharing the most words with ``focus``, kept in reading order."""
    rows = corpus.conn.execute(
        "SELECT cite, text FROM units WHERE doc_id = ? AND version = "
        "(SELECT label FROM versions WHERE doc_id = ? ORDER BY seq DESC LIMIT 1) ORDER BY seq",
        (doc_id, doc_id),
    ).fetchall()
    units = [(str(r[0]), str(r[1])) for r in rows]
    if sum(len(t) for _, t in units) > MAX_DOC_CHARS:
        words = set(re.findall(r"[a-z]{4,}", focus.lower()))
        ranked = sorted(
            range(len(units)),
            key=lambda i: -len(words & set(re.findall(r"[a-z]{4,}", units[i][1].lower()))),
        )
        keep: set[int] = set()
        total = 0
        for i in ranked:
            if total + len(units[i][1]) > MAX_DOC_CHARS:
                continue
            keep.add(i)
            total += len(units[i][1])
        units = [u for i, u in enumerate(units) if i in keep]
    return "\n\n".join(f"[{c}]\n{t}" for c, t in units)


def _json(text: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", text, re.S)
    if m is None:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return cast(dict[str, Any], data) if isinstance(data, dict) else None


def _verified(corpus: Corpus, evidence: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for e in evidence:
        cite, quote = str(e.get("cite", "")).strip("[] "), str(e.get("quote", ""))
        try:
            check = corpus.verify_quote(quote, cite)
            verdict = check.verdict.value
            if check.passed and check.locations:
                cite = check.locations[0].cite
        except (NotFoundError, QuoteTooShortError, ValueError) as exc:
            verdict = f"error: {exc}"[:120]
        out.append({"cite": cite, "quote": quote, "verdict": verdict})
    return out


def _passing(evidence: list[dict[str, str]]) -> list[str]:
    gold: list[str] = []
    for e in evidence:
        single = "-" not in e["cite"].rsplit("/", 1)[-1]
        if e["verdict"] in ("exact", "normalized") and single and e["cite"] not in gold:
            gold.append(e["cite"])
    return gold


async def _generate(model: str | Model, prompt: str) -> str:
    if isinstance(model, str) and is_cli_model(model):
        return await asyncio.to_thread(complete, model, prompt)

    out = await get_model(model).generate(prompt, config=GenerateConfig(max_tokens=8000))
    return out.completion


async def draft(corpus: Corpus, candidate: Candidate, model: str | Model) -> list[Question]:
    """Zero or more questions from one candidate. Each has a ``code`` check: its gold quotes
    (or, for located candidates, its gold units) were verified by code."""
    drafted_by = f"{model if isinstance(model, str) else model.name}#{PROMPT_ID}"
    extra = dict(candidate.extra)
    if candidate.method == "citing_sentence":
        prompt = CLAIM_PROMPT.format(
            citing_doc=extra.get("citing_doc", "?"),
            sentence=candidate.source_text,
            cited_title=extra.get("cited_title", candidate.cluster),
            units=_units_text(corpus, candidate.cluster, candidate.source_text),
        )
        data = _json(await _generate(model, prompt))
        if data is None:
            return []
        evidence = _verified(corpus, list(data.get("evidence") or []))
        gold = [g for g in _passing(evidence) if g.startswith(candidate.cluster + "/")]
        verdict = data.get("verdict")
        if not gold or verdict not in ("supported", "not_supported"):
            return []
        code_check = Check(level="code", by="verify_quote", at=now(), note="gold quotes verified")
        questions = [
            Question(
                id=question_id("citing_sentence", candidate.source_text),
                kind="claim",
                question=CLAIM_TEMPLATE.format(sentence=candidate.source_text),
                expected=verdict,
                gold=gold,
                cluster=candidate.cluster,
                made=Made(
                    method="citing_sentence",
                    source_cite=candidate.source_cite,
                    source_text=candidate.source_text,
                    drafted_by=drafted_by,
                    evidence=evidence,
                    note=str(data.get("attributed") or "") or None,
                ),
                checks=[code_check],
            )
        ]
        perturbed = data.get("perturbed")
        if verdict == "supported" and isinstance(perturbed, str) and len(perturbed) > 30:
            questions.append(
                Question(
                    id=question_id("perturbed_claim", perturbed),
                    kind="claim",
                    question=CLAIM_TEMPLATE.format(sentence=perturbed),
                    expected="not_supported",
                    gold=gold,
                    cluster=candidate.cluster,
                    made=Made(
                        method="perturbed_claim",
                        source_cite=candidate.source_cite,
                        source_text=candidate.source_text,
                        drafted_by=drafted_by,
                        evidence=evidence,
                        note=str(data.get("change") or "") or None,
                    ),
                    checks=[code_check],
                )
            )
        return questions

    # version_diff, shared_section: both units located by code.
    gold = [candidate.source_cite, *candidate.targets]
    if any("-" in g.rsplit("/", 1)[-1] for g in gold):
        return []  # gold is single units; a passage across a page break is skipped
    doc = corpus.document(candidate.cluster)
    if candidate.method == "version_diff":
        context = (
            f"DOCUMENT: {doc.title if doc else candidate.cluster}\n"
            f"EARLIER VERSION ({candidate.targets[0]}): {candidate.target_texts[0]}\n"
            f"LATER VERSION ({candidate.source_cite}): {candidate.source_text}"
        )
    else:
        texts: list[str] = []
        for cite in gold:
            units = corpus.read_units(cite)
            title = corpus.document(cite.split("/", 1)[0])
            texts.append(
                f"{title.title if title else cite} ({cite}), section "
                f"'{candidate.source_text}':\n{(units[0].text or '')[:6000]}"
            )
        context = "\n\n".join(texts)
    data = _json(await _generate(model, COMPARE_PROMPT.format(context=context)))
    if data is None or not isinstance(data.get("question"), str):
        return []
    return [
        Question(
            id=question_id(
                candidate.method, candidate.source_cite + "|" + "|".join(candidate.targets)
            ),
            kind="compare",
            question=data["question"],
            expected="answer",
            gold=gold,
            cluster=candidate.cluster,
            made=Made(
                method=candidate.method,  # type: ignore[arg-type]
                source_cite=candidate.source_cite,
                source_text=candidate.source_text,
                drafted_by=drafted_by,
            ),
            checks=[Check(level="code", by="mine", at=now(), note="gold units located by code")],
        )
    ]


async def check_question(corpus: Corpus, question: Question, model: str | Model) -> Check | None:
    """A second model's independent look at the question and its gold. ``None`` if it says no."""
    gold = "\n\n".join(
        f"[{cite}]\n{corpus.private_spine_text(r.version)[r.scope[0] : r.scope[1]]}"
        for cite in question.gold
        if (r := corpus.resolve(cite)).scope is not None
    )
    reply = await _generate(
        model,
        CHECK_PROMPT.format(question=question.question, expected=question.expected, gold=gold),
    )
    ok = re.findall(r"OK:\s*(yes|no)", reply, re.I)
    if not ok or ok[-1].lower() != "yes":
        return None
    name = model if isinstance(model, str) else model.name
    return Check(level="model", by=name, at=now(), note=reply.strip().splitlines()[0][:200])
