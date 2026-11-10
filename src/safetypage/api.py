"""Wire contracts: the shapes that cross a process boundary.

The MCP server returns these as ``structuredContent``, the site's JSON API returns them as
bodies, and the benchmark harness parses them. JSON Schemas for all of them are generated into
``schemas/`` (see :mod:`safetypage.schemas`), which is what the TypeScript side builds against.

Field names are the same everywhere: a unit is always identified by ``cite`` (the canonical cite
string) and ``url``; the licence tier is always ``tier``; a quote verdict is always ``verdict``.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from safetypage.licence import Tier
from safetypage.model import AnchorKindName, DocKind, Fidelity
from safetypage.quote import Verdict

__all__ = [
    "AnswerAudit",
    "Arm",
    "CitationAudit",
    "DocumentCard",
    "DocumentHit",
    "FetchRequest",
    "FetchResult",
    "Hit",
    "OutlineItem",
    "QuoteAudit",
    "QuoteCheck",
    "QuoteDiff",
    "QuoteLocation",
    "QuoteSegment",
    "ResponseMeta",
    "SearchBackend",
    "SearchRequest",
    "SearchResponse",
    "UnitText",
    "VerifyQuoteRequest",
    "VersionSummary",
]

Arm = Literal["bm25", "dense", "hybrid", "hybrid-rerank", "contextual"]
"""Retrieval arms. All arms index the same units, so a result is comparable across arms."""


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResponseMeta(_Wire):
    """Stamped on every tool result (MCP ``_meta``) and API response. Constant within a run."""

    server_version: str
    surface_id: str
    """``<name>@<hash of the resolved surface config>``, e.g. ``default@a1f3c9``."""
    snapshot: str
    arm: str
    request_id: str


# ---------------------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------------------


class SearchRequest(_Wire):
    """What an agent passes to ``search``, plus the arm (chosen by the surface, not the agent)."""

    query: str = ""
    """Concordance grammar: words are ANDed, ``"a phrase"``, ``prefix*``, ``a NEAR/5 b``,
    ``-exclude``. Empty lists documents matching the filters."""
    collection: str | None = None
    org: str | None = None
    kind: DocKind | None = None
    date_from: str | None = None
    """``YYYY`` or ``YYYY-MM``, inclusive."""
    date_to: str | None = None
    doc: str | None = None
    """Restrict to one document (a doc id) or one version (``doc_id/version``)."""
    tier: Tier | None = None
    mode: Literal["units", "documents"] = "units"
    """``units``: ranked pages and paragraphs. ``documents``: documents ranked by their hits."""
    sort: Literal["relevance", "date"] = "relevance"
    limit: int = Field(default=10, ge=1, le=25)
    cursor: str | None = None
    arm: Arm = "bm25"
    all_versions: bool = False
    """By default only each document's latest version is searched."""


class Hit(_Wire):
    """One page or paragraph. ``id``, ``title`` and ``url`` are the triple ChatGPT cites from."""

    id: str
    """The cite string; same as ``cite``."""
    title: str
    """``<document title> — <anchor label>``."""
    url: str
    cite: str
    doc_id: str
    version: str
    anchor: str
    anchor_label: str
    """What a person calls this place: ``p. 6``, ``p. xii (PDF p. 14)``, ``§3.1 ¶2``."""
    doc_title: str
    org: str | None
    kind: DocKind
    date: str | None
    tier: Tier
    licence: str
    score: float
    snippet: str
    """Never longer than the tier's snippet limit."""
    match_spans: list[tuple[int, int]] = Field(default_factory=list[tuple[int, int]])
    """Character ranges in ``snippet`` that matched the query."""
    source_url: str
    """Opens the source's own copy as near this place as its format allows."""


class DocumentHit(_Wire):
    doc_id: str
    version: str
    title: str
    url: str
    org: str | None
    kind: DocKind
    date: str | None
    tier: Tier
    licence: str
    hit_count: int
    top: list[Hit] = Field(default_factory=list[Hit])


class SearchResponse(_Wire):
    query: str
    interpretation: str
    """How the query was read, in words, so an agent can see a misparse."""
    arm: str
    snapshot: str
    mode: Literal["units", "documents"]
    total: int
    hits: list[Hit] = Field(default_factory=list[Hit])
    documents: list[DocumentHit] = Field(default_factory=list[DocumentHit])
    facets: dict[str, dict[str, int]] = Field(default_factory=dict[str, dict[str, int]])
    next_cursor: str | None = None


class SearchBackend(Protocol):
    """What the MCP server and the site call. One backend serves one frozen snapshot.

    Results are deterministic for a given (snapshot, arm, request): ties break on score, then
    cite string. Snippet limits by tier are enforced inside the backend, with
    :func:`safetypage.policy.clip`.
    """

    @property
    def snapshot(self) -> str: ...

    @property
    def arms(self) -> tuple[str, ...]: ...

    def search(self, request: SearchRequest) -> SearchResponse: ...


# ---------------------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------------------


class FetchRequest(_Wire):
    id: str
    """A doc id (the document card), ``doc/version``, a cite string, or a range
    (``arxiv:2305.15324/v2/p6-p8``, at most 8 units). A canonical URL is accepted too."""
    view: Literal["text", "image"] = "text"
    max_tokens: int = Field(default=6000, ge=500, le=16000)


class VersionSummary(_Wire):
    version: str
    published: str | None
    observed_at: str
    tier: Tier
    licence: str
    url: str
    latest: bool


class OutlineItem(_Wire):
    level: int
    title: str
    anchor: str
    cite: str
    url: str


class LicenceEvidence(_Wire):
    """How we know a version's licence: what the record page shows under "Licence"."""

    kind: str
    """``licence_link``, ``page_statement``, ``publisher_rule``, ``statute`` or ``manual``."""
    url: str
    quote: str
    observed_at: str


class DocumentCard(_Wire):
    doc_id: str
    title: str
    url: str
    authors: list[str]
    org: str | None
    kind: DocKind
    collection: str | None
    published: str | None
    source_url: str
    version: str
    """The version this card describes (the latest, unless one was asked for)."""
    versions: list[VersionSummary]
    tier: Tier
    licence: str
    anchor_kind: AnchorKindName
    fidelity: Fidelity
    unit_count: int
    outline: list[OutlineItem]
    licence_evidence: LicenceEvidence | None = None
    """The licence fact in force for this version. None when no statement was found."""
    summary: str | None = None
    """Machine-written orientation, when present. Not the source's words; never quotable."""


class UnitText(_Wire):
    cite: str
    url: str
    anchor: str
    anchor_label: str
    tier: Tier
    text: str | None
    """The unit's full text. Always None for a link-only document."""
    excerpt: str | None = None
    """Link-only documents: the unit's opening words, within the tier's limit."""
    source_url: str
    image_url: str | None = None
    """Open, paged documents: the rendered page image."""
    kind: str | None = None
    """``page``, or the block's kind (``heading``, ``paragraph``, ``caption`` ...)."""
    level: int | None = None
    """A heading block's level."""
    spine_start: int | None = None
    spine_end: int | None = None
    """The unit's stretch of the version's spine, so a quote location can be placed in it."""
    width: float | None = None
    height: float | None = None
    """A page's size in PDF points."""
    words: list[tuple[int, int, float, float, float, float]] | None = None
    """Word boxes ``[char_start, char_end, x0, y0, x1, y1]``: offsets into ``text``, PDF points
    from the top-left. Open, paged documents, and only when asked for
    (``read_units(layout=True)``, which the ``public/`` export uses). Drives the reader's text
    layer and highlight."""


class FetchResult(_Wire):
    id: str
    document: DocumentCard
    units: list[UnitText] = Field(default_factory=list[UnitText])
    truncated: str | None = None
    """Set when the token budget cut the result short: what was cut and how to get it."""
    # OpenAI's fetch contract: {id, title, text, url, metadata}
    title: str
    text: str
    url: str
    metadata: dict[str, str] = Field(default_factory=dict[str, str])


# ---------------------------------------------------------------------------------------
# verify_quote / check_answer
# ---------------------------------------------------------------------------------------


class VerifyQuoteRequest(_Wire):
    quote: str
    """The words about to go inside quotation marks. ``...`` may join fragments."""
    cite: str | None = None
    """The cite string or URL the quote will be attached to. Omit to search the library."""
    doc: str | None = None
    """Restrict a search to one document, when ``cite`` is omitted."""


class QuoteLocation(_Wire):
    cite: str
    url: str
    anchor: str
    spine_start: int
    """Character offsets in the version's spine (see ARCHITECTURE: "The spine")."""
    spine_end: int
    text: str
    """The source's own characters for this stretch (an excerpt, for a link-only document)."""


class QuoteDiff(_Wire):
    op: Literal["replace", "delete", "insert"]
    quote: str
    source: str


class QuoteSegment(_Wire):
    quote: str
    verdict: Verdict
    location: QuoteLocation | None
    diff: list[QuoteDiff] = Field(default_factory=list[QuoteDiff])
    similarity: float | None = None


class QuoteCheck(_Wire):
    quote: str
    cite: str | None
    """The citation that was checked, as given (normalised to a cite string)."""
    verdict: Verdict
    passed: bool
    """True only for ``exact`` and ``normalized``."""
    reason: str
    tier: Tier
    fidelity: Fidelity
    """``ocr`` means the match is against OCR text, not the publisher's own characters."""
    locations: list[QuoteLocation]
    """Where the quote is (``exact``, ``normalized``, ``elsewhere``) or the nearest wording
    (``near_miss``). One per fragment."""
    segments: list[QuoteSegment]
    ambiguous: bool = False
    other_locations: list[QuoteLocation] = Field(default_factory=list[QuoteLocation])


class QuoteAudit(_Wire):
    quote: str
    check: QuoteCheck | None
    error: str | None = None
    """Why the quote could not be checked (too short, nothing to check it against)."""


class CitationAudit(_Wire):
    raw: str
    """The citation as written in the answer."""
    cite: str
    url: str
    resolves: bool
    """The document, version and anchor all exist in this snapshot."""
    error: str | None = None
    tier: Tier | None = None
    quotes: list[QuoteAudit] = Field(default_factory=list[QuoteAudit])


class AnswerAudit(_Wire):
    """The deterministic audit of a draft answer. It does not judge whether a cited page
    supports the claim made about it; ``support_checked`` is always False to say so."""

    citations: list[CitationAudit]
    unattached_quotes: list[str] = Field(default_factory=list[str])
    """Quotations with no citation after them in the same paragraph."""
    citation_count: int
    resolved_count: int
    quote_count: int
    passed_count: int
    verdict_counts: dict[str, int]
    summary: str
    support_checked: Literal[False] = False
