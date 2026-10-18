# P1 readiness, 2026-10-18

Task 221 is complete. Its final [acceptance handoff](TASK_221_IMPLEMENTATION_HANDOFF.md#final-remaining-live-acceptance-2026-10-18) and checked implementation entry record the corrected phone and ordinary backpack results, exact saved/API membership and actual desktop/mobile/source checks. Those passes do not need to be rechecked before each batch. Task 227 passed offline repair acceptance separately; its optional manual live question test is not a new P1 prerequisite.

The original audit below was read-only. A subsequent implementation batch completed Tasks 179 and 193 with attribution prerequisite 188. Its final acceptance passed 59 offline checks. [Implementation handoff](TASK_179_193_IMPLEMENTATION_HANDOFF.md) records the changes, preserved work and historical gate limits. No live calls or browser journeys ran in that batch.

## Current disposition

| Task | Disposition | Current evidence and remaining scope |
| --- | --- | --- |
| 179 | Complete | Validated source claims, context, warnings and gaps reach shared typed consumers. Fresh SQLite reload resolves saved recommendation citations to exact canonical support. Source attribution prerequisite 188 and prewrite collision controls pass. |
| 181 | Closed, already fixed by later implementation | Actual normalization preserves the cited concern over a strong rule baseline. Temporary SQLite and fresh-session reload preserve the complete assessment, source/evidence IDs, scoped warning and result source projection. Persisted assessments retain precedence in owner inputs. Historical deterministic blocking requirements were superseded by Task 216. |
| 191 | Closed as superseded by completed Task 216 | Mandatory within-budget alternatives and automatic budget rejection conflict with the owner's current policy. Normal/saved instructions preserve budget/currency and request clear stretch explanations; the retained comparison exposes known overage and preserves model-authored advice. Existing live budget acceptance and three focused local controls cover the current policy. |
| 193 | Complete | Approved functional queries survive SDK tools, discovery, persisted sources, snapshot reads and public extraction. Stripped or changed identity fails; observed query-based collection links remain valid. |

## Original Task 179 audit evidence

Before implementation, `app/orchestration/shopping_runs.py` assigned and persisted `context.source_intelligence` without including its bundles in `_analysis_evidence`. The normal `_owner_recommendation` path separately reloads stored evidence into `context.owner_evidence`, so this is not a claim that every normal result loses every source. Task 227's recovery packet adapter is also useful existing work to reuse, not proof that the shared typed consumers are repaired.

The retained no-provider collector probe at `data/artifacts/p1-readiness-20261018/check_source_collector.py` asserted the original omission with three bundled claims and zero shared claims. It is historical failing-behavior evidence, not a current acceptance command. Current consumer, persistence and provenance controls are in `apps/backend/tests/test_task179_source_consumers.py`. Saved captions were reused without fetching them again.

## Task 181 evidence

`app/agents/live_seller_listing_trust.py::_normalize_listing_trust_assessment` now retains model summary, red flags and signal text, and only filters/deduplicates source and evidence IDs. It no longer replaces the concern with a strong-trust summary. `app/services/recommendation_trust.py` preserves model-authored advice and scoped warnings under Task 216. `app/agents/owner_research.py::assess_run_listings` gives the saved assessment precedence over a fresh rule result; saved owner input includes its summary and red flags.

The reproducible local artifact `data/artifacts/p1-readiness-20261018/check_seller_concern.py` ran successfully. It supplies a labeled synthetic seller-of-record conflict, calls actual normalization, saves actual source/evidence and result records to temporary in-memory SQLite, reloads in a fresh session and asserts exact complete assessment and advice equality. It also checks exact concern text, flags/signals, source/evidence IDs, source projection and persisted-owner override. The result is `check_seller_concern.result.json`. Reproduce from the repository root with `PYTHONDONTWRITEBYTECODE=1 apps/backend/.venv/bin/python data/artifacts/p1-readiness-20261018/check_seller_concern.py`.

Two existing focused tests passed in 1.11 seconds: `test_live_seller_listing_trust_can_improve_advisory_price_assessment` and `test_result_repository_saves_and_loads_full_fixture_bundle`. The new audit artifact supplies literal conflict assertions absent from those existing tests. No source code changed, and no HTTP route, browser display or future live model judgment is claimed by this control. Old forced-blocking criteria are superseded, not silently reintroduced.

## Task 191 evidence

`app/agents/live_general_shopping.py` gives normal and saved owners the requested budget, known prices/currencies, calculated overage and clear-explanation instructions. `app/agents/research_guidance.py` preserves the latest structured budget and distinguishes unlimited from missing budget. `docs/TASK_216.md` explicitly removes hard price vetoes and mandatory companion modes. [Accepted budget refinement](TASK_216_LIVE_ACCEPTANCE.md#saved-browser-journeys) records PHP 90,000, the PHP 94,990 lineup starting price and the model's explained PHP 4,990 stretch. No exact configuration/offer price was invented.

Three existing local controls passed in 1.35 seconds: `test_comparison_preserves_uncited_over_budget_model_selection_without_modes`, `test_comparison_input_exposes_budget_difference_and_unknowns_as_advice`, and `test_optional_modes_sources_budget_and_copy_are_model_judgments`. They use synthetic output and prove policy/context wiring; the historical live refinement supplies the real judgment evidence. No fresh live call was needed.

## Original Task 193 audit evidence

At audit time, `normalize_source_url` and `canonical_listing_url` retained `sku` while research, discovery and snapshot projections stripped it. Extraction then rejected the original query-defined offer. The implementation now uses a shared approved outbound policy and validates the inspected item identity.

The read-only local actual-function probe retained `/product?sku=A55` at the lower layers, produced `/product` in research/discovery, rejected the original query-defined listing and accepted the stripped one. That recorded gap is now repaired and covered by offline public-tool and extraction controls.

## Execution authorization

Use the lean active prompt in [TASK_EXECUTION_PROMPTS.md](../TASK_EXECUTION_PROMPTS.md#execute-a-later-batch-of-at-most-two-tasks). Necessary task-local live model, research and provider calls, including bounded retries, have standing owner authorization within existing settings and spending limits. End-to-end app journeys in a browser are separate tasks the owner will request. Do not create those tasks proactively. Completed P0 gates are reused.

P1 is reconciled. Tasks 179, 188 and 193 passed implementation acceptance; Tasks 181 and 191 remain closed. The next recommended batch is 132 then 128. Preserve current recommendation policy and the batch handoff's distinction between passing task acceptance and historical broad-gate failures.
