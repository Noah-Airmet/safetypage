from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from onthepage import schemas
from onthepage.api import Hit, SearchBackend, SearchRequest, SearchResponse
from onthepage.licence import Tier
from onthepage.quote import Verdict

REPO = Path(__file__).parent.parent


def test_checked_in_schemas_are_current() -> None:
    assert schemas.stale(REPO / "schemas") == [], "run: uv run python -m onthepage.schemas"


def test_schemas_use_the_one_vocabulary() -> None:
    rendered = {name: json.loads(text) for name, text in schemas.render().items()}
    quote_check = rendered["quote-check.schema.json"]
    assert quote_check["$defs"]["Verdict"]["enum"] == [v.value for v in Verdict]
    assert quote_check["$defs"]["Tier"]["enum"] == [t.value for t in Tier] == ["open", "link_only"]
    trace = rendered["trace.schema.json"]
    kinds = {
        variant["properties"]["kind"]["const"]
        for variant in (
            trace["$defs"][n]
            for n in ("ThinkEvent", "ToolEvent", "AnswerEvent", "CiteEvent", "VerifyEvent")
        )
    }
    assert kinds == {"think", "tool", "answer", "cite", "verify"}
    assert trace["properties"]["schema"]["const"] == "onthepage.trace/1"


def test_write_and_stale(tmp_path: Path) -> None:
    written = schemas.write(tmp_path)
    assert len(written) == len(schemas.MODELS)
    assert schemas.stale(tmp_path) == []
    (tmp_path / "trace.schema.json").write_text("{}")
    (tmp_path / "orphan.schema.json").write_text("{}")
    written[0].unlink()
    assert schemas.stale(tmp_path) == sorted(
        ["trace.schema.json", "orphan.schema.json", written[0].name]
    )
    assert schemas.stale(tmp_path / "missing") == sorted(schemas.render())


def test_search_request_limits() -> None:
    assert SearchRequest().model_dump()["arm"] == "bm25"
    assert SearchRequest(query="sandbagging", limit=25, mode="documents").limit == 25
    for bad in ({"limit": 0}, {"limit": 26}, {"arm": "magic"}, {"kind": "tweet"}, {"unknown": 1}):
        with pytest.raises(ValueError, match="validation error"):
            SearchRequest.model_validate(bad)


def test_a_backend_can_satisfy_the_search_protocol() -> None:
    class Fake:
        snapshot = "2026.11.0"
        arms = ("bm25",)

        def search(self, request: SearchRequest) -> SearchResponse:
            hit = Hit(
                id="arxiv:2305.15324/v2/p6",
                title="Model evaluation for extreme risks — p. 6",
                url="https://onthepage.test/d/arxiv/2305.15324/v2/p6",
                cite="arxiv:2305.15324/v2/p6",
                doc_id="arxiv:2305.15324",
                version="v2",
                anchor="p6",
                anchor_label="p. 6",
                doc_title="Model evaluation for extreme risks",
                org=None,
                kind="paper",
                date="2023-05-24",
                tier=Tier.OPEN,
                licence="CC-BY-4.0",
                score=1.0,
                snippet="…one of the main tools…",
                match_spans=[(1, 4)],
                source_url="https://arxiv.org/pdf/2305.15324v2#page=6",
            )
            return SearchResponse(
                query=request.query,
                interpretation="all of: tools",
                arm=request.arm,
                snapshot=self.snapshot,
                mode=request.mode,
                total=1,
                hits=[hit],
            )

    backend: SearchBackend = Fake()
    response = backend.search(SearchRequest(query="tools"))
    assert response.hits[0].id == response.hits[0].cite
    assert (response.arm, response.snapshot) == ("bm25", "2026.11.0")


def test_the_module_runs_as_a_check() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "onthepage.schemas", "--check"],
        cwd=REPO,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
