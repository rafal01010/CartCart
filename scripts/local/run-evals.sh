#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: uv is required to run local evals." >&2
  echo "Install uv and run scripts/local/sync-backend.sh first." >&2
  exit 1
fi

# Do not source .env or initialize the app's live providers/telemetry.
cd "${REPO_ROOT}/apps/backend"
uv run --locked --offline python -m app.tools.run_evals "$@"
