#!/usr/bin/env bash
# Everything CI checks, in the order CI checks it. Run it before pushing:
#   uv sync --all-groups && scripts/check.sh
set -euo pipefail
cd "$(dirname "$0")/.."

step() { printf '\n== %s\n' "$1"; }

step "invisible characters are written as escapes"
git ls-files -z '*.py' | xargs -0 uv run python scripts/escape_invisibles.py --check

step "format"
uv run ruff format --check .

step "lint"
uv run ruff check .

step "types"
uv run pyright

step "JSON Schemas are current"
uv run python -m onthepage.schemas --check

step "fixture bundles rebuild byte for byte"
uv run python fixtures/build.py --check

step "tests"
uv run pytest --cov=onthepage --cov-report=term --cov-fail-under=85 "$@"
