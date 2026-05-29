# CartCart API

Status: Initial public API shape for planning
Last updated: 2026-05-29

## Contract Direction

The backend API should be a typed FastAPI HTTP API. FastAPI OpenAPI output should become the source of truth for generated frontend types once schemas stabilize.

API responses should hide internal agent implementation details while exposing human-useful run stages, recoverable errors, result versions, source references, and recommendation output.

Long-running discovery and analysis runs should be asynchronous. Server-Sent Events are the recommended MVP progress transport because CartCart mostly needs one-way run progress plus normal request/response actions. WebSockets are not required for MVP.

## Initial Endpoints

```text
POST   /api/sessions
GET    /api/sessions/{session_id}
PATCH  /api/sessions/{session_id}/brief

POST   /api/sessions/{session_id}/runs
GET    /api/sessions/{session_id}/runs/{run_id}
GET    /api/sessions/{session_id}/runs/{run_id}/events

GET    /api/sessions/{session_id}/results
POST   /api/sessions/{session_id}/products
POST   /api/sessions/{session_id}/refinements
GET    /api/sessions/{session_id}/sources/{source_id}

GET    /healthz
GET    /readyz
GET    /metrics
```

`/metrics` is optional until a Prometheus-compatible exporter or equivalent monitoring path is added.

## Endpoint Responsibilities

`POST /api/sessions`

Creates a local shopping session from a natural-language query, region, optional budget, and optional preferences. The response should include the session ID, original input, current inferred or user-provided brief fields when available, and timestamps.

`GET /api/sessions/{session_id}`

Loads persisted session state, including current brief, known products, latest run summary, and latest result metadata if available.

`PATCH /api/sessions/{session_id}/brief`

Updates user-correctable brief fields such as inferred category, region, budget, constraints, and preferences. This should not silently overwrite historical run outputs.

`POST /api/sessions/{session_id}/runs`

Starts a discovery/analysis run from the current session state. Runs should persist status, stage summaries, trace IDs, and result versions.

`GET /api/sessions/{session_id}/runs/{run_id}`

Returns run status and human-useful stage summaries. It should not expose raw internal prompts or private provider payloads by default.

`GET /api/sessions/{session_id}/runs/{run_id}/events`

Streams ordered progress events using Server-Sent Events. Events should include stable event IDs, stage names, status, timestamps, and user-safe messages.

`GET /api/sessions/{session_id}/results`

Returns the latest recommendation bundle for the session, including final pick or no-strong-buy result, runner-ups, alternate modes, comparison data, trust notes, warnings, source references, and result version.

`POST /api/sessions/{session_id}/products`

Adds a user-known product, URL, or manual candidate to the session. User-added products should participate in later analysis alongside app-generated candidates.

`POST /api/sessions/{session_id}/refinements`

Submits a refinement such as changed budget, corrected category, new constraint, or added preference. The backend should start targeted recompute where cached artifacts make that possible.

`GET /api/sessions/{session_id}/sources/{source_id}`

Returns source and evidence metadata needed for inspection, such as URL, title, provider, extraction status, quality signals, transcript availability when relevant, and claims linked to that source.

`GET /healthz`

Liveness check. It should be cheap and not depend on external providers.

`GET /readyz`

Readiness check. It should cover database availability and configured provider readiness or warnings.

## Core Schema Families

Use Pydantic schemas for API contracts and agent structured outputs. Important schema families include:

- `ShoppingSession`
- `ShoppingBrief`
- `BudgetConstraint`
- `RegionPreference`
- `SearchPlan`
- `SearchQuery`
- `SearchResult`
- `SourceSnapshot`
- `SourceEvidence`
- `ProductListing`
- `CanonicalProduct`
- `DeduplicationDecision`
- `SellerProfile`
- `ListingTrustAssessment`
- `CategoryAnalysis`
- `ComparisonMatrix`
- `RecommendationMode`
- `RecommendationModeResult`
- `RecommendationBundle`
- `UserAddedProduct`
- `RefinementRequest`
- `RunEvent`
- `AgentRunRecord`
- `ErrorEnvelope`

## Schema Rules

- Version important agent output schemas.
- Require source IDs for factual claims about products, prices, sellers, and reviews.
- Separate known, unknown, and inferred fields.
- Preserve confidence separately from evidence quality.
- Keep product-level and listing-level entities separate.
- Preserve materially conflicting evidence rather than overwriting it silently.
- Represent transcript availability honestly for video evidence.

## Error Model

Errors should use a typed `ErrorEnvelope` with stable machine-readable codes and user-safe messages. The API should distinguish:

- Invalid user input.
- Provider unavailable.
- Provider rate-limited.
- Extraction failed.
- No candidates found.
- Weak evidence.
- Suspicious listing blocked.
- Run failed.
- Result not ready.

Recoverable errors should include enough context for the frontend to offer retry, correction, or partial-result paths.

