#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
FRONTEND_DIR="${REPO_ROOT}/apps/frontend"
BACKEND_DIR="${REPO_ROOT}/apps/backend"
VITE_BIN="${FRONTEND_DIR}/node_modules/.bin/vite"

# shellcheck source=scripts/local/lifecycle-common.sh
source "${SCRIPT_DIR}/lifecycle-common.sh"

require_command "pnpm" "start the frontend" "Install pnpm or enable it with Corepack first: https://pnpm.io/installation"
require_file "${FRONTEND_DIR}/package.json" "apps/frontend/package.json is missing." "Run scripts/local/init-frontend.sh first."
require_file "${VITE_BIN}" "apps/frontend/node_modules/.bin/vite is missing." "Run scripts/local/sync-frontend.sh first."

source_env_file "${BACKEND_DIR}/.env"
source_env_file "${FRONTEND_DIR}/.env"

DATA_DIR="${CARTCART_DATA_DIR:-${REPO_ROOT}/data}"
RUN_DIR="${CARTCART_RUN_DIR:-${DATA_DIR}/run}"
LOG_DIR="${CARTCART_LOG_DIR:-${DATA_DIR}/logs}"
PID_FILE="${RUN_DIR}/frontend.pid"
LOG_FILE="${LOG_DIR}/frontend.log"
HOST="${CARTCART_FRONTEND_HOST:-127.0.0.1}"
PORT="${CARTCART_FRONTEND_PORT:-5173}"
BACKEND_HOST="${CARTCART_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${CARTCART_BACKEND_PORT:-8000}"
export PUBLIC_CARTCART_API_BASE_URL="${PUBLIC_CARTCART_API_BASE_URL:-http://${BACKEND_HOST}:${BACKEND_PORT}}"

args=(
  "${VITE_BIN}"
  dev
  --host "${HOST}"
  --port "${PORT}"
  --strictPort
)

start_managed_service "frontend" "${PID_FILE}" "${LOG_FILE}" "${args[@]}"
