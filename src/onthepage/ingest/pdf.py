# pypdfium2 and its ctypes layer are untyped
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""A PDF's own text layer, page by page, with word boxes. Uses pypdfium2 (Apache-2.0 / BSD).

The text of record is pdfium's text for each page in its own order, character for character
(pdfium's generated line breaks become ``\\n``), passed through ``clean_text``. Each word records
its character range in that text and its box in PDF points from the page's top-left corner,
which is what the reader's highlight needs. Nothing is re-ordered or re-spelled.

Compared with PyMuPDF on the fixture PDFs, a two-column ACL paper, an arXiv paper and a system
card, the two give the same text on every page (skeleton similarity 1.0, 0.998 at worst on
math-heavy pages, where pdfium's spacing is the better of the two).
"""

from __future__ import annotations

from typing import Final

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from onthepage.model import NewPage, OutlineEntry
from onthepage.quote import skeleton
from onthepage.text import clean_text

__all__ = ["NeedsOcrError", "PdfError", "pdf_outline", "pdf_pages"]

MIN_CHARS_PER_PAGE: Final = 80
"""Below this many letters and digits per page on average, a PDF is treated as a scan."""


class PdfError(Exception):
    pass


class NeedsOcrError(PdfError):
    pass


Word = tuple[int, int, float, float, float, float]


def _page(page: pdfium.PdfPage) -> NewPage:
    width, height = page.get_size()
    textpage = page.get_textpage()
    try:
        raw = textpage.raw
        count = pdfium_c.FPDFText_CountChars(raw)
        chars: list[str] = []
        sources: list[int] = []  # for each kept character, its pdfium char index
        i = 0
        while i < count:
            code = pdfium_c.FPDFText_GetUnicode(raw, i)
            if 0xD800 <= code < 0xDC00 and i + 1 < count:
                low = pdfium_c.FPDFText_GetUnicode(raw, i + 1)
                if 0xDC00 <= low < 0xE000:
                    chars.append(chr(0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)))
                    sources.append(i)
                    i += 2
                    continue
            ch = chr(code) if code and not 0xD800 <= code < 0xE000 else ""
            if code in (0xFFFE, 0x02):
                ch = "-"  # pdfium's mark for a hyphen at a line break; the page shows "-"
            if ch == "\r":
                ch = "\n"
                if i + 1 < count and pdfium_c.FPDFText_GetUnicode(raw, i + 1) == 0x0A:
                    i += 1
            elif ch and not (ch.isprintable() or ch in "\n\t"):
                ch = clean_text(ch)
            if ch:
                chars.append(ch)
                sources.append(i)
            i += 1
        text = "".join(chars)
        if clean_text(text) != text:  # pragma: no cover - every character went through it
            raise PdfError("text did not clean character for character")
        words: list[Word] = []
        left, bottom, right, top = (pdfium_c.c_double() for _ in range(4))
        start = None
        for pos in range(len(text) + 1):
            boundary = pos == len(text) or text[pos].isspace()
            if not boundary and start is None:
                start = pos
            elif boundary and start is not None:
                x0 = y0 = float("inf")
                x1 = y1 = float("-inf")
                for k in range(start, pos):
                    idx = sources[k]
                    if pdfium_c.FPDFText_IsGenerated(raw, idx) == 1:
                        continue
                    if not pdfium_c.FPDFText_GetCharBox(raw, idx, left, right, bottom, top):
                        continue
                    x0, x1 = min(x0, left.value), max(x1, right.value)
                    y0, y1 = min(y0, height - top.value), max(y1, height - bottom.value)
                if x0 != float("inf"):
                    words.append(
                        (start, pos, round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1))
                    )
                start = None
    finally:
        textpage.close()
    return NewPage(
        text=text, width=round(width, 1), height=round(height, 1), words=words, label=None
    )


def pdf_pages(data: bytes) -> list[NewPage]:
    """Every page's text and words. Raises NeedsOcrError for a PDF with no real text layer."""
    try:
        document = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise PdfError(f"not a readable PDF: {exc}") from exc
    try:
        pages: list[NewPage] = []
        for index in range(len(document)):
            page = document[index]
            try:
                pages.append(_page(page))
            finally:
                page.close()
        labels = _labels(document, len(pages))
    finally:
        document.close()
    if not pages:
        raise PdfError("the PDF has no pages")
    letters = sum(len(skeleton(p.text).text) for p in pages)
    if letters / len(pages) < MIN_CHARS_PER_PAGE:
        raise NeedsOcrError(
            f"{letters} letters and digits over {len(pages)} pages: a scan, or images of text"
        )
    return [p.model_copy(update={"label": label}) for p, label in zip(pages, labels, strict=True)]


def _labels(document: pdfium.PdfDocument, n: int) -> list[str | None]:
    """Printed page labels, where the PDF defines them and they differ from the page number."""
    labels: list[str | None] = []
    buffer = pdfium_c.create_string_buffer(256)
    for index in range(n):
        size = pdfium_c.FPDF_GetPageLabel(document.raw, index, buffer, 256)
        label = None
        if size > 2:
            label = buffer.raw[: size - 2].decode("utf-16-le", errors="replace").strip() or None
        labels.append(None if label == str(index + 1) else label)
    return labels


def pdf_outline(data: bytes, pages: list[NewPage]) -> list[OutlineEntry]:
    """The PDF's bookmarks, keeping only those whose title is on the page they point at."""
    entries: list[OutlineEntry] = []
    document = pdfium.PdfDocument(data)
    try:
        for bookmark in document.get_toc(max_depth=16):
            title = " ".join((bookmark.get_title() or "").split())
            dest = bookmark.get_dest()
            index = None if dest is None else dest.get_index()
            if not title or index is None or not 0 <= index < len(pages):
                continue
            needle = skeleton(title).text
            if needle and needle in skeleton(pages[index].text).text:
                entries.append(
                    OutlineEntry(level=bookmark.level + 1, title=title, anchor=f"p{index + 1}")
                )
    except pdfium.PdfiumError:
        return []
    finally:
        document.close()
    return entries
