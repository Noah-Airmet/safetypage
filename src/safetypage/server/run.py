"""Load snapshots and surfaces, and run the server.

    python -m safetypage.server --fixtures                 # the fixture corpus, for development
    python -m safetypage.server --data /data               # every sealed snapshot under /data
    python -m safetypage.server --snapshot /snapshot       # one sealed snapshot directory

Settings come from flags or the environment (flags win):

``SAFETYPAGE_DATA``           data root holding ``snapshots/`` (and, by default, ``ops.sqlite``)
``SAFETYPAGE_SNAPSHOT``       one sealed snapshot directory, instead of a data root
``SAFETYPAGE_BASE_URL``       the public origin citation URLs are minted from
``SAFETYPAGE_STATIC_URL``     where ``public/`` is served, for page image links (default: base URL)
``SAFETYPAGE_OPS_DB``         the call log (default ``<data>/ops.sqlite``; ``none`` disables it)
``SAFETYPAGE_ALLOWED_HOSTS``  comma-separated Host values to accept (DNS-rebinding protection)
``SAFETYPAGE_TRUST_PROXY``    ``1`` behind a proxy that sets CF-Connecting-IP / X-Forwarded-For
``SAFETYPAGE_TIMEOUT``        per-call time limit in seconds (default 10)
"""

from __future__ import annotations

import argparse
import importlib
import logging
import os
import tempfile
from pathlib import Path

from safetypage.api import SearchBackend
from safetypage.bundle import load_bundles
from safetypage.corpus import Corpus
from safetypage.server.app import Limits, Server, build_app
from safetypage.server.backend import MemoryBackend
from safetypage.server.library import Library, open_readonly
from safetypage.server.oplog import OpsLog
from safetypage.server.surfaces import load_surfaces
from safetypage.snapshot import list_snapshots, load_manifest, resolve_snapshot

__all__ = ["fixture_library", "load_server", "main", "open_backend", "snapshot_library"]

log = logging.getLogger("safetypage.server")

FIXTURE_BUNDLES = Path(__file__).resolve().parents[3] / "fixtures" / "corpus" / "bundles"


def open_backend(snapshot_dir: Path, snapshot_id: str, base_url: str) -> SearchBackend:
    """The search track's Tantivy backend when the snapshot has an index, else the in-memory one."""
    if (snapshot_dir / "lexical").is_dir():
        try:
            module = importlib.import_module("safetypage.search.backend")
        except ImportError:
            log.warning(
                "%s has a lexical index but safetypage.search is not installed", snapshot_id
            )
        else:
            backend: SearchBackend = module.SnapshotSearch(snapshot_dir, base_url=base_url)
            return backend
    corpus = open_readonly(snapshot_dir / "corpus.sqlite", base_url)
    try:
        return MemoryBackend(corpus, snapshot=snapshot_id)
    finally:
        corpus.close()


def fixture_library(base_url: str, directory: Path | None = None) -> Library:
    """The checked-in fixture corpus as a library, with the in-memory backend."""
    directory = directory or Path(tempfile.mkdtemp(prefix="safetypage-fixtures-"))
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


def snapshot_library(directory: Path, base_url: str, static_url: str | None = None) -> Library:
    """One sealed snapshot directory as a library."""
    snapshot_id = load_manifest(directory).snapshot_id
    return Library(
        directory / "corpus.sqlite",
        open_backend(directory, snapshot_id, base_url),
        base_url=base_url,
        public_dir=directory / "public",
        static_url=static_url,
    )


def load_server(
    *,
    data: Path | None,
    fixtures: bool,
    snapshot: Path | None = None,
    base_url: str,
    static_url: str | None = None,
    ops_db: Path | None = None,
    limits: Limits | None = None,
) -> Server:
    libraries: dict[str, Library] = {}
    if fixtures:
        libraries["fixtures"] = libraries["current"] = fixture_library(base_url)
    elif snapshot is not None:
        library = snapshot_library(snapshot, base_url, static_url)
        libraries[library.snapshot] = libraries["current"] = library
    elif data is not None:
        for snapshot_id in list_snapshots(data):
            directory = resolve_snapshot(data, snapshot_id)
            libraries[snapshot_id] = snapshot_library(directory, base_url, static_url)
        current = load_manifest(resolve_snapshot(data)).snapshot_id
        libraries["current"] = libraries[current]
    else:
        raise SystemExit("give --data <root>, --snapshot <dir> or --fixtures")
    return Server(libraries, load_surfaces(), OpsLog(ops_db), limits or Limits())


def main(argv: list[str] | None = None) -> None:
    env = os.environ.get
    data_env = env("SAFETYPAGE_DATA")
    snapshot_env = env("SAFETYPAGE_SNAPSHOT")
    parser = argparse.ArgumentParser(
        prog="python -m safetypage.server", description="Run the SafetyPage search server."
    )
    parser.add_argument("--data", type=Path, default=Path(data_env) if data_env else None)
    parser.add_argument(
        "--snapshot", type=Path, default=Path(snapshot_env) if snapshot_env else None
    )
    parser.add_argument(
        "--fixtures", action="store_true", help="serve the checked-in fixture corpus"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--base-url", default=env("SAFETYPAGE_BASE_URL"))
    args = parser.parse_args(argv)

    import uvicorn  # noqa: PLC0415

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    base_url = args.base_url or f"http://{args.host}:{args.port}"
    ops = env("SAFETYPAGE_OPS_DB")
    ops_db = (
        None
        if ops == "none"
        else Path(ops)
        if ops
        else (args.data / "ops.sqlite" if args.data else None)
    )
    limits = Limits(
        timeout_s=float(env("SAFETYPAGE_TIMEOUT", "10")),
        trust_proxy=env("SAFETYPAGE_TRUST_PROXY") == "1",
    )
    server = load_server(
        data=args.data,
        fixtures=args.fixtures,
        snapshot=args.snapshot,
        base_url=base_url,
        static_url=env("SAFETYPAGE_STATIC_URL"),
        ops_db=ops_db,
        limits=limits,
    )
    hosts = [h.strip() for h in (env("SAFETYPAGE_ALLOWED_HOSTS") or "").split(",") if h.strip()]
    if not hosts and args.host in ("127.0.0.1", "localhost"):
        hosts = ["127.0.0.1:*", "localhost:*"]
    app = build_app(server, allowed_hosts=hosts or None)
    uvicorn.run(
        app, host=args.host, port=args.port, proxy_headers=limits.trust_proxy, log_level="info"
    )
