"""Running CitationBench with a coding-agent CLI on a subscription login.

    python -m safetypage.bench run citationbench/configs/cc-opus.toml [--batch 10] [--until 06:30]

One question per fresh CLI session. The server's call log (``ops.sqlite``, written in full for
calls that carry ``X-SafetyPage-Run`` and ``X-SafetyPage-Sample``) is the record of what the agent
saw; the CLI's own output gives the answer, the tokens and the account's usage meter. Scoring is
the same :func:`safetypage.bench.score.grade` the Inspect path uses, and the run writes the same
results file and traces.

Gentle on the account: a batch runs at most ``batch`` samples with ``pause`` seconds between
them, and stops cleanly, recording where, when the CLI reports a rate or usage limit, when the
usage meter passes ``max_used``, or when the next sample would not finish before ``until``.
Every finished sample is saved as it completes, so rerunning the same configuration resumes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from inspect_ai import eval as inspect_eval  # pyright: ignore[reportUnknownVariableType]

from safetypage.trace import (
    Answer,
    AnswerCitation,
    AnswerEvent,
    CiteEvent,
    ToolEvent,
    ToolReturn,
    Trace,
    TraceHeader,
    Usage,
    VerifyEvent,
)

from .agents import AgentRun, UsageLimitError, run_agent
from .judge import load_agreements, make_judge
from .questions import Question, load_questions
from .results import PriceTable, RunResult, summarize, write_result
from .score import MEASURES, Graded, grade
from .task import INSTRUCTIONS, REPO, SOLVER, citationbench, open_corpus, surface_url

__all__ = ["CLI_INSTRUCTIONS", "BatchOutcome", "rescore", "run_cli", "run_id_for"]

PC = REPO / "citationbench"
CLI_INSTRUCTIONS = INSTRUCTIONS.replace(
    "- When you are done, call submit() with your complete answer.\n",
    "- Use only the SafetyPage library tools. Your final message is your complete answer.\n",
)


@dataclass
class BatchOutcome:
    run_id: str
    done: int
    planned: int
    ran_now: int
    stopped: str | None
    results: Path | None


def run_id_for(config: dict[str, Any]) -> str:
    """Stable for a configuration, so rerunning it resumes the same run."""
    keep = {k: v for k, v in config.items() if k not in ("batch", "pause", "until", "max_used")}
    digest = hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest()[:6]
    return f"{config.get('name', 'run')}-{digest}"


def _ops_events(
    ops_db: Path, run_id: str, sample: str, started: datetime
) -> tuple[list[ToolEvent], dict[str, str]]:
    if not ops_db.is_file():
        return [], {}
    conn = sqlite3.connect(f"{ops_db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT request_id, ts, surface_id, snapshot, arm, server_version, tool, args, "
            "returned, verdict, result_tokens, latency_ms, error FROM tool_calls "
            "WHERE run_id = ? AND sample_id = ? ORDER BY rowid",
            (run_id, sample),
        ).fetchall()
    finally:
        conn.close()
    events: list[ToolEvent] = []
    meta: dict[str, str] = {}
    for n, r in enumerate(rows):
        request_id, ts, surface_id, snapshot, arm, version, tool, args, returned, verdict = r[:10]
        meta = {
            "surface_id": surface_id,
            "snapshot": snapshot,
            "arm": arm,
            "server_version": version,
        }
        cites: list[str] = [] if tool == "check_answer" else json.loads(returned or "[]")
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        events.append(
            ToolEvent(
                seq=n,
                t_ms=max(0, int((t - started).total_seconds() * 1000)),
                call_id=str(request_id),
                tool=str(tool),
                args=json.loads(args or "{}"),
                returned=[ToolReturn(cite=c) for c in dict.fromkeys(cites)],
                verdict=verdict
                if verdict in ("exact", "normalized", "elsewhere", "near_miss", "not_found")
                else None,  # type: ignore[arg-type]
                result_tokens=r[10],
                latency_ms=r[11],
                error=r[12],
                request_id=str(request_id),
            )
        )
    return events, meta


def _trace(
    run_id: str, question: Question, sample: str, record: dict[str, Any], config: dict[str, Any]
) -> Trace:
    events: list[Any] = [ToolEvent.model_validate(e) for e in record["tool_events"]]
    end = int(record["seconds"] * 1000)
    events.append(AnswerEvent(seq=len(events), t_ms=end, delta=record["answer"]))
    citations = [AnswerCitation.model_validate(c) for c in record["citations"]]
    for c in citations:
        events.append(
            CiteEvent(seq=len(events), t_ms=end, cite_id=c.cite_id, cite=c.cite, quote=c.quote)
        )
    for v in record["verify"]:
        events.append(
            VerifyEvent.model_validate(v).model_copy(update={"seq": len(events), "t_ms": end})
        )
    meta: dict[str, str] = record.get("server") or {}
    tokens = record["tokens"]
    return Trace(
        header=TraceHeader(
            trace_id=f"{run_id}-{sample}",
            run_id=run_id,
            sample_id=question.id,
            question=question.question,
            model=str(config["model"]),
            solver=record["agent_version"],
            surface_id=meta.get("surface_id", str(config.get("surface", "default"))),
            snapshot=meta.get("snapshot", str(config.get("corpus", "fixtures"))),
            arm=meta.get("arm", "unknown"),
            server_version=meta.get("server_version", "unknown"),
            started_at=record["started_at"],
            usage=Usage(
                input_tokens=tokens.get("input", 0),
                output_tokens=tokens.get("output", 0),
                cache_read_tokens=tokens.get("cache_read", 0),
            ),
        ),
        events=events,
        answer=Answer(text=record["answer"], citations=citations),
        scores={k: v for k, v in record["scores"].items() if v is not None},
    )


def _inspect_sample(
    config: dict[str, Any], question: Question, headers: dict[str, str], state: Path
) -> AgentRun:
    """One question through the Inspect agent (``react``), for local models and API keys."""
    task = citationbench(
        questions=str(config.get("questions", "citationbench/questions/dev.jsonl")),
        corpus=str(config.get("corpus", "fixtures")),
        server=str(config.get("server", "http://localhost:8766")),
        surface=str(config.get("surface", "default")),
        message_limit=int(config.get("message_limit", 40)),
        headers=headers,
    )
    model = str(config["model"])
    start = time.monotonic()
    [log] = inspect_eval(
        task,
        model=model,
        sample_id=question.id,
        log_dir=str(state / "logs"),
        display="none",
        score=False,
        **config.get("generate", {}),
    )
    seconds = time.monotonic() - start
    if not log.samples:
        error = str(log.error.message if log.error else log.status)
        if re.search(r"rate.?limit|quota|429", error, re.I):
            raise UsageLimitError(error)
        return AgentRun(answer="", seconds=seconds, error=error, agent_version=f"inspect {SOLVER}")
    sample = log.samples[0]
    u = sample.model_usage.get(model)
    return AgentRun(
        answer=sample.output.completion if sample.output else "",
        usage={
            "input": u.input_tokens if u else 0,
            "output": u.output_tokens if u else 0,
            "cache_read": (u.input_tokens_cache_read or 0) if u else 0,
            "cache_write": (u.input_tokens_cache_write or 0) if u else 0,
            "reasoning": (u.reasoning_tokens or 0) if u else 0,
        },
        seconds=seconds,
        error=sample.error.message if sample.error else None,
        agent_version=f"inspect {SOLVER}",
    )


def _grade(
    question: Question,
    answer: str,
    tool_events: list[ToolEvent],
    corpus: Any,
    *,
    judge: Any,
    invalid: bool,
) -> tuple[Graded, dict[str, float | None]]:
    """Score one answer. A sample that used something other than the library, or failed, is
    scored as wrong; its other measures are kept for diagnosis."""
    seen = {r.cite for e in tool_events for r in e.returned}
    graded = asyncio.run(grade(question, answer, seen, corpus, judge=judge))
    scores = dict(graded.scores)
    if invalid:
        scores = {m: (0.0 if m in ("correct", "verdict_correct") else v) for m, v in scores.items()}
    return graded, scores


def rescore(config: dict[str, Any]) -> Path | None:
    """Score a run's saved answers again (after a change to the scorer or the judge), without
    running any agent."""
    run_id = run_id_for(config)
    state = PC / "work" / "runs" / run_id
    qfile = REPO / str(config.get("questions", "citationbench/questions/dev.jsonl"))
    by_id = {q.id: q for q in load_questions(qfile)}
    corpus = open_corpus(str(config.get("corpus", "fixtures")))
    judge = make_judge(str(config["judge"])) if config.get("judge") else None
    for path in sorted((state / "samples").glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        events = [ToolEvent.model_validate(e) for e in rec["tool_events"]]
        invalid = bool(rec["off_library"] or rec["error"])
        question = by_id[rec["question_id"]]
        graded, scores = _grade(
            question, rec["answer"], events, corpus, judge=judge, invalid=invalid
        )
        rec["citations"] = [c.model_dump(mode="json") for c in graded.citations]
        rec["verify"] = [v.model_dump(mode="json") for v in graded.verify]
        rec["scores"] = scores
        path.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    stopped_file = state / "stopped.json"
    stopped = json.loads(stopped_file.read_text())["reason"] if stopped_file.is_file() else None
    plan = len(_subset(list(by_id.values()), config)) * int(config.get("epochs", 1))
    return write_cli_results(config, run_id, plan_size=plan, stopped=stopped)


def _subset(questions: list[Question], config: dict[str, Any]) -> list[Question]:
    """``limit = N`` runs the first N questions in id order (ids are hashes, so this is a fixed
    pseudo-random sample, and a 50-question run is a subset of a 150-question one)."""
    limit = int(config.get("limit", 0))
    return sorted(questions, key=lambda q: q.id)[:limit] if limit else questions


def _over(meter: dict[str, Any], ceiling: float | dict[str, float]) -> str | None:
    """``ceiling`` is one share for every window, or one per window
    (``{five_hour = 0.6, seven_day = 0.45}``)."""
    for key, value in meter.items():
        if not key.endswith("_used") or not isinstance(value, int | float):
            continue
        limit = ceiling.get(key.removesuffix("_used")) if isinstance(ceiling, dict) else ceiling
        if limit is not None and value >= limit:
            return f"usage meter {key} at {value:.0%}, at or above the {limit:.0%} ceiling"
    return None


def run_cli(
    config: dict[str, Any], *, batch: int | None = None, until: datetime | None = None
) -> BatchOutcome:
    agent, model = str(config["agent"]), str(config["model"])
    run_id = run_id_for(config)
    state = PC / "work" / "runs" / run_id
    (state / "samples").mkdir(parents=True, exist_ok=True)
    questions = _subset(
        load_questions(REPO / str(config.get("questions", "citationbench/questions/dev.jsonl"))),
        config,
    )
    epochs = int(config.get("epochs", 1))
    plan = [(q, e) for e in range(1, epochs + 1) for q in questions]
    batch = batch or int(config.get("batch", 10))
    pause = float(config.get("pause", 30))
    raw_ceiling = config.get("max_used", 0.8)
    ceiling = (
        {k: float(v) for k, v in raw_ceiling.items()}
        if isinstance(raw_ceiling, dict)
        else float(raw_ceiling)
    )
    ops_db = REPO / str(config.get("ops_db", "citationbench/work/ops.sqlite"))
    url = surface_url(
        str(config.get("server", "http://localhost:8766")), str(config.get("surface", "default"))
    )
    corpus = open_corpus(str(config.get("corpus", "fixtures")))
    judge = make_judge(str(config["judge"])) if config.get("judge") else None
    (state / "config.json").write_text(json.dumps(config, indent=1), encoding="utf-8")

    stopped: str | None = None
    ran = 0
    # The saved meter may be from a window that has since reset, so a batch starts unmetered:
    # its first sample reads the meter afresh.
    last_meter: dict[str, Any] = {}
    durations: list[float] = []
    (state / "stopped.json").unlink(missing_ok=True)
    for question, epoch in plan:
        sample = f"{question.id}.{epoch}"
        path = state / "samples" / f"{sample}.json"
        if path.is_file():
            continue
        if ran >= batch:
            stopped = f"batch of {batch} done; next is {sample}"
            break
        if (why := _over(last_meter, ceiling)) is not None:
            stopped = f"{why}; next is {sample}"
            break
        expected = (sum(durations) / len(durations)) if durations else 300.0
        if (
            until is not None
            and datetime.now(until.tzinfo).timestamp() + expected > until.timestamp()
        ):
            stopped = f"would not finish before {until:%H:%M}; next is {sample}"
            break
        if ran:
            time.sleep(pause)
        started = datetime.now(UTC)
        prompt = f"{CLI_INSTRUCTIONS}\nQUESTION:\n{question.question}"
        headers = {"X-SafetyPage-Run": run_id, "X-SafetyPage-Sample": sample}
        try:
            if agent == "inspect":
                result = _inspect_sample(config, question, headers, state)
            else:
                result = run_agent(
                    agent,
                    model,
                    prompt,
                    mcp_url=url,
                    headers=headers,
                    timeout=int(config.get("timeout", 900)),
                )
        except UsageLimitError as exc:
            stopped = f"usage limit: {exc}"[:500] + f"; next is {sample}"
            break
        tool_events, server = _ops_events(ops_db, run_id, sample, started)
        invalid = bool(result.off_library or result.error)
        graded, scores = _grade(
            question, result.answer, tool_events, corpus, judge=judge, invalid=invalid
        )
        record = {
            "question_id": question.id,
            "epoch": epoch,
            "started_at": started.isoformat(),
            "seconds": result.seconds,
            "answer": result.answer,
            "error": result.error,
            "off_library": result.off_library,
            "tokens": result.usage,
            "notional_usd": result.notional_usd,
            "meter": result.meter,
            "agent_version": result.agent_version,
            "server": server,
            "tool_events": [e.model_dump(mode="json") for e in tool_events],
            "citations": [c.model_dump(mode="json") for c in graded.citations],
            "verify": [v.model_dump(mode="json") for v in graded.verify],
            "scores": scores,
        }
        path.write_text(json.dumps(record, indent=1), encoding="utf-8")
        if result.raw:
            raw = state / "raw" / f"{sample}.jsonl"
            raw.parent.mkdir(exist_ok=True)
            raw.write_text(result.raw, encoding="utf-8")
        if result.meter:
            last_meter = result.meter
            (state / "meter.json").write_text(json.dumps(result.meter), encoding="utf-8")
        durations.append(result.seconds)
        ran += 1
    if stopped:
        (state / "stopped.json").write_text(
            json.dumps({"at": datetime.now(UTC).isoformat(), "reason": stopped}), encoding="utf-8"
        )
    results = write_cli_results(config, run_id, plan_size=len(plan), stopped=stopped)
    done = len(list((state / "samples").glob("*.json")))
    return BatchOutcome(run_id, done, len(plan), ran, stopped, results)


def write_cli_results(
    config: dict[str, Any], run_id: str, *, plan_size: int, stopped: str | None
) -> Path | None:
    state = PC / "work" / "runs" / run_id
    by_id = {
        q.id: q
        for q in load_questions(
            REPO / str(config.get("questions", "citationbench/questions/dev.jsonl"))
        )
    }
    records = [json.loads(p.read_text()) for p in sorted((state / "samples").glob("*.json"))]
    if not records:
        return None
    trace_dir = PC / "traces" / run_id
    trace_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for rec in records:
        question = by_id.get(rec["question_id"])
        if question is None:
            continue
        sample = f"{rec['question_id']}.{rec['epoch']}"
        trace = _trace(run_id, question, sample, rec, config)
        (trace_dir / f"{sample}.json").write_text(
            trace.model_dump_json(by_alias=True, exclude_none=True, indent=1), encoding="utf-8"
        )
        rows.append(
            {
                "scores": {m: rec["scores"].get(m) for m in MEASURES},
                "cluster": question.cluster,
                "method": question.made.method,
                "kind": question.kind,
                "correct": float(rec["scores"].get("correct") or 0.0),
                "tokens": rec["tokens"],
                "error": bool(rec["error"]),
                "contaminated": bool(rec["off_library"]),
                "seconds": rec["seconds"],
                "question_id": rec["question_id"],
            }
        )
    last = records[-1]
    meters = [r["meter"] for r in records if r.get("meter")]
    result: RunResult = summarize(
        rows,
        run_id=run_id,
        created_at=min(r["started_at"] for r in records),
        model=str(config["model"]),
        agent=str(last["agent_version"] or config["agent"]),
        epochs=int(config.get("epochs", 1)),
        config=config,
        log=f"work/runs/{run_id}",
        prices=PriceTable.load(REPO / "citationbench" / "prices" / "2026-11.json"),
        judge=str(config["judge"]) if config.get("judge") else None,
        agreements=load_agreements(REPO / "citationbench" / "labels" / "agreement.json"),
        billing="local"
        if str(config["model"]).startswith("openai-api/omlx/")
        else "api"
        if config.get("agent") == "inspect"
        else "subscription",
        meter={"after_first": meters[0], "after_last": meters[-1]} if meters else {},
        stopped=stopped if len(records) < plan_size else None,
        planned=plan_size,
    )
    return write_result(result, PC)
