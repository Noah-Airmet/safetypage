"""JSON Schemas for the wire contracts, generated from the Pydantic models.

``schemas/*.schema.json`` is checked in so the TypeScript side (the site, the edge Worker) can
build against it without running Python. A test fails if the files are out of date.

    uv run python -m onthepage.schemas          # rewrite schemas/
    uv run python -m onthepage.schemas --check  # exit 1 if they are stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel

from onthepage import api, snapshot, trace

__all__ = ["MODELS", "render", "write"]

MODELS: dict[str, type[BaseModel]] = {
    "search-request": api.SearchRequest,
    "search-response": api.SearchResponse,
    "fetch-request": api.FetchRequest,
    "fetch-result": api.FetchResult,
    "verify-quote-request": api.VerifyQuoteRequest,
    "quote-check": api.QuoteCheck,
    "answer-audit": api.AnswerAudit,
    "document-card": api.DocumentCard,
    "unit-text": api.UnitText,
    "response-meta": api.ResponseMeta,
    "trace": trace.Trace,
    "snapshot-manifest": snapshot.Manifest,
}


def render() -> dict[str, str]:
    """File name -> file content for every schema."""
    out: dict[str, str] = {}
    for name, model in MODELS.items():
        schema = model.model_json_schema(by_alias=True)
        out[f"{name}.schema.json"] = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    return out


def write(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, content in render().items():
        path = directory / name
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def stale(directory: Path) -> list[str]:
    """Names of schema files that are missing, out of date, or no longer generated."""
    expected = render()
    problems = [
        name
        for name, content in expected.items()
        if not (directory / name).is_file()
        or (directory / name).read_text(encoding="utf-8") != content
    ]
    if directory.is_dir():
        problems += [p.name for p in directory.glob("*.schema.json") if p.name not in expected]
    return sorted(problems)


def main(argv: list[str]) -> int:
    directory = Path("schemas")
    if "--check" in argv:
        problems = stale(directory)
        for name in problems:
            print(f"stale: {directory / name}", file=sys.stderr)
        return 1 if problems else 0
    for path in write(directory):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
