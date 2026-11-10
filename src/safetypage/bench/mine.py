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

import hashlib
import re
from dataclasses import asdict, dataclass
from itertools import pairwise
from typing import Any

from rapidfuzz import fuzz

from safetypage.corpus import Corpus
from safetypage.ids import Anchor
from safetypage.model import Version
from safetypage.quote import skeleton

__all__ = [
    "Candidate",
    "citing_contexts",
    "pick",
    "shared_sections",
    "split_sentences",
    "version_diffs",
]

_ABBREV = {"al", "e.g", "i.e", "fig", "figs", "cf", "vs", "eq", "sec", "no", "approx", "et"}
_BOUNDARY = re.compile(r"(?<=[.!?])[\"”’)\]]?\s+(?=[A-Z(\[“\"])")
_REFS_HEADING = re.compile(r"(?m)^\s*(?:\d+\s+)?(?:References|Bibliography|REFERENCES)\s*$")
_NUMBERED_REF = re.compile(r"\[(\d{1,3})\]|^\s*(\d{1,3})\.\s", re.M)
_BRACKETS = re.compile(r"\[(\d{1,3}(?:\s*[,–-]\s*\d{1,3})*)\]")
_REF_ENTRY = re.compile(r"^\s*\[\d{1,3}\]")
MIN_SENTENCE, MAX_SENTENCE = 40, 400


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


def _digitless(key: str) -> str:
    return re.sub(r"[0-9]", "", key)


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


_ARXIV_ID = re.compile(r"\b(\d{4}\.\d{4,5})(?:v\d+)?\b")
_KEY = 14
"""Titles are found by their first ``_KEY`` normalized characters, then matched in full."""


def _title_index(docs: dict[str, Any]) -> dict[str, list[tuple[str, str]]]:
    """Normalized titles by their first ``_KEY`` characters. A paper's title must be at least 20
    characters to count; a system card's or framework's may be shorter ("GPT-4 System Card")."""
    index: dict[str, list[tuple[str, str]]] = {}
    for doc_id, doc in docs.items():
        title = _norm(doc.title)
        if len(title) >= (20 if doc.kind in ("paper", "forum_post", "blog", "article") else _KEY):
            index.setdefault(title[:_KEY], []).append((title, doc_id))
    return index


def citing_contexts(corpus: Corpus) -> list[Candidate]:
    """Every sentence in a library document that cites another library document.

    A cited document is found in the citing document's reference list (the text after its last
    "References" heading) by title or arXiv id; the sentence by the in-text marker."""
    latest = {d: vs[-1] for d in corpus.doc_ids() if (vs := corpus.versions(d))}
    docs = {d: doc for d in latest if (doc := corpus.document(d)) is not None}
    index = _title_index(docs)
    out: list[Candidate] = []
    seen: set[tuple[str, str]] = set()
    for citing_id, version in latest.items():
        text = corpus.private_spine_text(version)
        refs_at = _references_start(text)
        if refs_at >= len(text):
            continue
        refs = text[refs_at:]
        sk = skeleton(refs)
        found: dict[str, list[int]] = {}
        for i in range(len(sk.text) - _KEY + 1):
            for title, doc_id in index.get(sk.text[i : i + _KEY], ()):
                if doc_id != citing_id and sk.text.startswith(title, i):
                    found.setdefault(doc_id, []).append(refs_at + sk.offsets[i])
        for m in _ARXIV_ID.finditer(refs):
            doc_id = f"arxiv:{m.group(1)}"
            if doc_id in docs and doc_id != citing_id:
                found.setdefault(doc_id, []).append(refs_at + m.start())
        if not found:
            continue
        spans = split_sentences(text[:refs_at])
        for cited_id, title_pos in found.items():
            doc = docs[cited_id]
            for pos in _markers(text, title_pos, doc.authors, doc.published):
                if pos >= refs_at:
                    continue
                span = _sentence_at(spans, pos)
                if span is None:
                    continue
                s, e = span
                sentence = _clean(text[s:e])
                if not MIN_SENTENCE <= len(sentence) <= MAX_SENTENCE:
                    continue
                if len(_BRACKETS.findall(sentence)) > 2 or _REF_ENTRY.match(sentence):
                    continue  # a list of works, or a reference entry, says nothing about one
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
            # Only "[12]" alone: a group ("[2-6]", "[3, 12]") does not single the work out.
            if _expand(m.group(1)) == {n}:
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
                if best in n_key or n_key in best or _digitless(best) == _digitless(n_key):
                    continue  # a page header, footer or number glued on, not an edit
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


def pick(
    corpus: Corpus, candidates: list[Candidate], quotas: dict[str, int], *, seed: str = "v1"
) -> list[Candidate]:
    """A spread of candidates to draft from. ``quotas`` maps ``<method>`` or
    ``<method>/<kind of the document asked about>`` to a count, so system cards, frameworks
    and government guidance are not swamped by papers. Within a quota the order is a fixed
    hash of the seed and the candidate; at most two candidates per document asked about (three
    for version diffs),
    and one per citing-and-cited pair."""

    def order(c: Candidate) -> str:
        return hashlib.sha256(f"{seed}|{c.source_cite}|{c.source_text}".encode()).hexdigest()

    kinds: dict[str, str] = {}
    out: list[Candidate] = []
    per_doc: dict[str, int] = {}
    pairs: set[tuple[str, str]] = set()
    for key, n in quotas.items():
        method, _, kind = key.partition("/")
        taken = 0
        for c in sorted(candidates, key=order):
            if taken >= n:
                break
            cap = 3 if method == "version_diff" else 2  # few documents have versions
            if c.method != method or per_doc.get(c.cluster, 0) >= cap:
                continue
            if c.cluster not in kinds:
                doc = corpus.document(c.cluster)
                kinds[c.cluster] = doc.kind if doc else ""
            if kind and kinds[c.cluster] != kind:
                continue
            pair = (dict(c.extra).get("citing_doc", c.source_cite), c.cluster)
            if method == "citing_sentence" and pair in pairs:
                continue
            pairs.add(pair)
            per_doc[c.cluster] = per_doc.get(c.cluster, 0) + 1
            out.append(c)
            taken += 1
    return out
