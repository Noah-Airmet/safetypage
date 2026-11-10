"""The official MCP conformance suite against the server, over a real socket.

Opt-in (it needs Node and fetches the suite with npx): ``ONTHEPAGE_CONFORMANCE=1 uv run pytest
tests/server/test_conformance.py``. Only the scenarios that apply to a tools-only server run; the
rest of the suite calls the suite's own reference tools (``test_image_content`` and so on),
resources and prompts, which this server does not have by design.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn

from onthepage.server.app import Server, build_app

SUITE = "@modelcontextprotocol/conformance@0.1.16"
SCENARIOS = ["server-initialize", "ping", "tools-list", "dns-rebinding-protection"]

pytestmark = pytest.mark.skipif(
    os.environ.get("ONTHEPAGE_CONFORMANCE") != "1" or shutil.which("npx") is None,
    reason="set ONTHEPAGE_CONFORMANCE=1 (needs npx) to run the MCP conformance suite",
)


@pytest.fixture
def url(server: Server) -> Iterator[str]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = build_app(server, allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"])
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    runner = uvicorn.Server(config)
    thread = threading.Thread(target=runner.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not runner.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    runner.should_exit = True
    thread.join(5)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_conformance(url: str, scenario: str) -> None:
    npx = shutil.which("npx") or "npx"
    done = subprocess.run(
        [npx, "-y", SUITE, "server", "--url", url, "--scenario", scenario],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    output = done.stdout + done.stderr
    assert done.returncode == 0 and " 0 failed" in output, output[-3000:]
