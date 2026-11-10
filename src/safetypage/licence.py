"""Licence facts and the one function that turns a licence into a tier.

Two tiers:

* ``open``: we may host the document in full (page images, full text, the file itself).
  CC BY, CC BY-SA, CC0, public domain, and the UK Open Government Licence.
* ``link_only``: everything else, and anything unknown. Search, short snippets, quote checking
  and a link to the source. A private copy is kept for indexing and quote checking; it is
  never served.

:func:`decide_tier` is the only place a tier is computed. Storage calls it when a licence fact is
recorded (callers cannot pass a tier in), and :func:`safetypage.corpus.Corpus.validate` recomputes
it from the stored evidence, so a hand-edited ``tier`` column fails the snapshot gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal

__all__ = [
    "ALL_RIGHTS_RESERVED",
    "ARXIV_NONEXCLUSIVE",
    "UNKNOWN",
    "EvidenceKind",
    "LicenceFact",
    "Tier",
    "TierDecision",
    "decide_tier",
    "is_open_licence",
    "licence_from_url",
    "normalise_licence",
]


class Tier(StrEnum):
    OPEN = "open"
    LINK_ONLY = "link_only"


UNKNOWN: Final = "unknown"
ALL_RIGHTS_RESERVED: Final = "all-rights-reserved"
ARXIV_NONEXCLUSIVE: Final = "arXiv-nonexclusive-1.0"
PUBLIC_DOMAIN: Final = "public-domain"
PUBLIC_DOMAIN_US_GOV: Final = "public-domain-us-gov"

# Canonical ids are SPDX ids where SPDX has one. A licence is a family plus a version; the
# allowlist is by family, so CC BY 3.0 and CC BY 4.0 are both open.
_OPEN_FAMILIES: Final = frozenset({"CC-BY", "CC-BY-SA", "CC0", "CC-PDM", "OGL-UK"})
_OPEN_EXACT: Final = frozenset({PUBLIC_DOMAIN, PUBLIC_DOMAIN_US_GOV})
_KNOWN_FAMILIES: Final = frozenset(
    {*_OPEN_FAMILIES, "CC-BY-NC", "CC-BY-ND", "CC-BY-NC-SA", "CC-BY-NC-ND"}
)
_KNOWN_EXACT: Final = frozenset({*_OPEN_EXACT, UNKNOWN, ALL_RIGHTS_RESERVED, ARXIV_NONEXCLUSIVE})
_BY_LOWER: Final = {known.lower(): known for known in _KNOWN_EXACT}

_FAMILY_VERSION_RE: Final = re.compile(r"([A-Z0-9]+(?:-[A-Z]+)*)-([0-9]+\.[0-9]+)")
_CC_URL_RE: Final = re.compile(
    r"https?://(?:www\.)?creativecommons\.org/"
    r"(licenses|publicdomain)/([a-z-]+)/([0-9]+\.[0-9]+)(?:/[a-z-]*)*/?",
    re.IGNORECASE,
)
_ARXIV_URL_RE: Final = re.compile(
    r"https?://(?:www\.)?arxiv\.org/licenses/nonexclusive-distrib/1\.0/?", re.IGNORECASE
)
_OGL_URL_RE: Final = re.compile(
    r"https?://(?:www\.)?nationalarchives\.gov\.uk/doc/open-government-licence/version/([123])/?",
    re.IGNORECASE,
)


def normalise_licence(licence: str) -> str:
    """Map a licence name to its canonical id, or ``unknown``.

    Only exact, known forms are recognised. A string this function has never heard of is
    ``unknown``, and unknown is link-only: the tier fails closed.
    """
    text = licence.strip()
    if text.lower() in _BY_LOWER:
        return _BY_LOWER[text.lower()]
    candidate = text.upper().replace(" ", "-").replace("_", "-")
    m = _FAMILY_VERSION_RE.fullmatch(candidate)
    if m is not None and m.group(1) in _KNOWN_FAMILIES:
        return f"{m.group(1)}-{m.group(2)}"
    return UNKNOWN


def licence_from_url(url: str) -> str:
    """The canonical id for a licence deed URL (the form arXiv's abstract pages link to)."""
    text = url.strip()
    m = _CC_URL_RE.fullmatch(text)
    if m is not None:
        section, code, version = m.group(1).lower(), m.group(2).lower(), m.group(3)
        if section == "publicdomain":
            if code == "zero":
                return f"CC0-{version}"
            if code == "mark":
                return f"CC-PDM-{version}"
            return UNKNOWN
        return normalise_licence(f"CC-{code}-{version}")
    if _ARXIV_URL_RE.fullmatch(text):
        return ARXIV_NONEXCLUSIVE
    m = _OGL_URL_RE.fullmatch(text)
    if m is not None:
        return f"OGL-UK-{m.group(1)}.0"
    return UNKNOWN


def is_open_licence(licence: str) -> bool:
    """Whether a canonical licence id is on the open allowlist. Not the tier: see decide_tier."""
    if licence in _OPEN_EXACT:
        return True
    m = _FAMILY_VERSION_RE.fullmatch(licence)
    return m is not None and m.group(1) in _OPEN_FAMILIES


EvidenceKind = Literal[
    "licence_link",  # a licence link on the source's own page for this version (arXiv abs page)
    "page_statement",  # a licence statement in the document or on its page (Distill "Reuse")
    "publisher_rule",  # a publisher-wide rule that covers this document (ACL: CC BY from 2016)
    "statute",  # a legal rule that covers the work (17 U.S.C. 105 for US government works)
    "manual",  # a person checked and wrote down what they found
]


@dataclass(frozen=True, slots=True)
class LicenceFact:
    """What licence a version carries, and how we know.

    A licence is a fact about one version (authors can change it between arXiv versions), read
    from the source and recorded with its evidence. Facts are appended, never edited.
    """

    licence: str
    """Canonical id (see :func:`normalise_licence`)."""
    evidence_kind: EvidenceKind
    evidence_url: str
    """Where the statement can be read."""
    evidence_quote: str
    """The statement itself: the link target, the sentence on the page, or the rule."""
    observed_at: str
    """ISO-8601 UTC time the evidence was read."""
    producer: str
    """The code or person that read it, e.g. ``ingest.arxiv@3`` or ``manual:reviewer``."""
    evidence_sha256: str | None = None
    """The stored snapshot of the page the statement was read from, when there is one."""


@dataclass(frozen=True, slots=True)
class TierDecision:
    tier: Tier
    licence: str
    reason: str


def decide_tier(fact: LicenceFact | None) -> TierDecision:
    """The single place a licence becomes a tier.

    ``open`` needs both an allowlisted licence and recorded evidence for it. No fact, an
    unrecognised licence, or an open licence nobody can point to the evidence for: link-only.
    """
    if fact is None:
        return TierDecision(Tier.LINK_ONLY, UNKNOWN, "no licence fact recorded")
    licence = normalise_licence(fact.licence)
    if licence != fact.licence:
        return TierDecision(
            Tier.LINK_ONLY, UNKNOWN, f"licence {fact.licence!r} is not a canonical licence id"
        )
    if not is_open_licence(licence):
        return TierDecision(Tier.LINK_ONLY, licence, f"{licence} is not on the open allowlist")
    missing = [
        name
        for name, value in (
            ("evidence_url", fact.evidence_url),
            ("evidence_quote", fact.evidence_quote),
            ("observed_at", fact.observed_at),
            ("producer", fact.producer),
        )
        if not value.strip()
    ]
    if missing:
        return TierDecision(
            Tier.LINK_ONLY,
            licence,
            f"{licence} is open, but the fact has no {', '.join(missing)}: no evidence, no hosting",
        )
    return TierDecision(Tier.OPEN, licence, f"{licence} is on the open allowlist")
