"""Mining question candidates from the corpus itself, so questions are not the author's own.

Three sources, all found by code:

``citing_contexts``  a sentence in one library document that cites another library document.
                     The reference entry is matched by the cited document's title (or arXiv
                     id) in the citing document's text; the in-text marker by author and year
                     (``Olah et al., 2020``) or by reference number (``[12]``).
``version_diffs``    a sentence that changed between two versions of one document.
``shared_sections``  a section heading that two documents of the same kind and org both have
                     (one evaluation across two system cards).

Each candidate carries cite strings located by code. :mod:`safetypage.bench.draft` turns
candidates into questions.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from itertools import pairwise
from typing import Any

from rapidfuzz import fuzz

from safetypage.corpus import Corpus
from safetypage.ids import Anchor
from safetypage.model import Version

__all__ = [
    "Candidate",
    "citing_contexts",
    "shared_sections",
    "split_sentences",
    "version_diffs",
]

_ABBREV = {"al", "e.g", "i.e", "fig", "figs", "cf", "vs", "eq", "sec", "no", "approx", "et"}
_BOUNDARY = re.compile(r"(?<=[.!?])[\"”’)\]]?\s+(?=[A-Z(\[“\"])")
_REFS_HEADING = re.compile(r"(?m)^\s*(?:\d+\s+)?(?:References|Bibliography|REFERENCES)\s*$")
_NUMBERED_REF = re.compile(r"\[(\d{1,3})\]|^\s*(\d{1,3})\.\s", re.M)
_BRACKETS = re.compile(r"\[(\d{1,3}(?:\s*[,–-]\s*\d{1,3})*)\]")
MIN_SENTENCE, MAX_SENTENCE = 40, 700


@dataclass(frozen=True)
class Candidate:
    method: str
    cluster: str
    """The document the question will be about."""
    source_cite: str
    source_text: str
    targets: tuple[str, ...] = ()
    """Cite strings code has already located: the other version's passage, or the other
    document's section. Empty for a citing context (the drafter finds the gold page)."""
    target_texts: tuple[str, ...] = ()
    extra: tuple[tuple[str, str], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def load(cls, row: dict[str, Any]) -> Candidate:
        return cls(
            method=str(row["method"]),
            cluster=str(row["cluster"]),
            source_cite=str(row["source_cite"]),
            source_text=str(row["source_text"]),
            targets=tuple(str(t) for t in row.get("targets", [])),
            target_texts=tuple(str(t) for t in row.get("target_texts", [])),
            extra=tuple((str(k), str(v)) for k, v in row.get("extra", [])),
        )


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _cite(version: Version, anchor: Anchor) -> str:
    return f"{version.doc_id}/{version.label}/{anchor}"


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans in ``text``. Abbreviations such as ``et al.`` do not end a sentence."""
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _BOUNDARY.finditer(text):
        before = text[max(0, m.start() - 6) : m.start()].rstrip('.!?"”’)]').split()
        word = before[-1].lower() if before else ""
        if word in _ABBREV or (len(word) == 1 and word.isalpha()):
            continue
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return [(s, e) for s, e in spans if e > s]


def _sentence_at(spans: list[tuple[int, int]], pos: int) -> tuple[int, int] | None:
    for s, e in spans:
        if s <= pos < e:
            return s, e
    return None


def _clean(text: str) -> str:
    return " ".join(text.split())


def _references_start(text: str) -> int:
    found = list(_REFS_HEADING.finditer(text))
    return found[-1].start() if found else len(text)


def citing_contexts(corpus: Corpus) -> list[Candidate]:
    """Every sentence in a library document that cites another library document."""
    latest = {d: corpus.versions(d)[-1] for d in corpus.doc_ids() if corpus.versions(d)}
    out: list[Candidate] = []
    seen: set[tuple[str, str]] = set()
    for citing_id, version in latest.items():
        text = corpus.private_spine_text(version)
        sk = corpus.private_skeleton(version)
        refs_at = _references_start(text)
        spans = split_sentences(text)
        for cited_id, _cited_version in latest.items():
            if cited_id == citing_id:
                continue
            doc = corpus.document(cited_id)
            if doc is None:
                continue
            title = _norm(doc.title)
            local = doc_id_local(cited_id)
            hits = (
                [m.start() for m in re.finditer(re.escape(title), sk.text)]
                if len(title) >= 20
                else []
            )
            title_pos = [sk.offsets[h] for h in hits]
            if not title_pos and local and re.search(rf"\b{re.escape(local)}\b", text):
                title_pos = [m.start() for m in re.finditer(re.escape(local), text)]
            if not title_pos:
                continue
            markers = _markers(text, title_pos, doc.authors, doc.published)
            for pos in markers:
                if pos >= refs_at or any(abs(pos - t) < 400 for t in title_pos):
                    continue
                span = _sentence_at(spans, pos)
                if span is None:
                    continue
                s, e = span
                sentence = _clean(text[s:e])
                if not MIN_SENTENCE <= len(sentence) <= MAX_SENTENCE:
                    continue
                key = (cited_id, sentence)
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    Candidate(
                        method="citing_sentence",
                        cluster=cited_id,
                        source_cite=_cite(version, corpus.locate(version, s, e)),
                        source_text=sentence,
                        extra=(("citing_doc", citing_id), ("cited_title", doc.title)),
                    )
                )
    return out


def doc_id_local(doc_id: str) -> str | None:
    ns, local = doc_id.split(":", 1)
    return local if ns == "arxiv" else None


def _markers(
    text: str, title_pos: list[int], authors: list[str] | None, published: str | None
) -> list[int]:
    """Positions of in-text citation markers for one reference."""
    found: list[int] = []
    year = (published or "")[:4]
    if authors and year.isdigit():
        surname = re.escape(authors[0].split()[-1])
        pattern = (
            rf"\b{surname}(?:\s+et\s+al\.?|\s+(?:and|&)\s+[A-Z][\w-]+)?,?\s*\(?\s*{year}[a-z]?\b"
        )
        found += [m.start() for m in re.finditer(pattern, text)]
    # Numbered references: the number printed just before the title in the reference list.
    for t in title_pos:
        window = text[max(0, t - 400) : t]
        numbers = [m.group(1) or m.group(2) for m in _NUMBERED_REF.finditer(window)]
        if not numbers:
            continue
        n = int(numbers[-1])
        for m in _BRACKETS.finditer(text):
            if n in _expand(m.group(1)):
                found.append(m.start())
    return sorted(set(found))


def _expand(group: str) -> set[int]:
    out: set[int] = set()
    for part in re.split(r"\s*,\s*", group):
        bounds = re.split(r"\s*[–-]\s*", part)
        if len(bounds) == 2 and all(b.isdigit() for b in bounds):
            out.update(range(int(bounds[0]), int(bounds[1]) + 1))
        elif part.isdigit():
            out.add(int(part))
    return out


def version_diffs(corpus: Corpus, *, per_pair: int = 8) -> list[Candidate]:
    """Sentences that were edited (not added or dropped) between consecutive versions."""
    out: list[Candidate] = []
    for doc_id in corpus.doc_ids():
        versions = corpus.versions(doc_id)
        for old, new in pairwise(versions):
            old_text, new_text = corpus.private_spine_text(old), corpus.private_spine_text(new)
            old_end, new_end = _references_start(old_text), _references_start(new_text)
            old_s = {_norm(old_text[s:e]): (s, e) for s, e in split_sentences(old_text[:old_end])}
            new_s = {_norm(new_text[s:e]): (s, e) for s, e in split_sentences(new_text[:new_end])}
            only_old = [k for k in old_s if k not in new_s and len(k) >= MIN_SENTENCE]
            only_new = [k for k in new_s if k not in old_s and len(k) >= MIN_SENTENCE]
            pairs: list[tuple[float, str, str]] = []
            for n_key in only_new:
                best = max(only_old, key=lambda o: fuzz.ratio(o, n_key), default=None)
                if best is None:
                    continue
                score = fuzz.ratio(best, n_key)
                if 60 <= score < 97:
                    pairs.append((score, best, n_key))
            pairs.sort(key=lambda p: (p[0], p[2]))
            for _, o_key, n_key in pairs[:per_pair]:
                (os_, oe), (ns, ne) = old_s[o_key], new_s[n_key]
                old_sentence, new_sentence = _clean(old_text[os_:oe]), _clean(new_text[ns:ne])
                if len(new_sentence) > MAX_SENTENCE:
                    continue
                out.append(
                    Candidate(
                        method="version_diff",
                        cluster=doc_id,
                        source_cite=_cite(new, corpus.locate(new, ns, ne)),
                        source_text=new_sentence,
                        targets=(_cite(old, corpus.locate(old, os_, oe)),),
                        target_texts=(old_sentence,),
                    )
                )
    return out


_NUMBERING = re.compile(r"^\s*(?:[A-Z]|\d+)(?:\.\d+)*\.?\s+")
SHARED_KINDS = ("system_card", "model_card", "framework", "eval_report")


def shared_sections(corpus: Corpus, *, min_title: int = 12) -> list[Candidate]:
    """One section heading in two documents of the same org and kind, consecutive by date."""
    groups: dict[tuple[str, str], list[tuple[str, Version]]] = {}
    for doc_id in corpus.doc_ids():
        doc = corpus.document(doc_id)
        versions = corpus.versions(doc_id)
        if doc is None or not versions or doc.kind not in SHARED_KINDS or not doc.org:
            continue
        groups.setdefault((doc.org, doc.kind), []).append((doc.published or "", versions[-1]))
    out: list[Candidate] = []
    for members in groups.values():
        members.sort(key=lambda m: (m[0], m[1].doc_id))
        sections: list[dict[str, str]] = []
        for _, version in members:
            sections.append(
                {
                    _norm(_NUMBERING.sub("", e.title)): e.anchor
                    for e in corpus.outline(version.version_id)
                    if len(_norm(e.title)) >= min_title
                }
            )
        for i in range(len(members) - 1):
            (_, a), (_, b) = members[i], members[i + 1]
            for key in sorted(set(sections[i]) & set(sections[i + 1])):
                title = next(
                    e.title
                    for e in corpus.outline(b.version_id)
                    if _norm(_NUMBERING.sub("", e.title)) == key
                )
                out.append(
                    Candidate(
                        method="shared_section",
                        cluster=b.doc_id,
                        source_cite=f"{b.doc_id}/{b.label}/{sections[i + 1][key]}",
                        source_text=_clean(_NUMBERING.sub("", title)),
                        targets=(f"{a.doc_id}/{a.label}/{sections[i][key]}",),
                    )
                )
    return out
