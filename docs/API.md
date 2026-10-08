# CartCart API

Status: Implemented API and future contract direction
Last updated: 2026-10-06

## Contract Direction

The backend API should be a typed FastAPI HTTP API. FastAPI OpenAPI output should become the source of truth for generated frontend types once schemas stabilize.

The current OpenAPI JSON can be exported with
`scripts/local/export-openapi.sh`. By default it writes `docs/openapi.json`.
The frontend currently uses hand-written TypeScript contracts under
`apps/frontend/src/lib/api` for these implemented endpoints. Generated frontend
types should replace or narrow those contracts once OpenAPI type generation is
added.

Money input schemas accept a non-negative number or a plain decimal string with
up to ten integer digits and two decimal places. The generated string pattern
uses no regex lookaround, so SDK structured outputs can use the same contract.
Runtime Decimal validation still enforces non-negative amounts, at most twelve
digits and two decimal places; responses continue to serialize amounts as strings.

API responses should hide internal agent implementation details while exposing
human-useful guided questions, recoverable errors, result versions, source
references, and recommendation output. The frontend should not need to show
agent names, prompts, providers, trace IDs, raw run mechanics, or developer
language in the normal shopper UI.

Long-running discovery and analysis runs should be asynchronous. Server-Sent Events are the recommended MVP progress transport because CartCart mostly needs one-way run progress plus normal request/response actions. WebSockets are not required for MVP.

## Guided Intake Direction

The user-facing API supports guided shopping intake before discovery and
analysis. The frontend asks one question at a time and keeps run mechanics out
of the normal shopper view.

Guided-intake responsibilities:

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
region setup, blocked-state, progress, and ready-for-analysis metadata. A live
OpenAI Agents SDK `ShoppingGuideAgent` now implements the same structured
`GuidedIntakeState` contract for isolated mock/live workbench runs. The normal
guided-intake API remains fixture-backed; the normal run workflow can opt into
live guarded intake and `IntakeAgent` processing after run start.

The existing guided endpoints supply the corrected brief and start the same
`/runs` resource. After scope/safety preflight and scoped intake, each opt-in
live run enters `GeneralShoppingAgent` before category routing. The run records
the active owner's draft and research trace. The last SDK owner now authors the
persisted recommendation after independent evidence checks and verification;
the older analysis stages can add evidence but do not rewrite it. General
receives the saved corrected brief and user-added product leads from the same
session; those leads still need source checks. General can now use a real SDK
handoff to Technology for a matching technology request. Technology can then
SDK-handoff to a matching monitor, phone, laptop, audio, TV, or watch specialist.
The completed transfer chain and last owner are recorded internally.
Internal `general_owner` activity includes `rejected_handoff` on a category
rejection, or `null` otherwise. It contains source and target agent names,
requested and buyer catalog routes, the bounded category length, and an exact
known category label or `null`. It omits raw arguments and handoff reasons.
`ProductAnalysisRoute` remains a Python-selected analysis route; source
agents-as-tools do not transfer shopper ownership. Shopper-facing endpoints do
not expose tool calls or agent names; internal activity can report an actual
Discovery, source-specialist, trust, General, Technology, or product-specialist `web_search_call`
separately from application-provider searches.

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
GET    /api/sessions/{session_id}/results/history
GET    /api/sessions/{session_id}/results/{result_version_id}
POST   /api/sessions/{session_id}/products
POST   /api/sessions/{session_id}/refinements
GET    /api/sessions/{session_id}/refinements/{refinement_id}/plan
POST   /api/sessions/{session_id}/refinements/{refinement_id}/execute

GET    /healthz
GET    /readyz
```

Planned later endpoints include `GET /api/sessions/{session_id}/sources/{source_id}`
and `GET /metrics`. They are not present in the current OpenAPI export.

Local-only internal agent workbench endpoints may be mounted at
`/internal/agent-workbench` when `CARTCART_AGENT_WORKBENCH_ENABLED=true` in a
local, test, or fixture environment. They are deliberately excluded from the
public OpenAPI contract and must not be consumed by the normal shopper UI.
`POST /internal/agent-workbench/research-tools/probe` accepts a validated
search query/intent/region/result limit, exercises fixture search and retrieval
against disposable in-memory persistence, and returns safe source/snapshot IDs,
typed tool results, and workbench tool-activity summaries. It never calls live
providers or models and is not the normal discovery workflow.
The local workbench also has isolated `ExtractionAgent` cases for an individual
product page, an ambiguous page, malformed model output, and a multi-product
page. Mock mode uses disposable persisted snapshots and no live model calls;
live mode is explicit and may incur OpenAI usage.
The isolated `GeneralShoppingAgent` workbench accepts a run ID and shopping
brief and returns a `GeneralShoppingDecisionDraft` with a selected candidate
only when fetched product/listing and independent review excerpts support it;
otherwise it returns `insufficient_evidence` and gaps. Candidate evidence
contains persisted source, snapshot, and evidence IDs. Its fixture case makes
no model or provider call; mock cases cover a wooden cane, an ambiguous request,
and weak search results. The same owner now runs first after intake in opt-in
live `/runs`; fixture runs do not call its model.
The YouTube specialist now exposes approved video search, metadata, and
transcript tools with fixture/mock/live workbench modes. Fixture remains a
provider-service run with no model; mock exercises the SDK contract offline;
explicit live mode runs the model over workbench provider fixtures. Reddit likewise exposes
approved public-community search/read tools and fixture/mock/live workbench
modes, with only mock/live representing SDK specialist runs. Amazon now exposes
approved bounded marketplace candidate-search/read tools and fixture/mock/live workbench
modes; fixture remains a provider-service probe, while mock/live run its SDK
specialist contract. IKEA now likewise exposes bounded official-region
search/read tools and fixture/mock/live workbench modes; only mock/live run its
SDK specialist contract. All four expose
`agent_as_tool_available=true` because the live shopping-run source manager now
invokes each through the SDK agent-as-tool path. The workbench fixture mode
still reports provider-service execution without a model call.
Transcript-backed YouTube evidence may include `signal_kind` (`pro`, `con`,
`concern`, or `other`) and a short interpretation alongside the exact quoted
`claim`, segment IDs, and timestamps. Metadata-only evidence has no transcript
claim.

## Endpoint Responsibilities

`POST /api/sessions`

Creates a local shopping session from a natural-language query, region, optional budget, and optional preferences. The response should include the session ID, original input, current inferred or user-provided brief fields when available, and timestamps.

Current implementation accepts `CreateSessionRequest` and returns
`SessionStateResponse`.
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
shopping-question flow. It does not ask for product links. The isolated live
`ShoppingGuideAgent` follows the same response schema and workbench constraints,
but this endpoint is not routed through it yet.
Volunteered HTTP(S) links in the first question are saved as distinct
`UserAddedProduct.url` candidates for direct listing extraction. Explicitly
named products are saved as separate text candidates for research. A question
containing only a link prompts for the shopper's goal before analysis can start.

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
Volunteered HTTP(S) links in guided answers are also saved as URL candidates.
Reanswering replaces candidates that came only from the superseded answer;
repeated links are collapsed to one candidate per listing URL. The product
endpoint below remains available for adding a listing after intake.

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

Loads persisted session state: original input, current brief, timestamps, and
`user_added_products`. Run status and results use their dedicated endpoints;
this response does not contain a latest-run or latest-result summary.

`PATCH /api/sessions/{session_id}/brief`

Updates user-correctable brief fields such as inferred category, region, budget, constraints, and preferences. This should not silently overwrite historical run outputs.

Current implementation accepts a partial brief correction body with these fields:
`category`, `category_source`, `region`, `budget`, `constraints`, and
`preferences`. Omitted fields keep their existing values. Updating `category`
requires an explicit `category_source`; sending `null` for nullable fields clears
them. The response returns the updated session state.

`POST /api/sessions/{session_id}/runs`

Starts a discovery/analysis run from the current session state. Runs should persist status, stage summaries, trace IDs, and result versions.

Current implementation creates a persisted `ShoppingRunRecord` and runs the
`ShoppingRunOrchestrator` synchronously. The response returns the terminal
`ShoppingRunRecord`; progress events are available from the SSE endpoint.
Workflow stages are checkpointed so a fatal
stage failure remains queryable as a terminal failed run rather than being
rolled back with the request. Expected individual source-access failures do not
fail the run. Fixture workflow mode remains the default and returns the monitor
result only for the complete monitor fixture scenario; other unsupported
fixture categories receive a no-strong-buy result without monitor products.
Fixture mode makes no live model calls. When `CARTCART_AGENT_WORKFLOW_MODE=live`,
`CARTCART_LIVE_AGENTS_ENABLED=true`, and `OPENAI_API_KEY` are configured, the
normal run path uses live typed agents for scoped intake, General ownership,
planning, discovery
selection, source-intelligence wrappers, trust, analysis, comparison, and
verification while keeping provider access behind typed service boundaries. If
the session question is blocked by shopping-scope or safe-product guardrails,
the endpoint returns `shopping_guardrail_blocked` with short user-safe copy and
does not create a run. If live workflow mode is requested without live-agent
configuration, the endpoint returns `live_agents_not_configured`.

With fixture agents and any enabled live source provider, this endpoint returns
HTTP 409 with `research_mode_mismatch` before creating a run or calling sources.
The error includes non-secret required mode flags in `details`. Isolated provider
probes are separate from normal shopping runs. A technical General-owner research
failure produces a terminal failed `ShoppingRunRecord` with a failed event and
saved owner activity, rather than a completed no-strong-buy result. Successfully
completed research with insufficient evidence retains the no-strong-buy outcome.

`GET /api/sessions/{session_id}/runs/{run_id}`

Returns run status and human-useful stage summaries. It should not expose raw internal prompts or private provider payloads by default.

Current implementation returns the persisted `ShoppingRunRecord` when the run
belongs to the requested session.

`GET /api/sessions/{session_id}/runs/{run_id}/events`

Streams ordered progress events using Server-Sent Events. Events should include stable event IDs, stage names, status, timestamps, and user-safe messages.

Current implementation streams persisted `RunEvent` records for the requested run
in sequence order as `text/event-stream` events named `run_event`, then closes the
response. In fixture mode, `POST /runs` produces the events synchronously before
the client opens the stream. A `general_owner` event follows intake and precedes
planning and category routing. The current stage sequence runs `deduplication`
after `extraction` and before `source_intelligence`. The deduplication event
uses a user-safe count summary with pre-dedupe extracted products, post-dedupe
product groups, preserved listings, and collapsed duplicates. The
`source_intelligence` event then reports checking review videos, community
discussions, Amazon listings, and regional store sources. Long-running
background orchestration is a later milestone.
In live-agent mode this stage is owned by `SourceIntelligenceManagerAgent`;
its persisted stage trace includes the parent model and nested specialist
agent-tool activity. Fixture mode keeps a provider-service simulation.

`GET /api/sessions/{session_id}/results`

Returns the latest recommendation bundle for the session, including final pick or no-strong-buy result, supported comparison modes, trust notes, warnings, source references, and result version. Live bundles retain `result_author`, `handoff_chain`, `verification_action`, and `verification_changes` for audit. The shopper view renders the recommendation and evidence without agent or handoff details.

For an approved live owner result, `final_rationale` and the best-overall mode
rationale preserve the final SDK owner's primary explanation. Verifier
revisions record the changed fields and authored reasons in
`verification_changes`. A missing revision reason blocks the result even when
automatic guardrail checks pass. Blocked results return a cautious
no-strong-buy answer without the unsupported primary explanation. The internal
owner contract requires a nonblank explanation of at most 1500 characters.
The public result schema and result-version links remain unchanged.

Recognized factual specifications require evidence for the candidate asserted
in the claim, including final, mode, and comparison explanations. Correctly
targeted evidence for another product cannot establish the winner's
specification. Supported comparisons retain citations for each named product.
The backend repeats this check after an approved verifier revision. A blocked
live result records the reason in `verification_changes` and clears the purchase
pick through the existing cautious result contract.

`final_product_id` and the exact `final_listing_id` identify the saved final
decision. `mode_results` is optional supporting data and may be empty or contain
only alternatives. The frontend builds the main pick from the final references,
`final_rationale`, and preserved evidence. A null final listing stays a
product-only recommendation, even when an optional mode names a purchase offer.
Mode tabs include the saved final decision so shoppers can return to it after
viewing an alternative. Saved `runner_up_product_ids` remain visible without
duplicate mode records, using available comparison or category analysis data.
Explicit saved runner-up offers retain their product/listing pairs.
Shortlist membership alone does not attach a purchase offer. A runner-up without
a saved mode or comparison-row listing stays product-only, retaining its saved
analysis and evidence.
Missing explanations, confidence, and offer details remain unavailable rather
than inferred from scores or unrelated candidates.

Current implementation returns the latest successful persisted result bundle for the
session across its runs. The response includes result-version metadata, trust
assessments, category analyses, agent records, comparison matrix, and
recommendation bundle, plus the run's canonical products, preserved listings,
ordered shortlist memberships (`candidate_id`, `product_id`, optional
`listing_id`), run-linked `considered_products` outcomes, source snapshots, and
source evidence so
the frontend can render inspectable source links for result claims. The persisted
considered-product outcome includes the session candidate and an explicit
`confirmed`, `possible`, `unresolved`, `manual`, or `excluded` status. A meaningful
rejection supplies `exclusion_reason`; manual details retain their field-level
`user_reported` or `unknown` status. The frontend uses these IDs and the saved
comparison matrix to show matches, gaps, and seller/listing concerns without
matching products by name. Shortlist and considered-product data belong to the
run that produced this result; a candidate added after that run appears after
the next completed run.

The persisted recommendation bundle preserves listing trust. Weak or suspicious
listing assessments produce listing-level warnings or rejections. Every explicit
recommended listing, including alternate modes and saved runner-up offers,
must satisfy seller safety and comparable-price hard caps. A suspicious offer
requires a blocking warning identifying that offer or exclusion. An ordinary
seller mention or another offer's warning does not qualify. Comparison-only
rows and rejected offers can remain visible without becoming buying picks.
Product-only recommendations do not infer listing IDs. Unknown prices and
different currencies do not establish a hard-cap breach. When
`no_strong_buy=true`, `no_strong_buy_reason` should explain what blocked a
responsible recommendation and include a plain-language next step for the
shopper. If the session exists but no result has been saved yet, the API
returns `404` with `result_not_ready`.
When research yields no verified product, the persisted no-strong-buy bundle
has no final product, empty comparison rows, and may have no evidence IDs.
It is an honest result, not a monitor-fixture fallback.

`POST /api/sessions/{session_id}/products`

Adds a user-known product or manual candidate to the session. User-added
products should participate in later analysis alongside app-generated
candidates. Normal guided intake should ask users for product names or
descriptions instead of asking them to paste product links.

The endpoint accepts URL entries and text-only product names/descriptions,
persists them as session-local
`UserAddedProduct` records, and returns the updated session state. On the next
shopping run, text-only user-added products add scoped lookup queries to the
query plan. Discovery selects sources by ID, and ExtractionAgent classifies
retrieved pages and explicitly links cited listings to a shopper hint as confirmed
or possible. A search hit alone is not a product match. URL entries are fetched
through the configured source extraction provider directly. Confirmed matches
are normalized and deduplicated with app-generated candidates; the user-added
record gains the canonical product and one linked listing. Ambiguous matches
remain separate in `possible_product_ids`, while each matched listing retains
its `user_added_matches`, seller, price, availability, and trust context.
Submitting the same listing URL again (including a tracking-parameter variant)
returns the existing session candidate. A later `POST /runs` checks the added
link in the same session; `GET /results` returns the newest completed result and
`GET /sessions/{session_id}` returns the candidate's research state. A candidate
with no confirmed listing remains an uncertain or unreadable lead, not a verified
offer. The result's source snapshots identify direct link attempts by candidate
ID and record whether the page was readable.

Manual fallback uses `manual_fallback_reason` (`retrieval_unavailable`,
`retrieval_insufficient`, or `user_correction`), `name`, optional identity fields,
and optional `manual_details` (seller, price, availability, review, warranty,
specifications). Retrieval reasons require `fallback_candidate_id` for an
existing, researched entry with no confirmed listing; correction can create a
new entry or replace one by ID. Product names alone remain research hints.
For an unavailable URL, the original link remains a research lead; a correction
clears the old link.
Manual details are shopper reports, never verified offers or citations. The
response exposes `manual_evidence_status` per field as `user_reported` or
`unknown`, with source always unknown, plus `research_attempted`. A manual-only
candidate enters the shortlist and comparison without a listing or invented
evidence; it cannot be selected as a buy until independent research confirms it.
The result UI offers this endpoint after a candidate has been researched without
a confirmed match, and for an explicit correction to a wrong match. It sends
`fallback_candidate_id` so the same session candidate is replaced, then starts
another run and reloads session state and the latest result. A correction sends
the corrected name as `input_text` for the next research attempt and clears the
old matched listing. The UI shows shopper-supplied fields separately from
unknown fields and does not turn either into a verified offer.

`POST /api/sessions/{session_id}/refinements`

Accepts a new `budget`, `region`, `category`, `result_mode`, constraints, or
preferences with a short instruction. An existing result is required (`409
refinement_requires_result` otherwise). The response contains the stored
`RefinementRequest`, a new **pending** run, and a typed `RecomputePlan` linked
to the prior run and exact result version. Planning does not execute the run or
replace the current result. The plan saves the base and target shopping
briefs, required stages, and a reason for each reused or invalidated artifact.
Budget changes can reuse source-backed candidate evidence in the same region;
category, region, currency, and new requirement changes trigger research.
Free-text changes without a typed field require re-intake. A mode-only change
can reuse the saved comparison.

`GET /api/sessions/{session_id}/refinements/{refinement_id}/plan`

Loads the stored plan for the same session, including its prior result link and
artifact decisions. Returns `404 refinement_not_found` for a missing plan or
one belonging to another session.

`POST /api/sessions/{session_id}/refinements/{refinement_id}/execute`

Executes the saved pending plan once. Research plans run fresh discovery,
extraction, candidate grouping, trust, analysis, decision, and verification
against the target brief. Budget and mode plans use the prior run's validated
candidate evidence and skip discovery and extraction; budget changes rerun
analysis, while mode changes reuse it. Every path produces a new decision and
verification record. The response is the completed or failed run record;
`GET /runs/{run_id}` and its events expose the same status. A stale plan or
repeat execution returns `409`. Failed execution leaves the last successful
result available.

`GET /api/sessions/{session_id}/results/{result_version_id}`

Returns one successful saved result version in the session. The ordinary
`GET /results` endpoint returns the latest successful version, which can belong
to an earlier run after a newer run fails. Clients
must respect a returned failed or cancelled run and require a matching
`result_version.run_id` before presenting a fallback lookup as completion of the
requested run. Retained earlier decisions must remain distinguishable from the
failed work. This applies to initial analysis, listing/manual checks, and refinements.
Result version numbers increase across the session; refinement results include their
`refinement_id`, `prior_result_version_id`, and requested result mode. When a
refinement reuses prior research, the response resolves the products, shortlist,
sources, and evidence from that prior run through the saved plan.
Considered-product outcomes are saved per research run so later candidate
corrections do not rewrite an older result view.

`GET /api/sessions/{session_id}/results/history`

Returns `original_query` and an ordered `versions` list of successful decisions
in that session. Each entry contains `result_version_id`, `version`, the saved
shopping `brief`, and a short `change` instruction (null for the original).
Context comes from saved refinement base/target briefs; pending or failed
plans never replace successful history context. An existing session with no
result returns an empty list; a missing session returns `404 session_not_found`.
Use the version endpoint above to inspect a selected decision. This response
omits agent records, run events, and recompute stages.

`GET /healthz`

Liveness check. It should be cheap and not depend on external providers.

`GET /readyz`

Readiness check. It reports configuration readiness, data directory location,
provider warnings, and live-agent configuration warnings. Missing keys for
enabled live providers or live OpenAI agents are returned as warnings while
fixture mode remains ready.

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
- Analysis and recommendation schemas in `app.schemas`: `DeduplicationDecision`, `ListingTrustAssessment`, structured listing trust signals, `CategoryAnalysis`, `ComparisonMatrix`, `RecommendationMode`, `RecommendationModeResult`, `RecommendationBundle`, and `RejectedItem`. `RejectedItem` includes an explicit `reason_code` for meaningful avoid reasons: suspicious listing, poor fit, overpaying, missing critical feature, or weak evidence.
- Run and refinement schemas in `app.schemas`: `ShoppingRunRecord`, `RunEvent`, `RunEventLog`, `RunStage`, `RunStatus`, `AgentRunRecord`, `RefinementRequest`, `RecomputePlan`, artifact decisions, and links to the shared `ErrorEnvelope`.
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
- `CommunitySupportingQuote` records on model-interpreted community evidence preserve exact cited public excerpts and source IDs.
- `AmazonProductEvidenceBundle`
- `IKEAStoreEvidenceBundle`
- `ProductListing`
- `CanonicalProduct`
- `DeduplicationDecision`
- `SellerProfile`
- `ListingTrustAssessment`, including deterministic signal rows for seller
  identity, established retailer/source type, review count, return/warranty
  clarity, suspicious price from plausibility comparison, missing metadata, and
  contradictory listing data. Live trust research may add neutral unverified
  web leads with persisted
  `source_ids` and `evidence_ids`; those leads do not change the trust level.
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


Task 100B adds internal `context_call` activity to existing run stage traces.
It records context sizes and estimated/actual usage without raw source or shopper
text. The public API shape is unchanged. Exhausted context budgets use the
existing failed-run error path, preserving the distinction between technical
failure and a completed no-strong-buy decision. See
[context limits](CONTEXT_MANAGEMENT.md#limits-and-accounting).

### Internal research processing and continuation

Task 211 adds SDK-only `complete_research_result`, `read_research_result`,
`read_search_results` and `read_source_bundle` controls. They preserve original
same-run source support while bounding active tool views. Search previews expose
deferred source IDs; evidence reads expose offsets, hashes and unreviewed
coverage. These controls do not change public run/result schemas or turn
snippets into citation evidence. Public results still require independent
canonical and candidate-specific verification.

Owner consultations return `consultation_id` and `consultation_sha256` when
notes or bundles need continuation. Pass that ID as `bundle_id` to
`read_source_bundle`, with the optional `content_sha256`, to read the original
consultation notes and exact bundle-version references. Evidence readers
support `evidence_offset` independently of the page-text offset. The internal
owner response cap is 11,000 characters before lifecycle metadata, using UTF-8
JSON without ASCII escape expansion. Public result schemas remain unchanged.

Task 211 owner completion can report the internal technical code
`unreviewed_research` when a categorical safety or local-warranty assurance
uses unreviewed or conflicting cited support. The public result retains its
existing insufficient-evidence shape and a precise evidence gap. This failure
does not authorize a new model attempt.
