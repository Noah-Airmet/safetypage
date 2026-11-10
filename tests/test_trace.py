from __future__ import annotations

import json
import sqlite3

import pytest
from pydantic import ValidationError

from safetypage.migrate import migrate
from safetypage.quote import Verdict
from safetypage.trace import (
    AnswerEvent,
    CiteEvent,
    Judgement,
    ToolEvent,
    ToolReturn,
    Trace,
    TraceHeader,
    VerifyEvent,
    citation_state,
)

HEADER = TraceHeader(
    trace_id="t_01",
    run_id="r_01",
    sample_id="pc-0412",
    question="How are evaluations used?",
    model="claude-opus-5-5",
    solver="react-baseline@1",
    surface_id="default@a1f3c9",
    snapshot="2026.11.0",
    arm="bm25",
    server_version="0.1.0",
    started_at="2026-11-10T03:00:00Z",
)
P6 = "arxiv:2305.15324/v2/p6"


def example() -> Trace:
    return Trace(
        header=HEADER,
        events=[
            ToolEvent(
                seq=0,
                t_ms=0,
                call_id="call_1",
                tool="search",
                args={"query": '"risk assessment"'},
                returned=[ToolReturn(cite=P6, score=12.1), ToolReturn(cite="nist:ai-100-1/r1/p9")],
                total=41,
                result_tokens=1240,
                latency_ms=38,
            ),
            ToolEvent(
                seq=1,
                t_ms=4100,
                call_id="call_2",
                tool="fetch",
                args={"id": P6},
                returned=[ToolReturn(cite=P6)],
            ),
            AnswerEvent(seq=2, t_ms=9000, delta="Model evaluation is one of the main tools"),
            CiteEvent(seq=3, t_ms=9400, cite_id="c1", cite=P6, quote="one of the main tools"),
            VerifyEvent(
                seq=4,
                t_ms=9900,
                cite_id="c1",
                state="verified",
                resolves=True,
                seen=True,
                quote_verdict=Verdict.EXACT,
                span=(1203, 1224),
            ),
        ],
        scores={"page_hit": 1.0},
    )


def test_round_trip_through_json() -> None:
    trace = example()
    data = json.loads(trace.model_dump_json(by_alias=True))
    assert data["schema"] == "safetypage.trace/1"
    assert [e["kind"] for e in data["events"]] == ["tool", "tool", "answer", "cite", "verify"]
    assert data["events"][4]["quote_verdict"] == "exact"
    assert Trace.model_validate(data) == trace
    assert trace.seen() == {P6, "nist:ai-100-1/r1/p9"}


def test_unknown_event_kinds_and_fields_are_rejected() -> None:
    data = json.loads(example().model_dump_json(by_alias=True))
    data["events"][0]["kind"] = "browse"
    with pytest.raises(ValidationError):
        Trace.model_validate(data)
    data = json.loads(example().model_dump_json(by_alias=True))
    data["events"][2]["surprise"] = 1
    with pytest.raises(ValidationError):
        Trace.model_validate(data)
    with pytest.raises(ValidationError):
        VerifyEvent(seq=0, t_ms=0, cite_id="c1", state="approved", resolves=True, seen=True)  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize(
    ("resolves", "seen", "verdict", "label", "expected"),
    [
        (True, True, Verdict.EXACT, None, ("verified", None)),
        (True, True, Verdict.NORMALIZED, "supported", ("verified", None)),
        (True, True, None, None, ("cited", None)),
        (False, True, Verdict.EXACT, None, ("rejected", "unresolved")),
        (True, False, Verdict.EXACT, None, ("rejected", "unseen")),
        (True, True, Verdict.ELSEWHERE, None, ("rejected", "quote_elsewhere")),
        (True, True, Verdict.NEAR_MISS, None, ("rejected", "quote_near_miss")),
        (True, True, Verdict.NOT_FOUND, None, ("rejected", "quote_not_found")),
        (True, True, Verdict.EXACT, "unsupported", ("rejected", "unsupported")),
        (True, True, None, "unsupported", ("rejected", "unsupported")),
        (False, False, Verdict.NOT_FOUND, "unsupported", ("rejected", "unresolved")),
    ],
)
def test_citation_state(
    resolves: bool,
    seen: bool,
    verdict: Verdict | None,
    label: str | None,
    expected: tuple[str, str | None],
) -> None:
    judgement = None if label is None else Judgement(judge="judge@v1", label=label)  # pyright: ignore[reportArgumentType]
    assert (
        citation_state(resolves=resolves, seen=seen, quote_verdict=verdict, judgement=judgement)
        == expected
    )


def test_a_near_miss_is_never_verified() -> None:
    for verdict in Verdict:
        state, _ = citation_state(resolves=True, seen=True, quote_verdict=verdict)
        assert (state == "verified") is (verdict in {Verdict.EXACT, Verdict.NORMALIZED})


def test_traces_store_in_the_ops_database() -> None:
    conn = sqlite3.connect(":memory:")
    migrate(conn, "ops")
    trace = example()
    h = trace.header
    conn.execute(
        "INSERT INTO traces (trace_id, sample_id, question, model, surface_id, snapshot, started_at, header) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            h.trace_id,
            h.sample_id,
            h.question,
            h.model,
            h.surface_id,
            h.snapshot,
            h.started_at,
            h.model_dump_json(),
        ),
    )
    conn.executemany(
        "INSERT INTO trace_events (trace_id, seq, t_ms, kind, event) VALUES (?,?,?,?,?)",
        [(h.trace_id, e.seq, e.t_ms, e.kind, e.model_dump_json()) for e in trace.events],
    )
    rows = conn.execute(
        "SELECT event FROM trace_events WHERE trace_id = ? ORDER BY seq", (h.trace_id,)
    )
    rebuilt = Trace.model_validate(
        {
            "header": json.loads(h.model_dump_json()),
            "events": [json.loads(r[0]) for r in rows],
            "scores": trace.scores,
        }
    )
    conn.close()
    assert rebuilt == trace
