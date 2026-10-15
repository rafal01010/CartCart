#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/private/tmp/cartcart-task222-uv-cache}"
export MYPY_CACHE_DIR="${MYPY_CACHE_DIR:-/private/tmp/cartcart-task222-mypy-cache}"
ARTIFACT_DIR="${REPO_ROOT}/data/artifacts/task222"
export CARTCART_TASK222_ARTIFACT_DIR="${ARTIFACT_DIR}"
mkdir -p "${ARTIFACT_DIR}"
cd "${REPO_ROOT}/apps/backend"

SOURCES=(
  app/agents/context_management.py app/agents/token_policy.py
  app/agents/request_compaction.py app/agents/research_history.py
  app/agents/owner_research.py app/orchestration/shopping_runs.py
  app/agents/live_amazon_product_intelligence.py app/agents/live_category_router.py
  app/agents/live_comparison_decision.py app/agents/live_discovery.py
  app/agents/live_earphones_headphones_specialist.py app/agents/live_extraction.py
  app/agents/live_general_shopping.py app/agents/live_generic_product_analyst.py
  app/agents/live_guardrails.py app/agents/live_guide.py
  app/agents/live_ikea_store_intelligence.py app/agents/live_intake.py
  app/agents/live_laptop_specialist.py app/agents/live_monitor_specialist.py
  app/agents/live_query_planner.py app/agents/live_reddit_community_intelligence.py
  app/agents/live_seller_listing_trust.py app/agents/live_smartphone_specialist.py
  app/agents/live_smartwatch_specialist.py app/agents/live_source_intelligence_manager.py
  app/agents/live_technology_domain_analyst.py app/agents/live_tv_specialist.py
  app/agents/live_verifier_critic.py app/agents/live_youtube_review_intelligence.py
)
CONTROLS=(
  tests/test_task222_budget_matrix.py tests/test_task222_source_sdk.py
  tests/test_task222_saved_completion.py tests/test_task222_configuration.py
)
uv run --locked --offline ruff check "${SOURCES[@]}" "${CONTROLS[@]}"
uv run --locked --offline python -m py_compile "${SOURCES[@]}" "${CONTROLS[@]}"
uv run --locked --offline mypy --follow-imports=silent \
  app/agents/context_management.py app/agents/token_policy.py \
  app/agents/request_compaction.py app/agents/research_history.py
uv run --locked --offline pytest -q "${CONTROLS[@]}" \
  --junitxml="${ARTIFACT_DIR}/offline-controls.junit.xml" -o junit_family=legacy
