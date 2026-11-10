# SafetyPage

A page-cited library of the AI safety record, built for people and for AI agents: research
papers on interpretability, alignment, evals and model welfare; frontier-lab system cards, model
cards and safety frameworks; evaluation reports; and government AI guidance.

Every search result opens an exact page or paragraph. Every citation names a document, a
version and a place in it, and code can check a quotation against that place. We check that
the page says it, and show you the page.

The repository also holds **CitationBench**, a benchmark of whether an agent with a library
tool cites the right page and quotes it accurately.

## Status

Everything here runs locally today. The site and the server are not deployed yet, so there is
no public URL to try.

- The library is built: a sealed snapshot of the corpus below, with keyword search over every
  page and paragraph. Embedding search is written and its vectors are still being computed.
- The server, the site and the benchmark harness are built and tested against a small fixture
  corpus that is checked in, so all of it can be run from a clone without the 100 GB of data.
- CitationBench has only small smoke runs so far (see [below](#citationbench)). There are no
  published numbers.

## What is in the library

Snapshot `2026.11.0`, built 9 November 2026:

| | |
|---|---|
| Documents | 14,356 (14,415 versions) |
| Citable units | 694,358: 170,594 PDF pages and 523,764 paragraphs of web documents |
| Hosted in full (open licences) | 3,524 versions, 114,245 units, with page images |
| Search, snippets, quote checks and a link to the source | 10,891 versions, 580,113 units |

| Shelf | Documents |
|---|---|
| Research papers (arXiv, ACL Anthology, OpenReview) | 6,278 |
| Alignment Forum and LessWrong posts | 5,593 |
| Independent evaluators and safety organisations | 1,096 |
| Lab research published on the web | 687 |
| Lab system cards, model cards, frameworks, policies | 395 |
| Government (NIST and CAISI, UK DSIT and AISI, EU AI Office, others) | 271 |
| Model welfare research | 38 |

[`corpus/`](corpus/README.md) is the inventory the library is built from, with what could not
be fetched and why in [`corpus/status/`](corpus/status/). The documents themselves are not in
the repository.

**Licence tiers.** Openly licensed documents (CC BY, CC BY-SA, CC0, public domain, UK Open
Government Licence) are hosted in full. Everything else, and anything whose licence is
unknown, gets search, short snippets, quote checking and a link that opens the source at the
page. The tier is computed by one function from a recorded licence fact with its evidence, and
it is enforced inside the library.

## What a citation is

```
arxiv:2305.15324/v2/p6                               document / version / anchor
https://<host>/d/arxiv/2305.15324/v2/p6              the same thing, as a link
```

`p6` is a PDF page. `b12` is a paragraph of a document that has no pages. A citation always
names a version, because pages move when a paper is revised.

## Checking a quote

```python
from safetypage.quote import verify_quote

page = "We find that the model does not reliably refuse harmful requests."

verify_quote("the model does not reliably refuse", page).verdict  # 'exact'
verify_quote("The model does NOT reliably refuse", page).verdict  # 'normalized'

miss = verify_quote("the model does reliably refuse harmful requests", page)
miss.verdict  # 'near_miss'  (a near miss fails)
miss.segments[0].diff  # (DiffOp(op='insert', quote='', source='not'),)
```

Five verdicts: `exact` and `normalized` pass; `elsewhere` (right words, wrong page),
`near_miss` and `not_found` fail. The check is deterministic and uses no model. It normalises
case, punctuation, hyphenation, ligatures and line breaks, and it keeps a map back to the
source's own characters, so a match can be shown on the page. It does not tolerate skipped
words, and a match has to start and end on a word boundary: `able to refuse` is not a
quotation of a page that says `unable to refuse`.

## Run it

Needs [uv](https://docs.astral.sh/uv/). This serves the fixture corpus (a handful of real,
openly licensed documents) on port 8000:

```sh
uv sync --all-groups
uv run python -m safetypage.server --fixtures
curl 'localhost:8000/api/search?query=%22risk%20assessment%22&limit=3'
```

The site, against that server ([site/README.md](site/README.md)):

```sh
cd site && npm install && npm run data
npm run api -- 8791 &
npm run dev -- --port 4391
```

## Connect an agent

The server speaks MCP over Streamable HTTP at `/mcp`, with no login. It has four read-only
tools: `search`, `fetch`, `verify_quote` and `check_answer` (which audits every citation and
quotation in a draft answer).

```sh
claude mcp add --transport http safetypage http://127.0.0.1:8000/mcp
```

[docs/SERVER.md](docs/SERVER.md) has the settings, the JSON API, the container, and the steps
for adding a hosted server to claude.ai and ChatGPT.

## CitationBench

CitationBench asks an agent questions about what documents in the library say, and scores the
answer's citations: whether the cited pages are the right ones, whether each quotation is on
the page it cites, whether the agent actually opened what it cited, and what a correct answer
cost. Those checks are made by code. Whether a cited page supports the claim made about it is
judged by a model, and that number is reported separately with the judge's agreement with
people next to it. [citationbench/README.md](citationbench/README.md) has the measures, how
the questions are made and how to run it.

Where it stands: the harness, the scorers and the question pipeline work end to end. The
results in [`citationbench/results/`](citationbench/results/) are six smoke runs (Claude Code,
Codex and Antigravity agents) on four development questions over the fixture corpus. They show
that the pipeline runs and that the traces replay on the site. They are far too small to compare
models, and nothing has been run on the full library yet.

## Layout

```
src/safetypage/    the Python package
  ids, quote, licence, policy, corpus, snapshot, api, trace    the core library
  ingest/          source adapters and parsers; builds the working corpus from corpus/scope
  search/, build/  the keyword index, embeddings, the snapshot builder
  server/          the four tools over MCP, and the same functions as a JSON API
  bench/           CitationBench: tasks, agents, scorers, results
citationbench/     benchmark configurations, development questions, results and traces
corpus/            the inventory (what the library holds) and the status of the last ingest
site/              the reader, search, the checker, the replay view, the leaderboard (Astro)
schemas/           JSON Schemas for every wire contract, generated from the models
fixtures/corpus/   real, openly licensed documents used by the tests
tests/             unit, property and end-to-end tests
docs/              ARCHITECTURE.md (the design and the decisions behind it), SERVER.md
deploy/server/     the server's container
scripts/           check.sh (everything CI runs)
```

## Develop

```sh
uv sync --all-groups     # Python 3.13 and every dependency, from the lock file
scripts/check.sh         # everything CI runs: format, lint, types, schemas, fixtures, tests
cd site && npm test      # the site's type check, unit tests and end-to-end tests
```

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) is the design: ids and anchors, the citation
string and URL, the SQLite schema, the snapshot layout, the search interface, the tools, the
trace format, the licence tiers, and the decisions behind them.

## Licence

The code is under the [Apache License 2.0](LICENSE). Documents in `fixtures/corpus/` keep their
own licences, listed with attributions in
[fixtures/corpus/README.md](fixtures/corpus/README.md).
