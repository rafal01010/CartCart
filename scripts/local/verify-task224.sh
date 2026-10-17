#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/private/tmp/cartcart-task224-uv-cache}"
ARTIFACT_DIR="${REPO_ROOT}/data/artifacts/task224"
mkdir -p "${ARTIFACT_DIR}"
cd "${REPO_ROOT}/apps/backend"
SOURCES=(
  app/agents/context_management.py app/agents/live_general_shopping.py
  app/agents/youtube_review_tools.py app/agents/live_youtube_review_intelligence.py
  app/agents/catalog.py tests/test_task224_finalization.py
  tests/test_task224_caption_focus.py ../../scripts/local/inspect-task224-cutoffs.py
)
uv run --locked --offline ruff check "${SOURCES[@]}"
uv run --locked --offline python -m py_compile "${SOURCES[@]}"
uv run --locked --offline pytest -q \
  tests/test_task224_finalization.py tests/test_task224_caption_focus.py \
  --junitxml="${ARTIFACT_DIR}/offline-controls.junit.xml" -o junit_family=legacy
PYTHONPATH=. uv run --locked --offline python ../../scripts/local/inspect-task224-cutoffs.py
PYTHONPATH=. uv run --locked --offline python ../../scripts/local/inspect-task223-configuration.py > "${ARTIFACT_DIR}/configuration-after.json"
cmp "${ARTIFACT_DIR}/configuration-before.json" "${ARTIFACT_DIR}/configuration-after.json"
