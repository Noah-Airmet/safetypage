from __future__ import annotations

import contextlib

import pytest
from hypothesis import given
from hypothesis import strategies as st

from onthepage.ids import (
    Anchor,
    AnchorKind,
    Citation,
    DocId,
    IdError,
    Ref,
    arxiv_ref,
    find_citations,
    mint_local_id,
    parse_citation,
    parse_ref,
    parse_url,
    source_link,
    text_fragment,
    version_label,
    version_number,
)

BASE = "https://onthepage.test"


def test_cite_string_and_url_are_the_same_parts() -> None:
    c = parse_citation("arxiv:2305.15324/v2/p6")
    assert (str(c.doc), c.version, str(c.anchor)) == ("arxiv:2305.15324", "v2", "p6")
    assert str(c) == "arxiv:2305.15324/v2/p6"
    assert c.url(BASE) == "https://onthepage.test/d/arxiv/2305.15324/v2/p6"
    assert c.path == "/d/arxiv/2305.15324/v2/p6"


def test_url_round_trips_with_a_quote() -> None:
    c = Citation(
        DocId("nist", "ai-100-1"), "r1", Anchor.page(12), quote='risk is "a composite" & more'
    )
    url = c.url(BASE + "/")
    assert url.startswith("https://onthepage.test/d/nist/ai-100-1/r1/p12?q=")
    ref, quote = parse_url(url)
    assert ref == c.ref
    assert quote == c.quote


def test_parse_url_accepts_a_bare_path_and_any_host() -> None:
    assert parse_url("/d/distill/zoom-in/r1/b14")[0] == parse_ref("distill:zoom-in/r1/b14")
    assert parse_url("http://localhost:8000/d/distill/zoom-in")[0] == Ref(
        DocId("distill", "zoom-in")
    )
    assert parse_url("https://x.example/d/distill/zoom-in/r1/")[0].version == "r1"


@pytest.mark.parametrize(
    "bad",
    [
        "https://x.example/b/distill/zoom-in/r1/b14",
        "https://x.example/d/distill",
        "https://x.example/d/distill/zoom-in/r1/b14/extra",
        "https://x.example/d/distill/zoom-in/b14",
    ],
)
def test_parse_url_rejects(bad: str) -> None:
    with pytest.raises(IdError):
        parse_url(bad)


@pytest.mark.parametrize(
    ("text", "kind", "start", "end"),
    [("p1", "p", 1, 1), ("b12", "b", 12, 12), ("p87-p89", "p", 87, 89), ("b3-b9", "b", 3, 9)],
)
def test_anchor_parse(text: str, kind: str, start: int, end: int) -> None:
    a = Anchor.parse(text)
    assert (a.kind, a.start, a.end) == (kind, start, end)
    assert str(a) == text
    assert a.size == end - start + 1
    assert str(a.singles()[0]) == f"{kind}{start}"


@pytest.mark.parametrize(
    "bad",
    ["", "p0", "p01", "6", "page6", "P6", "p6-b8", "p8-p6", "p6-p6", "p6-", "s4.3", "b1.5", "p-1"],
)
def test_anchor_rejects(bad: str) -> None:
    with pytest.raises(IdError):
        Anchor.parse(bad)


def test_anchor_contains() -> None:
    assert Anchor.page(6, 8).contains(Anchor.page(7))
    assert not Anchor.page(6, 8).contains(Anchor.page(9))
    assert not Anchor.page(6, 8).contains(Anchor.block(7))


@pytest.mark.parametrize(
    "bad",
    [
        "2305.15324",  # no namespace
        "arXiv:2305.15324",  # namespaces are lowercase
        "arxiv:",  # empty local id
        "arxiv:hep-th/9901001",  # no slash in a local id
        "arxiv:2305.15324.",  # must end on a letter or digit
        "arxiv:-x",
        "ar xiv:1",
    ],
)
def test_doc_id_rejects(bad: str) -> None:
    with pytest.raises(IdError):
        DocId.parse(bad)


def test_doc_ids_keep_case_and_sort() -> None:
    lw = DocId.parse("lw:N6WM6hs7RQMKDhYjB")
    assert lw.local == "N6WM6hs7RQMKDhYjB"
    assert lw.path == "lw/N6WM6hs7RQMKDhYjB"
    assert sorted([DocId("b", "1"), DocId("a", "2")])[0].ns == "a"


def test_refs() -> None:
    assert str(parse_ref("arxiv:2305.15324")) == "arxiv:2305.15324"
    assert parse_ref("arxiv:2305.15324/v2").version == "v2"
    assert parse_ref("arxiv:2305.15324/v2/p6-p8").anchor == Anchor.page(6, 8)
    assert parse_ref("arxiv:2305.15324").url(BASE) == "https://onthepage.test/d/arxiv/2305.15324"
    for bad in [
        "arxiv:2305.15324/p6",
        "arxiv:2305.15324/v0/p6",
        "arxiv:2305.15324/v2/p6/x",
        "arxiv:1/2",
    ]:
        with pytest.raises(IdError):
            parse_ref(bad)


def test_a_citation_must_be_complete() -> None:
    with pytest.raises(IdError, match="names a version and an anchor"):
        parse_citation("arxiv:2305.15324/v2")
    with pytest.raises(IdError):
        Ref(DocId("arxiv", "1"), None, Anchor.page(1))
    with pytest.raises(IdError):
        Citation(DocId("arxiv", "1"), "latest", Anchor.page(1))


def test_version_labels() -> None:
    assert version_label(2, publisher_numbered=True) == "v2"
    assert version_label(3, publisher_numbered=False) == "r3"
    assert version_number("r12") == 12
    for bad in ["2", "v0", "V2", "v", "x2", "v1.2"]:
        with pytest.raises(IdError):
            version_number(bad)
    with pytest.raises(IdError):
        version_label(0, publisher_numbered=True)


def test_arxiv_identifiers() -> None:
    assert str(arxiv_ref("2305.15324v2")) == "arxiv:2305.15324/v2"
    assert str(arxiv_ref("arXiv:2305.15324")) == "arxiv:2305.15324"
    assert str(arxiv_ref("hep-th/9901001v3")) == "arxiv:hep-th.9901001/v3"
    with pytest.raises(IdError):
        arxiv_ref("not-an-id")


def test_mint_local_id() -> None:
    assert mint_local_id("Claude Opus 4 System Card") == "Claude-Opus-4-System-Card"
    assert mint_local_id("2024.acl-long.787") == "2024.acl-long.787"
    assert mint_local_id(" hep-th/9901001 ") == "hep-th.9901001"
    with pytest.raises(IdError):
        mint_local_id("???")


def test_find_citations_in_prose() -> None:
    text = (
        "Evaluations inform training decisions "
        "[p. 6](https://onthepage.test/d/arxiv/2305.15324/v2/p6?q=critical%20governance) and, per "
        "nist:ai-100-1/r1/p12-p13, risk is contextual. See also (distill:zoom-in/r1/b14). "
        "Not citations: http://example.org/d/x, arxiv:2305.15324, a:b/c/d, 10:30/v2/p1."
    )
    found = find_citations(text)
    assert [str(f.citation) for f in found] == [
        "arxiv:2305.15324/v2/p6",
        "nist:ai-100-1/r1/p12-p13",
        "distill:zoom-in/r1/b14",
    ]
    assert found[0].citation.quote == "critical governance"
    assert text[found[1].start : found[1].end] == "nist:ai-100-1/r1/p12-p13"
    assert found[0].raw.startswith("https://onthepage.test/d/arxiv/")


def test_source_links() -> None:
    pdf = "https://arxiv.org/pdf/2305.15324v2"
    assert source_link(pdf, Anchor.page(6), paged=True) == pdf + "#page=6"
    assert source_link(pdf + "#x", Anchor.page(6, 8), paged=True) == pdf + "#page=6"
    html = "https://distill.pub/2020/circuits/zoom-in/"
    assert source_link(html, Anchor.block(3), paged=False) == html
    link = source_link(html, Anchor.block(3), paged=False, quote="science zoomed in")
    assert link == html + "#:~:text=science%20zoomed%20in"
    long = text_fragment(" ".join(f"w{i}" for i in range(40)))
    assert long.startswith("#:~:text=w0%20w1") and "," in long and long.endswith("w39")
    assert text_fragment("hard-to-forecast") == "#:~:text=hard%2Dto%2Dforecast"
    assert text_fragment("  ") == ""


_ns = st.from_regex(r"[a-z][a-z0-9-]{0,10}", fullmatch=True)
_local = st.from_regex(r"[A-Za-z0-9]([A-Za-z0-9._-]{0,20}[A-Za-z0-9])?", fullmatch=True)


def _make_version(kind: str, number: int) -> str:
    return f"{kind}{number}"


def _make_anchor(kind: AnchorKind, start: int, extra: int) -> Anchor:
    return Anchor(kind, start, start + extra)


_kinds: st.SearchStrategy[AnchorKind] = st.sampled_from(["p", "b"])
_version = st.builds(_make_version, st.sampled_from("vr"), st.integers(1, 999))
_anchor = st.builds(_make_anchor, _kinds, st.integers(1, 5000), st.integers(0, 40))
_citation = st.builds(Citation, st.builds(DocId, _ns, _local), _version, _anchor)


@given(_citation)
def test_citations_round_trip_through_strings_and_urls(c: Citation) -> None:
    assert parse_citation(str(c)) == c
    assert parse_url(c.url(BASE)) == (c.ref, None)
    assert [f.citation for f in find_citations(f"as shown ({c}) and at {c.url(BASE)}.")] == [c, c]


@given(_citation, st.text(min_size=1, max_size=200).filter(lambda s: s.strip() != ""))
def test_quotes_survive_the_url(c: Citation, quote: str) -> None:
    with_quote = Citation(c.doc, c.version, c.anchor, quote)
    ref, parsed = parse_url(with_quote.url(BASE))
    assert ref == c.ref
    assert parsed == quote


@given(st.text(max_size=60))
def test_parsers_never_crash(text: str) -> None:
    for parse in (parse_ref, parse_citation, Anchor.parse, DocId.parse, parse_url):
        with contextlib.suppress(IdError):
            parse(text)
    find_citations(text)
