# CartCart Architecture

## Advice ownership, Task 219

Shared shopper guidance defines direct what-to-buy prose in the owner, Technology/specialist handoffs, saved-research resume, forced completion, retained comparison/category analyzers and optional editorial verifier. It removes intake echoes, confidence narration, missing-source or missing-stock passages and where/how-to-buy rituals. Research targets suitability and meaningful relative differences. Known product age, support, compatibility and launch differences can matter; absent information does not require a warning or a mandatory search.

Existing rationale and tradeoff fields carry shopper advice. Diagnostic fields and factual source records retain their schemas and storage. The result component removes generated confidence, generic warning, unknowns and seller-check copy while preserving authored reasons, tradeoffs, supported budget notes and neutral links. Controlled fixture writers own developer labels; literal shopping and evidence text is never filtered by the word fixture. Task 220 retains ownership of history, duplicate comparison, refinement and restart layout work. Live validation deferred to Task 221.

## Authored choice groups, Task 218

The shopping owner assigns candidate `choice_group` before retaining its decision draft. Finalization keeps up to three primary choices and up to two optional runners-up rather than truncating all candidates to three or treating every later candidate as a runner. `RecommendationBundle.primary_product_ids` and existing `runner_up_product_ids` preserve membership through JSON storage and direct API projection. Existing mode records retain product reasons, tradeoffs and optional provenance. The frontend maps each group separately.

Model and schema boundaries validate counts, unique membership and final-pick consistency. They do not choose brands or impose a budget veto. The owner weighs suitability, adverse information, preferences and explained modest budget stretches; useful company/provider diversity is a preference, with explicit exclusive requests respected. One or two primary choices and zero runners are valid.

Null or absent primary IDs retain historical bundle compatibility. Old checkpoint candidates may omit their group. No new table, saved-record rewrite, agent, route, provider or model stage is added. Task 216 recommendation-by-default and Task 217 source projection remain. Task 219 owns concise advice; Task 220 page simplification remains a separate implementation unit. Live validation is deferred to Task 221.

## Offline shopper-feedback implementation, Task 217

Tasks 217-220 and their prerequisites have an active live-call hold. Task 217 keeps the existing shopping owner, SDK handoffs, research state and provider boundaries. Broad queries start with category, buyer intent, preferences and region, then follow useful results into products and companies. Named brands are preferences unless explicitly exclusive. Relevance, new information and useful breadth guide the bounded lead selection; duplicates and repeated facts are deferred while original records remain available. The owner stops when enough useful information exists, without source or video quotas.

The normal owner may request optional `video_review` intelligence through `consult_source_intelligence`. The source manager delegates to the existing YouTube specialist, which searches metadata and reads approved public captions through typed tools. Returned video bundles and provenance use the existing persistence repositories. Bounded parent context prioritizes cited transcript segments, with full originals available for reread. No separate mandatory source stage or verifier is introduced. Live search relevance and substantive caption use remain deferred to Task 221.

## Current recommendation policy, Task 216

Ordinary shopping gathers information where available and passes it with buyer preferences to the owning LLM. The model recommends by default and weighs strong adverse information. Missing sources, reviews, prices, stock, warranty or support details are unknowns, not reasons for automatic rejection. Source quality, comparison and seller scores are advisory. Official stores need no mandatory background check. Budgets inform the model, including explained slightly over-budget alternatives. Unlimited budget remains distinct from missing budget.

Advice and source associations are independent. Recommendation evidence IDs, sources, comparison matrices, checked listings and mode records are optional. The UI leads with recommendations, reasons and meaningful tradeoffs, then shows available page sources and search snippets. Unknowns remain diagnostic fields. A snippet is labeled as a snippet. A source note is not a verbatim quotation. No exact substring, quote visibility, span membership or hash equality admits recommendations or retries.

The normal, refinement and saved-retry workflows do not invoke a mandatory verifier. The active owner remains General -> Technology -> the appropriate specialist for supported technology, including Smartphone. `VerifierCriticAgent` remains an explicit optional tool-free editorial workbench capability. It cannot block or replace the owner's buying judgment. Its configured model/profile and authorized 180-second override remain available when explicitly invoked. Request refusal uses the installed OpenAI Agents SDK input guardrail, with no application phrase tripwires. Classifier timeout or invalid output is a retryable technical error.

The owner resumed live calls on 2026-10-11. Tasks 216, 214, 215 and 100A passed revised guided-browser acceptance. See [saved IDs, browser evidence, SQLite/API matches, usage and checks](TASK_216_LIVE_ACCEPTANCE.md). No P1 work started. Historical policies and recorded tests below are superseded wherever they require citations, exact provenance, source counts, mandatory verification, seller exclusions or hard budget vetoes.


Status: Current architecture and remaining design direction
Last updated: 2026-10-06

## Product Model

CartCart is a shopping discovery, comparison, and decision application. It should help a user answer what to buy, whether a candidate is a bad fit, and whether a listing or seller looks unsafe.

The product should use a guided shopping decision model. The first application
surface is a focused shopping-question prompt with a large textbox, not a
one-page research workspace. The UI may feel prompt-led, but it should not show
visible chat history. It should ask one useful question at a time, reveal only
the next needed step, and keep internal workflow mechanics out of the normal
shopper experience.

The old all-in-one homepage/workspace pattern is superseded. It is acceptable to
preserve useful backend session, run, result, source, and refinement plumbing,
but future frontend work should not expose the whole workflow on the homepage.
The normal UI should support:

- Natural-language shopping question entry.
- One-time local region setup outside the main shopping flow when no saved
  region exists.
- Progressive follow-up questions for budget, use case, constraints, and
  already-considered products only when needed.
- Inline constrained choices only when they are genuinely easier than typing.
- Back/reanswer behavior before analysis starts.
- `Skip question` for skippable optional questions.
- `Skip all and start analysis` once enough information exists.
- User-safe processing messages.
- Staged results with a final recommendation, runner-ups, alternate
  recommendation modes, comparison details, trust notes, warnings, rejected items
  when meaningful, and inspectable source evidence only when useful.

MVP is local/no-auth, English-only, desktop-first, and single-user. Mobile should remain usable, but dense desktop workflows take priority.

The initial MVP source-policy and retailer-coverage seed targets the
Philippines (`PH`), United States (`US`), South Korea (`KR`), Canada (`CA`),
Japan (`JP`), Singapore (`SG`), Macao (`MO`), Australia (`AU`), New Zealand
(`NZ`), Hong Kong (`HK`), and Taiwan (`TW`). These are prioritization targets
for source discovery, marketplace/store policy, and region-relevance scoring,
not a hard product-access allowlist. CartCart retains broad category support and
the generic fallback for shoppers outside the seeded regions. The runtime
default region remains separately configurable.

## Recommended Stack

Backend:

- Python.
- FastAPI for the HTTP API.
- Pydantic v2 for API contracts and agent structured outputs.
- OpenAI Agents SDK for typed agent steps.
- SQLAlchemy 2.0 async and Alembic for persistence and migrations.
- SQLite for MVP local persistence.
- httpx for provider calls.
- OpenTelemetry concepts from the start, with structured JSON logs and optional Logfire for local development.

Frontend:

- SvelteKit and Svelte 5.
- TypeScript.
- Tailwind CSS.
- shadcn-svelte and Bits UI for accessible component primitives.
- Formsnap, SvelteKit Superforms, and Zod for forms when needed.

Local tooling direction:

- `uv` for Python dependency management.
- `pnpm` for frontend dependency management.
- Docker Compose later for deployment-like local runs.

## Repository Shape

The monorepo has a FastAPI backend, SQLite/Alembic persistence, typed provider
and agent boundaries, an opt-in live shopping workflow, a fixture workflow, and
a SvelteKit guided shopping frontend. The backend persists sessions, run events,
research sources and evidence, products and listings, agent records, and
versioned results. Local scripts manage setup, migrations, app lifecycle, and
verification.

Current skeleton:

```text
apps/
  backend/
    alembic/
    app/
      api/
      core/
      db/
        models/
        repositories/
      main.py
    pyproject.toml
    uv.lock
    tests/
  frontend/
    src/
    package.json
    pnpm-lock.yaml
docs/
scripts/
  local/
    cleanup-artifacts.sh
    export-openapi.sh
    build-frontend.sh
    check-frontend.sh
    init-backend.sh
    init-frontend.sh
    lifecycle-common.sh
    lint-frontend.sh
    lint-backend.sh
    migrate-backend.sh
    reset-db.sh
    setup-playwright.sh
    start-app.sh
    start-backend.sh
    start-frontend.sh
    stop-app.sh
    sync-backend.sh
    sync-frontend.sh
    test-frontend.sh
    test-backend.sh
    typecheck-backend.sh
    restart-app.sh
AGENTS.md
.gitignore
README.md
supported_agents.md
```

Application structure by responsibility:

```text
apps/
  backend/
    app/
      api/
      agents/
      core/
      db/
      evals/
      schemas/
      services/
      orchestration/
      providers/
      tools/
    alembic/
    pyproject.toml
  frontend/
    src/
      lib/
      routes/
      app.css
    package.json
docs/
  ARCHITECTURE.md
  API.md
  EVALUATION.md
  OPERATIONS.md
scripts/
  local/
    init-backend.sh
    sync-backend.sh
    lint-backend.sh
    typecheck-backend.sh
    test-backend.sh
    migrate-backend.sh
    export-openapi.sh
    init-frontend.sh
    sync-frontend.sh
    lint-frontend.sh
    check-frontend.sh
    test-frontend.sh
    build-frontend.sh
    setup-playwright.sh
    start-backend.sh
    start-frontend.sh
    start-app.sh
    stop-app.sh
    restart-app.sh
AGENTS.md
supported_agents.md
```

## Guided Intake Architecture

Guided intake sits before the deeper discovery and analysis workflow. It owns the
user-facing question sequence and decides whether the next step should be a
plain-language textbox, a small inline choice block, a skip action, a
back/reanswer action, a blocked redirection, or a transition to analysis.
The frontend-facing Pydantic contract for these states lives in
`app.schemas.guided_intake`.

The guide contract must not require one large upfront form. Budget, region,
known products, use cases, deal-breakers, and product-specific details should be
captured progressively. Normal intake should ask for product names or
descriptions, not product links; CartCart is responsible for lookup and listing
matching. URL entry can exist later as an advanced corrective path, but it is not
the normal flow.

The current backend implementation provides fixture-backed guided intake
endpoints under `/api/sessions/guided` and `/api/sessions/{session_id}/guide`.
They keep guide state in fixture memory, update the persisted session
`ShoppingBrief` when the guide reaches `ready_for_analysis`, and leave the
existing `/api/sessions/{session_id}/runs` endpoint responsible for starting the
deterministic analysis run. A live OpenAI Agents SDK `ShoppingGuideAgent` now
implements the same `GuidedIntakeState` contract for isolated mock/live
workbench runs, including SDK input-guardrail checks and an `IntakeAgent`
handoff only after enough information exists. The normal shopper API is not
routed through the live guide yet.

The isolated workbench also exposes live OpenAI Agents SDK `QueryPlannerAgent`,
`DiscoveryAgent`, `CategoryRouterAgent`, `GenericProductAnalystAgent`,
`TechnologyDomainAnalystAgent`, `MonitorSpecialistAgent`,
`SmartphoneSpecialistAgent`, `LaptopSpecialistAgent`,
`EarphonesHeadphonesSpecialistAgent`, `TVSpecialistAgent`,
`SmartwatchSpecialistAgent`, `ComparisonDecisionAgent`, and
`VerifierCriticAgent` implementations behind the existing `SearchPlan`,
`DiscoveryAgentOutput`, `ProductAnalysisRoute`, `CategoryAnalysis`,
`RecommendationBundle`, and `VerificationReport` protocols.
Query planning produces region-aware shopping, review, official-source, price,
and video-review query strategy without tools, and falls back to a generic
search plan instead of blocking product categories that lack specialists.
Current discovery selects only supplied search-result source IDs for extraction, uses source quality as advisory context and returns explicit gaps when source inspection cannot finish. Category routing uses no tools, normalizes model output
through the executable catalog, sends MVP technology specialist categories
through `TechnologyDomainAnalystAgent`, and keeps
`GenericProductAnalystAgent` as the fallback for unknown or unsupported
categories. Generic product analysis uses no tools, consumes only supplied
product/listing/evidence bundles, preserves evidence and source IDs, covers
fit tradeoffs and gaps, and returns limitations instead of category refusal
when evidence is weak. Technology-domain analysis uses no tools, consumes only
supplied product/listing/evidence bundles plus the executable catalog route,
declares MVP specialist routing internally for workbench inspection, analyzes
broad technology categories without an MVP specialist, and falls back to
generic analysis for non-technology input or domain failure. Monitor specialist
analysis uses no tools, runs only for monitor-scoped products, covers
monitor-specific panel, resolution, refresh-rate, ergonomics, port, and tradeoff
checks from supplied evidence, and falls back to technology-domain or generic
analysis instead of forcing non-monitor input through monitor logic.
Smartphone specialist analysis uses no tools, runs only for smartphone-scoped
products, covers camera, battery, update-support, performance, and region/model
caveats from supplied evidence, and falls back to technology-domain or generic
analysis instead of forcing non-phone input through smartphone logic.
Laptop specialist analysis uses no tools, runs only for laptop-scoped products,
covers CPU, RAM, storage, battery, display, ports, weight, and upgradeability
from supplied evidence, and falls back to technology-domain or generic analysis
instead of forcing non-laptop input through laptop logic.
Earphones/headphones specialist analysis uses no tools, runs only for
earphone/headphone-scoped products, covers ANC, comfort/fit, microphone,
battery, codec/device fit, and source IDs from supplied evidence, and falls
back to technology-domain or generic analysis instead of forcing non-audio
input through headphone logic.
TV specialist analysis uses no tools, runs only for TV-scoped products, covers
panel/backlight, HDR, motion, gaming inputs, room brightness, size fit, and
source IDs from supplied evidence, and falls back to technology-domain or
generic analysis instead of forcing non-TV input through TV logic.
Smartwatch specialist analysis uses no tools, runs only for smartwatch-scoped
products, covers phone compatibility, health sensors, battery, durability, app
ecosystem, and source IDs from supplied evidence, and falls back to
technology-domain or generic analysis instead of forcing non-watch input
through smartwatch logic.
Seller/listing trust analysis uses no tools, consumes only supplied listing
records, evidence, and deterministic trust-rule assessments, and keeps product
quality separate from listing trust. Actual price and listing contradictions inform the model. It may improve or worsen the rule-derived assessment and must preserve the scope of its explanation.

Region setup is outside the main shopping question flow. If no region preference
or explicit refusal is saved locally, the frontend can show a lightweight setup
prompt explaining that location helps show products the user can actually buy.
The user can provide a region or refuse to answer. If region setup interrupts an
already-submitted shopping question, the frontend should automatically resume
the pending guided flow after either choice. Backend defaults remain allowed for
fixture/local operation, but must be marked as defaulted or inferred rather than
user-confirmed.

The OpenAI Agents SDK input guardrail classifies shopping scope and unsafe or illegal requests before research. The application has no phrase-list refusal tripwires. A blocked input receives the classifier's short redirection. Classifier errors and timeouts are retryable technical failures.

## Workflow Architecture

CartCart uses deterministic orchestration around agent-owned research decisions.
The backend owns stage order, typed tool safety, budgets, persistence, schema and run identity validation, trace IDs, and user-safe
events. `DiscoveryAgent` owns semantic source classification, relevance,
candidate/model hints, review-to-candidate leads, and follow-up search/fetch
decisions. `ExtractionAgent` is the primary interpreter of persisted snapshots
and may return zero, one, or many cited products/listings and evidence records
from a page. Mechanical HTML/text/JSON-LD/currency/identifier parsing remains
available as signals or explicit fallback, never as an undisclosed semantic
gate. Review evidence stays separate from retailer offers. Failed optional
sources become explicit gaps; a category-incompatible fixture is not a valid
fallback.

Run-scoped OpenAI Agents SDK `search_sources` and `fetch_source` function tools
now wrap the approved search/extraction providers. They validate bounded agent
choices, resolve fetches only from persisted same-run search IDs, commit source
and snapshot records before revealing IDs, and return safe excerpts instead of
credentials or raw provider metadata. The executable catalog approves search/fetch
and hosted OpenAI `web_search` for `DiscoveryAgent`. The four source specialists also receive hosted search alongside their site tools. Live discovery receives
all three tools with optional model choice and emits a
structured decision for every observed source, including generic provider
results; planned query source types are not stamped onto provider results.

Owner provider tools, evidence helpers, and hosted citation stores share the
normal run's request database session. Their database contexts use one access
guard owned by that session, including research tools created for a receiving
owner. The guard covers reads, writes, flushes, and commits so concurrent SDK
tools cannot read during another tool's commit. Provider requests and nested
source-agent execution run outside the guard. Factory-backed tool sessions
retain their separate lifetimes. Returned source and quote IDs remain durable
before the tools expose them.

`POST /api/sessions/{session_id}/runs` executes synchronously; search is called by
orchestration, live `DiscoveryAgent` can conduct bounded follow-up searches and
select generic results for inspection. Live `ExtractionAgent` reads selected
persisted snapshots through a bounded same-run tool and returns validated
zero/one/many products, listings, evidence, mentions, and gaps. For a shopper's
named candidate, it also returns cited confirmed or possible listing matches;
the query or search title cannot establish identity. Its listings feed
the current shortlist path. Cited mentions needing an offer lookup can
trigger bounded DiscoveryAgent follow-up cycles before the shortlist: at most
twelve leads per handoff, two follow-up discovery calls, four extraction cycles,
and twelve discovery-selected fetched pages (direct user-added URLs are a
separate input path). ExtractionAgent
must explicitly match
prior review evidence to a found product; otherwise the claim remains
source-scoped. Editorial snapshots cannot produce retailer listings, and a
collection URL cannot be reused as each item's direct offer URL. Each cycle
reviews candidate/evidence counts and gaps; a later discovery call sees typed
candidate, seller, citation, and gap summaries and chooses further sources.
Provider-type labels cannot veto a
selected generic result. Search results, snapshots, and evidence are stored;
per-source decisions, extracted entities, gaps, and lead matches are retained
in stage research activity. Live result persistence uses only the grouped
agent-validated shortlist, never the monitor fixture. Fixture mode now invokes
network-free `DiscoveryAgent` and `ExtractionAgent` contract replays through the
same bounded research loop. The complete monitor replay is activated only for
monitor requests with fixture providers; TV, furniture, and other unsupported
fixture categories receive an honest no-strong-buy result without monitor
products. Normal shopping runs reject mixed live-provider/fixture-agent mode
before source calls, with an actionable configuration error. Direct isolated
provider probes remain available. The normal run path remains
fixture-first; live typed agents require explicit configuration.

All model-running agents receive the current UTC date and explicit budget-intent
guidance through their shared SDK configuration. Research roles also receive
instructions for focused regional queries, official sources, publication versus
event dates, blocked-source recovery, and the distinction between product advice
and verified purchase offers. Tools expose extracted publication dates when
available. Hosted search uses medium context and requests actual search-source
metadata. The General owner uses its configured turn and timeout budgets for the
whole handoff chain; unrelated specialist overrides cannot shorten that chain.
It permits six hosted search actions and eighteen hosted actions in total, so
opening and finding page text do not consume a two-search limit.

Phone research guidance prioritizes releases within 365 days, permits models up
to two years old as value alternatives, and preserves explicit older-model
requests with age/support caveats. An explicitly unconstrained budget favors
current flagships. Missing budget does not imply unlimited budget. The owner
checks credible launches within about 60 days and distinguishes confirmed dates
from expectations. These are model instructions, not a deterministic launch-date
filter; live research quality requires manual validation. Known phone requests
are instructed to transfer early through General, Technology, and Smartphone.
Model exceptions, timeouts and unrecovered owner validation failures are failed
shopping runs with saved activity, rather than completed no-strong-buy decisions.

Agents should produce typed outputs at each stage. Search, fetch, extraction, persistence, and scoring support should live behind tools or services with clear contracts. The target SDK handoffs are limited to General -> Technology -> eligible specialist ownership; backend code remains responsible for the persisted workflow and operational boundaries.

Production SDK wrappers use the shared bounded model gateway described in
[context management](CONTEXT_MANAGEMENT.md). Each model turn, transfer and nested
source call projects exact typed state and can retire explicitly processed
bodies into exact useful facts, bounded caution/gap state and canonical lookup
references. New and unprocessed text stays visible. Omitted passages remain
unreviewed, and SDK call pairs stay intact. Extraction reads one initial page and defers other assigned IDs. Comparison consumes available saved research. Optional editorial assistance uses supplied context without source rereads or per-claim revalidation. Shared
pre-call reservations preserve decision/verification room; the existing owner
and source ceilings remain. Budget failures stop the shopping run explicitly.
No extra model summarizer or temporary evidence store is introduced.

Recommended stages:

1. User sends a first shopping question from the focused prompt.
2. If needed, the frontend handles one-time local region setup outside the main
   shopping flow and resumes the pending question.
3. Guided intake asks one useful follow-up at a time, supports skip/reanswer
   behavior, and determines when enough information exists.
4. Shopping-scope and safe-product guardrails block or redirect unsuitable
   requests before discovery.
5. Intake produces a typed `ShoppingBrief`.
6. Query planning creates region-aware search and source plans.
7. `DiscoveryAgent` uses approved, bounded search tools to classify inspected
   results, including generic provider results, and decide what to inspect.
8. Approved retrieval tools persist snapshots; `ExtractionAgent` interprets each
   page and keeps review evidence, product mentions, and listings distinct.
9. Cited product/listing candidates may drive bounded follow-up listing lookup;
   backend validation persists valid entities and explicit gaps.
10. Deduplication groups obvious duplicates while preserving all listing-level
    seller, price, availability, and source-quality differences.
11. Reusable source-intelligence checks add relevant YouTube/video, Reddit/community, Amazon, and IKEA evidence bundles for grouped products without replacing normal web/listing evidence.
12. Category analysis evaluates product fit, specs, tradeoffs, and evidence gaps.
13. Seller/listing trust analysis evaluates buyer-safety signals.
14. The owning model recommends useful options with reasons, tradeoffs and unknowns, or explains its no-option judgment. A winner and modes are optional.
15. Persist model-owned advice directly. Optional editorial review is an explicit workbench capability, outside the run stage sequence.
16. The frontend renders staged results. A refinement stores a pending run
    and a typed recompute plan linked to the exact prior result version.
    Execution runs fresh research when the plan invalidates it, or reads
    validated candidate evidence from the prior run for budget and mode
    changes. It then produces a new model-owned decision. Results
    are numbered across the session, and failed runs leave the last successful
    result accessible. Considered-product outcomes are snapshotted per run so
    later corrections do not change older result views. The shopper opens one
    contextual refinement action, answers a focused prompt, and retains the
    prior result during execution or failure. A collapsed decision history
    loads saved context and results through session-scoped endpoints, without
    exposing chat history or internal stages.

## Agent And Source Capability Model

`supported_agents.md` is the public, human-editable source of intent for supported agents, reusable source capabilities, routing, and fallback behavior. Runtime code must not parse that Markdown file. Agent wrapper contracts, deterministic fake implementations, and the validated executable catalog live under `apps/backend/app/agents`; these define typed input/output boundaries, current routing categories, fallback paths, reusable source capabilities, provider requirements, and invocation modes. In fixture mode, `ShoppingGuideAgent` and `ShoppingScopeGuardrail` use guided intake schemas. Live `ShoppingGuideAgent`, `IntakeAgent`, `QueryPlannerAgent`, `DiscoveryAgent`, `CategoryRouterAgent`, product analysts, `SellerListingTrustAgent`, `ComparisonDecisionAgent`, and `VerifierCriticAgent` have model-running implementations. The live shopping run now invokes `SourceIntelligenceManagerAgent` after deduplication. This model-running parent selects relevant YouTube, Reddit, Amazon, and IKEA SDK specialists through `Agent.as_tool()`, each with bounded source tools and cited bundle validation. The manager passes only validated bundles to existing persistence and downstream evidence consumers. Fixture mode retains provider-service simulation without recording a model call. The IKEA specialist selects official country-path search results or permitted persisted snapshots and validates cited source IDs and supported fields before evidence creation.

Each catalog entry also declares an operator-configured OpenAI run profile
(`fast`, `strong`, or `default`). The shared runtime resolver combines an
exact-agent override, assigned profile, optional default profile, and global
fallback for model, reasoning effort, timeout, and max turns. SDK runners, workbench output,
trace metadata, and persisted model-backed stage records use that resolution;
fixture/mock SDK-agent execution can report the configured model without calling it.
Provider-service probes instead report no resolved or called model, with a
separate planned model for the future specialist.
The current fixture shopping-run workflow also calls the typed
`SellerListingTrustAgent` contract for listing trust review, seeded by
deterministic trust rules, before final fixture recommendations are persisted.
The isolated agent workbench in `app.agents.workbench` is the local-only
debugging path for invoking one catalog-allowlisted agent through its typed
protocol without starting the full shopping workflow. It owns starter fixture
scenarios for fake agents plus mocked/live scenarios for implemented OpenAI
Agents SDK steps such as `ShoppingScopeGuardrail`, `ShoppingGuideAgent`,
`IntakeAgent`, `QueryPlannerAgent`, `DiscoveryAgent`, `CategoryRouterAgent`,
`GenericProductAnalystAgent`, `TechnologyDomainAnalystAgent`,
`MonitorSpecialistAgent`, `SmartphoneSpecialistAgent`,
`LaptopSpecialistAgent`, `EarphonesHeadphonesSpecialistAgent`,
`TVSpecialistAgent`, SDK specialist scenarios for YouTube, Reddit, Amazon, and IKEA,
with separate provider-service fixture scenarios. It is disabled
unless the local workbench flag is
explicitly enabled.

Required MVP agent roles include:

- `ShoppingRunOrchestrator`
- `ShoppingGuideAgent`
- `ShoppingScopeGuardrail`
- `IntakeAgent`
- `QueryPlannerAgent`
- `DiscoveryAgent`
- `ExtractionAgent` (live primary snapshot interpreter)
- `DeduplicationReviewAgent`
- `CategoryRouterAgent`
- `GenericProductAnalystAgent`
- `TechnologyDomainAnalystAgent`
- `MonitorSpecialistAgent`
- `SmartphoneSpecialistAgent`
- `LaptopSpecialistAgent`
- `EarphonesHeadphonesSpecialistAgent`
- `TVSpecialistAgent`
- `SmartwatchSpecialistAgent`
- `SellerListingTrustAgent`
- `ComparisonDecisionAgent`
- `VerifierCriticAgent`

`GenericProductAnalystAgent` is the current per-product analysis fallback for normal shopping categories. `TechnologyDomainAnalystAgent` is an MVP domain layer so technology routing is modular from the beginning. MVP technology specialists cover monitors, smartphones, laptops, earphones/headphones, TVs, and smartwatches. Reusable source intelligence capabilities include required MVP YouTube, Reddit, Amazon, and IKEA source agents plus later marketplace product intelligence, official brand-store lookup, professional review sources, and broader community discussion signals. Generic product analysis remains available in the current typed-step workflow when no narrower specialist exists or when a specialist/domain fallback is needed.

### General owner and SDK handoffs

The live workflow retains typed analysis steps after guided intake.
`CategoryRouterAgent` returns `ProductAnalysisRoute`; Python selects analysts
that return `CategoryAnalysis`. `ComparisonDecisionAgent` remains a separate
typed capability but no longer writes the live owner result. Those analysis
routes are application routing, not SDK handoffs.
`Agent.as_tool()` source delegation likewise returns bounded evidence, not
shopper-request ownership. The opt-in live API now enters the SDK
`GeneralShoppingAgent` after intake, before category routing, and records its
draft and research trace. The last SDK owner now authors the persisted result;
the older typed analysis path remains an evidence input in live runs. General can make a real SDK handoff to
Technology when the handoff context matches a technology request. The SDK's
completed handoff item and last agent determine the recorded draft owner;
Technology may now SDK-handoff to one matching catalog-approved specialist.
The specialist returns the owner draft directly, and the run records both
completed transfer items and the SDK's last agent. The per-product
Technology `CategoryAnalysis` path remains separate, and
OpenAI's hosted web-search tool is attached to live `DiscoveryAgent`, scoped
source specialists, listing trust, and all eight shopper owners.
Provider `search_sources` and `fetch_source` remain separate tools.

The catalog resolves categories for both owner-handoff arguments and the
buyer's brief. Phone aliases include `phone`, `smartphone`, `mobile phone`,
`phones`, `smartphones`, and `mobile phones`. These finite aliases share the
existing Smartphone route and fallback chain. Category and depth checks still
apply at both SDK transfer boundaries. A rejected category records
`rejected_handoff` in internal `general_owner` activity, with approved agent
names, catalog route paths, category length, and an exact known category label
or `null`. This diagnostic does not establish a completed SDK transfer.

The owner design keeps the guided UI: `ShoppingGuideAgent` asks progressive
questions, `IntakeAgent` normalizes the brief, and the backend applies
scope/safe-product checks before a run. Every ordinary request then enters
`GeneralShoppingAgent` as first model owner. General can research and finish
any broad request, including one without a specialist, with useful advice and optional sources, or an explicit no-option judgment. It may SDK-handoff only to
`TechnologyDomainAnalystAgent`. Technology may finish broad technology
requests or hand off only to a catalog-approved implemented monitor,
smartphone, laptop, earphones/headphones, TV, or smartwatch specialist. The
specialist is the last model owner and authors the shopper-facing draft.
No source, intake, generic-analysis, comparison, or verification agent is a
target in this shopper-owner handoff graph. `GenericProductAnalystAgent`
continues as an evidence-only `CategoryAnalysis` capability in the current
workflow; it is distinct from General.

Each active owner gets bounded access to persisted research, approved provider
search/fetch, source lookup, candidate comparison, advisory listing trust and
optional source-manager consultation. A persisted product or a named candidate
can scope that consultation without an exact quotation. The source manager
delegates to YouTube, Reddit, Amazon and IKEA specialists within their existing
permissions. Backend code owns credentials, run/source identity, URL safety,
context/spending limits and persistence. The last owner authors the advice.
Candidates can be saved without a listing or citation. Persist the actual handoff
chain, author, available associations, usage and immutable result version.

Shopper owners return a bounded primary rationale and optional candidate reasons, tradeoffs, unknowns and warnings. Projection persists each selected candidate even without sources, a checked listing or mode records. It retains known source associations while omitting invalid optional references. Operational identity errors use a technical failure. Missing information cannot become a deterministic no-option result.

Hosted OpenAI web search is implemented alongside existing approved provider
tools for live `DiscoveryAgent`, all eight shopper owners, and the four
site/source specialists, and as a scoped optional tool for live
`SellerListingTrustAgent`. Owners also have typed provider search/fetch and
optional source-note recording. Hosted citations, search snippets and fetched pages are labeled available information. The owning model weighs them without source-count, review, exact quote or official-only eligibility. Hosted search is not planned for the source manager as unrestricted search
or for intake-only, extraction-only, comparison-only, and verification-only
roles. The model may choose either research path; a search hit is not a
verified listing. Available snippets and fetched content can inform qualified model advice without a separately recorded citation.

Discovery reads real SDK `web_search_call` items and URL annotations. Public,
policy-allowed cited URLs are persisted as run-scoped search results and
unextracted snapshots, with weak source-metadata evidence IDs for the exact
cited span. Hosted citations have no automatic product/listing authority;
selected pages still pass approved extraction and backend claim validation.
The buying region is sent as an approximate country hint, allowed domains are
passed to hosted search when configured, and all returned URLs are checked
again before persistence. A missing citation or failed hosted call is recorded
as a discovery gap. The tool builder checks catalog permissions, domain limits,
and region scope independently of the selected model. Environment settings,
profiles, and exact-agent overrides supply the SDK model. The OpenAI API
validates the submitted model, tools, and reasoning settings. API rejection
keeps the existing explicit failure or fallback status and does not trigger
changes to an agent's selected model or removal of required tools. Technology
owner recovery after specialist failure remains separately recorded. Fixture
runs remain network-free.

Live listing trust receives source identity, buyer region, available seller information and advisory rule scores. The model can improve or worsen that assessment. Official stores need no mandatory background check. Meaningful adverse findings retain their listing scope. The final owner model weighs those findings without deterministic score exclusions.

Each live source specialist has `tool_choice=auto` and a source-specific hosted
domain filter: YouTube, Reddit, the target Amazon marketplace, or the official
IKEA domain. IKEA citation URLs must also match the selected regional path.
The manager passes one run-scoped citation store to its nested specialists;
isolated live workbench runs use disposable persistence. SDK call items,
returned URLs, retained citations with source/snapshot/evidence IDs, and
rejected URLs are recorded under the specialist's name. A retained citation
is only weak source metadata. Transcript claims still require validated
segments, community signals require read discussions, marketplace offers
require the Amazon read tool, and IKEA prices or stock require official
regional read evidence. Missing or failed hosted calls yield gaps. Model
profiles reach the API with the required scoped tool, and API rejection leaves
an explicit source evidence gap.

Required MVP reusable source intelligence roles include:

- `YouTubeReviewIntelligenceAgent`
- `RedditCommunityIntelligenceAgent`
- `AmazonProductIntelligenceAgent`
- `IKEAStoreIntelligenceAgent`

Reusable source intelligence agents are not category specialists and are not final decision agents. They retrieve, normalize, quality-score, and summarize source-specific evidence that can be reused by discovery, product/domain analysts, trust analysis, and the final decision flow. Their scope is usable evidence retrieval, not availability-only checks. Depending on the source, they may return product-page information, review summaries, recurring owner complaints, seller/fulfillment signals, price/currency, regional availability, shipping/store context, warranty/return context, and explicit evidence gaps.

The YouTube SDK specialist rejects fabricated quotes and wrong-source selections.
Its metadata-only fallback uses the same deterministic bias annotation as the
fixture provider service. It preserves visible sponsorship and affiliate
context from approved metadata and any transcript already read, then discards
transcript-backed product claims. A timeout before transcript reads preserves
`not_checked` availability. The catalog declares its evidence-gap fallback.

The Amazon SDK specialist now selects candidate products and marketplace source IDs through bounded approved tools. Its SerpAPI search tool exposes valid ASIN/title hits without the provider's older semantic name-match gate; the agent chooses which hit to read. Its typed output selects source-backed provider facts and marks ASIN/variant ambiguity; backend validation enforces neutral URLs, source/evidence IDs, and non-removable hard listing-risk warnings. Live shopping runs reach it through the source manager's SDK agent tool; fixture runs continue to use the provider service.

## MVP Behavior Rules

These rules define the minimum behavior expected from schemas, tests, agents, source policy, and result rendering.

### Budget handling

Pass budget intent, known prices, currencies and comparable over-budget amounts
to the owning model. The model may recommend a slightly over-budget option with
an explanation. There is no hard cap, fixed stretch percentage or required
within-budget companion. Missing and unlimited budgets remain distinct. Unknown
or incomparable prices are not labeled within budget. Modes are optional.

### Source and marketplace policy

Source classes, reputations, scores and historical exclusions are advisory.
Usable content from unknown or mixed-marketplace sources remains available
through approved access paths. Preserve seller, variant, regional availability,
price and source context. Official product pages and company announcements are
useful sources, and reviews are optional. Basic URL/content validity and network
access protections remain operational requirements.

### Seller and listing trust

Product quality and listing trust remain separate. The model may improve or
worsen the rule-derived assessment. An official store provides acceptable seller
context without a mandatory review count or checklist. Actual contradictions and
implausible prices inform model judgment with their scope. Missing reviews,
warranty, seller details or price are unknowns and cannot alone exclude a product.
The owner preserves its specific offer warnings. Trust levels and scores cannot
remove a card or neutral link.

### Evidence and confidence

- Available source associations and confidence are advisory.
- Unknown, inferred, user-reported and source-confirmed values remain distinguishable.
- The model preserves material conflicts and qualifies uncertain current facts.
- Source-specific information retains regional, seller, variant and availability context.
- Sources and exact quotations are optional. Source notes are labeled without implying verbatim quotation.

### Current Broad Category Fallback

- Every normal shopping query must be eligible for `GenericProductAnalystAgent`.
- Technology products should route through `TechnologyDomainAnalystAgent` and then to an MVP technology specialist when the category matches monitors, smartphones, laptops, earphones/headphones, TVs, or smartwatches.
- If no specialist matches, the technology domain may analyze the product broadly when it is technology-related.
- If the technology domain does not apply, fails, times out, or produces insufficient confidence, generic analysis remains available.
- The app should not show an unsupported-category error for ordinary consumer products solely because no specialist exists.
- Tests should cover non-technology generic fallback, technology-domain routing, each MVP technology specialist route, and fallback from specialist to domain to generic.

### User-Added Products

- User-added products must enter the same deduplication, extraction, trust, analysis, and decision pipeline as app-generated candidates.
- Normal guided intake should ask for product names or descriptions, not product URLs.
- Name- or description-based user-added products remain hints through scoped lookup queries and DiscoveryAgent selection. ExtractionAgent explicitly links cited listings to a hint as confirmed or possible; a query hit alone is not a match. Ambiguous variants stay separate while each listing keeps its seller and trust context.
- URL-based user-added products are an advanced or corrective path; the run workflow fetches and extracts them through the normal source/listing pipeline before deduplication, then marks the deduped product/listing as user-supplied.
- Manual fallback is available for an inconclusive researched candidate or an explicit shopper correction. It preserves the shopper's reported identity and optional seller, price, availability, review, warranty, and specification details as unverified input, with per-field unknown/user-reported status. A manual-only candidate remains labeled user-reported and can inform the owning model without independent evidence.
- A user-added product can win, place as a runner-up, be rejected for a meaningful reason, or be excluded because the listing is unsafe.
- User-added products should be marked as user-supplied in stored state and result output so the UI can distinguish them from discovered candidates.

### No-option decisions and warnings

The model recommends by default. It may discourage a purchase for strong adverse information and suggest useful alternatives. Missing reviews, citations, seller metadata or price cannot alone erase options. A specific warning retains its product or offer scope. Technical failures use retryable failed runs rather than buying judgments. No-option results carry the model's own reason.

### Conditional Why-Not Output

- Rejected-item or "why not" output should appear only when there is a meaningful negative reason.
- Meaningful reasons must be explicit in structured output. MVP avoid reason codes cover suspicious listing, poor fit for stated constraints, material overpaying, unsuitable products and meaningful adverse findings.
- Duplicate/near-duplicate inferior listings, region unavailability, or better equivalent alternatives may be represented only when they map to one of the explicit avoid reason codes or a later schema expansion adds a specific code.
- Ordinary non-winning candidates do not need forced negative explanations.
- The result schema should allow rejected items to be absent or empty.
- Tests should cover both cases: a result with meaningful rejected items and a normal result where no artificial why-not section is emitted.

## Persistence Architecture

SQLite is the canonical MVP persistence layer. Store structured entities and links in SQLite, including:

- Sessions and user inputs.
- Guided intake state, current user-facing question, answer history for internal
  state, skip/reanswer metadata, and region setup/refusal state where backend
  persistence is useful.
- Shopping briefs.
- Search runs and search results.
- Source snapshots and extracted evidence.
- Product listings and canonical product groups.
- Candidate shortlist membership.
- Seller/listing trust assessments.
- Agent run records and typed outputs.
- Recommendation bundles.
- Refinement history.
- Eval cases and local eval summaries when useful.

Use file storage under `data/` for large raw artifacts if needed, such as HTML snapshots, extracted Markdown, screenshots, trace exports, or eval exports. SQLite should hold references to those artifacts.

Do not build cross-session user preference profiling for MVP. OpenAI Agents SDK session memory may be used for conversational context only if it improves refinement; it must not be the only application state store. Large local artifacts should follow the retention policy in `docs/OPERATIONS.md`; structured IDs, links, and evidence references remain in SQLite.

Vector search is deferred. Use SQLite indexes and possibly FTS5 first. Consider LanceDB later only if semantic retrieval over saved source snapshots becomes materially useful.

## Source And Retrieval Architecture

Search and extraction should be adapter-based. Initial provider interfaces should cover:

- General web search.
- Source extraction.
- Optional shopping-specific product search.
- Reusable source-intelligence providers such as video search, transcripts, Reddit/community retrieval, Amazon product/listing/review retrieval, IKEA regional store lookup, marketplace product intelligence, and official store lookup.

Static source retrieval uses `HttpSourceFetcher`: it sends an explicit CartCart user
agent and HTML accept policy, validates that the initial URL and every redirect resolve
only to public network addresses, follows a bounded number of redirects, enforces the
configured timeout and decoded-body limit while streaming, and rejects non-HTML or
unsuccessful responses. Retryable timeouts, rate limits, and server failures use bounded
attempts and backoff; access-control responses such as HTTP 403 are never bypassed.
Completed bodies are written atomically beneath `data/artifacts/raw-sources/`; the
structured `SourceSnapshot` stores the relative artifact path, content metadata, and
hash. Fetching does not perform text extraction, which remains a separate stage.
`StaticPageTextExtractor` reads that stored artifact without another network request
and uses Trafilatura to add main text, title, author, description, site name,
publication date, language when available, and word count to the same
`SourceSnapshot`. Expected per-source failures return a failed or excluded snapshot
with a safe failure code instead of aborting the shopping run. Pages with no usable
static text retain the raw artifact and are marked as failed extraction so later policy
can consider an optional dynamic path.
`DynamicExtractionPolicy` is the decision point for that path. It always requests
static extraction first, accepts usable static output, and considers dynamic
extraction only after static output is failed, partial, or below the configured
minimum word count. Excluded sources, search-result records, and video records do
not enter browser extraction. Dynamic fallback is disabled by default and remains
optional even when enabled; the policy returns a decision but does not launch
Playwright, Crawl4AI, or any other browser runtime. Sparse static results are marked
partial and retain the policy decision metadata.

`ProductListingExtractor` is a legacy/test helper, not a shopping-run semantic
extraction authority in either fixture or live mode. It can propose mechanical fields from a
snippet or static page, including exact model/SKU/UPC/EAN, URL, price, currency,
seller and region hints, but yields at most one linked
`CanonicalProduct`/`ProductListing` and declines review pages. Live
`ExtractionAgent` interprets persisted pages first, separates product, seller,
listing, and review facts, and may return zero, one, or many cited entities and
explicit gaps. Invalid schema, missing same-run snapshot IDs, unsupported
listing URLs/prices, or malformed model output fail closed to a gap rather than
silently invoking the legacy normalizer. Review-derived leads enter the bounded
discovery/fetch/extraction loop before shortlist construction.

`DeterministicProductDeduplicator` is the conservative product grouping layer
for obvious duplicates. It canonicalizes listing URLs with the source URL
policy, extracts conservative retailer product IDs such as Amazon ASINs or
explicit product/SKU query IDs, and collapses when canonical URL, same-retailer
retailer ID, UPC, EAN, SKU with exact retailer/brand support, or exact
brand/model evidence matches. After exact matching, normalized title/spec
similarity can produce `same_product`, `same_family`, `uncertain`, or
`different_product` review outcomes. Only high-confidence `same_product`
outcomes collapse candidates; `same_family` and `uncertain` outcomes preserve
separate candidates for later review.

The run orchestrator invokes this deduplicator immediately after extraction.
That stage persists one canonical product per group, preserves every grouped
listing, writes one shortlist membership per grouped product, and emits pre/post
dedupe counts before source-intelligence and later analysis stages run.

`SourceEvidenceCreator` constructs typed evidence from parsed page signals in
the fixture/helper path. In live research, `ExtractionAgent` interpretation
decides which product,
listing, warranty, availability, or review claims a source actually supports;
the backend validates referenced snapshot/target IDs, persists evidence, and
detects mechanical conflicts without silently choosing a winner. Neither this
helper nor source-domain scoring may invent a product or decide whether a
review is a retailer offer.

The implemented backend provider boundary lives under `apps/backend/app/providers`.
`SearchProvider`, `ExtractionProvider`, and optional `ShoppingProvider` are async
protocols that return existing typed source and product schemas. Provider options
carry a `SourceAllowAvoidPolicy` so orchestration can pass explicit allow and
avoid rules without hard-coding a single marketplace, source category, or search
vendor. Deterministic fake providers live beside the contracts for fixture-mode
tests. In a normal live-agent workflow, unavailable, unconfigured or credential-
missing providers return empty/disabled evidence, never fixture sources, page
text, transcripts or offers. Explicit test injection still permits offline
fixtures. The first live adapter is `TavilySearchProvider`, which uses Tavily's HTTP
Search API behind the same `SearchProvider` protocol. It maps responses into
`SearchResult`, keeps source quality unknown for the separate deterministic
scoring layer, applies domain allow/avoid rules through Tavily's domain filters,
and does not retain raw page content or API secrets.

Configured page extraction uses `HttpStaticExtractionProvider` as the single
runtime boundary. It composes the bounded `HttpSourceFetcher` and
`StaticPageTextExtractor`, preserves the requested page source type, and returns
the resulting stored and extracted `SourceSnapshot`. Runtime modes are explicit:
`fixture` is deterministic, `disabled` returns an excluded snapshot without a
request, and `http_static` performs the implemented HTTP/static path when its
enabled flag is true. Tavily is not an extraction setting. The optional generic
`ShoppingProvider` remains a contract/fake for test substitution and has no
runtime setting; SerpApi configuration belongs only to Amazon intelligence.

YouTube video discovery uses `YouTubeDataApiVideoSearchProvider` behind the
`VideoSearchProvider` protocol. It calls the official YouTube Data API
`search.list` endpoint for relevant video snippets and `videos.list` for
duration metadata. Results preserve video ID, neutral watch URL, title,
description, channel, publish timestamp, and duration when returned. The
adapter is metadata-only: transcript availability remains `not_checked`, no
caption endpoint is called, and no transcript claim is inferred.

`YouTubeTranscriptIngestor` is the separate transcript boundary. Fixture mode
uses `FakeTranscriptProvider`; configured live mode uses
`YtDlpTranscriptProvider`, an approved third-party strategy for public captions.
The live adapter accepts only a validated YouTube video ID and matching URL,
constructs a fixed backend-owned `yt-dlp` argument list, requests manual
subtitles before automatic captions, and never downloads video or audio. It
ignores user yt-dlp configuration, disables plugins and remote EJS components,
uses the configured Deno runtime, bounds subprocess time/output/temp storage,
and always removes its temporary directory. The runner receives the existing
`temp_storage_limit_bytes` alongside timeout and output bounds, samples disk
usage every 10 ms, and stops/reaps owned writers before cleanup. POSIX runs
use a separate process group so cancellation and failures also stop descendants.
Sampled enforcement permits growth during one poll plus scheduling and
termination delay; it is not a hard filesystem quota. WebVTT parsing is deterministic and
preserves language and timestamps while removing duplicate rolling-caption
text. Missing dependencies, unavailable or restricted captions, rate limits,
challenge failures, and other provider failures become sanitized explicit gaps;
live mode does not substitute fixture transcript text. `VideoEvidenceCreator`
accepts only claims found in cited transcript segments, derives timestamp
references from those segments when needed, and otherwise emits source-metadata
evidence that explicitly says no transcript-backed product claim was created.

Reddit community discovery uses `RedditCommunityDiscoveryProvider` behind the
`CommunityDiscussionProvider` protocol. It composes the configured general
`SearchProvider`, adds `site:reddit.com` query scope plus a `reddit.com` domain
allow rule, rejects non-Reddit results, parses subreddit/thread/comment context
from public URLs, and applies deterministic community source-quality scoring.
Search excerpts are returned as qualitative evidence with warnings. Full public
page text is used only when an approved upstream provider supplies it; this
adapter does not fetch Reddit pages directly and records missing extraction,
recency, engagement, removed content, and no-result cases as explicit gaps.
`CommunityEvidenceCreator` requires each qualitative claim to appear in every
cited bundled discussion summary, preserves all cited thread/comment source IDs
for recurring signals, and rejects unsupported product facts instead of
creating evidence from them. Stale, excerpt-only, low-context, and anecdotal
signals remain explicit evidence-quality warnings.

Amazon product intelligence uses `SerpApiAmazonProductIntelligenceProvider`
behind the `AmazonProductIntelligenceProvider` protocol. It uses SerpApi's
documented Amazon Search API for conservative ASIN discovery when no Amazon
listing is supplied, then the Amazon Product API for structured product-page,
offer, delivery, and review-summary fields. The adapter preserves marketplace
domain and country, ASIN/listing identity, selected seller and ship-from
context, requested ship-to region, product facts, rating/review counts, review
summaries, third-party seller warnings, and variant/review ambiguity. Evidence
links are rebuilt as neutral Amazon `/dp/{ASIN}` URLs; provider, tracking, and
affiliate URLs are not propagated.

`AmazonProductEvidenceCreator` is the provider-independent evidence boundary.
It converts approved normalized listing context into product, listing, seller,
review, and region evidence; emits explicit gaps for missing product facts,
seller/fulfillment, review access, or inconclusive shipping; and rejects
tracked or affiliate-style listing URLs before evidence is created.

IKEA regional store intelligence uses `IKEARegionalStoreDiscoveryProvider`
behind the `IKEAStoreIntelligenceProvider` protocol. It composes the configured
general `SearchProvider`, scopes queries to the expected official IKEA domain
and country path, and rejects results outside that regional path. Accepted
results preserve the official URL, country/region, product number and page
information, local price/currency, and stock, pickup, store, or delivery signals
when present in search metadata. Unsupported regions, missing products, absent
price or delivery details, and unavailable products produce explicit evidence
gaps. The adapter does not fetch IKEA pages directly and never converts global
brand presence into a shipping or availability claim.

`IKEAStoreEvidenceCreator` is the provider-independent evidence boundary. It
accepts approved normalized regional store context, validates that source URLs
are neutral official URLs on the declared IKEA country path, and creates
separate product and region evidence for product-page facts, local
price/currency, availability, and store/delivery context. Missing or unavailable
fields remain explicit gaps, and every purchase-context claim warns that it does
not establish availability or shipping outside the declared region.

Reusable source-intelligence providers are also defined in the provider layer.
The agent contract and executable catalog define four reusable source roles for
YouTube, Reddit, Amazon, and IKEA. Live runs delegate to their SDK agents through
the source manager; fixture runs use provider services without model calls.
Both paths return evidence bundles rather than final recommendations. The
provider boundary exposes enabled state, supported
capabilities, official/user-authorized access, domain-scoped search support,
public-page extraction support, Amazon product/listing/review support, regional
ship-to evidence support, IKEA regional official-store support, and compliance
notes. Fake implementations can return metadata-only video evidence, available
transcript segments with language and timestamps, explicit unavailable or
failed-transcript gaps, Reddit/community
evidence gaps or recurring discussion signals, Amazon product/listing/review
evidence, IKEA regional store evidence, and disabled-provider results without
making live calls.

The shopping workflow invokes those provider boundaries after normal extraction
for a small scoped set of candidate products/categories. YouTube metadata is
selected through `VideoSearchProvider`, transcripts are fetched only through the
configured `TranscriptProvider`, Reddit remains qualitative, Amazon remains
marketplace/listing-specific, and IKEA runs only when source relevance and
regional official-store capability allow it.

Provider runtime configuration is typed in backend settings. Search, extraction,
optional shopping, video metadata, Amazon product-intelligence, and IKEA
regional-store providers have explicit provider names, enabled flags, shared
timeout/rate-limit defaults, a default region, and local secret fields where
needed. IKEA search mode reuses the configured general search provider rather
than introducing a separate credential.
Missing keys for enabled live providers surface as readiness warnings rather
than blocking fixture operation.

Tavily is the implemented live general search adapter. Brave remains reserved
without a runtime adapter. SerpApi is optional and used only for Amazon product
intelligence.

Source policy prefers official manufacturer pages, company announcements and
region-relevant sources while keeping reviews optional. Unknown domains,
reseller platforms and mixed marketplaces remain usable through approved access
paths. Product, seller, regional and variant contexts remain distinguishable.
Actual material concerns inform model judgment without an automatic exclusion.

`apps/backend/app/providers/source_quality.py` normalizes neutral URLs and
classifies source domains. It returns advisory quality, region relevance and
reasons. Historical exclusion and mandatory-trust fields no longer discard
usable research or options. Query planning preserves useful results and stores
advisory metadata for later model context.

## Recommendation principles

Recommend by default from available information and buyer preferences. Give useful
distinct options with concise reasons, practical tradeoffs and relevant unknowns.
A final winner, mode records, citations and checked offers are optional. The model
weighs actual adverse findings and buyer requirements. Source quality and seller
trust inform judgment without deciding eligibility. Budgets inform the model,
including known currency and over-budget amount when comparable.

### Processed research views

`research_history.py` keeps invocation-scoped originals and processing checkpoints.
Bounded derived views retain identities, useful source notes, cautions, gaps and
original lookup handles. Notes may paraphrase originals and are labeled as notes.
Exact quotation metadata is diagnostic; it cannot veto a recommendation or retry.
Canonical sources stay in existing repositories. SDK call/output pairs and
ownership transfers remain intact. No extra summarizer agent or evidence store
is introduced.

### Automatic request fitting and research selection

`BudgetedModel` measures the complete request and reserves transport usage.
Deterministic archives and bounded original views shorten reducible inputs.
Required buyer state, identity, SDK pairs and result contracts remain intact.
Irreducible input or cumulative-spending failures are technical errors.
Before research reaches its operational allowance, tools and handoffs close and
the model synthesizes advice from available snippets, pages and source notes.
Task 216 removes the funded quote-capture and follow-up-fetch phases.

`ResearchSelection` shares buyer-scoped leads across compatible owners. It ranks
relevance and novelty, preserves contrary information and supports bounded
shortlists and deferred lookup. Review counts, exact facts and quoted coverage
are not completion or recommendation prerequisites. Domain labels and quality
scores are advisory. URL/access protections and provider limits remain.

### Saved decisions and retries

Eligible retries claim the saved run atomically and reuse its owner checkpoints,
research and candidate artifacts. They preserve canonical identities, old events
and immutable result versions. The request/brief must remain compatible, and a
second active retry is rejected. The final owner call uses saved information
without research tools. Refinement decisions reuse the applicable research run
when the saved plan permits it. Model failures remain retryable technical errors.
They do not become a no-option buying judgment.

`VerifierCriticAgent` remains an explicit optional workbench capability. It receives
the saved bundle and supplied context, has no tools and cannot change the owner's
choices or block advice. Its observations are editorial notes. The configured
model/profile and authorized 180-second timeout remain available. Ordinary run,
refinement and retry orchestration omit the verifier.
