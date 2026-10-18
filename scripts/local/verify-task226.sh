#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/private/tmp/cartcart-task225-uv-cache}"
ARTIFACT_DIR="${REPO_ROOT}/data/artifacts/task226"
mkdir -p "${ARTIFACT_DIR}"
cd "${REPO_ROOT}/apps/backend"
SOURCES=(
  app/agents/research_guidance.py app/agents/live_general_shopping.py
  app/agents/live_comparison_decision.py app/agents/context_management.py
  app/agents/decision_sources.py app/agents/catalog.py app/schemas/analysis.py
  app/orchestration/shopping_runs.py
  tests/test_task226_policy.py tests/test_task226_options.py tests/test_task226_catalog.py
  tests/test_task225_history.py
  ../../scripts/local/inspect-task226-preservation.py
)
uv run --locked --offline ruff check "${SOURCES[@]}"
uv run --locked --offline python -m py_compile "${SOURCES[@]}"
uv run --locked --offline pytest -q tests/test_task226_policy.py tests/test_task226_options.py \
  tests/test_task226_catalog.py \
  tests/test_task225_history.py::test_compaction_does_not_erase_a_candidates_only_useful_support \
  --junitxml="${ARTIFACT_DIR}/offline-controls.junit.xml" -o junit_family=legacy
PYTHONPATH=. uv run --locked --offline python ../../scripts/local/inspect-task223-configuration.py > "${ARTIFACT_DIR}/configuration-after.json"
cmp "${ARTIFACT_DIR}/configuration-before.json" "${ARTIFACT_DIR}/configuration-after.json"
uv run --locked --offline python ../../scripts/local/inspect-task226-preservation.py
cd "${REPO_ROOT}/apps/frontend"
pnpm exec tsc --ignoreConfig --noEmit --strict --skipLibCheck --target es2022 \
  --module nodenext --moduleResolution nodenext --types node \
  tests/e2e/task226-local-options.spec.ts playwright.task226-local.config.ts
pnpm exec playwright test --config playwright.task226-local.config.ts
cd "${REPO_ROOT}"
git diff --check
bash -n scripts/local/verify-task226.sh
