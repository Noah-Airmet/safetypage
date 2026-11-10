"""The task end to end on Inspect's mock model, with in-process stand-ins for the MCP tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai import eval as inspect_eval  # pyright: ignore[reportUnknownVariableType]
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.tool import Tool, tool

from safetypage.bench import __main__ as cli
from safetypage.bench import results
from safetypage.bench.questions import Made, Question, save_questions
from safetypage.bench.task import citationbench, open_corpus

GOLD = "arxiv:2305.15324/v2/p6"


@tool
def fetch() -> Tool:
    async def execute(id: str) -> str:
        """Read a page.

        Args:
            id: A cite string.
        """
        units = open_corpus("fixtures").read_units(id)
        return "\n\n".join(f"## {u.cite}\n{u.text}" for u in units)

    return execute


def _question(tmp_path: Path) -> Path:
    q = Question(
        id="pc-test000001",
        kind="claim",
        question="A paper says model evaluation is the only tool for AI risk assessment. "
        "Does the cited source support that?",
        expected="not_supported",
        gold=[GOLD],
        cluster="arxiv:2305.15324",
        split="dev",
        made=Made(method="perturbed_claim", source_cite=GOLD),
    )
    path = tmp_path / "q.jsonl"
    save_questions(path, [q])
    return path


def test_task_scores_a_mock_run(tmp_path: Path) -> None:
    answer = (
        'Verdict: not supported\n\nThe paper says "Model evaluation is not the only tool '
        f'available for AI risk assessment" {GOLD}.'
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call("mockllm/model", "fetch", {"id": GOLD}),
            ModelOutput.for_tool_call("mockllm/model", "submit", {"answer": answer}),
        ],
    )
    task = citationbench(questions=str(_question(tmp_path)), tools=[fetch()])
    [log] = inspect_eval(task, model=model, log_dir=str(tmp_path / "logs"), display="none")
    assert log.status == "success", log.error
    assert log.samples is not None
    value = log.samples[0].scores["citationbench_scorer"].value  # type: ignore[index]
    assert isinstance(value, dict)
    assert value["correct"] == 1.0
    assert value["page_precision"] == 1.0
    assert value["quote_fidelity"] == 1.0
    assert value["seen_rate"] == 1.0

    out = results.write_run(
        Path(log.location), tmp_path / "out", config={"name": "mock"}, prices=None
    )
    data = json.loads(out.read_text())
    assert data["measures"]["correct"]["mean"] == 1.0
    traces = list((tmp_path / "out" / "traces").rglob("*.json"))
    assert len(traces) == 1
    trace = json.loads(traces[0].read_text())
    kinds = [e["kind"] for e in trace["events"]]
    assert kinds[0] == "tool" and "verify" in kinds
    assert trace["answer"]["citations"][0]["state"] == "verified"

    results_file = out
    cli.main(["compare", str(results_file), str(results_file)])
    board = results.publish([out], tmp_path / "site", version="test")
    data = json.loads(board.read_text())
    assert data["schema"] == "safetypage.leaderboard/1" and data["rows"][0]["rank_band"] == [1, 1]
    run = json.loads((tmp_path / "site" / "runs" / f"{data['rows'][0]['run_id']}.json").read_text())
    assert run["samples"][0]["tally"]["verified"] == 1
