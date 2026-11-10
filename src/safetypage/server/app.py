"""The search server: the four tools over MCP (one endpoint per surface) and as a JSON API.

Routes:

``POST /mcp``                     the default surface, stateless Streamable HTTP
``POST /x/<surface>/mcp``         a named surface variant
``GET  /api/search`` ...          the JSON API for the site (``/s/<snapshot>/api/...`` pins one)
``GET  /health``                  liveness, with the snapshots and surfaces served

Run it with ``python -m safetypage.server`` (see ``--help``).
"""

from __future__ import annotations

import contextlib
import json
import logging
import secrets
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import Any

import anyio
from pydantic import BaseModel, ValidationError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from safetypage.api import (
    AnswerAudit,
    FetchResult,
    QuoteCheck,
    ResponseMeta,
    SearchResponse,
    VerifyQuoteRequest,
)
from safetypage.server import render
from safetypage.server.library import Library, MissingError, ToolError, estimate_tokens
from safetypage.server.oplog import CallRecord, OpsLog
from safetypage.server.surfaces import Surface

__all__ = ["Limits", "Server", "build_app", "client_family", "server_version"]

log = logging.getLogger("safetypage.server")

META_KEY = "safetypage"
"""Key of :class:`ResponseMeta` in every tool result's ``_meta``."""
RUN_HEADER = "x-safetypage-run"
SAMPLE_HEADER = "x-safetypage-sample"
MAX_BODY_BYTES = 128 * 1024


def server_version() -> str:
    try:
        return package_version("safetypage")
    except PackageNotFoundError:  # pragma: no cover
        return "0.0.0"


def client_family(user_agent: str | None) -> str:
    """The kind of client, from its User-Agent: who is calling, never which person."""
    ua = (user_agent or "").lower()
    if "claude-code" in ua or "claude code" in ua:
        return "claude-code"
    if "claude" in ua or "anthropic" in ua:
        return "claude.ai"
    if "openai" in ua or "chatgpt" in ua:
        return "chatgpt"
    if "inspect" in ua:
        return "inspect"
    return "other"


HOSTED = frozenset({"claude.ai", "chatgpt"})
"""Clients that call from their own servers, so one address carries many people."""


@dataclass(frozen=True, slots=True)
class Limits:
    timeout_s: float = 10.0
    """Per-call time limit, including time spent waiting for a worker."""
    workers: int = 4
    """Tool calls that may run at once."""
    per_minute: int = 120
    """Requests per minute from one address and client family."""
    hosted_per_minute: int = 3000
    """The same, for a hosted client (claude.ai, ChatGPT): their many users share an address."""
    trust_proxy: bool = False
    """Take the client address from CF-Connecting-IP / X-Forwarded-For (behind a proxy only)."""
    search_text_tokens: int = 8000
    """Budget for full text returned with search hits, on a surface that does that."""


# ---------------------------------------------------------------------------------------
# the server: surfaces, libraries, limits, logging
# ---------------------------------------------------------------------------------------


@dataclass
class Caller:
    client: str
    run_id: str | None = None
    sample_id: str | None = None


@dataclass
class Outcome:
    model: BaseModel
    markdown: str
    meta: ResponseMeta


@dataclass
class Server:
    libraries: dict[str, Library]
    """Snapshot id → library. ``current`` is an alias for one of them."""
    surfaces: dict[str, Surface]
    ops: OpsLog
    limits: Limits = field(default_factory=Limits)
    version: str = field(default_factory=server_version)

    def __post_init__(self) -> None:
        self._limiter = anyio.CapacityLimiter(self.limits.workers)
        self.surfaces = {name: s for name, s in self.surfaces.items() if self._check_surface(s)}

    def _check_surface(self, surface: Surface) -> bool:
        library = self.libraries.get(surface.snapshot)
        if library is None:
            log.warning(
                "surface %s: snapshot %s is not loaded; not served", surface.name, surface.snapshot
            )
            return False
        if surface.arm not in library.backend.arms:
            log.warning("surface %s: arm %s is not built; not served", surface.name, surface.arm)
            return False
        return True

    def close(self) -> None:
        """Release each backend's threads and connections, then the call log."""
        for library in {id(v): v for v in self.libraries.values()}.values():
            close = getattr(library.backend, "close", None)
            if callable(close):
                close()
        self.ops.close()

    def library(self, snapshot: str = "current") -> Library:
        library = self.libraries.get(snapshot)
        if library is None:
            served = ", ".join(sorted(k for k in self.libraries if k != "current"))
            raise MissingError(f"snapshot {snapshot!r} is not served here. Served: {served}.")
        return library

    async def call(
        self,
        surface: Surface,
        tool: str,
        args: dict[str, Any],
        caller: Caller,
        *,
        snapshot: str | None = None,
    ) -> Outcome:
        """Run one tool call under the time limit and the worker cap, and log it."""
        library = self.library(snapshot or surface.snapshot)
        meta = ResponseMeta(
            server_version=self.version,
            surface_id=surface.surface_id,
            snapshot=library.snapshot,
            arm=surface.arm,
            request_id="r_" + secrets.token_urlsafe(9),
        )
        record = CallRecord(
            request_id=meta.request_id,
            surface_id=meta.surface_id,
            snapshot=meta.snapshot,
            arm=meta.arm,
            server_version=meta.server_version,
            tool=tool,
            client=caller.client,
            run_id=caller.run_id,
            sample_id=caller.sample_id,
            args=args,
        )
        started = time.perf_counter()

        def work() -> tuple[BaseModel, str]:
            return _run(library, surface, tool, args, self.limits)

        try:
            with anyio.fail_after(self.limits.timeout_s):
                model, markdown = await anyio.to_thread.run_sync(
                    work, limiter=self._limiter, abandon_on_cancel=True
                )
        except TimeoutError:
            record.error, record.error_kind = "timeout", "timeout"
            raise _failure(
                meta,
                f"{tool} took longer than {self.limits.timeout_s:g} seconds and was stopped. Try "
                "a narrower query, fewer units, or a shorter text.",
            ) from None
        except ToolError as exc:
            record.error, record.error_kind = str(exc), "bad_request"
            exc.meta = meta
            raise
        except Exception as exc:
            log.exception("%s failed", tool)
            record.error, record.error_kind = repr(exc), "internal"
            raise _failure(
                meta,
                f"{tool} failed with an internal error (request {meta.request_id}). Try again; if "
                "it keeps failing, the request id identifies it in our logs.",
            ) from exc
        finally:
            record.latency_ms = round((time.perf_counter() - started) * 1000)
            if record.error:
                self.ops.write(record)
        record.returned = _returned(model)
        record.verdict = _verdict(model)
        record.result_tokens = estimate_tokens(markdown)
        self.ops.write(record)
        return Outcome(model, markdown, meta)


def _failure(meta: ResponseMeta, message: str) -> ToolError:
    failure = ToolError(message)
    failure.meta = meta
    return failure


def _run(
    library: Library, surface: Surface, tool: str, args: dict[str, Any], limits: Limits
) -> tuple[BaseModel, str]:
    if tool == "search":
        response = library.search(surface.arm, **args)
        texts = None
        if surface.search_full_text:
            texts = library.full_texts([h.cite for h in response.hits], limits.search_text_tokens)
        return response, render.search(response, texts)
    if tool == "fetch":
        result = library.fetch(**args)
        return result, render.fetch(result)
    if tool == "verify_quote":
        check = library.verify_quote(**args)
        return check, render.quote(check)
    if tool == "check_answer":
        audit = library.check_answer(**args)
        return audit, render.answer(audit)
    if tool == "document":
        card = library.document(**args)
        return card, ""
    if tool == "units":
        units = library.units(**args)
        return _UnitList(units=units), ""
    raise ToolError(f"unknown tool {tool!r}")


class _UnitList(BaseModel):
    units: list[Any]


def _returned(model: BaseModel) -> list[str]:
    if isinstance(model, SearchResponse):
        return [h.cite for h in model.hits] + [f"{d.doc_id}/{d.version}" for d in model.documents]
    if isinstance(model, FetchResult):
        return [u.cite for u in model.units] or [model.id]
    if isinstance(model, QuoteCheck):
        return [loc.cite for loc in model.locations]
    if isinstance(model, AnswerAudit):
        return [c.cite for c in model.citations]
    if isinstance(model, _UnitList):
        return [str(getattr(u, "cite", "")) for u in model.units]
    return []


def _verdict(model: BaseModel) -> str | None:
    if isinstance(model, QuoteCheck):
        return str(model.verdict)
    if isinstance(model, AnswerAudit):
        return f"{model.passed_count}/{model.quote_count}"
    return None


# ---------------------------------------------------------------------------------------
# rate limiting
# ---------------------------------------------------------------------------------------


class RateLimit:
    """A token bucket per (address, client family). Addresses live in memory only."""

    def __init__(self, app: ASGIApp, limits: Limits) -> None:
        self.app = app
        self.limits = limits
        self._buckets: dict[tuple[str, str], tuple[float, float]] = {}

    def _address(self, scope: Scope, headers: dict[str, str]) -> str:
        if self.limits.trust_proxy:
            forwarded = headers.get("cf-connecting-ip") or headers.get("x-forwarded-for", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
        client = scope.get("client")
        return str(client[0]) if client else "unknown"

    def allow(self, address: str, family: str, now: float) -> float:
        """0 if allowed, else seconds until the next request would be."""
        rate = (self.limits.hosted_per_minute if family in HOSTED else self.limits.per_minute) / 60
        capacity = rate * 60 / 4  # a burst of a quarter-minute's allowance
        key = (address, family)
        tokens, last = self._buckets.get(key, (capacity, now))
        tokens = min(capacity, tokens + (now - last) * rate)
        if tokens < 1:
            self._buckets[key] = (tokens, now)
            return (1 - tokens) / rate
        self._buckets[key] = (tokens - 1, now)
        if len(self._buckets) > 50_000:
            self._buckets = {k: v for k, v in self._buckets.items() if now - v[1] < 120}
        return 0.0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path", ""))
        if scope["type"] != "http" or scope.get("method") == "OPTIONS" or path in ("/health", "/"):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
        family = client_family(headers.get("user-agent"))
        wait = self.allow(self._address(scope, headers), family, time.monotonic())
        if wait:
            response = JSONResponse(
                {"error": f"Too many requests. Wait {wait:.0f} seconds and try again."},
                status_code=429,
                headers={"Retry-After": str(max(1, round(wait)))},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------------------
# the JSON API
# ---------------------------------------------------------------------------------------


def _caller(request: Request) -> Caller:
    return Caller(
        client=client_family(request.headers.get("user-agent")),
        run_id=request.headers.get(RUN_HEADER),
        sample_id=request.headers.get(SAMPLE_HEADER),
    )


def _meta_headers(meta: ResponseMeta) -> dict[str, str]:
    return {
        "X-Server-Version": meta.server_version,
        "X-Surface": meta.surface_id,
        "X-Snapshot": meta.snapshot,
        "X-Arm": meta.arm,
        "X-Request-Id": meta.request_id,
    }


def _api_routes(server: Server) -> list[Route]:
    surface = server.surfaces["default"]

    async def respond(request: Request, tool: str, args: dict[str, Any]) -> Response:
        snapshot = request.path_params.get("snapshot")
        try:
            outcome = await server.call(surface, tool, args, _caller(request), snapshot=snapshot)
        except ToolError as exc:
            status = 404 if isinstance(exc, MissingError) else 400
            headers = _meta_headers(exc.meta) if exc.meta else None
            return JSONResponse({"error": str(exc)}, status_code=status, headers=headers)
        body = outcome.model.model_dump(mode="json")
        if isinstance(outcome.model, _UnitList):
            body = body["units"]
        return JSONResponse(body, headers=_meta_headers(outcome.meta))

    async def body(request: Request) -> dict[str, Any]:
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            raise ToolError(f"request body over {MAX_BODY_BYTES} bytes")
        data = json.loads(raw or b"{}")
        if not isinstance(data, dict):
            raise ToolError("request body must be a JSON object")
        return dict(data)  # pyright: ignore[reportUnknownArgumentType]

    async def search(request: Request) -> Response:
        return await respond(request, "search", dict(request.query_params))

    async def doc(request: Request) -> Response:
        p = request.path_params
        ref = f"{p['ns']}:{p['local']}" + (f"/{p['version']}" if "version" in p else "")
        return await respond(request, "document", {"ref": ref})

    async def units(request: Request) -> Response:
        p = request.path_params
        return await respond(
            request, "units", {"ref": f"{p['ns']}:{p['local']}/{p['version']}/{p['anchor']}"}
        )

    async def verify(request: Request) -> Response:
        try:
            req = VerifyQuoteRequest.model_validate(await body(request))
        except (ValidationError, ValueError, ToolError) as exc:
            return JSONResponse({"error": f"bad request: {exc}"}, status_code=400)
        return await respond(request, "verify_quote", req.model_dump())

    async def check(request: Request) -> Response:
        try:
            data = await body(request)
        except (ValueError, ToolError) as exc:
            return JSONResponse({"error": f"bad request: {exc}"}, status_code=400)
        if set(data) != {"text"} or not isinstance(data["text"], str):
            return JSONResponse(
                {"error": 'bad request: send {"text": "<answer>"}'}, status_code=400
            )
        return await respond(request, "check_answer", {"text": data["text"]})

    routes: list[Route] = []
    for prefix in ("", "/s/{snapshot}"):
        routes += [
            Route(f"{prefix}/api/search", search, methods=["GET"]),
            Route(f"{prefix}/api/doc/{{ns}}/{{local}}", doc, methods=["GET"]),
            Route(f"{prefix}/api/doc/{{ns}}/{{local}}/{{version}}", doc, methods=["GET"]),
            Route(
                f"{prefix}/api/units/{{ns}}/{{local}}/{{version}}/{{anchor}}",
                units,
                methods=["GET"],
            ),
            Route(f"{prefix}/api/verify", verify, methods=["POST"]),
            Route(f"{prefix}/api/check", check, methods=["POST"]),
        ]
    return routes


# ---------------------------------------------------------------------------------------
# the app
# ---------------------------------------------------------------------------------------


def build_app(server: Server, *, allowed_hosts: list[str] | None = None) -> Starlette:
    """The ASGI app: MCP per surface, the JSON API, and health."""
    from safetypage.server.mcp import mcp_endpoint  # noqa: PLC0415 (keeps the SDK import local)

    endpoints = {
        name: mcp_endpoint(server, s, allowed_hosts) for name, s in server.surfaces.items()
    }

    async def health(_: Request) -> Response:
        return JSONResponse(
            {
                "ok": True,
                "server_version": server.version,
                "snapshots": sorted(k for k in server.libraries if k != "current"),
                "current": server.libraries["current"].snapshot
                if "current" in server.libraries
                else None,
                "surfaces": {n: s.surface_id for n, s in server.surfaces.items()},
            }
        )

    async def index(_: Request) -> Response:
        return JSONResponse(
            {
                "name": "SafetyPage",
                "mcp": "/mcp",
                "variants": {n: f"/x/{n}/mcp" for n in server.surfaces if n != "default"},
                "api": "/api/search?query=…",
                "health": "/health",
            }
        )

    routes: list[Route] = [
        Route("/", index, methods=["GET"]),
        Route("/health", health, methods=["GET"]),
        Route("/mcp", endpoints["default"].asgi, methods=["GET", "POST", "DELETE"]),
    ]
    for name, endpoint in endpoints.items():
        routes.append(Route(f"/x/{name}/mcp", endpoint.asgi, methods=["GET", "POST", "DELETE"]))
    routes += _api_routes(server)

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncGenerator[None]:
        async with contextlib.AsyncExitStack() as stack:
            for endpoint in endpoints.values():
                await stack.enter_async_context(endpoint.run())
            yield
        server.close()

    middleware = [
        Middleware(RateLimit, limits=server.limits),
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
            expose_headers=["X-Request-Id", "X-Snapshot", "X-Surface", "X-Arm", "X-Server-Version"],
        ),
    ]
    return Starlette(routes=routes, middleware=middleware, lifespan=lifespan)
