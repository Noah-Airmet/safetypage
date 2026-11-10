from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from safetypage.blobs import BlobStore
from safetypage.build import snapshot as build
from safetypage.build.snapshot import build_snapshot
from safetypage.corpus import Corpus
from safetypage.ids import parse_citation, parse_ref
from safetypage.snapshot import (
    Manifest,
    SnapshotError,
    load_manifest,
    public_doc_path,
    public_file_path,
    public_page_image_path,
    public_text_path,
    resolve_snapshot,
    verify_snapshot,
)

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "corpus"
OPEN_PAGE = parse_citation("arxiv:2305.15324/v2/p6")


@pytest.fixture(scope="module")
def root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("data")
    blobs = BlobStore(root / "blobs")
    for source in sorted((FIXTURES / "sources").iterdir()):
        blobs.put(source.read_bytes())
    return root


@pytest.fixture(scope="module")
def built(root: Path, fixture_db: Path) -> tuple[Path, Manifest]:
    manifest = build_snapshot(fixture_db, root, "2026.11.0", make_current=True, dense_model=None)
    return resolve_snapshot(root), manifest


def test_sealed_and_current(built: tuple[Path, Manifest]) -> None:
    directory, manifest = built
    assert directory.name == "2026.11.0" == manifest.snapshot_id
    assert verify_snapshot(directory) == []
    assert manifest.components["lexical"]["units"] == manifest.counts["units"]
    public = manifest.components["public"]
    assert public["cards"] == 6 and public["missing_blobs"] == 0
    assert public["images"] == 2 * (20 + 20 + 20 + 48)  # four open PDFs, two widths
    assert (directory / "lexical" / "meta.json").is_file()


def test_public_holds_cards_for_both_tiers_and_text_only_for_open(
    built: tuple[Path, Manifest], fixture_db: Path
) -> None:
    directory, _ = built
    for doc in ("arxiv:2305.15324", "example:link-only-eval-report", "example:unlicensed-post"):
        card = json.loads((directory / str(public_doc_path(parse_ref(doc).doc))).read_text())
        assert card["doc_id"] == doc
    public = directory / "public"
    for area in ("text", "pages", "files"):
        assert not (public / area / "example").exists()
    unit = json.loads((directory / str(public_text_path(OPEN_PAGE))).read_text())
    with Corpus.open(fixture_db, readonly=True) as corpus:
        expected = corpus.read_units(str(OPEN_PAGE), layout=True)[0]
    assert unit["text"] == expected.text and unit["words"] == [
        list(w) for w in expected.words or []
    ]
    block = parse_citation("distill:zoom-in/r1/b3")
    assert (directory / str(public_text_path(block))).is_file()
    assert (directory / str(public_file_path(OPEN_PAGE.ref, "pdf"))).is_file()
    assert (directory / str(public_file_path(parse_ref("distill:zoom-in/r1"), "html"))).is_file()


def test_page_images(built: tuple[Path, Manifest]) -> None:
    directory, _ = built
    for width in build.PAGE_WIDTHS:
        with Image.open(directory / str(public_page_image_path(OPEN_PAGE, width))) as image:
            assert image.format == "WEBP" and abs(image.width - width) <= 1


def test_image_cache_is_reused(root: Path, fixture_db: Path, built: tuple[Path, Manifest]) -> None:
    del built
    manifest = build_snapshot(fixture_db, root, "2026.11.1", dense_model=None)
    assert manifest.components["public"]["rendered"] == 0
    assert manifest.components["public"]["images"] == 216


def test_failed_build_leaves_nothing(
    root: Path, fixture_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object, **__: object) -> dict[str, object]:
        raise RuntimeError("index build failed")

    monkeypatch.setattr(build, "build_lexical_index", broken)
    with pytest.raises(RuntimeError, match="index build failed"):
        build_snapshot(fixture_db, root, "2026.11.5", images=False, dense_model=None)
    assert not (root / "snapshots" / "2026.11.5.staging").exists()
    assert not (root / "snapshots" / "2026.11.5").exists()


def test_publish_gate_stops_link_only_files(
    root: Path, fixture_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the export ever wrote a link-only unit's text, sealing would refuse the snapshot."""
    leak = parse_citation("example:link-only-eval-report/r1/p1")
    original = build.export_public

    def leaky(corpus: Corpus, staging: Path, **kwargs: object) -> dict[str, int]:
        counts = original(corpus, staging, **kwargs)  # type: ignore[arg-type]
        path = staging / str(public_text_path(leak))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        return counts

    monkeypatch.setattr(build, "export_public", leaky)
    with pytest.raises(SnapshotError, match="link-only"):
        build_snapshot(fixture_db, root, "2026.11.6", images=False, dense_model=None)
    assert not (root / "snapshots" / "2026.11.6").exists()


def test_dense_skipped_without_vectors(root: Path, fixture_db: Path) -> None:
    manifest = build_snapshot(fixture_db, root, "2026.11.7", images=False)
    (component,) = (v for k, v in manifest.components.items() if k.startswith("dense/"))
    assert "have no vector" in component["skipped"]
    assert load_manifest(root / "snapshots" / "2026.11.7").snapshot_id == "2026.11.7"
