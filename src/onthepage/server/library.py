"""The four tools as plain functions over one snapshot. MCP and the JSON API both call these.

Every function returns an :mod:`onthepage.api` model or raises :class:`ToolError`, whose
message is written for a model reading it cold: what went wrong and what to do next.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path

from pydantic import ValidationError

from onthepage.api import (
    AnswerAudit,
    DocumentCard,
    FetchResult,
    QuoteCheck,
    ResponseMeta,
    SearchBackend,
    SearchRequest,
    SearchResponse,
    UnitText,
)
from onthepage.corpus import Corpus, CorpusError, NotFoundError
from onthepage.ids import IdError, Ref, parse_ref, parse_url
from onthepage.licence import Tier
from onthepage.migrate import current_version, load_migrations
from onthepage.quote import QuoteTooShortError, Verdict
from onthepage.snapshot import public_page_image_path

__all__ = [
    "MAX_ANSWER_CHARS",
    "MAX_QUOTE_CHARS",
    "Library",
    "MissingError",
    "ToolError",
    "estimate_tokens",
    "link_only_note",
]

MAX_QUOTE_CHARS = 2000
MAX_ANSWER_CHARS = 40_000
_CANDIDATE_DOCS = 5
_STOPWORDS = frozenset(
    """the and for that with this from are was were have has had not but its their they them
    which what when where who will would can could should may might our your than then there
    these those into about also been being such each other more most some only very""".split()  # noqa: SIM905
)


class ToolError(Exception):
    """A call that cannot be answered. The message is shown to the agent as the tool error."""

    meta: ResponseMeta | None = None
    """Set by the server once the call has a request id, so errors are stamped too."""


class MissingError(ToolError):
    """A document, version, anchor or snapshot that does not exist."""


def _failure(exc: Exception) -> ToolError:
    return MissingError(str(exc)) if isinstance(exc, NotFoundError) else ToolError(str(exc))


def estimate_tokens(text: str) -> int:
    """A rough token count (four characters a token), for budgets."""
    return len(text) // 4 + 1


def link_only_note(cite: str) -> str:
    doc = cite.split("/", maxsplit=1)[0]
    return (
        "This document is link-only: its licence does not let us return its full text. You can "
        "still cite this URL, read it at the source (source_url opens the page), search inside it "
        f'with search(doc="{doc}") for short snippets, and check exact wording with verify_quote.'
    )


def _ref(text: str) -> Ref:
    text = text.strip()
    try:
        return (
            parse_url(text)[0]
            if text.startswith(("http://", "https://", "/d/"))
            else parse_ref(text)
        )
    except IdError as exc:
        raise ToolError(
            f"{exc}. Ids look like arxiv:2305.15324 (a document), arxiv:2305.15324/v2 (a version) "
            "or arxiv:2305.15324/v2/p6 (a page); the url of a search hit works too."
        ) from exc


def open_readonly(path: Path, base_url: str) -> Corpus:
    """A read-only corpus connection usable from a worker thread."""
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
    expected = len(load_migrations("corpus"))
    found = current_version(conn)
    if found != expected:
        conn.close()
        raise CorpusError(f"{path} is at schema version {found}; this code reads {expected}")
    return Corpus(conn, base_url=base_url)


class Library:
    """One snapshot: its corpus (one read-only connection per worker thread) and its backend."""

    def __init__(
        self,
        corpus_path: Path,
        backend: SearchBackend,
        *,
        base_url: str,
        public_dir: Path | None = None,
        static_url: str | None = None,
    ) -> None:
        self.corpus_path = corpus_path
        self.backend = backend
        self.base_url = base_url.rstrip("/")
        self.public_dir = public_dir
        self.static_url = (static_url or base_url).rstrip("/")
        self._local = threading.local()

    @property
    def snapshot(self) -> str:
        return self.backend.snapshot

    @property
    def corpus(self) -> Corpus:
        corpus: Corpus | None = getattr(self._local, "corpus", None)
        if corpus is None:
            corpus = open_readonly(self.corpus_path, self.base_url)
            self._local.corpus = corpus
        return corpus

    # ------------------------------------------------------------------ search

    def search(self, arm: str, **args: object) -> SearchResponse:
        try:
            request = SearchRequest.model_validate({**args, "arm": arm})
        except ValidationError as exc:
            raise ToolError(_validation_message(exc, "search")) from exc
        if request.doc is not None:
            request = request.model_copy(update={"doc": str(_ref(request.doc))})
        try:
            response = self.backend.search(request)
        except Exception as exc:
            if _is_search_error(exc):
                raise ToolError(str(exc)) from exc
            raise
        if response.total == 0 and _has_filters(request):
            bare = self.backend.search(
                SearchRequest(query=request.query, arm=request.arm, limit=1, mode=request.mode)
            )
            if bare.total:
                raise ToolError(
                    f"0 hits with these filters ({response.interpretation}); without filters this "
                    f"query has {bare.total}. Drop or change a filter."
                )
        return response

    def full_texts(self, cites: list[str], max_tokens: int) -> dict[str, str]:
        """Full text of open units, for a surface that returns text with search hits."""
        out: dict[str, str] = {}
        used = 0
        for cite in cites:
            for unit in self.corpus.read_units(cite):
                if unit.text is None:
                    continue
                used += estimate_tokens(unit.text)
                if used > max_tokens:
                    return out
                out[unit.cite] = unit.text
        return out

    # ------------------------------------------------------------------ fetch

    def fetch(self, id: str, view: str = "text", max_tokens: int = 6000) -> FetchResult:
        if view not in ("text", "image"):
            raise ToolError('view must be "text" or "image".')
        max_tokens = max(500, min(int(max_tokens), 16000))
        ref = _ref(id)
        corpus = self.corpus
        try:
            card = corpus.document_card(Ref(ref.doc, ref.version))
            units = [] if ref.anchor is None else corpus.read_units(ref)
        except CorpusError as exc:
            raise _failure(exc) from exc
        truncated: str | None = None
        kept: list[UnitText] = []
        used = estimate_tokens(" ".join(o.title for o in card.outline))
        for unit in units:
            used += estimate_tokens(unit.text or unit.excerpt or "")
            if kept and used > max_tokens:
                rest = units[len(kept) :]
                first, last = rest[0].anchor, rest[-1].anchor
                span = first if first == last else f"{first}-{last}"
                truncated = (
                    f"Cut at the {max_tokens}-token budget after {kept[-1].anchor}. Continue with "
                    f'fetch(id="{card.doc_id}/{card.version}/{span}") or raise max_tokens.'
                )
                break
            kept.append(self._with_image(unit) if view == "image" else unit)
        return self._fetch_result(ref, card, kept, truncated)

    def _with_image(self, unit: UnitText) -> UnitText:
        if unit.tier != Tier.OPEN or not unit.anchor.startswith("p") or self.public_dir is None:
            return unit
        path = public_page_image_path(parse_ref(unit.cite).citation(), 1600)
        if not (self.public_dir.parent / path).is_file():
            return unit
        relative = path.relative_to("public")
        return unit.model_copy(update={"image_url": f"{self.static_url}/{relative}"})

    def _fetch_result(
        self, ref: Ref, card: DocumentCard, units: list[UnitText], truncated: str | None
    ) -> FetchResult:
        metadata = {
            "doc_id": card.doc_id,
            "version": card.version,
            "tier": str(card.tier),
            "licence": card.licence,
            "source_url": card.source_url,
        }
        if not units:
            outline = "\n".join(f"{o.title} ({o.cite})" for o in card.outline)
            text = f"{card.title}. {card.unit_count} units. Outline:\n{outline}"
            return FetchResult(
                id=str(ref),
                document=card,
                title=card.title,
                text=text,
                url=card.url,
                metadata=metadata,
            )
        if card.tier != Tier.OPEN:
            metadata["note"] = link_only_note(units[0].cite)
        text = "\n\n".join(u.text if u.text is not None else (u.excerpt or "") for u in units)
        first, last = units[0], units[-1]
        label = (
            first.anchor_label if first is last else f"{first.anchor_label} to {last.anchor_label}"
        )
        return FetchResult(
            id=str(ref),
            document=card,
            units=units,
            truncated=truncated,
            title=f"{card.title} — {label}",
            text=text,
            url=first.url
            if first is last
            else Ref(ref.doc, card.version, ref.anchor).url(self.base_url),
            metadata=metadata,
        )

    def units(self, ref: str) -> list[UnitText]:
        try:
            return self.corpus.read_units(_ref(ref))
        except CorpusError as exc:
            raise _failure(exc) from exc

    def document(self, ref: str) -> DocumentCard:
        r = _ref(ref)
        try:
            return self.corpus.document_card(Ref(r.doc, r.version))
        except CorpusError as exc:
            raise _failure(exc) from exc

    # ------------------------------------------------------------------ verify_quote

    def verify_quote(
        self, quote: str, cite: str | None = None, doc: str | None = None
    ) -> QuoteCheck:
        quote = quote.strip()
        if not quote:
            raise ToolError(
                "quote is empty: pass the exact words you intend to put in quotation marks."
            )
        if len(quote) > MAX_QUOTE_CHARS:
            raise ToolError(
                f"quote is {len(quote)} characters; the most is {MAX_QUOTE_CHARS}. Check a long "
                "passage in parts, or join its pieces with '...'."
            )
        try:
            if cite:
                return self.corpus.verify_quote(quote, _ref(cite))
            if doc:
                return self.corpus.verify_quote(quote, _ref(doc))
            return self._verify_anywhere(quote)
        except QuoteTooShortError as exc:
            raise ToolError(
                f"{exc}. A term that short is a search, not a quotation: use search instead."
            ) from exc
        except CorpusError as exc:
            raise _failure(exc) from exc

    def _verify_anywhere(self, quote: str) -> QuoteCheck:
        words = [
            w for w in re.findall(r"[^\W_]+", quote.lower()) if len(w) > 2 and w not in _STOPWORDS
        ]
        distinct = sorted(dict.fromkeys(words), key=len, reverse=True)
        candidates: list[str] = []
        for take in (6, 3, 2):
            query = " ".join(distinct[:take])
            if not query:
                break
            response = self.backend.search(SearchRequest(query=query, limit=25))
            for hit in response.hits:
                key = f"{hit.doc_id}/{hit.version}"
                if key not in candidates:
                    candidates.append(key)
            if candidates:
                break
        if not candidates:
            raise ToolError(
                "No document in the library contains the distinctive words of this quote, so "
                "there is nothing to check it against. It may be a paraphrase, or from outside the "
                "library. Search for its key terms, or pass cite= or doc= if you know the source."
            )
        rank = {
            Verdict.EXACT: 0,
            Verdict.NORMALIZED: 1,
            Verdict.ELSEWHERE: 2,
            Verdict.NEAR_MISS: 3,
            Verdict.NOT_FOUND: 4,
        }
        checks = [self.corpus.verify_quote(quote, c) for c in candidates[:_CANDIDATE_DOCS]]
        return min(
            checks, key=lambda c: (rank[c.verdict], -max((s.similarity or 0) for s in c.segments))
        )

    # ------------------------------------------------------------------ check_answer

    def check_answer(self, text: str) -> AnswerAudit:
        if len(text) > MAX_ANSWER_CHARS:
            raise ToolError(
                f"text is {len(text)} characters; the most is {MAX_ANSWER_CHARS}. Check the answer "
                "in sections."
            )
        return self.corpus.check_answer(text)


def _is_search_error(exc: Exception) -> bool:
    """A backend refusing a query (bad syntax, unknown filter, busy, slow): tell the agent."""
    module = type(exc).__module__
    return isinstance(exc, ValueError | LookupError) or module.startswith(
        ("onthepage.search", "onthepage.server.backend")
    )


def _has_filters(request: SearchRequest) -> bool:
    return any(
        getattr(request, name) is not None
        for name in ("collection", "org", "kind", "date_from", "date_to", "doc")
    )


def _validation_message(exc: ValidationError, tool: str) -> str:
    problems = "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}" for e in exc.errors()
    )
    return f"{tool}: bad arguments ({problems})."
