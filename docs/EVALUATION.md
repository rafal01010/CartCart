# CartCart Evaluation

Status: Evaluation strategy and implemented regression coverage
Last updated: 2026-09-27

## Evaluation Direction

CartCart should treat evaluation as an MVP requirement, not polish. The system combines search, extraction, source evidence, agent reasoning, seller/listing trust, and final recommendation logic, so regressions need to be caught at multiple layers.

Current executable routing cases use local fixtures and pytest under
`apps/backend/app/evals/` and `apps/backend/tests/`. Pydantic Evals is the
planned framework for broader scored scenario evaluation; it is not yet an
installed or running evaluation suite.

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

## Product Analysis Routing Eval Cases

Fixture-backed routing eval cases live in
`apps/backend/app/evals/routing.py` and are exercised by
`apps/backend/tests/test_live_product_analysis_routing.py`. They cover:

- broad non-technology fallback to `GenericProductAnalystAgent`
- non-specialist technology routing to `TechnologyDomainAnalystAgent`
- every MVP specialist route through `TechnologyDomainAnalystAgent`
- fallback availability from each MVP specialist to technology-domain analysis
  and then generic analysis

These are cheap mocked/local regression checks. Live model routing evals remain
opt-in and are deferred to the Section N live-agents gate.

The shopper-owner contract has separate mocked SDK tests. Existing routing evals
exercise Python-selected `ProductAnalysisRoute` and analyst fallback, not SDK
handoffs. Mocked SDK cases cover a broad request finishing with
General, a broad technology request can finish with Technology, and a phone
request transferring General -> Technology -> Smartphone with the smartphone as
last agent and draft author. Source agents remain agents-as-tools.
Research cases must distinguish actual OpenAI hosted web-search calls from
application-provider `search_sources`/`fetch_source`, allow the model to use
or skip each approved path, persist valid citations/evidence IDs, and reject
unsupported product/listing claims. Task 89R's focused mocked-SDK cases check
Discovery's live tool attachment, hosted call and citation-ID mapping, no-call
choice, rejected URL, missing citation, failure, and incompatible model.
Task 89R1's focused offline cases cover all four source specialists' live tool
attachment and optional use, site/region rejection, run-scoped citation IDs,
and incompatible models. Site evidence contracts still reject snippet-only
transcript, discussion, offer, and official IKEA claims. General's isolated
owner now has mocked cane, ambiguous-request, and weak-search cases. Its cane
draft needs fetched product/listing and review excerpts from independent
domains with persisted source, snapshot, and evidence IDs; weak or invented
evidence stays an explicit gap. Focused offline API/routing cases now check
that both wooden-cane and smartphone guided requests enter General before
category routing, while fixture runs stay offline. Task 89X's focused offline
result cases check General and Smartphone ownership, cited page records,
same-run persistence, no inferred listing, a rejected tampered quote,
verifier revisions and blocks, unverified-output blocking, a cited alternate
value mode, and an honest no-strong-buy UI projection. Task 89U's mocked SDK cases
now check General finishing a cane request, an actual General -> Technology
handoff on a keyboard request with Technology as `last_agent`, and rejection of
a non-technology handoff. Technology's narrower tools and independent model
instructions are checked. Task 89V adds mocked SDK two-hop phone ownership,
domain-only and General-only paths, failed-specialist recovery, and offline
workbench handoff scenarios. Task 89W adds role-scoped hosted search and
provider/source/trust/comparison tools to Technology and all six specialists.
Focused offline cases exercise a phone specialist recording product and
independent-review quotes, receiving a source-manager tool result or explicit
failure gap, retaining a hosted citation under its own identity, and ending as
the sole draft author. A separate case accepts a quote-backed candidate before
product persistence and rejects an unrelated name. The broader evaluation
remains deferred to the Tasks 89Q-89Y section gate.

## Evaluation Dimensions

Eval cases should check whether the system:

- Correctly extracts user need, region, budget, hard constraints, and soft preferences.
- Produces an app-generated shortlist.
- Includes user-added products when supplied.
- Finds named user-added products without links, refuses unrelated lookup hits, preserves ambiguous variants and separate seller risk, and merges only strongly evidenced product duplicates.
- Allows manual fallback only after inconclusive research or explicit correction; keeps reported price, seller, availability, review, warranty, and specifications unverified, shows a manual-only candidate in comparison, and returns no strong buy when no independent evidence supports a purchase.
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
- Checks agent classification of official sources, established first-party and
  mixed retailers, open marketplaces, excluded proxy/resale platforms,
  review/testing sources, community sources, and unknown stores against cited
  source evidence. Deterministic source policy still excludes unsafe sources.
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
create app-generated shortlist memberships. Mixed-success cases must prove that
one blocked, timed-out, oversized, or non-HTML source is persisted as a failed
snapshot while other sources and the run continue. Security cases must reject
loopback, private, link-local, and redirect-to-private targets before a request,
and professional-review pages must never be normalized as store listings.
Fixture research regressions additionally assert typed DiscoveryAgent and
ExtractionAgent replay, explicit uncertain/gap outcomes for unknown pages,
and TV/office-chair no-product results that never inherit Dell/ASUS monitor
candidates. The complete monitor replay remains the positive fixture case.

## Agent-First Research Gate Cases

The research/extraction architecture has fixture-backed and mocked checks
beyond deterministic provider checks. Seed
inputs include `tests/fixtures/providers/agent_research_source_shapes.json`;
the workbench's mixed TV discovery case now has eight review and eighteen
generic shopping results. Mocked tool-invocation tests prove bounded follow-up
searches without live calls; the workbench scenario alone is not proof of the
full extraction loop. Required cases:

- `research/tv-reviews-and-generic-shopping`: review pages remain reviews,
  generic shopping results reach `DiscoveryAgent`, likely listings/collections
  are inspected, and no monitor fixture is presented as a TV result.
- `extraction/individual-page`, `extraction/ambiguous-page`,
  `extraction/malformed-output`, and `extraction/multiple-products`: exercise
  mocked `ExtractionAgent` output against persisted, run-scoped snapshots,
  checking cited entity links, unknown-field handling, and explicit gaps.
- `research/review-to-product-lookup`: several cited TV model mentions from a
  roundup trigger bounded official/retailer listing searches; the review is
  never itself a listing.
- `extraction-agent/review-roundup`: mocked editorial extraction returns three
  cited TV leads and review claims, with zero retailer listings. The focused
  orchestration tests confirm two leads can trigger one targeted discovery pass,
  while a separate bounded-loop case repeats discovery after a partial first
  pass. Generic provider source types remain inspectable; lead matches are
  explicit before shortlist construction and unmatched evidence remains
  source-scoped.
- `research/multi-product-collection`: one retailer/category page yields
  multiple distinct cited products/listings, not its page title and first price.
- `extraction-agent/collection-without-item-urls`: two cited item leads but no
  invented direct offer URL or listing; the missing item links remain an
  explicit gap for targeted discovery.
- `research/partial-page-provider-failure`: a failed selected fetch leaves a
  persisted failed snapshot and explicit gap while another generic selected
  page still yields multiple candidates. Stage research activity records
  per-source decisions, extracted entities, gaps, and follow-up matches.
- `test_agent_first_research_gate.py` replays the observed TV result shape
  through a mocked Tavily HTTP response and a persisted shopping run: eight
  preclassified professional reviews plus eighteen generic shopping results
  reach `DiscoveryAgent`. The network-free fixture interpreter has no TV
  product facts to replay, so the result is honestly no-strong-buy with no
  monitor products. Twelve selected pages are inspected under the research
  budget; source-intelligence stages may persist additional source snapshots.
- `research/uncertain-page-and-no-results`: explicit ignore/uncertainty/gaps,
  with no fabricated identifiers, prices, availability, or candidate products.
- `research/source-id-and-budget-integrity`: every entity/evidence reference
  resolves to a persisted source/snapshot, provider failures remain gaps, and
  search/fetch/tool depth and call budgets are enforced.
- `research/typed-tool-boundary`: SDK tool schemas expose only query, intent,
  region, result count, and same-run source ID; arbitrary URLs/vendor arguments,
  private or credentialed provider URLs, secrets in raw metadata, and cross-run
  source IDs cannot reach model-facing tool output. Generic provider labels
  survive, safe records commit before their IDs are returned, and partial
  provider failure is represented as a typed gap. Focused mocked tests cover
  the implemented boundary and SDK tool invocation.

The offline gate combines these workbench, contract, and integration tests with
per-agent profile assertions. The optional live TV discovery workbench smoke is
marked `live_provider` and runs only with
`CARTCART_RUN_LIVE_PROVIDER_TESTS=1` and a configured `OPENAI_API_KEY`; offline
success does not claim that a real live TV search yielded purchasable listings.

The focused Section J fixture-mode gate command and its live-provider exclusions
are documented in `docs/PROVIDERS.md`. Keep live calls, full backend/frontend
suites, extraction checks, E2E tests, and model/eval runs outside that gate.

Contract tests should verify OpenAPI export and generated or hand-maintained frontend API expectations once the backend exists.

End-to-end tests should cover the guided fixture workflow: ask a shopping
question, complete intake, start analysis, observe progress, and inspect the
result. The current Playwright smoke test is
`apps/frontend/tests/e2e/guided-flow-smoke.spec.ts`. Product addition and
refinement remain integration/API coverage rather than claims about that
browser test.

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
path. Live-model runs must be explicitly enabled with
`CARTCART_LIVE_AGENTS_ENABLED=true`, credentialed with `OPENAI_API_KEY`, and
clearly identified as networked/cost-incurring manual checks. Workbench runs
complement unit tests and evals; they do not replace regression assertions,
routing tests, or full-workflow verification.

Normal shopping-run live-agent smokes are also opt-in. They require
`CARTCART_AGENT_WORKFLOW_MODE=live` in addition to the live-agent flag and
OpenAI key, and should be run only after fixture and mocked scenarios pass.

The local runner command shape is:

```bash
CARTCART_AGENT_WORKBENCH_ENABLED=true scripts/local/run-agent-workbench.sh \
  --agent ShoppingScopeGuardrail \
  --scenario guardrail/allowed-coffee-grinder \
  --mode fixture
```

The browser route is `/internal/agent-workbench` on the local frontend. It is
not linked from the shopper UI and depends on disabled-by-default backend
endpoints under `/internal/agent-workbench`. The backend route is mounted only
when `CARTCART_AGENT_WORKBENCH_ENABLED=true` and the backend environment is
`local`, `test`, or `fixture`; it is excluded from the public OpenAPI schema.
For Task 74B guardrail acceptance, pair the allowed fixture scenario with the
mocked boundary scenario `guardrail/blocked-dangerous-product`, which should
return blocked user-safe copy and show that the model runner did not start.
For Task 75A guide acceptance, use `guide/headphones-missing-budget` in mocked
or live mode to inspect one concise budget/use-case follow-up without product
recommendation output, and pair it with `guide/ready-monitor-brief` to inspect
the ready-for-analysis transition and `IntakeAgent` handoff when category,
budget, region, and constraints are already present.
For Task 75 intake acceptance, use `intake/monitor-ph-budget` in mocked or live
mode to inspect a structured `ShoppingBrief` with monitor category, PH region,
budget, and key preferences, and pair it with `intake/ambiguous-category` to
confirm ambiguous requests preserve category uncertainty.
For Task 89V ownership checks, use `GeneralShoppingAgent/wooden_cane`,
`GeneralShoppingAgent/keyboard_domain`, and
`GeneralShoppingAgent/smartphone_two_hop` in workbench mock mode. The latter two
run the real SDK handoff engine with offline scripted models: inspect the
completed transfer items, depth, and last owner. The cane remains with General;
keyboard ends at Technology; smartphone ends at the phone specialist. These
workbench drafts may report evidence gaps because the handoff scenarios do not
seed product and independent-review evidence.
For Task 76 query-planner acceptance, use `query-planner/coffee-grinder-us` in
mocked or live mode to inspect region-aware shopping and review queries for a
non-specialist category, and pair it with
`query-planner/unknown-category-generic` to confirm generic fallback planning
without artificial category blocking. For Task 77 discovery acceptance, use
`discovery/select-valid-sources` in mocked or live mode to inspect explicit
review/listing decisions while excluded proxy sources are ignored. Pair it
with `discovery/tv-review-and-generic-results`,
`discovery/misleading-domains`, and `discovery/no-good-results` to inspect
generic-source classification, misleading context, and an
`insufficient_candidates` outcome without product-detail fabrication. For Task
78 category-router acceptance, use `router/monitor-to-specialist` in mocked or
live mode to inspect the `TechnologyDomainAnalystAgent` to
`MonitorSpecialistAgent` route, and pair it with `router/office-chair-generic`
to confirm `GenericProductAnalystAgent` fallback without an unsupported-category
error. For Task 79 generic analyst acceptance, use
`generic/office-chair-analysis` in mocked or live mode to inspect an
office-chair `CategoryAnalysis` with fit tradeoffs, evidence gaps, and
preserved evidence/source IDs, and pair it with `generic/weak-evidence` to
confirm weak inputs produce limitations rather than category refusal. For Task
79A technology-domain acceptance, use `technology/router-monitor` in mocked or
live mode to inspect the declared `MonitorSpecialistAgent` route in internal
tool activity, and pair it with `technology/router-keyboard-domain` to confirm
broad technology-domain analysis for a technology category without an MVP
specialist. For Task 79B monitor-specialist acceptance, use
`monitor/coding-movies-1440p` in mocked or live mode to inspect a source-backed
monitor `CategoryAnalysis` covering panel type, resolution, refresh rate,
ergonomics, ports, tradeoffs, and source IDs, and pair it with
`monitor/non-monitor-reject` to confirm non-monitor input falls back instead of
being forced through monitor analysis. For Task 79C smartphone-specialist
acceptance, use `smartphone/midrange-camera-battery` in mocked or live mode to
inspect a source-backed smartphone `CategoryAnalysis` covering camera, battery,
update support, performance, region/model caveats, and source IDs, and pair it
with `smartphone/non-phone-reject` to confirm non-phone input falls back instead
of being forced through smartphone analysis. For Task 79D laptop-specialist
acceptance, use `laptop/student-portable` in mocked or live mode to inspect a
source-backed laptop `CategoryAnalysis` covering CPU, RAM, storage, battery,
display, ports, weight, upgradeability, and source IDs, and pair it with
`laptop/non-laptop-reject` to confirm non-laptop input falls back instead of
being forced through laptop analysis. For Task 79E
earphones/headphones-specialist acceptance, use
`headphones/noise-cancelling-commute` in mocked or live mode to inspect a
source-backed headphone `CategoryAnalysis` covering ANC, comfort/fit,
microphone, battery, codec/device fit, and source IDs, and pair it with
`headphones/non-audio-reject` to confirm non-audio input falls back instead of
being forced through headphone analysis. For Task 79F TV-specialist
acceptance, use `tv/55-inch-movies-gaming` in mocked or live mode to inspect a
source-backed TV `CategoryAnalysis` covering panel/backlight, HDR, motion,
gaming inputs, room brightness, size fit, and source IDs, and pair it with
`tv/non-tv-reject` to confirm non-TV input falls back instead of being forced
through TV analysis. For Task 79G smartwatch-specialist acceptance, use
`smartwatch/fitness-android` in mocked or live mode to inspect a source-backed
smartwatch `CategoryAnalysis` covering phone compatibility, health sensors,
battery, durability, app ecosystem, and source IDs, and pair it with
`smartwatch/non-watch-reject` to confirm non-watch input falls back instead of
being forced through smartwatch analysis. For Task 81 seller/listing trust
acceptance, use `trust/unknown-marketplace-cheap` in mocked or live mode to
inspect a weak or suspicious `ListingTrustAssessment` for an unknown
marketplace seller with a far-below-comparable price and unclear return policy,
and pair it with `trust/established-retailer` to confirm reasonable trust when
evidence supports the seller and source. The hard suspicious-flag tests should
prove deterministic price or contradiction flags cannot be silently overridden.
Task 89R2 adds mocked SDK branches for those trust fixtures: a concrete
seller/listing and region can trigger hosted search, the established retailer
can skip it, and a cited exact seller page yields persisted source/evidence IDs
for a neutral unverified lead. Wrong-seller URLs, missing citations, failed
calls, and incompatible model profiles must leave the existing trust level or
an explicit gap; snippets, marketplace ratings, and model-only positives must
not upgrade weak or unknown seller trust. Execute the full trust eval set at
the Tasks 89Q-89Y section gate.
For Task 81A YouTube review intelligence acceptance, use
`youtube/monitor-review-transcript` in mocked mode to inspect timestamped
pros/cons/concerns tied to the fixture video/source IDs, sponsorship and
affiliate-bias signals, and no final recommendation fields; pair it with
`youtube/no-transcript-gap` to confirm metadata-only evidence gaps are preserved
without fabricated video claims.
For Task 81B Reddit community intelligence acceptance, use
`reddit/headphones-recurring-complaint` in mocked mode to inspect recurring
qualitative signals tied to subreddit/thread/comment/source IDs plus anecdotal
and manipulation warnings; pair it with `reddit/inaccessible-gap` to confirm
inaccessible public content remains an explicit evidence gap without fabricated
community claims.
For Task 82 comparison decision acceptance, use
`comparison/monitor-shortlist` in mocked or live mode to inspect a
source-backed three-monitor `RecommendationBundle` with best overall, best
value, within-budget, stretch, and runner-up modes; pair it with
`comparison/no-strong-buy` to confirm weak or suspicious candidate sets produce
an explicit no-strong-buy outcome instead of a forced pick.
For Task 88 no-strong-buy acceptance, also use
`comparison/weak-candidates` in mocked mode to confirm weak evidence sets explain
why none are strong buys and include a concrete next step for the shopper.
For Task 83 verifier acceptance, use `verifier/unsupported-claim-block` to
confirm uncited product/spec claims block output, and
`verifier/suspicious-listing-warning` to confirm suspicious final listings are
rejected or made visibly unsafe for display unless a trust caveat is present.
Starter scenarios are registered in
`app.agents.workbench` for the current fake and live-agent implementations.
Later live-agent tasks should add their normal and boundary/failure scenarios to
that registry rather than creating new debugging plumbing.

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

Required reusable source intelligence evals should cover YouTube/video, Reddit/community, Amazon product/listing/review, and IKEA regional store evidence. The provider-service baseline must verify cited bundles and explicit gaps without counting a service call as an SDK model run. All four SDK source specialists have focused mocked-model/tool tests. A focused offline delegation test now exercises one model-running parent invoking two distinct SDK specialist agent tools, accepting cited bundles, and explaining skipped sources. The section-gate eval must additionally check model-selected review relevance, transcript/timestamp grounding, public-community quote/source grounding, independent-thread recurrence versus anecdotes, stale/low-context/manipulation warnings, inaccessible/deleted discussions, bounded tools, wrong IDs, and live model runs over recorded provider data. Amazon cases must also cover ASIN/variant ambiguity, neutral links, region uncertainty, separate seller risk, unknown IDs, and provider failure. IKEA cases cover official-region filtering, item ambiguity, local price/currency and availability grounding, unsupported regions, wrong IDs, and provider/model failure. The parent-to-specialist live model smoke passed at Task 89P; a fixture service result alone would not satisfy it.

Task 89P has an opt-in `live_model` test in
`tests/test_source_intelligence_live_model_smoke.py`. It injects an in-process
IKEA fixture provider, so the only permitted network call is to OpenAI. Passing
requires a completed parent SDK run, one validated nested IKEA agent-as-tool
call, actual source search/read tool activity, grounded source/evidence IDs, and
resolved parent/specialist models. Initial 2026-09-27 attempts exposed a turn
limit, Codex-sandbox DNS restrictions, and an unsupported constrained-decimal
regex in the IKEA structured-output schema. Those issues were corrected or
avoided, with backend `Money` and source-grounding validation retained. The
final authorized unsandboxed rerun passed: a `gpt-6-sol` parent called the
`gpt-6-luna` IKEA specialist as an SDK agent tool, the specialist searched and
read fixture data, and the parent accepted a cited bundle with valid
source/evidence IDs. The focused offline gate passed 266 tests, including the
schema regression. Task 89P is complete. No live source providers were called;
their availability and the normal end-to-end live shopping workflow remain
unverified.

Task 89Y's focused offline gate passed 329 backend checks across
owner contracts, hosted/provider tools, routing, mocked SDK handoffs, workbench,
persistence, API, trust, and result verification. Four frontend result/guided/API
unit files pass 31 checks, and the guided fixture browser smoke passes. The
credentialed smokes in `tests/test_general_owner_live_gate_smoke.py` also
passed: real General -> Technology -> Smartphone SDK handoffs ended with a
smartphone-authored result, and a real hosted OpenAI web-search call produced
citations whose source/evidence IDs were checked against run persistence. The
first opt-in attempt stopped during local fixture validation before a model
call. A later hosted attempt failed only because its test treated intermediate
citation activity as completed calls; that assertion was corrected before the
authorized passing rerun. The smokes loaded the real backend `.env`, checked
non-secret model profiles and limits, and used in-process fixture application
providers. Task 89Y is complete. Live source-provider availability remains
unverified; no live source-provider calls were made.
