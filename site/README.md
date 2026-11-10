# The site

The reader, the record pages, search, the checker, the replay view and the CitationBench
leaderboard. Astro, static output, React only on the three interactive parts (search, the
checker, the replay). Hand-written CSS on the tokens in
[`src/styles/site.css`](src/styles/site.css); light and dark follow the system setting.

## Run it

```sh
cd site
npm install
npm run data              # library data from the fixture corpus, into public/data/ (about 30 s)
npm run api -- 8791 &     # the search server on the fixture corpus (docs/SERVER.md)
npm run dev -- --port 4391
```

`npm run build` writes the static site to `dist/`. `npm test` runs the type check, the unit
tests, and the end-to-end and accessibility tests against a fresh build.

## What it reads

| What | From | Setting |
|---|---|---|
| Document cards, unit text with layout, page images | a snapshot's `public/` tree ([ARCHITECTURE §7](../docs/ARCHITECTURE.md#7-storage-on-disk-blobs-and-snapshots)), at build time and in the browser | `SAFETYPAGE_PUBLIC_DIR` (build, default `public/data`), `PUBLIC_DATA_BASE` (browser, default `/data`) |
| Search, quote checks, answer audits | the server's JSON API | `PUBLIC_API_BASE` (default: same origin; in dev `/api` is proxied to `SAFETYPAGE_API`) |
| Leaderboard | CitationBench's results files, one per run | `SAFETYPAGE_RESULTS_DIR` (default `../citationbench/results`) |
| Replays | CitationBench's traces, one per sample | `SAFETYPAGE_TRACES_DIR` (default `../citationbench/traces`) |
| The MCP address shown on Connect | | `PUBLIC_MCP_URL` (default `<site>/mcp`) |
| The site's own address, for links and preview cards | | `SITE_URL` |

`scripts/make_data.py` builds the `public/` layout from the fixture corpus with the core
library, so the site has pages to show before a real snapshot exists. Point `SAFETYPAGE_PUBLIC_DIR`
at a sealed snapshot's `public/` and nothing else changes.

## Routes

| Route | What |
|---|---|
| `/` | a checked citation and a rejected one on a real page, then search |
| `/d/<ns>/<id>[/<version>]` | the record: catalogue entry, outline, versions, licence and its evidence, how to cite |
| `/d/<ns>/<id>/<version>/<anchor>[?q=<quote>]` | the reader at a page or paragraph, with the quote highlighted |
| `/search?query=` | the concordance; every result is a citation |
| `/check[?text=]` | paste a paragraph; each citation comes back Verified, Page only or Rejected |
| `/r/<trace id>[?step=N]` | a research run played back from its trace |
| `/q/<id>` | one quote check with its page (built for the landing examples and every quoted citation in a trace) |
| `/citationbench`, `/citationbench/runs/<run id>` | the leaderboard and a run's questions |
| `/library`, `/connect`, `/about` | the catalogue, how to connect an agent, how it works |
| `/og/…png` | preview cards for a document, a page, a quote check and a replay |

## How the pieces work

- **Reader.** A PDF page is an image with a transparent text layer positioned from the page's
  word boxes ([`src/scripts/reader.ts`](src/scripts/reader.ts)), so selection and copy are the
  browser's own. The highlight is drawn from the same boxes. An HTML document is re-set from
  its blocks with `¶` anchors. A link-only document shows a card that opens the source at the
  page. No PDF engine is loaded.
- **Finding a quote on a page** ([`src/lib/quote.ts`](src/lib/quote.ts)) places words for the
  highlight. It is not a verdict; verdicts come from the server's `verify_quote`.
- **Replay** ([`src/lib/replay.ts`](src/lib/replay.ts)). The state at a step is a pure function
  of the events up to it, so scrubbing either way is the same computation.
- **Preview cards** ([`src/lib/og.ts`](src/lib/og.ts)) are drawn at build time with Satori and
  resvg.

## Checks

- `npm test`: `tsc`, Vitest ([`tests/lib.test.ts`](tests/lib.test.ts)), Playwright with axe
  ([`tests/site.e2e.ts`](tests/site.e2e.ts)) in light and dark and at phone width.
- `ui-check` (Noah's tool, [`ui-check.config.mjs`](ui-check.config.mjs)) measures alignment,
  sizes and contrast on the main screens against saved screenshots, with the dev servers
  running as above. After a change you meant: `ui-check update`.

## Static hosting, at full scale

Every page of every document is prerendered today, which is right for a few hundred documents.
The reader page is the same shell for every anchor of a version, so at hundreds of thousands
of pages the per-anchor routes (and their preview cards) can be served by one edge function
that fills in the anchor, with the record pages still static. A citation to a range
(`…/p6-p8`) is handled on the 404 page, which opens the reader at the first page.
