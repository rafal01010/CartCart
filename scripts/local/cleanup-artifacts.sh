#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/apps/backend"

if [[ "${1:-}" != "--yes" ]]; then
  echo "Usage: scripts/local/cleanup-artifacts.sh --yes" >&2
  echo "Deletes local artifact files according to CARTCART_*_RETENTION_DAYS." >&2
  exit 2
fi

if [[ -f "${BACKEND_DIR}/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${BACKEND_DIR}/.env"
  set +a
fi

DATA_DIR="${CARTCART_DATA_DIR:-${REPO_ROOT}/data}"
ARTIFACT_DIR="${CARTCART_ARTIFACT_DIR:-${DATA_DIR}/artifacts}"

case "${ARTIFACT_DIR}" in
  /*) ;;
  *) ARTIFACT_DIR="${REPO_ROOT}/${ARTIFACT_DIR}" ;;
esac

cleanup_dir() {
  local relative_dir="$1"
  local retention_days="$2"
  local target_dir="${ARTIFACT_DIR}/${relative_dir}"

  if [[ ! -d "${target_dir}" ]]; then
    return
  fi

  if [[ "${retention_days}" == "0" ]]; then
    find "${target_dir}" -type f -delete
  else
    find "${target_dir}" -type f -mtime "+${retention_days}" -delete
  fi
  find "${target_dir}" -type d -empty -delete
}

cleanup_dir "raw-sources" "${CARTCART_RAW_SOURCE_SNAPSHOT_RETENTION_DAYS:-30}"
cleanup_dir "extracted-content" "${CARTCART_EXTRACTED_CONTENT_RETENTION_DAYS:-30}"
cleanup_dir "screenshots" "${CARTCART_SCREENSHOT_RETENTION_DAYS:-7}"
cleanup_dir "agent-outputs" "${CARTCART_AGENT_OUTPUT_RETENTION_DAYS:-30}"
cleanup_dir "traces" "${CARTCART_TRACE_RETENTION_DAYS:-14}"
cleanup_dir "evals" "${CARTCART_EVAL_ARTIFACT_RETENTION_DAYS:-30}"

echo "Cleaned local artifacts under ${ARTIFACT_DIR} according to retention settings."
