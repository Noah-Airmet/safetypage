"""Build the library data the site reads, from the fixture corpus, until a real snapshot exists.

    uv run --group fixtures --group build python site/scripts/make_data.py

Writes `site/.data/` in the layout of a snapshot's `public/` (docs/ARCHITECTURE.md
section 7): document cards, unit text with layout, page images at 800 and 1600 px. Not
committed, and not copied into a build: the site reads it where a real snapshot's `public/`
would be (SAFETYPAGE_PUBLIC_DIR), and the host serves it at /data.
"""

from __future__ import annotations

import io
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image

from safetypage.bundle import load_bundles
from safetypage.corpus import Corpus
from safetypage.ids import DocId, parse_citation
from safetypage.snapshot import public_doc_path, public_page_image_path, public_text_path

SITE = Path(__file__).resolve().parents[1]
FIXTURES = SITE.parent / "fixtures" / "corpus"
DATA = SITE / ".data"
WIDTHS = (800, 1600)


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def under_data(path: Any) -> Path:
    return DATA / Path(*Path(str(path)).parts[1:])  # drop the leading "public/"


def public_tree(corpus: Any) -> None:
    if DATA.exists():
        shutil.rmtree(DATA)
    sources = json.loads((FIXTURES / "sources.json").read_text())["versions"]
    pdfs = {
        f"{e['document']['doc_id']}/{e['version']['label']}": FIXTURES
        / "sources"
        / e["files"]["pdf"]["name"]
        for e in sources
        if e.get("files", {}).get("pdf")
    }
    for doc_id in corpus.doc_ids():
        card = corpus.document_card(doc_id)
        dump(under_data(public_doc_path(DocId.parse(doc_id))), card.model_dump(mode="json"))
        for version in corpus.versions(doc_id):
            if version.tier != "open":
                continue
            ref = f"{doc_id}/{version.label}"
            units = corpus.conn.execute(
                "SELECT cite FROM units WHERE doc_id = ? AND version = ? ORDER BY seq",
                (doc_id, version.label),
            ).fetchall()
            for (cite,) in units:
                unit = corpus.read_units(cite, layout=True)[0]
                dump(
                    under_data(public_text_path(parse_citation(cite))), unit.model_dump(mode="json")
                )
            if ref in pdfs:
                with pymupdf.open(pdfs[ref]) as pdf:
                    for number, page in enumerate(pdf, 1):
                        cite = parse_citation(f"{ref}/p{number}")
                        pix = page.get_pixmap(
                            matrix=pymupdf.Matrix(1600 / page.rect.width, 1600 / page.rect.width),
                            alpha=False,
                        )
                        full = Image.open(io.BytesIO(pix.tobytes("png")))
                        for width in WIDTHS:
                            out = under_data(public_page_image_path(cite, width))
                            out.parent.mkdir(parents=True, exist_ok=True)
                            image = (
                                full
                                if width == full.width
                                else full.resize(
                                    (width, round(full.height * width / full.width)), Image.LANCZOS
                                )
                            )
                            image.save(out, "WEBP", quality=72, method=6)
        print("public:", doc_id)


def add_missing_words(corpus: Any) -> None:
    """Most fixture bundles carry no word boxes. Read them from the fixture PDFs so every
    open page gets a text layer, as ingestion supplies for the real corpus."""
    sys.path.insert(0, str(SITE.parent))
    from fixtures.build import pdf_pages  # noqa: PLC0415  (needs the path above)

    for entry in json.loads((FIXTURES / "sources.json").read_text())["versions"]:
        pdf = entry.get("files", {}).get("pdf")
        if not pdf:
            continue
        version = corpus.resolve(
            f"{entry['document']['doc_id']}/{entry['version']['label']}"
        ).version
        have = corpus.conn.execute(
            "SELECT count(*) FROM page_words WHERE version_id = ?", (version.version_id,)
        ).fetchone()[0]
        if have or version.tier != "open":
            continue
        stored = {p.page: p.text for p in corpus.pages(version.version_id)}
        for number, page in enumerate(
            pdf_pages(FIXTURES / "sources" / pdf["name"], with_words=True), 1
        ):
            if page.words is not None and stored.get(number) == page.text:
                corpus.conn.execute(
                    "INSERT INTO page_words (version_id, page, words) VALUES (?,?,?)",
                    (version.version_id, number, json.dumps(page.words, separators=(",", ":"))),
                )
    corpus.conn.commit()


def main() -> None:
    corpus = Corpus.memory(base_url="")
    load_bundles(corpus, FIXTURES / "bundles")
    add_missing_words(corpus)
    public_tree(corpus)


if __name__ == "__main__":
    main()
