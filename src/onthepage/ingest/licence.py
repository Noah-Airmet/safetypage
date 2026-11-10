"""Licence facts for ingested versions: the inventory's finding, checked by machine where it can be.

Every version gets a fact. ``decide_tier`` (core) turns it into a tier; nothing here does.

What is checked:

* **arXiv**: the licence URL in arXiv's metadata (OAI-PMH, via the inventory's snapshot) is
  mapped with ``licence_from_url`` and must agree with the inventory's licence.
* **ACL Anthology**: the Anthology's rule (CC BY 4.0 from 2016, CC BY-NC-SA 3.0 before) is
  applied to the year in the Anthology id.
* **Web documents claimed open** (CC, OGL): the fetched page or PDF must carry the statement.
  Found: a ``page_statement`` fact quoting it, with the hash of the file it was read from. Not
  found: the inventory's evidence is recorded as it is (``manual``), so an open claim nobody
  machine-checked is still visible as such.
* **US federal works**: public domain by statute (17 U.S.C. 105), recorded as ``statute``.
* **LessWrong / Alignment Forum**: no open licence; EA Forum-hosted cross-posts from 2022-12-01
  on are CC BY 4.0 by that forum's rule, checked against the post's own record.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

from onthepage.bundle import BundleLicence
from onthepage.ingest.items import Item
from onthepage.licence import (
    ALL_RIGHTS_RESERVED,
    ARXIV_NONEXCLUSIVE,
    UNKNOWN,
    EvidenceKind,
    is_open_licence,
    licence_from_url,
    normalise_licence,
)

__all__ = ["INVENTORY", "PRODUCER", "canonical", "licence_for"]

PRODUCER: Final = "ingest.licence@1"
INVENTORY: Final = "inventory:corpus/scope@2026-11-09"

_ALIASES: Final = {
    "arxiv-default": ARXIV_NONEXCLUSIVE,
    "licenseref-us-gov-pd": "public-domain-us-gov",
    "licenseref-ogl-uk-3.0": "OGL-UK-3.0",
    "all-rights-reserved": ALL_RIGHTS_RESERVED,
}

_STATEMENTS: Final[dict[str, re.Pattern[str]]] = {
    "CC-BY": re.compile(
        r"creativecommons\.org/licenses/by/\d\.\d|Creative Commons Attribution(?![- ]Non)"
        r"(?: 4\.0)?(?: International)?(?: Licen[cs]e)?|\bCC[- ]BY(?:[- ]4\.0)?\b(?![- ]?N)",
        re.IGNORECASE,
    ),
    "CC-BY-SA": re.compile(
        r"creativecommons\.org/licenses/by-sa/|Attribution-ShareAlike|CC[- ]BY[- ]SA",
        re.IGNORECASE,
    ),
    "CC0": re.compile(r"creativecommons\.org/publicdomain/zero|\bCC0\b|CC-0", re.IGNORECASE),
    "OGL-UK": re.compile(r"Open Government Licen[cs]e", re.IGNORECASE),
}

_EAF_RULE_URL: Final = "https://forum.effectivealtruism.org/posts/KK6AE8HzPkR2KnqSg"
_LW_TERMS_URL: Final = "https://intelligence.org/files/PrivacyandTerms-Lesswrong.com.pdf"


def canonical(licence: str) -> str:
    return _ALIASES.get(licence.strip().lower()) or normalise_licence(licence)


def _family(licence: str) -> str:
    m = re.fullmatch(r"([A-Z0-9]+(?:-[A-Z]+)*)-[0-9]+\.[0-9]+", licence)
    return m.group(1) if m else licence


def _snippet(text: str, start: int, end: int, pad: int = 120) -> str:
    return " ".join(text[max(0, start - pad) : end + pad].split())


_DEED_RE: Final = re.compile(
    r"https?://(?:www\.)?(?:creativecommons\.org/(?:licenses|publicdomain)/[a-z-]+/\d\.\d"
    r"|nationalarchives\.gov\.uk/doc/open-government-licence/version/\d)/?",
    re.IGNORECASE,
)
_TAG_RE: Final = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.IGNORECASE | re.DOTALL)


def _visible(content: str) -> str:
    """Text a reader sees, for quoting: tags dropped, entities left as they are."""
    if "<" not in content[:2000]:
        return content
    return _TAG_RE.sub(" ", content)


def _statement(content: str, pattern: re.Pattern[str]) -> tuple[str | None, str] | None:
    """The licence a file states, and the statement. A deed link names the exact licence and
    version, and wins over the inventory's reading; a phrase alone confirms the family."""
    text = _visible(content)
    matches = list(pattern.finditer(text))
    # Prefer the occurrence in a sentence about licensing over a passing mention.
    phrase = next(
        (m for m in matches if "licen" in text[max(0, m.start() - 150) : m.end() + 150].lower()),
        matches[0] if matches else None,
    )
    quote = _snippet(text, phrase.start(), phrase.end()) if phrase else ""
    for deed in _DEED_RE.finditer(content):
        licence = licence_from_url(deed.group(0).rstrip("/") + "/")
        if licence != UNKNOWN and is_open_licence(licence):
            return licence, f"{quote} [links to {deed.group(0)}]".strip()
    if phrase is None:
        return None
    return None, quote


def _fact(  # noqa: PLR0917
    licence: str,
    kind: EvidenceKind,
    url: str,
    quote: str,
    observed_at: str,
    producer: str,
    sha: str | None = None,
) -> BundleLicence:
    return BundleLicence(
        licence=licence,
        evidence_kind=kind,
        evidence_url=url,
        evidence_quote=quote.strip() or "(no statement recorded)",
        observed_at=observed_at,
        producer=producer,
        evidence_sha256=sha,
    )


def licence_for(
    item: Item,
    *,
    observed_at: str,
    content: str = "",
    content_sha256: str | None = None,
    post: Mapping[str, object] | None = None,
) -> BundleLicence:
    """The licence fact for one version of ``item``.

    ``content`` is the fetched file as text (raw HTML, or the PDF's text) for the statement check;
    ``post`` is the forum post's own record, for forum items.
    """
    claimed = canonical(item.licence)
    evidence = item.licence_evidence

    if item.adapter == "arxiv":
        m = re.search(r"https?://\S+?(?=[\s)]|$)", evidence)
        deed = m.group(0).rstrip(".,") if m else ""
        found = licence_from_url(deed) if deed else UNKNOWN
        oai = (
            "https://export.arxiv.org/oai2?verb=GetRecord&metadataPrefix=arXiv"
            f"&identifier=oai:arXiv.org:{item.url}"
        )
        if found != claimed or found == UNKNOWN:
            return _fact(
                UNKNOWN,
                "manual",
                oai,
                f"metadata licence {deed!r} does not map to {claimed}: {evidence}",
                observed_at,
                PRODUCER,
            )
        return _fact(
            found,
            "licence_link",
            oai,
            deed,
            observed_at,
            f"{PRODUCER} (arXiv OAI-PMH metadata via the inventory snapshot)",
        )

    if item.doc_id.startswith("acl:"):
        m = re.match(r"(\d{4})\.|[A-Z](\d{2})-", item.doc_id.removeprefix("acl:"))
        year = None
        if m:
            year = int(m.group(1)) if m.group(1) else 2000 + int(m.group(2))
        if year is None:
            return _fact(UNKNOWN, "manual", item.source_url, evidence, observed_at, INVENTORY)
        rule = "CC-BY-4.0" if year >= 2016 else "CC-BY-NC-SA-3.0"
        return _fact(
            rule,
            "publisher_rule",
            "https://aclanthology.org/faq/copyright/",
            "ACL materials published in or after 2016 are licensed CC BY 4.0; materials "
            f"before 2016 CC BY-NC-SA 3.0. This paper's Anthology id gives {year}.",
            observed_at,
            PRODUCER,
        )

    if item.adapter == "lw":
        cross = item.extra.get("crosspost")
        if claimed.startswith("CC-BY") and isinstance(cross, dict) and post is not None:
            posted = str(post.get("postedAt") or "")
            hosted_elsewhere = cross.get("hosted_on_lw") is False  # pyright: ignore[reportUnknownMemberType]
            linkpost = bool(post.get("url"))
            if hosted_elsewhere and not linkpost and posted >= "2022-12-01":
                return _fact(
                    "CC-BY-4.0",
                    "publisher_rule",
                    _EAF_RULE_URL,
                    "The EA Forum licenses all content posted from 2022-12-01 under CC BY 4.0. "
                    f"This post is hosted on the EA Forum (post {cross.get('eaf_post_id')}), "  # pyright: ignore[reportUnknownMemberType]
                    f"posted {posted[:10]}, and is not a link-post.",
                    observed_at,
                    PRODUCER,
                )
        return _fact(UNKNOWN, "manual", _LW_TERMS_URL, evidence, observed_at, INVENTORY)

    if claimed == "public-domain-us-gov":
        return _fact(
            claimed,
            "statute",
            "https://www.law.cornell.edu/uscode/text/17/105",
            "17 U.S.C. 105: copyright protection is not available for any work of the "
            f"United States Government. {evidence}",
            observed_at,
            PRODUCER,
        )

    family = _family(claimed)
    pattern = _STATEMENTS.get(family)
    if pattern is not None and content:
        found = _statement(content, pattern)
        if found is not None:
            licence, quote = found
            return _fact(
                licence or claimed,
                "page_statement",
                item.url,
                quote,
                observed_at,
                PRODUCER,
                content_sha256,
            )
    if claimed in {UNKNOWN, ALL_RIGHTS_RESERVED} or pattern is None or not evidence:
        if claimed == UNKNOWN and item.licence.lower() not in {"unknown", ""}:
            evidence = f"inventory licence {item.licence!r}: {evidence}"
        return _fact(claimed, "manual", item.url, evidence, observed_at, INVENTORY)
    # Claimed open, statement not found in the fetched file: keep the inventory's finding as
    # what a reviewer recorded, and say that the machine check did not find it.
    rule_url = re.search(r"https?://\S+", evidence)
    if rule_url and rule_url.group(0).rstrip(".,);") != item.url:
        return _fact(
            claimed,
            "publisher_rule",
            rule_url.group(0).rstrip(".,);"),
            evidence,
            observed_at,
            INVENTORY,
        )
    return _fact(
        claimed,
        "manual",
        item.url,
        f"{evidence} (not found in the fetched file by {PRODUCER})",
        observed_at,
        INVENTORY,
    )
