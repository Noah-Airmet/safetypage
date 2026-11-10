from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from onthepage.corpus import Corpus
from onthepage.ids import parse_citation, parse_ref
from onthepage.snapshot import (
    CORPUS_DB,
    MANIFEST,
    SnapshotError,
    check_public_tree,
    corpus_digest,
    list_snapshots,
    load_manifest,
    public_doc_path,
    public_file_path,
    public_page_image_path,
    public_text_path,
    resolve_snapshot,
    seal_snapshot,
    set_current,
    stage_snapshot,
    verify_snapshot,
)

OPEN = parse_citation("arxiv:2305.15324/v2/p6")
LINK_ONLY = parse_citation("example:link-only-eval-report/r1/p1")


def put(staging: Path, relative: object, content: str = "{}") -> Path:
    path = staging / str(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_public_paths() -> None:
    assert str(public_doc_path(OPEN.doc)) == "public/docs/arxiv/2305.15324.json"
    assert str(public_text_path(OPEN)) == "public/text/arxiv/2305.15324/v2/p6.json"
    assert (
        str(public_page_image_path(OPEN, 1600)) == "public/pages/arxiv/2305.15324/v2/p6.1600.webp"
    )
    assert str(public_file_path(OPEN.ref, "pdf")) == "public/files/arxiv/2305.15324/v2/source.pdf"
    with pytest.raises(ValueError, match="single"):
        public_text_path(parse_citation("arxiv:2305.15324/v2/p6-p7"))
    with pytest.raises(ValueError, match="single pages"):
        public_page_image_path(parse_citation("distill:zoom-in/r1/b3"), 800)
    with pytest.raises(ValueError, match="one version"):
        public_file_path(parse_ref("arxiv:2305.15324"), "pdf")


def test_stage_seal_verify_and_publish(fixture_db: Path, tmp_path: Path) -> None:
    staging = stage_snapshot(fixture_db, tmp_path, "2026.11.0")
    assert staging.name == "2026.11.0.staging"
    put(staging, public_doc_path(OPEN.doc))
    put(staging, public_doc_path(LINK_ONLY.doc))  # a link-only document still has a record
    put(staging, public_text_path(OPEN), '{"text": "..."}')
    put(staging, "lexical/meta.json")

    manifest = seal_snapshot(
        staging,
        code_version="abc1234",
        created_at="2026-11-10T03:00:00Z",
        components={"lexical": {"engine": "tantivy"}},
    )
    final = tmp_path / "snapshots" / "2026.11.0"
    assert final.is_dir() and not staging.exists()
    assert manifest.snapshot_id == "2026.11.0"
    assert manifest.counts["by_tier"]["link_only"]["versions"] == 2
    assert [v.ref for v in manifest.versions][:2] == ["arxiv:2305.15324/v1", "arxiv:2305.15324/v2"]
    assert {f.path for f in manifest.files} == {
        CORPUS_DB,
        "lexical/meta.json",
        "public/docs/arxiv/2305.15324.json",
        "public/docs/example/link-only-eval-report.json",
        "public/text/arxiv/2305.15324/v2/p6.json",
    }
    assert load_manifest(final) == manifest
    on_disk = json.loads((final / MANIFEST).read_text())
    assert on_disk["schema"] == "onthepage.snapshot/1"
    assert verify_snapshot(final) == []

    # the snapshot's corpus opens read-only and answers like the working copy
    with Corpus.open(final / CORPUS_DB, readonly=True) as corpus:
        assert (
            corpus.verify_quote("AI systems with dangerous capabilities", str(OPEN.ref)).verdict
            == "elsewhere"
        )
        assert corpus_digest(corpus) == manifest.content_digest

    assert list_snapshots(tmp_path) == ["2026.11.0"]
    with pytest.raises(SnapshotError, match="no current snapshot"):
        resolve_snapshot(tmp_path)
    set_current(tmp_path, "2026.11.0")
    assert resolve_snapshot(tmp_path) == final.resolve()
    assert resolve_snapshot(tmp_path, "2026.11.0") == final

    # a second snapshot is served side by side; current moves atomically
    seal_snapshot(stage_snapshot(fixture_db, tmp_path, "2026.11.1"))
    assert list_snapshots(tmp_path) == ["2026.11.0", "2026.11.1"]
    assert resolve_snapshot(tmp_path).name == "2026.11.0"
    set_current(tmp_path, "2026.11.1")
    assert resolve_snapshot(tmp_path).name == "2026.11.1"
    assert resolve_snapshot(tmp_path, "2026.11.0") == final  # the old one is still there


def test_snapshots_are_immutable(fixture_db: Path, tmp_path: Path) -> None:
    seal_snapshot(stage_snapshot(fixture_db, tmp_path, "2026.11.0"))
    with pytest.raises(SnapshotError, match="immutable"):
        stage_snapshot(fixture_db, tmp_path, "2026.11.0")
    final = tmp_path / "snapshots" / "2026.11.0"
    (final / "stray.txt").write_text("x")
    (final / CORPUS_DB).write_bytes((final / CORPUS_DB).read_bytes() + b"\0")
    assert verify_snapshot(final) == [
        "not in the manifest: stray.txt",
        f"changed since sealing: {CORPUS_DB}",
    ]
    (final / CORPUS_DB).unlink()
    assert f"missing: {CORPUS_DB}" in verify_snapshot(final)


def test_the_content_digest_depends_on_content_not_on_the_build(
    fixture_db: Path, tmp_path: Path
) -> None:
    a = seal_snapshot(
        stage_snapshot(fixture_db, tmp_path, "2026.11.0"), created_at="2026-11-10T00:00:00Z"
    )
    b = seal_snapshot(
        stage_snapshot(fixture_db, tmp_path, "2026.11.1"), created_at="2026-12-01T00:00:00Z"
    )
    assert a.content_digest == b.content_digest
    changed = tmp_path / "changed.sqlite"
    shutil.copy(fixture_db, changed)
    with Corpus.open(changed) as corpus:
        version = corpus.resolve("example:unlicensed-post").version
        corpus.conn.execute(
            "UPDATE blocks SET text = replace(text, 'backwards', 'sidewards') WHERE version_id = ?",
            (version.version_id,),
        )
        corpus.conn.commit()
        assert corpus.validate() == []
    c = seal_snapshot(stage_snapshot(changed, tmp_path, "2026.11.2"))
    assert c.content_digest != a.content_digest


@pytest.mark.parametrize(
    ("relative", "problem"),
    [
        (public_text_path(LINK_ONLY), "is link-only; its text cannot be published"),
        (public_page_image_path(LINK_ONLY, 800), "is link-only; its pages cannot be published"),
        (public_file_path(LINK_ONLY.ref, "pdf"), "is link-only; its files cannot be published"),
        ("public/text/example/unlicensed-post/r1/b1.json", "is link-only"),
        ("public/text/arxiv/2305.15324/v7/p1.json", "no such version"),
        ("public/docs/arxiv/9999.99999.json", "no such document"),
        ("public/dump.sqlite", "not a recognised public file"),
        ("public/text/arxiv/2305.15324/p1.json", "not a recognised public file"),
        ("public/secret/arxiv/2305.15324/v2/p1.json", "not a recognised public file"),
    ],
)
def test_the_publish_gate_refuses_to_seal(
    fixture_db: Path, tmp_path: Path, relative: object, problem: str
) -> None:
    """A snapshot that would publish link-only content, or anything unrecognised, is not sealed."""
    staging = stage_snapshot(fixture_db, tmp_path, "2026.11.0")
    put(staging, public_text_path(OPEN))
    put(staging, relative)
    with pytest.raises(SnapshotError, match="failed its gates") as excinfo:
        seal_snapshot(staging)
    assert problem in str(excinfo.value)
    assert staging.exists()
    assert not (tmp_path / "snapshots" / "2026.11.0").exists()
    with Corpus.open(staging / CORPUS_DB, readonly=True) as corpus:
        assert len(check_public_tree(staging, corpus)) == 1


def test_a_corpus_that_fails_validation_is_not_sealed(fixture_db: Path, tmp_path: Path) -> None:
    broken = tmp_path / "broken.sqlite"
    shutil.copy(fixture_db, broken)
    with Corpus.open(broken) as corpus:
        corpus.conn.execute("UPDATE versions SET tier = 'open' WHERE licence = 'unknown'")
        corpus.conn.commit()
    with pytest.raises(SnapshotError, match="does not follow from its licence fact"):
        seal_snapshot(stage_snapshot(broken, tmp_path, "2026.11.0"))


def test_bad_ids_and_directories(fixture_db: Path, tmp_path: Path) -> None:
    for bad in ["latest", "2026-11-0", "../2026.11.0", "2026.11"]:
        with pytest.raises(SnapshotError, match="bad snapshot id"):
            stage_snapshot(fixture_db, tmp_path, bad)
    with pytest.raises(SnapshotError, match="not a staging directory"):
        seal_snapshot(tmp_path)
    with pytest.raises(SnapshotError, match="no sealed snapshot"):
        set_current(tmp_path, "2026.11.5")
    with pytest.raises(SnapshotError, match="not a sealed snapshot"):
        load_manifest(tmp_path)
    assert list_snapshots(tmp_path / "nowhere") == []
    stage_snapshot(fixture_db, tmp_path, "2026.11.0")
    with pytest.raises(SnapshotError, match="already exists"):
        stage_snapshot(fixture_db, tmp_path, "2026.11.0")
    assert list_snapshots(tmp_path) == []  # staging directories are not snapshots
