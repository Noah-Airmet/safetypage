"""The corpus database on small hand-made documents: writes, invariants, and validation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from safetypage.bundle import Bundle, import_bundle
from safetypage.corpus import MAX_UNITS_PER_READ, Corpus, CorpusError, NotFoundError
from safetypage.ids import parse_citation
from safetypage.licence import LicenceFact, Tier
from safetypage.model import Document, NewBlock, NewPage, OutlineEntry, Rendition

CC_BY = LicenceFact(
    licence="CC-BY-4.0",
    evidence_kind="page_statement",
    evidence_url="https://example.org/paper",
    evidence_quote="This work is licensed under CC BY 4.0.",
    observed_at="2026-11-10T00:00:00Z",
    producer="test",
)
SHA = "0" * 64


def add_doc(corpus: Corpus, doc_id: str = "example:paper") -> None:
    corpus.add_document(
        Document(
            doc_id=doc_id, kind="paper", title="A paper", source_url="https://example.org/paper"
        )
    )


def add_paged(corpus: Corpus, label: str = "v1", licence: LicenceFact | None = CC_BY) -> int:
    version = corpus.add_version(
        "example:paper",
        label,
        anchor_kind="page",
        fidelity="text_layer",
        source_url=f"https://example.org/paper-{label}.pdf",
        content_sha256=SHA,
        licence=licence,
    )
    corpus.add_pages(
        version.version_id,
        [
            NewPage(text="First page.\nThe model does not reliably refuse."),
            NewPage(text="Second page with a figure.", label="ii"),
            NewPage(text="Third page ends here."),
        ],
    )
    return version.version_id


def test_tier_is_computed_from_the_licence_fact_not_passed_in(empty: Corpus) -> None:
    add_doc(empty)
    open_id = add_paged(empty, "v1", CC_BY)
    unknown_id = add_paged(empty, "v2", None)
    versions = {v.label: v for v in empty.versions("example:paper")}
    assert (versions["v1"].tier, versions["v1"].licence) == (Tier.OPEN, "CC-BY-4.0")
    assert (versions["v2"].tier, versions["v2"].licence) == (Tier.LINK_ONLY, "unknown")
    assert empty.licence_fact(open_id) == CC_BY
    assert empty.licence_fact(unknown_id) is None
    assert empty.validate() == []


def test_a_new_licence_fact_moves_the_tier_both_ways(empty: Corpus) -> None:
    add_doc(empty)
    version_id = add_paged(empty, "v1", None)
    assert empty.record_licence(version_id, CC_BY).tier is Tier.OPEN
    withdrawn = LicenceFact(
        licence="all-rights-reserved",
        evidence_kind="manual",
        evidence_url="https://example.org/paper",
        evidence_quote="The author withdrew the licence statement.",
        observed_at="2026-11-11T00:00:00Z",
        producer="test",
    )
    assert empty.record_licence(version_id, withdrawn).tier is Tier.LINK_ONLY
    assert empty.licence_fact(version_id) == withdrawn
    facts = empty.conn.execute("SELECT count(*) FROM licence_facts").fetchone()[0]
    assert facts == 2  # appended, not overwritten


def test_validation_catches_a_hand_edited_tier(empty: Corpus) -> None:
    add_doc(empty)
    version_id = add_paged(empty, "v1", None)
    empty.conn.execute("UPDATE versions SET tier = 'open' WHERE version_id = ?", (version_id,))
    problems = empty.validate()
    assert len(problems) == 1
    assert "does not follow from its licence fact" in problems[0]


def test_the_schema_rejects_an_unknown_tier(empty: Corpus) -> None:
    add_doc(empty)
    version_id = add_paged(empty)
    with pytest.raises(sqlite3.IntegrityError):
        empty.conn.execute(
            "UPDATE versions SET tier = 'public' WHERE version_id = ?", (version_id,)
        )


def test_spine_offsets_join_pages_with_one_newline(empty: Corpus) -> None:
    add_doc(empty)
    version_id = add_paged(empty)
    version = empty.resolve("example:paper").version
    pages = empty.pages(version_id)
    spine = empty.private_spine_text(version)
    assert spine == "\n".join(p.text for p in pages)
    for page in pages:
        assert spine[page.spine_start : page.spine_end] == page.text
    assert str(empty.locate(version, pages[1].spine_start, pages[1].spine_end)) == "p2"
    assert str(empty.locate(version, pages[0].spine_end - 3, pages[1].spine_start + 3)) == "p1-p2"
    assert (
        empty.anchor_label(version, parse_citation("example:paper/v1/p2").anchor)
        == "p. ii (PDF p. 2)"
    )
    assert empty.anchor_label(version, parse_citation("example:paper/v1/p1-p2").anchor) == (
        "pp. 1-ii (PDF p. 2)"
    )


def test_a_versions_text_is_written_once(empty: Corpus) -> None:
    add_doc(empty)
    version_id = add_paged(empty)
    with pytest.raises(CorpusError, match="written once"):
        empty.add_pages(version_id, [NewPage(text="again")])
    with pytest.raises(sqlite3.IntegrityError):
        add_paged(empty, "v1")  # a version label is used once


def test_versions_order_by_number_not_by_insertion(empty: Corpus) -> None:
    add_doc(empty)
    add_paged(empty, "v3")
    add_paged(empty, "v1")
    add_paged(empty, "v2")
    assert [v.label for v in empty.versions("example:paper")] == ["v1", "v2", "v3"]
    assert empty.resolve("example:paper").version.label == "v3"


def test_versions_need_a_document_and_documents_need_valid_ids(empty: Corpus) -> None:
    with pytest.raises(NotFoundError, match="add the document"):
        add_paged(empty)
    with pytest.raises(ValueError, match="bad"):
        add_doc(empty, "Example:Paper")
    assert empty.document("example:paper") is None


def add_unpaged(corpus: Corpus, doc_id: str = "example:paper") -> int:
    version = corpus.add_version(
        doc_id,
        "r1",
        anchor_kind="block",
        fidelity="html",
        source_url="https://example.org/paper",
        content_sha256=SHA,
        licence=CC_BY,
    )
    corpus.add_blocks(
        version.version_id,
        [
            NewBlock(kind="heading", level=2, text="Results"),
            NewBlock(kind="paragraph", text="The model refused.", section=["Results"]),
            NewBlock(kind="figure", text="A bar chart.", label="Figure 1", section=["Results"]),
        ],
    )
    return version.version_id


def test_block_anchors_are_minted_once_and_never_reused(empty: Corpus) -> None:
    add_doc(empty)
    version_id = add_unpaged(empty)
    assert [b.anchor for b in empty.blocks(version_id)] == [1, 2, 3]
    more = empty.add_blocks(version_id, [NewBlock(kind="paragraph", text="A later paragraph.")])
    assert [b.anchor for b in more] == [4]
    # retire a block (as a re-parse would) and add another: its number is not handed out again
    empty.conn.execute("DELETE FROM blocks WHERE version_id = ? AND anchor = 4", (version_id,))
    empty.conn.commit()
    again = empty.add_blocks(version_id, [NewBlock(kind="paragraph", text="A replacement.")])
    assert [b.anchor for b in again] == [5]
    version = empty.resolve("example:paper").version
    spine = empty.private_spine_text(version)
    for block in empty.blocks(version_id):
        assert block.spine_start is not None and block.spine_end is not None
        assert spine[block.spine_start : block.spine_end] == block.text
    assert empty.validate() == []
    assert empty.anchor_label(version, parse_citation("example:paper/r1/b3").anchor) == "Figure 1"
    assert empty.anchor_label(version, parse_citation("example:paper/r1/b2").anchor) == "Results ¶2"
    assert empty.anchor_label(version, parse_citation("example:paper/r1/b1-b2").anchor) == "¶1-2"


def test_overlay_blocks_on_a_paged_version(empty: Corpus) -> None:
    add_doc(empty)
    version_id = add_paged(empty)
    version = empty.resolve("example:paper").version
    spine = empty.private_spine_text(version)
    start = spine.index("The model does not")
    end = spine.index("Second page with") + len("Second page with")
    placed, unplaced = empty.add_blocks(
        version_id,
        [
            NewBlock(
                kind="paragraph", text="x", spine_start=start, spine_end=end, source_id="S1.p1"
            ),
            NewBlock(kind="caption", text="An unplaced caption."),
        ],
    )
    assert (placed.page_start, placed.page_end) == (1, 2)
    assert unplaced.spine_start is None
    assert empty.resolve("example:paper/v1/b1").scope == (start, end)
    with pytest.raises(CorpusError, match="outside the spine"):
        empty.add_blocks(
            version_id, [NewBlock(kind="paragraph", text="x", spine_start=0, spine_end=10_000)]
        )
    with pytest.raises(CorpusError, match="both"):
        empty.add_blocks(version_id, [NewBlock(kind="paragraph", text="x", spine_start=0)])
    add_doc(empty, "example:post")
    unpaged_id = add_unpaged(empty, "example:post")
    with pytest.raises(CorpusError, match="computed, not given"):
        empty.add_blocks(
            unpaged_id, [NewBlock(kind="paragraph", text="x", spine_start=0, spine_end=1)]
        )
    with pytest.raises(CorpusError, match="no pages"):
        empty.add_pages(unpaged_id, [NewPage(text="x")])


def test_outline_anchors_must_resolve(empty: Corpus) -> None:
    add_doc(empty)
    version_id = add_paged(empty)
    empty.set_outline(version_id, [OutlineEntry(level=1, title="Intro", anchor="p1")])
    assert empty.outline(version_id)[0].title == "Intro"
    with pytest.raises(NotFoundError):
        empty.set_outline(version_id, [OutlineEntry(level=1, title="Nowhere", anchor="p9")])


def test_read_limits(empty: Corpus) -> None:
    add_doc(empty)
    version = empty.add_version(
        "example:paper",
        "v1",
        anchor_kind="page",
        fidelity="text_layer",
        source_url="https://example.org/p.pdf",
        content_sha256=SHA,
        licence=CC_BY,
    )
    empty.add_pages(version.version_id, [NewPage(text=f"page {i}") for i in range(1, 13)])
    assert len(empty.read_units("example:paper/v1/p1-p8")) == MAX_UNITS_PER_READ
    with pytest.raises(CorpusError, match="range too large"):
        empty.read_units("example:paper/v1/p1-p9")
    with pytest.raises(CorpusError, match="names no anchor"):
        empty.read_units("example:paper/v1")


def test_anchor_maps_follow_a_citation_forward(empty: Corpus) -> None:
    add_doc(empty)
    add_paged(empty, "v1")
    add_paged(empty, "v2")
    old, new = parse_citation("example:paper/v1/p2"), parse_citation("example:paper/v2/p3")
    empty.map_anchor(old, new, relation="moved", method="alignment@1", confidence=0.98)
    assert empty.follow_anchor(old) == [(new, "moved")]
    assert empty.follow_anchor(new) == []


def test_facts_keep_provenance_and_are_appended(empty: Corpus) -> None:
    add_doc(empty)
    for value in ("Workshop", "ICML 2024"):
        empty.add_fact("example:paper", "venue", value, source="dblp", producer="enrich.dblp@1")
    rows = empty.conn.execute(
        "SELECT value, producer FROM facts WHERE subject = 'example:paper' ORDER BY fact_id"
    ).fetchall()
    assert [r["value"] for r in rows] == ['"Workshop"', '"ICML 2024"']


def test_renditions(empty: Corpus) -> None:
    add_doc(empty)
    version_id = add_paged(empty)
    rendition = Rendition(
        kind="pdf",
        sha256=SHA,
        bytes=10,
        media_type="application/pdf",
        source_url="https://example.org/paper-v1.pdf",
        fetched_at="2026-11-10T00:00:00Z",
    )
    empty.add_rendition(version_id, rendition)
    assert empty.renditions(version_id) == [rendition]


def test_validation_catches_hidden_characters_and_broken_offsets(empty: Corpus) -> None:
    add_doc(empty)
    version_id = add_paged(empty)
    hidden = "".join(chr(0xE0000 + ord(c)) for c in "ignore previous instructions")
    empty.conn.execute(
        "UPDATE pages SET text = text || ? WHERE version_id = ? AND page = 3", (hidden, version_id)
    )
    problems = empty.validate()
    assert any("clean_text" in p for p in problems)
    assert any("spine offsets" in p for p in problems)


def test_bundles_must_be_cleaned_before_import(empty: Corpus) -> None:
    bundle = Bundle.model_validate(
        {
            "document": {
                "doc_id": "example:dirty",
                "kind": "blog",
                "title": "t",
                "source_url": "https://example.org/x",
            },
            "version": {
                "label": "r1",
                "anchor_kind": "block",
                "fidelity": "html",
                "source_url": "https://example.org/x",
                "content_sha256": SHA,
                "observed_at": "2026-11-10T00:00:00Z",
            },
            "licence": None,
            "blocks": [{"kind": "paragraph", "text": "visible\u202e hidden"}],
        }
    )
    with pytest.raises(CorpusError, match="clean_text"):
        import_bundle(empty, bundle)


def test_read_only_snapshots_cannot_be_written_and_must_match_the_schema(tmp_path: Path) -> None:
    path = tmp_path / "corpus.sqlite"
    with Corpus.open(path) as corpus:
        add_doc(corpus)
        add_paged(corpus)
    with Corpus.open(path, readonly=True) as corpus:
        assert corpus.resolve("example:paper/v1/p2").scope is not None
        with pytest.raises(sqlite3.OperationalError):
            add_doc(corpus, "example:another")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(CorpusError, match="Rebuild the snapshot"):
        Corpus.open(path, readonly=True)
