from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from safetypage.server.surfaces import SURFACES_DIR, SurfaceError, load_surface, load_surfaces


def test_shipped_surfaces() -> None:
    surfaces = load_surfaces()
    assert next(iter(surfaces)) == "default"
    assert set(surfaces) == {"default", "short", "no-verify", "one-tool"}
    assert surfaces["default"].tools == ("search", "fetch", "verify_quote", "check_answer")
    assert "verify_quote" not in surfaces["no-verify"].tools
    assert "verify_quote" not in surfaces["no-verify"].instructions
    assert surfaces["one-tool"].tools == ("search",) and surfaces["one-tool"].search_full_text
    assert len({s.surface_id for s in surfaces.values()}) == 4
    for s in surfaces.values():
        assert s.surface_id.startswith(f"{s.name}@") and len(s.surface_id) == len(s.name) + 7
        assert s.instructions and all(s.descriptions[t] for t in s.tools)


def test_surface_id_is_stable_and_tracks_descriptions(tmp_path: Path) -> None:
    copy = tmp_path / "surfaces"
    shutil.copytree(SURFACES_DIR, copy)
    before = load_surface("default", copy).surface_id
    assert before == load_surface("default", SURFACES_DIR).surface_id
    path = copy / "descriptions" / "search.long.md"
    path.write_text(path.read_text() + "\nOne more sentence.")
    assert load_surface("default", copy).surface_id != before


def test_adding_a_variant_is_adding_a_file(tmp_path: Path) -> None:
    copy = tmp_path / "surfaces"
    shutil.copytree(SURFACES_DIR, copy)
    (copy / "no-check.toml").write_text(
        'extends = "short"\ntools = ["search", "fetch", "verify_quote"]\n'
    )
    surface = load_surfaces(copy)["no-check"]
    assert surface.tools == ("search", "fetch", "verify_quote")
    assert surface.descriptions["search"] == load_surface("short", copy).descriptions["search"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('tools = ["search", "grep"]', "tools must be"),
        ("colour = 1", "unknown keys"),
        ('descriptions = "purple"', "no description file"),
        ('extends = "loop"', "extends itself"),
    ],
)
def test_bad_surfaces(tmp_path: Path, text: str, message: str) -> None:
    copy = tmp_path / "surfaces"
    shutil.copytree(SURFACES_DIR, copy)
    (copy / "loop.toml").write_text(text)
    with pytest.raises(SurfaceError, match=message):
        load_surface("loop", copy)
