# The corpus inventory

`scope/` is the list of what the library holds, and the source of truth for ingestion
(`python -m safetypage.ingest`, see [`src/safetypage/ingest/`](../src/safetypage/ingest/__init__.py)).
Fetched files are never committed; they live in the gitignored `data/` directory.

| File | Rows | What |
|---|---|---|
| `scope/labs.jsonl` | 385 | Frontier-lab system cards, model cards, safety frameworks, policies, reports |
| `scope/lab-research-web.jsonl` | 636 | Lab research published on the web: Transformer Circuits, Distill, alignment blogs |
| `scope/evaluators.jsonl` | 1,028 | Independent evaluators and safety organisations |
| `scope/government.jsonl` | 275 | NIST and CAISI, US presidential documents, UK DSIT and AISI, EU AI Office, International AI Safety Report |
| `scope/welfare.jsonl` | 40 | Model welfare research |
| `scope/papers.jsonl` | 6,804 | Research papers (arXiv, ACL Anthology, OpenReview); `papers-method.md` says how the list was made |
| `scope/forum-posts.jsonl` | 5,500 | Alignment Forum posts, and AI-tagged LessWrong posts with karma 100+ or curated |
| `scope/excluded.jsonl` | 692 | Rows set aside from the inventory, each with `excluded_because` and the shelf file it came from |

`sources.md` lists the index pages, sitemaps and feeds behind the five web files.

**Document identity.** Every web row has a `doc_id`. Rows that share one are versions of one
document (a system card re-uploaded in place, each Responsible Scaling Policy version), ingested
oldest first as `r1`, `r2` ... Redlines are their own document (`anthropic:rsp-redline`), and
families that are not one document (the EU code-of-practice drafts and chapters, the
International AI Safety Report and its summaries) are split. Paper and post ids are derived:
`arxiv:<id>` (latest version only, labelled as arXiv labels it), `acl:<id>`,
`openreview:<id>`, `lw:<post id>`.

**Excluded** from the inventory: index pages, announcements, team pages, policy and
publication landing pages, jobs, press and tool pages, stubs that only link to a document
listed elsewhere, pointers to sections of documents listed elsewhere, and duplicates.

**Duplicates.** Two documents are duplicates when their text is the same or nearly so (most of
their word 8-grams shared), whatever their titles. One copy is kept: the openly licensed copy if
there is one; otherwise the publisher's own copy over an arXiv copy or a forum cross-post (and
the ACL Anthology copy over arXiv); and within one publisher, the PDF over a web page with the
same text. The other copy's row moves to `excluded.jsonl`, naming the id that was kept.
`python -m safetypage.ingest prune` then removes from the working corpus every document the
inventory no longer lists; `prune --refetch <doc id>` also removes that document so the next
run ingests it afresh (after its row is corrected, or the extractor fixed).

`status/` is written by each ingest run: `summary.json` (counts by shelf, tier and licence),
`unfetched.jsonl` (rows that could not be fetched, or need a browser, with the reason) and
`set-aside.jsonl` (rows fetched but not ingested: scans that need OCR, unsupported files). A
browser session can save a page and hand it in with
`python -m safetypage.ingest add-file <url> <path>`; the next run ingests it.
