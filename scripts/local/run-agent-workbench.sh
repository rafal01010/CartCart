#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/apps/backend"

# shellcheck source=scripts/local/lifecycle-common.sh
source "${SCRIPT_DIR}/lifecycle-common.sh"

require_command "uv" "run the isolated agent workbench" "Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
require_file "${BACKEND_DIR}/pyproject.toml" "apps/backend/pyproject.toml is missing." "Run scripts/local/init-backend.sh first."

USE_SHELL_ENV=false
if [[ "${1:-}" == "--use-shell-env" ]]; then
  USE_SHELL_ENV=true
  shift
fi
source_env_file "${BACKEND_DIR}/.env" "${USE_SHELL_ENV}"

cd "${BACKEND_DIR}"
uv run python -m app.tools.agent_workbench "$@"
