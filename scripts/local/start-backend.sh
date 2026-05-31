#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/apps/backend"
UVICORN_BIN="${BACKEND_DIR}/.venv/bin/uvicorn"

# shellcheck source=scripts/local/lifecycle-common.sh
source "${SCRIPT_DIR}/lifecycle-common.sh"

require_command "uv" "start the backend" "Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
require_file "${BACKEND_DIR}/pyproject.toml" "apps/backend/pyproject.toml is missing." "Run scripts/local/init-backend.sh first."
require_file "${UVICORN_BIN}" "apps/backend/.venv/bin/uvicorn is missing." "Run scripts/local/sync-backend.sh first."

source_env_file "${BACKEND_DIR}/.env"

DATA_DIR="${CARTCART_DATA_DIR:-${REPO_ROOT}/data}"
RUN_DIR="${CARTCART_RUN_DIR:-${DATA_DIR}/run}"
LOG_DIR="${CARTCART_LOG_DIR:-${DATA_DIR}/logs}"
PID_FILE="${RUN_DIR}/backend.pid"
LOG_FILE="${LOG_DIR}/backend.log"
HOST="${CARTCART_BACKEND_HOST:-127.0.0.1}"
PORT="${CARTCART_BACKEND_PORT:-8000}"
RELOAD="${CARTCART_BACKEND_RELOAD:-true}"

args=(
  "${UVICORN_BIN}"
  --app-dir "${BACKEND_DIR}"
  app.main:create_app
  --factory
  --host "${HOST}"
  --port "${PORT}"
)

if [[ "${RELOAD}" == "true" ]]; then
  args+=(--reload)
fi

start_managed_service "backend" "${PID_FILE}" "${LOG_FILE}" "${args[@]}"
