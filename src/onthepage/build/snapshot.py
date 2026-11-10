"""Build a sealed snapshot from a working corpus.

    build_snapshot(root / "corpus.sqlite", root, "2026.11.0")

1. :func:`onthepage.snapshot.stage_snapshot` copies the corpus into ``<id>.staging/``.
2. ``lexical/``: the Tantivy index over every unit.
3. ``public/``: a document card for every document; for every *open* version, each unit's text
   with its page layout (``read_units(layout=True)``), page images at 800 and 1600 px wide
   (WebP) for versions with a PDF, and the source file itself.
4. ``dense/<model>/``: assembled from the embedding cache when it covers every unit; otherwise
   skipped, with the reason recorded in the manifest.
5. :func:`onthepage.snapshot.seal_snapshot` runs the gates (``Corpus.validate()`` and the
   publish gate, which refuses anything of a link-only version under ``public/``) and renames
   the directory into place.

Page images are rendered once per PDF and kept in ``<root>/cache/pages/<pdf sha256>/``, so a
new snapshot renders only PDFs it has not seen. Files from the blob store and the image cache
are hard-linked into the snapshot when the filesystem allows, copied otherwise.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Final

from onthepage.blobs import BlobStore
from onthepage.corpus import Corpus
from onthepage.ids import Anchor, Citation, DocId, Ref, parse_citation
from onthepage.licence import Tier
from onthepage.search.dense import DEFAULT_MODEL, assemble_dense, model_slug
from onthepage.search.lexical import LEXICAL_DIR, build_lexical_index
from onthepage.snapshot import (
    CORPUS_DB,
    Manifest,
    public_doc_path,
    public_file_path,
    public_page_image_path,
    public_text_path,
    seal_snapshot,
    set_current,
    stage_snapshot,
)

__all__ = ["PAGE_WIDTHS", "build_snapshot", "export_public", "render_pdf_pages"]

PAGE_WIDTHS: Final = (800, 1600)
WEBP_QUALITY: Final = 80
_SOURCE_EXTENSIONS: Final = {"pdf": "pdf", "html": "html"}


def _link(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)


def _write(staging: Path, relative: object, content: str) -> None:
    path = staging / str(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------------------
# Page images
# ---------------------------------------------------------------------------------------


def render_pdf_pages(
    pdf: Path, out_dir: Path, pages: int, widths: tuple[int, ...] = PAGE_WIDTHS
) -> int:
    """Render pages 1..``pages`` of ``pdf`` to ``out_dir/p<n>.<width>.webp``, skipping files
    that already exist. Returns how many images were rendered."""
    import pymupdf  # noqa: PLC0415  (the build group; the server never renders)
    from PIL import Image  # noqa: PLC0415

    out_dir.mkdir(parents=True, exist_ok=True)
    rendered = 0
    document: Any
    with pymupdf.open(pdf) as document:
        for n in range(1, min(pages, document.page_count) + 1):
            page = document[n - 1]
            for width in widths:
                target = out_dir / f"p{n}.{width}.webp"
                if target.exists():
                    continue
                zoom = width / page.rect.width
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
                image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                temporary = target.with_suffix(".tmp")
                image.save(temporary, "WEBP", quality=WEBP_QUALITY, method=4)
                temporary.replace(target)
                rendered += 1
    return rendered


def _render_job(job: tuple[str, str, int]) -> int:
    pdf, out_dir, pages = job
    return render_pdf_pages(Path(pdf), Path(out_dir), pages)


# ---------------------------------------------------------------------------------------
# public/
# ---------------------------------------------------------------------------------------


def export_public(
    corpus: Corpus,
    staging: Path,
    *,
    blobs: BlobStore | None,
    image_cache: Path | None,
    workers: int | None = None,
    log: Callable[[str], None] = lambda _: None,
) -> dict[str, Any]:
    """Write ``public/``: cards for every document; text, images and files for open versions."""
    counts = {"cards": 0, "texts": 0, "images": 0, "rendered": 0, "files": 0, "missing_blobs": 0}
    for doc_id in corpus.doc_ids():
        card = corpus.document_card(doc_id)
        _write(staging, public_doc_path(DocId.parse(doc_id)), card.model_dump_json())
        counts["cards"] += 1
    jobs: list[tuple[str, str, int]] = []
    placements: list[tuple[Path, Citation]] = []
    for version in corpus.all_versions():
        if version.tier is not Tier.OPEN:
            continue
        doc = DocId.parse(version.doc_id)
        anchors = corpus.conn.execute(
            "SELECT anchor FROM units WHERE version_id = ? ORDER BY seq", (version.version_id,)
        ).fetchall()
        for (anchor,) in anchors:
            unit = corpus.read_units(f"{version.ref}/{anchor}", layout=True)[0]
            _write(staging, public_text_path(parse_citation(unit.cite)), unit.model_dump_json())
            counts["texts"] += 1
        for rendition in corpus.renditions(version.version_id):
            extension = _SOURCE_EXTENSIONS.get(rendition.kind)
            if extension is None:
                continue
            if blobs is None or not blobs.has(rendition.sha256):
                counts["missing_blobs"] += 1
                continue
            source = blobs.path(rendition.sha256)
            _link(source, staging / str(public_file_path(Ref(doc, version.label), extension)))
            counts["files"] += 1
            if rendition.kind == "pdf" and version.paged and image_cache is not None:
                pages = len(anchors)
                out_dir = image_cache / rendition.sha256
                jobs.append((str(source), str(out_dir), pages))
                placements.extend(
                    (out_dir, Citation(doc, version.label, Anchor.page(n)))
                    for n in range(1, pages + 1)
                )
    if jobs:
        log(f"rendering page images for {len(jobs)} PDFs")
        with ProcessPoolExecutor(max_workers=workers) as pool:
            counts["rendered"] = sum(pool.map(_render_job, jobs))
    for out_dir, citation in placements:
        for width in PAGE_WIDTHS:
            image = out_dir / f"p{citation.anchor.start}.{width}.webp"
            if image.exists():
                _link(image, staging / str(public_page_image_path(citation, width)))
                counts["images"] += 1
    return counts


# ---------------------------------------------------------------------------------------
# The whole build
# ---------------------------------------------------------------------------------------


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).parent,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def build_snapshot(
    corpus_db: Path,
    root: Path,
    snapshot_id: str,
    *,
    blobs: BlobStore | None = None,
    images: bool = True,
    dense_model: str | None = DEFAULT_MODEL,
    make_current: bool = False,
    base_url: str = "http://localhost:8000",
    workers: int | None = None,
    log: Callable[[str], None] = lambda _: None,
) -> Manifest:
    """Stage, build and seal snapshot ``snapshot_id`` under ``root``.

    ``blobs`` defaults to ``<root>/blobs``. The embedding cache for ``dense_model`` is
    ``<root>/embeddings/<model>/``; pass ``dense_model=None`` to leave the dense arm out.
    A build that fails removes its staging directory.
    """
    blobs = blobs if blobs is not None else BlobStore(root / "blobs")
    staging = stage_snapshot(corpus_db, root, snapshot_id)
    components: dict[str, dict[str, Any]] = {}
    try:
        with Corpus.open(staging / CORPUS_DB, readonly=True, base_url=base_url) as corpus:
            log("building the keyword index")
            components["lexical"] = build_lexical_index(corpus, staging / LEXICAL_DIR)
            log("writing public/")
            components["public"] = export_public(
                corpus,
                staging,
                blobs=blobs,
                image_cache=root / "cache" / "pages" if images else None,
                workers=workers,
                log=log,
            )
            if dense_model is not None:
                slug = model_slug(dense_model)
                try:
                    components[f"dense/{slug}"] = assemble_dense(
                        corpus,
                        root / "embeddings" / slug,
                        staging / "dense" / slug,
                        model=dense_model,
                    )
                except LookupError as exc:
                    components[f"dense/{slug}"] = {"skipped": str(exc)}
                    log(f"dense skipped: {exc}")
        log("sealing")
        manifest = seal_snapshot(staging, code_version=_git_commit(), components=components)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if make_current:
        set_current(root, snapshot_id)
    return manifest
