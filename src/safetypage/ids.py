"""Document ids, version labels, anchors, citations and their URLs.

One grammar, used everywhere (tool results, traces, gold labels, the reader's routes):

    cite string   arxiv:2305.15324/v2/p6
    URL           https://<host>/d/arxiv/2305.15324/v2/p6

The cite string is the URL path after ``/d/`` with the first ``/`` written as ``:``.

    doc id    <ns>:<local>      ns     [a-z][a-z0-9-]*          (who published it)
                                local  [A-Za-z0-9._-]+          (their id, or a slug; no "/")
    version   v<n> | r<n>       v = the publisher's own numbering (arXiv v2)
                                r = a revision we observed (the bytes changed at the source)
    anchor    p<n>              physical PDF page, 1-based (what ``#page=N`` opens)
              b<n>              a block (paragraph, heading, figure...) minted once per version
              p<n>-p<m>, b<n>-b<m>   an inclusive range of one kind

A citation always names a version and an anchor. A *ref* may stop early: ``arxiv:2305.15324``
is the document, ``arxiv:2305.15324/v2`` is one version of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal
from urllib.parse import quote as _urlquote
from urllib.parse import unquote, urlsplit

__all__ = [
    "Anchor",
    "AnchorKind",
    "Citation",
    "DocId",
    "FoundCitation",
    "IdError",
    "Ref",
    "arxiv_ref",
    "find_citations",
    "mint_local_id",
    "parse_citation",
    "parse_ref",
    "parse_url",
    "source_link",
    "text_fragment",
    "version_label",
    "version_number",
]

AnchorKind = Literal["p", "b"]

_NS: Final = r"[a-z][a-z0-9-]{0,31}"
_LOCAL: Final = r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?"
_VERSION: Final = r"[vr][1-9][0-9]{0,5}"
_N: Final = r"[1-9][0-9]{0,6}"
_ANCHOR: Final = rf"(?:p{_N}(?:-p{_N})?|b{_N}(?:-b{_N})?)"

_NS_RE: Final = re.compile(_NS)
_LOCAL_RE: Final = re.compile(_LOCAL)
_VERSION_RE: Final = re.compile(_VERSION)
_ANCHOR_RE: Final = re.compile(rf"([pb])({_N})(?:-([pb])({_N}))?")

URL_PREFIX: Final = "/d/"


class IdError(ValueError):
    """An id, anchor, citation or URL that does not follow the grammar."""


@dataclass(frozen=True, slots=True, order=True)
class DocId:
    """A document: ``<ns>:<local>``. Immutable once minted; never derived from a file path."""

    ns: str
    local: str

    def __post_init__(self) -> None:
        if not _NS_RE.fullmatch(self.ns):
            raise IdError(f"bad namespace {self.ns!r}: lowercase letters, digits and '-'")
        if not _LOCAL_RE.fullmatch(self.local):
            raise IdError(
                f"bad local id {self.local!r}: letters, digits, '.', '_' and '-' "
                "(no '/'; must start and end with a letter or digit)"
            )

    @classmethod
    def parse(cls, text: str) -> DocId:
        ns, sep, local = text.partition(":")
        if not sep:
            raise IdError(f"bad doc id {text!r}: expected <ns>:<local>, e.g. arxiv:2305.15324")
        return cls(ns, local)

    def __str__(self) -> str:
        return f"{self.ns}:{self.local}"

    @property
    def path(self) -> str:
        """The id as two URL path segments: ``arxiv/2305.15324``."""
        return f"{self.ns}/{self.local}"


@dataclass(frozen=True, slots=True, order=True)
class Anchor:
    """A page (``p6``), a block (``b12``) or an inclusive range of one kind (``p6-p8``)."""

    kind: AnchorKind
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.kind not in ("p", "b"):
            raise IdError(f"bad anchor kind {self.kind!r}: 'p' (page) or 'b' (block)")
        if self.start < 1 or self.end < self.start:
            raise IdError(f"bad anchor range {self.kind}{self.start}-{self.kind}{self.end}")

    @classmethod
    def page(cls, n: int, end: int | None = None) -> Anchor:
        return cls("p", n, n if end is None else end)

    @classmethod
    def block(cls, n: int, end: int | None = None) -> Anchor:
        return cls("b", n, n if end is None else end)

    @classmethod
    def parse(cls, text: str) -> Anchor:
        m = _ANCHOR_RE.fullmatch(text)
        if m is None:
            raise IdError(
                f"bad anchor {text!r}: expected p<n> (PDF page), b<n> (block) "
                "or a range such as p6-p8"
            )
        kind, start, end_kind, end = m.group(1), int(m.group(2)), m.group(3), m.group(4)
        if end_kind is not None and end_kind != kind:
            raise IdError(f"bad anchor {text!r}: a range stays in one kind (p6-p8 or b3-b9)")
        last = start if end is None else int(end)
        if last <= start and end is not None:
            raise IdError(f"bad anchor {text!r}: a range must run forwards")
        return cls("p" if kind == "p" else "b", start, last)

    @property
    def is_range(self) -> bool:
        return self.end > self.start

    @property
    def size(self) -> int:
        return self.end - self.start + 1

    def singles(self) -> list[Anchor]:
        """The single anchors this one covers, in order."""
        return [Anchor(self.kind, n, n) for n in range(self.start, self.end + 1)]

    def contains(self, other: Anchor) -> bool:
        return self.kind == other.kind and self.start <= other.start and other.end <= self.end

    def __str__(self) -> str:
        if self.is_range:
            return f"{self.kind}{self.start}-{self.kind}{self.end}"
        return f"{self.kind}{self.start}"


def version_label(number: int, *, publisher_numbered: bool) -> str:
    """``v<n>`` when the source numbers its own versions, ``r<n>`` when we observed the change."""
    if number < 1:
        raise IdError("version numbers start at 1")
    label = f"{'v' if publisher_numbered else 'r'}{number}"
    if not _VERSION_RE.fullmatch(label):
        raise IdError(f"bad version number {number}")
    return label


def version_number(label: str) -> int:
    if not _VERSION_RE.fullmatch(label):
        raise IdError(f"bad version {label!r}: expected v<n> or r<n>, e.g. v2")
    return int(label[1:])


@dataclass(frozen=True, slots=True)
class Ref:
    """A document, one of its versions, or an anchor in a version.

    ``fetch`` and the reader accept any of the three; a :class:`Citation` is the complete form.
    """

    doc: DocId
    version: str | None = None
    anchor: Anchor | None = None

    def __post_init__(self) -> None:
        if self.version is None:
            if self.anchor is not None:
                raise IdError("an anchor needs a version: pages and blocks belong to one version")
        else:
            version_number(self.version)

    def __str__(self) -> str:
        parts = [str(self.doc)]
        if self.version is not None:
            parts.append(self.version)
        if self.anchor is not None:
            parts.append(str(self.anchor))
        return "/".join(parts)

    @property
    def path(self) -> str:
        """The URL path, ``/d/<ns>/<local>[/<version>[/<anchor>]]``."""
        return URL_PREFIX + str(self).replace(":", "/", 1)

    def url(self, base_url: str) -> str:
        return base_url.rstrip("/") + self.path

    def citation(self, quote: str | None = None) -> Citation:
        if self.version is None or self.anchor is None:
            raise IdError(f"{self} is not a citation: a citation names a version and an anchor")
        return Citation(self.doc, self.version, self.anchor, quote)


@dataclass(frozen=True, slots=True)
class Citation:
    """Document + version + anchor, with an optional quote. The unit of everything here."""

    doc: DocId
    version: str
    anchor: Anchor
    quote: str | None = None

    def __post_init__(self) -> None:
        version_number(self.version)

    @property
    def ref(self) -> Ref:
        return Ref(self.doc, self.version, self.anchor)

    def __str__(self) -> str:
        """The canonical cite string. The quote is not part of it."""
        return f"{self.doc}/{self.version}/{self.anchor}"

    @property
    def path(self) -> str:
        return self.ref.path

    def url(self, base_url: str) -> str:
        """The canonical URL. A quote rides along as ``?q=`` so the reader can highlight it."""
        url = self.ref.url(base_url)
        if self.quote:
            url += "?q=" + _urlquote(self.quote, safe="")
        return url


def parse_ref(text: str) -> Ref:
    """Parse ``ns:local``, ``ns:local/version`` or ``ns:local/version/anchor``."""
    parts = text.split("/")
    if len(parts) > 3:
        raise IdError(
            f"bad ref {text!r}: expected <ns>:<id>[/<version>[/<anchor>]], "
            "e.g. arxiv:2305.15324/v2/p6"
        )
    doc = DocId.parse(parts[0])
    version = parts[1] if len(parts) > 1 else None
    if version is not None:
        version_number(version)
    anchor = Anchor.parse(parts[2]) if len(parts) > 2 else None
    return Ref(doc, version, anchor)


def parse_citation(text: str) -> Citation:
    """Parse a complete cite string such as ``arxiv:2305.15324/v2/p6``."""
    return parse_ref(text).citation()


def parse_url(url: str) -> tuple[Ref, str | None]:
    """Parse a canonical URL (any host) or a bare ``/d/...`` path into a ref and its ``?q=`` quote.

    The host is not checked here; callers that care compare it to their own base URL.
    """
    parts = urlsplit(url)
    path = parts.path
    if not path.startswith(URL_PREFIX):
        raise IdError(f"bad citation URL {url!r}: the path must start with {URL_PREFIX}")
    segments = path[len(URL_PREFIX) :].rstrip("/").split("/")
    if len(segments) < 2 or len(segments) > 4:
        raise IdError(f"bad citation URL {url!r}: expected /d/<ns>/<id>[/<version>[/<anchor>]]")
    ref = parse_ref(f"{segments[0]}:{'/'.join(segments[1:])}")
    quote: str | None = None
    for pair in parts.query.split("&"):
        key, sep, value = pair.partition("=")
        if key == "q" and sep:
            quote = unquote(value.replace("+", " ")) or None
    return ref, quote


_CITE_STRING_RE: Final = re.compile(rf"(?<![\w/:.-])({_NS}:{_LOCAL}/{_VERSION}/{_ANCHOR})(?![\w-])")
_CITE_URL_RE: Final = re.compile(
    rf"https?://[^\s/<>()\[\]\"']+(/d/{_NS}/{_LOCAL}/{_VERSION}/{_ANCHOR})(\?q=[^\s<>()\[\]\"']*)?"
)


@dataclass(frozen=True, slots=True)
class FoundCitation:
    """A citation found in running text, with where it was found."""

    citation: Citation
    start: int
    end: int
    raw: str


def find_citations(text: str) -> list[FoundCitation]:
    """Find every canonical URL and bare cite string in a piece of text, in order.

    Used by ``check_answer`` and by the benchmark scorer, so both read an answer the same way.
    """
    found: list[FoundCitation] = []
    taken: list[tuple[int, int]] = []
    for m in _CITE_URL_RE.finditer(text):
        try:
            ref, quote = parse_url(m.group(1) + (m.group(2) or ""))
        except IdError:
            continue
        found.append(FoundCitation(ref.citation(quote), m.start(), m.end(), m.group(0)))
        taken.append((m.start(), m.end()))
    for m in _CITE_STRING_RE.finditer(text):
        if any(s <= m.start() < e for s, e in taken):
            continue
        try:
            citation = parse_citation(m.group(1))
        except IdError:
            continue
        found.append(FoundCitation(citation, m.start(1), m.end(1), m.group(1)))
    found.sort(key=lambda f: f.start)
    return found


_LOCAL_UNSAFE_RE: Final = re.compile(r"[^A-Za-z0-9._-]+")


def mint_local_id(raw: str) -> str:
    """Turn a source's native id or a title into a legal local id.

    ``/`` becomes ``.`` (so old arXiv ids such as ``hep-th/9901001`` keep their shape), any other
    illegal run becomes ``-``. Case is kept, because some sources' ids are case-sensitive.
    """
    local = _LOCAL_UNSAFE_RE.sub("-", raw.strip().replace("/", ".")).strip("-._")
    if not _LOCAL_RE.fullmatch(local):
        raise IdError(f"cannot mint a local id from {raw!r}")
    return local


_ARXIV_RE: Final = re.compile(
    r"(?:arxiv:)?((?:[0-9]{4}\.[0-9]{4,5})|(?:[a-z-]+(?:\.[A-Z]{2})?/[0-9]{7}))(?:v([1-9][0-9]*))?",
    re.IGNORECASE,
)


def arxiv_ref(identifier: str) -> Ref:
    """``2305.15324v2`` (arXiv's own way of writing it) as a ref: ``arxiv:2305.15324/v2``."""
    m = _ARXIV_RE.fullmatch(identifier.strip())
    if m is None:
        raise IdError(f"not an arXiv identifier: {identifier!r}")
    doc = DocId("arxiv", mint_local_id(m.group(1)))
    return Ref(doc, f"v{m.group(2)}" if m.group(2) else None)


def text_fragment(quote: str, *, max_words: int = 8) -> str:
    """A ``#:~:text=`` fragment that scrolls a browser to ``quote`` on the source's own page.

    Long quotes use the ``start,end`` form so the URL stays short.
    """
    words = quote.split()
    if not words:
        return ""

    def enc(chunk: list[str]) -> str:
        return _urlquote(" ".join(chunk), safe="").replace("-", "%2D")

    if len(words) <= 2 * max_words:
        return "#:~:text=" + enc(words)
    return "#:~:text=" + enc(words[:max_words]) + "," + enc(words[-max_words:])


def source_link(
    source_url: str, anchor: Anchor | None, *, paged: bool, quote: str | None = None
) -> str:
    """The link that opens the source's own copy as near the cited place as its format allows.

    PDFs open at the page (``#page=N``, the physical index). HTML opens at the quoted words when a
    quote is known. This is what a link-only document's "open at source" button uses.
    """
    base = source_url.split("#", 1)[0]
    if paged and anchor is not None and anchor.kind == "p":
        return f"{base}#page={anchor.start}"
    if not paged and quote:
        return base + text_fragment(quote)
    return base
