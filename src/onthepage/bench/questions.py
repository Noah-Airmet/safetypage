"""PageCite questions: what is asked, what the gold pages are, and how each question was made.

One question per line in a JSONL file. Every question records its provenance (``made``) and how
its gold was checked (``checked``), so results can be reported per construction method and per
check level, and nothing in the set is an unrecorded hand-written test case.

Kinds:

``claim``    A sentence from a document in the library that cites another document. The agent
             finds the cited source and the page that bears on the claim, and says whether the
             source supports it. ``expected`` is ``supported`` or ``not_supported``.
``compare``  A question whose answer spans two units: one evaluation across two system cards,
             or one passage across two versions of a paper. ``expected`` is ``answer``.

Splits are assigned by a hash of the question's ``cluster`` (the cited document), so questions
about one document never sit on both sides of the dev/test line.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CANARY",
    "Check",
    "Made",
    "Question",
    "assign_split",
    "load_questions",
    "save_questions",
]

CANARY = "PAGECITE CANARY 7f3c1e2a-5b8d-4e61-9a0f-onthepage-pagecite-v1"
"""Written into every question file. Do not train on text that contains it."""

Kind = Literal["claim", "compare"]
Expected = Literal["supported", "not_supported", "answer"]
Method = Literal["citing_sentence", "perturbed_claim", "version_diff", "shared_section"]
"""``citing_sentence``: a real sentence in one library document that cites another.
``perturbed_claim``: a real citing sentence rewritten by a model so the source does not say it.
``version_diff``: a passage that changed between two versions of one document.
``shared_section``: a section heading two documents of the same kind and org both have."""


class Made(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Method
    source_cite: str | None = None
    """Where the citing sentence (or the changed passage) is, as a cite string."""
    source_text: str | None = None
    """The citing sentence as it stands in the source, or the passage it came from."""
    drafted_by: str | None = None
    """Model id and prompt id that wrote the question text and proposed the gold, if any."""
    evidence: list[dict[str, str]] = Field(default_factory=list[dict[str, str]])
    """The drafter's evidence: ``{"cite", "quote", "verdict"}``, the verdict being the code's
    quote check of that quote on that unit."""
    note: str | None = None


class Check(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["code", "model", "human"]
    """``code``: every gold quote verified on its unit by ``verify_quote``. ``model``: plus a
    second model from another family agreed. ``human``: a person accepted it."""
    by: str
    at: str
    note: str | None = None


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    """``pc-`` and the first 10 hex of the SHA-256 of the method and the source text."""
    kind: Kind
    question: str
    """What the agent is shown."""
    expected: Expected
    gold: list[str]
    """Cite strings of the units that answer it (single units, no ranges)."""
    cluster: str
    """The document the question is about (the cited document); the unit of the split and of
    the bootstrap."""
    split: Literal["dev", "test"] | None = None
    made: Made
    checks: list[Check] = Field(default_factory=list[Check])
    status: Literal["draft", "accepted", "rejected"] = "draft"

    @property
    def check_level(self) -> str:
        order = {"code": 0, "model": 1, "human": 2}
        levels = [c.level for c in self.checks]
        return max(levels, key=order.__getitem__) if levels else "none"


def question_id(method: str, text: str) -> str:
    return "pc-" + hashlib.sha256(f"{method}\n{text}".encode()).hexdigest()[:10]


def assign_split(cluster: str, *, test_share: float = 0.5) -> Literal["dev", "test"]:
    """Deterministic by cluster: the same document always lands in the same split."""
    h = int(hashlib.sha256(cluster.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "test" if h < test_share else "dev"


def load_questions(path: Path) -> list[Question]:
    out: list[Question] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        data = json.loads(line)
        if "canary" in data:
            continue
        out.append(Question.model_validate(data))
    return out


def save_questions(path: Path, questions: Iterable[Question]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"canary": CANARY})]
    lines += [q.model_dump_json(exclude_none=True) for q in questions]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines) - 1
