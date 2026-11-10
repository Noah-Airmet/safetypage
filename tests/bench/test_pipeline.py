"""Question construction and the command line, with Inspect's mock model standing in for the
drafter and the checker."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from inspect_ai.model import ModelOutput, get_model

from safetypage.bench import __main__ as cli
from safetypage.bench.cli_run import _over  # pyright: ignore[reportPrivateUsage]
from safetypage.bench.draft import check_question, draft
from safetypage.bench.label import pairs_from_questions, pairs_from_traces, unit_text
from safetypage.bench.mine import Candidate, citing_contexts, pick, shared_sections, version_diffs
from safetypage.bench.questions import load_questions, save_questions
from safetypage.bench.task import open_corpus

POLY = "Neural networks often contain"


def _mock(*replies: str):  # type: ignore[no-untyped-def]
    return get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content("mockllm/model", r) for r in replies],
    )


def _polysemantic() -> Candidate:
    return next(
        c for c in citing_contexts(open_corpus("fixtures")) if "polysemantic" in c.source_text
    )


def test_draft_keeps_only_verified_gold() -> None:
    corpus = open_corpus("fixtures")
    good = corpus.read_units("distill:zoom-in/r1/b62")[0].text or ""
    quote = " ".join(good.split()[:12])
    reply = json.dumps(
        {
            "attributed": "neurons are often polysemantic",
            "verdict": "supported",
            "evidence": [
                {"cite": "distill:zoom-in/r1/b62", "quote": quote},
                {
                    "cite": "distill:zoom-in/r1/b63",
                    "quote": "a sentence that is not on that block at all",
                },
            ],
            "perturbed": "Using individual neurons has had some success, but nearly every neuron "
            "is polysemantic (Olah et al., 2020).",
            "change": "often -> nearly every",
        }
    )
    questions = asyncio.run(draft(corpus, _polysemantic(), _mock(reply)))
    assert [q.made.method for q in questions] == ["citing_sentence", "perturbed_claim"]
    real, perturbed = questions
    assert real.gold == ["distill:zoom-in/r1/b62"] == perturbed.gold
    assert real.expected == "supported" and perturbed.expected == "not_supported"
    assert [e["verdict"] for e in real.made.evidence][1] != "exact"
    assert real.check_level == "code"
    assert real.question.startswith("A document in the library")


def test_draft_drops_unverifiable_and_drafts_compare() -> None:
    corpus = open_corpus("fixtures")
    bad = json.dumps(
        {"verdict": "supported", "evidence": [{"cite": "x:y/r1/b1", "quote": "nothing"}]}
    )
    assert asyncio.run(draft(corpus, _polysemantic(), _mock(bad))) == []
    assert asyncio.run(draft(corpus, _polysemantic(), _mock("not json"))) == []
    [diff] = version_diffs(corpus)
    [q] = asyncio.run(draft(corpus, diff, _mock('{"question": "What changed?"}')))
    assert q.kind == "compare" and q.gold == ["arxiv:2305.15324/v2/p6", "arxiv:2305.15324/v1/p6"]


def test_check_question() -> None:
    corpus = open_corpus("fixtures")
    [diff] = version_diffs(corpus)
    [q] = asyncio.run(draft(corpus, diff, _mock('{"question": "What changed?"}')))
    ok = asyncio.run(check_question(corpus, q, _mock("Fine.\nOK: yes")))
    assert ok is not None and ok.level == "model"
    assert asyncio.run(check_question(corpus, q, _mock("No.\nOK: no"))) is None


def test_pairs_carry_no_document_text(tmp_path: Path) -> None:
    corpus = open_corpus("fixtures")
    [diff] = version_diffs(corpus)
    candidates = [_polysemantic(), diff]
    good = (corpus.read_units("distill:zoom-in/r1/b62")[0].text or "").split()[:12]
    reply = json.dumps(
        {
            "verdict": "supported",
            "evidence": [{"cite": "distill:zoom-in/r1/b62", "quote": " ".join(good)}],
        }
    )
    questions = asyncio.run(draft(corpus, candidates[0], _mock(reply)))
    pairs = pairs_from_questions(questions)
    assert pairs and set(pairs[0]) == {"pair_id", "claim", "cite", "source"}
    assert POLY in unit_text(corpus, pairs[0]["cite"])
    assert pairs_from_traces([]) == []


def test_cli_mine_split_schema_estimate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "candidates.jsonl"
    cli.main(["mine", "--out", str(out)])
    rows = [json.loads(x) for x in out.read_text().splitlines()]
    assert {r["method"] for r in rows} == {"citing_sentence", "version_diff"}
    assert Candidate.load(rows[0]).source_text == rows[0]["source_text"]

    dev, test = tmp_path / "dev.jsonl", tmp_path / "test.jsonl"
    cli.main(
        [
            "split",
            "--questions",
            str(cli.PC / "questions" / "fixtures.jsonl"),
            "--dev",
            str(dev),
            "--test",
            str(test),
        ]
    )
    assert len(load_questions(dev)) + len(load_questions(test)) == len(
        load_questions(cli.PC / "questions" / "fixtures.jsonl")
    )

    monkeypatch.setattr(cli, "REPO", tmp_path)
    cli.main(["schema"])
    assert (tmp_path / "schemas" / "citationbench" / "run-result.schema.json").is_file()

    results = sorted((cli.PC / "results").glob("*.json"))
    if results:
        cli.main(["estimate", str(results[-1]), "--questions", "10", "--epochs", "1"])
        assert "claude-sonnet-5-5" in capsys.readouterr().out


def test_vault_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CITATIONBENCH_TEST_SETTING", raising=False)
    cli._env_from_vault({"CITATIONBENCH_TEST_SETTING": "plain"})  # pyright: ignore[reportPrivateUsage]
    assert os.environ["CITATIONBENCH_TEST_SETTING"] == "plain"


def test_cli_draft_check_pairs_label_agreement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pc = tmp_path / "pc"
    (pc / "labels").mkdir(parents=True)
    monkeypatch.setattr(cli, "PC", pc)
    monkeypatch.setattr(cli, "AGREEMENT", pc / "labels" / "agreement.json")
    candidates, questions = tmp_path / "c.jsonl", tmp_path / "q.jsonl"
    cli.main(["mine", "--out", str(candidates)])
    # The mock model's default reply is not JSON, so nothing is drafted; the plumbing runs.
    cli.main(
        [
            "draft",
            "--candidates",
            str(candidates),
            "--model",
            "mockllm/model",
            "--out",
            str(questions),
        ]
    )
    assert load_questions(questions) == []

    dev = cli.REPO / "citationbench" / "questions" / "fixtures.jsonl"
    pairs = pc / "labels" / "pairs.jsonl"
    cli.main(["pairs", "--questions", str(dev), "--out", str(pairs), "--traces", str(tmp_path)])
    assert pairs.read_text().strip()

    answers = iter(["x", "s", "k", "u", "q"])

    def fake_input(_prompt: str) -> str:
        return next(answers)

    monkeypatch.setattr("builtins.input", fake_input)
    cli.main(["label", "--pairs", str(pairs), "--who", "test"])
    labelled = (pc / "labels" / "human-test.jsonl").read_text().splitlines()
    assert [json.loads(x)["label"] for x in labelled] == ["supported", "unsupported"]

    cli.main(["agreement", "--pairs", str(pairs), "--judge", "mockllm/model"])
    agreement = json.loads((pc / "labels" / "agreement.json").read_text())
    [entry] = agreement.values()
    assert entry["n"] == 2 and entry["judge"].startswith("mockllm/model#")


def test_cli_check_rejects_on_no(tmp_path: Path) -> None:
    path = tmp_path / "q.jsonl"
    path.write_text((cli.PC / "questions" / "fixtures.jsonl").read_text())
    qs = load_questions(path)
    for q in qs:
        q.checks = [c for c in q.checks if c.level != "model"]
    from_dev = len(qs)
    save_questions(path, qs)
    cli.main(["check", "--questions", str(path), "--model", "mockllm/model"])
    statuses = [q.status for q in load_questions(path)]
    assert statuses == ["rejected"] * from_dev


def test_pick_spreads_by_kind() -> None:
    corpus = open_corpus("fixtures")
    found = citing_contexts(corpus) + version_diffs(corpus) + shared_sections(corpus)
    chosen = pick(corpus, found, {"citing_sentence/paper": 1, "version_diff": 5})
    assert [c.method for c in chosen].count("citing_sentence") <= 1
    assert all(c.method in ("citing_sentence", "version_diff") for c in chosen)
    assert chosen == pick(corpus, found, {"citing_sentence/paper": 1, "version_diff": 5})


def test_usage_ceiling_per_window() -> None:
    meter = {"five_hour_used": 0.5, "seven_day_used": 0.5}
    assert _over(meter, 0.6) is None
    assert _over(meter, {"five_hour": 0.6, "seven_day": 0.45}) is not None
    assert _over(meter, {"five_hour": 0.4}) is not None
