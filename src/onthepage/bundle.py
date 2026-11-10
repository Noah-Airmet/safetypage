"""The hand-off from ingestion to storage: one JSON document per version.

A bundle is everything known about one version of one document: its catalogue record, how its
licence is known, its raw files (by hash), and its text of record as pages or blocks. Ingestion
writes bundles; :func:`import_bundle` is the only code that turns one into rows, so the
invariants in :class:`onthepage.corpus.Corpus` hold however the bundle was produced.

The fixture corpus in ``fixtures/corpus/bundles/`` is a set of these.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from onthepage.corpus import Corpus, CorpusError
from onthepage.licence import EvidenceKind, LicenceFact
from onthepage.model import (
    AnchorKindName,
    Document,
    Fidelity,
    NewBlock,
    NewPage,
    OutlineEntry,
    Rendition,
    Version,
)
from onthepage.text import is_clean

__all__ = ["Bundle", "BundleLicence", "BundleVersion", "import_bundle", "load_bundles"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BundleVersion(_Model):
    label: str
    anchor_kind: AnchorKindName
    fidelity: Fidelity
    source_url: str
    content_sha256: str
    observed_at: str
    published: str | None = None


class BundleLicence(_Model):
    licence: str
    evidence_kind: EvidenceKind
    evidence_url: str
    evidence_quote: str
    observed_at: str
    producer: str
    evidence_sha256: str | None = None

    def fact(self) -> LicenceFact:
        return LicenceFact(**self.model_dump())


class Bundle(_Model):
    document: Document
    version: BundleVersion
    licence: BundleLicence | None
    """None when the licence is not known. Unknown is link-only."""
    renditions: list[Rendition] = Field(default_factory=list[Rendition])
    pages: list[NewPage] = Field(default_factory=list[NewPage])
    blocks: list[NewBlock] = Field(default_factory=list[NewBlock])
    outline: list[OutlineEntry] = Field(default_factory=list[OutlineEntry])


def import_bundle(corpus: Corpus, bundle: Bundle) -> Version:
    """Write one version into the corpus. The document row is created on its first version."""
    texts = [p.text for p in bundle.pages] + [b.text for b in bundle.blocks]
    if not all(is_clean(t) for t in texts):
        raise CorpusError(
            f"{bundle.document.doc_id}/{bundle.version.label}: text must go through "
            "onthepage.text.clean_text before it is stored"
        )
    if corpus.document(bundle.document.doc_id) is None:
        corpus.add_document(bundle.document)
    v = bundle.version
    version = corpus.add_version(
        bundle.document.doc_id,
        v.label,
        anchor_kind=v.anchor_kind,
        fidelity=v.fidelity,
        source_url=v.source_url,
        content_sha256=v.content_sha256,
        licence=None if bundle.licence is None else bundle.licence.fact(),
        observed_at=v.observed_at,
        published=v.published,
    )
    for rendition in bundle.renditions:
        corpus.add_rendition(version.version_id, rendition)
    if bundle.pages:
        corpus.add_pages(version.version_id, bundle.pages)
    if bundle.blocks:
        corpus.add_blocks(version.version_id, bundle.blocks)
    if bundle.outline:
        corpus.set_outline(version.version_id, bundle.outline)
    return version


def load_bundles(corpus: Corpus, directory: Path) -> list[Version]:
    """Import every ``*.json`` bundle in a directory, in file-name order."""
    return [
        import_bundle(corpus, Bundle.model_validate_json(path.read_text(encoding="utf-8")))
        for path in sorted(directory.glob("*.json"))
    ]
