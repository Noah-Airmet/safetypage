"""PDF and HTML extraction: the text of record, word boxes, blocks, and what is set aside."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from safetypage.ingest.html import ExtractError, blocks_from_html, outline_of, page_blocks
from safetypage.ingest.pdf import NeedsOcrError, PdfError, pdf_outline, pdf_pages
from safetypage.quote import skeleton, verify_quote
from safetypage.text import is_clean

FIXTURES = Path(__file__).parents[2] / "fixtures" / "corpus"


def _bundle(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / "bundles" / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("pdf", "bundle"),
    [
        ("arxiv-2305.15324v2.pdf", "arxiv-2305.15324-v2"),
        ("nist-ai-100-1.pdf", "nist-ai-100-1-r1"),
    ],
)
def test_pdf_text_matches_the_fixture_extraction(pdf: str, bundle: str) -> None:
    """pypdfium2 gives the same text, page for page, as the PyMuPDF-built fixtures."""
    pages = pdf_pages((FIXTURES / "sources" / pdf).read_bytes())
    expected: list[dict[str, str]] = _bundle(bundle)["pages"]  # type: ignore[assignment]
    assert len(pages) == len(expected)
    for got, want in zip(pages, expected, strict=True):
        assert skeleton(got.text).text == skeleton(want["text"]).text
        assert is_clean(got.text)


def test_words_point_at_their_own_text() -> None:
    pages = pdf_pages((FIXTURES / "sources" / "arxiv-2305.15324v2.pdf").read_bytes())
    page = pages[5]
    assert page.words
    assert page.width and page.height
    for start, end, x0, y0, x1, y1 in page.words:
        word = page.text[start:end]
        assert word and not any(c.isspace() for c in word)
        assert 0 <= x0 <= x1 <= page.width + 1
        assert 0 <= y0 <= y1 <= page.height + 1


def test_a_quote_verifies_on_the_extracted_page() -> None:
    pages = pdf_pages((FIXTURES / "sources" / "arxiv-2305.15324v2.pdf").read_bytes())
    text = "\n".join(p.text for p in pages)
    result = verify_quote("Model evaluation is not the only tool available", text)
    assert result.passed


def test_page_labels_and_outline() -> None:
    data = (FIXTURES / "sources" / "nist-ai-100-1.pdf").read_bytes()
    pages = pdf_pages(data)
    assert pages[2].label == "i"
    outline = pdf_outline(data, pages)
    assert outline
    for entry in outline:
        n = int(entry.anchor.removeprefix("p"))
        assert skeleton(entry.title).text in skeleton(pages[n - 1].text).text


def test_a_pdf_without_text_needs_ocr() -> None:
    document = pdfium.PdfDocument.new()
    document.new_page(612, 792)  # pyright: ignore[reportUnknownMemberType]
    buffer = io.BytesIO()
    document.save(buffer)  # pyright: ignore[reportUnknownMemberType]
    with pytest.raises(NeedsOcrError):
        pdf_pages(buffer.getvalue())


def test_bytes_that_are_not_a_pdf() -> None:
    with pytest.raises(PdfError):
        pdf_pages(b"<html>not a pdf</html>")


SAMPLE = """
<html><body><article>
<h1>Title</h1>
<p>Opening   paragraph,
with a line break.</p>
<h2>Method</h2>
<p>We did <em>this</em>.</p>
<ul><li>first item</li><li><p>second item</p><ul><li>nested item</li></ul></li></ul>
<blockquote><p>a quoted line</p></blockquote>
<pre>code line 1
code line 2</pre>
<table><tr><th>a</th><th>b</th></tr><tr><td>1</td><td>2</td></tr></table>
<h2>Notes</h2>
<ol class="footnotes"><li><p>a footnote</p></li></ol>
<script>var hidden = 1;</script>
</article></body></html>
"""


def test_blocks_from_html() -> None:
    blocks = blocks_from_html(SAMPLE)
    got = [(b.kind, b.text) for b in blocks]
    assert got == [
        ("heading", "Title"),
        ("paragraph", "Opening paragraph, with a line break."),
        ("heading", "Method"),
        ("paragraph", "We did this."),
        ("list_item", "first item"),
        ("list_item", "second item"),
        ("list_item", "nested item"),
        ("quote", "a quoted line"),
        ("code", "code line 1\ncode line 2"),
        ("table", "a | b\n1 | 2"),
        ("heading", "Notes"),
        ("footnote", "a footnote"),
    ]
    assert blocks[3].section == ["Title", "Method"]
    assert [e.anchor for e in outline_of(blocks)] == ["b1", "b3", "b11"]


def test_distill_article_keeps_its_headings() -> None:
    data = (FIXTURES / "sources" / "distill-zoom-in.reduced.html").read_bytes()
    blocks = page_blocks(data, "https://distill.pub/2020/circuits/zoom-in/")
    headings = [b.text for b in blocks if b.kind == "heading"]
    assert "Three Speculative Claims" in headings
    assert all(is_clean(b.text) for b in blocks)


def test_a_script_shell_is_set_aside() -> None:
    shell = b"<html><body><p>Please enable javascript for this website.</p></body></html>"
    with pytest.raises(ExtractError):
        page_blocks(shell, "https://example.org/")


def test_a_deployment_safety_hub_page_keeps_its_whole_main() -> None:
    sections = "".join(
        f"<article><h2>{n}. Section</h2><p>{'Evaluation text. ' * 30}</p></article>"
        for n in range(1, 6)
    )
    page = (
        "<html><body><nav><a>Home</a></nav><main><p>Published February 5, 2026</p>"
        f"<h1>A System Card</h1>{sections}</main><footer>footer</footer></body></html>"
    ).encode()
    blocks = page_blocks(page, "https://deploymentsafety.openai.com/a-card")
    assert [b.text for b in blocks if b.kind == "heading"] == [
        "A System Card",
        *(f"{n}. Section" for n in range(1, 6)),
    ]
    assert not any("footer" in b.text or "Home" in b.text for b in blocks)
