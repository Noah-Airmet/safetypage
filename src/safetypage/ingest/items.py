"""The inventory in ``corpus/scope/``, read as a list of things to fetch.

One :class:`Item` per inventory row. Rows that share a ``doc_id`` are versions of one document,
taken oldest first. Papers and forum posts carry no ``doc_id`` in their files; theirs is derived
here (``arxiv:<id>``, ``acl:<id>``, ``openreview:<id>``, ``lw:<post id>``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from safetypage.model import DocKind

__all__ = ["WEB_SHELVES", "Item", "load_items"]

WEB_SHELVES = ("labs", "lab-research-web", "evaluators", "government", "welfare")

Adapter = Literal["web", "arxiv", "lw"]

_KINDS: dict[str, DocKind] = {
    "system_card": "system_card",
    "model_card": "model_card",
    "safety_framework": "framework",
    "framework": "framework",
    "framework_profile": "framework",
    "evaluation_report": "eval_report",
    "red_team_report": "eval_report",
    "safety_report": "eval_report",
    "independent_report": "eval_report",
    "research_paper": "paper",
    "research_pdf": "paper",
    "paper": "paper",
    "technical_report": "paper",
    "blog_post": "blog",
    "research_post": "blog",
    "research_update": "blog",
    "note": "blog",
    "lab_post": "blog",
}


@dataclass(frozen=True)
class Item:
    key: str
    """Unique per inventory row: the URL it is fetched from, or the source's own id."""
    shelf: str
    doc_id: str
    adapter: Adapter
    url: str
    """What is fetched (for ``lw``, the post id is in ``doc_id``)."""
    source_url: str
    """The page a person opens."""
    kind: DocKind
    title: str
    authors: list[str]
    org: str | None
    published: str | None
    licence: str
    licence_evidence: str
    label: str | None = None
    """The publisher's version label (arXiv ``v3``); None means we number it ``r<n>``."""
    extra: dict[str, Any] = field(default_factory=dict[str, Any])


def _date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    m = re.match(r"\d{4}(-\d{2}(-\d{2})?)?", value)
    return m.group(0) if m else None


def _authors(row: dict[str, Any]) -> list[str]:
    """Names as people write them: some sources list "Olah, Chris"; we store "Chris Olah"."""
    names: list[str] = []
    listed: list[Any] = list(row.get("authors") or [])
    for name in map(str, listed):
        surname, comma, given = name.partition(", ")
        names.append(f"{given} {surname}" if comma and "," not in given else name)
    return names


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _web(shelf: str, row: dict[str, Any]) -> Item:
    kind = _KINDS.get(row["doc_type"]) or ("government" if shelf == "government" else "article")
    return Item(
        key=row["url"],
        shelf=shelf,
        doc_id=row["doc_id"],
        adapter="web",
        url=row["url"],
        source_url=row["url"],
        kind=kind,
        title=row["title"],
        authors=_authors(row),
        org=row["publisher"].split(" (")[0].strip() or None,
        published=_date(row.get("date")),
        licence=row["licence"],
        licence_evidence=row.get("licence_evidence") or "",
    )


def _paper(row: dict[str, Any]) -> Item | None:
    common: dict[str, Any] = {
        "shelf": "papers",
        "kind": "paper",
        "title": row["title"],
        "authors": _authors(row),
        "org": None,
        "published": _date(row.get("date")),
        "licence": row["licence"],
        "licence_evidence": row.get("licence_evidence") or "",
    }
    acl_id = row.get("acl_id")
    evidence = (row.get("licence_evidence") or "").lower()
    if acl_id and (not row.get("arxiv_id") or "anthology" in evidence):
        # The ACL Anthology PDF is the venue's version of record, and its licence is ACL's.
        pdf = row.get("pdf_url") or f"https://aclanthology.org/{acl_id}.pdf"
        page = f"https://aclanthology.org/{acl_id}/"
        return Item(
            key=pdf, doc_id=f"acl:{acl_id}", adapter="web", url=pdf, source_url=page, **common
        )
    if row.get("arxiv_id"):
        arxiv_id: str = row["arxiv_id"]
        latest = row["versions"][-1] if row.get("versions") else {"version": "v1"}
        label = latest["version"]
        return Item(
            key=f"arxiv:{arxiv_id}",
            doc_id=f"arxiv:{arxiv_id.replace('/', '.')}",
            adapter="arxiv",
            url=arxiv_id,
            source_url=f"https://arxiv.org/abs/{arxiv_id}{label}",
            label=label,
            extra={"version_date": latest.get("date")},
            **common,
        )
    pdf = row.get("pdf_url") or ""
    m = re.search(r"openreview\.net/(?:pdf|forum)\?id=([A-Za-z0-9_-]+)", pdf)
    if m:
        return Item(
            key=pdf,
            doc_id=f"openreview:{m.group(1)}",
            adapter="web",
            url=pdf,
            source_url=row.get("url") or pdf,
            **common,
        )
    if pdf:
        local = re.sub(r"[^A-Za-z0-9._-]+", "-", pdf.split("//", 1)[-1]).strip("-.")[:80]
        return Item(
            key=pdf, doc_id=f"paper:{local}", adapter="web", url=pdf, source_url=pdf, **common
        )
    return None


def _post(row: dict[str, Any]) -> Item:
    return Item(
        key=f"lw:{row['post_id']}",
        shelf="forum",
        doc_id=f"lw:{row['post_id']}",
        adapter="lw",
        url=row["post_id"],
        source_url=row["url"],
        kind="forum_post",
        title=row["title"],
        authors=_authors(row),
        org="Alignment Forum" if row.get("af") else "LessWrong",
        published=_date(row.get("date")),
        licence=row["licence"],
        licence_evidence=row.get("licence_evidence") or "",
        extra={"crosspost": row.get("crosspost")},
    )


def load_items(scope: Path, shelves: tuple[str, ...] | None = None) -> tuple[list[Item], list[str]]:
    """Every item on the chosen shelves, and the inventory rows that cannot be fetched at all."""
    items: list[Item] = []
    unfetchable: list[str] = []
    wanted = shelves or (*WEB_SHELVES, "papers", "forum")
    for shelf in WEB_SHELVES:
        if shelf in wanted:
            items += [_web(shelf, row) for row in _rows(scope / f"{shelf}.jsonl")]
    if "papers" in wanted and (scope / "papers.jsonl").exists():
        for row in _rows(scope / "papers.jsonl"):
            item = _paper(row)
            if item is None:
                unfetchable.append(row["title"])
            else:
                items.append(item)
    if "forum" in wanted and (scope / "forum-posts.jsonl").exists():
        items += [_post(row) for row in _rows(scope / "forum-posts.jsonl")]
    return items, unfetchable
