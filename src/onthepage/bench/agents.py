"""Coding-agent CLIs as PageCite agents, on subscription logins rather than API keys.

Each agent runs headless, one question per fresh session, with the library's MCP server as its
only way to look anything up:

``claude-code``  ``claude -p``: no built-in tools (``--tools ""``), only
                 the library server (``--strict-mcp-config``), no user settings, plugins or
                 hooks (``--setting-sources ""``), no saved session.
``codex``        ``codex exec`` on the ChatGPT login, with its own ``CODEX_HOME`` (so no user
                 AGENTS.md or config; ``auth.json`` is a link to the real one), the shell, code
                 mode, apps, plugins, browser, images and web search turned off.
``antigravity``  ``agy -p`` on the Google login, with its own ``HOME`` (only the library server
                 configured) and permission rules denying commands, files and URLs. Its web
                 search cannot be turned off, so any step that is not a library call marks the
                 sample ``contaminated`` and it scores as wrong.

:func:`complete` is the same CLIs with no tools at all, for drafting, checking and judging.
Model specs: ``claude-code:<model>``, ``codex:<model>``, ``antigravity:<model>``; anything else
is an Inspect model id.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

__all__ = [
    "AGENTS",
    "AgentRun",
    "UsageLimitError",
    "complete",
    "is_cli_model",
    "run_agent",
]

AGENTS = ("claude-code", "codex", "antigravity")
REPO = Path(__file__).resolve().parents[3]
WORK = REPO / "pagecite" / "work"

CLAUDE_BIN = os.environ.get("PAGECITE_CLAUDE", "claude")
CODEX_BIN = os.environ.get("PAGECITE_CODEX", "codex")
AGY_BIN = os.environ.get("PAGECITE_AGY", "agy")

LIMIT_RE = re.compile(
    r"rate.?limit|usage limit|limit reached|quota|resource.?exhausted|\b429\b|too many requests"
    r"|out of (?:credits|usage)|try again (?:at|in)",
    re.I,
)

CODEX_DISABLE = [
    "shell_tool",
    "unified_exec",
    "apps",
    "plugins",
    "remote_plugin",
    "multi_agent",
    "image_generation",
    "view_image",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "in_app_browser",
    "sleep_tool",
    "skill_search",
    "tool_suggest",
    "memories",
    "shell_snapshot",
]
LIBRARY_TOOLS = ("search", "fetch", "verify_quote", "check_answer")


class UsageLimitError(RuntimeError):
    """The account hit a rate or usage limit, or is above the configured ceiling. The batch
    stops cleanly; rerun later to resume."""


@dataclass
class AgentRun:
    answer: str
    usage: dict[str, int] = field(default_factory=dict[str, int])
    """``input``, ``output``, ``cache_read``, ``cache_write``, ``reasoning`` tokens."""
    seconds: float = 0.0
    notional_usd: float | None = None
    """What the CLI says the run would have cost at list prices (Claude Code only)."""
    meter: dict[str, Any] = field(default_factory=dict[str, Any])
    """The account's usage meter after the run, as the CLI reports it."""
    off_library: list[str] = field(default_factory=list[str])
    """Tools used that are not the library's (Antigravity's web search, for instance)."""
    error: str | None = None
    agent_version: str = ""
    raw: str = ""
    """The CLI's own output, kept so a record can be re-read later."""


def is_cli_model(spec: str | None) -> bool:
    return bool(spec) and spec.split(":", 1)[0] in AGENTS  # type: ignore[union-attr]


def _version(binary: str) -> str:
    try:
        out = subprocess.run(  # noqa: S603
            [binary, "--version"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr) else ""


def _run(
    cmd: list[str], *, env: dict[str, str] | None = None, cwd: Path, timeout: int
) -> tuple[str, str, int, float]:
    start = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=cwd,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return out, "timeout", -1, time.monotonic() - start
    return proc.stdout, proc.stderr, proc.returncode, time.monotonic() - start


def _d(value: Any) -> dict[str, Any]:
    """A JSON object, or an empty one."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _jsonl(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


# ------------------------------------------------------------------------------ Claude Code


def _claude(
    prompt: str, model: str, *, mcp_url: str | None, headers: dict[str, str], timeout: int
) -> AgentRun:
    cwd = WORK / "claude-code"
    cwd.mkdir(parents=True, exist_ok=True)
    cmd = [
        CLAUDE_BIN, "-p", prompt, "--model", model, "--tools", "", "--strict-mcp-config",
        "--setting-sources", "", "--no-session-persistence", "--output-format", "stream-json",
        "--verbose", "--disable-slash-commands",
    ]  # fmt: skip
    if mcp_url:
        config = {"mcpServers": {"onthepage": {"type": "http", "url": mcp_url, "headers": headers}}}
        path = cwd / f"mcp-{os.getpid()}.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        cmd += ["--mcp-config", str(path)]
        cmd += ["--allowedTools", ",".join(f"mcp__onthepage__{t}" for t in LIBRARY_TOOLS)]
    out, err, code, secs = _run(cmd, cwd=cwd, timeout=timeout)
    events = _jsonl(out)
    run = AgentRun(
        answer="", seconds=secs, agent_version=f"claude-code {_version(CLAUDE_BIN)}", raw=out
    )
    for e in events:
        if e.get("type") == "rate_limit_event":
            info = _d(e.get("rate_limit_info"))
            windows = _d(info.get("unifiedWindows"))
            run.meter = {
                "status": info.get("status"),
                **{f"{k}_used": _d(v).get("utilization") for k, v in windows.items()},
            }
        elif e.get("type") == "assistant":
            for block in e.get("message", {}).get("content", []):
                name = str(block.get("name", ""))
                # A bare library name is a malformed call that fails; it reaches nothing else.
                if (
                    block.get("type") == "tool_use"
                    and not name.startswith("mcp__onthepage__")
                    and name not in LIBRARY_TOOLS
                ):
                    run.off_library.append(name)
        elif e.get("type") == "result":
            run.answer = str(e.get("result") or "")
            u = _d(e.get("usage"))
            run.usage = {
                "input": int(u.get("input_tokens", 0)),
                "output": int(u.get("output_tokens", 0)),
                "cache_read": int(u.get("cache_read_input_tokens", 0)),
                "cache_write": int(u.get("cache_creation_input_tokens", 0)),
                "reasoning": int(_d(u.get("output_tokens_details")).get("thinking_tokens", 0)),
            }
            run.notional_usd = e.get("total_cost_usd")
            if e.get("is_error"):
                run.error = str(e.get("result") or e.get("subtype"))
    if not events or (code != 0 and not run.answer):
        run.error = run.error or (err.strip()[-400:] or f"exit {code}")
    if run.meter.get("status") not in (None, "allowed", "allowed_warning"):
        raise UsageLimitError(f"Claude Code rate limit: {run.meter}")
    if run.error and LIMIT_RE.search(run.error):
        raise UsageLimitError(run.error)
    return run


# ------------------------------------------------------------------------------ Codex


def _codex_home() -> Path:
    """A CODEX_HOME holding only a link to the real login, so no user AGENTS.md, config, rules,
    memories or plugins load. If Codex replaced the link with a refreshed login, the refreshed
    file is copied back to the real home so the two never diverge."""
    home = WORK / "codex-home"
    home.mkdir(parents=True, exist_ok=True)
    link = home / "auth.json"
    real = Path.home() / ".codex" / "auth.json"
    if link.exists() and not link.is_symlink():
        shutil.copy2(link, real)
        link.unlink()
    if not link.exists():
        link.symlink_to(real)
    return home


def _find(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]  # pyright: ignore[reportUnknownVariableType]
        for v in obj.values():  # pyright: ignore[reportUnknownVariableType]
            if (found := _find(v, key)) is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:  # pyright: ignore[reportUnknownVariableType]
            if (found := _find(v, key)) is not None:
                return found
    return None


def _codex_meter(home: Path, since: float) -> dict[str, Any]:
    """The last ``rate_limits`` Codex wrote to this run's session file: used share of the
    5-hour and weekly windows."""
    files = [p for p in (home / "sessions").rglob("*.jsonl") if p.stat().st_mtime >= since - 1]
    meter: dict[str, Any] = {}
    for path in sorted(files, key=lambda p: p.stat().st_mtime):
        for line in path.read_text(encoding="utf-8").splitlines():
            if '"rate_limits"' not in line:
                continue
            limits = _d(_find(json.loads(line), "rate_limits"))
            for key in ("primary", "secondary"):
                w = _d(limits.get(key))
                if w:
                    minutes = w.get("window_minutes")
                    name = {300: "five_hour", 10080: "seven_day"}.get(int(minutes or 0), key)
                    meter[f"{name}_used"] = (w.get("used_percent") or 0) / 100
    return meter


def _codex(
    prompt: str, model: str, *, mcp_url: str | None, headers: dict[str, str], timeout: int
) -> AgentRun:
    home = _codex_home()
    cwd = WORK / "codex"
    cwd.mkdir(parents=True, exist_ok=True)
    cmd = [CODEX_BIN, "exec", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
           "--json", "-s", "read-only", "-m", model, "-c", 'web_search="disabled"',
           "-c", "project_doc_max_bytes=0"]  # fmt: skip
    for feature in CODEX_DISABLE:
        cmd += ["--disable", feature]
    if mcp_url:
        hdr = ",".join(f'"{k}"="{v}"' for k, v in headers.items())
        cmd += [
            "-c",
            f'mcp_servers.onthepage.url="{mcp_url}"',
            "-c",
            f"mcp_servers.onthepage.http_headers={{{hdr}}}",
        ]
    cmd.append(prompt)
    started = time.time()
    out, err, code, secs = _run(
        cmd, env=dict(os.environ, CODEX_HOME=str(home)), cwd=cwd, timeout=timeout
    )
    _codex_home()  # restore the link if Codex refreshed the login
    run = AgentRun(answer="", seconds=secs, agent_version=f"codex {_version(CODEX_BIN)}", raw=out)
    usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "reasoning": 0}
    messages: list[str] = []
    errors: list[str] = []
    for e in _jsonl(out):
        kind = e.get("type")
        item = _d(e.get("item"))
        if kind == "item.completed":
            itype = item.get("type")
            if itype == "agent_message":
                messages.append(str(item.get("text", "")))
            elif itype == "error":
                errors.append(str(item.get("message", "")))
            elif itype not in ("reasoning", "mcp_tool_call", "todo_list"):
                run.off_library.append(str(itype))
            elif itype == "mcp_tool_call" and item.get("server") not in (None, "onthepage"):
                run.off_library.append(f"mcp:{item.get('server')}")
        elif kind == "turn.completed":
            u = _d(e.get("usage"))
            cached = int(u.get("cached_input_tokens", 0))
            usage["input"] += int(u.get("input_tokens", 0)) - cached
            usage["cache_read"] += cached
            usage["output"] += int(u.get("output_tokens", 0))
            usage["reasoning"] += int(u.get("reasoning_output_tokens", 0))
        elif kind in ("turn.failed", "error"):
            errors.append(json.dumps(e)[:400])
    run.usage = usage
    run.answer = messages[-1] if messages else ""
    run.meter = _codex_meter(home, started)
    if errors and not run.answer:
        run.error = " | ".join(errors)[-600:]
    elif code != 0 and not run.answer:
        run.error = err.strip()[-400:] or f"exit {code}"
    if run.error and LIMIT_RE.search(run.error):
        raise UsageLimitError(run.error)
    return run


# ------------------------------------------------------------------------------ Antigravity


AGY_SETTINGS = {
    "permissions": {
        "allow": ["mcp(onthepage/*)"],
        "deny": [
            "command(*)", "read_file(*)", "write_file(*)", "read_url(*)", "execute_url(*)",
            "download_url(*)",
        ],
    }
}  # fmt: skip
AGY_OK_STEPS = {"call_mcp_tool", "list_resources", "read_resource"}


def _agy_home(mcp_url: str | None, headers: dict[str, str]) -> Path:
    home = WORK / "agy-home"
    config = home / ".gemini" / "config"
    config.mkdir(parents=True, exist_ok=True)
    library = home / "Library"
    if not library.is_symlink() and not library.exists():
        library.symlink_to(Path.home() / "Library")  # the login lives in the keychain
    servers = {"onthepage": {"serverUrl": mcp_url, "headers": headers}} if mcp_url else {}
    (config / "mcp_config.json").write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
    return home


def _agy(
    prompt: str, model: str, *, mcp_url: str | None, headers: dict[str, str], timeout: int
) -> AgentRun:
    home = _agy_home(mcp_url, headers)
    cwd = WORK / "agy"
    cwd.mkdir(parents=True, exist_ok=True)
    cmd = [AGY_BIN, "-p", prompt, "--model", model, "--output-format", "stream-json", "--sandbox",
           "--disable-slash-commands", "--settings", json.dumps(AGY_SETTINGS),
           "--print-timeout", f"{timeout - 10}s"]  # fmt: skip
    out, err, code, secs = _run(cmd, env=dict(os.environ, HOME=str(home)), cwd=cwd, timeout=timeout)
    run = AgentRun(
        answer="", seconds=secs, agent_version=f"antigravity {_version(AGY_BIN)}", raw=out
    )
    usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "reasoning": 0}
    names: dict[Any, str] = {}
    for e in _jsonl(out):
        step = _d(e.get("step_update"))
        if step.get("step_type") == "tool":
            index = step.get("step_index")
            if step.get("state") == "ACTIVE":
                names[index] = str(step.get("tool_name"))
            elif step.get("state") == "DONE":
                # Only a tool step that succeeded reached anything; denied ones end in ERROR.
                name = str(step.get("tool_name") or names.get(index))
                if name not in AGY_OK_STEPS:
                    run.off_library.append(name)
        if step.get("state") == "DONE" and step.get("usage"):
            u = _d(step.get("usage"))
            usage["input"] += int(u.get("input_tokens", 0))
            usage["cache_read"] += int(u.get("cache_read_tokens", 0))
            usage["output"] += int(u.get("output_tokens", 0))
            usage["reasoning"] += int(u.get("thinking_tokens", 0))
        result = _d(e.get("result"))
        if result:
            run.answer = str(result.get("response") or "")
            if result.get("status") != "SUCCESS":
                run.error = str(result.get("error") or result.get("status"))
    run.usage = usage
    if not run.answer and not run.error:
        run.error = err.strip()[-400:] or f"exit {code}"
    if run.error and LIMIT_RE.search(run.error + err[-400:]):
        raise UsageLimitError(run.error)
    return run


_RUNNERS = {"claude-code": _claude, "codex": _codex, "antigravity": _agy}


def run_agent(
    agent: str,
    model: str,
    prompt: str,
    *,
    mcp_url: str | None,
    headers: dict[str, str] | None = None,
    timeout: int = 900,
) -> AgentRun:
    return _RUNNERS[agent](prompt, model, mcp_url=mcp_url, headers=headers or {}, timeout=timeout)


def complete(spec: str, prompt: str, *, timeout: int = 600) -> str:
    """One prompt, no tools, the reply's text. ``spec`` is ``<agent>:<model>``."""
    agent, model = spec.split(":", 1)
    run = run_agent(agent, model, prompt, mcp_url=None, timeout=timeout)
    if run.error and not run.answer:
        raise RuntimeError(f"{spec}: {run.error}")
    return run.answer
