# On the Page

A complete, page-cited library of the AI safety record, built for people and for AI agents:
interpretability, alignment, evals and model welfare research; frontier-lab system cards, model
cards and safety frameworks; evaluation reports; and government AI guidance.

Every search result opens an exact page or paragraph. Every citation names a document, a
version and a place in it, and can be checked against that place by code. We check that the
page says it, and show you the page.

*On the Page is a working name.*

## Status

This repository holds the foundation: the core library that every other part imports, its
tests, and the design the rest is built against. The search index, the MCP server, the site
and the benchmark (PageCite) are being built on top of it.

- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** is the design: ids and anchors, the citation
  string and URL, the SQLite schema, the snapshot layout, the search interface, the tools, the
  trace format, the licence tiers, and the decisions behind them.

## What a citation is

```
arxiv:2305.15324/v2/p6                               document / version / anchor
https://<host>/d/arxiv/2305.15324/v2/p6              the same thing, as a link
```

`p6` is a PDF page. `b12` is a paragraph of a document that has no pages. A citation always
names a version, because pages move when a paper is revised.

## Checking a quote

```python
from onthepage.quote import verify_quote

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

Against a stored document, with the citation as the scope:

```python
from pathlib import Path
from onthepage.bundle import load_bundles
from onthepage.corpus import Corpus

corpus = Corpus.memory()
load_bundles(corpus, Path("fixtures/corpus/bundles"))  # the checked-in fixture corpus

check = corpus.verify_quote(
    "Model evaluation is the only tool available for AI risk assessment",
    "arxiv:2305.15324/v2/p6",
)
check.verdict  # 'near_miss': the page says "is not the only tool"
check.segments[0].diff  # [QuoteDiff(op='insert', quote='', source='not')]

corpus.verify_quote(
    "model evaluation is one of the main tools we have for AI risk assessment",
    "arxiv:2305.15324/v2/p3",
).locations[0].cite  # 'arxiv:2305.15324/v2/p6'  (verdict: 'elsewhere')
```

## Licence tiers

Openly licensed documents (CC BY, CC BY-SA, CC0, public domain, UK Open Government Licence)
are hosted in full. Everything else, and anything whose licence is unknown, is search, short
snippets, quote checking and a link to the source at the page. The tier is computed by one
function from a recorded licence fact with its evidence, and it is enforced inside the library,
not left to callers.

## Layout

```
src/onthepage/     the core library (ids, quote, licence, policy, corpus, snapshot, api, trace)
tests/             unit, property and end-to-end tests
fixtures/corpus/   real, openly licensed documents used by the tests
schemas/           JSON Schemas for every wire contract, generated from the models
docs/              the architecture
scripts/           check.sh (everything CI runs)
```

## Develop

Needs [uv](https://docs.astral.sh/uv/).

```sh
uv sync --all-groups     # Python 3.13 and every dependency, from the lock file
uv run pytest            # the tests
scripts/check.sh         # everything CI runs: format, lint, types, schemas, fixtures, tests
```

The core library depends on `pydantic` and `rapidfuzz`, and on nothing else at run time.

## Licence

The code is under the [Apache License 2.0](LICENSE). Documents in `fixtures/corpus/` keep their
own licences, listed with attributions in
[fixtures/corpus/README.md](fixtures/corpus/README.md).
