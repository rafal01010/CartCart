#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/apps/backend"
if ! command -v uv >/dev/null 2>&1; then
  echo "Error: uv is required. Run scripts/local/sync-backend.sh first." >&2
  exit 1
fi
mkdir -p "${REPO_ROOT}/data/artifacts"
CONTEXT_TEMP="$(mktemp -d "${REPO_ROOT}/data/artifacts/context-gate.XXXXXX")"
trap 'rm -rf -- "${CONTEXT_TEMP}"' EXIT
export UV_CACHE_DIR="${CONTEXT_TEMP}/uv-cache"
export MYPY_CACHE_DIR="${CONTEXT_TEMP}/mypy-cache"
cd "${BACKEND_DIR}"
LIVE_CONTEXT_TESTS=()
for test_file in tests/test_live_*.py; do
  case "${test_file}" in
    tests/test_live_query_planner_agent.py|tests/test_live_extraction_agent.py|tests/test_live_comparison_decision_agent.py|tests/test_live_verifier_critic_agent.py) continue ;;
  esac
  LIVE_CONTEXT_TESTS+=("${test_file}")
done
uv run --locked --offline pytest -q \
  tests/test_context_management.py tests/test_context_exact_support.py \
  tests/test_research_history.py tests/test_context_research_completion.py \
  tests/test_downstream_context_projection.py \
  tests/test_context_decision_fidelity.py tests/test_agent_research_tools.py \
  "${LIVE_CONTEXT_TESTS[@]}" \
  tests/test_reddit_community_intelligence_agent.py \
  tests/test_amazon_product_intelligence_agent.py tests/test_ikea_store_intelligence_agent.py \
  tests/test_shopping_run_orchestrator.py tests/test_agent_first_research_gate.py \
  tests/test_search_source_repository.py tests/test_source_intelligence_repository.py \
  tests/test_source_extraction.py tests/test_refinement_planning.py tests/test_refinement_api.py \
  tests/test_search_provider_runtime.py tests/test_extraction_provider_runtime.py \
  tests/test_openai_agent_config.py tests/test_shopping_intent.py tests/test_agent_catalog.py \
  --deselect tests/test_agent_catalog.py::test_agent_catalog_exposes_required_reusable_source_tools \
  -m "not live_provider and not live_model" --basetemp "${CONTEXT_TEMP}/pytest"
CONTEXT_FILES=(app/agents/context_management.py app/agents/context_metrics.py \
  app/agents/research_history.py app/agents/model_input_projection.py \
  app/agents/source_spans.py app/agents/owner_research.py app/agents/research_tools.py app/agents/extraction_tools.py \
  app/agents/youtube_review_tools.py app/agents/reddit_community_tools.py \
  app/agents/amazon_marketplace_tools.py app/agents/ikea_regional_tools.py \
  app/agents/research_guidance.py \
  app/agents/live_*.py app/orchestration/shopping_runs.py app/tools/audit_context.py \
  app/services/shopping_intent.py app/agents/catalog.py)
UNIQUE_CONTEXT_FILES=()
for source_file in "${CONTEXT_FILES[@]}"; do
  case "${source_file}" in
    app/agents/catalog.py|app/agents/live_query_planner.py|app/agents/live_extraction.py|app/agents/live_comparison_decision.py|app/agents/live_verifier_critic.py|app/agents/live_youtube_review_intelligence.py) continue ;;
  esac
  UNIQUE_CONTEXT_FILES+=("${source_file}")
done
uv run --locked --offline ruff check "${UNIQUE_CONTEXT_FILES[@]}" tests/test_context_management.py \
  tests/test_research_history.py tests/test_context_research_completion.py \
  tests/test_downstream_context_projection.py \
  tests/test_context_exact_support.py tests/test_context_decision_fidelity.py \
  tests/test_agent_research_tools.py tests/test_live_general_shopping_agent.py \
  tests/test_amazon_product_intelligence_agent.py tests/test_ikea_store_intelligence_agent.py \
  tests/test_youtube_review_intelligence_agent.py tests/test_reddit_community_intelligence_agent.py \
  app/services/runs.py app/agents/workbench.py app/evals/discovery_extraction.py app/evals/source_intelligence.py
uv run --locked --offline ruff format --check app/agents/context_management.py \
  app/agents/research_history.py app/agents/model_input_projection.py \
  tests/test_research_history.py tests/test_context_research_completion.py \
  tests/test_downstream_context_projection.py \
  app/agents/context_metrics.py app/agents/source_spans.py app/tools/audit_context.py \
  tests/test_context_management.py
uv run --locked --offline mypy --follow-imports=silent "${UNIQUE_CONTEXT_FILES[@]}"
uv run --locked --offline python -m app.tools.audit_context \
  --output "${REPO_ROOT}/data/artifacts/context/task100b-after.json"
bash -n "${SCRIPT_DIR}/verify-context.sh"
"${SCRIPT_DIR}/verify-evals.sh"
