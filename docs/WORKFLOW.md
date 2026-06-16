# CartCart Workflow

Status: Provider-backed discovery and extraction with fixture analysis stages
Last updated: 2026-06-14

## Scope

This document describes the current backend workflow shape. Search discovery and
page extraction are provider-backed behind configuration and default to
deterministic fixture mode. Trust, analysis, recommendation, and reusable source
intelligence remain fixture based and do not call OpenAI models or live
source-intelligence tools.

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
2. Creates a run context with `run_id`, `session_id`, and a deterministic fixture
   trace ID.
3. Builds and persists a search plan from the current shopping brief.
4. Calls the configured search provider and persists policy-scored search
   results.
5. Sends eligible page results through the configured extraction provider,
   persists linked snapshots, and creates normalized shortlist candidates from
   usable extraction outcomes.
6. Executes the remaining fixture stages in a fixed order.
7. Persists one run event and one agent trace record per executable stage.
8. Persists the downstream monitor-shopping fixture analysis output.
9. Appends the final `complete` event.

Long-running background orchestration, retries, cancellation, and partial-result
resumption are later milestones.

## Stage Order

The executable stages are:

1. `intake`
2. `query_planning`
3. `discovery`
4. `extraction`
5. `deduplication`
6. `listing_trust`
7. `category_analysis`
8. `comparison_decision`
9. `verification`

The terminal stage is:

10. `complete`

Each executable stage persists an `AgentRunRecord` with a deterministic local
trace ID. Query planning and discovery use provider-backed behavior even though
the trace prefix and later stages remain fixture-oriented:

```text
fixture-run-{run_id}:{stage}
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

The current successful fixture event sequence has 10 events: nine `running`
stage events and one terminal `succeeded` event for `complete`.

## Discovery, Extraction, And Fixture Output

Query planning persists the current run's `SearchPlan`. Discovery executes each
planned query through the resolved provider, applies deterministic source
quality policy, drops explicitly excluded domains, and persists accepted
`SearchResult` records with provider IDs and policy metadata. Eligible non-video
page results are then passed to the configured `ExtractionProvider`. Each
returned `SourceSnapshot` is linked to its originating search result and
persisted with extraction-provider metadata.

Candidate creation requires a usable snapshot status. Product, retailer, and
official-brand pages normalize from extracted page content. Other usable page
types can use the persisted search-result metadata supported by the deterministic
listing normalizer. Generated products, listings, and shortlist memberships are
persisted before later stages run. The extraction event reports how many sources
were checked and products were added. Fixture and disabled modes remain
network-free; configured HTTP/static mode uses this same provider boundary.

The downstream fixture analysis output remains a monitor-shopping scenario. It
persists:

- Source snapshots and source evidence.
- Fixture products and listings used by the current analysis bundle. Fixture
  shortlist memberships are used only when extraction yields no candidates.
- A user-added monitor candidate.
- Duplicate Dell listings that preserve listing identity.
- Suspicious seller/listing trust assessments.
- Category analyses for generated and user-added candidates.
- A best pick, runner-ups, rejected item, warnings, comparison matrix, and
  recommendation bundle.

The fixture best pick is the Dell UltraSharp U2724DE official listing. The
fixture includes a suspicious duplicate marketplace listing for the same Dell
monitor and rejects the user-added ViewPro listing because seller/source signals
are weak.

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
