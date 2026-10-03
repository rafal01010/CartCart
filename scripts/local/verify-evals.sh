#!/usr/bin/env bash
# Section Q only: no earlier gates, app builds, E2E, or live calls.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/apps/backend"
if ! command -v uv >/dev/null 2>&1; then
  echo "Error: uv is required. Run scripts/local/sync-backend.sh first." >&2
  exit 1
fi
mkdir -p "${REPO_ROOT}/data/artifacts"
GATE_TEMP="$(mktemp -d "${REPO_ROOT}/data/artifacts/section-q.XXXXXX")"
trap 'rm -rf -- "${GATE_TEMP}"' EXIT
export UV_CACHE_DIR="${GATE_TEMP}/uv-cache"
cd "${BACKEND_DIR}"
GATE_STATUS=0
run_check() {
  if "$@"; then
    return 0
  else
    GATE_STATUS=1
  fi
}
# Full always executes all five quick lanes first, including on failure, then
# retains complete diagnostics. A failed quick phase cannot become a green gate.
run_check "${SCRIPT_DIR}/run-evals.sh" --suite full
run_check uv run --locked --offline pytest -q \
  tests/test_eval_scaffolding.py tests/test_initial_eval_dataset.py \
  tests/test_intake_planning_evals.py tests/test_discovery_extraction_evals.py \
  tests/test_trust_recommendation_evals.py tests/test_source_intelligence_evals.py \
  tests/test_eval_suites.py tests/test_section_q_repairs.py \
  tests/test_live_query_planner_agent.py tests/test_live_extraction_agent.py \
  tests/test_live_comparison_decision_agent.py tests/test_live_verifier_critic_agent.py \
  tests/test_youtube_review_intelligence_agent.py tests/test_youtube_review_intelligence_service.py \
  tests/test_video_evidence_creation.py tests/test_source_intelligence_manager.py \
  tests/test_agent_catalog.py::test_agent_catalog_exposes_required_reusable_source_tools \
  tests/test_guided_intake_api.py::test_submit_followup_answer_captures_budget_and_known_product_without_links \
  tests/test_guided_intake_api.py::test_sentence_link_and_named_products_become_separate_candidates \
  tests/test_guided_intake_api.py::test_standalone_product_name_is_tracked_without_mistaking_budget_for_product \
  -m "not live_provider and not live_model" --basetemp "${GATE_TEMP}/pytest"
run_check uv run --locked --offline ruff check app/evals app/tools/run_evals.py \
  tests/test_eval_scaffolding.py tests/test_initial_eval_dataset.py \
  tests/test_intake_planning_evals.py tests/test_discovery_extraction_evals.py \
  tests/test_trust_recommendation_evals.py tests/test_source_intelligence_evals.py \
  tests/test_eval_suites.py tests/test_section_q_repairs.py \
  app/agents/catalog.py app/agents/live_query_planner.py app/agents/live_extraction.py \
  app/agents/live_comparison_decision.py app/agents/live_verifier_critic.py \
  app/agents/live_youtube_review_intelligence.py app/agents/youtube_review_intelligence_service.py \
  app/services/volunteered_products.py tests/test_agent_catalog.py
run_check uv run --locked --offline mypy --follow-imports=silent \
  app/evals/suites.py app/evals/runner.py app/tools/run_evals.py \
  app/agents/catalog.py app/agents/live_query_planner.py app/agents/live_extraction.py \
  app/agents/live_comparison_decision.py app/agents/live_verifier_critic.py \
  app/agents/live_youtube_review_intelligence.py app/agents/youtube_review_intelligence_service.py \
  app/services/volunteered_products.py
run_check bash -n "${SCRIPT_DIR}/run-evals.sh" "${SCRIPT_DIR}/verify-evals.sh"
run_check git -C "${REPO_ROOT}" diff --check
exit "${GATE_STATUS}"
