# Architecture

SafetyPage is a library of the AI safety record (research papers, system cards, safety
frameworks, evaluation reports, government guidance) in which every result opens an exact page
or paragraph, and every citation can be checked against that page by code.

This document is the settled design and the contracts the parts build against. It is written
for someone reading the repository cold. Section 12 lists the decisions that needed an argument
and what the argument was.

Contents:

1. [The parts](#1-the-parts)
2. [Identity: documents, versions, anchors](#2-identity-documents-versions-anchors)
3. [Citations and URLs](#3-citations-and-urls)
4. [The document model and the corpus schema](#4-the-document-model-and-the-corpus-schema)
5. [Quote verification](#5-quote-verification)
6. [Licence tiers](#6-licence-tiers)
7. [Storage on disk: blobs and snapshots](#7-storage-on-disk-blobs-and-snapshots)
8. [The search interface](#8-the-search-interface)
9. [The tools](#9-the-tools)
10. [Traces](#10-traces)
11. [Engineering practice](#11-engineering-practice)
12. [Decision records](#12-decision-records)
13. [What is built, and what each track builds against](#13-what-is-built-and-what-each-track-builds-against)

---

## 1. The parts

```
 sources ──► ingestion ──► working corpus ──► snapshot (frozen) ──┬─► search server (one container)
 (arXiv,     (adapters,    corpus.sqlite      corpus.sqlite       │     search, fetch, verify_quote,
  lab sites,  parsers)     + blob store       lexical/ dense/     │     check_answer over MCP and JSON
  NIST ...)                                   public/             │
                                                                  └─► static files (public/ only)
                                                                        reader, page images, records

 benchmark harness (CitationBench, on Inspect) ──► calls the tools ──► traces ──► scores, leaderboard
 site (Astro) ──► reads static files and the JSON API ──► reader, replay view, checker
```

| Part | Language | State it owns |
|---|---|---|
| Core library (`src/safetypage/`, this repository's foundation) | Python | none; every other part imports it |
| Ingestion: source adapters, parsers, corpus scope | Python | the working `corpus.sqlite` and the blob store |
| Search and snapshots: index builders, retrieval arms, snapshot builder | Python | sealed snapshots |
| Server: the four tools over MCP, and the same functions as a JSON API | Python | `ops.sqlite` (call log) |
| CitationBench: the benchmark harness on Inspect | Python | runs and traces in `ops.sqlite`, `.eval` logs |
| Site: reader, replay view, landing page | Astro + React islands | none (static) |
| Edge: caching and rate limits | TypeScript Worker | none |

Three properties hold the design together.

**One implementation of each rule.** How a citation is written, whether a quote is on a page,
and which licence allows what are each decided by one function in the core library. The server
answers an agent with the same `verify_quote` that the benchmark scores with, so an in-run
verdict and a leaderboard verdict cannot disagree.

**Snapshots are immutable.** Search, the reader and the benchmark all read a frozen snapshot.
Several snapshots are served side by side, so the public library can grow while a benchmark
stays pinned to the corpus it was written against.

**Only search needs a server.** The search server is a single container holding a snapshot.
Everything else the site needs is static files. That keeps the choice of host open: a home
server behind a tunnel and a cloud host both work, and reading and citing keep working when
search is down.

---

## 2. Identity: documents, versions, anchors

Implemented in [`safetypage.ids`](../src/safetypage/ids.py).

### Documents

A document id is `<ns>:<local>`.

- `ns` says who published it: `arxiv`, `acl`, `distill`, `nist`, `anthropic`, `openai`, `lw`.
  Lowercase letters, digits and `-`.
- `local` is the publisher's own identifier where there is one (`2305.15324`,
  `2024.acl-long.787`, `ai-100-1`), otherwise a slug. Letters, digits, `.`, `_`, `-`. No `/`
  (old arXiv ids such as `hep-th/9901001` are written `hep-th.9901001`). Case is kept, because
  some sources' ids are case-sensitive.

Ids are permanent and are never derived from a file path.

### Versions

A version is one immutable state of a document's bytes. A new arXiv version, a system card
re-uploaded in place and an edited forum post are each a new version, never an overwrite.

- `v<n>` when the publisher numbers versions (arXiv's `v2`).
- `r<n>` when we observed the change ourselves, so our numbering is not mistaken for theirs.

The latest version of a document is the one with the highest number.

### Anchors

An anchor is a place inside one version.

| Anchor | Means | Notes |
|---|---|---|
| `p<n>` | PDF page `n` | The physical index, 1-based: what `#page=n` opens. The printed label (`xii`) is stored and shown, never used in an anchor. |
| `b<n>` | block `n` | A paragraph, heading, caption, figure or table. Minted once per version by `Corpus.add_blocks`, in reading order, and never reused or renumbered. |
| `p6-p8`, `b3-b9` | an inclusive range of one kind | For reading several units and for quotes that span units. |

Every version is one of two kinds:

- **paged** (`anchor_kind = "page"`): it has a PDF. The citation unit is the page. Blocks may
  exist as a structure overlay (each block records the stretch of page text it covers) and can
  be cited as a narrower scope, but search results and quote locations are reported by page.
- **unpaged** (`anchor_kind = "block"`): HTML only. The citation unit is the block.

Pages cannot drift, because they belong to the bytes. Block ids cannot drift, because they are
minted once and recorded. When a version is re-parsed or a new version appears, the
`anchor_map` table records where each old anchor went, so an old citation can be followed
forward.

The source's own ids (arXiv's LaTeXML `S3.SS1.p2`, an HTML heading id) are kept in
`blocks.source_id` for linking out. They are aliases, not anchors (see
[DR-2](#dr-2-block-anchors-are-minted-not-borrowed)).

---

## 3. Citations and URLs

A citation is **document + version + anchor**, with an optional quote.

```
cite string    arxiv:2305.15324/v2/p6
URL            https://<host>/d/arxiv/2305.15324/v2/p6
with a quote   https://<host>/d/arxiv/2305.15324/v2/p6?q=one%20of%20the%20main%20tools
```

The cite string is the URL path after `/d/` with the first `/` written as `:`. They carry the
same three parts in the same order and convert mechanically, so there is one grammar to learn,
parse and test. The cite string is what appears in tool results, traces, gold labels and
database rows. The URL is what a person clicks.

Rules:

- **A citation always names a version.** `arxiv:2305.15324/p6` is not valid. Pages move between
  versions, so an unversioned page number is not a citation.
- A *ref* may stop early: `arxiv:2305.15324` is the document (the reader shows the latest
  version and says so), `arxiv:2305.15324/v2` is one version. `fetch` and the reader accept refs.
- The anchor is in the **path**, never in a `#fragment`. Some clients and link unfurlers drop
  fragments, the server needs to see the anchor to render a correct preview card, and ChatGPT
  builds citations from the `url` field of a result.
- The quote is not part of the cite string. In a URL it rides as `?q=`, which the reader uses
  to find and highlight the words.
- The host is not part of a citation. Cite strings are stored; URLs are minted at serve time
  from the server's base URL.

Reader routes, all under `/d/`:

| Route | Shows |
|---|---|
| `/d/<ns>/<id>` | the document's record page, latest version |
| `/d/<ns>/<id>/<version>` | that version's record page |
| `/d/<ns>/<id>/<version>/<anchor>` | the reader, opened at the anchor |
| `…?q=<quote>` | the same, with the quote found and highlighted |

Linking out to the source uses `source_link()`: `#page=N` for PDFs and a `#:~:text=` fragment
for HTML. That is what a link-only document's "open at source" button uses.

API:

```python
from safetypage.ids import parse_citation, parse_ref, parse_url, find_citations

c = parse_citation("arxiv:2305.15324/v2/p6")
c.doc, c.version, c.anchor  # DocId('arxiv', '2305.15324'), 'v2', Anchor('p', 6, 6)
str(c)  # 'arxiv:2305.15324/v2/p6'
c.url("https://host")  # 'https://host/d/arxiv/2305.15324/v2/p6'
parse_url("https://host/d/arxiv/2305.15324/v2/p6?q=main%20tools")  # (Ref, 'main tools')
find_citations(answer_text)  # every canonical URL and bare cite string, in order
```

---

## 4. The document model and the corpus schema

Implemented in [`safetypage.model`](../src/safetypage/model.py),
[`safetypage.corpus`](../src/safetypage/corpus.py) and
[`migrations/corpus/`](../src/safetypage/migrations/corpus/0001_initial.sql).

```
Document        arxiv:2305.15324           one work, with a permanent id
 └ Version      v1, v2 ...                 one immutable state of its bytes; has a licence and a tier
    ├ Rendition pdf | html | latex | text  a raw file, in the blob store by content hash
    ├ Page      p1 ... pN                  a paged version's text of record: the PDF's own text layer
    └ Block     b1 ... bN                  paragraph, heading, caption, figure, table ...
                                           the citation unit of an unpaged version;
                                           a structure overlay on a paged one
```

### The text of record, and the spine

For anything with a PDF, the text of record is the PDF's own text layer, extracted in reading
order and stored one row per page. For HTML-only documents it is the text of the parsed blocks.
A model's transcription is never the text of record. Text passes through
`safetypage.text.clean_text` before it is stored, which removes only what a reader cannot see
(Unicode tag characters, bidirectional overrides, control characters) and unifies line endings.
Nothing is re-spelled, de-hyphenated or re-ordered at ingest.

A version's **spine** is its text of record as one string: its units (pages, or blocks) joined
by a single newline. Every offset in the system (`spine_start`, `spine_end`) indexes that
string. Quote checking runs against the spine, which is why a match maps back to the source's
own characters and why a quote can run from one page onto the next.

### Tables (`corpus.sqlite`)

| Table | One row per | Key columns |
|---|---|---|
| `documents` | document | `doc_id` PK, `ns`, `local_id`, `kind`, `title`, `authors` (JSON), `org`, `collection`, `published`, `source_url` |
| `versions` | version | `version_id` PK, `doc_id`, `label` (`v2`), `seq`, `anchor_kind` (`page`/`block`), `fidelity` (`text_layer`/`html`/`ocr`), `source_url`, `content_sha256`, `licence`, `tier`, `next_block` |
| `licence_facts` | observation of a licence | `version_id`, `licence`, `evidence_kind`, `evidence_url`, `evidence_quote`, `evidence_sha256`, `observed_at`, `producer`. Append-only; the newest is in force |
| `renditions` | raw file | `version_id`, `kind`, `sha256`, `bytes`, `media_type`, `source_url`, `fetched_at` |
| `pages` | PDF page | `(version_id, page)` PK, `label`, `width`, `height`, `text`, `spine_start`, `spine_end` |
| `page_words` | PDF page | `words`: JSON `[[char_start, char_end, x0, y0, x1, y1], ...]`, offsets into `pages.text`, PDF points from the top-left. Drives the reader's highlight |
| `blocks` | block | `(version_id, anchor)` PK, `seq`, `kind`, `level`, `label`, `section` (JSON path), `text`, `spine_start`, `spine_end`, `page_start`, `page_end`, `source_id`, `bbox` |
| `outline` | section heading | `version_id`, `seq`, `level`, `title`, `anchor` |
| `anchor_map` | moved anchor | from `(version, anchor)` to `(version, anchor)`, `relation`, `method`, `confidence` |
| `facts` | metadata observation | `subject`, `field`, `value` (JSON), `source`, `producer`, `input_sha256`, `retrieved_at`, `confidence`. Append-only provenance for every metadata value |
| `units` (view) | **citation unit** | `cite`, `doc_id`, `version`, `anchor`, `seq`, `kind`, `label`, `text`, `spine_start`, `spine_end`, `tier` |

`units` is the retrieval unit: one row per page of a paged version and one per block of an
unpaged version. Every retrieval arm indexes exactly these rows, so a hit is always a citable
unit and results are comparable across arms.

All tables are `STRICT`. Document kinds: `paper`, `system_card`, `model_card`, `framework`,
`eval_report`, `forum_post`, `blog`, `article`, `government`, `book`. Block kinds: `heading`,
`paragraph`, `list_item`, `caption`, `figure`, `table`, `equation`, `footnote`, `quote`,
`code`, `reference`.

### Writing: bundles

Ingestion hands storage one **bundle** per version
([`safetypage.bundle`](../src/safetypage/bundle.py)): the catalogue record, the licence fact, the
renditions by hash, and the pages or blocks. `import_bundle` is the only code that turns a
bundle into rows. The write methods on `Corpus` keep the invariants:

- the tier is computed from the licence fact (callers cannot pass one in);
- block anchors are minted from a per-version counter that never goes down;
- spine offsets are computed, not supplied (except overlay blocks, whose offsets are checked);
- a version's text is written once.

`Corpus.validate()` re-checks all of this mechanically and returns the problems it finds. A
snapshot is not sealed unless it returns none.

### Migrations

Numbered plain-SQL files, tracked in `PRAGMA user_version`, applied in a transaction each
([`safetypage.migrate`](../src/safetypage/migrate.py)). There are two schemas: `corpus` and
`ops`. The working corpus is migrated in place. A snapshot's copy is never migrated: a
read-only open refuses a database whose schema version differs from the code's, and the
snapshot is rebuilt instead.

---

## 5. Quote verification

Implemented in [`safetypage.quote`](../src/safetypage/quote.py). Deterministic, no model.

### Verdicts

One vocabulary, used by the tools, the trace, the reader and the scorer.

| Verdict | Passes | Means |
|---|---|---|
| `exact` | yes | Found where cited, character for character once runs of whitespace are collapsed |
| `normalized` | yes | Found where cited after normalisation: case, punctuation, quote marks, hyphenation, ligatures, line breaks |
| `elsewhere` | **no** | The words are in this document, but not at the cited anchor. The result says where they are |
| `near_miss` | **no** | Something close is there, but not these words. Comes with the source's wording and a word diff |
| `not_found` | **no** | Nothing close enough to report |

A pass is `exact` or `normalized`. A near miss never passes. `NEAR_MISS_CUTOFF` (80% similarity)
only decides which failing verdict is shown.

Three things that are fields rather than verdicts: `ambiguous` (a quote that occurs more than
once, with every location), `fidelity` (`ocr` means the match is against OCR text rather than
the publisher's characters) and per-fragment results for quotes with ellipses.

### Algorithm

1. **Skeleton.** The quote and the source are each reduced to case-folded letters and digits:
   NFKC (which folds ligatures, full-width forms and the math-italic letters PDF text layers
   use), diacritics stripped, soft hyphens and zero-width characters dropped. Every skeleton
   character keeps the source offset it came from.
2. **Fragments.** `...`, `…`, `[...]` and bracketed editorial insertions (`[the model]`, `[sic]`)
   split the quote. Every fragment must be found, in order, without overlap. A single bracketed
   letter (`[T]he`) is not a gap.
3. **Contiguous.** A fragment matches only as a contiguous run of the source's skeleton. There
   is no tolerance for skipped words.
4. **Whole words.** A match must start and end on a word boundary of the source. A hyphen
   inside a word (`non-trivial`), a word hyphenated across a line break (`un-⏎able`), and a
   point or comma between digits (`3.5`, `1,000`) do not make a boundary.
5. **Scope.** With a cited anchor, the anchor's stretch of the spine is searched first. Found
   there: `exact` or `normalized`. Found only elsewhere in the version: `elsewhere`.
6. **Diagnosis.** A fragment that cannot be placed is explained: found out of order, found only
   inside a longer word, or approximately found (best window by `rapidfuzz` partial alignment,
   widened to whole words, with a word-level diff).

A quote with fewer than 10 letters and digits is a term, not a quotation, and raises
`QuoteTooShortError`.

### Why steps 3 and 4 exist

The checker this project replaces let up to three stray source words sit between quoted words,
to forgive margin notes wedged into sentences by PDF text layers. That rule accepts a quotation
with the negation removed: `the model does reliably refuse` verifies against a page that says
`the model does not reliably refuse`. The regression test for it is in
[`tests/test_quote.py`](../tests/test_quote.py), and the same case on a real page is in
[`tests/test_fixture_corpus.py`](../tests/test_fixture_corpus.py) (the paper says "Model
evaluation is not the only tool available"; the quote without "not" fails with the missing
word in its diff).

Matching on a skeleton alone has the same class of hole at word edges: `able to refuse` is a
substring of `unable to refuse`, `a trivial rate` of `a non-trivial rate`, and `5% of cases` of
`3.5% of cases`. Each inverts or changes the claim. Step 4 closes it.

### What is tested

- A table of about 35 rows, each a claim about strictness.
- Property tests (Hypothesis): any run of whole words taken from a source verifies as `exact`
  at the right offsets; deleting, changing, inserting or swapping one word never passes;
  starting or ending inside a word never passes; re-flowing the source with line breaks,
  hyphenation and soft hyphens never changes a pass; and for arbitrary input, a pass implies
  the words are in the source contiguously and in order.
- Real pages: a two-version arXiv paper, a Distill article, a NIST publication.

### Known limits

- **Page furniture.** The text of record is the page's text layer as it is, including running
  heads and page numbers. A sentence that runs across a page break is not contiguous in the
  spine. The honest quote marks the gap with an ellipsis and cites the page range; that passes.
- **Math.** Matching is against the text layer. A quotation of LaTeX source matches only where
  the document's text has it. Math quotes should be reported separately in benchmark results.
- **Ellipses and brackets are trusted as visible signals.** `does … refuse` passes over a
  dropped `not`, as it would in print. The reader of the quotation can see the ellipsis.

### API

```python
from safetypage.quote import verify_quote  # plain strings; tier-agnostic; internal

result = verify_quote(quote, page_text, scope=(start, end))
result.verdict, result.passed, result.segments[0].span.text, result.segments[0].diff

from safetypage.corpus import Corpus  # against a stored document; applies the tier

check = corpus.verify_quote(quote, "arxiv:2305.15324/v2/p6")  # -> api.QuoteCheck
check.verdict, check.locations[0].cite, check.locations[0].spine_start
```

---

## 6. Licence tiers

Implemented in [`safetypage.licence`](../src/safetypage/licence.py) and
[`safetypage.policy`](../src/safetypage/policy.py).

| Tier | Which documents | What is served |
|---|---|---|
| `open` | CC BY, CC BY-SA, CC0, public domain (including US government works), UK Open Government Licence | Everything: full text, page images, the file itself |
| `link_only` | Everything else, and anything unknown: the arXiv default licence, CC NC and ND licences, ordinary copyright, no statement found | Search hits, short snippets, quote checking, the record and outline, and a link that opens the source at the page |

For a link-only document we keep a private copy, used to build the index and to check quotes.
It is never served.

### The rules

1. **A licence is a fact about one version, recorded with its evidence.** A `LicenceFact`
   holds the canonical licence id, the kind of evidence (`licence_link`, `page_statement`,
   `publisher_rule`, `statute`, `manual`), where the statement can be read, the statement
   itself, when it was read and what read it. Facts are appended, never edited.
2. **One function decides.** `decide_tier(fact)` is the only place a licence becomes a tier.
   `open` needs an allowlisted licence in canonical form *and* its evidence. No fact, an
   unrecognised string, or an open licence without evidence is `link_only`. It fails closed.
3. **Callers cannot set a tier.** `Corpus.add_version` and `Corpus.record_licence` compute it.
   The `tier` column is a cache for filtering; `Corpus.validate()` recomputes it from the
   stored fact, so a hand-edited row fails the snapshot gate.
4. **The limits are enforced on the server side**, in `safetypage.policy`, for every surface:

   | | `open` | `link_only` |
   |---|---|---|
   | full unit text | yes | never |
   | page images, source files | yes | never |
   | search snippet | up to 600 characters | up to 300 characters |
   | source text around a quote check or a fetch stub | no limit | up to 40 words |

   `Corpus.read_units` and `Corpus.verify_quote` apply these themselves. The methods that
   return whole text regardless of tier are named `private_*` and documented as for indexing
   and quote checking only. A property test asserts that nothing the public methods return
   holds a longer run of a link-only document than the limit.
5. **The publish gate.** `public/` in a snapshot is the only directory ever published.
   `check_public_tree` refuses to seal a snapshot whose `public/` holds text, images or files
   under a link-only version, or anything it does not recognise.

Both tiers get the same record page, outline, search hits and citations. The tier changes where
a person reads the document, not what the library knows about it. In the interface the tiers
read "Read here" and "Read at source".

Canonical licence ids follow SPDX where SPDX has one (`CC-BY-4.0`, `CC-BY-SA-4.0`, `CC0-1.0`,
`OGL-UK-3.0`), plus `public-domain`, `public-domain-us-gov`, `arXiv-nonexclusive-1.0`,
`all-rights-reserved` and `unknown`. `licence_from_url` maps the deed URLs that arXiv's
abstract pages link to.

---

## 7. Storage on disk: blobs and snapshots

Implemented in [`safetypage.blobs`](../src/safetypage/blobs.py) and
[`safetypage.snapshot`](../src/safetypage/snapshot.py).

```
<data root>/
  blobs/sha256/ab/cd/<hash>          every fetched file, both tiers. Private. Never served.
  corpus.sqlite                      the working corpus (ingestion writes here)
  snapshots/
    2026.11.0/                       sealed; nothing in it changes again
      manifest.json                  ids, counts, per-file hashes, the content digest
      corpus.sqlite                  all text, both tiers. Private.
      lexical/                       the Tantivy index
      dense/<model>/                 vectors.f16.npy, unit_ids.json, model.json
      public/                        THE ONLY directory that is ever published
        docs/<ns>/<id>.json                       DocumentCard, both tiers (no text)
        text/<ns>/<id>/<ver>/<anchor>.json        UnitText, with layout  open only
        pages/<ns>/<id>/<ver>/p<n>.<width>.webp   page image             open only
        files/<ns>/<id>/<ver>/source.<ext>        the file itself        open only
    2026.11.0.staging/               being built
    current -> 2026.11.0             swapped atomically
  ops.sqlite                         runs, traces, the call log. The only mutable database.
```

**Blobs.** A file's name is the SHA-256 of its bytes. The database refers to files by hash, so
moving things on disk cannot lose a record and the same bytes fetched twice are stored once.
Writes go to a temporary file and are renamed into place. Reads re-hash by default.

**Snapshot lifecycle.**

1. `stage_snapshot(corpus_db, root, "2026.11.0")` copies the working corpus into
   `2026.11.0.staging/`.
2. Builders add `lexical/`, `dense/<model>/` and `public/`. Page images for open, paged
   versions are rendered here, once, at widths 800 and 1600, and served as static files.
3. `seal_snapshot(staging)` runs the gates (`Corpus.validate()` and the publish gate), writes
   `manifest.json` and renames the directory into place. A snapshot that fails a gate is not
   sealed.
4. `set_current(root, "2026.11.0")` points `current` at it with an atomic rename.

The `text/` files are written from `Corpus.read_units(cite, layout=True)`, which adds what the
reader needs to draw a page and nothing a tool result should carry: the page's `width` and
`height` in PDF points and its `words` (the `page_words` boxes, offsets into `text`). Every
`UnitText` also carries `kind`, `level`, `spine_start` and `spine_end`, so the reader can
re-set an HTML document's blocks and place a `QuoteLocation` inside a page. The `DocumentCard`
in `docs/` carries `licence_evidence` (the licence fact in force: kind, URL, statement, when
it was read), which is what the record page shows under the licence.

`verify_snapshot` re-hashes a sealed snapshot against its manifest. The manifest's
`content_digest` hashes what the snapshot says (every unit's text, every version's licence and
tier), independent of file layout and build time, so the same inputs give the same digest.

Snapshot ids are `YYYY.MM.N`. The server opens any number of snapshots read-only; a benchmark
names the one it runs against.

**`ops.sqlite`** ([schema](../src/safetypage/migrations/ops/0001_initial.sql)) holds `runs`,
`traces`, `trace_events` and `tool_calls`. It is the only state that cannot be rebuilt from
sources and code.

---

## 8. The search interface

Contract in [`safetypage.api`](../src/safetypage/api.py): `SearchRequest`, `SearchResponse`,
`Hit`, `DocumentHit`, `SearchBackend`.

```python
class SearchBackend(Protocol):
    snapshot: str  # the frozen snapshot this backend serves, e.g. "2026.11.0"
    arms: tuple[str, ...]  # the retrieval arms built into that snapshot

    def search(self, request: SearchRequest) -> SearchResponse: ...
```

One backend serves one snapshot. The server holds a backend per snapshot it serves. The
retrieval **arm** is a field of the request, chosen by the tool surface (section 9), never by
the agent. Every response echoes the `arm` and `snapshot` that produced it.

`SearchRequest`:

| Field | Meaning |
|---|---|
| `query` | Concordance grammar: words are ANDed, `"a phrase"`, `prefix*`, `a NEAR/5 b`, `-exclude`. Empty lists documents matching the filters |
| `collection`, `org`, `kind`, `date_from`, `date_to`, `tier` | filters |
| `doc` | restrict to one document (`arxiv:2305.15324`) or version (`arxiv:2305.15324/v2`) |
| `mode` | `units` (ranked pages and paragraphs) or `documents` (documents ranked by their hits) |
| `sort` | `relevance` or `date` |
| `limit` (1–25, default 10), `cursor` | paging |
| `arm` | `bm25` (default), `dense`, `hybrid`, `hybrid-rerank`, `contextual` |
| `all_versions` | default false: only each document's latest version is searched |

`SearchResponse`: `query`, `interpretation` (how the query was read, in words), `arm`,
`snapshot`, `mode`, `total`, `hits`, `documents`, `facets`, `next_cursor`.

`Hit`: `id` (the cite string), `title`, `url`, `cite`, `doc_id`, `version`, `anchor`,
`anchor_label` (`p. 6`, `p. xii (PDF p. 14)`), `doc_title`, `org`, `kind`, `date`, `tier`,
`licence`, `score`, `snippet`, `match_spans` (character ranges in the snippet), `source_url`.
`id`, `title` and `url` are the triple ChatGPT's deep research cites from.

Rules for any backend:

- **It indexes `units`, nothing else.** One row per page or block, for every arm. One vector
  per unit; no free-floating chunks.
- **Deterministic.** For a given snapshot, arm and request the response is identical. Ties
  break on score, then cite string. No recency boosts, no cache that can change results.
- **Tier limits inside the backend.** Snippets are clipped with `safetypage.policy` before they
  leave it. Link-only units are indexed in full and returned as snippets only.
- **Bounded work.** A per-query work budget and a concurrency cap, from day one.

Storage choices: SQLite for metadata and text, Tantivy (through its Python binding) for the
keyword index, a flat `.npy` matrix per embedding model with exact search. Lexical ships first.
Dense, hybrid and the rest are arms measured on the benchmark's dev split, and the default
public arm is whichever wins there.

### As built: `safetypage.search` and `safetypage.build`

`SnapshotSearch(snapshot_dir, base_url=...)` in
[`safetypage.search.backend`](../src/safetypage/search/backend.py) is the `SearchBackend` for one
sealed snapshot.

**The query grammar** ([`safetypage.search.grammar`](../src/safetypage/search/grammar.py)):

| Query | Means |
|---|---|
| `sparse autoencoder` | both words, anywhere in the unit (bare words are ANDed; `AND` is accepted and ignored) |
| `"sparse autoencoder"` | the words together, in order |
| `"sparse auto*"` | a phrase whose last word starts with `auto` |
| `eval*` | any word starting with `eval`; at least 3 letters before the `*` |
| `refuse NEAR/5 harmful` | both words, **in either order, with at most 5 other words between them**. `NEAR` alone is `NEAR/10`; the most is `NEAR/50`. Operands are single plain words |
| `-benchmark`, `-"red team"` | the unit must not contain it; a query needs at least one positive term |

Words are what the index's analyzer makes of the text: split on anything that is not a letter
or digit, lower-cased, accents folded (`Café` = `cafe`), words of 40 bytes or more dropped. No
stemming and no stop words. `ASL-3` is the phrase `asl 3`. `OR` and parentheses are refused
with a message saying what to do instead. At most 12 terms. Tantivy's phrase slop is ordered
and charges 2 for a swap, so `NEAR/n` compiles to the union of both orders, each with slop
`n`; golden cases in [`tests/search/test_lexical.py`](../tests/search/test_lexical.py) pin
the meaning for the engine and the highlighter together.

**Filters** are request fields: `doc` (a document: its latest version; or `doc/version`),
`kind`, `collection` and `org` (case-insensitive; an unknown value is an error listing the
known ones), `tier`, `date_from`/`date_to` (`YYYY`, `YYYY-MM`, `YYYY-MM-DD`, inclusive, on the
document's `published`; undated documents never match a date filter). Only latest versions
are searched unless `all_versions` is set or `doc` names a version.

**Results.** `score` is BM25 (bm25), cosine similarity (dense) or the fused RRF score
(hybrid); `sort=date` orders by date, newest first, and reports score 0. Snippets are at most
300 characters around the densest run of matches, whitespace collapsed; a link-only unit's
snippet is cut by `policy.clip`. `match_spans` are offsets into the snippet. `facets` counts
the matches by `kind`, `collection`, `org` and `tier` (bm25 only). In `documents` mode bm25
ranks documents by how many of their units match; dense and hybrid group the top 200 units.
An empty query lists documents by id (or by date with `sort=date`). Paging is a numeric
cursor, to at most 250 results.

**Arms.** `bm25` is always there. `dense` (Qwen3-Embedding-0.6B, one vector per unit, text
truncated to 1,024 tokens, exact search) and `hybrid` (reciprocal rank fusion, k = 60, of the
top 100 of each; the bm25 half reads single words as "any of") need `dense/<model>/` in the
snapshot; without it they fall back to bm25 and the response's `arm` and `interpretation` say
so. `hybrid-rerank` and `contextual` are not built: asking for them raises
`ArmUnavailableError`.

**Limits.** Each backend runs searches on its own pool: at most 8 at once, a 2 s time limit
per query (`SearchTimeoutError`), 1 s to wait for a slot (`SearchBusyError`). A query past its
limit finishes in the background but keeps its slot, so slow queries cannot pile up. All
errors derive from `safetypage.search.errors.SearchError` and their messages are written for an
agent.

**Building a snapshot** ([`safetypage.build.snapshot`](../src/safetypage/build/snapshot.py)):
`build_snapshot(corpus_db, root, id)` stages, writes `lexical/`, `public/` (cards for every
document; for open versions each unit's `read_units(layout=True)` JSON, the source PDF or
HTML, and WebP page images at 800 and 1600 px), assembles `dense/<model>/` if the embedding
cache covers every unit (otherwise the manifest records why it was skipped), and seals.
Page images are cached by PDF hash in `<root>/cache/pages/`; blob and image files are
hard-linked into the snapshot.

**Embeddings** are a resumable batch job into `<root>/embeddings/<model>/`, keyed by the hash
of the unit's text, so a restart carries on and unchanged units are never embedded twice. The
command refuses to start outside 22:00–06:00 (local model work runs overnight) unless told
`--now`, and stops at 06:00.

```sh
uv run python -m safetypage.search build   --root data --id 2026.11.0 --current
uv run python -m safetypage.search query   --root data '"reward hacking" -benchmark' --kind paper
uv run python -m safetypage.search latency --root data
uv sync --extra embed && uv run python -m safetypage.search embed --root data   # at night
```

The site's JSON API is the same functions over HTTP, with `/s/<snapshot>/` as an optional
prefix to pin a snapshot (unprefixed routes serve `current`):

| Route | Returns |
|---|---|
| `GET /api/search?query=…&kind=…` | `SearchResponse` |
| `GET /api/doc/<ns>/<id>[/<version>]` | `DocumentCard` |
| `GET /api/units/<ns>/<id>/<version>/<anchor>` | `list[UnitText]` |
| `POST /api/verify` (`VerifyQuoteRequest`) | `QuoteCheck` |
| `POST /api/check` (`{"text": …}`) | `AnswerAudit` |

---

## 9. The tools

Four tools on the official Python MCP SDK, stateless Streamable HTTP, no authentication, all
read-only (`readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true`,
`openWorldHint: false`). Each returns a compact markdown `content` block for the model and a
`structuredContent` object whose schema is one of the models in `safetypage.api`.

| Tool | Signature | `structuredContent` |
|---|---|---|
| `search` | `search(query="", collection?, org?, kind?, date_from?, date_to?, doc?, mode="units", sort="relevance", limit=10, cursor?)` | `SearchResponse` |
| `fetch` | `fetch(id, view="text", max_tokens=6000)` | `FetchResult` |
| `verify_quote` | `verify_quote(quote, cite?, doc?)` | `QuoteCheck` |
| `check_answer` | `check_answer(text)` | `AnswerAudit` |

**`search`** is section 8. The agent's arguments are `SearchRequest` without `arm`, `tier` and
`all_versions`.

**`fetch`** takes a ref. A document id returns the `DocumentCard`: metadata, versions, licence,
outline with an anchor per section. A cite string or range (at most 8 units) returns
`UnitText` for each unit: full `text` for an open document; for a link-only one, `text` is
null and the unit carries an `excerpt` (its opening words), the `source_url` that opens the
source at that page, and a note that says what the agent can still do (cite it, search inside
it, verify a quote against it). `FetchResult` also carries OpenAI's `fetch` fields (`id`,
`title`, `text`, `url`, `metadata`). Core call: `Corpus.document_card`, `Corpus.read_units`.

**`verify_quote`** returns a `QuoteCheck`: `verdict`, `passed`, `reason`, `tier`, `fidelity`,
`locations` (each with `cite`, `url`, `anchor`, `spine_start`, `spine_end` and the source's own
`text`), per-fragment `segments` with diffs, `ambiguous` and `other_locations`. With `cite`,
that anchor is the scope. With only `doc`, the whole document is. With neither, the server
finds candidate documents through search and checks each. Core call: `Corpus.verify_quote`.

**`check_answer`** audits a draft answer. `AnswerAudit` lists every citation in the text
(`resolves`, `tier`, `error`) with the quotations attached to it and their `QuoteCheck`s, lists
unattached quotations, and gives counts and a one-line summary. It does not judge whether a
cited page supports the claim made about it, and says so in every result
(`support_checked: false`). Core call: `Corpus.check_answer`.

How quotations attach to citations is one rule set, in
[`safetypage.answer`](../src/safetypage/answer.py), shared with the scorer: a blockquote belongs
to the first citation inside it or on the next non-blank line; an inline quotation of three or
more words belongs to the nearest citation after it in the same paragraph, failing that the
nearest before it.

**Errors teach.** `NotFoundError` messages are written to be shown to an agent as the tool
error: `arxiv:2305.15324 has 20 pages; there is no p21. Pages run arxiv:2305.15324/v2/p1 to
arxiv:2305.15324/v2/p20.`

**What is not a tool: seen-text checking.** Whether an agent cited a page it never opened is
checked by the harness, which holds the trace. A stateless server has no session to check it
against.

### Surfaces

A **surface** is a named configuration: which tools, which descriptions, which retrieval arm,
which snapshot, which result shape. Surfaces are files in the repository and are how tool
design is ablated: one TOML file each in `src/safetypage/server/surfaces/`, with description
files in `surfaces/descriptions/` (see [SERVER.md](SERVER.md#surfaces)).

- `/mcp` serves the default surface on the current snapshot.
- `/x/<surface>/mcp` serves a variant at its own path. A path, not a header, because the
  clients people use (claude.ai, ChatGPT) take only a URL.
- `surface_id` is `<name>@<first 6 hex of the SHA-256 of the resolved config and its
  description files>`.

Every result carries `ResponseMeta` in MCP `_meta` under the key `safetypage` (error results
too), and in API responses as the headers `X-Server-Version`, `X-Surface`, `X-Snapshot`, `X-Arm`
and `X-Request-Id`: `server_version`, `surface_id`, `snapshot`, `arm`, `request_id`. The harness
asserts the first four are constant within a run.

A benchmark run identifies itself with the HTTP headers `X-SafetyPage-Run: <run_id>` and
`X-SafetyPage-Sample: <sample_id>` on every MCP request. How to run, call and deploy the server,
and how to add it to claude.ai and ChatGPT: [SERVER.md](SERVER.md).

---

## 10. Traces

Contract in [`safetypage.trace`](../src/safetypage/trace.py); JSON Schema in
[`schemas/trace.schema.json`](../schemas/trace.schema.json).

A trace is one question, everything the agent did, and how each citation checked out. The
benchmark writes one per sample (derived from the Inspect `.eval` log, which stays the
canonical benchmark record) and scores from it. The replay view plays it back. State at time
*t* is a pure function of `events[:t]`, so scrubbing backwards costs nothing.

```jsonc
{
  "schema": "safetypage.trace/1",
  "header": {
    "trace_id": "t_01", "run_id": "r_01", "sample_id": "pc-0412",
    "question": "…", "model": "…", "solver": "react-baseline@1",
    "surface_id": "default@a1f3c9", "snapshot": "2026.11.0", "arm": "bm25",
    "server_version": "0.1.0", "started_at": "2026-11-20T18:04:11Z",
    "usage": {"input_tokens": 48120, "output_tokens": 2210, "cost_usd": 0.083, "price_table": "2026-11-20"}
  },
  "events": [
    {"seq": 0, "t_ms": 0,    "kind": "tool", "call_id": "c1", "tool": "search",
     "args": {"query": "\"risk assessment\""},
     "returned": [{"cite": "arxiv:2305.15324/v2/p6", "score": 12.1}], "total": 41,
     "result_tokens": 1240, "latency_ms": 38, "request_id": "r_8Kq2"},
    {"seq": 1, "t_ms": 4100, "kind": "tool", "call_id": "c2", "tool": "fetch",
     "args": {"id": "arxiv:2305.15324/v2/p6"}, "returned": [{"cite": "arxiv:2305.15324/v2/p6"}]},
    {"seq": 2, "t_ms": 9000, "kind": "answer", "delta": "Model evaluation is one of the main tools"},
    {"seq": 3, "t_ms": 9400, "kind": "cite", "cite_id": "c1", "cite": "arxiv:2305.15324/v2/p6",
     "quote": "one of the main tools"},
    {"seq": 4, "t_ms": 9900, "kind": "verify", "cite_id": "c1", "state": "verified",
     "resolves": true, "seen": true, "quote_verdict": "exact", "span": [1203, 1224]}
  ],
  "answer": {"text": "…", "citations": [{"cite_id": "c1", "cite": "…", "state": "verified", "gold": true}]},
  "scores": {"page_hit": 1.0, "quote_fidelity": 1.0}
}
```

Five kinds of event, each with `seq` (from 0, no gaps) and `t_ms` (since the run started):

| `kind` | Fields | Notes |
|---|---|---|
| `think` | `text` | reasoning, when the model exposes it |
| `tool` | `call_id`, `tool`, `args`, `returned[{cite, score}]`, `total`, `verdict`, `found_at`, `result_tokens`, `latency_ms`, `error`, `request_id` | One shape for every tool, including a variant surface's. `returned` is what the replay lights up, and what makes a later citation count as seen |
| `answer` | `delta` | answer text as it streamed |
| `cite` | `cite_id`, `cite`, `quote` | a citation appearing in the answer |
| `verify` | `cite_id`, `state`, `reason`, `resolves`, `seen`, `quote_verdict`, `span`, `closest`, `judgement` | the scorer's finding on one citation |

A citation is shown in one of three states, computed by `citation_state()`:

| State | When |
|---|---|
| `verified` | it resolves, the run saw it, and its quote is `exact` or `normalized` there |
| `cited` | it resolves and the run saw it, with no quote to check |
| `rejected` | anything else, with a `reason`: `unresolved`, `unseen`, `quote_elsewhere`, `quote_near_miss`, `quote_not_found`, `unsupported` |

Deterministic checks and a judge's opinion are never mixed. A model's verdict on support is a
`judgement` object with the judge's id and its measured agreement with human labels, and only
`unsupported` comes from it.

In `ops.sqlite`, `traces` holds the header and `trace_events` holds one event per row.
`tool_calls` is the server's own log, one row per call; `request_id` joins it to a trace.
Calls that belong to a benchmark run (an `X-SafetyPage-Run` header) keep their arguments, the
cites returned and the error message. Public calls keep none of these (only the kind of error),
and no IP address is ever written.

---

## 11. Engineering practice

- Python 3.13, managed with `uv`; everything pinned in `uv.lock`.
- `ruff` for lint and format, `pyright` in strict mode on `src/` and `tests/`, `pytest` with
  `hypothesis` for property tests.
- The core library has two runtime dependencies: `pydantic` (models and JSON Schema) and
  `rapidfuzz` (near-miss diagnosis). SQLite is the standard library's.
- JSON Schemas for every wire contract are generated into [`schemas/`](../schemas) and checked
  in, so the TypeScript side builds against them without running Python. A test fails if they
  are stale.
- A fixture corpus of real, openly licensed documents is checked in
  ([`fixtures/corpus/`](../fixtures/corpus/README.md)). Documents that cannot be redistributed
  are never committed, including as fixtures; the link-only tier is tested on synthetic
  documents written for the suite.
- CI runs [`scripts/check.sh`](../scripts/check.sh): format, lint, types, schema freshness,
  fixture reproducibility, tests with coverage.
- Invisible characters in source files are written as escapes
  ([`scripts/escape_invisibles.py`](../scripts/escape_invisibles.py)), because this code is
  about soft hyphens and bidi controls and a reviewer has to be able to see them.
- Code is Apache-2.0. Corpus documents keep their own licences, recorded per version.

---

## 12. Decision records

Short records for the choices that needed an argument. Each says what was chosen, what the
alternative was, and why.

### DR-1. One cite string, one path URL

**Chosen:** `arxiv:2305.15324/v2/p6` and `/d/arxiv/2305.15324/v2/p6`.
**Alternatives:** `arxiv:2501.12948v1@p6` with `/arxiv/2501.12948/v1/p6`; or `doc_id:anchor`
with `/d/{doc}/{anchor}` and the version left to a `@v2` suffix.
**Why:** The string and the URL should be the same parts in the same order, so one parser and
one set of tests covers both. The version is always present because pages move between
versions; an unversioned page citation silently changes meaning when a paper is revised. `/` is
the only separator inside the string, which makes it trivially splittable (local ids contain no
`/`). The `/d/` prefix keeps document routes from colliding with the site's other routes. The
anchor is in the path because fragments are dropped by some clients and never reach the server.

### DR-2. Block anchors are minted, not borrowed

**Chosen:** every block anchor is `b<n>`, minted by storage. The source's ids are aliases.
**Alternatives:** use arXiv's LaTeXML ids (`S3.SS1.p2`) as anchors; content-hash paragraph ids;
section anchors (`s4.3`); label anchors (`fig3`).
**Why:** LaTeXML gives paragraphs outside any section the ids `p1`, `p2`, which collide with
page anchors. Borrowed ids also mean a different anchor grammar per source. Hash ids are
unreadable and change when a parser's whitespace handling changes. One short, typable form that
storage controls is simpler to parse, to validate and to keep stable; figures and sections are
blocks with a `kind` and a `label`, found through the outline.

### DR-3. Five verdicts

**Chosen:** `exact`, `normalized`, `elsewhere`, `near_miss`, `not_found`.
**Alternatives:** `verbatim / normalized / not_verbatim / not_found`; or `exact /
exact_normalized / fragments_in_order / near / elsewhere / not_found`.
**Why:** `elsewhere` earns its place because the wrong page is the most common real citation
error and the fix is specific. `fragments_in_order` is not a verdict: an ellipsis quote is
graded like any other, per fragment. `near` is renamed `near_miss` so that nobody reads it as a
fuzzy pass. OCR is a property of the document (`fidelity`), and ambiguity is a property of the
match; neither changes whether the words are there.

### DR-4. Matches must fall on word boundaries

**Chosen:** a match must start and end at a word boundary of the source (section 5, step 4).
**Alternative:** accept any skeleton substring, on the view that cross-word matches are
harmless given a minimum length.
**Why:** They are not harmless. `able to` inside `unable to`, `trivial` inside `non-trivial`
and `5%` inside `3.5%` each pass a quotation that says something the page does not. This is
the same failure as the dropped "not", at a different granularity.

### DR-5. The text of record is not normalised at ingest

**Chosen:** store the text layer as extracted (minus invisible hazards); normalise at match
time with an offset map.
**Alternative:** NFC, de-hyphenate and expand ligatures once at ingest and match on that.
**Why:** De-hyphenation at ingest is lossy (it cannot tell `co-\noperate` from `co-operate`)
and breaks the correspondence between characters and word boxes that the reader's highlight
needs. Normalising at match time keeps the source's own characters as the thing every offset
points at, and "the source's own characters" is what a verdict claims.

### DR-6. Two tiers, named `open` and `link_only`, decided by one function

**Chosen:** as in section 6. NonCommercial and NoDerivatives licences are link-only.
**Alternatives:** three tiers with a display-only middle tier for NC licences; `open/restricted`
or `A/B` as names.
**Why:** Two tiers are one rule to enforce and to explain. "Restricted" suggests a paywall,
and these documents are free at their source. Requiring recorded evidence for `open` means the
tier of every hosted document can be audited from the database alone.

### DR-7. Page images are rendered when a snapshot is built

**Chosen:** render open-tier page images once, into `public/pages/`, as static files.
**Alternative:** render on demand in the server and cache.
**Why:** It keeps the reader independent of the search server, makes images immutable and
cacheable forever under a snapshot id, and puts the tier check in one place (the publish gate)
instead of on a hot request path.

### DR-8. SQLite, Tantivy, flat vector files; no database server

**Chosen:** as in sections 7 and 8.
**Alternatives:** SQLite FTS5 for search; Postgres with a Tantivy-backed extension and pgvector.
**Why:** A snapshot is a directory of files that can be copied, hashed, published and served
read-only by any number of processes. FTS5 has no dynamic pruning and ranks every match, which
is adequate at 200k pages and too slow on common terms at several million. Exact vector search
over one matrix has no approximate-recall confound in ablations. Nothing here needs concurrent
writers.

### DR-9. Seen-text is checked by the harness

**Chosen:** the server does not track what an agent has read.
**Alternative:** a run handle threaded through every tool call.
**Why:** The MCP transport is stateless, and making every public caller carry a run handle
would tax all use to serve the benchmark. The harness already holds the whole trace.

### DR-10. Hosting is not decided, and the design does not depend on it

**Chosen:** the search server is one container that reads a snapshot directory; everything else
is static files under `public/`.
**Why:** Either a home server behind a tunnel or a cloud host can run one container and serve
one directory. Nothing in the contracts names a host.

### DR-11. A quotation needs ten letters or digits; bracketed insertions are gaps

**Chosen:** `MIN_QUOTE_CHARS = 10` for the whole quote, no per-fragment minimum, and
`[editorial text]` splits a quote like an ellipsis.
**Alternatives:** a 15-character minimum per fragment with shorter fragments skipped;
bracketed insertions as wildcards for up to four words.
**Why:** Skipping a short fragment means not checking it, which is a silent hole. With
whole-word matching a short fragment is safe to check. Treating a bracketed insertion as a gap
needs no new verdict and no tunable wildcard width.

### DR-12. The ingestion pipeline extracts PDFs with pypdfium2

**Chosen:** pypdfium2 (Apache-2.0 / BSD) for page text, word boxes, page labels and bookmarks
in `safetypage.ingest.pdf`. pdfium's mark for a hyphen at a line break (U+FFFE) is written as
the `-` the page shows.
**Alternative:** PyMuPDF, which the fixture builder uses (AGPL, in its own dependency group).
**Why:** On the fixture PDFs, a two-column ACL paper, an arXiv paper and a 42-page system card,
the two give the same text on every page (skeleton similarity 1.0; 0.998 at worst on
math-heavy pages, where pdfium's spacing is the better one), and the repository is Apache-2.0.
The fixture builder keeps PyMuPDF; the fixture bundles still match pypdfium2's text, which a
test checks.

### Open

- **Removing page furniture from the spine.** Running heads and page numbers interrupt
  sentences at page breaks (section 5, known limits). A furniture-aware spine would let such
  quotes pass without an ellipsis, at the cost of the spine no longer being the raw text layer.

---

## 13. What is built, and what each track builds against

Built in this repository now: the core library and its tests, the two schemas with migrations,
the JSON Schemas, and the fixture corpus.

| Module | Holds |
|---|---|
| `safetypage.ids` | doc ids, versions, anchors, refs, citations, URLs, finding citations in text |
| `safetypage.quote` | skeleton, fragments, `verify_quote`, verdicts |
| `safetypage.licence`, `safetypage.policy` | licence facts, `decide_tier`, what each tier may be served |
| `safetypage.text` | `clean_text` |
| `safetypage.model`, `safetypage.bundle` | the document model; the ingestion hand-off |
| `safetypage.corpus` | the `Corpus` database: writes, resolving, reading with the tier applied, quote checking, `check_answer`, validation |
| `safetypage.answer` | pairing quotations with citations in a written answer |
| `safetypage.blobs`, `safetypage.snapshot` | content-addressed files; staging, sealing, verifying and publishing snapshots |
| `safetypage.api`, `safetypage.trace`, `safetypage.schemas` | wire contracts, the trace format, JSON Schema export |
| `safetypage.migrate` | the migration runner |

Not built yet, and the contract each builds against:

| Track | Builds | Against |
|---|---|---|
| Ingestion and corpus scope | source adapters, parsers, HTML-to-page alignment, licence readers, scope | Emit a `Bundle` per version; `import_bundle` stores it. Text through `clean_text`. Licence as a `LicenceFact` with evidence. Files into `BlobStore`. `Corpus.validate()` must stay empty |
| Search and snapshots | Tantivy index, embeddings, arms, the `public/` export, page images | Index the `units` view. Implement `SearchBackend`. Clip with `policy`. `stage_snapshot` → build → `seal_snapshot`; paths from `public_*_path` |
| MCP server | the four tools, surfaces, the JSON API, the call log | `safetypage.api` models as `structuredContent`; `Corpus.read_units`, `document_card`, `verify_quote`, `check_answer`; `ResponseMeta`; `tool_calls` in `ops.sqlite` |
| Site and reader | reader, record pages, replay view, checker | `schemas/*.schema.json`; URL routes in section 3; `public/` layout in section 7; `page_words` for highlights; trace states in section 10 |
| CitationBench on Inspect | tasks, solvers, scorers, leaderboard data | `Trace` and `citation_state`; `parse_answer`; `Corpus.verify_quote` on the pinned snapshot; gold labels as cite strings |
