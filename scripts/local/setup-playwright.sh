#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
FRONTEND_DIR="${REPO_ROOT}/apps/frontend"

if ! command -v pnpm >/dev/null 2>&1; then
  echo "Error: pnpm is required to set up Playwright." >&2
  echo "Install pnpm or enable it with Corepack first: https://pnpm.io/installation" >&2
  exit 1
fi

if [[ ! -f "${FRONTEND_DIR}/package.json" ]]; then
  echo "Error: apps/frontend/package.json is missing." >&2
  echo "Run scripts/local/init-frontend.sh first." >&2
  exit 1
fi

if [[ ! -x "${FRONTEND_DIR}/node_modules/.bin/playwright" ]]; then
  echo "Error: Playwright is not installed in apps/frontend/node_modules." >&2
  echo "Run scripts/local/sync-frontend.sh first, then rerun this script." >&2
  exit 1
fi

if (($# > 0)); then
  pnpm --dir "${FRONTEND_DIR}" run setup:playwright -- "$@"
else
  pnpm --dir "${FRONTEND_DIR}" run setup:playwright
fi
