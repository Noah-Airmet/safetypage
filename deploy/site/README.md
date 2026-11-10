# Deploying

Two origins. The addresses are written once, in [`site/deploy.env`](../../site/deploy.env).

| Origin | What it serves | Where it runs |
|---|---|---|
| `https://safetypage.noahairmet.com` | the static site: about 14,600 files, 194 MB, and one small worker for citation addresses | a Cloudflare Pages project |
| `https://api.safetypage.noahairmet.com` | search and quote checks (`/api/…`), MCP (`/mcp`, `/x/<surface>/mcp`), and the snapshot's public files (`/data/<snapshot id>/…`) | one machine, behind a Cloudflare tunnel |

The browser calls the API origin directly; the server answers cross-origin requests from
anywhere, and so does the file server.

## The API origin

The Python server does not serve files. [`deploy/server/compose.yaml`](../server/compose.yaml)
runs it beside a Caddy file server ([`Caddyfile`](../server/Caddyfile)) on one port:

```sh
SNAPSHOT_DIR=<snapshot dir> SNAPSHOT_ID=<its id, e.g. 2026.11.1> \
  docker compose -f deploy/server/compose.yaml up -d --build
# then point the tunnel at http://127.0.0.1:8080
```

- `/data/<snapshot id>/…` is the snapshot's `public/` directory: `docs/` (75 MB), `text/`
  (2 GB), `pages/` (page images) and `files/` (the open PDFs, 12 GB). The snapshot's id is in
  the path because a sealed snapshot never changes: every file is sent with
  `Cache-Control: public, max-age=31536000, immutable`, so Cloudflare and browsers keep it. A
  new snapshot is a new path, mounted beside the old one. Nothing outside `public/` is reachable.
- Everything else goes to the search server, which reads the snapshot's `corpus.sqlite` (4 GB)
  and `lexical/` (0.3 GB). It used 350 MB of memory serving this snapshot locally.
- The site's build must name the same snapshot: it reads the id from the snapshot's
  `manifest.json` and writes `…/data/<snapshot id>` into the pages.

## The site

```sh
uv run python -m safetypage.server --snapshot <snapshot dir> --port 8000 &   # the build asks it questions
cd site && npm ci
SAFETYPAGE_PUBLIC_DIR=<snapshot dir>/public SAFETYPAGE_API=http://127.0.0.1:8000 npm run build:deploy
npx wrangler pages deploy dist --project-name safetypage
```

`npm run build:deploy` is the one command that builds the static site for the two origins in
`deploy.env`. `SAFETYPAGE_API` may also be the deployed API origin, once it is up.

**The edge rule.** `dist/_worker.js` (from [`site/edge/worker.js`](../../site/edge/worker.js))
runs for `/d/*` only (`dist/_routes.json`); every other address is a file.

- `/d/<ns>/<id>/<version>/<anchor>` gets the reader's shell, `/reader.html`, which draws the
  page in the browser. The worker fetches the document's card from the API origin (cached at
  the edge for a day) to write the title, description and preview image into the shell, so a
  citation link unfurls as "Shevlane et al. 2023, p. 6" with the cited page as its image. If
  the document or version does not exist, 404. If the API origin is slow or down, the plain
  shell is sent.
- `/d/<ns>/<id>/<version>` gets the document's record page when that version is the latest.
- `/d/<ns>/<id>` is a file, passed through.

Pages allows 20,000 files a deployment on the free plan; the build has about 14,600. Worker
requests count against the free plan's 100,000 a day, and only `/d/*` addresses use them.

## Checked, and not yet

- The Pages worker was run with `wrangler pages dev` against a real build: record pages,
  citation addresses (with title, canonical address and page image written in), ranges,
  missing documents and versions (404), and the API origin switched off (plain shell, 200).
- The Caddyfile was run with a local Caddy in front of the real server and snapshot: files with
  the cache and cross-origin headers, `..` paths refused, `/api`, `/mcp` and `/health` passed on.
- A build for two local origins was opened in a browser on 122 pages at desktop and phone
  width with no failed request.
- Not done: `docker compose` itself has not been run (no Docker on the build machine), nothing
  is deployed, and the tunnel is not set up.
