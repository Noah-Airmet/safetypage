"""The server over HTTP: MCP on every surface, the JSON API, the call log and the limits."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx2
import pytest
from mcp_types import TextContent

from safetypage.api import AnswerAudit, FetchResult, QuoteCheck, ResponseMeta, SearchResponse
from safetypage.server.app import HOSTED, Limits, RateLimit, Server, build_app, client_family
from safetypage.server.library import Library

from .conftest import mcp_client, running

pytestmark = pytest.mark.anyio


def _text(result: Any) -> str:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


def _meta(result: Any) -> ResponseMeta:
    return ResponseMeta.model_validate(result.meta["safetypage"])


async def test_default_surface_tools(http: httpx2.AsyncClient, server: Server) -> None:
    async with mcp_client(http) as client:
        tools = (await client.list_tools()).tools
        assert [t.name for t in tools] == ["search", "fetch", "verify_quote", "check_answer"]
        for tool in tools:
            assert tool.output_schema and tool.title and tool.description
            assert tool.annotations and tool.annotations.read_only_hint
            assert tool.annotations.destructive_hint is False

        r = await client.call_tool("search", {"query": "risk assessment", "limit": 2})
        assert not r.is_error
        search = SearchResponse.model_validate(r.structured_content)
        assert search.hits[0].url.startswith("https://safetypage.test/d/")
        meta = _meta(r)
        assert meta.surface_id == server.surfaces["default"].surface_id
        assert meta.snapshot == "fixtures" and meta.arm == "bm25"
        assert "Cite a hit by its url." in _text(r)

        r = await client.call_tool("fetch", {"id": "arxiv:2305.15324/v2/p6"})
        fetched = FetchResult.model_validate(r.structured_content)
        assert fetched.units[0].text and fetched.url.endswith("/p6")
        assert "<source_text" in _text(r)

        r = await client.call_tool(
            "verify_quote", {"quote": "Model evaluation is not the only tool available"}
        )
        assert QuoteCheck.model_validate(r.structured_content).passed

        r = await client.call_tool(
            "check_answer", {"text": "See arxiv:2305.15324/v2/p6 and arxiv:2305.15324/v2/p66."}
        )
        audit = AnswerAudit.model_validate(r.structured_content)
        assert audit.resolved_count == 1 and audit.support_checked is False

        r = await client.call_tool("fetch", {"id": "arxiv:2305.15324/v2/p99"})
        assert r.is_error and "Pages run" in _text(r)
        assert _meta(r).request_id.startswith("r_")


async def test_link_only_fetch_over_mcp_has_no_text(http: httpx2.AsyncClient) -> None:
    async with mcp_client(http) as client:
        r = await client.call_tool("fetch", {"id": "example:unlicensed-post/r1/b1-b6"})
        result = FetchResult.model_validate(r.structured_content)
        assert result.units and all(u.text is None for u in result.units)
        assert "link-only" in _text(r)


@pytest.mark.parametrize(
    ("path", "tools"),
    [
        ("/x/default/mcp", ["search", "fetch", "verify_quote", "check_answer"]),
        ("/x/short/mcp", ["search", "fetch", "verify_quote", "check_answer"]),
        ("/x/no-verify/mcp", ["search", "fetch", "check_answer"]),
        ("/x/one-tool/mcp", ["search"]),
    ],
)
async def test_variant_surfaces(http: httpx2.AsyncClient, path: str, tools: list[str]) -> None:
    async with mcp_client(http, path) as client:
        listed = (await client.list_tools()).tools
        assert [t.name for t in listed] == tools
        r = await client.call_tool("search", {"query": "risk assessment", "limit": 2})
        assert _meta(r).surface_id.startswith(path.split("/")[2] + "@")


async def test_short_descriptions_are_short(http: httpx2.AsyncClient) -> None:
    async with mcp_client(http, "/x/short/mcp") as client:
        short = {t.name: t.description or "" for t in (await client.list_tools()).tools}
    async with mcp_client(http) as client:
        long = {t.name: t.description or "" for t in (await client.list_tools()).tools}
    assert all(len(short[n]) * 4 < len(long[n]) for n in long)


async def test_one_tool_search_returns_text(http: httpx2.AsyncClient) -> None:
    async with mcp_client(http, "/x/one-tool/mcp") as client:
        r = await client.call_tool("search", {"query": "risk assessment", "limit": 2})
        text = _text(r)
        assert text.count("<source_text") == 2 and "not the only tool" in text


async def test_unknown_surface_is_404(http: httpx2.AsyncClient) -> None:
    r = await http.post("/x/nope/mcp", json={})
    assert r.status_code == 404


async def test_call_log_keeps_nothing_from_the_public(
    http: httpx2.AsyncClient, ops_path: Path
) -> None:
    async with mcp_client(http) as client:
        await client.call_tool("search", {"query": "secret public question"})
    async with mcp_client(
        http, headers={"X-SafetyPage-Run": "run_1", "X-SafetyPage-Sample": "s1"}
    ) as client:
        await client.call_tool("search", {"query": "risk assessment", "limit": 2})
        await client.call_tool("fetch", {"id": "arxiv:2305.15324/v2/p99"})
    conn = sqlite3.connect(ops_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM tool_calls ORDER BY ts")]
    public = [r for r in rows if r["run_id"] is None]
    run = [r for r in rows if r["run_id"] == "run_1"]
    assert len(public) == 1 and len(run) == 2
    assert public[0]["args"] is None and public[0]["returned"] == "[]"
    assert "secret" not in json.dumps(public)
    assert json.loads(run[0]["args"])["query"] == "risk assessment"
    assert json.loads(run[0]["returned"])[0] == "arxiv:2305.15324/v2/p6"
    assert run[0]["sample_id"] == "s1" and run[0]["result_tokens"] > 0
    assert "Pages run" in run[1]["error"]
    columns = {r[1] for r in conn.execute("PRAGMA table_info(tool_calls)")}
    assert not {"ip", "address", "client_ip"} & columns


async def test_time_limit(lib: Library, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from safetypage.server.oplog import OpsLog  # noqa: PLC0415
    from safetypage.server.surfaces import load_surfaces  # noqa: PLC0415

    server = Server(
        {"current": lib, "fixtures": lib}, load_surfaces(), OpsLog(None), Limits(timeout_s=0.05)
    )

    def slow(*args: object, **kwargs: object) -> None:
        time.sleep(0.5)

    monkeypatch.setattr(lib, "check_answer", slow)
    async with running(build_app(server)) as http, mcp_client(http) as client:
        r = await client.call_tool("check_answer", {"text": "anything"})
    assert r.is_error and "took longer than" in _text(r)


async def test_json_api(http: httpx2.AsyncClient, server: Server) -> None:
    r = await http.get("/api/search", params={"query": "risk assessment", "limit": "2"})
    assert r.status_code == 200
    assert SearchResponse.model_validate(r.json()).hits
    assert r.headers["x-surface"] == server.surfaces["default"].surface_id
    assert r.headers["x-snapshot"] == "fixtures" and r.headers["x-request-id"].startswith("r_")

    r = await http.get("/api/doc/arxiv/2305.15324")
    assert r.status_code == 200 and r.json()["version"] == "v2"
    r = await http.get("/api/doc/arxiv/2305.15324/v1")
    assert r.json()["version"] == "v1"

    r = await http.get("/s/fixtures/api/units/arxiv/2305.15324/v2/p6-p7")
    assert r.status_code == 200 and [u["anchor"] for u in r.json()] == ["p6", "p7"]
    r = await http.get("/api/units/example/link-only-eval-report/r1/p1")
    assert r.json()[0]["text"] is None

    r = await http.post(
        "/api/verify",
        json={
            "quote": "Model evaluation is not the only tool available",
            "cite": "arxiv:2305.15324/v2/p6",
        },
    )
    assert r.status_code == 200 and r.json()["passed"]

    r = await http.post("/api/check", json={"text": "See arxiv:2305.15324/v2/p6."})
    assert r.json()["resolved_count"] == 1

    r = await http.get("/api/doc/arxiv/9999.99999")
    assert r.status_code == 404 and "Unknown document" in r.json()["error"]
    r = await http.get("/s/1999.01.0/api/doc/arxiv/2305.15324")
    assert r.status_code == 404 and "not served" in r.json()["error"]
    r = await http.post("/api/check", json={"words": 1})
    assert r.status_code == 400
    r = await http.post("/api/verify", content=b"x" * 200_000)
    assert r.status_code == 400


async def test_health_and_index(http: httpx2.AsyncClient) -> None:
    health = (await http.get("/health")).json()
    assert health["ok"] and health["current"] == "fixtures"
    assert set(health["surfaces"]) == {"default", "short", "no-verify", "one-tool"}
    assert (await http.get("/")).json()["mcp"] == "/mcp"


async def test_cors_for_the_site(http: httpx2.AsyncClient) -> None:
    r = await http.get("/api/doc/arxiv/2305.15324", headers={"Origin": "https://example.com"})
    assert r.headers["access-control-allow-origin"] == "*"


def test_client_family() -> None:
    assert client_family("Claude-User (claude.ai)") == "claude.ai"
    assert client_family("claude-code/3.1.0") == "claude-code"
    assert client_family("Mozilla/5.0; ChatGPT-User/1.0") == "chatgpt"
    assert client_family("inspect_ai/0.3") == "inspect"
    assert client_family(None) == "other"


def test_rate_limit_buckets() -> None:
    async def app(scope: object, receive: object, send: object) -> None: ...

    limit = RateLimit(app, Limits(per_minute=60, hosted_per_minute=6000))  # type: ignore[arg-type]
    now = 1000.0
    allowed = sum(limit.allow("1.2.3.4", "other", now) == 0 for _ in range(100))
    assert allowed == 15  # a quarter-minute burst
    assert limit.allow("1.2.3.4", "other", now) > 0
    assert limit.allow("5.6.7.8", "other", now) == 0  # another address has its own bucket
    hosted = sum(limit.allow("1.2.3.4", "claude.ai", now) == 0 for _ in range(1000))
    assert hosted == 1000 and "claude.ai" in HOSTED
    assert limit.allow("1.2.3.4", "other", now + 60) == 0  # refills


async def test_rate_limit_answers_429(server: Server) -> None:
    server.limits = Limits(per_minute=4)
    async with running(build_app(server)) as http:
        codes = [(await http.get("/api/doc/arxiv/2305.15324")).status_code for _ in range(3)]
    assert codes == [200, 429, 429]
