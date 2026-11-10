"""Rebuild the fixture bundles in fixtures/corpus/bundles/ from fixtures/corpus/sources/.

    uv run --group fixtures python fixtures/build.py          # rewrite the bundles
    uv run --group fixtures python fixtures/build.py --check  # exit 1 if they would change

This is a fixture builder, not the ingestion pipeline: it parses just far enough to exercise the
document model, the anchors and the quote checker on real documents. It does follow the
pipeline's rules: the PDF's own text layer (PyMuPDF, default reading order) is the text of record
for anything with a PDF; structure comes from arXiv's LaTeXML HTML laid over that text by one
whole-document alignment; nothing is transcribed by a model.

Everything it reads is described in fixtures/corpus/sources.json.
"""

from __future__ import annotations

import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pymupdf
from rapidfuzz.distance import Levenshtein

from onthepage.blobs import sha256_file
from onthepage.bundle import Bundle, BundleLicence, BundleVersion
from onthepage.model import Document, NewBlock, NewPage, OutlineEntry, Rendition
from onthepage.quote import skeleton
from onthepage.text import clean_text

ROOT = Path(__file__).parent / "corpus"
SOURCES = ROOT / "sources"
BUNDLES = ROOT / "bundles"

MEDIA_TYPES = {"pdf": "application/pdf", "html": "text/html", "text": "text/plain"}
VOID = {"br", "img", "hr", "meta", "link", "input", "wbr", "source", "col", "area", "base"}


# --------------------------------------------------------------------------- PDF


def pdf_pages(path: Path, *, with_words: bool) -> list[NewPage]:
    pages: list[NewPage] = []
    with pymupdf.open(path) as doc:
        for page in doc:
            text = clean_text(page.get_text())
            label = page.get_label() or None
            words: list[tuple[int, int, float, float, float, float]] | None = None
            if with_words:
                words = []
                cursor = 0
                for x0, y0, x1, y1, word, *_ in page.get_text("words"):
                    word = clean_text(word)
                    at = text.find(word, cursor)
                    if at < 0 or not word:
                        continue
                    words.append(
                        (at, at + len(word), round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1))
                    )
                    cursor = at + len(word)
            pages.append(
                NewPage(
                    text=text,
                    label=label,
                    width=round(page.rect.width, 1),
                    height=round(page.rect.height, 1),
                    words=words,
                )
            )
    return pages


def pdf_outline(path: Path) -> list[OutlineEntry]:
    with pymupdf.open(path) as doc:
        return [
            OutlineEntry(level=level, title=" ".join(title.split()), anchor=f"p{page}")
            for level, title, page in doc.get_toc()
            if 1 <= page <= doc.page_count and title.strip()
        ]


# --------------------------------------------------------------------------- HTML


class _Blocks(HTMLParser):
    """Collect headings, paragraphs and captions from an HTML document, in order.

    Subclasses say which elements open a block and which subtrees to skip.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict[str, Any]] = []
        self.sections: list[tuple[int, str]] = []
        self._stack: list[tuple[str, bool]] = []  # (tag, is the element that opened the block)
        self._current: dict[str, Any] | None = None
        self._skip_tag: str | None = None  # the element whose subtree is being skipped
        self._skip_depth = 0
        self._active = True

    # hooks
    def opens(self, tag: str, attrs: dict[str, str]) -> dict[str, Any] | None:
        raise NotImplementedError

    def skips(self, tag: str, attrs: dict[str, str]) -> bool:
        raise NotImplementedError

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if self._skip_tag is not None:
            # Count only the skipped element's own tag, so unclosed tags inside cannot unbalance.
            self._skip_depth += tag == self._skip_tag
            return
        if tag in VOID:
            if tag == "br" and self._current is not None:
                self._current["parts"].append(" ")
            return
        if self.skips(tag, a):
            self._skip_tag, self._skip_depth = tag, 1
            return
        opened = False
        if self._current is None and self._active:
            block = self.opens(tag, a)
            if block is not None:
                self._current = {"parts": [], **block}
                opened = True
        self._stack.append((tag, opened))

    def handle_endtag(self, tag: str) -> None:
        if self._skip_tag is not None:
            self._skip_depth -= tag == self._skip_tag
            if self._skip_depth == 0:
                self._skip_tag = None
            return
        if tag in VOID:
            return
        while self._stack:
            name, opened = self._stack.pop()
            if opened:
                self._close()
            if name == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._current is not None and self._skip_tag is None:
            self._current["parts"].append(data)

    def _close(self) -> None:
        block = self._current
        self._current = None
        if block is None:
            return
        text = clean_text(" ".join("".join(block.pop("parts")).split()))
        if not text:
            return
        if block["kind"] == "heading":
            level = block["level"]
            self.sections = [s for s in self.sections if s[0] < level] + [(level, text)]
            block["section"] = [s[1] for s in self.sections[:-1]]
        else:
            block["section"] = [s[1] for s in self.sections]
        block["text"] = text
        self.blocks.append(block)


class _LatexmlBlocks(_Blocks):
    """arXiv's LaTeXML HTML: section titles, ltx_para paragraphs, figure and table captions."""

    def opens(self, tag: str, attrs: dict[str, str]) -> dict[str, Any] | None:
        cls = attrs.get("class", "")
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and "ltx_title" in cls:
            if "ltx_title_document" in cls:
                return {"kind": "heading", "level": 1, "source_id": None}
            return {"kind": "heading", "level": max(int(tag[1]), 2), "source_id": None}
        if tag == "div" and "ltx_para" in cls.split() and attrs.get("id"):
            return {"kind": "paragraph", "level": None, "source_id": attrs["id"]}
        if tag == "figcaption":
            return {"kind": "caption", "level": None, "source_id": None}
        return None

    def skips(self, tag: str, attrs: dict[str, str]) -> bool:
        classes = set(attrs.get("class", "").split())
        return tag in {
            "math",
            "script",
            "style",
            "svg",
            "nav",
            "footer",
            "header",
            "button",
        } or bool(
            classes
            & {"ltx_note", "ltx_bibliography", "ltx_authors", "ltx_dates", "ltx_role_footnote"}
        )


class _DistillBlocks(_Blocks):
    """A Distill article: everything inside <d-article>, minus footnotes and widgets."""

    def __init__(self) -> None:
        super().__init__()
        self._active = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "d-article":
            self._active = True
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        super().handle_endtag(tag)
        if tag == "d-article":
            self._active = False

    def opens(self, tag: str, attrs: dict[str, str]) -> dict[str, Any] | None:
        source_id = attrs.get("id") or None
        if tag in {"h2", "h3", "h4"}:
            return {"kind": "heading", "level": int(tag[1]), "source_id": source_id}
        if tag == "p":
            return {"kind": "paragraph", "level": None, "source_id": source_id}
        if tag == "figcaption":
            return {"kind": "caption", "level": None, "source_id": source_id}
        if tag == "li":
            return {"kind": "list_item", "level": None, "source_id": source_id}
        return None

    def skips(self, tag: str, attrs: dict[str, str]) -> bool:
        return tag in {
            "d-footnote",
            "d-cite",
            "d-contents",
            "d-math",
            "script",
            "style",
            "svg",
            "nav",
            "section",  # the thread navigation box at the top
        }


def html_blocks(path: Path, parser: _Blocks) -> list[dict[str, Any]]:
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    return parser.blocks


def place_blocks(blocks: list[dict[str, Any]], spine: str) -> None:
    """Lay HTML blocks over the PDF text: one order-preserving alignment of the whole document.

    Each block gets the stretch of the spine its characters landed on, when at least 80% of them
    landed and they landed together. Otherwise it stays unplaced (still listed, not citable).
    """
    sk = skeleton(spine)
    parts = [skeleton(b["text"]).text for b in blocks]
    joined = "".join(parts)
    mapping = [-1] * len(joined)
    for tag, i1, i2, j1, _ in Levenshtein.opcodes(joined, sk.text):
        if tag == "equal":
            for k in range(i2 - i1):
                mapping[i1 + k] = j1 + k
    offset = 0
    for block, part in zip(blocks, parts, strict=True):
        hits = [m for m in mapping[offset : offset + len(part)] if m >= 0]
        offset += len(part)
        if len(part) < 4 or len(hits) < 0.8 * len(part):
            continue
        # Ignore stragglers (a few characters matched far from the rest) when judging the spread.
        lo, hi = hits[len(hits) // 50], hits[-1 - len(hits) // 50] + 1
        if hi - lo > 1.5 * len(part):
            continue
        # Most blocks are in the PDF text exactly; when one is, use that exact stretch.
        exact = sk.text.find(part, max(0, lo - len(part)), hi + len(part))
        if exact >= 0:
            lo, hi = exact, exact + len(part)
        else:
            lo, hi = sk.widen_to_words(lo, hi)
        block["spine_start"], block["spine_end"] = sk.source_span(lo, hi)


def to_new_blocks(blocks: list[dict[str, Any]]) -> list[NewBlock]:
    return [
        NewBlock(
            kind=b["kind"],
            text=b["text"],
            level=b["level"],
            section=b["section"],
            source_id=b["source_id"],
            spine_start=b.get("spine_start"),
            spine_end=b.get("spine_end"),
        )
        for b in blocks
    ]


# --------------------------------------------------------------------------- bundles


def rendition(kind: str, name: str, source_url: str, fetched_at: str) -> Rendition:
    path = SOURCES / name
    return Rendition(
        kind=kind,  # pyright: ignore[reportArgumentType]
        sha256=sha256_file(path),
        bytes=path.stat().st_size,
        media_type=MEDIA_TYPES[kind],
        source_url=source_url,
        fetched_at=fetched_at,
    )


def build(entry: dict[str, Any]) -> Bundle:
    files: dict[str, dict[str, str]] = entry["files"]
    observed_at: str = entry["version"]["observed_at"]
    renditions = [
        rendition(kind, spec["name"], spec["url"], observed_at) for kind, spec in files.items()
    ]
    pages: list[NewPage] = []
    blocks: list[NewBlock] = []
    outline: list[OutlineEntry] = []
    parser: str = entry["parser"]

    if parser in {"pdf", "pdf+latexml"}:
        pdf = SOURCES / files["pdf"]["name"]
        pages = pdf_pages(pdf, with_words=bool(entry.get("words")))
        outline = pdf_outline(pdf)
        primary = "pdf"
        if parser == "pdf+latexml":
            raw = html_blocks(SOURCES / files["html"]["name"], _LatexmlBlocks())
            place_blocks(raw, "\n".join(p.text for p in pages))
            blocks = to_new_blocks(raw)
    elif parser == "distill":
        raw = html_blocks(SOURCES / files["html"]["name"], _DistillBlocks())
        blocks = to_new_blocks(raw)
        primary = "html"
    elif parser == "text-pages":
        text = (SOURCES / files["text"]["name"]).read_text(encoding="utf-8")
        pages = [NewPage(text=clean_text(p.strip("\n"))) for p in text.split("\f")]
        primary = "text"
    elif parser == "text-blocks":
        text = (SOURCES / files["text"]["name"]).read_text(encoding="utf-8")
        for chunk in (c.strip() for c in text.split("\n\n")):
            if chunk.startswith("# "):
                blocks.append(NewBlock(kind="heading", level=2, text=clean_text(chunk[2:])))
            elif chunk:
                blocks.append(NewBlock(kind="paragraph", text=clean_text(" ".join(chunk.split()))))
        primary = "text"
    else:
        raise ValueError(f"unknown parser {parser!r}")

    if not pages:
        section_starts = [
            OutlineEntry(level=b.level or 2, title=b.text, anchor=f"b{i}")
            for i, b in enumerate(blocks, start=1)
            if b.kind == "heading"
        ]
        outline = section_starts

    content = next(r for r in renditions if r.kind == primary)
    return Bundle(
        document=Document(**entry["document"]),
        version=BundleVersion(content_sha256=content.sha256, **entry["version"]),
        licence=None if entry["licence"] is None else BundleLicence(**entry["licence"]),
        renditions=renditions,
        pages=pages,
        blocks=blocks,
        outline=outline,
    )


def render() -> dict[str, str]:
    entries = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))["versions"]
    out: dict[str, str] = {}
    for entry in entries:
        bundle = build(entry)
        text = json.dumps(
            bundle.model_dump(mode="json"), ensure_ascii=False, indent=1, sort_keys=True
        )
        out[f"{entry['bundle']}.json"] = text + "\n"
    return out


def main(argv: list[str]) -> int:
    rendered = render()
    if "--check" in argv:
        stale = [
            name
            for name, text in rendered.items()
            if not (BUNDLES / name).is_file()
            or (BUNDLES / name).read_text(encoding="utf-8") != text
        ]
        stale += [p.name for p in BUNDLES.glob("*.json") if p.name not in rendered]
        for name in stale:
            print(f"stale: {BUNDLES / name}", file=sys.stderr)
        return 1 if stale else 0
    BUNDLES.mkdir(parents=True, exist_ok=True)
    for name, text in rendered.items():
        (BUNDLES / name).write_text(text, encoding="utf-8")
        print(BUNDLES / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
