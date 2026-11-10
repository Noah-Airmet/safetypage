"""Claim support: a named judge model, and its measured agreement with human labels.

The judge reads one claim and the full text of the unit cited for it, and answers
``supported``, ``partially_supported`` or ``unsupported``. Its id is ``<model>#<prompt hash>``,
so a change to either is a different judge. A leaderboard names the judge it used and the
judge's agreement with people, measured on the labelling file (:mod:`onthepage.bench.label`),
because the unsupported-citation rate on identical outputs moves several-fold with the verifier
alone (arXiv 2607.20527).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Literal

from inspect_ai.model import GenerateConfig, get_model

from onthepage.trace import Judgement

from .agents import complete, is_cli_model
from .score import Judge

__all__ = [
    "JUDGE_PROMPT",
    "LABELS",
    "Agreement",
    "agreement",
    "judge_id",
    "make_judge",
    "parse_label",
]

Label = Literal["supported", "partially_supported", "unsupported"]
LABELS: tuple[Label, ...] = ("supported", "partially_supported", "unsupported")

JUDGE_PROMPT = """\
You are checking a citation. Below is a CLAIM written by someone, and the full TEXT of the page
or paragraph they cited for it.

Decide whether the TEXT supports the CLAIM:

- supported: everything the claim attributes to this source is stated in the TEXT, or follows
  directly from it. Paraphrase is fine.
- partially_supported: the TEXT supports part of the claim, but the claim adds something the
  TEXT does not say (a number, a stronger wording, a scope, a cause).
- unsupported: the TEXT does not say this, says something different, or says the opposite.

Judge only against the TEXT. Do not use what you know about the source from elsewhere.
Answer with one short sentence of reasons, then a last line of the form
LABEL: supported | partially_supported | unsupported

CLAIM:
{claim}

CITED ({cite}):
{text}
"""

PROMPT_HASH = hashlib.sha256(JUDGE_PROMPT.encode()).hexdigest()[:6]
_LABEL_RE = re.compile(r"LABEL\s*:\s*\**\s*(supported|partially_supported|unsupported)", re.I)


def judge_id(model: str) -> str:
    return f"{model}#{PROMPT_HASH}"


def parse_label(text: str) -> Label | None:
    found = _LABEL_RE.findall(text)
    return found[-1].lower() if found else None  # type: ignore[return-value]


def make_judge(model: str, *, agreement: float | None = None, max_chars: int = 24000) -> Judge:
    """A judge on any Inspect model (``anthropic/claude-sonnet-5-5``,
    ``openai-api/omlx/<model>`` ...). Unparseable answers count as ``unsupported``."""

    jid = judge_id(model)

    async def judge(claim: str, cite: str, text: str) -> Judgement:
        prompt = JUDGE_PROMPT.format(claim=claim, cite=cite, text=text[:max_chars])
        if is_cli_model(model):
            reply = await asyncio.to_thread(complete, model, prompt)
        else:
            output = await get_model(model).generate(prompt, config=GenerateConfig(max_tokens=4000))
            reply = output.completion
        label = parse_label(reply) or "unsupported"
        return Judgement(judge=jid, label=label, agreement=agreement)

    return judge


class Agreement(dict[str, float | int | str]):
    """``n``, ``accuracy``, ``kappa`` (Cohen's, three labels), and precision and recall of the
    judge's ``unsupported`` against people's, plus ``binary_kappa`` with ``partially_supported``
    folded into ``unsupported``."""


def _kappa(pairs: Sequence[tuple[str, str]]) -> float:
    n = len(pairs)
    if n == 0:
        return float("nan")
    observed = sum(a == b for a, b in pairs) / n
    left = Counter(a for a, _ in pairs)
    right = Counter(b for _, b in pairs)
    expected = sum(left[k] * right[k] for k in set(left) | set(right)) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def agreement(pairs: Iterable[tuple[str, str]], judge: str) -> Agreement:
    """``pairs`` are ``(human_label, judge_label)``."""
    pairs = list(pairs)
    n = len(pairs)
    binary = [
        (
            "supported" if h == "supported" else "unsupported",
            "supported" if j == "supported" else "unsupported",
        )
        for h, j in pairs
    ]
    tp = sum(h == "unsupported" and j == "unsupported" for h, j in binary)
    judge_unsup = sum(j == "unsupported" for _, j in binary)
    human_unsup = sum(h == "unsupported" for h, _ in binary)
    return Agreement(
        judge=judge,
        n=n,
        accuracy=sum(h == j for h, j in pairs) / n if n else float("nan"),
        kappa=_kappa(pairs),
        binary_kappa=_kappa(binary),
        unsupported_precision=tp / judge_unsup if judge_unsup else float("nan"),
        unsupported_recall=tp / human_unsup if human_unsup else float("nan"),
    )


def load_agreements(path: Path) -> dict[str, Agreement]:
    if not path.is_file():
        return {}
    return {k: Agreement(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
