"""From an Inspect log to the files the site reads: one results file per run, one trace per sample.

The ``.eval`` log stays the canonical record. This module derives:

- ``<out>/results/<run_id>.json``: a :class:`RunResult` (schema in
  ``schemas/pagecite/run-result.schema.json``), every measure with a 95% confidence interval
  from a cluster bootstrap over cited documents, and cost from a frozen price table;
- ``<out>/traces/<run_id>/<sample>.<epoch>.json``: a :class:`onthepage.trace.Trace` per sample,
  for the replay view.

``compare`` gives the paired difference between two runs on the same questions, which is how
an ablation is reported.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from inspect_ai.event import ToolEvent as InspectToolEvent
from inspect_ai.log import read_eval_log
from pydantic import BaseModel, ConfigDict, Field

from onthepage.trace import (
    Answer,
    AnswerCitation,
    AnswerEvent,
    CiteEvent,
    Trace,
    TraceHeader,
    Usage,
    VerifyEvent,
)

from .judge import judge_id as make_judge_id
from .questions import Question
from .score import MEASURES, tool_event

__all__ = [
    "SCHEMA",
    "Estimate",
    "PriceTable",
    "RunResult",
    "bootstrap",
    "compare",
    "write_run",
]

SCHEMA = "pagecite.result/1"
BOOTSTRAP_RESAMPLES = 2000


class Estimate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mean: float | None
    ci_low: float | None
    ci_high: float | None
    n: int
    """Samples on which the measure is defined."""


class Cost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    billing: Literal["subscription", "api", "local"] = "api"
    """How the run was paid for. For ``subscription`` and ``local`` runs the dollar figures are
    what the same tokens would cost at the table's list prices, not money spent."""

    price_table: str | None
    priced: bool
    """False for a model the table has no price for (local models are priced at 0 and marked
    ``local`` in the table instead)."""
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_usd: float | None
    per_sample_usd: float | None
    per_correct_usd: Estimate
    """Dollars per correct, fully cited answer, the headline cost."""


class JudgeInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    agreement: dict[str, Any] | None = None
    """From ``pagecite/labels/agreement.json``: n, kappa, accuracy, precision and recall on
    ``unsupported``. None until people have labelled a sample."""


class RunResult(BaseModel):
    """One run: one model, one tool surface, one question file. What the leaderboard reads."""

    model_config = ConfigDict(extra="forbid")

    schema_: str = Field(default=SCHEMA, alias="schema")
    run_id: str
    name: str
    """The run configuration's name, e.g. ``ablation-no-verify``."""
    created_at: str
    agent: str
    """The agent harness and its version: ``claude-code 2.1.321``, ``codex 0.167.0``,
    ``inspect react-baseline@1``. A leaderboard row is an agent plus a model."""
    model: str
    solver: str
    surface: str
    server: str | None
    snapshot: str
    """The corpus the run was scored against: a snapshot id, or ``fixtures``."""
    questions: dict[str, Any]
    """``{"file", "sha256", "n"}``."""
    epochs: int
    samples: int
    planned_samples: int
    complete: bool
    stopped: str | None = None
    """Why and where a run stopped early (a usage limit, a time window), if it did."""
    errors: int
    contaminated: int = 0
    """Samples where the agent used something other than the library (scored as wrong)."""
    seconds_per_sample: float | None = None
    judge: JudgeInfo | None
    measures: dict[str, Estimate]
    by_method: dict[str, dict[str, Estimate]]
    by_kind: dict[str, dict[str, Estimate]]
    cost: Cost
    meter: dict[str, Any] = Field(default_factory=dict[str, Any])
    """The account's usage meter as the agent CLI reported it, before and after the run."""
    config: dict[str, Any]
    """The run configuration as given: enough to rerun it (``python -m onthepage.bench run``)."""
    log: str
    """The Inspect log file name."""


class PriceTable(BaseModel):
    """Frozen prices in USD per million tokens. A run names the table it was costed with."""

    model_config = ConfigDict(extra="forbid")

    id: str
    note: str = ""
    models: dict[str, dict[str, float | str]]
    """``model -> {"input", "output", "cache_read", "cache_write"}``, plus ``"local": "yes"``
    for a model served on our own hardware."""

    @classmethod
    def load(cls, path: Path) -> PriceTable:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def price(self, model: str) -> dict[str, float] | None:
        entry = self.models.get(model) or next(
            (v for k, v in self.models.items() if k.rsplit("/", 1)[-1] == model.rsplit("/", 1)[-1]),
            None,
        )
        if entry is None:
            return None
        return {k: float(v) for k, v in entry.items() if k != "local"}


def bootstrap(
    values: Sequence[float | None],
    clusters: Sequence[str],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = 0,
) -> Estimate:
    """Mean of the defined values, with a 95% percentile interval from resampling clusters."""
    by_cluster: dict[str, list[float]] = defaultdict(list)
    for v, c in zip(values, clusters, strict=True):
        if v is not None:
            by_cluster[c].append(float(v))
    flat = [v for vs in by_cluster.values() for v in vs]
    if not flat:
        return Estimate(mean=None, ci_low=None, ci_high=None, n=0)
    mean = sum(flat) / len(flat)
    keys = sorted(by_cluster)
    rng = random.Random(seed)  # noqa: S311  (resampling, not a secret)
    stats: list[float] = []
    for _ in range(resamples):
        total = count = 0.0
        for k in rng.choices(keys, k=len(keys)):
            total += sum(by_cluster[k])
            count += len(by_cluster[k])
        stats.append(total / count)
    stats.sort()
    return Estimate(
        mean=mean,
        ci_low=stats[int(0.025 * (len(stats) - 1))],
        ci_high=stats[int(0.975 * (len(stats) - 1))],
        n=len(flat),
    )


def _ratio_bootstrap(
    cost: Sequence[float], correct: Sequence[float], clusters: Sequence[str], seed: int = 0
) -> Estimate:
    by_cluster: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for c, k, cl in zip(cost, correct, clusters, strict=True):
        by_cluster[cl].append((c, k))
    total_correct = sum(correct)
    if not total_correct:
        return Estimate(mean=None, ci_low=None, ci_high=None, n=len(cost))
    keys = sorted(by_cluster)
    rng = random.Random(seed)  # noqa: S311  (resampling, not a secret)
    stats: list[float] = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        c_sum = k_sum = 0.0
        for key in rng.choices(keys, k=len(keys)):
            c_sum += sum(c for c, _ in by_cluster[key])
            k_sum += sum(k for _, k in by_cluster[key])
        stats.append(c_sum / k_sum if k_sum else float("inf"))
    stats.sort()
    return Estimate(
        mean=sum(cost) / total_correct,
        ci_low=stats[int(0.025 * (len(stats) - 1))],
        ci_high=stats[int(0.975 * (len(stats) - 1))],
        n=len(cost),
    )


def _text(result: Any) -> str:
    """A tool result as the text the model read."""
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        return "\n".join(str(getattr(c, "text", "") or "") for c in result)  # type: ignore[union-attr]
    return str(getattr(result, "text", result))


def _values(score: Any) -> dict[str, Any]:
    value: object = getattr(score, "value", None)
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _ms(later: datetime | None, earlier: datetime) -> int:
    return 0 if later is None else max(0, int((later - earlier).total_seconds() * 1000))


def _trace(
    sample: Any, log: Any, config: dict[str, Any], usage: Usage, question: Question
) -> Trace:

    started = sample.events[0].timestamp if sample.events else datetime.now()
    events: list[Any] = []
    for ev in sample.events:
        if not isinstance(ev, InspectToolEvent) or ev.function == "submit":
            continue
        result = _text(ev.result)
        events.append(
            tool_event(
                seq=len(events),
                call_id=ev.id,
                tool=ev.function,
                args=dict(ev.arguments),
                result=result,
                error=ev.error.message if ev.error else None,
                t_ms=_ms(ev.timestamp, started),
                latency_ms=_ms(ev.completed, ev.timestamp) if ev.completed else None,
            )
        )
    score = next(iter(sample.scores.values())) if sample.scores else None
    answer_text = (score.answer if score else None) or (
        sample.output.completion if sample.output else ""
    )
    end_ms = _ms(sample.events[-1].timestamp, started) if sample.events else 0
    events.append(AnswerEvent(seq=len(events), t_ms=end_ms, delta=answer_text))
    meta: dict[str, Any] = (score.metadata or {}) if score else {}
    citations = [AnswerCitation.model_validate(c) for c in meta.get("citations", [])]
    for c in citations:
        events.append(
            CiteEvent(seq=len(events), t_ms=end_ms, cite_id=c.cite_id, cite=c.cite, quote=c.quote)
        )
    for v in meta.get("verify", []):
        verify = VerifyEvent.model_validate(v)
        events.append(verify.model_copy(update={"seq": len(events), "t_ms": end_ms}))
    values = _values(score)
    return Trace(
        header=TraceHeader(
            trace_id=f"{log.eval.run_id}-{sample.id}-{sample.epoch}",
            run_id=log.eval.run_id,
            sample_id=str(sample.id),
            question=question.question,
            model=log.eval.model,
            solver=str(config.get("solver", "react-baseline@1")),
            surface_id=str(config.get("surface", "default")),
            snapshot=str(config.get("corpus", "fixtures")),
            arm=str(config.get("arm", "default")),
            server_version=str(config.get("server_version", "unknown")),
            started_at=started.isoformat(),
            usage=usage,
        ),
        events=events,
        answer=Answer(text=answer_text, citations=citations),
        scores={k: float(v) for k, v in values.items() if isinstance(v, int | float)},
    )


def _estimates(
    rows: list[dict[str, Any]], key: str | None = None
) -> dict[str, dict[str, Estimate]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[r[key] if key else "all"].append(r)
    return {
        g: {
            m: bootstrap([r["scores"].get(m) for r in rs], [r["cluster"] for r in rs])
            for m in MEASURES
        }
        for g, rs in groups.items()
    }


def write_run(
    log_path: Path,
    out: Path,
    *,
    config: dict[str, Any],
    prices: PriceTable | None,
    agreements: dict[str, Any] | None = None,
) -> Path:
    """Write the results file and the traces for one Inspect log. Returns the results path."""

    log = read_eval_log(str(log_path), resolve_attachments=True)
    run_id = log.eval.run_id
    model = log.eval.model
    trace_dir = out / "traces" / run_id
    trace_dir.mkdir(parents=True, exist_ok=True)

    price = prices.price(model) if prices else None
    rows: list[dict[str, Any]] = []
    judge_id: str | None = None
    for sample in log.samples or []:
        question = Question.model_validate(sample.metadata["question"])
        u = sample.model_usage.get(model)
        tokens = {
            "input": u.input_tokens if u else 0,
            "output": u.output_tokens if u else 0,
            "cache_read": (u.input_tokens_cache_read or 0) if u else 0,
            "cache_write": (u.input_tokens_cache_write or 0) if u else 0,
        }
        cost = None
        if price is not None:
            cost = sum(tokens[k] * price.get(k, price.get("input", 0.0)) for k in tokens) / 1e6
        usage = Usage(
            input_tokens=tokens["input"],
            output_tokens=tokens["output"],
            cache_read_tokens=tokens["cache_read"],
            cost_usd=cost,
            price_table=prices.id if prices else None,
        )
        trace = _trace(sample, log, config, usage, question)
        (trace_dir / f"{sample.id}.{sample.epoch}.json").write_text(
            trace.model_dump_json(by_alias=True, exclude_none=True, indent=1), encoding="utf-8"
        )
        score = next(iter(sample.scores.values())) if sample.scores else None
        if score and score.metadata and score.metadata.get("judge"):
            judge_id = str(score.metadata["judge"])
        values = _values(score)
        rows.append(
            {
                "scores": {m: values.get(m) if not sample.error else 0.0 for m in MEASURES},
                "cluster": question.cluster,
                "method": question.made.method,
                "kind": question.kind,
                "correct": float(values.get("correct") or 0.0),
                "tokens": tokens,
                "error": sample.error is not None,
                "question_id": question.id,
            }
        )

    result = summarize(
        rows,
        run_id=run_id,
        created_at=log.eval.created,
        model=model,
        agent=f"inspect {config.get('solver', 'react-baseline@1')}",
        epochs=int(log.eval.config.epochs or 1),
        config=config,
        log=Path(log_path).name,
        prices=prices,
        judge=judge_id,
        agreements=agreements,
        billing="local" if model.startswith("openai-api/omlx/") else "api",
    )
    return write_result(result, out)


def write_result(result: RunResult, out: Path) -> Path:
    path = out / "results" / f"{result.run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(by_alias=True, indent=1), encoding="utf-8")
    return path


def summarize(
    rows: list[dict[str, Any]],
    *,
    run_id: str,
    created_at: str,
    model: str,
    agent: str,
    epochs: int,
    config: dict[str, Any],
    log: str,
    prices: PriceTable | None,
    judge: str | None,
    agreements: dict[str, Any] | None,
    billing: str,
    meter: dict[str, Any] | None = None,
    stopped: str | None = None,
    planned: int | None = None,
) -> RunResult:
    """A results file from per-sample rows: ``scores``, ``cluster``, ``method``, ``kind``,
    ``correct``, ``tokens`` (``input``, ``output``, ``cache_read``, ``cache_write``), ``error``,
    and optionally ``seconds`` and ``contaminated``."""
    price = prices.price(config.get("price_as", model)) if prices else None
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    costs: list[float] = []
    for r in rows:
        for k in totals:
            totals[k] += int(r["tokens"].get(k, 0))
        if price is not None:
            costs.append(
                sum(r["tokens"].get(k, 0) * price.get(k, price.get("input", 0.0)) for k in totals)
                / 1e6
            )
    clusters = [r["cluster"] for r in rows]
    total_usd = sum(costs) if price is not None else None
    per_correct = (
        _ratio_bootstrap(costs, [r["correct"] for r in rows], clusters)
        if price is not None and rows
        else Estimate(mean=None, ci_low=None, ci_high=None, n=len(rows))
    )
    qfile = Path(str(config.get("questions", "")))
    if not qfile.is_absolute():
        qfile = Path(__file__).resolve().parents[3] / qfile
    qhash = hashlib.sha256(qfile.read_bytes()).hexdigest() if qfile.is_file() else None
    judge_info = None
    if judge is not None:
        jid = make_judge_id(judge)
        judge_info = JudgeInfo(id=jid, agreement=(agreements or {}).get(jid))
    seconds = [float(r["seconds"]) for r in rows if r.get("seconds") is not None]
    return RunResult(
        run_id=run_id,
        name=str(config.get("name", run_id)),
        created_at=created_at,
        agent=agent,
        model=model,
        solver=str(config.get("solver", agent)),
        surface=str(config.get("surface", "default")),
        server=config.get("server"),
        snapshot=str(config.get("corpus", "fixtures")),
        questions={
            "file": str(config.get("questions", "")),
            "sha256": qhash,
            "n": len({r.get("question_id", i) for i, r in enumerate(rows)}),
        },
        epochs=epochs,
        samples=len(rows),
        planned_samples=planned if planned is not None else len(rows),
        complete=stopped is None,
        stopped=stopped,
        errors=sum(bool(r.get("error")) for r in rows),
        contaminated=sum(bool(r.get("contaminated")) for r in rows),
        seconds_per_sample=sum(seconds) / len(seconds) if seconds else None,
        judge=judge_info,
        measures=_estimates(rows)["all"] if rows else {},
        by_method=_estimates(rows, "method"),
        by_kind=_estimates(rows, "kind"),
        cost=Cost(
            billing=billing,  # type: ignore[arg-type]
            price_table=prices.id if prices else None,
            priced=price is not None,
            input_tokens=totals["input"],
            output_tokens=totals["output"],
            cache_read_tokens=totals["cache_read"],
            cache_write_tokens=totals["cache_write"],
            total_usd=total_usd,
            per_sample_usd=total_usd / len(rows) if total_usd is not None and rows else None,
            per_correct_usd=per_correct,
        ),
        meter=meter or {},
        config=config,
        log=log,
    )


def compare(a: Path, b: Path, measure: str = "correct") -> Estimate:
    """Paired difference ``b - a`` on one measure, over the questions both runs answered,
    clustered by cited document. Reads the traces each results file points at."""

    def per_question(results_path: Path) -> dict[str, tuple[str, float]]:
        run = RunResult.model_validate_json(results_path.read_text(encoding="utf-8"))
        out: dict[str, list[float]] = defaultdict(list)
        for f in (results_path.parent.parent / "traces" / run.run_id).glob("*.json"):
            t = Trace.model_validate_json(f.read_text(encoding="utf-8"))
            if measure in t.scores and t.header.sample_id:
                out[t.header.sample_id].append(t.scores[measure])
        return {k: ("", sum(v) / len(v)) for k, v in out.items()}

    left, right = per_question(a), per_question(b)
    shared = sorted(set(left) & set(right))
    diffs = [right[k][1] - left[k][1] for k in shared]
    return bootstrap(diffs, shared)


LEADERBOARD_METRICS = [
    ("correct", "Correct, fully cited", "deterministic"),
    ("verdict_correct", "Verdict right", "deterministic"),
    ("page_precision", "Page precision", "deterministic"),
    ("page_recall", "Page recall", "deterministic"),
    ("quote_fidelity", "Quote fidelity", "deterministic"),
    ("seen_rate", "Cited what it read", "deterministic"),
    ("support_rate", "Claim support", "judge"),
]


def publish(results: Sequence[Path], content: Path, *, version: str) -> Path:
    """Write the site's files from results files: ``leaderboard.json``
    (``onthepage.leaderboard/1``), ``runs/<run_id>.json`` (``onthepage.run/1``) and each run's
    traces under ``traces/``. Rows whose 95% intervals on ``correct`` overlap share a rank
    band."""
    runs = [RunResult.model_validate_json(p.read_text(encoding="utf-8")) for p in results]
    (content / "runs").mkdir(parents=True, exist_ok=True)
    (content / "traces").mkdir(parents=True, exist_ok=True)

    def ci(run: RunResult) -> tuple[float, float]:
        e = run.measures.get("correct")
        if e is None or e.ci_low is None or e.ci_high is None:
            return (0.0, 0.0)
        return (e.ci_low, e.ci_high)

    rows: list[dict[str, Any]] = []
    for run, path in zip(runs, results, strict=True):
        low, high = ci(run)
        band = [
            1 + sum(ci(o)[0] > high for o in runs),
            sum(ci(o)[1] >= low for o in runs),
        ]
        rows.append(
            {
                "agent": run.agent,
                "model": run.model,
                "billing": run.cost.billing,
                "solver": run.solver,
                "surface": run.surface,
                "run_id": run.run_id,
                "rank_band": band,
                "scores": {
                    key: {"value": e.mean, "ci": [e.ci_low, e.ci_high], "n": e.n}
                    for key, e in run.measures.items()
                },
                "cost_per_correct_usd": run.cost.per_correct_usd.mean,
            }
        )
        samples: list[dict[str, Any]] = []
        for f in sorted((path.parent.parent / "traces" / run.run_id).glob("*.json")):
            trace = Trace.model_validate_json(f.read_text(encoding="utf-8"))
            tally = {"verified": 0, "cited": 0, "rejected": 0}
            for c in trace.answer.citations if trace.answer else []:
                tally[c.state] += 1
            samples.append(
                {
                    "sample_id": trace.header.sample_id,
                    "trace_id": trace.header.trace_id,
                    "question": trace.header.question,
                    "tally": tally,
                }
            )
            (content / "traces" / f"{trace.header.trace_id}.json").write_text(
                f.read_text(encoding="utf-8"), encoding="utf-8"
            )
        (content / "runs" / f"{run.run_id}.json").write_text(
            json.dumps(
                {
                    "schema": "onthepage.run/1",
                    "sample": False,
                    "run_id": run.run_id,
                    "model": run.model,
                    "solver": run.solver,
                    "snapshot": run.snapshot,
                    "started_at": run.created_at,
                    "samples": samples,
                },
                indent=1,
            ),
            encoding="utf-8",
        )
    rows.sort(key=lambda r: r["rank_band"])
    judges = {r.judge.id: r.judge.agreement for r in runs if r.judge}
    board = {
        "schema": "onthepage.leaderboard/1",
        "sample": False,
        "benchmark": "PageCite",
        "version": version,
        "questions": max((r.questions.get("n", 0) for r in runs), default=0),
        "updated": max((r.created_at[:10] for r in runs), default=""),
        "snapshot": runs[0].snapshot if runs else "",
        "harness": "Inspect, onthepage.bench",
        "judge": (
            {"id": next(iter(judges)), "agreement": next(iter(judges.values()))}
            if len(judges) == 1
            else None
        ),
        "metrics": [
            {"key": k, "label": label, "source": source, "better": "higher", "unit": "%"}
            for k, label, source in LEADERBOARD_METRICS
        ],
        "rows": rows,
    }
    path = content / "leaderboard.json"
    path.write_text(json.dumps(board, indent=1), encoding="utf-8")
    return path
