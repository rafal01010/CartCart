#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/apps/backend"
OUTPUT_PATH="${1:-${REPO_ROOT}/docs/openapi.json}"

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: uv is required to export OpenAPI." >&2
  echo "Install uv first: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

if [[ ! -f "${BACKEND_DIR}/pyproject.toml" ]]; then
  echo "Error: apps/backend/pyproject.toml is missing." >&2
  echo "Run scripts/local/init-backend.sh first." >&2
  exit 1
fi

cd "${BACKEND_DIR}"
uv run python -m app.tools.export_openapi "${OUTPUT_PATH}"
