"""The CLI runners, with fake agent binaries, and the per-question runner's resume and stops."""

from __future__ import annotations

import json
import sqlite3
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from safetypage.bench import agents, cli_run
from safetypage.bench.agents import AgentRun, UsageLimitError, complete, is_cli_model, run_agent
from safetypage.migrate import migrate

GOLD = "arxiv:2305.15324/v2/p6"
ANSWER = (
    'Verdict: not supported\n\nThe paper says "Model evaluation is not the only tool '
    f'available for AI risk assessment" {GOLD}.'
)


def _fake(tmp_path: Path, name: str, lines: list[dict[str, Any]], code: int = 0) -> str:
    out = tmp_path / f"{name}.out"
    out.write_text("".join(json.dumps(x) + "\n" for x in lines))
    script = tmp_path / name
    script.write_text(
        f"#!/bin/sh\ncase \"$1\" in --version) echo '{name} 1.0';; *) cat {out}; exit {code};; esac\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


@pytest.fixture(autouse=True)
def _work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agents, "WORK", tmp_path / "work")


def test_claude_code_parse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "mcp__safetypage__search"}]},
        },
        {
            "type": "rate_limit_event",
            "rate_limit_info": {
                "status": "allowed",
                "unifiedWindows": {"five_hour": {"utilization": 0.2}},
            },
        },
        {
            "type": "result",
            "result": ANSWER,
            "total_cost_usd": 0.01,
            "usage": {
                "input_tokens": 3,
                "output_tokens": 50,
                "cache_read_input_tokens": 900,
                "cache_creation_input_tokens": 100,
                "output_tokens_details": {"thinking_tokens": 7},
            },
        },
    ]
    monkeypatch.setattr(agents, "CLAUDE_BIN", _fake(tmp_path, "claude", lines))
    run = run_agent(
        "claude-code", "claude-haiku-5-5", "q", mcp_url="http://x/mcp", headers={"A": "b"}
    )
    assert run.answer == ANSWER and run.off_library == []
    assert run.usage == {
        "input": 3,
        "output": 50,
        "cache_read": 900,
        "cache_write": 100,
        "reasoning": 7,
    }
    assert run.meter["five_hour_used"] == 0.2 and run.notional_usd == 0.01
    assert run.agent_version.startswith("claude-code")


def test_claude_code_limit_stops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [
        {"type": "rate_limit_event", "rate_limit_info": {"status": "rejected"}},
        {"type": "result", "result": "", "is_error": True},
    ]
    monkeypatch.setattr(agents, "CLAUDE_BIN", _fake(tmp_path, "claude", lines))
    with pytest.raises(UsageLimitError):
        run_agent("claude-code", "m", "q", mcp_url=None)


def test_codex_parse_and_meter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [
        {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "safetypage"}},
        {"type": "item.completed", "item": {"type": "web_search"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": ANSWER}},
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 100, "cached_input_tokens": 60, "output_tokens": 9},
        },
    ]
    monkeypatch.setattr(agents, "CODEX_BIN", _fake(tmp_path, "codex", lines))
    monkeypatch.setattr(agents.Path, "home", lambda: tmp_path)
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "auth.json").write_text("{}")
    session = tmp_path / "work" / "codex-home" / "sessions" / "s.jsonl"
    session.parent.mkdir(parents=True)
    limits = {
        "primary": {"used_percent": 4.0, "window_minutes": 300},
        "secondary": {"used_percent": 21.0, "window_minutes": 10080},
    }
    session.write_text(json.dumps({"payload": {"rate_limits": limits}}) + "\n")
    run = run_agent("codex", "gpt-6-luna", "q", mcp_url="http://x/mcp", headers={"A": "b"})
    assert run.answer == ANSWER and run.off_library == ["web_search"]
    assert run.usage["input"] == 40 and run.usage["cache_read"] == 60
    assert run.meter == {"five_hour_used": 0.04, "seven_day_used": 0.21}
    assert (tmp_path / "work" / "codex-home" / "auth.json").is_symlink()


def test_antigravity_marks_web_search(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [
        {
            "event": "step_update",
            "step_update": {
                "step_index": 1,
                "step_type": "tool",
                "state": "ACTIVE",
                "tool_name": "search_web",
            },
        },
        {
            "event": "step_update",
            "step_update": {
                "step_index": 1,
                "step_type": "tool",
                "state": "DONE",
                "tool_name": "search_web",
            },
        },
        {
            "event": "step_update",
            "step_update": {
                "step_index": 2,
                "step_type": "tool",
                "state": "ACTIVE",
                "tool_name": "read_file",
            },
        },
        {
            "event": "step_update",
            "step_update": {
                "step_index": 2,
                "step_type": "tool",
                "state": "ERROR",
                "tool_name": "read_file",
            },
        },
        {
            "event": "step_update",
            "step_update": {
                "step_index": 3,
                "step_type": "tool",
                "state": "DONE",
                "tool_name": "call_mcp_tool",
            },
        },
        {
            "event": "step_update",
            "step_update": {
                "state": "DONE",
                "usage": {"input_tokens": 10, "output_tokens": 2, "cache_read_tokens": 4},
            },
        },
        {"event": "result", "result": {"status": "SUCCESS", "response": "hi"}},
    ]
    monkeypatch.setattr(agents, "AGY_BIN", _fake(tmp_path, "agy", lines))
    monkeypatch.setattr(agents.Path, "home", lambda: tmp_path)
    run = run_agent("antigravity", "gemini-3.8-flash-low", "q", mcp_url="http://x/mcp", headers={})
    assert run.off_library == ["search_web"] and run.usage["input"] == 10
    assert complete("antigravity:gemini", "q") == "hi"
    assert is_cli_model("codex:x") and not is_cli_model("anthropic/claude-haiku-5-5")


def _ops(path: Path, run_id: str, sample: str) -> None:
    conn = sqlite3.connect(path)
    migrate(conn, "ops")
    conn.execute(
        "INSERT INTO tool_calls (request_id, ts, surface_id, snapshot, arm, server_version, tool, "
        "run_id, sample_id, args, returned) VALUES (?, ?, 'default@abc', 'fixtures', 'bm25', "
        "'0.1.0', ?, ?, ?, '{}', ?)",
        (
            f"{run_id}-{sample}-1",
            datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fetch",
            run_id,
            sample,
            json.dumps([GOLD]),
        ),
    )
    conn.execute(
        "INSERT INTO tool_calls (request_id, ts, surface_id, snapshot, arm, server_version, tool, "
        "run_id, sample_id, args, returned) VALUES (?, ?, 'default@abc', 'fixtures', 'bm25', "
        "'0.1.0', 'check_answer', ?, ?, '{}', ?)",
        (
            f"{run_id}-{sample}-2",
            datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            run_id,
            sample,
            json.dumps(["arxiv:2305.15324/v2/p9"]),
        ),
    )
    conn.commit()
    conn.close()


def test_runner_scores_from_the_call_log_resumes_and_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pc = tmp_path / "pc"
    monkeypatch.setattr(cli_run, "PC", pc)
    questions = cli_run.REPO / "citationbench" / "questions" / "dev.jsonl"
    ops = tmp_path / "ops.sqlite"
    config = {
        "name": "t",
        "agent": "claude-code",
        "model": "claude-haiku-5-5",
        "questions": str(questions),
        "ops_db": str(ops),
        "pause": 0,
    }
    run_id = cli_run.run_id_for(config)
    calls: list[str] = []

    def fake_run(agent: str, model: str, prompt: str, **kw: Any) -> AgentRun:
        sample = kw["headers"]["X-SafetyPage-Sample"]
        calls.append(sample)
        _ops(ops, kw["headers"]["X-SafetyPage-Run"], sample)
        return AgentRun(
            answer=ANSWER,
            usage={"input": 1, "output": 2},
            seconds=1.0,
            meter={"five_hour_used": 0.1},
            agent_version="claude-code 9",
        )

    monkeypatch.setattr(cli_run, "run_agent", fake_run)
    first = cli_run.run_cli(config, batch=2)
    assert first.ran_now == 2 and first.stopped and "batch of 2" in first.stopped
    result = json.loads(first.results.read_text())  # type: ignore[union-attr]
    assert result["agent"] == "claude-code 9" and result["cost"]["billing"] == "subscription"
    assert result["complete"] is False and result["planned_samples"] == 4
    trace = json.loads(next((pc / "traces" / run_id).glob("*.json")).read_text())
    tools = [e for e in trace["events"] if e["kind"] == "tool"]
    assert (
        tools[0]["returned"] == [{"cite": GOLD}] and tools[1]["returned"] == []
    )  # check_answer echoes
    assert trace["header"]["surface_id"] == "default@abc"

    second = cli_run.run_cli(config, batch=10)
    assert second.ran_now == 2 and second.stopped is None and len(set(calls)) == 4

    def limited(*_a: Any, **_k: Any) -> AgentRun:
        raise UsageLimitError("usage limit reached")

    monkeypatch.setattr(cli_run, "run_agent", limited)
    config2 = config | {"name": "t2"}
    out = cli_run.run_cli(config2, batch=5)
    assert out.stopped and out.stopped.startswith("usage limit") and out.done == 0
    assert (pc / "work" / "runs" / cli_run.run_id_for(config2) / "stopped.json").is_file()

    monkeypatch.setattr(cli_run, "run_agent", fake_run)
    late = cli_run.run_cli(config | {"name": "t3"}, until=datetime.now(UTC) + timedelta(seconds=5))
    assert late.ran_now == 0 and late.stopped and "would not finish" in late.stopped
    over = cli_run.run_cli(config | {"name": "t4", "max_used": 0.05}, batch=5)
    assert over.ran_now == 1 and over.stopped and "ceiling" in over.stopped
