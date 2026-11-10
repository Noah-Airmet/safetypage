"""The PageCite task on Inspect: an agent with the library's tools, scored on its citations.

    inspect eval src/onthepage/bench/task.py@pagecite -T server=http://localhost:8000 \\
        -T surface=default --model anthropic/claude-sonnet-5-5

or, with a run configuration that also writes the results file and the traces:

    uv run --group bench python -m onthepage.bench run pagecite/configs/smoke.toml

The agent reaches the library through the MCP server (``<server>/mcp`` for the default surface,
``<server>/x/<surface>/mcp`` for a variant), so what is measured is the surface people connect
to. Scoring reads the same snapshot locally (``corpus``), with the same ``verify_quote``.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import Any

from inspect_ai import Task, task
from inspect_ai.agent import react
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessage, ChatMessageAssistant, ChatMessageTool
from inspect_ai.scorer import (
    Metric,
    SampleScore,
    Score,
    Scorer,
    Target,
    metric,
    scorer,
)
from inspect_ai.solver import TaskState
from inspect_ai.tool import Tool, ToolSource, mcp_server_http

from onthepage.bundle import load_bundles
from onthepage.corpus import Corpus

from .judge import make_judge
from .questions import Question, load_questions
from .score import MEASURES, grade, tool_event

__all__ = ["SOLVER", "open_corpus", "pagecite", "pagecite_scorer", "surface_url"]

REPO = Path(__file__).resolve().parents[3]
SOLVER = "react-baseline@1"

INSTRUCTIONS = """\
You answer questions about the AI safety record (research papers, system cards, safety
frameworks, evaluation reports, government guidance) using the On the Page library tools.

- Cite every claim you take from the library with the cite string of the page or paragraph it
  is on, exactly as the tools give it, for example arxiv:2305.15324/v2/p6.
- Cite only pages and paragraphs the tools have shown you.
- When you quote, put the source's exact words in double quotation marks, followed by the
  citation of the page they are on. Double quotation marks mean a quotation and are checked
  word for word against the page cited after them: write titles in italics, not in quotation
  marks.
- When asked to check a claim, start your answer with one line, either
  "Verdict: supported" or "Verdict: not supported", then explain, citing the page(s) that show
  what the source says.
- When you are done, call submit() with your complete answer.
"""


def surface_url(server: str, surface: str) -> str:
    server = server.rstrip("/")
    return f"{server}/mcp" if surface == "default" else f"{server}/x/{surface}/mcp"


@cache
def open_corpus(corpus: str) -> Corpus:
    """``fixtures`` (the checked-in fixture corpus), a snapshot directory, or a corpus.sqlite."""
    if corpus == "fixtures":
        c = Corpus.memory()
        load_bundles(c, REPO / "fixtures/corpus/bundles")
        return c
    path = Path(corpus)
    if path.is_dir():
        path = path / "corpus.sqlite"
    return Corpus.open(path, readonly=True)


def _sample(q: Question) -> Sample:
    return Sample(id=q.id, input=q.question, metadata={"question": q.model_dump(mode="json")})


def seen_and_events(messages: Sequence[ChatMessage]) -> tuple[set[str], list[Any]]:
    """Every unit a tool returned, and the tool calls as trace events (untimed)."""
    calls: dict[str, tuple[str, dict[str, Any]]] = {}
    events: list[Any] = []
    for message in messages:
        if isinstance(message, ChatMessageAssistant):
            for call in message.tool_calls or []:
                calls[call.id] = (call.function, dict(call.arguments))
        elif isinstance(message, ChatMessageTool):
            name, args = calls.get(message.tool_call_id or "", (message.function or "?", {}))
            if name == "submit":
                continue
            events.append(
                tool_event(
                    seq=len(events),
                    call_id=message.tool_call_id or f"call{len(events)}",
                    tool=name,
                    args=args,
                    result=message.text,
                    error=message.error.message if message.error else None,
                )
            )
    seen = {r.cite for e in events for r in e.returned}
    return seen, events


@metric
def defined_mean() -> Metric:
    """Mean over the samples where a measure is defined (it is ``None`` elsewhere)."""

    def compute(scores: list[SampleScore]) -> float:
        values = [s.score.value for s in scores if isinstance(s.score.value, int | float)]
        return sum(values) / len(values) if values else float("nan")

    return compute


@scorer(metrics={m: [defined_mean()] for m in MEASURES})
def pagecite_scorer(corpus: str = "fixtures", judge: str | None = None) -> Scorer:
    run_judge = make_judge(judge) if judge else None

    async def score(state: TaskState, target: Target) -> Score:  # noqa: ARG001
        question = Question.model_validate(state.metadata["question"])
        answer = state.output.completion if state.output else ""
        seen, _ = seen_and_events(state.messages)
        graded = await grade(question, answer, seen, open_corpus(corpus), judge=run_judge)
        return Score(
            value=dict(graded.scores),  # type: ignore[arg-type]
            answer=answer,
            metadata={
                "citations": [c.model_dump(mode="json") for c in graded.citations],
                "verify": [v.model_dump(mode="json") for v in graded.verify],
                "judge": run_judge and judge,
            },
        )

    return score


@task
def pagecite(  # noqa: PLR0917  (task arguments are given by name from the CLI)
    questions: str = "pagecite/questions/dev.jsonl",
    corpus: str = "fixtures",
    server: str = "http://localhost:8000",
    surface: str = "default",
    judge: str | None = None,
    message_limit: int = 40,
    tools: Sequence[Tool | ToolSource] | None = None,
) -> Task:
    """PageCite. ``tools`` replaces the MCP server (tests use it); everything else is a string
    so the task runs from the command line."""
    path = Path(questions)
    if not path.is_absolute():
        path = REPO / path
    dataset = MemoryDataset([_sample(q) for q in load_questions(path)], name=path.stem)
    if tools is None:
        tools = [mcp_server_http(name="onthepage", url=surface_url(server, surface), timeout=30)]
    return Task(
        dataset=dataset,
        solver=react(prompt=INSTRUCTIONS, tools=list(tools)),
        scorer=pagecite_scorer(corpus=corpus, judge=judge),
        message_limit=message_limit,
        metadata={"solver": SOLVER, "surface": surface, "server": server, "corpus": corpus},
    )
