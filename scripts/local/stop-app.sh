#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/apps/backend"
FRONTEND_DIR="${REPO_ROOT}/apps/frontend"

# shellcheck source=scripts/local/lifecycle-common.sh
source "${SCRIPT_DIR}/lifecycle-common.sh"

source_env_file "${BACKEND_DIR}/.env"
BACKEND_DATA_DIR="${CARTCART_DATA_DIR:-${REPO_ROOT}/data}"
BACKEND_RUN_DIR="${CARTCART_RUN_DIR:-${BACKEND_DATA_DIR}/run}"

source_env_file "${FRONTEND_DIR}/.env"
FRONTEND_DATA_DIR="${CARTCART_DATA_DIR:-${REPO_ROOT}/data}"
FRONTEND_RUN_DIR="${CARTCART_RUN_DIR:-${FRONTEND_DATA_DIR}/run}"

stop_managed_service "frontend" "${FRONTEND_RUN_DIR}/frontend.pid"
stop_managed_service "backend" "${BACKEND_RUN_DIR}/backend.pid"

echo "CartCart local app stopped."
