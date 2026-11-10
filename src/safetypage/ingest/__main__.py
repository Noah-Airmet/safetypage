"""Command line for the ingest pipeline.

    uv run --group ingest python -m safetypage.ingest run                  # everything not yet done
    uv run --group ingest python -m safetypage.ingest run --shelf labs --limit 20
    uv run --group ingest python -m safetypage.ingest run --only anthropic:rsp
    uv run --group ingest python -m safetypage.ingest status               # write corpus/status/
    uv run --group ingest python -m safetypage.ingest prune                # drop rows scope dropped
    uv run --group ingest python -m safetypage.ingest prune --refetch ID   # and ingest ID afresh
    uv run --group ingest python -m safetypage.ingest add-file URL PATH    # a page a browser saved

The data directory (fetched files, corpus.sqlite, ingest.sqlite) is ``$SAFETYPAGE_DATA``, else
``data/`` at the repository root. It is gitignored: fetched files never go into the repository.
"""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
import sys
from pathlib import Path

from safetypage.ingest.items import WEB_SHELVES
from safetypage.ingest.pipeline import Pipeline

REPO = Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m safetypage.ingest")
    parser.add_argument(
        "--data", type=Path, default=Path(os.environ.get("SAFETYPAGE_DATA", REPO / "data"))
    )
    parser.add_argument("--scope", type=Path, default=REPO / "corpus" / "scope")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="fetch, extract and store everything not yet done")
    run.add_argument("--shelf", action="append", choices=[*WEB_SHELVES, "papers", "forum"])
    run.add_argument("--only", action="append", default=[], help="a doc id prefix or item key")
    run.add_argument("--limit", type=int)
    run.add_argument("--no-retry", action="store_true", help="leave earlier failures alone")
    run.add_argument(
        "--refresh", action="store_true", help="refetch; new bytes become new versions"
    )
    sub.add_parser("status", help="write corpus/status/ and print the summary")
    prune = sub.add_parser(
        "prune", help="remove documents the inventory no longer lists from the working corpus"
    )
    prune.add_argument(
        "--refetch", action="append", default=[], help="also remove this doc id, to ingest again"
    )
    add = sub.add_parser("add-file", help="store a file as the response for a URL")
    add.add_argument("url")
    add.add_argument("path", type=Path)
    add.add_argument("--media-type")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.ERROR)  # pdfium and trafilatura warn on every odd file

    pipeline = Pipeline(args.data, args.scope)
    if args.command == "run":
        counts = pipeline.run(
            shelves=tuple(args.shelf) if args.shelf else None,
            only=args.only,
            limit=args.limit,
            retry=not args.no_retry,
            refresh=args.refresh,
        )
        print(json.dumps(counts, indent=2))
        problems = pipeline.corpus.validate()
        print(f"Corpus.validate(): {len(problems)} problems")
        for problem in problems[:20]:
            print("  ", problem)
        pipeline.write_status(REPO / "corpus" / "status")
        return 1 if problems else 0
    if args.command == "prune":
        gone = pipeline.prune(args.refetch)
        print(f"removed {len(gone)} documents")
        for doc_id in gone:
            print("  ", doc_id)
        return 0
    if args.command == "status":
        print(json.dumps(pipeline.write_status(REPO / "corpus" / "status"), indent=2))
        return 0
    media = args.media_type or mimetypes.guess_type(args.path.name)[0] or "text/html"
    fetched = pipeline.fetcher.record(args.url, args.path.read_bytes(), media)
    print(
        f"stored {fetched.bytes} bytes for {args.url} ({fetched.sha256[:12]}); run again to ingest"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
