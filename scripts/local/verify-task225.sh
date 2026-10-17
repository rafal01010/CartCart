#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/private/tmp/cartcart-task225-uv-cache}"
ARTIFACT_DIR="${REPO_ROOT}/data/artifacts/task225"
mkdir -p "${ARTIFACT_DIR}"
cd "${REPO_ROOT}/apps/backend"
SOURCES=(
  app/agents/decision_sources.py app/schemas/decision_sources.py
  app/agents/research_selection.py app/agents/research_tools.py
  app/agents/research_guidance.py app/agents/context_management.py
  app/agents/request_compaction.py app/agents/live_general_shopping.py app/agents/live_comparison_decision.py
  app/agents/live_source_intelligence_manager.py app/agents/owner_research.py
  app/agents/live_youtube_review_intelligence.py app/agents/source_consultation.py
  app/agents/catalog.py app/db/repositories/results.py app/api/routes/results.py
  tests/test_task225_decision_sources.py tests/test_task225_shared_video.py
  tests/test_task225_projection.py tests/test_task225_catalog.py tests/test_task225_history.py
  tests/test_live_comparison_decision_agent.py tests/test_downstream_context_projection.py ../../scripts/local/inspect-task225-preservation.py
)
uv run --locked --offline ruff check "${SOURCES[@]}"
uv run --locked --offline python -m py_compile "${SOURCES[@]}"
uv run --locked --offline pytest -q tests/test_task225_decision_sources.py \
  tests/test_task225_shared_video.py tests/test_task225_projection.py tests/test_task225_catalog.py tests/test_task225_history.py \
  tests/test_live_comparison_decision_agent.py \
  tests/test_downstream_context_projection.py::test_video_metadata_is_shared_without_losing_claims_or_changed_metadata \
  tests/test_downstream_context_projection.py::test_real_sdk_receives_complete_comparison_and_verifier_graphs \
  --junitxml="${ARTIFACT_DIR}/offline-controls.junit.xml" -o junit_family=legacy
PYTHONPATH=. uv run --locked --offline python ../../data/artifacts/task225/replay-saved-selection.py
PYTHONPATH=. uv run --locked --offline python ../../scripts/local/inspect-task223-configuration.py > "${ARTIFACT_DIR}/configuration-after.json"
cmp "${ARTIFACT_DIR}/configuration-before.json" "${ARTIFACT_DIR}/configuration-after.json"
uv run --locked --offline python ../../scripts/local/inspect-task225-preservation.py
cd "${REPO_ROOT}/apps/frontend"
pnpm exec vitest run src/lib/results/result-view.test.ts -t 'Task 225'
pnpm exec svelte-kit sync
pnpm exec svelte-check --tsconfig ./tsconfig.json
pnpm exec playwright test --config playwright.task225-local.config.ts
cd "${REPO_ROOT}"
git diff --check
bash -n scripts/local/verify-task225.sh
