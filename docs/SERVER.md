# The search server

The four tools (`search`, `fetch`, `verify_quote`, `check_answer`) over MCP for agents, and the
same functions as a JSON API for the site. Code in
[`src/safetypage/server/`](../src/safetypage/server/), tests in
[`tests/server/`](../tests/server/), design in [ARCHITECTURE.md §9](ARCHITECTURE.md#9-the-tools).

## Run it

```sh
uv sync --all-groups
uv run python -m safetypage.server --fixtures                  # the fixture corpus, port 8000
uv run python -m safetypage.server --snapshot <dir>            # one sealed snapshot
uv run python -m safetypage.server --data <root>               # every snapshot under <root>/snapshots
```

| Setting | Flag / variable | Default |
|---|---|---|
| Public origin for citation URLs | `--base-url` / `SAFETYPAGE_BASE_URL` | `http://<host>:<port>` |
| Where `public/` is served (page image links) | `SAFETYPAGE_STATIC_URL` | the base URL |
| Call log | `SAFETYPAGE_OPS_DB` (`none` for no log) | `<data>/ops.sqlite`, or none |
| Accepted `Host` values (DNS-rebinding guard) | `SAFETYPAGE_ALLOWED_HOSTS` | localhost when bound to localhost; off otherwise |
| Rate limits key on the proxy's client header | `SAFETYPAGE_TRUST_PROXY=1` | off |
| Per-call time limit, seconds | `SAFETYPAGE_TIMEOUT` | 10 |

A snapshot with a `lexical/` directory is searched by the search track's Tantivy backend
(`safetypage.search.open_backend(snapshot_dir)`); anything else, including the fixtures, by a
small in-memory backend (`safetypage.server.backend.MemoryBackend`) with the same grammar.

### Container

[`deploy/server/Dockerfile`](../deploy/server/Dockerfile): one process, one sealed snapshot
mounted read-only at `/snapshot`, the call log at `/ops/ops.sqlite`.

```sh
docker build -f deploy/server/Dockerfile -t safetypage-server .
docker run -p 8000:8000 -v <snapshot dir>:/snapshot:ro -v <ops dir>:/ops \
  -e SAFETYPAGE_BASE_URL=https://<host> -e SAFETYPAGE_TRUST_PROXY=1 safetypage-server
```

## Routes

| Route | What |
|---|---|
| `POST /mcp` | the default surface: stateless Streamable HTTP, JSON responses, no login |
| `POST /x/<surface>/mcp` | a surface variant (`short`, `no-verify`, `one-tool`) |
| `GET /api/search?query=…` | `SearchResponse` (the default surface's arm) |
| `GET /api/doc/<ns>/<id>[/<version>]` | `DocumentCard` |
| `GET /api/units/<ns>/<id>/<version>/<anchor>` | `list[UnitText]` |
| `POST /api/verify` (`VerifyQuoteRequest`) | `QuoteCheck` |
| `POST /api/check` (`{"text": …}`) | `AnswerAudit` |
| `/s/<snapshot>/api/…` | the same, pinned to one snapshot |
| `GET /health` | snapshots and surface ids served |

Errors: MCP returns a tool result with `isError: true` and a message saying what to do next; the
API returns `{"error": …}` with 404 (no such document, page or snapshot) or 400.

## Call it

```sh
curl 'localhost:8000/api/search?query=%22risk%20assessment%22&limit=3'
curl -X POST localhost:8000/api/verify -H 'content-type: application/json' \
  -d '{"quote": "Model evaluation is not the only tool available", "cite": "arxiv:2305.15324/v2/p6"}'
```

From Claude Code:

```sh
claude mcp add --transport http safetypage http://127.0.0.1:8000/mcp
```

From Python, with the MCP SDK:

```python
from mcp.client import Client

async with Client("http://127.0.0.1:8000/mcp") as client:
    result = await client.call_tool("search", {"query": "sandbagging"})
    result.content[0].text  # markdown, for the model
    result.structured_content  # safetypage.api.SearchResponse
    result.meta["safetypage"]  # ResponseMeta: server_version, surface_id, snapshot, arm, request_id
```

A benchmark harness sends `X-SafetyPage-Run: <run id>` (and `X-SafetyPage-Sample: <sample id>`) on
every request; those calls are logged in full in `ops.sqlite` (`tool_calls`). Calls without a run
id keep no arguments, no returned cites and no error text, and no IP address is ever written.

## Surfaces

A surface is a TOML file in
[`src/safetypage/server/surfaces/`](../src/safetypage/server/surfaces/) naming the tools, the
description style, the retrieval arm and the snapshot; descriptions are Markdown files in
`surfaces/descriptions/`. Adding a variant is adding a file:

```toml
# surfaces/no-check.toml  →  served at /x/no-check/mcp
extends = "default"
tools = ["search", "fetch", "verify_quote"]
```

`surface_id` (`default@c1a7f2`) hashes the resolved config and every description file it uses,
so any wording change is a new id. A surface whose arm or snapshot is not loaded is skipped with a
warning.

## Operating in public

- Per-call time limit (10 s, including waiting for a worker) and four worker threads.
- Results are budgeted: `fetch` to `max_tokens` (default 6,000, at most 16,000) with a note on
  how to continue, markdown capped at 60,000 characters, request bodies at 128 KB, quotes at 2,000
  characters, answers at 40,000.
- Rate limit: a token bucket per (address, client family). claude.ai and ChatGPT call from their
  own servers, so they get a separate, much larger allowance (3,000 a minute against 120) instead
  of putting all their users in one small bucket. Anthropic publishes its egress ranges
  (<https://platform.claude.com/docs/en/api/ip-addresses>) if a tighter rule is ever needed.
- Document text in results is fenced as `<source_text cite="…">…</source_text>` and the server
  instructions say it is quoted material, not instructions.
- Licence tiers are enforced by the core library: link-only documents return the record, the
  outline, short excerpts and a `source_url` that opens the page at the source, never page text.

## Add it as a connector

Both need the server on a public HTTPS URL; the MCP endpoint is `https://<host>/mcp`.

**claude.ai** (Free plans get one custom connector; Pro, Max, Team and Enterprise more). Claude
connects from Anthropic's cloud, so the URL must be reachable from the public internet.

1. Open **Customize → Connectors** (<https://claude.ai/customize/connectors>).
2. Click **+ Add**, then **Add custom connector**.
3. Name it `SafetyPage` and enter `https://<host>/mcp`. Click **Continue**.
4. Under **Authentication**, choose **No sign in**. Leave **Request headers** empty. Click
   **Add**.
5. In a chat, click **+** (lower left) → **Connectors** and turn SafetyPage on.

On a Team or Enterprise plan an Owner adds it first under **Organization settings → Connectors**
→ **Add** → **Custom** → **Web**, with the same steps; members then find it under **Customize →
Connectors** and click **Connect**. A surface variant is added the same way with its own URL,
e.g. `https://<host>/x/short/mcp`.

**ChatGPT** (paid plans; workspace policy may restrict custom servers).

1. Open **Plugins** (<https://chatgpt.com/plugins>).
2. Click **+**, then **Add custom MCP server**.
3. Enter the name `SafetyPage` and a one-line description.
4. Under **Connection**, enter `https://<host>/mcp`.
5. Set authentication to none, read the risk warning and select **I understand and want to
   continue**.
6. Select **Create as a plugin**, check the four tools it lists, and install it.
7. In a new conversation, type `@` and pick SafetyPage.

After a change to tool names, descriptions or schemas, open the server at
<https://chatgpt.com/plugins> and select **Refresh**. `search` and `fetch` follow OpenAI's
contract (`id`, `title`, `url` on every hit), which is what ChatGPT builds citations from.

## Tests

```sh
uv run pytest tests/server                                         # everything but the suite
SAFETYPAGE_CONFORMANCE=1 uv run pytest tests/server/test_conformance.py   # the official MCP
                                                                   # conformance scenarios (needs npx)
```

The conformance test runs the scenarios that apply to a tools-only server (initialize, ping,
tools-list, DNS-rebinding protection). The rest of that suite calls its own reference tools,
resources and prompts.
