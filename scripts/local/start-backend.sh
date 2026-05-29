#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/apps/backend"

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: uv is required to start the backend." >&2
  echo "Install uv first: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

if [[ ! -f "${BACKEND_DIR}/pyproject.toml" ]]; then
  echo "Error: apps/backend/pyproject.toml is missing." >&2
  echo "Run scripts/local/init-backend.sh first." >&2
  exit 1
fi

if [[ -f "${BACKEND_DIR}/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${BACKEND_DIR}/.env"
  set +a
fi

HOST="${CARTCART_BACKEND_HOST:-127.0.0.1}"
PORT="${CARTCART_BACKEND_PORT:-8000}"
RELOAD="${CARTCART_BACKEND_RELOAD:-true}"

args=(
  uv
  run
  --project "${BACKEND_DIR}"
  uvicorn
  --app-dir "${BACKEND_DIR}"
  app.main:create_app
  --factory
  --host "${HOST}"
  --port "${PORT}"
)

if [[ "${RELOAD}" == "true" ]]; then
  args+=(--reload)
fi

exec "${args[@]}"
