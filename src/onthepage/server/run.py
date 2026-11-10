"""Load snapshots and surfaces, and run the server.

    python -m onthepage.server --fixtures                 # the fixture corpus, for development
    python -m onthepage.server --data /data               # every sealed snapshot under /data

Settings come from flags or the environment (flags win):

``ONTHEPAGE_DATA``           data root holding ``snapshots/`` (and, by default, ``ops.sqlite``)
``ONTHEPAGE_BASE_URL``       the public origin citation URLs are minted from
``ONTHEPAGE_STATIC_URL``     where ``public/`` is served, for page image links (default: base URL)
``ONTHEPAGE_OPS_DB``         the call log (default ``<data>/ops.sqlite``; ``none`` disables it)
``ONTHEPAGE_ALLOWED_HOSTS``  comma-separated Host values to accept (DNS-rebinding protection)
``ONTHEPAGE_TRUST_PROXY``    ``1`` behind a proxy that sets CF-Connecting-IP / X-Forwarded-For
``ONTHEPAGE_TIMEOUT``        per-call time limit in seconds (default 10)
"""

from __future__ import annotations

import argparse
import importlib
import logging
import os
import tempfile
from pathlib import Path

from onthepage.api import SearchBackend
from onthepage.bundle import load_bundles
from onthepage.corpus import Corpus
from onthepage.server.app import Limits, Server, build_app
from onthepage.server.backend import MemoryBackend
from onthepage.server.library import Library, open_readonly
from onthepage.server.oplog import OpsLog
from onthepage.server.surfaces import load_surfaces
from onthepage.snapshot import list_snapshots, resolve_snapshot

__all__ = ["fixture_library", "load_server", "main", "open_backend"]

log = logging.getLogger("onthepage.server")

FIXTURE_BUNDLES = Path(__file__).resolve().parents[3] / "fixtures" / "corpus" / "bundles"


def open_backend(snapshot_dir: Path, snapshot_id: str, base_url: str) -> SearchBackend:
    """The snapshot's Tantivy backend when it has one, else the in-memory backend."""
    if (snapshot_dir / "lexical").is_dir():
        try:
            search = importlib.import_module("onthepage.search")
            opener = search.open_backend
        except (ImportError, AttributeError):
            log.warning(
                "%s has a lexical index but onthepage.search.open_backend is missing", snapshot_id
            )
        else:
            return opener(snapshot_dir)  # pyright: ignore[reportUnknownVariableType]
    corpus = open_readonly(snapshot_dir / "corpus.sqlite", base_url)
    try:
        return MemoryBackend(corpus, snapshot=snapshot_id)
    finally:
        corpus.close()


def fixture_library(base_url: str, directory: Path | None = None) -> Library:
    """The checked-in fixture corpus as a library, with the in-memory backend."""
    directory = directory or Path(tempfile.mkdtemp(prefix="onthepage-fixtures-"))
    path = directory / "corpus.sqlite"
    if not path.exists():
        with Corpus.open(path, base_url=base_url) as corpus:
            load_bundles(corpus, FIXTURE_BUNDLES)
    corpus = open_readonly(path, base_url)
    try:
        backend = MemoryBackend(corpus, snapshot="fixtures")
    finally:
        corpus.close()
    return Library(path, backend, base_url=base_url)


def load_server(
    *,
    data: Path | None,
    fixtures: bool,
    base_url: str,
    static_url: str | None = None,
    ops_db: Path | None = None,
    limits: Limits | None = None,
) -> Server:
    libraries: dict[str, Library] = {}
    if fixtures:
        libraries["fixtures"] = libraries["current"] = fixture_library(base_url)
    elif data is not None:
        for snapshot_id in list_snapshots(data):
            directory = resolve_snapshot(data, snapshot_id)
            libraries[snapshot_id] = Library(
                directory / "corpus.sqlite",
                open_backend(directory, snapshot_id, base_url),
                base_url=base_url,
                public_dir=directory / "public",
                static_url=static_url,
            )
        current = resolve_snapshot(data).name
        libraries["current"] = libraries[current]
    else:
        raise SystemExit("give --data <root> or --fixtures")
    return Server(libraries, load_surfaces(), OpsLog(ops_db), limits or Limits())


def main(argv: list[str] | None = None) -> None:
    env = os.environ.get
    data_env = env("ONTHEPAGE_DATA")
    parser = argparse.ArgumentParser(
        prog="python -m onthepage.server", description="Run the On the Page search server."
    )
    parser.add_argument("--data", type=Path, default=Path(data_env) if data_env else None)
    parser.add_argument(
        "--fixtures", action="store_true", help="serve the checked-in fixture corpus"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--base-url", default=env("ONTHEPAGE_BASE_URL"))
    args = parser.parse_args(argv)

    import uvicorn  # noqa: PLC0415

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    base_url = args.base_url or f"http://{args.host}:{args.port}"
    ops = env("ONTHEPAGE_OPS_DB")
    ops_db = (
        None
        if ops == "none"
        else Path(ops)
        if ops
        else (args.data / "ops.sqlite" if args.data else None)
    )
    limits = Limits(
        timeout_s=float(env("ONTHEPAGE_TIMEOUT", "10")),
        trust_proxy=env("ONTHEPAGE_TRUST_PROXY") == "1",
    )
    server = load_server(
        data=args.data,
        fixtures=args.fixtures,
        base_url=base_url,
        static_url=env("ONTHEPAGE_STATIC_URL"),
        ops_db=ops_db,
        limits=limits,
    )
    hosts = [h.strip() for h in (env("ONTHEPAGE_ALLOWED_HOSTS") or "").split(",") if h.strip()]
    if not hosts and args.host in ("127.0.0.1", "localhost"):
        hosts = ["127.0.0.1:*", "localhost:*"]
    app = build_app(server, allowed_hosts=hosts or None)
    uvicorn.run(
        app, host=args.host, port=args.port, proxy_headers=limits.trust_proxy, log_level="info"
    )
