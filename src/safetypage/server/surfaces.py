"""Surfaces: named tool configurations, one TOML file each, served at ``/x/<name>/mcp``.

A surface file says which tools are offered, which description files they use, which retrieval
arm and snapshot serve them, and how results are shaped. Adding a variant is adding a file::

    # surfaces/no-verify.toml
    extends = "default"
    tools = ["search", "fetch", "check_answer"]

Keys:

``extends``        another surface to start from (its keys, overridden by this file's)
``about``          one line on what the variant tests
``tools``          the tools offered, from ``search``, ``fetch``, ``verify_quote``, ``check_answer``
``descriptions``   the description style: ``descriptions/<tool>.<style>.md`` and
                   ``descriptions/instructions.<style>.md``
``description_files``  per-tool overrides, ``{search = "search.full-text"}``
``arm``            the retrieval arm (``bm25`` ...)
``snapshot``       ``current`` or a snapshot id
``search_full_text``  search returns the full text of open units with each hit

``surface_id`` is ``<name>@<first 6 hex of the SHA-256 of the resolved config and the text of
every description file it uses>``.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["SURFACES_DIR", "TOOLS", "Surface", "SurfaceError", "load_surface", "load_surfaces"]

SURFACES_DIR = Path(__file__).parent / "surfaces"
TOOLS = ("search", "fetch", "verify_quote", "check_answer")
_KEYS = {
    "extends",
    "about",
    "tools",
    "descriptions",
    "description_files",
    "arm",
    "snapshot",
    "search_full_text",
}


class SurfaceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Surface:
    name: str
    surface_id: str
    about: str
    tools: tuple[str, ...]
    descriptions: dict[str, str]
    """Tool name → description text."""
    instructions: str
    arm: str
    snapshot: str
    search_full_text: bool


def _raw(name: str, directory: Path, seen: tuple[str, ...] = ()) -> dict[str, Any]:
    if name in seen:
        raise SurfaceError(f"surface {name!r} extends itself: {' -> '.join((*seen, name))}")
    path = directory / f"{name}.toml"
    if not path.is_file():
        raise SurfaceError(f"no surface {name!r} ({path})")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    unknown = set(data) - _KEYS
    if unknown:
        raise SurfaceError(f"{path.name}: unknown keys {sorted(unknown)}")
    parent = data.pop("extends", None)
    if parent is None:
        return data
    base = _raw(str(parent), directory, (*seen, name))
    files = {**base.get("description_files", {}), **data.get("description_files", {})}
    merged = {**base, **data}
    if files:
        merged["description_files"] = files
    if "about" not in data:
        merged.pop("about", None)
    return merged


def load_surface(name: str, directory: Path = SURFACES_DIR) -> Surface:
    data = _raw(name, directory)
    tools = tuple(data.get("tools", TOOLS))
    bad = [t for t in tools if t not in TOOLS]
    if bad or not tools:
        raise SurfaceError(f"surface {name!r}: tools must be some of {TOOLS}, got {list(tools)}")
    style = str(data.get("descriptions", "long"))
    files: dict[str, str] = {t: f"{t}.{style}" for t in tools}
    files["instructions"] = f"instructions.{style}"
    files.update({k: str(v) for k, v in data.get("description_files", {}).items()})
    texts: dict[str, str] = {}
    for key, stem in files.items():
        if key != "instructions" and key not in tools:
            continue
        path = directory / "descriptions" / f"{stem}.md"
        if not path.is_file():
            raise SurfaceError(f"surface {name!r}: no description file {path}")
        texts[key] = path.read_text(encoding="utf-8").strip()
    arm = str(data.get("arm", "bm25"))
    snapshot = str(data.get("snapshot", "current"))
    full_text = bool(data.get("search_full_text", False))
    resolved = {
        "tools": list(tools),
        "arm": arm,
        "snapshot": snapshot,
        "search_full_text": full_text,
        "texts": texts,
    }
    digest = hashlib.sha256(json.dumps(resolved, sort_keys=True).encode()).hexdigest()[:6]
    return Surface(
        name=name,
        surface_id=f"{name}@{digest}",
        about=str(data.get("about", "")),
        tools=tools,
        descriptions={t: texts[t] for t in tools},
        instructions=texts["instructions"],
        arm=arm,
        snapshot=snapshot,
        search_full_text=full_text,
    )


def load_surfaces(directory: Path = SURFACES_DIR) -> dict[str, Surface]:
    """Every surface in the directory, ``default`` first."""
    names = sorted(p.stem for p in directory.glob("*.toml"))
    if "default" not in names:
        raise SurfaceError(f"no default surface in {directory}")
    names.remove("default")
    return {name: load_surface(name, directory) for name in ["default", *names]}
