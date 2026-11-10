"""Human labels for claim-citation pairs, to measure the judge.

A pair is a claim and the unit cited for it. Pairs come from the question set (each citing or
perturbed sentence with its gold units) and from runs (each answer's claims with what they
cite). The pairs file holds cite strings and claims only, never document text, so it can be
published; the labeller reads the unit from the corpus.

    python -m onthepage.bench pairs [--traces pagecite/traces]
    python -m onthepage.bench label --who noah
    python -m onthepage.bench agreement --judge anthropic/claude-sonnet-5-5

Labelling is blind: the labeller never sees the judge's label or the pair's source.
"""

from __future__ import annotations

import hashlib
import json
import random
import textwrap
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from onthepage.corpus import Corpus
from onthepage.ids import find_citations
from onthepage.trace import Trace

from .questions import Question
from .score import claim_context

__all__ = ["label_loop", "pairs_from_questions", "pairs_from_traces", "read_jsonl"]

KEYS = {"s": "supported", "p": "partially_supported", "u": "unsupported"}


def _pair(claim: str, cite: str, source: str) -> dict[str, str]:
    pid = "lp-" + hashlib.sha256(f"{claim}\n{cite}".encode()).hexdigest()[:10]
    return {"pair_id": pid, "claim": claim, "cite": cite, "source": source}


def pairs_from_questions(questions: Iterable[Question]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for q in questions:
        if q.kind != "claim" or not q.made.source_text:
            continue
        claim = q.question.split("> ", 1)[-1].split("\n\n", 1)[0]
        for cite in q.gold:
            out.append(_pair(claim, cite, f"question:{q.id}"))
    return out


def pairs_from_traces(paths: Iterable[Path]) -> list[dict[str, str]]:

    out: list[dict[str, str]] = []
    for path in paths:
        trace = Trace.model_validate_json(path.read_text(encoding="utf-8"))
        if trace.answer is None:
            continue
        text = trace.answer.text
        resolved = {c.cite for c in trace.answer.citations if c.reason != "unresolved"}
        for found in find_citations(text):
            cite = str(found.citation)
            if cite in resolved and found.citation.anchor.size == 1:
                claim = claim_context(text, found.start, found.end)
                out.append(_pair(claim, cite, f"run:{trace.header.run_id}"))
    return out


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def unit_text(corpus: Corpus, cite: str) -> str:
    r = corpus.resolve(cite)
    if r.scope is None:
        raise ValueError(f"{cite} names no unit")
    return corpus.private_spine_text(r.version)[r.scope[0] : r.scope[1]]


def label_loop(corpus: Corpus, pairs: list[dict[str, str]], out: Path, who: str) -> int:
    """Ask a person about each unlabelled pair, in a fixed shuffled order. Returns how many
    were labelled this session."""
    done = {r["pair_id"] for r in read_jsonl(out)}
    todo = [p for p in pairs if p["pair_id"] not in done]
    random.Random(who).shuffle(todo)  # noqa: S311  (an order, not a secret)
    labelled = 0
    for i, pair in enumerate(todo, start=1):
        print("\n" + "=" * 78)
        print(f"[{i}/{len(todo)}]  CLAIM:\n")
        print(textwrap.fill(pair["claim"], 78))
        print(f"\nCITED: {pair['cite']}\n")
        print(textwrap.fill(" ".join(unit_text(corpus, pair["cite"]).split()), 78))
        while True:
            key = input("\n[s]upported  [p]artially  [u]nsupported  [k] skip  [q] quit > ")
            key = key.strip().lower()[:1]
            if key in KEYS or key in ("k", "q"):
                break
        if key == "q":
            break
        if key == "k":
            continue
        _append(
            out,
            {
                "pair_id": pair["pair_id"],
                "label": KEYS[key],
                "who": who,
                "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
        labelled += 1
    return labelled
