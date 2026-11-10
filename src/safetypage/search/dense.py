"""The dense arm: one vector per unit, exact search over a flat matrix.

Three pieces:

- **The embedding cache** (``<root>/embeddings/<model>/``), filled by :func:`embed_units`, a
  resumable batch job. Vectors are keyed by the SHA-256 of the unit's text, so a unit that is
  unchanged between snapshots is never embedded twice, and a job stopped at any point resumes
  where it left off. The cache is a series of parts: ``part-00001.npy`` (float16 rows) and
  ``part-00001.keys`` (one key per row, written last, so a part without keys is ignored).
- **The snapshot's copy** (``dense/<model>/``), assembled by :func:`assemble_dense` when the
  cache covers every unit: ``vectors.f16.npy``, ``unit_ids.json`` (cite strings, row order),
  ``model.json``.
- **Search** (:class:`DenseIndex`): the query vector against every row, with the same filters
  as the keyword arm applied as masks.

Vectors are L2-normalised, so the score is cosine similarity. Unit text is truncated to
:data:`MAX_TOKENS` tokens for embedding.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Protocol

import numpy as np
import numpy.typing as npt

from safetypage.corpus import Corpus

__all__ = [
    "DEFAULT_MODEL",
    "MAX_TOKENS",
    "DenseIndex",
    "Embedder",
    "SentenceTransformerEmbedder",
    "assemble_dense",
    "cache_keys",
    "embed_units",
    "model_slug",
    "text_key",
]

DEFAULT_MODEL: Final = "Qwen/Qwen3-Embedding-0.6B"
MAX_TOKENS: Final = 1024
PART_ROWS: Final = 2048
QUERY_PROMPT: Final = "query"
"""The prompt name Qwen3-Embedding's sentence-transformers config defines for queries."""

_BLOCK_ROWS: Final = 32_768

Matrix = npt.NDArray[np.float32]


class Embedder(Protocol):
    name: str
    dim: int

    def encode_documents(self, texts: Sequence[str]) -> Matrix: ...

    def encode_query(self, text: str) -> Matrix: ...


class SentenceTransformerEmbedder:
    """Qwen3-Embedding (or any sentence-transformers model) loaded on first use.

    Needs the ``embed`` extra: ``uv sync --extra embed``.
    """

    def __init__(self, name: str = DEFAULT_MODEL, *, device: str | None = None) -> None:
        self.name = name
        self.device = device
        self._model: Any = None
        self.dim = 0

    def _load(self) -> Any:
        if self._model is None:
            try:
                module = importlib.import_module("sentence_transformers")
            except ImportError as exc:  # pragma: no cover - depends on the environment
                raise RuntimeError(
                    "the dense arm needs the embed extra: uv sync --extra embed"
                ) from exc
            model = module.SentenceTransformer(self.name, device=self.device)
            model.max_seq_length = MAX_TOKENS
            self._model = model
            self.dim = int(model.get_sentence_embedding_dimension())
        return self._model

    def encode_documents(self, texts: Sequence[str]) -> Matrix:  # pragma: no cover - model
        model = self._load()
        out = model.encode(list(texts), batch_size=16, normalize_embeddings=True)
        return np.asarray(out, dtype=np.float32)

    def encode_query(self, text: str) -> Matrix:  # pragma: no cover - model
        model = self._load()
        out = model.encode([text], prompt_name=QUERY_PROMPT, normalize_embeddings=True)
        return np.asarray(out[0], dtype=np.float32)


def model_slug(name: str) -> str:
    """``Qwen/Qwen3-Embedding-0.6B`` -> ``qwen3-embedding-0.6b``: the directory name."""
    return name.rsplit("/", 1)[-1].lower()


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------------------------------------
# The cache and the batch job
# ---------------------------------------------------------------------------------------


def _parts(cache: Path) -> list[Path]:
    return sorted(p for p in cache.glob("part-*.keys"))


def cache_keys(cache: Path) -> dict[str, tuple[Path, int]]:
    """Every cached key, with the part file and row that hold its vector."""
    found: dict[str, tuple[Path, int]] = {}
    for keys in _parts(cache):
        vectors = keys.with_suffix(".npy")
        for row, key in enumerate(keys.read_text(encoding="ascii").split()):
            found.setdefault(key, (vectors, row))
    return found


def _unit_texts(corpus: Corpus) -> Iterable[tuple[str, str]]:
    for cite, text in corpus.conn.execute(
        "SELECT u.cite, u.text FROM units u JOIN versions v ON v.version_id = u.version_id "
        "ORDER BY u.doc_id, v.seq, u.seq"
    ):
        yield str(cite), str(text)


@dataclass
class EmbedReport:
    units: int
    cached_before: int
    embedded: int
    remaining: int
    stopped_early: bool
    parts_written: list[str] = field(default_factory=list[str])


def embed_units(
    corpus: Corpus,
    cache: Path,
    embedder: Embedder,
    *,
    stop: Callable[[], bool] = lambda: False,
    part_rows: int = PART_ROWS,
    log: Callable[[str], None] = lambda _: None,
) -> EmbedReport:
    """Embed every unit whose text is not in the cache yet, one part at a time.

    ``stop`` is checked before each part; when it returns True the job ends cleanly and the next
    run carries on from there. Texts are embedded shortest first within the job, which keeps
    batches evenly padded.
    """
    cache.mkdir(parents=True, exist_ok=True)
    have = cache_keys(cache)
    todo: dict[str, str] = {}
    units = 0
    for _, text in _unit_texts(corpus):
        units += 1
        key = text_key(text)
        if key not in have and key not in todo:
            todo[key] = text
    pending = sorted(todo.items(), key=lambda kv: (len(kv[1]), kv[0]))
    report = EmbedReport(units, len(have), 0, len(pending), stopped_early=False)
    number = len(_parts(cache))
    for start in range(0, len(pending), part_rows):
        if stop():
            report.stopped_early = True
            break
        chunk = pending[start : start + part_rows]
        vectors = embedder.encode_documents([text for _, text in chunk]).astype(np.float16)
        number += 1
        base = cache / f"part-{number:05d}"
        np.save(base.with_suffix(".npy"), vectors)
        temporary = base.with_suffix(".keys.tmp")
        temporary.write_text("\n".join(k for k, _ in chunk) + "\n", encoding="ascii")
        temporary.replace(base.with_suffix(".keys"))
        report.embedded += len(chunk)
        report.remaining -= len(chunk)
        report.parts_written.append(base.name)
        log(f"{base.name}: {report.embedded} embedded, {report.remaining} to go")
    return report


def night_window_stop(until_hour: int = 6) -> Callable[[], bool]:
    """A ``stop`` for :func:`embed_units` that ends the job at ``until_hour`` local time."""

    def stop() -> bool:
        return datetime.now().hour == until_hour

    return stop


# ---------------------------------------------------------------------------------------
# The snapshot's copy
# ---------------------------------------------------------------------------------------


def assemble_dense(
    corpus: Corpus, cache: Path, directory: Path, *, model: str, dim: int | None = None
) -> dict[str, Any]:
    """Write ``vectors.f16.npy`` and ``unit_ids.json`` for every unit, in the index's row order.

    Raises ``LookupError`` saying how many units have no vector, when the cache is incomplete.
    """
    have = cache_keys(cache)
    cites: list[str] = []
    places: list[tuple[Path, int]] = []
    missing = 0
    for cite, text in _unit_texts(corpus):
        place = have.get(text_key(text))
        if place is None:
            missing += 1
            continue
        cites.append(cite)
        places.append(place)
    if missing:
        raise LookupError(
            f"{missing} of {missing + len(cites)} units have no vector in {cache}; "
            "run the embed job (python -m safetypage.search embed) and build again"
        )
    loaded: dict[Path, npt.NDArray[np.float16]] = {}
    width = dim or (int(np.load(places[0][0], mmap_mode="r").shape[1]) if places else 0)
    matrix = np.zeros((len(cites), width), dtype=np.float16)
    for i, (path, row) in enumerate(places):
        if path not in loaded:
            loaded[path] = np.load(path, mmap_mode="r")
        matrix[i] = loaded[path][row]
    directory.mkdir(parents=True, exist_ok=True)
    np.save(directory / "vectors.f16.npy", matrix)
    (directory / "unit_ids.json").write_text(json.dumps(cites), encoding="utf-8")
    info = {
        "model": model,
        "dim": width,
        "units": len(cites),
        "normalized": True,
        "max_tokens": MAX_TOKENS,
        "query_prompt": QUERY_PROMPT,
    }
    (directory / "model.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return info


# ---------------------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------------------


class DenseIndex:
    """A snapshot's vectors for one model, memory-mapped, with the cite of each row."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.info: dict[str, Any] = json.loads((directory / "model.json").read_text("utf-8"))
        self.model: str = self.info["model"]
        self.vectors: npt.NDArray[np.float16] = np.load(
            directory / "vectors.f16.npy", mmap_mode="r"
        )
        self.cites: list[str] = json.loads((directory / "unit_ids.json").read_text("utf-8"))

    def scores(self, query: Matrix) -> Matrix:
        """Cosine similarity of every row to ``query``, in blocks so float16 rows are widened
        a block at a time rather than all at once."""
        q = query.astype(np.float32)
        out = np.empty(len(self.vectors), dtype=np.float32)
        for start in range(0, len(self.vectors), _BLOCK_ROWS):
            block = np.asarray(self.vectors[start : start + _BLOCK_ROWS], dtype=np.float32)
            out[start : start + len(block)] = block @ q
        return out

    def top(
        self, query: Matrix, mask: npt.NDArray[np.bool_] | None, k: int
    ) -> list[tuple[int, float]]:
        """The ``k`` best rows among those ``mask`` allows: ``(row, score)``, ties by cite."""
        scores = self.scores(query)
        if mask is not None:
            scores = np.where(mask, scores, -np.inf)
        allowed = int(np.isfinite(scores).sum())
        k = min(k, allowed)
        if k <= 0:
            return []
        # Take a margin past k so rows tied with the k-th are all considered, then sort exactly.
        margin = min(len(scores), k + 32)
        rows = np.argpartition(-scores, margin - 1)[:margin]
        ranked = sorted(
            ((int(r), float(scores[r])) for r in rows if np.isfinite(scores[r])),
            key=lambda rs: (-rs[1], self.cites[rs[0]]),
        )
        return ranked[:k]
