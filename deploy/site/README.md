# Deploying

Two origins. The addresses are written once, in [`site/deploy.env`](../../site/deploy.env).

| Origin | What it serves | Where it runs |
|---|---|---|
| `https://safetypage.noahairmet.com` | the static site: about 14,600 files, 194 MB, and one small worker for citation addresses | a Cloudflare Pages project |
| `https://safetypage-api.noahairmet.com` | search and quote checks (`/api/…`), MCP (`/mcp`, `/x/<surface>/mcp`), and the snapshot's public files (`/data/<snapshot id>/…`) | one machine, behind a Cloudflare tunnel |

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
  `Cache-Control: public, max-age=31536000, immutable`, so Cloudflare and browsers keep it (a
  miss is sent `no-store`). Cloudflare only keeps some file types by default, and JSON is not
  one, so the zone has one cache rule: host is the API origin and the path starts with
  `/data/`, eligible for cache. Only the live snapshot's `public/` is mounted; nothing outside
  it is reachable.
- Everything else goes to the search server, which reads the snapshot's `corpus.sqlite` (4 GB)
  and `lexical/` (0.3 GB). It used 350 MB of memory serving this snapshot locally.
- The snapshot is mounted read-only except its `lexical/` directory: Tantivy takes a lock
  file to open an index, so that directory must be writable by the container's user (uid
  65534).
- The two settings can sit in `deploy/server/.env` (untracked) instead of the command line.
- The hostname is one label under the zone (`safetypage-api`, not `api.safetypage`) because
  Cloudflare's free certificate covers `*.noahairmet.com` and nothing deeper.
- The site's build must name the same snapshot: it reads the id from the snapshot's
  `manifest.json` and writes `…/data/<snapshot id>` into the pages.

## A new snapshot

```sh
deploy/redeploy.sh data/snapshots/<snapshot id>
```

[`redeploy.sh`](../redeploy.sh) does three things, each of which can be run by hand:

1. copies the snapshot's `manifest.json`, `corpus.sqlite`, `lexical/` and `public/` to the
   server with `rsync` (rate-capped; files identical to the live snapshot's are hard-linked
   rather than sent);
2. on the server, pulls this repository, writes `deploy/server/.env` and runs
   `docker compose up -d --build --wait`, then waits for `/health` to name the new snapshot;
3. builds the site against the same snapshot and uploads it to the Pages project.

It reads the server's ssh name and paths from the environment or from `deploy/.env`
(untracked); the top of the script lists them. Between steps 2 and 3, a minute or so, the
published site still names the old snapshot's files, which are no longer mounted. Old
snapshot directories stay on the server until they are removed by hand.

## The site

```sh
cd site && npm ci
SAFETYPAGE_PUBLIC_DIR=<snapshot dir>/public SAFETYPAGE_API=https://safetypage-api.noahairmet.com \
  npm run build:deploy
npx wrangler pages deploy dist --project-name safetypage --branch main
```

`npm run build:deploy` is the one command that builds the static site for the two origins in
`deploy.env`. The build asks a search server on the same snapshot a few questions
(`SAFETYPAGE_API`): the deployed API origin, or a local
`uv run python -m safetypage.server --snapshot <snapshot dir>`.

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
