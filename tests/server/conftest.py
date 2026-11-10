from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
import pytest
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette

from safetypage.server.app import Limits, Server, build_app
from safetypage.server.library import Library
from safetypage.server.oplog import OpsLog
from safetypage.server.run import fixture_library
from safetypage.server.surfaces import load_surfaces

BASE_URL = "https://safetypage.test"


@pytest.fixture(scope="session")
def lib(tmp_path_factory: pytest.TempPathFactory) -> Library:
    return fixture_library(BASE_URL, tmp_path_factory.mktemp("server-corpus"))


@pytest.fixture
def ops_path(tmp_path: Path) -> Path:
    return tmp_path / "ops.sqlite"


@pytest.fixture
def server(lib: Library, ops_path: Path) -> Iterator[Server]:
    srv = Server({"fixtures": lib, "current": lib}, load_surfaces(), OpsLog(ops_path), Limits())
    yield srv
    srv.ops.close()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@asynccontextmanager
async def running(app: Starlette) -> AsyncGenerator[httpx2.AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as http:
            yield http


@pytest.fixture
async def http(server: Server) -> AsyncGenerator[httpx2.AsyncClient]:
    async with running(build_app(server)) as client:
        yield client


@asynccontextmanager
async def mcp_client(
    http: httpx2.AsyncClient, path: str = "/mcp", headers: dict[str, str] | None = None
) -> AsyncGenerator[Client]:
    if headers:
        http.headers.update(headers)
    async with Client(
        streamable_http_client(f"http://testserver{path}", http_client=http)
    ) as client:
        yield client
