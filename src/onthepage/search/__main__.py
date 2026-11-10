"""Command line: build a snapshot, embed units, run a query, measure latency.

    python -m onthepage.search build   --root data --id 2026.11.0 [--current] [--no-images]
    python -m onthepage.search embed   --root data             (overnight: stops at 06:00)
    python -m onthepage.search query   --root data [--snapshot 2026.11.0] "sparse autoencoder*"
    python -m onthepage.search latency --root data [--snapshot ...]

``--root`` is the data root: ``corpus.sqlite``, ``blobs/``, ``snapshots/``, ``embeddings/``.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

from onthepage.api import SearchRequest
from onthepage.corpus import Corpus
from onthepage.search.dense import (
    DEFAULT_MODEL,
    SentenceTransformerEmbedder,
    embed_units,
    model_slug,
    night_window_stop,
)
from onthepage.search.errors import SearchError
from onthepage.snapshot import resolve_snapshot

LATENCY_QUERIES = (
    "alignment",
    "sparse autoencoder",
    '"reward hacking"',
    '"model organisms"',
    "interpret*",
    "deceptive NEAR/5 alignment",
    '"in the"',
    "the of and",
    "constitutional -classifier",
    '"responsible scaling policy"',
)


def _log(message: str) -> None:
    print(f"{datetime.now():%H:%M:%S} {message}", file=sys.stderr, flush=True)


def _build(args: argparse.Namespace) -> int:
    from onthepage.build.snapshot import build_snapshot  # noqa: PLC0415  (build group only)

    root: Path = args.root
    manifest = build_snapshot(
        root / "corpus.sqlite",
        root,
        args.id,
        images=not args.no_images,
        dense_model=None if args.no_dense else args.model,
        make_current=args.current,
        base_url=args.base_url,
        workers=args.workers,
        log=_log,
    )
    print(manifest.model_dump_json(indent=2, include={"snapshot_id", "counts", "components"}))
    return 0


def _embed(args: argparse.Namespace) -> int:
    hour = datetime.now().hour
    if not args.now and 6 <= hour < 22:
        print(
            "Local model work runs 22:00-06:00. Start this at night, or pass --now.",
            file=sys.stderr,
        )
        return 2
    cache = args.root / "embeddings" / model_slug(args.model)
    embedder = SentenceTransformerEmbedder(args.model, device=args.device)
    with Corpus.open(args.root / "corpus.sqlite", readonly=True) as corpus:
        report = embed_units(
            corpus,
            cache,
            embedder,
            stop=(lambda: False) if args.now else night_window_stop(6),
            log=_log,
        )
    print(report)
    return 0


def _backend(args: argparse.Namespace):
    from onthepage.search.backend import SnapshotSearch  # noqa: PLC0415

    return SnapshotSearch(resolve_snapshot(args.root, args.snapshot), base_url=args.base_url)


def _query(args: argparse.Namespace) -> int:
    backend = _backend(args)
    request = SearchRequest(
        query=args.query,
        arm=args.arm,
        mode=args.mode,
        limit=args.limit,
        kind=args.kind,
        org=args.org,
        collection=args.collection,
        doc=args.doc,
        date_from=args.date_from,
        date_to=args.date_to,
    )
    started = time.perf_counter()
    try:
        response = backend.search(request)
    except SearchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        backend.close()
    elapsed = (time.perf_counter() - started) * 1000
    if args.json:
        print(response.model_dump_json(indent=2))
        return 0
    print(f"{response.total} matches in {elapsed:.1f} ms ({response.arm}, {response.snapshot})")
    print(response.interpretation)
    for hit in response.hits:
        marked, last = "", 0
        for start, end in hit.match_spans:
            marked += hit.snippet[last:start] + "[" + hit.snippet[start:end] + "]"
            last = end
        marked += hit.snippet[last:]
        print(f"\n{hit.cite}  {hit.anchor_label}  ({hit.tier}, {hit.score:.3f})")
        print(f"  {hit.doc_title}")
        print(f"  {marked}")
    for doc in response.documents:
        print(f"\n{doc.doc_id}/{doc.version}  {doc.hit_count} hits  {doc.title}")
    return 0


def _latency(args: argparse.Namespace) -> int:
    backend = _backend(args)
    try:
        print(f"snapshot {backend.snapshot}, arm {args.arm}, {args.runs} runs each, warm")
        print(f"{'query':32} {'total':>9} {'median ms':>10} {'max ms':>8}")
        for query in LATENCY_QUERIES:
            request = SearchRequest(query=query, arm=args.arm, limit=10)
            times: list[float] = []
            total = 0
            for _ in range(args.runs + 1):
                started = time.perf_counter()
                try:
                    total = backend.search(request).total
                except SearchError as exc:
                    total = -1
                    print(f"{query:32} error: {exc}")
                    break
                times.append((time.perf_counter() - started) * 1000)
            if times[1:]:
                print(
                    f"{query:32} {total:>9} {statistics.median(times[1:]):>10.1f} "
                    f"{max(times[1:]):>8.1f}"
                )
    finally:
        backend.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m onthepage.search")
    parser.add_argument("--root", type=Path, default=Path("data"))
    parser.add_argument("--base-url", default="http://localhost:8000")
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="build and seal a snapshot")
    build.add_argument("--id", required=True, help="YYYY.MM.N")
    build.add_argument("--current", action="store_true", help="point current at it")
    build.add_argument("--no-images", action="store_true")
    build.add_argument("--no-dense", action="store_true")
    build.add_argument("--model", default=DEFAULT_MODEL)
    build.add_argument("--workers", type=int, default=None)
    build.set_defaults(run=_build)

    embed = commands.add_parser("embed", help="embed units into the cache (resumable)")
    embed.add_argument("--model", default=DEFAULT_MODEL)
    embed.add_argument("--device", default="mps")
    embed.add_argument("--now", action="store_true", help="run outside 22:00-06:00, no stop")
    embed.set_defaults(run=_embed)

    for name, run in (("query", _query), ("latency", _latency)):
        sub = commands.add_parser(name)
        sub.add_argument("--snapshot", default="current")
        sub.add_argument("--arm", default="bm25")
        sub.set_defaults(run=run)
        if name == "latency":
            sub.add_argument("--runs", type=int, default=5)
            continue
        sub.add_argument("query")
        sub.add_argument("--mode", default="units", choices=["units", "documents"])
        sub.add_argument("--limit", type=int, default=10)
        sub.add_argument("--json", action="store_true")
        for field in ("kind", "org", "collection", "doc", "date-from", "date-to"):
            sub.add_argument(f"--{field}")

    args = parser.parse_args(argv)
    return int(args.run(args))


if __name__ == "__main__":
    sys.exit(main())
