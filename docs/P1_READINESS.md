# P1 readiness, 2026-10-18

Task 221 is complete. Its final [acceptance handoff](TASK_221_IMPLEMENTATION_HANDOFF.md#final-remaining-live-acceptance-2026-10-18) and checked implementation entry record the corrected phone and ordinary backpack results, exact saved/API membership and actual desktop/mobile/source checks. Those passes do not need to be rechecked before each batch. Task 227 passed offline repair acceptance separately; its optional manual live question test is not a new P1 prerequisite.

This audit checks current code and retained acceptance rather than assuming historical unchecked entries still describe defects. No application implementation, browser journey, model/provider call or new live-run task was performed.

## Current disposition

| Task | Disposition | Current evidence and remaining scope |
| --- | --- | --- |
| 179 | Pending, partly covered | Normal owner conversion reloads persisted evidence and Task 227 retains consultation packets for recovery. The separate reusable-source stage still stores bundles without adding their claims to `_analysis_evidence`, which feeds shared analysis/trust/comparison inputs. The local collector probe gives three bundled speech claims and zero shared collector claims. Complete that remaining consumer wiring and its relevant attribution/gap acceptance. |
| 181 | Closed, already fixed by later implementation | Actual normalization preserves the cited concern over a strong rule baseline. Temporary SQLite and fresh-session reload preserve the complete assessment, source/evidence IDs, scoped warning and result source projection. Persisted assessments retain precedence in owner inputs. Historical deterministic blocking requirements were superseded by Task 216. |
| 191 | Closed as superseded by completed Task 216 | Mandatory within-budget alternatives and automatic budget rejection conflict with the owner's current policy. Normal/saved instructions preserve budget/currency and request clear stretch explanations; the retained comparison exposes known overage and preserves model-authored advice. Existing live budget acceptance and three focused local controls cover the current policy. |
| 193 | Pending, partly covered | Lower-level URL normalization and dedup retain functional queries. Research/discovery/snapshot projections still strip `sku`, and extraction rejects query-bearing original listings while accepting the stripped destination. Complete those consumer boundaries and exact identity/persistence controls. |

## Task 179 evidence

`app/orchestration/shopping_runs.py` assigns and persists `context.source_intelligence` in its source-manager/provider paths. `_analysis_evidence` returns extraction, fixture and owner evidence only. Its source bundles are absent. The normal `_owner_recommendation` path separately reloads stored evidence into `context.owner_evidence`, so this is not a claim that every normal result loses every source. Task 227's recovery packet adapter is also useful existing work to reuse, not proof that the shared typed consumers are repaired.

Reproduce the no-provider collector probe from `apps/backend` with `PYTHONPATH=. UV_CACHE_DIR=/private/tmp/cartcart-uv-cache uv run --offline python ../../data/artifacts/p1-readiness-20261018/check_source_collector.py`. It uses the existing frozen caption fixture and a typed in-memory context. Output is three bundled claims, zero shared collector claims. It does not fetch transcripts or modify saved runs.

## Task 181 evidence

`app/agents/live_seller_listing_trust.py::_normalize_listing_trust_assessment` now retains model summary, red flags and signal text, and only filters/deduplicates source and evidence IDs. It no longer replaces the concern with a strong-trust summary. `app/services/recommendation_trust.py` preserves model-authored advice and scoped warnings under Task 216. `app/agents/owner_research.py::assess_run_listings` gives the saved assessment precedence over a fresh rule result; saved owner input includes its summary and red flags.

The reproducible local artifact `data/artifacts/p1-readiness-20261018/check_seller_concern.py` ran successfully. It supplies a labeled synthetic seller-of-record conflict, calls actual normalization, saves actual source/evidence and result records to temporary in-memory SQLite, reloads in a fresh session and asserts exact complete assessment and advice equality. It also checks exact concern text, flags/signals, source/evidence IDs, source projection and persisted-owner override. The result is `check_seller_concern.result.json`. Reproduce from the repository root with `PYTHONDONTWRITEBYTECODE=1 apps/backend/.venv/bin/python data/artifacts/p1-readiness-20261018/check_seller_concern.py`.

Two existing focused tests passed in 1.11 seconds: `test_live_seller_listing_trust_can_improve_advisory_price_assessment` and `test_result_repository_saves_and_loads_full_fixture_bundle`. The new audit artifact supplies literal conflict assertions absent from those existing tests. No source code changed, and no HTTP route, browser display or future live model judgment is claimed by this control. Old forced-blocking criteria are superseded, not silently reintroduced.

## Task 191 evidence

`app/agents/live_general_shopping.py` gives normal and saved owners the requested budget, known prices/currencies, calculated overage and clear-explanation instructions. `app/agents/research_guidance.py` preserves the latest structured budget and distinguishes unlimited from missing budget. `docs/TASK_216.md` explicitly removes hard price vetoes and mandatory companion modes. [Accepted budget refinement](TASK_216_LIVE_ACCEPTANCE.md#saved-browser-journeys) records PHP 90,000, the PHP 94,990 lineup starting price and the model's explained PHP 4,990 stretch. No exact configuration/offer price was invented.

Three existing local controls passed in 1.35 seconds: `test_comparison_preserves_uncited_over_budget_model_selection_without_modes`, `test_comparison_input_exposes_budget_difference_and_unknowns_as_advice`, and `test_optional_modes_sources_budget_and_copy_are_model_judgments`. They use synthetic output and prove policy/context wiring; the historical live refinement supplies the real judgment evidence. No fresh live call was needed.

## Task 193 evidence

`app/providers/source_quality.py::normalize_source_url` and `app/services/product_deduplication.py::canonical_listing_url` retain `sku` and remove tracking. In contrast, the `_neutral_url` functions in `app/agents/research_tools.py` and `live_discovery.py`, and the snapshot reader in `extraction_tools.py`, strip functional queries. `live_extraction.py::_validate_extraction` rejects any query and then compares identity against the already stripped readable URL.

The read-only local actual-function probe retained `/product?sku=A55` at the lower layers, produced `/product` in research/discovery, rejected the original query-defined listing and accepted the stripped one. This is an observed current implementation gap, not a reason to rerun paid shopping research.

## Execution authorization

Use the lean active prompt in [TASK_EXECUTION_PROMPTS.md](../TASK_EXECUTION_PROMPTS.md#execute-a-later-batch-of-at-most-two-tasks). Necessary task-local live model, research and provider calls, including bounded retries, have standing owner authorization within existing settings and spending limits. End-to-end app journeys in a browser are separate tasks the owner will request. Do not create those tasks proactively. Completed P0 gates are reused.

The current next batch is Tasks 179 and 193. Tasks 181 and 191 have been reconciled and closed; do not reimplement their historical policies. Continue to P2 after the remaining P1 acceptance passes.
