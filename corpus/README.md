# The corpus inventory

`scope/` is the list of what the library holds, and the source of truth for ingestion
(`python -m onthepage.ingest`, see [`src/onthepage/ingest/`](../src/onthepage/ingest/__init__.py)).
Fetched files are never committed; they live in the gitignored `data/` directory.

| File | Rows | What |
|---|---|---|
| `scope/labs.jsonl` | 461 | Frontier-lab system cards, model cards, safety frameworks, policies, reports |
| `scope/lab-research-web.jsonl` | 691 | Lab research published on the web: Transformer Circuits, Distill, alignment blogs |
| `scope/evaluators.jsonl` | 1,102 | Independent evaluators and safety organisations |
| `scope/government.jsonl` | 314 | NIST and CAISI, US presidential documents, UK DSIT and AISI, EU AI Office, International AI Safety Report |
| `scope/welfare.jsonl` | 42 | Model welfare research |
| `scope/papers.jsonl` | 6,826 | Research papers (arXiv, ACL Anthology, OpenReview); `papers-method.md` says how the list was made |
| `scope/forum-posts.jsonl` | 5,698 | Alignment Forum posts, and AI-tagged LessWrong posts with karma 100+ or curated |
| `scope/excluded.jsonl` | 226 | Rows set aside from the web inventory, each with `excluded_because` |

`sources.md` lists the index pages, sitemaps and feeds behind the five web files.

**Document identity.** Every web row has a `doc_id`. Rows that share one are versions of one
document (a system card re-uploaded in place, each Responsible Scaling Policy version), ingested
oldest first as `r1`, `r2` ... Redlines are their own document (`anthropic:rsp-redline`), and
families that are not one document (the EU code-of-practice drafts and chapters, the
International AI Safety Report and its summaries) are split. Paper and post ids are derived:
`arxiv:<id>` (latest version only, labelled as arXiv labels it), `acl:<id>`,
`openreview:<id>`, `lw:<post id>`.

**Excluded** from the web inventory: index pages, announcements, team pages, policy and
publication landing pages, jobs, press and tool pages, stubs that only link to a document
listed elsewhere, pointers to sections of documents listed elsewhere, and duplicate URLs.

`status/` is written by each ingest run: `summary.json` (counts by shelf, tier and licence),
`unfetched.jsonl` (rows that could not be fetched, or need a browser, with the reason) and
`set-aside.jsonl` (rows fetched but not ingested: scans that need OCR, unsupported files). A
browser session can save a page and hand it in with
`python -m onthepage.ingest add-file <url> <path>`; the next run ingests it.
