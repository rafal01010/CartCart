# CartCart Evaluation

Status: Initial public evaluation strategy for planning
Last updated: 2026-06-14

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
- Rejects extracted product or listing claims whose target does not cite the
  exact source snapshot, and retains both sides of contradictory warranty or
  review-verdict fixture evidence with an explicit conflict record.
- Offers useful alternate recommendation modes from the same analysis pass.
- Preserves broad category fallback.
- Uses video review evidence only when source-backed and available.
- Represents transcript gaps honestly.
- Uses Reddit/community evidence as qualitative signal with source context, not as uncited authoritative product facts.
- Uses Amazon evidence with marketplace, listing, seller/fulfillment, review, and regional availability context preserved.
- Uses IKEA evidence only with explicit country/region context and does not infer global shipping or availability.
- Handles unavailable, blocked, weak, stale, anecdotal, or conflicting reusable source intelligence without fabricating certainty.
- Classifies official sources, established first-party and mixed retailers,
  open marketplaces, excluded proxy/resale platforms, review/testing sources,
  community sources, and unknown stores deterministically.
- Scores matching and mismatched regional domains, currencies, shipping,
  Amazon marketplaces, and IKEA country paths predictably and with reasons.

## Test Layers

Unit tests should cover schemas, deterministic source policy, budget semantics, deduplication, trust rules, and recommendation invariants.

Integration tests should cover API endpoints, persistence, run lifecycle, event ordering, provider fixture replay, source extraction fixtures, and result versioning.

YouTube metadata adapter tests should replay synthetic `search.list` and
`videos.list` fixtures without network access, verify video identity, title,
description, channel, publish date, duration, and neutral URL mapping, and keep
transcript availability explicitly `not_checked`. Missing results and provider
errors should return typed unavailable or sanitized error behavior without
leaking API keys.

YouTube transcript-ingestion tests should use deterministic permitted-provider
fixtures, preserve transcript language and timestamps, represent unavailable or
failed access as explicit gaps, and retain metadata-only evidence without
inventing product claims. Deterministic video evidence creation must reject a
claim unless its cited text appears in bundled transcript segments.

Reddit community discovery evals should replay domain-scoped search fixtures
without network access and verify public thread/comment URLs, subreddit and
thread context, permitted excerpts or extracted text, optional recency and
engagement metadata, qualitative source scoring, and explicit gaps for removed,
inaccessible, unextracted, weak, or missing content. Expected outputs must not
treat community anecdotes as authoritative specifications, prices, warranties,
or availability facts. Focused evidence-creation tests should preserve all
supporting thread/comment source IDs for recurring complaints, warn on stale or
low-context discussions, and reject product claims that do not appear in every
cited public discussion summary.

Amazon product-intelligence tests should replay synthetic SerpApi Amazon Search
and Product responses without network access. They should verify conservative
ASIN matching, marketplace and listing identity, neutral non-affiliate product
URLs, seller/ship-from separation, third-party seller warnings, requested-region
delivery evidence or explicit gaps, product-page facts, rating/review summaries,
variant ambiguity, missing review access, disabled/fixture/live runtime modes,
and sanitized provider failures. Live SerpApi tests must remain credentialed and
explicitly opt-in.

Focused Amazon evidence-creation tests should verify third-party seller risk,
variant/review ambiguity warnings, unavailable or inconclusive shipping,
missing review access, explicit product-fact gaps, and rejection of affiliate or
tracking URLs without creating unsupported facts.

IKEA regional-store tests should replay synthetic domain-scoped search fixtures
without network access. They should verify official country-path filtering,
country/region context, neutral official URLs, product-page identity, local
price/currency, stock and delivery/store signals, and explicit gaps for
unavailable products or unsupported regions. A no-regional-presence case should
prove that no search call occurs, and expected output must never infer global
shipping from IKEA brand presence.

Focused IKEA evidence-creation tests should verify available and unavailable
regional products, preservation of official source/store context, explicit gaps
for missing product facts, price, availability, or store/delivery fields, and
rejection of tracked or cross-region URLs. Generated availability and shipping
claims must remain scoped to the declared IKEA country or region.

Focused discovery and extraction integration tests should verify that fixture
mode makes no network calls, enabled provider configuration resolves the
intended adapters, planned queries receive region/category options, accepted
results are policy-scored and persisted, explicitly excluded domains are
dropped, tracking parameters are normalized away, eligible pages pass through
the extraction boundary, linked snapshots are persisted, and usable outcomes
create app-generated shortlist memberships.

The focused Section J fixture-mode gate command and its live-provider exclusions
are documented in `docs/PROVIDERS.md`. Keep live calls, full backend/frontend
suites, extraction checks, E2E tests, and model/eval runs outside that gate.

Contract tests should verify OpenAPI export and generated or hand-maintained frontend API expectations once the backend exists.

End-to-end tests should cover the first stubbed workflow, then the fixture-backed full workflow: create a session, start a run, observe progress, inspect results, add a product, and submit a refinement. The first Playwright smoke test lives at `apps/frontend/tests/e2e/stub-run-smoke.spec.ts` and covers the session creation, fixture run, progress, and final-pick path.

Eval tests should run against stable local fixtures first. Live provider or live model evals should be opt-in because they require credentials, cost, and network access.

Local frontend verification wrappers live under `scripts/local/`: `lint-frontend.sh`, `check-frontend.sh`, `test-frontend.sh`, `build-frontend.sh`, and `setup-playwright.sh`. Use focused unit test arguments during normal feature work and reserve full frontend verification, production builds, and browser checks such as `pnpm --dir apps/frontend run test:e2e` for the relevant gate or explicit release-like checks.

## Isolated Agent Workbench

Live-agent implementation should include a local-only workbench for hands-on
inspection of one agent at a time. This is a developer and project-owner
verification surface, not part of the normal shopper UI and not a public API.

The workbench should provide both a scriptable terminal runner and a small local
browser page backed by disabled-by-default internal endpoints. It should invoke
only allowlisted agents from the executable catalog through their existing typed
protocols. Each implemented agent should provide named normal and
boundary/failure scenarios with schema-valid inputs; structured workflow agents
should not be forced into a chat interface merely because conversational agents
can use one.

An isolated run should make the following inspectable without exposing secrets
or hidden reasoning:

- Validated agent input and structured output.
- Allowed tool calls and sanitized tool results.
- Model, elapsed time, trace ID, token usage when available, and estimated cost
  when the application can calculate it reliably.
- Schema-validation, timeout, provider, guardrail, and fallback outcomes.

Mocked-model and fixture scenarios remain the required repeatable acceptance
path. Live-model runs must be explicitly enabled, credentialed, and clearly
identified as networked/cost-incurring manual checks. Workbench runs complement
unit tests and evals; they do not replace regression assertions, routing tests,
or full-workflow verification.

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
