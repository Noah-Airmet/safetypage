"""The MCP side: one stateless Streamable HTTP endpoint per surface, on the official SDK.

Every tool result carries a markdown ``content`` block for the model, the :mod:`safetypage.api`
model as ``structuredContent`` (published as the tool's ``outputSchema``), and
:class:`~safetypage.api.ResponseMeta` under ``_meta["safetypage"]``.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, Field

from safetypage.api import AnswerAudit, FetchResult, QuoteCheck, SearchResponse
from safetypage.model import DocKind
from safetypage.server.app import (
    MAX_BODY_BYTES,
    META_KEY,
    RUN_HEADER,
    SAMPLE_HEADER,
    Caller,
    Server,
    client_family,
)
from safetypage.server.library import ToolError
from safetypage.server.surfaces import Surface

__all__ = ["McpEndpoint", "build_mcp", "mcp_endpoint"]

TITLES = {
    "search": "Search the library",
    "fetch": "Read a document or page",
    "verify_quote": "Check a quotation",
    "check_answer": "Check an answer's citations",
}

READ_ONLY = {
    "read_only_hint": True,
    "destructive_hint": False,
    "idempotent_hint": True,
    "open_world_hint": False,
}


def _caller(ctx: Context) -> Caller:
    headers = {k.lower(): v for k, v in (ctx.headers or {}).items()}
    return Caller(
        client=client_family(headers.get("user-agent")),
        run_id=headers.get(RUN_HEADER),
        sample_id=headers.get(SAMPLE_HEADER),
    )


def _drop_none(args: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in args.items() if v is not None}


async def _result(
    server: Server, surface: Surface, tool: str, args: dict[str, Any], ctx: Context
) -> CallToolResult:
    try:
        outcome = await server.call(surface, tool, args, _caller(ctx))
    except ToolError as exc:
        failed = CallToolResult(content=[TextContent(text=str(exc))], is_error=True)
        if exc.meta is not None:
            failed.meta = {META_KEY: exc.meta.model_dump(mode="json")}
        return failed
    structured: BaseModel = outcome.model
    result = CallToolResult(
        content=[TextContent(text=outcome.markdown)],
        structured_content=structured.model_dump(mode="json"),
    )
    result.meta = {META_KEY: outcome.meta.model_dump(mode="json")}
    return result


ToolFn = Callable[..., Coroutine[Any, Any, CallToolResult]]

ARGS = {
    "query": 'Words, "phrases", prefix*, a NEAR/5 b, -exclude. Empty lists documents.',
    "kind": "Document kind.",
    "org": "Publishing organisation, e.g. Anthropic, NIST.",
    "collection": "Collection, e.g. interpretability, evals.",
    "date": "YYYY or YYYY-MM, inclusive.",
    "doc": "Search inside one document or version, e.g. arxiv:2305.15324.",
    "mode": "units: pages and paragraphs; documents: whole documents ranked by their hits.",
    "cursor": "next_cursor from the previous page.",
    "id": (
        "A document id, a cite string such as arxiv:2305.15324/v2/p6, a range of up to 8 units, "
        "or a result url."
    ),
    "view": "image adds page image links (open PDFs).",
    "quote": "The exact words you intend to put in quotation marks; '...' joins fragments.",
    "cite": "The cite string or url you will attach to it.",
    "quote_doc": "Without cite: check against this whole document.",
    "text": "The draft answer, in markdown, with its citations and quotations.",
}


def _arg(name: str) -> Any:
    return Field(description=ARGS[name])


def _tools(server: Server, surface: Surface) -> dict[str, ToolFn]:
    async def search(
        ctx: Context,
        *,
        query: Annotated[str, _arg("query")] = "",
        kind: Annotated[DocKind | None, _arg("kind")] = None,
        org: Annotated[str | None, _arg("org")] = None,
        collection: Annotated[str | None, _arg("collection")] = None,
        date_from: Annotated[str | None, _arg("date")] = None,
        date_to: Annotated[str | None, _arg("date")] = None,
        doc: Annotated[str | None, _arg("doc")] = None,
        mode: Annotated[Literal["units", "documents"], _arg("mode")] = "units",
        sort: Literal["relevance", "date"] = "relevance",
        limit: Annotated[int, Field(ge=1, le=25)] = 10,
        cursor: Annotated[str | None, _arg("cursor")] = None,
    ) -> Annotated[CallToolResult, SearchResponse]:
        args = _drop_none(
            {
                "query": query, "kind": kind, "org": org, "collection": collection,
                "date_from": date_from, "date_to": date_to, "doc": doc, "mode": mode,
                "sort": sort, "limit": limit, "cursor": cursor,
            }
        )  # fmt: skip
        return await _result(server, surface, "search", args, ctx)

    async def fetch(
        ctx: Context,
        *,
        id: Annotated[str, _arg("id")],
        view: Annotated[Literal["text", "image"], _arg("view")] = "text",
        max_tokens: Annotated[int, Field(ge=500, le=16000)] = 6000,
    ) -> Annotated[CallToolResult, FetchResult]:
        args = {"id": id, "view": view, "max_tokens": max_tokens}
        return await _result(server, surface, "fetch", args, ctx)

    async def verify_quote(
        ctx: Context,
        *,
        quote: Annotated[str, _arg("quote")],
        cite: Annotated[str | None, _arg("cite")] = None,
        doc: Annotated[str | None, _arg("quote_doc")] = None,
    ) -> Annotated[CallToolResult, QuoteCheck]:
        args = _drop_none({"quote": quote, "cite": cite, "doc": doc})
        return await _result(server, surface, "verify_quote", args, ctx)

    async def check_answer(
        ctx: Context, *, text: Annotated[str, _arg("text")]
    ) -> Annotated[CallToolResult, AnswerAudit]:
        return await _result(server, surface, "check_answer", {"text": text}, ctx)

    return {
        "search": search,
        "fetch": fetch,
        "verify_quote": verify_quote,
        "check_answer": check_answer,
    }


def build_mcp(server: Server, surface: Surface) -> MCPServer:
    """An MCP server offering a surface's tools, with its descriptions."""
    mcp = MCPServer(
        name="safetypage",
        title="SafetyPage",
        description="A page-cited library of the AI safety record.",
        instructions=surface.instructions,
        version=server.version,
    )
    tools = _tools(server, surface)
    for name in surface.tools:
        mcp.add_tool(
            tools[name],
            name=name,
            title=TITLES[name],
            description=surface.descriptions[name],
            annotations=ToolAnnotations(title=TITLES[name], **READ_ONLY),
            structured_output=True,
        )
    return mcp


@dataclass(frozen=True, slots=True)
class McpEndpoint:
    asgi: StreamableHTTPASGIApp
    manager: StreamableHTTPSessionManager

    def run(self) -> AbstractAsyncContextManager[None]:
        return self.manager.run()


def mcp_endpoint(server: Server, surface: Surface, allowed_hosts: list[str] | None) -> McpEndpoint:
    mcp = build_mcp(server, surface)
    if allowed_hosts:
        origins = [f"{scheme}://{host}" for host in allowed_hosts for scheme in ("http", "https")]
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=origins,
        )
    else:
        security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        max_request_body_size=MAX_BODY_BYTES,
        transport_security=security,
    )
    manager = mcp.session_manager
    return McpEndpoint(StreamableHTTPASGIApp(manager), manager)
