from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from safetypage.blobs import BlobError, BlobStore, sha256_bytes, sha256_file


def test_put_get_round_trip_and_layout(tmp_path: Path) -> None:
    store = BlobStore(tmp_path / "blobs")
    digest = store.put(b"the text of record")
    assert digest == sha256_bytes(b"the text of record")
    assert store.has(digest)
    assert store.get(digest) == b"the text of record"
    path = store.path(digest)
    assert path.relative_to(tmp_path / "blobs").parts == ("sha256", digest[:2], digest[2:4], digest)
    assert sha256_file(path) == digest
    with store.open(digest) as handle:
        assert handle.read(3) == b"the"


def test_the_same_bytes_are_stored_once(tmp_path: Path) -> None:
    store = BlobStore(tmp_path)
    first = store.put(b"same")
    mtime = store.path(first).stat().st_mtime_ns
    assert store.put(b"same") == first
    assert store.path(first).stat().st_mtime_ns == mtime
    assert list(store) == [first]
    assert not list(tmp_path.rglob(".tmp-*"))


def test_put_file(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.5 ...")
    store = BlobStore(tmp_path / "blobs")
    assert store.get(store.put_file(source)) == b"%PDF-1.5 ..."


def test_corruption_is_detected_on_read(tmp_path: Path) -> None:
    store = BlobStore(tmp_path)
    digest = store.put(b"original")
    store.path(digest).write_bytes(b"tampered")
    with pytest.raises(BlobError, match="corrupt"):
        store.get(digest)
    assert store.get(digest, verify=False) == b"tampered"


def test_missing_and_malformed(tmp_path: Path) -> None:
    store = BlobStore(tmp_path)
    assert list(store) == []
    with pytest.raises(BlobError, match="no blob"):
        store.get("a" * 64)
    with pytest.raises(BlobError, match="no blob"):
        store.open("a" * 64)
    for bad in ["", "abc", "../../etc/passwd", "A" * 64, "g" * 64]:
        with pytest.raises(BlobError, match="not a SHA-256"):
            store.path(bad)
    assert not store.has("b" * 64)


@given(st.lists(st.binary(max_size=200), max_size=8))
def test_any_bytes_round_trip(tmp_path_factory: pytest.TempPathFactory, blobs: list[bytes]) -> None:
    store = BlobStore(tmp_path_factory.mktemp("blobs"))
    digests = [store.put(b) for b in blobs]
    assert [store.get(d) for d in digests] == blobs
    assert sorted(set(digests)) == list(store)
