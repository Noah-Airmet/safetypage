# GraphQL JSON is untyped
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""LessWrong and Alignment Forum posts, through LessWrong's public GraphQL API.

Alignment Forum posts are LessWrong posts with the same id, so one endpoint serves both. Posts
are asked for in batches (one aliased query per batch), at LessWrong's robots.txt crawl delay of
3 seconds between requests. Each post's record (``postedAt``, ``url`` for link-posts, and
``contents { html version editedAt }``) is stored as the fetched response, keyed ``lw:<id>``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any, Final

from onthepage.ingest.fetch import Fetcher, FetchError

__all__ = ["ENDPOINT", "fetch_posts"]

ENDPOINT: Final = "https://www.lesswrong.com/graphql"
BATCH: Final = 10
_FIELDS: Final = "_id title postedAt modifiedAt url contents { version editedAt html }"


def fetch_posts(
    fetcher: Fetcher,
    post_ids: Sequence[str],
    *,
    refresh: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, str]:
    """Fetch every post not already stored. Returns the ids that failed, with the reason."""
    todo = [p for p in post_ids if refresh or fetcher.cached(f"lw:{p}") is None]
    failed: dict[str, str] = {}
    for start in range(0, len(todo), BATCH):
        batch = todo[start : start + BATCH]
        query = " ".join(
            f'p{i}: post(input: {{selector: {{_id: "{pid}"}}}}) {{ result {{ {_FIELDS} }} }}'
            for i, pid in enumerate(batch)
        )
        try:
            body: Any = fetcher.post_json(ENDPOINT, {"query": f"{{ {query} }}"})
        except FetchError as exc:
            for pid in batch:
                failed[pid] = exc.reason
            continue
        data: dict[str, Any] = (body or {}).get("data") or {}
        for i, pid in enumerate(batch):
            result = (data.get(f"p{i}") or {}).get("result")
            if not result or not (result.get("contents") or {}).get("html"):
                failed[pid] = "the API returned no post body"
                continue
            payload = json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")
            fetcher.record(f"lw:{pid}", payload, "application/json", ENDPOINT)
        if progress is not None:
            progress(min(start + BATCH, len(todo)), len(todo))
    return failed
