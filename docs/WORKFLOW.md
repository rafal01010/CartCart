# CartCart Workflow

Status: Transitional fixture runtime; bounded live-agent research implemented
Last updated: 2026-09-26

## Scope

This document describes the current backend workflow shape. Search discovery,
page extraction, reusable source intelligence, and agent-backed analysis are
configured fixture-first. The normal run path can opt into live OpenAI agents
with `CARTCART_AGENT_WORKFLOW_MODE=live`,
`CARTCART_LIVE_AGENTS_ENABLED=true`, and a local `OPENAI_API_KEY`. Fixture mode
remains the default and does not make live model calls.

The target research cycle is bounded: agent query planning; typed provider
search; `DiscoveryAgent` classification/relevance and source decisions;
approved fetch with persisted snapshot IDs; primary `ExtractionAgent` semantic
interpretation of zero/one/many products and review evidence; cited candidate
and evidence validation; then agent-requested targeted follow-up when needed.
The backend owns provider credentials, URL/content safety, budgets, schema and
evidence-ID integrity, persistence, and policy. Search-provider source labels,
domain scores, and parsing helpers are signals only. A review may identify
several candidate models, but it is not itself a shop listing. An unknown or
generic search-result type must reach the agent for judgment.

The approved `search_sources` and `fetch_source` SDK tool boundary is attached
to live `DiscoveryAgent`. It persists same-run source/snapshot IDs,
enforces call and content limits, and reports provider gaps without exposing
vendor arguments or arbitrary-URL retrieval. Live discovery may make bounded
follow-up searches; seed and tool-returned results receive per-source decisions.
Live `ExtractionAgent` has a separate read-only `read_source_snapshot` SDK tool.
It can read only assigned same-run persisted snapshots, with a bounded text
excerpt and read budget. Invalid structured output becomes an explicit gap.

The live path now repeats selected fetch, extraction, candidate/evidence review,
and DiscoveryAgent follow-up within four cycles, two follow-up discovery calls,
and twelve discovery-selected fetched pages; direct user-added URLs are a
separate input path. Follow-up inputs include bounded candidate, seller,
evidence, and gap summaries. Each discovery invocation retains its own
four-search-call tool budget; up to twelve cited leads can be handed off per
call. ExtractionAgent can explicitly link earlier review
evidence to a found product; unmatched review claims stay source-scoped, never
becoming store offers. Source results, snapshots, and evidence are persisted;
agent decisions, extracted entities, gaps, and follow-up matches are recorded
in the run's research activity. Fixture normalization remains single-listing
oriented and fixture behavior remains Task 89H work.
The following run lifecycle describes the current transitional behavior.

Related docs:

- `docs/API.md` covers endpoint contracts.
- `docs/DATABASE.md` covers persisted tables, indexes, and artifact boundaries.
- `docs/ARCHITECTURE.md` covers broader product and agent architecture.
- `supported_agents.md` covers the human-editable supported-agent intent.

## Session Lifecycle

1. The client creates a session with `POST /api/sessions`.
2. The backend persists the original `CreateSessionRequest` and an initial
   `ShoppingBrief`.
3. The client can load the session with `GET /api/sessions/{session_id}`.
4. The client can patch user-correctable brief fields with
   `PATCH /api/sessions/{session_id}/brief`.
5. User-added products can be stored with
   `POST /api/sessions/{session_id}/products`.

The MVP remains local/no-auth and does not build cross-session preference
profiles.

## Run Lifecycle

`POST /api/sessions/{session_id}/runs` creates a `ShoppingRunRecord` and runs the
`ShoppingRunOrchestrator` synchronously inside the request. The response
therefore returns a terminal succeeded run in the current transitional slice.

The orchestrator:

1. Loads the persisted run.
2. Creates a run context with `run_id`, `session_id`, active brief, and a local
   trace ID.
3. In fixture mode, records deterministic intake. In live workflow mode, runs
   `IntakeAgent` through the typed contract and merges inferred fields without
   overwriting existing user-provided brief fields.
4. Builds and persists a search plan from the active shopping brief. Text-only
   user-added product names/descriptions are added as scoped lookup queries so
   they can be found without asking the shopper for links.
5. Calls the configured search provider and persists policy-scored search
   results. Live `DiscoveryAgent` receives those seeds and may use approved
   search/fetch tools for bounded follow-up. Its structured output classifies
   every observed source and selects pages by ID, including generic results.
6. In live mode, fetches DiscoveryAgent-selected pages in bounded batches,
   persists linked snapshots, asks ExtractionAgent to interpret each readable
   page, reviews cited candidates/gaps, and lets DiscoveryAgent search again
   when research remains insufficient. Generic provider types are not a veto.
   Fixture mode retains the legacy single-listing normalizer.
   User-added URL snapshots are tied directly
   to the user-supplied candidate rather than to a search-result record;
   name/description matches retain their provider search-result link.
7. Deduplicates extracted generated and user-added candidates together,
   persists grouped canonical products,
   listing records, and shortlist memberships, and reports pre/post grouping
   counts. When a user-added URL or name/description match extracts
   successfully, the session's `UserAddedProduct` record is updated with the
   deduped product/listing.
8. Runs reusable source-intelligence checks for scoped candidate products and
   categories where provider capability and source relevance allow it. In live
   workflow mode, the reusable source-intelligence agents call only their typed
   provider/service boundaries.
9. Runs listing trust, category routing/analysis, comparison, and verification
   either through fixture stages or the configured live typed agents.
10. Persists one run event and one agent trace record per executable stage.
11. Persists the resulting analysis output. Live runs persist only their
    agent-validated shortlist and recommendation, never monitor fixture
    products. Fixture mode still has category-incompatible fallback behavior;
    Task 89H addresses it.
12. Appends the final `complete` event.

Long-running background orchestration, retries, cancellation, and partial-result
resumption are later milestones.

## Stage Order

The executable stages are:

1. `intake`
2. `query_planning`
3. `discovery`
4. `extraction`
5. `deduplication`
6. `source_intelligence`
7. `listing_trust`
8. `category_analysis`
9. `comparison_decision`
10. `verification`

The terminal stage is:

11. `complete`

Each executable stage persists an `AgentRunRecord` with a local trace ID,
runtime mode, stage timing, model name where a model-backed agent was used,
sanitized tool activity, fallback/error outcome, and nullable token/cost fields.
Fixture traces use:

```text
fixture-run-{run_id}:{stage}
```

Live-agent workflow traces use:

```text
live-agent-run-{run_id}:{stage}
```

## Event Emission

Run events are persisted in `run_events` with monotonically increasing sequence
numbers per run. The current API exposes them through:

```text
GET /api/sessions/{session_id}/runs/{run_id}/events
```

The endpoint streams persisted events as Server-Sent Events named `run_event`.
Because the current `POST /runs` path is synchronous, clients open the stream
after all run events are already persisted.

The current successful fixture event sequence has 11 events: ten `running`
stage events and one terminal `succeeded` event for `complete`.

## Discovery, Extraction, And Fixture Output

Query planning persists the current run's `SearchPlan`. Discovery executes each
planned query through the resolved provider, applies deterministic source
quality policy, drops explicitly excluded domains, and persists accepted
`SearchResult` records with provider IDs and policy metadata. Eligible non-video
page results are then passed to the configured `ExtractionProvider`. Each
returned `SourceSnapshot` is linked to its originating search result and
persisted with extraction-provider metadata.

Fixture candidate creation still uses legacy listing-eligible source types and
the deterministic one-listing normalizer. In live mode, selected generic results
and other source types are persisted before `ExtractionAgent` reads their
snapshots. Its validated listings feed the current shortlist path, including
multiple listings from one page; its evidence is persisted and passed to later
analysis. Review/collection mentions can trigger bounded targeted offer lookup
across multiple cycles. Decisions, mentions, gaps, and follow-up matches are
retained in the research stage trace; extracted evidence and page snapshots are
stored as source records.
Fixture and disabled provider modes remain network-free.

The deduplication stage then groups those normalized candidates before source
intelligence, trust, analysis, and recommendations run. It uses deterministic
URL, retailer ID, SKU/model/UPC/EAN, exact brand/model, and conservative
title/spec similarity matching. Only obvious same-product matches collapse.
Uncertain or family-level matches stay separate. The stage persists one
canonical product per group, all listing records under that product, and one
shortlist membership per product group. Its run event reports pre-dedupe
candidate count, post-dedupe product-group count, preserved listing count, and
collapsed duplicate count.

After deduplication, the reusable source-intelligence stage builds a
`ReusableSourceIntelligenceRequest` from the current brief, target region,
grouped candidate products, their preserved listings, and source IDs. It then
calls enabled and source-relevant providers for:

- YouTube/video review metadata plus transcript retrieval through the configured
  `TranscriptProvider` boundary.
- Reddit/community discussion signals through the configured community provider.
- Amazon product/listing/review evidence through the configured Amazon provider.
- IKEA regional official-store evidence when the product/category or search
  results make IKEA relevant.

The stage limits transcript retrieval to the small provider-selected review
video set, preserves transcript failures as video gap notes, stores source
snapshots for source-intelligence references, and persists source-specific
evidence bundles separately from normal web/listing evidence. Fixture mode uses
fake source-intelligence providers. Configured live transcript mode uses
`YtDlpTranscriptProvider`; it does not substitute fixture transcript text when
caption retrieval fails.

The listing-trust stage then calls the typed `SellerListingTrustAgent` contract
for the run's grouped listings and fixture-backed candidates. The fixture agent
is seeded with deterministic trust-rule output, including price-plausibility
context where comparable listings exist, and the resulting
`ListingTrustAssessment` rows are saved through result persistence before the
final fixture recommendation bundle is stored. Result assembly then folds those
trust assessments into the persisted recommendation bundle: suspicious or weak
listings become listing-level warnings or avoid items, and a suspicious final
listing becomes no-strong-buy unless a safer listing is selected.

When fixture workflow mode is selected, the downstream fixture analysis output remains a
monitor-shopping scenario. It persists:

- Source snapshots and source evidence.
- Fixture products and listings used by the current analysis bundle. Fixture
  shortlist memberships are used only when extraction yields no candidates.
- A user-added monitor candidate.
- Duplicate Dell listings that preserve listing identity.
- Suspicious seller/listing trust assessments.
- Category analyses for generated and user-added candidates.
- A trust-aware best pick, best-value, within-budget, stretch-upgrade, runner-up,
  rejected listing items, warnings, comparison matrix, and recommendation bundle.
- No-strong-buy output when no candidate clears the fit, budget, evidence, and
  listing-trust bar, with plain next-step guidance for the shopper.

The fixture best pick is the Dell UltraSharp U2724DE official listing. The
fixture includes a suspicious duplicate marketplace listing for the same Dell
monitor and rejects that duplicate as a bad listing rather than a bad product.
It also rejects the user-added ViewPro listing because seller/source signals are
weak.

Recommendation modes are stored inside the persisted `RecommendationBundle`.
Switching between best overall, best value, within-budget, and stretch-upgrade
views on the frontend reads that stored bundle and does not create a new run.

## Result Versioning

Result persistence stores versioned recommendation bundles per run. Loading
session results with:

```text
GET /api/sessions/{session_id}/results
```

returns the latest result version across runs in that session.

When additional result bundles are saved for the same run, the version number for
that run increments. Refinement runs remain separate runs and do not overwrite
the original run's result versions.

## Failure States

The schema supports `pending`, `running`, `succeeded`, `failed`, and
`cancelled`. Failed run events require an `ErrorEnvelope`.

In the current stub orchestrator, an exception during stage execution or fixture
output persistence appends a failed event for the current stage and re-raises the
exception. There is not yet a user-facing retry endpoint, resumable checkpoint
logic, cancellation path, or background task recovery mechanism.

## OpenAPI Export

The current OpenAPI contract can be exported with:

```sh
scripts/local/export-openapi.sh
```

By default this writes:

```text
docs/openapi.json
```

Pass a path to write elsewhere:

```sh
scripts/local/export-openapi.sh /tmp/cartcart-openapi.json
```
