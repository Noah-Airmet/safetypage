# The search server: one process serving one sealed snapshot, mounted read-only.
#
#   docker build -f deploy/server/Dockerfile -t safetypage-server .
#   docker run -p 8000:8000 \
#     -v /srv/safetypage/snapshots/2026.11.0:/snapshot:ro \
#     -v /srv/safetypage/ops:/ops \
#     -e SAFETYPAGE_BASE_URL=https://safetypage.example \
#     safetypage-server
#
# /ops holds ops.sqlite, the call log (the only state written). Set SAFETYPAGE_OPS_DB=none to
# keep no log. Behind Cloudflare or another proxy, set SAFETYPAGE_TRUST_PROXY=1 so rate limits
# key on the caller's address rather than the proxy's.

FROM python:3.13-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --group server --group search --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --group server --group search --no-editable

# The image that runs: Python and the environment, without uv or the build's layers.
FROM python:3.13-slim
COPY --from=build /app/.venv /app/.venv
WORKDIR /app

ENV SAFETYPAGE_SNAPSHOT=/snapshot \
    SAFETYPAGE_OPS_DB=/ops/ops.sqlite \
    PATH=/app/.venv/bin:$PATH

RUN mkdir -p /ops && chown nobody /ops
USER nobody
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["python", "-m", "safetypage.server", "--host", "0.0.0.0", "--port", "8000"]
