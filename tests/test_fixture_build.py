"""The checked-in bundles are exactly what the fixture builder produces from the sources."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from onthepage.blobs import sha256_file
from onthepage.bundle import Bundle
from onthepage.licence import licence_from_url

REPO = Path(__file__).parent.parent
CORPUS = REPO / "fixtures" / "corpus"


def bundles() -> list[Bundle]:
    return [
        Bundle.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted((CORPUS / "bundles").glob("*.json"))
    ]


def test_every_rendition_is_the_committed_source_file() -> None:
    names = {
        spec["name"]: (entry["bundle"], kind)
        for entry in json.loads((CORPUS / "sources.json").read_text())["versions"]
        for kind, spec in entry["files"].items()
    }
    hashes = {sha256_file(CORPUS / "sources" / name): name for name in names}
    assert len(hashes) == len(names) == len(list((CORPUS / "sources").iterdir()))
    for bundle in bundles():
        assert bundle.renditions
        for rendition in bundle.renditions:
            assert rendition.sha256 in hashes
        assert bundle.version.content_sha256 in {r.sha256 for r in bundle.renditions}


def test_only_openly_licensed_or_synthetic_documents_are_committed() -> None:
    """Nothing that cannot be redistributed may be a fixture."""
    for bundle in bundles():
        if bundle.document.doc_id.startswith("example:"):
            assert "synthetic fixture" in bundle.document.title
            continue
        assert bundle.licence is not None
        assert bundle.licence.licence in {"CC-BY-4.0", "public-domain-us-gov"}
        if bundle.licence.evidence_kind == "licence_link":
            assert licence_from_url(bundle.licence.evidence_quote) == bundle.licence.licence


def test_bundles_rebuild_byte_for_byte() -> None:
    pytest.importorskip("pymupdf", reason="needs the fixtures dependency group")
    result = subprocess.run(
        [sys.executable, str(REPO / "fixtures" / "build.py"), "--check"],
        cwd=REPO,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
