# The site

The reader, the record pages, search, the checker, the replay view and the CitationBench
leaderboard. Astro, static output, React only on the three interactive parts (search, the
checker, the replay). Hand-written CSS on the tokens in
[`src/styles/site.css`](src/styles/site.css); light and dark follow the system setting.

## Run it

On the fixture corpus that is checked in (six documents, no data to download):

```sh
cd site
npm install
npm run data              # library data from the fixture corpus, into .data/ (about 30 s)
npm run api -- 8791 &     # the search server on the fixture corpus (docs/SERVER.md)
npm run dev -- --port 4391
```

`npm test` runs the type check, the unit tests, and the end-to-end and accessibility tests
against a fresh build of the fixture corpus.

## On the real library

One command builds the static site against a sealed snapshot. It names the snapshot's
`public/` tree, a running search server on the same snapshot, and the site's public address:

```sh
uv run python -m safetypage.server --snapshot <snapshot dir> --port 8000 &
cd site
SAFETYPAGE_PUBLIC_DIR=<snapshot dir>/public SAFETYPAGE_API=http://127.0.0.1:8000 \
  SITE_URL=https://<host> npm run build
node scripts/serve.mjs dist 4395      # look at it: the static files, /data and /api as the host serves them
```

On snapshot `2026.11.0` (14,356 documents) the build takes 8 seconds and writes 14,703 files,
196 MB (13 KB a record page). None of the library's data is in
`dist/`: page images and text stay in the snapshot's `public/` tree and are served at `/data`.
[deploy/site/](../deploy/site/README.md) has what goes where on a host.

## What is built, and what the browser draws

| | How | Why |
|---|---|---|
| Landing, library, shelves, follow pages, About, Connect, CitationBench, replays, quote checks | prerendered | first paint with no script; a preview card each |
| A record page per document (`/d/<ns>/<id>`), and one per older version | prerendered, 14,415 pages | the catalogue entry, outline and licence are the document's link preview, and work with no script and no server |
| The reader at any page or paragraph (`/d/<ns>/<id>/<version>/<anchor>`) | one shell, [`reader.astro`](src/pages/reader.astro), drawn in the browser by [`reader.ts`](src/scripts/reader.ts) from the snapshot's static files | 688,000 addresses, one file |
| A shelf's full catalogue | `/catalogue/<shelf>.json`, fetched when a filter is used | a shelf page prints its newest 60; the largest catalogue is 934 KB before compression |
| Search, the checker, a link-only page's excerpt and quote check | the server's JSON API | they need the text, which is not published for link-only documents |

**The one rule a static host needs.** A page or paragraph address has no file of its own. The
host must answer `/d/<ns>/<id>/<version>/<anchor>` (pattern
`^/d/[^/]+/[^/]+/[vr]\d+/[pb]\d+(-[pb]?\d+)?$`) with `/reader/index.html`, status 200, and
`/d/<ns>/<id>/<version>` with `/d/<ns>/<id>/index.html` when the version has no page of its
own. [`deploy/site/worker.js`](../deploy/site/worker.js) does this on Cloudflare and also
writes the document's title and preview tags into the shell, so a citation link unfurls as
"Shevlane et al. 2023, p. 6"; [`scripts/serve.mjs`](scripts/serve.mjs) does it locally, and
`astro dev` has the same rule in [`astro.config.mjs`](astro.config.mjs). A citation to a range
(`…/p6-p8`) opens the reader at its first page.

## What it reads

| What | From | Setting |
|---|---|---|
| Document cards | a snapshot's `public/docs/` ([ARCHITECTURE §7](../docs/ARCHITECTURE.md#7-storage-on-disk-blobs-and-snapshots)), at build time | `SAFETYPAGE_PUBLIC_DIR` (default `.data`, the fixture tree) |
| The landing page's two quote checks, the follow pages' searches | the server's JSON API, at build time | `SAFETYPAGE_API` (default `http://127.0.0.1:8791`) |
| Cards, unit text with layout, page images | the same `public/` tree, in the browser | `PUBLIC_DATA_BASE` (default `/data`) |
| Search, quote checks, answer audits, link-only excerpts | the server's JSON API, in the browser | `PUBLIC_API_BASE` (default: same origin) |
| Leaderboard | CitationBench's results files, one per run | `SAFETYPAGE_RESULTS_DIR` (default `../citationbench/results`) |
| Replays | CitationBench's traces, one per sample | `SAFETYPAGE_TRACES_DIR` (default `../citationbench/traces`) |
| The MCP address shown on Connect | | `PUBLIC_MCP_URL` (default `<site>/mcp`) |
| The site's own address, for links and preview cards | | `SITE_URL` |

## Routes

| Route | What |
|---|---|
| `/` | a checked citation and a rejected one on a real page, search, the library's numbers |
| `/library`, `/library/<shelf>[?publisher=&kind=&year=&read=&q=]` | the shelves; one shelf, filtered in the browser |
| `/d/<ns>/<id>[/<version>]` | the record: catalogue entry, outline, versions, licence and its evidence, how to cite |
| `/d/<ns>/<id>/<version>/<anchor>[?q=<quote>]` | the reader at a page or paragraph, with the quote highlighted |
| `/search?query=[&collection=&kind=&org=&tier=&doc=]` | the concordance; every result is a citation |
| `/follow`, `/follow/<topic>` | one evaluation across the labs' system cards, by lab and date: a saved search ([`follow.ts`](src/lib/follow.ts)) |
| `/check[?text=]` | paste a paragraph; each citation comes back Verified, Page only or Rejected |
| `/r/<trace id>[?step=N]` | a research run played back from its trace |
| `/q/<id>` | one quote check with its page (built for the landing examples and every quoted citation in a trace) |
| `/citationbench`, `/citationbench/runs/<run id>` | the leaderboard and a run's questions |
| `/connect`, `/about` | how to connect an agent, how it works |
| `/og/…png` | preview cards for the site, a quote check and a replay |

## How the pieces work

- **Reader.** A PDF page is an image with a transparent text layer positioned from the page's
  word boxes ([`src/scripts/reader.ts`](src/scripts/reader.ts)), so selection and copy are the
  browser's own. The highlight is drawn from the same boxes. An HTML document is re-set from
  its blocks with `¶` anchors; a very long one draws 150 paragraphs either side of the cited
  one and loads the rest on request. No PDF engine is loaded.
- **A document read at its source** (three quarters of the library) gets the same record,
  outline and search results. Its reader page shows where the place falls in the outline, the
  opening words the library holds, a quote check against the library's copy, and a link that
  opens the source at the page (`#page=N`) or at the passage (a text fragment).
- **Finding a quote on a page** ([`src/lib/quote.ts`](src/lib/quote.ts)) places words for the
  highlight. It is not a verdict; verdicts come from the server's `verify_quote`.
- **Replay** ([`src/lib/replay.ts`](src/lib/replay.ts)). The state at a step is a pure function
  of the events up to it, so scrubbing either way is the same computation.
- **Preview cards** ([`src/lib/og.ts`](src/lib/og.ts)) are drawn at build time with Satori and
  resvg for the site, quote checks and replays. A document's card is the site's; an open PDF
  uses its own page image when `PUBLIC_DATA_BASE` is an absolute address or the Worker fills it in.

## Checks

- `npm test`: `tsc`, Vitest ([`tests/lib.test.ts`](tests/lib.test.ts)), Playwright with axe
  ([`tests/site.e2e.ts`](tests/site.e2e.ts)) in light and dark and at phone width.
- `ui-check` ([`ui-check.config.mjs`](ui-check.config.mjs)) measures alignment, sizes and
  contrast on the main screens of the real library against saved screenshots, with a real
  build served on port 4395. `UI_CHECK_SCHEME=dark ui-check` does the same in the dark theme.
  After a change you meant: `ui-check update`.
- `node scripts/shots.mjs <base> <dir>` saves a screenshot of each main screen at desktop
  and phone width in both themes.
