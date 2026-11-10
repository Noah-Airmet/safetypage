"""The overnight local-model run: start at 04:00, stop by 06:30, resume the next night.

    python -m safetypage.bench nightly [--until 06:25] [--dry-run]

For each configuration listed in ``citationbench/configs/nightly.txt``, in order:

1. skip it if its run is already complete;
2. make sure oMLX (a local model server) and a library server with a call log are up,
   starting them if not;
3. check free memory against the model's ``size_gb`` plus a margin (another overnight job, such
   as the search track's embeddings, may be using the machine), and skip the model if it does
   not fit tonight;
4. download it if the configuration says ``download = true`` and it is not on disk;
5. run its questions with the per-question runner until the window closes;
6. if the run is now complete and the configuration says ``delete_after = true``, delete the
   model's files from the Hugging Face cache (``~/.cache/huggingface/hub/models--<org>--<name>``).
   Models that were already on disk have no ``delete_after`` and are never deleted.

Anything this job started (oMLX, the library server) is stopped at the end; anything that was
already running is left running. A log goes to ``citationbench/work/nightly.log``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from .cli_run import run_cli, run_id_for
from .task import REPO

__all__ = ["available_gb", "nightly"]

PC = REPO / "citationbench"
LOG = PC / "work" / "nightly.log"
HF_HUB = Path.home() / ".cache" / "huggingface" / "hub"
MARGIN_GB = 6.0


def log(message: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")
    print(message, flush=True)


def available_gb() -> float:
    """Memory that can be had without swapping: free, inactive, speculative and purgeable
    pages, from ``vm_stat``."""
    out = subprocess.run(["vm_stat"], capture_output=True, text=True, check=True).stdout  # noqa: S607
    page = int(re.search(r"page size of (\d+)", out).group(1))  # type: ignore[union-attr]
    pages = 0
    for label in ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable"):
        m = re.search(rf"{label}:\s+(\d+)", out)
        pages += int(m.group(1)) if m else 0
    return pages * page / 1e9


def _up(url: str, key: str | None = None) -> bool:
    request = urllib.request.Request(url)  # noqa: S310
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(request, timeout=5) as r:  # noqa: S310
            return r.status == 200
    except OSError:
        return False


def _wait(url: str, key: str | None, seconds: int) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _up(url, key):
            return True
        time.sleep(5)
    return False


def _hf_dir(repo: str) -> Path:
    return HF_HUB / f"models--{repo.replace('/', '--')}"


def _complete(config: dict[str, Any]) -> bool:
    path = PC / "results" / f"{run_id_for(config)}.json"
    return path.is_file() and bool(json.loads(path.read_text(encoding="utf-8")).get("complete"))


def nightly(configs: list[dict[str, Any]], *, until: datetime, dry_run: bool = False) -> int:
    omlx = os.environ.get("OMLX_BASE_URL", "http://localhost:8000/v1").rstrip("/")
    key = os.environ.get("OMLX_API_KEY")
    started: list[str] = []
    server_proc: subprocess.Popen[bytes] | None = None
    try:
        todo = [c for c in configs if not _complete(c)]
        log(
            f"nightly: {len(todo)} of {len(configs)} configurations unfinished; until {until:%H:%M}"
        )
        if not todo or dry_run:
            for c in todo:
                log(
                    f"  would run {c['name']} ({c['model']}), needs {c.get('size_gb', '?')} GB; "
                    f"{available_gb():.1f} GB available now"
                )
            return 0
        if not _up(f"{omlx}/models", key):
            log("starting oMLX")
            subprocess.run(["open", "-g", "-a", "oMLX"], check=False)  # noqa: S607
            started.append("omlx")
            if not _wait(f"{omlx}/models", key, 240):
                log("oMLX did not come up; stopping")
                return 1
        server = str(todo[0].get("server", "http://localhost:8766"))
        if not _up(f"{server}/api/doc/arxiv/2305.15324"):
            port = server.rsplit(":", 1)[-1].split("/", maxsplit=1)[0]
            env = dict(
                os.environ,
                SAFETYPAGE_OPS_DB=str(
                    REPO / str(todo[0].get("ops_db", "citationbench/work/ops.sqlite"))
                ),
            )
            corpus = str(todo[0].get("corpus", "fixtures"))
            args = ["--fixtures"] if corpus == "fixtures" else ["--snapshot", corpus]
            log(f"starting the library server on port {port}")
            server_proc = subprocess.Popen(  # noqa: S603
                [shutil.which("uv") or "uv", "run", "--group", "server", "python", "-m",
                 "safetypage.server", *args, "--port", port, "--base-url", server],
                cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )  # fmt: skip
            if not _wait(f"{server}/api/doc/arxiv/2305.15324", None, 120):
                log("library server did not come up; stopping")
                return 1
        for config in todo:
            if datetime.now(until.tzinfo) >= until:
                break
            need = float(config.get("size_gb", 20)) + MARGIN_GB
            have = available_gb()
            if have < need:
                log(f"skip {config['name']}: needs {need:.0f} GB, {have:.1f} GB available")
                continue
            repo = config.get("hf_repo")
            if repo and not _hf_dir(str(repo)).exists():
                if not config.get("download"):
                    log(f"skip {config['name']}: {repo} is not downloaded and download is off")
                    continue
                log(f"downloading {repo}")
                subprocess.run(  # noqa: S603
                    [
                        shutil.which("uvx") or "uvx",
                        "--from",
                        "huggingface_hub",
                        "hf",
                        "download",
                        str(repo),
                    ],
                    check=True,
                )
            log(f"run {config['name']} ({config['model']})")
            outcome = run_cli(config, batch=10_000, until=until)
            log(f"  {outcome.done}/{outcome.planned} done; stopped: {outcome.stopped}")
            if outcome.done == outcome.planned and config.get("delete_after") and repo:
                path = _hf_dir(str(repo))
                if path.is_dir() and path.parent == HF_HUB:
                    log(f"  deleting {path}")
                    shutil.rmtree(path)
        return 0
    finally:
        if server_proc is not None:
            server_proc.terminate()
        if "omlx" in started:
            log("quitting oMLX (this job started it)")
            subprocess.run(["osascript", "-e", 'quit app "oMLX"'], check=False)  # noqa: S607
