# CartCart Evaluation

Status: Initial public evaluation strategy for planning
Last updated: 2026-06-02

## Evaluation Direction

CartCart should treat evaluation as an MVP requirement, not polish. The system combines search, extraction, source evidence, agent reasoning, seller/listing trust, and final recommendation logic, so regressions need to be caught at multiple layers.

Use Pydantic Evals first. It aligns with the recommended Python/Pydantic backend, Logfire/OpenTelemetry tracing direction, and code-first evaluation of complex multi-agent workflows.

DeepEval, OpenAI Evals, and Ragas may be useful later, especially if the system becomes more RAG-like over saved source evidence, but they are not the initial default.

## Minimum Eval Dataset

The first local eval dataset should contain roughly 15 to 25 shopping scenarios across categories and failure modes:

- Monitor for coding and movies.
- Smartphone purchase.
- Laptop purchase.
- Earphones/headphones under budget.
- TV purchase.
- Smartwatch purchase.
- Office chair.
- Coffee grinder.
- Running shoes.
- Portable power bank.
- Product with strong video review evidence.
- Product with useful Reddit/community discussion evidence.
- Product with Amazon product/listing/review evidence and marketplace seller ambiguity.
- Product with IKEA regional official-store evidence.
- User-added product comparison.
- Region-specific query.
- No clear strong buy.
- Suspicious cheap listing.
- Ambiguous product category.
- Budget stretch scenario.
- Duplicate listings across stores.
- Weak source or review signals.
- Refinement loop.

The dataset should cover broad category fallback, technology-domain routing, and MVP technology specialist routing. CartCart should not fail normal shopping requests just because a deep specialist does not exist.

## Evaluation Dimensions

Eval cases should check whether the system:

- Correctly extracts user need, region, budget, hard constraints, and soft preferences.
- Produces an app-generated shortlist.
- Includes user-added products when supplied.
- Uses source-backed claims.
- Avoids reseller-only platforms.
- Handles mixed marketplaces only with seller/listing trust analysis.
- Does not over-hard-filter soft budgets.
- Routes technology products through `TechnologyDomainAnalystAgent` and the appropriate MVP specialist when available.
- Provides one best pick and runner-ups, or an explicit no-strong-buy result.
- Provides seller/listing trust analysis.
- Correctly flags suspicious listings.
- Separates product quality from listing trust.
- Handles incomplete information without hallucinating certainty.
- Preserves conflicting evidence and surfaces material conflicts.
- Offers useful alternate recommendation modes from the same analysis pass.
- Preserves broad category fallback.
- Uses video review evidence only when source-backed and available.
- Represents transcript gaps honestly.
- Uses Reddit/community evidence as qualitative signal with source context, not as uncited authoritative product facts.
- Uses Amazon evidence with marketplace, listing, seller/fulfillment, review, and regional availability context preserved.
- Uses IKEA evidence only with explicit country/region context and does not infer global shipping or availability.
- Handles unavailable, blocked, weak, stale, anecdotal, or conflicting reusable source intelligence without fabricating certainty.

## Test Layers

Unit tests should cover schemas, deterministic source policy, budget semantics, deduplication, trust rules, and recommendation invariants.

Integration tests should cover API endpoints, persistence, run lifecycle, event ordering, provider fixture replay, source extraction fixtures, and result versioning.

Contract tests should verify OpenAPI export and generated or hand-maintained frontend API expectations once the backend exists.

End-to-end tests should cover the first stubbed workflow, then the fixture-backed full workflow: create a session, start a run, observe progress, inspect results, add a product, and submit a refinement. The first Playwright smoke test lives at `apps/frontend/tests/e2e/stub-run-smoke.spec.ts` and covers the session creation, fixture run, progress, and final-pick path.

Eval tests should run against stable local fixtures first. Live provider or live model evals should be opt-in because they require credentials, cost, and network access.

Local frontend verification wrappers live under `scripts/local/`: `lint-frontend.sh`, `check-frontend.sh`, `test-frontend.sh`, `build-frontend.sh`, and `setup-playwright.sh`. Use focused unit test arguments during normal feature work and reserve full frontend verification, production builds, and browser checks such as `pnpm --dir apps/frontend run test:e2e` for the relevant gate or explicit release-like checks.

## Evidence And Fixture Policy

Provider responses used in tests should be recorded safely:

- Do not commit secrets.
- Avoid excessive raw content.
- Preserve enough metadata to debug search, extraction, trust, and source quality behavior.
- Include representative failure modes such as unavailable transcripts, inaccessible or weak Reddit threads, Amazon variant/review ambiguity, unavailable IKEA regional inventory, extraction failures, weak evidence, duplicate listings, and suspicious sellers.

Claims in expected outputs should reference source IDs where the production schema requires them.

## Quality Gates

Before a workflow capability is considered accepted, verification should show:

- Schema validation passes for expected outputs.
- Relevant unit and integration tests pass.
- The affected eval cases pass or have documented expected failures.
- Trace/log fields are sufficient to debug the run.
- No recommendation output makes unsupported factual claims.
- Suspicious listing behavior is not silently bypassed.

When adding, removing, moving, or changing fallback behavior for an agent or source capability, update `supported_agents.md`, the runtime agent catalog once it exists, related routing tests, provider fixtures where relevant, and eval cases together.

Required reusable source intelligence evals should cover YouTube/video, Reddit/community, Amazon product/listing/review, and IKEA regional store evidence. They should prove that source agents add useful evidence to product analysis without becoming final recommendation agents or bypassing seller/listing trust.
