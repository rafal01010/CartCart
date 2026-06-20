# CartCart API

Status: Initial public API shape with guided intake direction
Last updated: 2026-06-12

## Contract Direction

The backend API should be a typed FastAPI HTTP API. FastAPI OpenAPI output should become the source of truth for generated frontend types once schemas stabilize.

The current OpenAPI JSON can be exported with
`scripts/local/export-openapi.sh`. By default it writes `docs/openapi.json`.
The frontend currently uses hand-written TypeScript contracts under
`apps/frontend/src/lib/api` for these implemented endpoints. Generated frontend
types should replace or narrow those contracts once OpenAPI type generation is
added.

API responses should hide internal agent implementation details while exposing
human-useful guided questions, recoverable errors, result versions, source
references, and recommendation output. The frontend should not need to show
agent names, prompts, providers, trace IDs, raw run mechanics, or developer
language in the normal shopper UI.

Long-running discovery and analysis runs should be asynchronous. Server-Sent Events are the recommended MVP progress transport because CartCart mostly needs one-way run progress plus normal request/response actions. WebSockets are not required for MVP.

## Guided Intake Direction

The public user-facing API should support a guided shopping intake layer before
deeper discovery and analysis starts. The current implemented endpoints preserve
useful session/run/result plumbing, but future guided frontend work should not
force the user through one large form or expose `run` as the user's mental
model.

Planned guided-intake responsibilities:

- Start from one natural-language shopping question.
- Return one current user-facing question at a time.
- Accept natural-language answers through the main textbox.
- Support inline yes/no, two-option, and justified two-option-plus-type-answer
  choice controls when constrained answers are genuinely helpful.
- Support `Skip question` for skippable optional prompts.
- Support `Skip all and start analysis` once enough information exists.
- Support going back to reanswer prior guided questions before analysis starts.
- Capture known products by name or description, not by asking for links in the
  normal flow.
- Represent one-time region setup separately from the main shopping question
  flow, including locally cached region values and explicit refusal to answer.
- Return short user-safe redirection copy for off-topic, unsafe, illegal, or
  inappropriate requests without starting discovery.

The guided-intake schema contract exists in `app.schemas.guided_intake`, and
the fixture-backed guided intake endpoints are implemented as a small API
surface around the existing session/run plumbing. The frontend-facing response
models include only regular-person-safe question, control, skip/reanswer,
region setup, blocked-state, progress, and ready-for-analysis metadata.

## Implemented Endpoints

```text
POST   /api/sessions
POST   /api/sessions/guided
GET    /api/sessions/{session_id}
PATCH  /api/sessions/{session_id}/brief
GET    /api/sessions/{session_id}/guide
POST   /api/sessions/{session_id}/answers
POST   /api/sessions/{session_id}/guide/skip
POST   /api/sessions/{session_id}/guide/skip-all
POST   /api/sessions/{session_id}/guide/reanswer
POST   /api/sessions/{session_id}/guide/region

POST   /api/sessions/{session_id}/runs
GET    /api/sessions/{session_id}/runs/{run_id}
GET    /api/sessions/{session_id}/runs/{run_id}/events

GET    /api/sessions/{session_id}/results
POST   /api/sessions/{session_id}/products
POST   /api/sessions/{session_id}/refinements

GET    /healthz
GET    /readyz
```

Planned later endpoints include `GET /api/sessions/{session_id}/sources/{source_id}`
and `GET /metrics`. They are not present in the current OpenAPI export.

## Endpoint Responsibilities

`POST /api/sessions`

Creates a local shopping session from a natural-language query, region, optional budget, and optional preferences. The response should include the session ID, original input, current inferred or user-provided brief fields when available, and timestamps.

Current implementation accepts `CreateSessionRequest` and returns `ShoppingSession`.
The initial `current_brief` preserves the original query plus any user-provided
region, budget, constraints, and preferences. Category inference is not performed
by this endpoint yet.

`POST /api/sessions/guided`

Creates a local shopping session from one natural-language shopping question and
returns the current guided-intake state. The request accepts
`CreateGuidedSessionRequest`, including optional one-time region setup supplied
from browser-local storage or explicit region refusal. The fixture implementation
returns either one current user-facing prompt/control, a blocked guardrail state,
or enough metadata for the frontend to ask for region setup outside the main
shopping-question flow. It does not ask for product links.

`GET /api/sessions/{session_id}/guide`

Loads the current guided-intake state for a session. If the session was created
through the older session endpoint, the fixture guide derives its starting state
from the persisted session query and current brief.

`POST /api/sessions/{session_id}/answers`

Submits the answer for the active guided question. The request accepts
`GuidedAnswerSubmission`, including natural-language textbox answers, yes/no
answers, two-option choices, and justified two-option-plus-type-answer choices.
The fixture implementation updates the in-memory guide state and persists a
ready `ShoppingBrief` to the session once intake has enough information. Natural
language known-product mentions are preserved as user-added product text without
asking the shopper to provide links.

`POST /api/sessions/{session_id}/guide/skip`

Skips only the active skippable guided question. In the fixture implementation,
this is limited to the combined optional context prompt and returns
`ready_for_analysis` when the original question is enough to begin.

`POST /api/sessions/{session_id}/guide/skip-all`

Skips remaining optional intake and persists a ready brief when enough
information exists. The frontend should use the returned `ready_for_analysis`
state to move to user-safe progress and then call the existing run endpoint.

`POST /api/sessions/{session_id}/guide/reanswer`

Selects a prior answered guided question for revision before analysis starts.
The response returns that question as the current answer surface with navigation
metadata indicating which prior question is being changed.

`POST /api/sessions/{session_id}/guide/region`

Submits one-time region setup after guided session creation. The request accepts
`RegionSetupSubmission` with either a provided region or explicit refusal, and
the response resumes the pending guided state.

`GET /api/sessions/{session_id}`

Loads persisted session state, including current brief, known products, latest run summary, and latest result metadata if available.

Current implementation returns the persisted session fields plus
`user_added_products`. Run and result summary fields will be added by their later
endpoint milestones.

`PATCH /api/sessions/{session_id}/brief`

Updates user-correctable brief fields such as inferred category, region, budget, constraints, and preferences. This should not silently overwrite historical run outputs.

Current implementation accepts a partial brief correction body with these fields:
`category`, `category_source`, `region`, `budget`, `constraints`, and
`preferences`. Omitted fields keep their existing values. Updating `category`
requires an explicit `category_source`; sending `null` for nullable fields clears
them. The response returns the updated `ShoppingSession`.

`POST /api/sessions/{session_id}/runs`

Starts a discovery/analysis run from the current session state. Runs should persist status, stage summaries, trace IDs, and result versions.

Current implementation creates a persisted `ShoppingRunRecord` and runs the
fixture `ShoppingRunOrchestrator` synchronously. The response returns the
terminal succeeded run, persisted progress events, and a fixture monitor-shopping
result bundle. Search, extraction, and reusable source-intelligence stages use
configured provider boundaries and default to fixture providers. Later analysis
and recommendation stages remain deterministic fixtures and do not call models.

`GET /api/sessions/{session_id}/runs/{run_id}`

Returns run status and human-useful stage summaries. It should not expose raw internal prompts or private provider payloads by default.

Current implementation returns the persisted `ShoppingRunRecord` when the run
belongs to the requested session.

`GET /api/sessions/{session_id}/runs/{run_id}/events`

Streams ordered progress events using Server-Sent Events. Events should include stable event IDs, stage names, status, timestamps, and user-safe messages.

Current implementation streams persisted `RunEvent` records for the requested run
in sequence order as `text/event-stream` events named `run_event`, then closes the
response. In fixture mode, `POST /runs` produces the events synchronously before
the client opens the stream. The current stage sequence runs `deduplication`
after `extraction` and before `source_intelligence`. The deduplication event
uses a user-safe count summary with pre-dedupe extracted products, post-dedupe
product groups, preserved listings, and collapsed duplicates. The
`source_intelligence` event then reports checking review videos, community
discussions, Amazon listings, and regional store sources. Long-running
background orchestration is a later milestone.

`GET /api/sessions/{session_id}/results`

Returns the latest recommendation bundle for the session, including final pick or no-strong-buy result, runner-ups, alternate modes, comparison data, trust notes, warnings, source references, and result version.

Current implementation returns the latest persisted fixture result bundle for the
session across its runs. The response includes result-version metadata, trust
assessments, category analyses, agent records, comparison matrix, and
recommendation bundle, plus the run's source snapshots and source evidence so
the frontend can render inspectable source links for result claims. The persisted
recommendation bundle is trust-aware: weak or suspicious listing assessments are
surfaced as listing-level warnings or rejections, and a suspicious final listing
is blocked instead of being returned as an unqualified best buy. If the session
exists but no result has been saved yet, the API returns `404` with
`result_not_ready`.

`POST /api/sessions/{session_id}/products`

Adds a user-known product or manual candidate to the session. User-added
products should participate in later analysis alongside app-generated
candidates. Normal guided intake should ask users for product names or
descriptions instead of asking them to paste product links.

Current implementation accepts URL placeholders and lightweight manual product
details, persists them as session-local `UserAddedProduct` records, and returns
the updated session state. It does not fetch URLs or extract listing details yet.

`POST /api/sessions/{session_id}/refinements`

Submits a refinement such as changed budget, corrected category, new constraint, or added preference. The backend should start targeted recompute where cached artifacts make that possible.

Current implementation stores a `RefinementRequest`, creates a new stub
`ShoppingRunRecord`, links the refinement to that run, executes the same fixture
orchestrator path used by `POST /runs`, and returns both records. It does not
perform targeted recompute yet. Existing result versions remain attached to
their original runs.

`GET /healthz`

Liveness check. It should be cheap and not depend on external providers.

`GET /readyz`

Readiness check. It reports configuration readiness, data directory location,
and provider warnings. Missing keys for enabled live providers are returned as
warnings while fixture/stub mode remains ready.

## Error Responses

API errors use a consistent JSON envelope:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "request_id": "request-id",
    "details": []
  }
}
```

The backend returns an `X-Request-ID` response header. If the client sends `X-Request-ID`, that value is echoed; otherwise the backend generates one. Validation errors and project application errors use this envelope.

## Core Schema Families

Use Pydantic schemas for API contracts and agent structured outputs. Important schema families include:

- Base primitives in `app.schemas`: UUID-based entity IDs, timezone-aware UTC timestamps, non-negative money amounts with ISO-style currency codes, country regions, confidence scores, source references, and schema version fields.
- Intake and session schemas in `app.schemas`: `CreateSessionRequest`, `ShoppingSession`, `ShoppingBrief`, `BudgetConstraint`, `RegionPreference`, and `PreferenceConstraint`.
- Search and source schemas in `app.schemas`: `SearchPlan`, `SearchQuery`, `SearchResult`, `SourceSnapshot`, `RawSourceSnapshotArtifact`, `SourceEvidence`, `EvidenceTarget`, `EvidenceConflict`, provider metadata, source quality, `ReusableSourceIntelligenceRequest`, `SourceIntelligenceCapabilityDescriptor`, `SourceEvidenceGap`, video source primitives, transcript availability, transcript segments, timestamped video review evidence, metadata-only video evidence, channel signals, sponsorship/affiliate-bias signals, Reddit/community discussion evidence, Amazon product/listing/review evidence, and IKEA regional official-store evidence.
- Product and listing schemas in `app.schemas`: `CanonicalProduct`, `ProductListing`, `ProductListingExtraction`, `ListingExtractionMissingField`, `SellerProfile`, `UserAddedProduct`, product/listing identity fields such as model, SKU, UPC, EAN, canonical listing URL, and retailer product ID, price money fields, region availability, listing source quality, deterministic extraction confidence, explicit extraction gaps, and extracted seller trust signals that remain separate from later listing trust assessments.
- Analysis and recommendation schemas in `app.schemas`: `DeduplicationDecision`, `ListingTrustAssessment`, structured listing trust signals, `CategoryAnalysis`, `ComparisonMatrix`, `RecommendationMode`, `RecommendationModeResult`, `RecommendationBundle`, and `RejectedItem`.
- Run and refinement schemas in `app.schemas`: `ShoppingRunRecord`, `RunEvent`, `RunEventLog`, `RunStage`, `RunStatus`, `AgentRunRecord`, `RefinementRequest`, and links to the shared `ErrorEnvelope`.
- Guided intake schemas in `app.schemas.guided_intake` cover current
  user-facing question state, natural-language answer submission, yes/no and
  inline choice controls, combined optional prompt text, skip/reanswer
  availability, ready-for-analysis state, one-time region setup/refusal,
  locally cached region handoff, progress display, and shopping-scope/safe-product
  guardrail results. These schemas do not include frontend-visible
  agent names, tool names, prompts, provider details, trace IDs, raw process
  mechanics, normal product-link requests, or multi-row mini-form prompts.
- `ShoppingSession`
- `ShoppingBrief`
- `BudgetConstraint`
- `RegionPreference`
- `SearchPlan`
- `SearchQuery`
- `SearchResult`
- `SourceSnapshot`
- `SourceEvidence`
- `ReusableSourceIntelligenceRequest`
- `VideoReviewEvidenceBundle`
- `CommunityDiscussionEvidenceBundle`
- `AmazonProductEvidenceBundle`
- `IKEAStoreEvidenceBundle`
- `ProductListing`
- `CanonicalProduct`
- `DeduplicationDecision`
- `SellerProfile`
- `ListingTrustAssessment`, including deterministic signal rows for seller
  identity, established retailer/source type, review count, return/warranty
  clarity, suspicious price from plausibility comparison, missing metadata, and
  contradictory listing data.
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
- Use timezone-aware timestamps and normalize backend schema timestamps to UTC.
- Use explicit money objects with amount and currency rather than bare numbers.
- Use source reference objects when a later schema points at evidence or extracted source material.
- Preserve field provenance for intake values, including `user_provided`, `inferred`, and `defaulted`.
- Represent hard budgets as `hard_cap` and soft budgets as `preferred`.
- Allow missing region at the schema layer; later intake/defaulting logic must mark any defaulted region as `defaulted`, not user-confirmed.
- Require source URLs and provider metadata on search results and source snapshots.
- Keep `SourceQuality` separate from analysis `Confidence`.
- Keep listing source quality on each `ProductListing`; canonical grouping must not merge away listing-level seller trust, price, availability, or source quality differences.
- Preserve video source IDs, transcript availability, and timestamp references when evidence is video-derived.
- Preserve source-specific context for reusable source intelligence, including Reddit thread/comment references where available, Amazon marketplace/listing/seller/fulfillment context where available, and IKEA country/region official-store context where available.
- Keep Reddit/community claims qualitative, require their text to be grounded in every cited public discussion summary, and retain all supporting context source IDs for recurring signals.
- Create Amazon evidence only from approved normalized listing context, preserve marketplace/ASIN, seller/fulfillment, review-warning, and ship-to-region fields, and reject tracked or affiliate-style source URLs.
- Create IKEA evidence only from approved normalized regional store context, require neutral official URLs on the declared country path, keep product facts separate from regional price/availability/store evidence, and represent missing or unavailable fields as explicit gaps without implying shipping elsewhere.
- Require source IDs for factual claims about products, listings, prices, sellers, reviews, regions, community discussion, marketplace evidence, official-store evidence, and video evidence.
- Require evidence targets for source-backed claims so product, listing, seller, review, candidate, region, and source-metadata evidence remain distinguishable.
- Require evidence ID citations on downstream analysis and recommendation claims while retaining source IDs for source-level inspection.
- Separate known, unknown, and inferred fields.
- Preserve confidence separately from evidence quality.
- Keep product-level and listing-level entities separate.
- Use deterministic product/listing identity fields for exact duplicate
  matching, followed by conservative normalized title/spec similarity review
  with `same_product`, `same_family`, `uncertain`, and `different_product`
  outcomes. Only high-confidence `same_product` outcomes may collapse
  candidates; uncertain title/spec similarity must preserve distinct
  candidates.
- Enforce one final best pick or an explicit no-strong-buy outcome in recommendation bundles.
- Preserve ordered run events and use `pending`, `running`, `succeeded`, `failed`, and `cancelled` run statuses consistently.
- Preserve materially conflicting evidence rather than overwriting it silently.
- Represent transcript availability honestly for video evidence.
- Represent unavailable, blocked, weak, anecdotal, stale, or region-mismatched source intelligence as explicit evidence gaps or low-confidence evidence rather than fabricated product facts.

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
