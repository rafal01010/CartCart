#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/apps/backend"

if [[ "${1:-}" != "--yes" ]]; then
  echo "Usage: scripts/local/reset-db.sh --yes [--use-shell-env]" >&2
  echo "Deletes the configured local SQLite database and sidecar files." >&2
  exit 2
fi

# shellcheck source=scripts/local/lifecycle-common.sh
source "${SCRIPT_DIR}/lifecycle-common.sh"
parse_env_options "${@:2}"
source_env_file "${BACKEND_DIR}/.env" "${USE_SHELL_ENV}"

DATA_DIR="${CARTCART_DATA_DIR:-${REPO_ROOT}/data}"
DATABASE_PATH="${CARTCART_DATABASE_PATH:-${DATA_DIR}/cartcart.sqlite3}"

case "${DATABASE_PATH}" in
  /*) ;;
  *) DATABASE_PATH="${REPO_ROOT}/${DATABASE_PATH}" ;;
esac

rm -f \
  "${DATABASE_PATH}" \
  "${DATABASE_PATH}-journal" \
  "${DATABASE_PATH}-shm" \
  "${DATABASE_PATH}-wal"

echo "Deleted local SQLite database files for ${DATABASE_PATH}"
echo "Recreate the schema with: cd apps/backend && uv run alembic -c alembic.ini upgrade head"
