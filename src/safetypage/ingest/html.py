# lxml and trafilatura are untyped
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""HTML documents as blocks: headings, paragraphs, list items, quotes, code, tables, captions.

A web page's main text is found with trafilatura (Apache-2.0), which drops navigation, footers
and boilerplate and returns plain HTML; :func:`blocks_from_html` then walks that HTML in order.
Clean HTML that is already only the article (a LessWrong post body) goes straight to the walker.
Block text is the element's text with runs of whitespace collapsed (code and tables keep their
lines), passed through ``clean_text``. Anchors are minted by storage, in this order.
"""

from __future__ import annotations

from typing import Any, Final

import trafilatura
from lxml import html as lxml_html
from lxml.etree import ParserError

from safetypage.model import BlockKind, NewBlock, OutlineEntry
from safetypage.text import clean_text

__all__ = ["MIN_TEXT_CHARS", "ExtractError", "blocks_from_html", "outline_of", "page_blocks"]

MIN_TEXT_CHARS: Final = 300
"""A page whose main text is shorter than this is not the document (a script shell, a stub)."""

_HEADINGS: Final = {"h1", "h2", "h3", "h4", "h5", "h6"}
_SKIP: Final = {"script", "style", "noscript", "nav", "button", "svg", "math", "form", "iframe"}
_CONTAINERS: Final = {"ul", "ol", "dl"}


class ExtractError(Exception):
    pass


def _text(el: Any, *, keep_lines: bool = False) -> str:
    parts: list[str] = []
    for node in el.iter():
        tag = node.tag if isinstance(node.tag, str) else ""
        if tag in _SKIP:
            continue
        if tag == "br":
            parts.append("\n")
        if node.text and tag not in _SKIP:
            parts.append(node.text)
        if node is not el and node.tail:
            parts.append(node.tail)
    raw = "".join(parts)
    if keep_lines:
        lines = [" ".join(line.split()) for line in raw.split("\n")]
        return clean_text("\n".join(line for line in lines if line))
    return clean_text(" ".join(raw.split()))


def _table_text(el: Any) -> str:
    rows: list[str] = []
    for tr in el.iter("tr"):
        cells = [_text(c) for c in tr if isinstance(c.tag, str) and c.tag in {"td", "th"}]
        if any(cells):
            rows.append(" | ".join(cells))
    return clean_text("\n".join(rows))


class _Walker:
    def __init__(self) -> None:
        self.blocks: list[NewBlock] = []
        self.sections: list[tuple[int, str]] = []

    def add(self, kind: BlockKind, text: str, *, level: int | None = None) -> None:
        if not text.strip():
            return
        if kind == "heading" and level is not None:
            self.sections = [s for s in self.sections if s[0] < level]
            section = [s[1] for s in self.sections]
            self.sections.append((level, text))
        else:
            section = [s[1] for s in self.sections]
        self.blocks.append(NewBlock(kind=kind, text=text, level=level, section=section))

    def walk(self, el: Any, *, in_footnotes: bool = False) -> None:
        for child in el:
            tag = child.tag if isinstance(child.tag, str) else ""
            if not tag or tag in _SKIP:
                continue
            classes = (child.get("class") or "").split()
            footnotes = in_footnotes or "footnotes" in classes or "footnote-section" in classes
            if tag in _HEADINGS:
                self.add("heading", _text(child), level=int(tag[1]))
            elif tag == "p":
                self.add("footnote" if footnotes else "paragraph", _text(child))
            elif tag == "li":
                if any(isinstance(c.tag, str) and c.tag in {"p", *_CONTAINERS} for c in child):
                    self.walk_item(child, footnotes)
                else:
                    self.add("footnote" if footnotes else "list_item", _text(child))
            elif tag in {"pre", "code"}:
                self.add("code", _text(child, keep_lines=True))
            elif tag == "table":
                self.add("table", _table_text(child))
            elif tag == "figcaption":
                self.add("caption", _text(child))
            elif tag == "blockquote":
                if any(isinstance(c.tag, str) and c.tag in {"p", "ul", "ol"} for c in child):
                    for para in child.iter("p", "li"):
                        self.add("quote", _text(para))
                else:
                    self.add("quote", _text(child))
            elif tag in {"dt", "dd"}:
                self.add("paragraph", _text(child))
            else:
                self.walk(child, in_footnotes=footnotes)
                if child.text and child.text.strip() and tag in {"div", "section", "article"}:
                    # Loose text directly inside a container, with no paragraph around it.
                    self.add("paragraph", _text_of(child.text))

    def walk_item(self, li: Any, footnotes: bool) -> None:
        lead = _text_of(li.text or "")
        if lead:
            self.add("footnote" if footnotes else "list_item", lead)
        for child in li:
            if isinstance(child.tag, str) and child.tag == "p":
                self.add("footnote" if footnotes else "list_item", _text(child))
            elif isinstance(child.tag, str):
                self.walk([child], in_footnotes=footnotes)
            if isinstance(child.tag, str) and child.tail and child.tail.strip():
                self.add("footnote" if footnotes else "list_item", _text_of(child.tail))


def _text_of(raw: str) -> str:
    return clean_text(" ".join(raw.split()))


def blocks_from_html(html: str) -> list[NewBlock]:
    """Blocks from HTML that holds only the document (no page furniture)."""
    try:
        root = lxml_html.fromstring(html)
    except (ParserError, ValueError) as exc:
        raise ExtractError(f"unparseable HTML: {exc}") from exc
    walker = _Walker()
    body = root.find("body")
    walker.walk(body if body is not None else root)
    return walker.blocks


def page_blocks(data: bytes, url: str) -> list[NewBlock]:
    """A web page's main text as blocks. Raises ExtractError when there is no real text."""
    html = data.decode("utf-8", errors="replace")
    blocks = _d_article_blocks(html)
    if blocks is None:
        blocks = _main_blocks(html, url)
    total = sum(len(b.text) for b in blocks)
    if total < MIN_TEXT_CHARS:
        raise ExtractError(
            f"only {total} characters of main text (the page may need JavaScript, or be a stub)"
        )
    return blocks


_D_SKIP: Final = {
    *("d-footnote", "d-cite", "d-contents", "d-math", "d-figure", "d-byline"),
    *("dt-fn", "dt-cite", "dt-byline", "dt-math"),
}
_D_ARTICLE: Final = ("d-article", "d-appendix", "dt-article", "dt-appendix")


def _d_article_blocks(html: str) -> list[NewBlock] | None:
    """Distill and the Transformer Circuits thread put the article in ``<d-article>`` (older
    Distill: ``<dt-article>``); walking it directly keeps the headings a general extractor drops."""
    if "<d-article" not in html and "<dt-article" not in html:
        return None
    root = lxml_html.fromstring(html)
    articles = [el for tag in _D_ARTICLE for el in root.iter(tag)]
    if not articles:
        return None
    for article in articles:
        for el in list(article.iter(*_D_SKIP)):
            el.drop_tree()  # removes the element and keeps the text that followed it
    walker = _Walker()
    for article in articles:
        walker.walk(article)
    return walker.blocks


def _main_blocks(html: str, url: str) -> list[NewBlock]:
    main = trafilatura.extract(
        html,
        url=url,
        output_format="html",
        include_tables=True,
        include_comments=False,
        include_links=False,
        include_images=False,
        favor_recall=True,
    )
    if not main:
        raise ExtractError("no main text found (the page may need JavaScript)")
    return blocks_from_html(main)


def outline_of(blocks: list[NewBlock], first_anchor: int = 1) -> list[OutlineEntry]:
    """Headings as an outline, assuming the blocks are minted from ``first_anchor`` in order."""
    return [
        OutlineEntry(level=b.level or 1, title=b.text[:300], anchor=f"b{first_anchor + i}")
        for i, b in enumerate(blocks)
        if b.kind == "heading"
    ]
