"""The trace: one question, everything the agent did, and how each citation checked out.

One format, read by two consumers. The benchmark writes a trace per sample (derived from the
Inspect log, which stays the canonical benchmark record) and scores from it; the replay view
plays it back. State at time *t* is a pure function of ``events[:t]``, so scrubbing is free.

Five kinds of event:

``think``   reasoning text, when the model exposes it
``tool``    one tool call and its result: which units came back, in order
``answer``  a piece of the answer text, as it streamed
``cite``    a citation appearing in the answer
``verify``  the scorer's finding on one citation: verified, cited, or rejected, and why

A trace is self-describing: ``header`` pins the model, the tool surface, the retrieval arm and the
corpus snapshot, which is enough to rerun it.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from safetypage.quote import Verdict

__all__ = [
    "SCHEMA",
    "Answer",
    "AnswerCitation",
    "AnswerEvent",
    "CitationState",
    "CiteEvent",
    "Judgement",
    "RejectReason",
    "ThinkEvent",
    "ToolEvent",
    "ToolReturn",
    "Trace",
    "TraceEvent",
    "TraceHeader",
    "Usage",
    "VerifyEvent",
    "citation_state",
]

SCHEMA = "safetypage.trace/1"

CitationState = Literal["verified", "cited", "rejected"]
"""``verified``: the quote is at the cited anchor (``exact`` or ``normalized``).
``cited``: a real anchor the run saw, with no quote to check.
``rejected``: anything else. Rejected citations are shown struck through, never hidden."""

RejectReason = Literal[
    "unresolved",  # no such document, version or anchor
    "unseen",  # the anchor exists, but no tool returned it during this run
    "quote_elsewhere",
    "quote_near_miss",
    "quote_not_found",
    "unsupported",  # a judge said the cited text does not support the claim
]


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=0)
    """Position in the trace, from 0, without gaps."""
    t_ms: int = Field(ge=0)
    """Milliseconds since the run started."""


class ThinkEvent(_Event):
    kind: Literal["think"] = "think"
    text: str


class ToolReturn(BaseModel):
    """One unit a tool returned. ``cite`` is what the replay lights up and what makes a later
    citation of it count as *seen*."""

    model_config = ConfigDict(extra="forbid")

    cite: str
    score: float | None = None


class ToolEvent(_Event):
    kind: Literal["tool"] = "tool"
    call_id: str
    tool: str
    """``search``, ``fetch``, ``verify_quote``, ``check_answer``, or a variant surface's tool."""
    args: dict[str, Any]
    returned: list[ToolReturn] = Field(default_factory=list[ToolReturn])
    """Units in the result, in the order the agent saw them."""
    total: int | None = None
    """search: how many hits there were in all."""
    verdict: Verdict | None = None
    """verify_quote: the verdict."""
    found_at: str | None = None
    """verify_quote: the cite string of where the quote really is."""
    result_tokens: int | None = None
    latency_ms: int | None = None
    error: str | None = None
    request_id: str | None = None
    """The server's id for this call; joins the trace to the server's own call log."""


class AnswerEvent(_Event):
    kind: Literal["answer"] = "answer"
    delta: str


class CiteEvent(_Event):
    kind: Literal["cite"] = "cite"
    cite_id: str
    """Stable within the trace: ``c1``, ``c2``..."""
    cite: str
    quote: str | None = None


class Judgement(BaseModel):
    """A model's verdict on support. Always labelled as a judge's, never mixed with code checks."""

    model_config = ConfigDict(extra="forbid")

    judge: str
    """Judge id: model and prompt hash, e.g. ``judge@v2``."""
    label: Literal["supported", "partially_supported", "unsupported"]
    agreement: float | None = None
    """This judge's measured agreement with human labels, when known."""


class VerifyEvent(_Event):
    kind: Literal["verify"] = "verify"
    cite_id: str
    state: CitationState
    reason: RejectReason | None = None
    resolves: bool
    seen: bool
    quote_verdict: Verdict | None = None
    span: tuple[int, int] | None = None
    """Where the quote matched, as spine offsets, for the highlight."""
    closest: str | None = None
    """For a failed quote: the cite string of the nearest wording, or of where it really is."""
    judgement: Judgement | None = None


TraceEvent = Annotated[
    ThinkEvent | ToolEvent | AnswerEvent | CiteEvent | VerifyEvent, Field(discriminator="kind")
]


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float | None = None
    price_table: str | None = None
    """Which frozen price table ``cost_usd`` was computed from."""


class TraceHeader(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    run_id: str | None = None
    sample_id: str | None = None
    question: str
    model: str
    solver: str | None = None
    surface_id: str
    snapshot: str
    arm: str
    server_version: str
    started_at: str
    usage: Usage = Field(default_factory=Usage)


class AnswerCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cite_id: str
    cite: str
    quote: str | None = None
    state: CitationState
    reason: RejectReason | None = None
    gold: bool | None = None
    """Benchmark runs: whether this anchor is a gold anchor for the question."""


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    citations: list[AnswerCitation] = Field(default_factory=list[AnswerCitation])


class Trace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_: Literal["safetypage.trace/1"] = Field(default=SCHEMA, alias="schema")
    header: TraceHeader
    events: list[TraceEvent]
    answer: Answer | None = None
    scores: dict[str, float] = Field(default_factory=dict[str, float])

    def seen(self) -> set[str]:
        """Every cite string a tool returned during the run."""
        return {r.cite for e in self.events if isinstance(e, ToolEvent) for r in e.returned}


def citation_state(
    *,
    resolves: bool,
    seen: bool,
    quote_verdict: Verdict | None,
    judgement: Judgement | None = None,
) -> tuple[CitationState, RejectReason | None]:
    """The one rule that turns checks into the state a citation is shown in.

    Order matters: a citation that does not resolve is rejected for that reason, whatever else
    is true of it.
    """
    if not resolves:
        return "rejected", "unresolved"
    if not seen:
        return "rejected", "unseen"
    if quote_verdict is Verdict.ELSEWHERE:
        return "rejected", "quote_elsewhere"
    if quote_verdict is Verdict.NEAR_MISS:
        return "rejected", "quote_near_miss"
    if quote_verdict is Verdict.NOT_FOUND:
        return "rejected", "quote_not_found"
    if judgement is not None and judgement.label == "unsupported":
        return "rejected", "unsupported"
    if quote_verdict is None:
        return "cited", None
    return "verified", None
