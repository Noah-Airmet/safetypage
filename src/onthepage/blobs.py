"""Content-addressed file storage: a file's name is the SHA-256 of its bytes.

Every fetched rendition lands here, for both tiers, and the store as a whole is private. The
database refers to files by hash only, so moving or renaming anything on disk cannot lose a
record, and the same bytes fetched twice are stored once.

Layout: ``<root>/sha256/ab/cd/abcd...`` (two levels of fan-out).
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, Final

__all__ = ["BlobError", "BlobStore", "sha256_bytes", "sha256_file"]

_HEX_RE: Final = re.compile(r"[0-9a-f]{64}")
_CHUNK: Final = 1 << 20


class BlobError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


class BlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, sha256: str) -> Path:
        if not _HEX_RE.fullmatch(sha256):
            raise BlobError(f"not a SHA-256 hex digest: {sha256!r}")
        return self.root / "sha256" / sha256[:2] / sha256[2:4] / sha256

    def has(self, sha256: str) -> bool:
        return self.path(sha256).is_file()

    def put(self, data: bytes) -> str:
        """Store ``data`` and return its hash. Storing the same bytes again is a no-op."""
        digest = sha256_bytes(data)
        target = self.path(digest)
        if target.is_file():
            return digest
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write beside the target, then rename: a reader never sees a half-written blob.
        fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            Path(tmp_name).replace(target)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return digest

    def put_file(self, source: Path) -> str:
        return self.put(source.read_bytes())

    def get(self, sha256: str, *, verify: bool = True) -> bytes:
        """Read a blob. With ``verify`` (the default) the bytes are re-hashed first."""
        target = self.path(sha256)
        try:
            data = target.read_bytes()
        except FileNotFoundError:
            raise BlobError(f"no blob {sha256}") from None
        if verify and sha256_bytes(data) != sha256:
            raise BlobError(f"blob {sha256} is corrupt: its bytes no longer match its name")
        return data

    def open(self, sha256: str) -> BinaryIO:
        try:
            return self.path(sha256).open("rb")
        except FileNotFoundError:
            raise BlobError(f"no blob {sha256}") from None

    def __iter__(self) -> Iterator[str]:
        base = self.root / "sha256"
        if not base.is_dir():
            return
        for path in sorted(base.glob("??/??/*")):
            if _HEX_RE.fullmatch(path.name):
                yield path.name
