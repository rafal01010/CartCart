#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/private/tmp/cartcart-task223-uv-cache}"
ARTIFACT_DIR="${REPO_ROOT}/data/artifacts/task223"
mkdir -p "${ARTIFACT_DIR}"
cd "${REPO_ROOT}/apps/backend"
SOURCES=(
  app/agents/catalog.py app/agents/live_general_shopping.py
  app/agents/live_source_intelligence_manager.py app/agents/source_consultation.py
  app/agents/live_youtube_review_intelligence.py app/agents/owner_research.py
  app/agents/research_guidance.py app/agents/youtube_review_tools.py
  app/api/routes/results.py app/api/routes/runs.py
  app/db/models/results.py app/db/models/__init__.py
  app/db/repositories/results.py app/db/repositories/video_sources.py
  app/orchestration/shopping_runs.py app/providers/contracts.py
  app/providers/youtube_transcript.py app/schemas/search_sources.py
  app/services/runs.py app/services/video_evidence_creation.py
  alembic/versions/0005_result_source_projections.py
)
CONTROLS=(
  tests/test_task223_source_lifecycle.py tests/test_task223_owner_flow.py
  tests/test_task223_projection.py tests/test_task223_contracts.py
)
uv run --locked --offline ruff check "${SOURCES[@]}" "${CONTROLS[@]}" ../../scripts/local/inspect-task223-configuration.py
uv run --locked --offline python -m py_compile "${SOURCES[@]}" "${CONTROLS[@]}" ../../scripts/local/inspect-task223-configuration.py
uv run --locked --offline pytest -q "${CONTROLS[@]}" \
  tests/test_source_intelligence_manager.py::test_parent_invokes_two_sdk_agent_tools_and_preserves_cited_bundles \
  tests/test_source_intelligence_manager.py::test_nested_model_failure_is_recorded_as_a_gap \
  tests/test_source_intelligence_manager.py::test_parent_model_failure_returns_only_explicit_source_gaps \
  tests/test_video_review_repository.py \
  tests/test_result_repository.py tests/test_result_api.py \
  tests/test_youtube_transcript_provider.py::test_provider_preserves_sanitized_access_failures \
  tests/test_youtube_transcript_provider.py::test_provider_returns_explicit_no_caption_gap_after_both_attempts \
  --junitxml="${ARTIFACT_DIR}/offline-controls.junit.xml" -o junit_family=legacy
PYTHONPATH=. uv run --locked --offline python ../../scripts/local/inspect-task223-configuration.py > "${ARTIFACT_DIR}/effective-configuration-final.json"
cmp "${ARTIFACT_DIR}/effective-configuration.json" "${ARTIFACT_DIR}/effective-configuration-final.json"
cd "${REPO_ROOT}/apps/frontend"
pnpm exec vitest run src/lib/results/result-view.test.ts
pnpm exec svelte-kit sync
pnpm exec svelte-check --tsconfig ./tsconfig.json --fail-on-warnings --threshold error
pnpm exec playwright test --config playwright.task223-local.config.ts
