"""The document model: what ingestion writes and everything else reads.

    Document        arxiv:2305.15324           one work, with a permanent id
     └ Version      v1, v2 ...                 one immutable state of its bytes
        ├ Rendition pdf | html | latex | text  the raw file, in the blob store by content hash
        ├ Page      p1 ... pN                  a paged version's text of record (the PDF text layer)
        └ Block     b1 ... bN                  paragraphs, headings, figures: the unit of citation
                                               for an unpaged version, a structure overlay for a
                                               paged one

Input types (``NewPage``, ``NewBlock``) are what a caller hands to
:class:`safetypage.corpus.Corpus`; the stored types add
what storage computes (spine offsets, minted anchors, the tier).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from safetypage.licence import Tier

__all__ = [
    "AnchorKindName",
    "Block",
    "BlockKind",
    "DocKind",
    "Document",
    "Fidelity",
    "NewBlock",
    "NewPage",
    "OutlineEntry",
    "Page",
    "Rendition",
    "RenditionKind",
    "Version",
]

DocKind = Literal[
    "paper",
    "system_card",
    "model_card",
    "framework",
    "eval_report",
    "forum_post",
    "blog",
    "article",
    "government",
    "book",
]
AnchorKindName = Literal["page", "block"]
Fidelity = Literal["text_layer", "html", "ocr"]
RenditionKind = Literal["pdf", "html", "latex", "text"]
BlockKind = Literal[
    "heading",
    "paragraph",
    "list_item",
    "caption",
    "figure",
    "table",
    "equation",
    "footnote",
    "quote",
    "code",
    "reference",
]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Document(_Model):
    doc_id: str
    kind: DocKind
    title: str
    authors: list[str] = Field(default_factory=list[str])
    org: str | None = None
    collection: str | None = None
    published: str | None = None
    """``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD``."""
    source_url: str
    added_at: str | None = None


class Version(_Model):
    version_id: int
    doc_id: str
    label: str
    seq: int
    anchor_kind: AnchorKindName
    fidelity: Fidelity
    published: str | None
    observed_at: str
    source_url: str
    content_sha256: str
    licence: str
    tier: Tier

    @property
    def paged(self) -> bool:
        return self.anchor_kind == "page"

    @property
    def ref(self) -> str:
        return f"{self.doc_id}/{self.label}"


class Rendition(_Model):
    kind: RenditionKind
    sha256: str
    bytes: int
    media_type: str
    source_url: str
    fetched_at: str


class NewPage(_Model):
    """One PDF page, in physical order. ``text`` is the text layer exactly as extracted."""

    text: str
    label: str | None = None
    width: float | None = None
    height: float | None = None
    words: list[tuple[int, int, float, float, float, float]] | None = None
    """``(char_start, char_end, x0, y0, x1, y1)`` per word: offsets into ``text``, PDF points."""


class Page(_Model):
    version_id: int
    page: int
    label: str | None
    width: float | None
    height: float | None
    text: str
    spine_start: int
    spine_end: int


class NewBlock(_Model):
    kind: BlockKind
    text: str
    level: int | None = None
    label: str | None = None
    section: list[str] = Field(default_factory=list[str])
    source_id: str | None = None
    spine_start: int | None = None
    """Paged versions only: where this block's text sits in the page spine, if it was placed."""
    spine_end: int | None = None
    bbox: tuple[int, float, float, float, float] | None = None


class Block(_Model):
    version_id: int
    anchor: int
    seq: int
    kind: BlockKind
    level: int | None
    label: str | None
    section: list[str]
    text: str
    spine_start: int | None
    spine_end: int | None
    page_start: int | None
    page_end: int | None
    source_id: str | None


class OutlineEntry(_Model):
    level: int
    title: str
    anchor: str
