from __future__ import annotations

import json
from pathlib import Path

import pytest

from safetypage.search.__main__ import main


def test_query_and_latency(search_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = ["--root", str(search_root), "query", "--snapshot", "2026.11.0"]
    assert main([*args, '"is not the only tool"']) == 0
    out = capsys.readouterr().out
    assert "arxiv:2305.15324/v2/p6" in out and "[is not the only tool]" in out
    assert main([*args, "risk", "--mode", "documents", "--org", "nist"]) == 0
    assert "nist:ai-100-1/r1" in capsys.readouterr().out
    assert main([*args, "risk", "--json", "--limit", "1"]) == 0
    assert len(json.loads(capsys.readouterr().out)["hits"]) == 1
    assert main([*args, "a OR b"]) == 1
    assert "OR is not an operator" in capsys.readouterr().err
    latency = ["--root", str(search_root), "latency", "--snapshot", "2026.11.0", "--runs", "1"]
    assert main(latency) == 0
    assert "median ms" in capsys.readouterr().out


def test_embed_waits_for_night(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from safetypage.search import __main__ as cli  # noqa: PLC0415

    class Noon:
        @staticmethod
        def now() -> object:
            class T:
                hour = 12

            return T()

    monkeypatch.setattr(cli, "datetime", Noon)
    assert main(["--root", str(tmp_path), "embed"]) == 2
