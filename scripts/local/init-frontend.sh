#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
FRONTEND_DIR="${REPO_ROOT}/apps/frontend"

SV_TEMPLATE="minimal"
SV_TYPES="ts"

if ! command -v node >/dev/null 2>&1; then
  echo "Error: Node.js is required to initialize the frontend." >&2
  echo "Install Node.js first: https://nodejs.org/" >&2
  exit 1
fi

if ! command -v pnpm >/dev/null 2>&1; then
  echo "Error: pnpm is required to initialize the frontend." >&2
  echo "Install pnpm or enable it with Corepack first: https://pnpm.io/installation" >&2
  exit 1
fi

mkdir -p "${FRONTEND_DIR}"

if [[ -f "${FRONTEND_DIR}/package.json" ]]; then
  echo "Using existing frontend project metadata at apps/frontend/package.json"
else
  pnpm dlx sv create "${FRONTEND_DIR}" \
    --template "${SV_TEMPLATE}" \
    --types "${SV_TYPES}" \
    --no-add-ons \
    --no-install \
    --no-dir-check
fi

if [[ -f "${FRONTEND_DIR}/.gitkeep" && -f "${FRONTEND_DIR}/package.json" ]]; then
  rm "${FRONTEND_DIR}/.gitkeep"
fi

(
  cd "${FRONTEND_DIR}"
  pnpm install

  if ! node -e "const pkg = require('./package.json'); process.exit(pkg.devDependencies?.['@types/node'] ? 0 : 1);"; then
    pnpm add --save-dev @types/node
  fi
)

echo "Frontend dependencies installed at apps/frontend/node_modules"
echo "Run the SvelteKit dev server with: pnpm --dir apps/frontend dev"
