"""PageCite command line. ``uv run --group bench python -m onthepage.bench <command> --help``.

Questions:  mine -> draft -> check -> split
Runs:       run <config.toml>  (eval, then results + traces)   |  results <log>  |  compare a b
Judge:      pairs -> label -> agreement
Planning:   estimate (cost of a full run per model, from a smoke run)
Contracts:  schema (writes schemas/pagecite/)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tomllib
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from inspect_ai import eval as inspect_eval  # pyright: ignore[reportUnknownVariableType]

from .agents import AGENTS
from .cli_run import rescore, run_cli
from .draft import check_question, draft
from .judge import agreement, judge_id, load_agreements, make_judge
from .label import label_loop, pairs_from_questions, pairs_from_traces, read_jsonl, unit_text
from .mine import Candidate, citing_contexts, shared_sections, version_diffs
from .nightly import nightly
from .questions import Question, assign_split, load_questions, save_questions
from .results import PriceTable, RunResult, compare, publish, write_run
from .task import open_corpus, pagecite

REPO = Path(__file__).resolve().parents[3]
PC = REPO / "pagecite"
PRICES = PC / "prices" / "2026-11.json"
AGREEMENT = PC / "labels" / "agreement.json"


def _corpus(name: str) -> Any:
    return open_corpus(name)


def _env_from_vault(mapping: dict[str, str]) -> None:
    """Fill unset environment variables from 1Password references (``op://...``) through
    ``agent-op``. Values go into this process's environment only."""
    for var, ref in mapping.items():
        if os.environ.get(var):
            continue
        if not ref.startswith("op://"):
            os.environ[var] = ref  # a plain value, not a secret
            continue
        if not shutil.which("agent-op"):  # pragma: no cover
            sys.exit(f"{var} is not set and agent-op is not available to read {ref}")
        agent_op = shutil.which("agent-op")
        value = subprocess.run(  # noqa: S603
            [agent_op or "agent-op", "read", ref],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        os.environ[var] = value


def keys_for(*models: str | None, vault: bool | list[str] = False) -> None:
    """Read API keys from the vault, only when asked to (``--vault``, or ``vault = [...]`` in a
    run configuration). API keys are never the default: subscription CLIs are."""
    if not vault:
        return
    prefixes = {"anthropic/": "anthropic", "openai/azure/": "azure", "openai-api/omlx/": "omlx"}
    sections = {s for m in models if m for p, s in prefixes.items() if m.startswith(p)}
    if isinstance(vault, list):
        sections &= set(vault)
    if not sections:
        return
    local = PC / "vault.local.toml"
    if not local.is_file():
        sys.exit(
            f"API keys for {sorted(sections)} were asked for from the vault, but {local} does not "
            "exist. Set the environment variables, or copy vault.example.toml to it."
        )
    refs = tomllib.loads(local.read_text(encoding="utf-8"))
    for section in sorted(sections):
        _env_from_vault(refs[section])


# ----------------------------------------------------------------------------- questions


def cmd_mine(a: argparse.Namespace) -> None:

    corpus = _corpus(a.corpus)
    found = citing_contexts(corpus) + version_diffs(corpus) + shared_sections(corpus)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(c.as_dict()) + "\n" for c in found), encoding="utf-8")
    print(f"{len(found)} candidates -> {out}", dict(Counter(c.method for c in found)))


def cmd_draft(a: argparse.Namespace) -> None:

    keys_for(a.model, vault=a.vault)
    corpus = _corpus(a.corpus)
    rows = [json.loads(x) for x in Path(a.candidates).read_text().splitlines() if x.strip()]
    candidates = [Candidate.load(r) for r in rows][: a.limit or None]

    async def go() -> list[Question]:
        sem = asyncio.Semaphore(a.concurrency)

        async def one(c: Candidate) -> list[Question]:
            async with sem:
                return await draft(corpus, c, a.model)

        return [q for qs in await asyncio.gather(*(one(c) for c in candidates)) for q in qs]

    questions = asyncio.run(go())
    existing = load_questions(Path(a.out)) if Path(a.out).is_file() else []
    merged = {q.id: q for q in existing} | {q.id: q for q in questions}
    n = save_questions(Path(a.out), merged.values())
    print(f"{len(questions)} drafted from {len(candidates)} candidates; {n} in {a.out}")


def cmd_check(a: argparse.Namespace) -> None:

    keys_for(a.model, vault=a.vault)
    corpus = _corpus(a.corpus)
    path = Path(a.questions)
    questions = load_questions(path)

    async def go() -> None:
        for q in questions:
            if q.status != "draft" or any(c.level == "model" for c in q.checks):
                continue
            check = await check_question(corpus, q, a.model)
            if check is None:
                q.status = "rejected"
            else:
                q.checks.append(check)

    asyncio.run(go())
    save_questions(path, questions)
    print(dict(Counter(f"{q.status}/{q.check_level}" for q in questions)))


def cmd_split(a: argparse.Namespace) -> None:
    questions = [q for q in load_questions(Path(a.questions)) if q.status != "rejected"]
    for q in questions:
        q.split = assign_split(q.cluster, test_share=a.test_share)
    dev = [q for q in questions if q.split == "dev"]
    test = [q for q in questions if q.split == "test"]
    save_questions(Path(a.dev), dev)
    save_questions(Path(a.test), test)
    print(f"dev {len(dev)} -> {a.dev}; test {len(test)} -> {a.test} (held out, not committed)")


# ----------------------------------------------------------------------------- runs


def load_config(path: Path) -> dict[str, Any]:
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    config.setdefault("name", path.stem)
    return config


def cmd_run(a: argparse.Namespace) -> None:

    config = load_config(Path(a.config))
    if config.get("agent") in (*AGENTS, "inspect"):
        keys_for(config["model"], config.get("judge"), vault=config.get("vault", False))
        outcome = run_cli(config, batch=a.batch or None, until=_until(a.until))
        print(json.dumps(outcome.__dict__, default=str, indent=1))
        if outcome.stopped and outcome.done < outcome.planned:
            sys.exit(3)
        return
    keys_for(config["model"], config.get("judge"), vault=config.get("vault", False))
    task = pagecite(
        questions=config.get("questions", "pagecite/questions/dev.jsonl"),
        corpus=config.get("corpus", "fixtures"),
        server=config.get("server", "http://localhost:8000"),
        surface=config.get("surface", "default"),
        judge=config.get("judge"),
        message_limit=int(config.get("message_limit", 40)),
    )
    [log] = inspect_eval(
        task,
        model=config["model"],
        epochs=int(config.get("epochs", 1)),
        limit=a.limit or config.get("limit"),
        log_dir=str(PC / "logs"),
        max_connections=int(config.get("max_connections", 4)),
        **config.get("generate", {}),
    )
    if log.status != "success":
        sys.exit(f"run failed: {log.error}")
    out = write_run(
        Path(log.location),
        PC,
        config=config,
        prices=PriceTable.load(PRICES),
        agreements=load_agreements(AGREEMENT),
    )
    print(out)


def _until(text: str | None) -> datetime | None:
    if not text:
        return None
    hour, minute = (int(x) for x in text.split(":"))
    now = datetime.now().astimezone()
    end = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return end if end > now else end + timedelta(days=1)


def cmd_rescore(a: argparse.Namespace) -> None:
    config = load_config(Path(a.config))
    keys_for(config.get("judge"), vault=config.get("vault", False))
    print(rescore(config))


def cmd_nightly(a: argparse.Namespace) -> None:
    names = [
        line.strip()
        for line in (PC / "configs" / "nightly.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    configs = [load_config(PC / "configs" / name) for name in names]
    keys_for(*(c["model"] for c in configs), vault=["omlx"])
    until = _until(a.until) or datetime.now().astimezone()
    sys.exit(nightly(configs, until=until, dry_run=a.dry_run))


def cmd_results(a: argparse.Namespace) -> None:

    config = load_config(Path(a.config)) if a.config else {}
    print(
        write_run(
            Path(a.log),
            PC,
            config=config,
            prices=PriceTable.load(PRICES),
            agreements=load_agreements(AGREEMENT),
        )
    )


def cmd_compare(a: argparse.Namespace) -> None:

    est = compare(Path(a.a), Path(a.b), a.measure)
    print(json.dumps(est.model_dump(), indent=1))


def cmd_publish(a: argparse.Namespace) -> None:
    files = [Path(f) for f in a.results] or sorted((PC / "results").glob("*.json"))
    print(publish(files, Path(a.content), version=a.version))


def cmd_estimate(a: argparse.Namespace) -> None:
    """Cost of a full run for every priced model, scaling a smoke run's tokens per sample."""

    run = RunResult.model_validate_json(Path(a.results).read_text())
    table = PriceTable.load(PRICES)
    per = {
        "input": run.cost.input_tokens / run.samples,
        "output": run.cost.output_tokens / run.samples,
        "cache_read": run.cost.cache_read_tokens / run.samples,
        "cache_write": run.cost.cache_write_tokens / run.samples,
    }
    n = a.questions * a.epochs
    print(
        f"from {run.model}, {run.samples} samples: tokens/sample "
        + json.dumps({k: round(v) for k, v in per.items()})
    )
    print(f"full run = {a.questions} questions x {a.epochs} epochs")
    print("token use is assumed the same for every model\n")
    for model, entry in table.models.items():
        price = table.price(model) or {}
        usd = sum(per[k] * price.get(k, price.get("input", 0.0)) for k in per) / 1e6
        tag = " (local)" if entry.get("local") else ""
        print(f"  {model:42s} ${usd:7.4f}/sample  ${usd * n:9.2f}/run{tag}")


# ----------------------------------------------------------------------------- judge


def cmd_pairs(a: argparse.Namespace) -> None:

    pairs = pairs_from_questions(q for path in a.questions for q in load_questions(Path(path)))
    if a.traces:
        pairs += pairs_from_traces(Path(a.traces).rglob("*.json"))
    out = Path(a.out)
    have = {p["pair_id"]: p for p in read_jsonl(out)}
    for p in pairs:
        have.setdefault(p["pair_id"], p)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(p) + "\n" for p in have.values()), encoding="utf-8")
    print(f"{len(have)} pairs in {out}")


def cmd_label(a: argparse.Namespace) -> None:

    pairs = read_jsonl(Path(a.pairs))
    out = PC / "labels" / f"human-{a.who}.jsonl"
    n = label_loop(_corpus(a.corpus), pairs, out, a.who)
    print(f"{n} labelled this session -> {out}")


def cmd_agreement(a: argparse.Namespace) -> None:

    keys_for(a.judge, vault=a.vault)
    corpus = _corpus(a.corpus)
    pairs = {p["pair_id"]: p for p in read_jsonl(Path(a.pairs))}
    human: dict[str, str] = {}
    for f in sorted((PC / "labels").glob("human-*.jsonl")):
        for r in read_jsonl(f):
            human.setdefault(r["pair_id"], r["label"])  # first labeller's label is the reference
    jid = judge_id(a.judge)
    judged_path = PC / "labels" / f"judge-{jid.replace('/', '_').replace('#', '@')}.jsonl"
    judged = {r["pair_id"]: r["label"] for r in read_jsonl(judged_path)}
    judge = make_judge(a.judge)

    async def go() -> None:
        with judged_path.open("a", encoding="utf-8") as f:
            for pid in human:
                if pid in judged or pid not in pairs:
                    continue
                p = pairs[pid]
                j = await judge(p["claim"], p["cite"], unit_text(corpus, p["cite"]))
                judged[pid] = j.label
                f.write(json.dumps({"pair_id": pid, "label": j.label, "judge": jid}) + "\n")

    asyncio.run(go())
    result = agreement(((human[p], judged[p]) for p in human if p in judged), jid)
    all_ = load_agreements(AGREEMENT)
    all_[jid] = result
    AGREEMENT.write_text(json.dumps(all_, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))


def cmd_schema(_: argparse.Namespace) -> None:

    out = REPO / "schemas" / "pagecite"
    out.mkdir(parents=True, exist_ok=True)
    for name, model in {"run-result": RunResult, "question": Question}.items():
        schema = model.model_json_schema(by_alias=True)
        (out / f"{name}.schema.json").write_text(
            json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(out)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        prog="python -m onthepage.bench",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(required=True)
    corpus_help = "fixtures, a snapshot directory, or a corpus.sqlite"

    s = sub.add_parser("mine", help="find question candidates in the corpus")
    s.add_argument("--corpus", default="fixtures", help=corpus_help)
    s.add_argument("--out", default=str(PC / "work" / "candidates.jsonl"))
    s.set_defaults(fn=cmd_mine)

    s = sub.add_parser(
        "draft", help="draft questions from candidates with a model; code checks gold"
    )
    s.add_argument("--corpus", default="fixtures", help=corpus_help)
    s.add_argument("--candidates", default=str(PC / "work" / "candidates.jsonl"))
    s.add_argument("--model", default="claude-code:claude-opus-5-5")
    s.add_argument("--vault", action="store_true", help="read API keys from the vault")
    s.add_argument("--out", default=str(PC / "work" / "questions.jsonl"))
    s.add_argument("--limit", type=int, default=0)
    s.add_argument("--concurrency", type=int, default=4)
    s.set_defaults(fn=cmd_draft)

    s = sub.add_parser("check", help="a second model from another family checks each draft")
    s.add_argument("--corpus", default="fixtures", help=corpus_help)
    s.add_argument("--questions", default=str(PC / "work" / "questions.jsonl"))
    s.add_argument("--model", default="codex:gpt-6-luna")
    s.add_argument("--vault", action="store_true", help="read API keys from the vault")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("split", help="assign dev/test by cited document and write both files")
    s.add_argument("--questions", default=str(PC / "work" / "questions.jsonl"))
    s.add_argument("--dev", default=str(PC / "questions" / "dev.jsonl"))
    s.add_argument("--test", default=str(PC / "heldout" / "test.jsonl"))
    s.add_argument("--test-share", type=float, default=0.5)
    s.set_defaults(fn=cmd_split)

    s = sub.add_parser("run", help="run a configuration, write results and traces")
    s.add_argument("config")
    s.add_argument("--limit", type=int, default=0, help="Inspect runs: at most this many samples")
    s.add_argument("--batch", type=int, default=0, help="CLI runs: samples in this batch")
    s.add_argument("--until", default=None, help="CLI runs: stop before HH:MM local time")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("rescore", help="score a CLI run's saved answers again (no agent runs)")
    s.add_argument("config")
    s.set_defaults(fn=cmd_rescore)

    s = sub.add_parser("nightly", help="the overnight local-model run (configs/nightly.txt)")
    s.add_argument("--until", default="06:25", help="stop before HH:MM local time")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_nightly)

    s = sub.add_parser("results", help="(re)write results and traces from an Inspect log")
    s.add_argument("log")
    s.add_argument("--config")
    s.set_defaults(fn=cmd_results)

    s = sub.add_parser("compare", help="paired difference between two runs (b - a)")
    s.add_argument("a")
    s.add_argument("b")
    s.add_argument("--measure", default="correct")
    s.set_defaults(fn=cmd_compare)

    s = sub.add_parser("publish", help="write the site's leaderboard, runs and traces")
    s.add_argument("results", nargs="*", help="results files (default: all in pagecite/results)")
    s.add_argument("--content", default=str(REPO / "site" / "src" / "content"))
    s.add_argument("--version", default="dev")
    s.set_defaults(fn=cmd_publish)

    s = sub.add_parser("estimate", help="cost of a full run per model, from a smoke run")
    s.add_argument("results")
    s.add_argument("--questions", type=int, default=300)
    s.add_argument("--epochs", type=int, default=3)
    s.set_defaults(fn=cmd_estimate)

    s = sub.add_parser("pairs", help="collect claim-citation pairs for human labels")
    s.add_argument("--questions", nargs="*", default=[str(PC / "questions" / "dev.jsonl")])
    s.add_argument("--traces", default=None)
    s.add_argument("--out", default=str(PC / "labels" / "pairs.jsonl"))
    s.set_defaults(fn=cmd_pairs)

    s = sub.add_parser("label", help="label pairs in the terminal (blind to the judge)")
    s.add_argument("--corpus", default="fixtures", help=corpus_help)
    s.add_argument("--pairs", default=str(PC / "labels" / "pairs.jsonl"))
    s.add_argument("--who", required=True)
    s.set_defaults(fn=cmd_label)

    s = sub.add_parser("agreement", help="run a judge on the labelled pairs and measure agreement")
    s.add_argument("--corpus", default="fixtures", help=corpus_help)
    s.add_argument("--pairs", default=str(PC / "labels" / "pairs.jsonl"))
    s.add_argument("--judge", default="claude-code:claude-sonnet-5-5")
    s.add_argument("--vault", action="store_true", help="read API keys from the vault")
    s.set_defaults(fn=cmd_agreement)

    s = sub.add_parser("schema", help="write schemas/pagecite/*.schema.json")
    s.set_defaults(fn=cmd_schema)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
