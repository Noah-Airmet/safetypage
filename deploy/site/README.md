# Deploying the site

Three things are served, and they can be on one hostname.

| What | Where it comes from | Where it goes |
|---|---|---|
| The static site | `site/dist/` after the build ([site/README.md](../../site/README.md#on-the-real-library)): about 14,700 files, 196 MB | any static host |
| The library's public files | the snapshot's `public/` tree: `docs/` (75 MB), `text/` (2 GB) and `pages/` (30 GB of page images), served under `/data` | object storage |
| Search, quote checks, MCP | the server container ([docs/SERVER.md](../../docs/SERVER.md#container)) with the sealed snapshot mounted read-only: `corpus.sqlite` (4 GB) and `lexical/` (0.3 GB); it used 350 MB of memory serving this snapshot locally | anything that runs a container, behind HTTPS |

`public/files/` (the source PDFs, 12 GB) is not read by the site and need not be uploaded.

## The edge rule

A static host needs one rule: a page or paragraph address, `/d/<ns>/<id>/<version>/<anchor>`,
has no file and is answered with `/reader/index.html`, which draws the page in the browser.
[`worker.js`](worker.js) is that rule for Cloudflare, about 60 lines:

- `/d/<ns>/<id>/<version>/<anchor>`: the reader's shell with the document's card and its title,
  description and preview image written in (so a citation link has a real preview); 404 if the
  document or version is not in the library.
- `/d/<ns>/<id>/<version>`: the document's record page, when that version is the latest.
- `/data/…`: the public files, from the R2 bucket bound as `DATA`.
- `/api/…`, `/mcp`, `/x/…`: passed to the search server at `API_ORIGIN`, so the site, the API
  and the MCP endpoint share one origin and the Connect page's address is `https://<host>/mcp`.

Record pages and everything else are plain files and never run the Worker.

## Cloudflare, step by step

```sh
# 1. the public files, once per snapshot (rclone configured for R2)
rclone copy <snapshot dir>/public r2:safetypage-data --exclude 'files/**' --transfers 32

# 2. the site, built against that snapshot with its server running (site/README.md)
cd site && SAFETYPAGE_PUBLIC_DIR=<snapshot dir>/public SAFETYPAGE_API=http://127.0.0.1:8000 \
  SITE_URL=https://<host> npm run build

# 3. the Worker and the files: set API_ORIGIN and the bucket name in wrangler.jsonc first
cd ../deploy/site && npx wrangler deploy
```

The build has 14,703 files, under the 20,000 a free Workers plan allows per deployment; a
paid plan allows 100,000. Another host needs the same three things: the rewrite above
(Netlify and Vercel both express it as a rewrite rule), `/data` pointed at the bucket, and
`/api` and `/mcp` proxied to the server. If the API is on its own hostname instead, build
with `PUBLIC_API_BASE=https://<api host>` and `PUBLIC_MCP_URL=https://<api host>/mcp`; the
server already answers cross-origin requests.

## Checked, and not yet

The Worker was run locally with `wrangler dev` against a real build and real objects in a
local R2 bucket: every route above answered as described. Nothing has been deployed to
Cloudflare, and the R2 upload has not been run.
