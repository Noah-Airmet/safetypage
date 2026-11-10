"""Frozen corpus snapshots: everything search and the site need, immutable once sealed.

    <root>/
      blobs/sha256/ab/cd/<hash>     every fetched file, both tiers. Private. Never served.
      snapshots/
        2026.11.0/                  sealed: nothing in here changes again
          manifest.json             what is in it, with hashes, counts and the content digest
          corpus.sqlite             all text, both tiers. Private.
          lexical/                  the Tantivy index            (built by the search track)
          dense/<model>/            vectors.f16.npy + unit list  (built by the search track)
          public/                   THE ONLY directory that is ever published as static files
            docs/<ns>/<id>.json                      document cards, both tiers (no text)
            text/<ns>/<id>/<ver>/<anchor>.json       unit text         open tier only
            pages/<ns>/<id>/<ver>/p<n>.<w>.webp      page images       open tier only
            files/<ns>/<id>/<ver>/source.<ext>       the file itself   open tier only
        2026.11.0.staging/          being built; renamed into place by seal_snapshot
        current -> 2026.11.0        swapped atomically; several snapshots are served side by side
      ops.sqlite                    runs, traces, the call log. The only mutable database.

Lifecycle: :func:`stage_snapshot` copies the working corpus into a staging directory; builders add
``lexical/``, ``dense/`` and ``public/``; :func:`seal_snapshot` runs the gates, writes the manifest
and renames the directory into place; :func:`set_current` points ``current`` at it.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from pathlib import Path, PurePosixPath
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from onthepage.blobs import sha256_file
from onthepage.corpus import Corpus, utc_now
from onthepage.ids import Citation, DocId, IdError, Ref, parse_ref
from onthepage.licence import Tier
from onthepage.migrate import current_version

__all__ = [
    "CORPUS_DB",
    "MANIFEST",
    "FileEntry",
    "Manifest",
    "SnapshotError",
    "VersionEntry",
    "check_public_tree",
    "corpus_digest",
    "list_snapshots",
    "load_manifest",
    "public_doc_path",
    "public_file_path",
    "public_page_image_path",
    "public_text_path",
    "resolve_snapshot",
    "seal_snapshot",
    "set_current",
    "stage_snapshot",
    "verify_snapshot",
]

CORPUS_DB: Final = "corpus.sqlite"
MANIFEST: Final = "manifest.json"
PUBLIC: Final = "public"
STAGING_SUFFIX: Final = ".staging"
SCHEMA: Final = "onthepage.snapshot/1"

_ID_RE: Final = re.compile(r"[0-9]{4}\.[0-9]{2}\.[0-9]+")
_OPEN_ONLY_AREAS: Final = frozenset({"text", "pages", "files"})


class SnapshotError(RuntimeError):
    pass


# ---------------------------------------------------------------------------------------
# Paths inside public/
# ---------------------------------------------------------------------------------------


def public_doc_path(doc: DocId) -> PurePosixPath:
    """The document card (a ``DocumentCard`` as JSON). Exists for both tiers."""
    return PurePosixPath(PUBLIC, "docs", doc.ns, f"{doc.local}.json")


def public_text_path(citation: Citation) -> PurePosixPath:
    """One unit's text (a ``UnitText`` as JSON). Open tier only; single anchors, not ranges."""
    if citation.anchor.is_range:
        raise IdError("static files are per unit: give a single anchor, not a range")
    return PurePosixPath(
        PUBLIC,
        "text",
        citation.doc.ns,
        citation.doc.local,
        citation.version,
        f"{citation.anchor}.json",
    )


def public_page_image_path(citation: Citation, width: int) -> PurePosixPath:
    """A rendered page image at ``width`` pixels. Open tier, paged versions only."""
    if citation.anchor.kind != "p" or citation.anchor.is_range:
        raise IdError("page images exist for single pages only")
    return PurePosixPath(
        PUBLIC,
        "pages",
        citation.doc.ns,
        citation.doc.local,
        citation.version,
        f"{citation.anchor}.{width}.webp",
    )


def public_file_path(ref: Ref, extension: str) -> PurePosixPath:
    """The source file itself (``source.pdf``, ``source.html``). Open tier only."""
    if ref.version is None:
        raise IdError("a source file belongs to one version")
    return PurePosixPath(
        PUBLIC, "files", ref.doc.ns, ref.doc.local, ref.version, f"source.{extension}"
    )


# ---------------------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------------------


class FileEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    """Relative to the snapshot directory, with ``/`` separators."""
    sha256: str
    bytes: int


class VersionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str
    """``doc_id/version``."""
    content_sha256: str
    tier: Tier
    licence: str
    units: int


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_: Literal["onthepage.snapshot/1"] = Field(default=SCHEMA, alias="schema")
    snapshot_id: str
    created_at: str
    code_version: str | None
    """The git commit of the code that built it."""
    corpus_schema_version: int
    content_digest: str
    """A hash of what the snapshot says (every unit's text, every version's licence and tier),
    independent of file layout and build time. Same inputs, same digest."""
    counts: dict[str, Any]
    versions: list[VersionEntry]
    components: dict[str, dict[str, Any]] = Field(default_factory=dict[str, dict[str, Any]])
    """What each builder added, by name: ``lexical``, ``dense/<model>``, ``public``."""
    files: list[FileEntry]


def corpus_digest(corpus: Corpus) -> str:
    """Hash the corpus's content: versions (with licence and tier) and every unit's text."""
    digest = hashlib.sha256()
    for version in corpus.all_versions():
        digest.update(
            f"V\t{version.ref}\t{version.content_sha256}\t{version.licence}\t"
            f"{version.tier.value}\n".encode()
        )
    rows = corpus.conn.execute("SELECT cite, text FROM units ORDER BY cite")
    for cite, text in rows:
        digest.update(f"U\t{cite}\t{hashlib.sha256(text.encode()).hexdigest()}\n".encode())
    return digest.hexdigest()


def _snapshots_dir(root: Path) -> Path:
    return root / "snapshots"


def _check_id(snapshot_id: str) -> None:
    if not _ID_RE.fullmatch(snapshot_id):
        raise SnapshotError(f"bad snapshot id {snapshot_id!r}: expected YYYY.MM.N, e.g. 2026.11.0")


def stage_snapshot(corpus_db: Path, root: Path, snapshot_id: str) -> Path:
    """Start a snapshot: copy the working corpus into ``<id>.staging/``. Returns that directory."""
    _check_id(snapshot_id)
    final = _snapshots_dir(root) / snapshot_id
    staging = _snapshots_dir(root) / (snapshot_id + STAGING_SUFFIX)
    if final.exists():
        raise SnapshotError(f"snapshot {snapshot_id} already exists; snapshots are immutable")
    if staging.exists():
        raise SnapshotError(f"{staging} already exists; remove it or pick another id")
    staging.mkdir(parents=True)
    source = sqlite3.connect(f"{corpus_db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        source.execute("VACUUM INTO ?", (str(staging / CORPUS_DB),))
    finally:
        source.close()
    return staging


def _walk(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*") if p.is_file() and p.name != MANIFEST)


def seal_snapshot(
    staging: Path,
    *,
    code_version: str | None = None,
    created_at: str | None = None,
    components: dict[str, dict[str, Any]] | None = None,
) -> Manifest:
    """Run the gates, write the manifest, and rename the staging directory into place.

    Refuses to seal if the corpus fails validation or if ``public/`` holds anything of a
    link-only document.
    """
    if not staging.name.endswith(STAGING_SUFFIX):
        raise SnapshotError(f"{staging} is not a staging directory")
    snapshot_id = staging.name.removesuffix(STAGING_SUFFIX)
    _check_id(snapshot_id)
    final = staging.with_name(snapshot_id)
    if final.exists():
        raise SnapshotError(f"snapshot {snapshot_id} already exists; snapshots are immutable")

    with Corpus.open(staging / CORPUS_DB, readonly=True) as corpus:
        problems = corpus.validate() + check_public_tree(staging, corpus)
        if problems:
            listing = "\n  ".join(problems[:20])
            raise SnapshotError(f"snapshot {snapshot_id} failed its gates:\n  {listing}")
        manifest = Manifest(
            snapshot_id=snapshot_id,
            created_at=created_at or utc_now(),
            code_version=code_version,
            corpus_schema_version=current_version(corpus.conn),
            content_digest=corpus_digest(corpus),
            counts=corpus.counts(),
            versions=[
                VersionEntry(
                    ref=v.ref,
                    content_sha256=v.content_sha256,
                    tier=v.tier,
                    licence=v.licence,
                    units=corpus.unit_count(v.version_id),
                )
                for v in corpus.all_versions()
            ],
            components=components or {},
            files=[],
        )
    manifest.files = [
        FileEntry(
            path=path.relative_to(staging).as_posix(),
            sha256=sha256_file(path),
            bytes=path.stat().st_size,
        )
        for path in _walk(staging)
    ]
    (staging / MANIFEST).write_text(
        manifest.model_dump_json(indent=2, by_alias=True) + "\n", encoding="utf-8"
    )
    staging.rename(final)
    return manifest


def load_manifest(snapshot_dir: Path) -> Manifest:
    try:
        text = (snapshot_dir / MANIFEST).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SnapshotError(f"{snapshot_dir} has no manifest: not a sealed snapshot") from None
    return Manifest.model_validate_json(text)


def verify_snapshot(snapshot_dir: Path) -> list[str]:
    """Re-hash a sealed snapshot against its manifest. Returns the problems found."""
    manifest = load_manifest(snapshot_dir)
    problems: list[str] = []
    listed = {entry.path: entry for entry in manifest.files}
    present = {p.relative_to(snapshot_dir).as_posix(): p for p in _walk(snapshot_dir)}
    for path in sorted(listed.keys() - present.keys()):
        problems.append(f"missing: {path}")
    for path in sorted(present.keys() - listed.keys()):
        problems.append(f"not in the manifest: {path}")
    for path in sorted(listed.keys() & present.keys()):
        if sha256_file(present[path]) != listed[path].sha256:
            problems.append(f"changed since sealing: {path}")
    return problems


def list_snapshots(root: Path) -> list[str]:
    """Sealed snapshot ids under ``root``, oldest first."""
    base = _snapshots_dir(root)
    if not base.is_dir():
        return []
    ids = [
        p.name
        for p in base.iterdir()
        if p.is_dir()
        and not p.is_symlink()
        and _ID_RE.fullmatch(p.name)
        and (p / MANIFEST).is_file()
    ]
    return sorted(ids, key=lambda s: [int(part) for part in s.split(".")])


def resolve_snapshot(root: Path, name: str = "current") -> Path:
    """The directory of a snapshot by id, or of whichever one ``current`` points at."""
    base = _snapshots_dir(root)
    if name == "current":
        link = base / "current"
        if not link.is_symlink():
            raise SnapshotError(f"no current snapshot under {root}")
        target = (base / link.readlink()).resolve()
    else:
        _check_id(name)
        target = base / name
    if not (target / MANIFEST).is_file():
        raise SnapshotError(f"no sealed snapshot {name!r} under {root}")
    return target


def set_current(root: Path, snapshot_id: str) -> None:
    """Point ``current`` at a sealed snapshot, atomically (a rename over the old link)."""
    resolve_snapshot(root, snapshot_id)
    base = _snapshots_dir(root)
    temporary = base / f".current-{os.getpid()}"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(snapshot_id)
    temporary.replace(base / "current")


# ---------------------------------------------------------------------------------------
# The publish gate
# ---------------------------------------------------------------------------------------


def check_public_tree(snapshot_dir: Path, corpus: Corpus) -> list[str]:
    """Everything under ``public/`` must be something the licence tiers allow to be published.

    Document cards are allowed for every document. Text, page images and source files are
    allowed only under a version whose tier is ``open``. Anything else under ``public/`` (a
    stray file, an unknown area, a version that is not in the corpus) is a problem.
    """
    public = snapshot_dir / PUBLIC
    if not public.is_dir():
        return []
    tiers = {v.ref: v.tier for v in corpus.all_versions()}
    documents = set(corpus.doc_ids())
    problems: list[str] = []
    for path in sorted(p for p in public.rglob("*") if p.is_file()):
        rel = path.relative_to(public).as_posix()
        parts = rel.split("/")
        area = parts[0]
        try:
            if area == "docs" and len(parts) == 3 and parts[2].endswith(".json"):
                doc = DocId(parts[1], parts[2].removesuffix(".json"))
                if str(doc) not in documents:
                    problems.append(f"public/{rel}: no such document")
                continue
            if area in _OPEN_ONLY_AREAS and len(parts) == 5:
                ref = parse_ref(f"{parts[1]}:{parts[2]}/{parts[3]}")
                tier = tiers.get(str(ref))
                if tier is None:
                    problems.append(f"public/{rel}: no such version")
                elif tier is not Tier.OPEN:
                    problems.append(
                        f"public/{rel}: {ref} is link-only; its {area} cannot be published"
                    )
                continue
        except IdError as exc:
            problems.append(f"public/{rel}: {exc}")
            continue
        problems.append(f"public/{rel}: not a recognised public file")
    return problems
