"""Build what the site needs from the fixture corpus, until real snapshots and runs exist.

    uv run --group fixtures --group build python site/scripts/make_data.py

Writes two things:

1. `site/public/data/`, in the layout of a snapshot's `public/` (docs/ARCHITECTURE.md
   section 7): document cards, unit text with layout, page images at 800 and 1600 px.
   Not committed. A real snapshot's `public/` replaces it.
2. `site/src/content/`: the landing page's two example checks, one scripted sample trace,
   and a sample leaderboard with its run. Committed, and labelled as samples wherever the
   site shows them. Every verdict in them comes from the core library's `verify_quote`.
"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image
from standin import FIXTURES, SNAPSHOT, add_missing_words, library, search

from onthepage.ids import parse_citation
from onthepage.quote import Verdict
from onthepage.snapshot import public_doc_path, public_page_image_path, public_text_path
from onthepage.ids import DocId
from onthepage.trace import Trace, citation_state

SITE = Path(__file__).resolve().parents[1]
DATA = SITE / "public" / "data"
CONTENT = SITE / "src" / "content"
WIDTHS = (800, 1600)


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def under_data(path: Any) -> Path:
    return DATA / Path(*Path(str(path)).parts[1:])  # drop the leading "public/"


def public_tree(corpus: Any) -> None:
    if DATA.exists():
        shutil.rmtree(DATA)
    sources = json.loads((FIXTURES / "sources.json").read_text())["versions"]
    pdfs = {
        f"{e['document']['doc_id']}/{e['version']['label']}": FIXTURES / "sources" / e["files"]["pdf"]["name"]
        for e in sources
        if e.get("files", {}).get("pdf")
    }
    for doc_id in corpus.doc_ids():
        card = corpus.document_card(doc_id)
        dump(under_data(public_doc_path(DocId.parse(doc_id))), card.model_dump(mode="json"))
        for version in corpus.versions(doc_id):
            if version.tier != "open":
                continue
            ref = f"{doc_id}/{version.label}"
            units = corpus.conn.execute(
                "SELECT cite FROM units WHERE doc_id = ? AND version = ? ORDER BY seq",
                (doc_id, version.label),
            ).fetchall()
            for (cite,) in units:
                unit = corpus.read_units(cite, layout=True)[0]
                dump(under_data(public_text_path(parse_citation(cite))), unit.model_dump(mode="json"))
            if ref in pdfs:
                with pymupdf.open(pdfs[ref]) as pdf:
                    for number, page in enumerate(pdf, 1):
                        cite = parse_citation(f"{ref}/p{number}")
                        pix = page.get_pixmap(matrix=pymupdf.Matrix(1600 / page.rect.width, 1600 / page.rect.width), alpha=False)
                        full = Image.open(io.BytesIO(pix.tobytes("png")))
                        for width in WIDTHS:
                            out = under_data(public_page_image_path(cite, width))
                            out.parent.mkdir(parents=True, exist_ok=True)
                            image = full if width == full.width else full.resize((width, round(full.height * width / full.width)), Image.LANCZOS)
                            image.save(out, "WEBP", quality=72, method=6)
        print("public:", doc_id)


# ------------------------------------------------------------------ samples

PAPER = "arxiv:2305.15324/v2"
NIST = "nist:ai-100-1/r1"


def landing(corpus: Any) -> None:
    good = corpus.verify_quote("not the only tool available for AI risk assessment", f"{PAPER}/p6")
    bad = corpus.verify_quote("Model evaluation is the only tool available for AI risk assessment", f"{PAPER}/p6")
    assert good.verdict == Verdict.EXACT and bad.verdict == Verdict.NEAR_MISS
    dump(
        CONTENT / "landing.json",
        {
            "doc": corpus.document_card("arxiv:2305.15324").model_dump(mode="json"),
            "verified": good.model_dump(mode="json"),
            "rejected": bad.model_dump(mode="json"),
        },
    )


def sample_trace(corpus: Any) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    clock = 0
    calls = 0

    def add(gap_ms: int, **event: Any) -> None:
        nonlocal clock
        clock += gap_ms
        events.append({"seq": len(events), "t_ms": clock, **event})

    def tool_search(gap_ms: int, query: str) -> None:
        nonlocal calls
        calls += 1
        result = search(corpus, query, limit=6)
        returned = [{"cite": h["cite"], "score": h["score"]} for h in result["hits"]]
        seen.update(r["cite"] for r in returned)
        add(gap_ms, kind="tool", call_id=f"call_{calls}", tool="search", args={"query": query}, returned=returned, total=result["total"], latency_ms=40)

    def tool_fetch(gap_ms: int, cite: str) -> None:
        nonlocal calls
        calls += 1
        seen.add(cite)
        add(gap_ms, kind="tool", call_id=f"call_{calls}", tool="fetch", args={"id": cite}, returned=[{"cite": cite}], latency_ms=25)

    citations: list[dict[str, Any]] = []
    answer_text = ""

    def say(gap_ms: int, text: str) -> None:
        nonlocal answer_text
        answer_text += text
        add(gap_ms, kind="answer", delta=text)

    def cite(gap_ms: int, target: str, quote: str | None) -> None:
        cite_id = f"c{len(citations) + 1}"
        add(gap_ms, kind="cite", cite_id=cite_id, cite=target, quote=quote)
        verdict = span = closest = None
        if quote:
            check = corpus.verify_quote(quote, target)
            verdict = check.verdict
            if check.locations:
                where = check.locations[0]
                span = [where.spine_start, where.spine_end]
                if not check.passed:
                    closest = where.cite
        state, reason = citation_state(resolves=True, seen=target in seen, quote_verdict=verdict)
        add(350, kind="verify", cite_id=cite_id, state=state, reason=reason, resolves=True, seen=target in seen, quote_verdict=verdict, span=span, closest=closest)
        citations.append({"cite_id": cite_id, "cite": target, "quote": quote, "state": state, "reason": reason})

    add(0, kind="think", text="Start with the paper that argues for evaluations and see what it claims for them. Then look for the limits it admits, and whether NIST treats risk measurement as settled.")
    tool_search(1400, '"model evaluation" "risk assessment"')
    tool_fetch(2100, f"{PAPER}/p3")
    tool_fetch(1500, f"{PAPER}/p6")
    add(1800, kind="think", text="Page 6 says evaluation is one tool among several. The paper has a limitations section; read it.")
    tool_search(1200, "overtrust evaluation")
    tool_fetch(1700, f"{PAPER}/p13")
    tool_search(2200, '"risk measurement"')
    tool_fetch(1600, f"{NIST}/p10")
    add(2400, kind="think", text="Enough to answer. Quote the pages directly.")

    say(1500, "No. The paper that makes the case for evaluations says model evaluation is ")
    say(300, "“not the only tool available for AI risk assessment” ")
    cite(200, f"{PAPER}/p6", "not the only tool available for AI risk assessment")
    say(900, ", though it is “one of the main tools we have for AI risk assessment” ")
    cite(200, f"{PAPER}/p3", "one of the main tools we have for AI risk assessment")
    say(900, ". Its limitations section goes further and calls evaluation “a necessary and sufficient strategy for identifying and mitigating extreme risks” ")
    cite(200, f"{PAPER}/p13", "a necessary and sufficient strategy for identifying and mitigating extreme risks")
    say(1100, ".\n\nNIST's AI Risk Management Framework agrees that measurement is hard: risks that are not well understood are “difficult to measure quantitatively or qualitatively” ")
    cite(200, f"{NIST}/p10", "difficult to measure quantitatively or qualitatively")
    say(900, ", and it lists the lack of reliable metrics among the open challenges ")
    cite(200, f"{NIST}/p11", None)
    say(500, ".")

    trace = {
        "schema": "onthepage.trace/1",
        "header": {
            "trace_id": "sample-evals",
            "run_id": "sample-run",
            "sample_id": "sample-1",
            "question": "Is model evaluation enough on its own to assess extreme risks from AI?",
            "model": "scripted sample (no model)",
            "solver": "hand-written",
            "surface_id": "standin",
            "snapshot": SNAPSHOT,
            "arm": "standin-keyword",
            "server_version": "0.0.0",
            "started_at": "2026-11-10T00:00:00Z",
            "usage": {},
        },
        "events": events,
        "answer": {"text": answer_text, "citations": citations},
        "scores": {},
    }
    Trace.model_validate(trace)  # the contract
    states = [c["state"] for c in citations]
    assert states == ["verified", "rejected", "rejected", "verified", "cited"], states
    return trace


def leaderboard() -> tuple[dict[str, Any], dict[str, Any]]:
    def score(value: float, half: float) -> dict[str, Any]:
        return {"value": value, "ci": [round(value - half, 3), round(value + half, 3)], "n": 1}

    rows = [
        ("Sample agent A", "sample-run", [1, 2], 0.71, 0.93, 0.98, 0.21),
        ("Sample agent B", "sample-run", [1, 2], 0.69, 0.91, 0.96, 0.18),
        ("Sample agent C", "sample-run", [3, 3], 0.48, 0.72, 0.81, 0.02),
    ]
    board = {
        "schema": "onthepage.leaderboard/1",
        "sample": True,
        "benchmark": "PageCite",
        "version": "sample",
        "questions": 1,
        "updated": "2026-11-10",
        "snapshot": SNAPSHOT,
        "harness": "none (sample file)",
        "judge": None,
        "metrics": [
            {"key": "answer_correct", "label": "Answer correct", "source": "judge", "better": "higher", "unit": "%"},
            {"key": "page_hit", "label": "Page precision", "source": "deterministic", "better": "higher", "unit": "%"},
            {"key": "quote_fidelity", "label": "Quote fidelity", "source": "deterministic", "better": "higher", "unit": "%"},
        ],
        "rows": [
            {
                "model": model,
                "solver": "sample",
                "run_id": run,
                "rank_band": band,
                "scores": {"answer_correct": score(a, 0.04), "page_hit": score(p, 0.02), "quote_fidelity": score(q, 0.015)},
                "cost_per_correct_usd": cost,
            }
            for model, run, band, a, p, q, cost in rows
        ],
    }
    run = {
        "schema": "onthepage.run/1",
        "sample": True,
        "run_id": "sample-run",
        "model": "scripted sample (no model)",
        "solver": "hand-written",
        "snapshot": SNAPSHOT,
        "started_at": "2026-11-10T00:00:00Z",
        "samples": [
            {
                "sample_id": "sample-1",
                "trace_id": "sample-evals",
                "question": "Is model evaluation enough on its own to assess extreme risks from AI?",
                "tally": {"verified": 2, "cited": 1, "rejected": 2},
            }
        ],
    }
    return board, run


def main() -> None:
    corpus = library()
    add_missing_words(corpus)
    public_tree(corpus)
    landing(corpus)
    trace = sample_trace(corpus)
    dump(CONTENT / "traces" / "sample-evals.json", trace)
    board, run = leaderboard()
    dump(CONTENT / "leaderboard.json", board)
    dump(CONTENT / "runs" / "sample-run.json", run)
    print("samples written")


if __name__ == "__main__":
    main()
