#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/apps/backend"

PYTHON_VERSION="3.12"
PROJECT_NAME="cartcart-backend"
PROJECT_DESCRIPTION="CartCart backend service."

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: uv is required to initialize the backend environment." >&2
  echo "Install uv first: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

mkdir -p "${BACKEND_DIR}"

if [[ ! -f "${BACKEND_DIR}/pyproject.toml" ]]; then
  uv init \
    --bare \
    --name "${PROJECT_NAME}" \
    --description "${PROJECT_DESCRIPTION}" \
    --vcs none \
    --python "${PYTHON_VERSION}" \
    "${BACKEND_DIR}"
else
  echo "Using existing backend project metadata at apps/backend/pyproject.toml"
fi

if [[ ! -f "${BACKEND_DIR}/.python-version" ]]; then
  uv --directory "${BACKEND_DIR}" python pin "${PYTHON_VERSION}"
fi

"${SCRIPT_DIR}/sync-backend.sh"
