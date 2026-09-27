# CartCart Supported Agents And Source Capabilities

Status: Agent-first research runtime with fixture limitations called out below
Last updated: 2026-09-27

## Purpose

This file is the human-editable source of intent for CartCart's supported agents and agent-like source capabilities. It covers both:

- Hierarchical product/domain analysis agents, such as generic product analysis, technology analysis, or monitor analysis.
- Reusable cross-cutting agents-as-tools, such as YouTube review intelligence, Reddit community intelligence, Amazon product intelligence, IKEA regional store intelligence, seller/listing trust, marketplace product intelligence, or official brand-store lookup.

This is intentionally broader than an agent hierarchy file. Some agents belong in the product-analysis hierarchy; others are reusable source intelligence tools that can be called by agents at different hierarchy levels.

Reusable source intelligence means retrieving usable source-backed information, not only checking availability. Depending on the source, usable information can include product descriptions, specifications, pricing, regional availability, shipping or store presence, seller/fulfillment signals, review summaries, recurring owner complaints, product-page claims, warranty/return context, and evidence gaps.

## Relationship To Runtime Code

- This file is design documentation and approved product/source-routing intent.
- The application must not parse this Markdown file at runtime.
- Runtime configuration lives in the validated code registry at `apps/backend/app/agents/catalog.py`.
- The code registry, agent tests, routing evals, and this file must be updated together whenever an implemented agent is added, removed, moved, or assigned a new fallback.
- The agent tool matrix below must be updated whenever an agent gains, loses, or changes SDK tools, typed sub-runs, provider/service boundaries, or forbidden direct actions.
- A proposed or required future agent can appear here before it is implemented, but its status must not be changed to `implemented` until code, tests, and eval coverage exist.
- The 2026-06-02 required source-intelligence expansion is a design update only. The runtime catalog must be brought back into sync in the dedicated implementation backfill task before provider/live-agent work continues.
- The 2026-06-12 guided-intake backfill adds fixture-mode `ShoppingGuideAgent` and `ShoppingScopeGuardrail` contracts to the runtime catalog. The live OpenAI Agents SDK `ShoppingScopeGuardrail`, `IntakeAgent`, `ShoppingGuideAgent`, `QueryPlannerAgent`, `DiscoveryAgent`, `CategoryRouterAgent`, `GenericProductAnalystAgent`, `TechnologyDomainAnalystAgent`, `MonitorSpecialistAgent`, `SmartphoneSpecialistAgent`, `LaptopSpecialistAgent`, `EarphonesHeadphonesSpecialistAgent`, `TVSpecialistAgent`, `SmartwatchSpecialistAgent`, `SellerListingTrustAgent`, `ComparisonDecisionAgent`, and `VerifierCriticAgent` are available through their typed protocols in the isolated workbench and, when explicitly configured, the normal shopping-run workflow. The 2026-06-21 reusable source-intelligence implementations for YouTube, Reddit, Amazon, and IKEA are provider-backed through typed provider/service and evidence-creation boundaries in the isolated workbench and opt-in normal workflow. The normal full shopping workflow remains fixture-first by default; live-agent workflow mode requires explicit configuration and credentials.
- Four source SDK specialists and their parent agent-as-tool wiring are implemented and passed the Task 89P gate: focused offline checks cover all four specialists and parent delegation, and an authorized unsandboxed OpenAI smoke confirmed a real Sol parent invoking the Luna IKEA specialist as an SDK tool over an in-process fixture, returning validated cited evidence. Real source providers and the normal end-to-end live shopping workflow were not exercised; local app settings still select fixture-agent mode by default.

## Architectural Decision

CartCart uses deterministic workflow orchestration with typed agent steps. The orchestrator owns workflow stages, persisted state, evidence, errors, retries, and tracing.

### Shopper ownership: current and target

Today the guided API gathers a brief, then the live run enters
`GeneralShoppingAgent` after intake and before query planning, discovery, or
category routing. Its cited draft and research activity are recorded with the
run; the existing typed decision stages still assemble the persisted result.
`CategoryRouterAgent` returns a `ProductAnalysisRoute`; domain/specialist calls
return `CategoryAnalysis`; `ComparisonDecisionAgent` authors the final bundle.
These route strings, Python sub-runs, and source agents-as-tools are **not**
OpenAI Agents SDK handoffs. General now has one real SDK handoff option to
`TechnologyDomainAnalystAgent`. The SDK's completed handoff item, validated
reason/context, resolved models, and `last_agent` are recorded in the run trace;
the persisted recommendation still comes from the transitional decision stages.
`GeneralShoppingAgent` has an SDK runner in
the normal opt-in live workflow and the isolated workbench. Live
`DiscoveryAgent`, listing trust, the four source-intelligence specialists, and
General have the hosted OpenAI `WebSearchTool` in live runs;
Discovery's separate
`search_sources` and `fetch_source` tools call application providers only.

The target guided API retains progressive questions, skipping/reanswering,
brief corrections, and preflight scope/safety checks. `ShoppingGuideAgent`
(with `IntakeAgent` where needed) asks intake questions and produces the brief;
it never owns the purchase decision. After preflight, each ordinary request
enters `GeneralShoppingAgent` first. General owns the active shopper request,
may research and finish any broad category with a cited recommendation or an
honest insufficient-evidence answer, and may SDK-handoff only to
`TechnologyDomainAnalystAgent`. Technology may finish broad technology cases
or SDK-handoff only to one catalog-approved implemented product specialist:
monitor, smartphone, laptop, earphones/headphones, TV, or smartwatch. The
receiving specialist owns the rest of the model decision and originates the
shopper-facing draft; it has no further handoff target. A failed or unsuitable
specialization stays with the current owner under an explicit safe fallback,
never an invented specialist or a hidden parent rewrite.

`GenericProductAnalystAgent` remains a current, evidence-only per-product
analysis fallback returning `CategoryAnalysis`; it is distinct from the target
General owner and is not a shopper-request handoff target. `ComparisonDecisionAgent`
currently synthesizes `RecommendationBundle`; in the target flow its comparison
logic is an owner-accessible helper, not a second author after a handoff.
`DiscoveryAgent` and `ExtractionAgent` supply bounded research and cited
entities. `SellerListingTrustAgent` supplies separate listing-risk evidence.
`SourceIntelligenceManagerAgent` delegates scoped work to the four source SDK
agents-as-tools; neither the manager nor source specialists take over the
shopper request. The active owner may consume their validated persisted
artifacts through run-scoped typed tools, alongside approved provider research
and comparison helpers. Backend code keeps credentials, source/region policy,
budgets, seller-risk invariants, source/evidence-ID validation, and persistence.
The actual last owner drafts the result; independent backend checks and
`VerifierCriticAgent` may approve, request an auditable correction, or block it.
Persistence records the originating owner, actual handoff chain, citations,
verification changes, model/usage, and result version. The parent does not
resume to write a replacement answer.

Research semantics belong to agents, not to provider metadata or page-shape
heuristics. `DiscoveryAgent` classifies and judges search results, identifies
product leads from reviews, and chooses bounded follow-up searches and pages to
inspect. `ExtractionAgent` is the required primary interpreter of persisted
source snapshots: it can return zero, one, or many cited products/listings,
product mentions, review evidence, and explicit gaps. A review is evidence and
a source of candidate leads, not a store listing. Deterministic code owns
request validation, approved provider access and credentials, URL/network
safety, rate/size/cost limits, mechanical parsing signals, persistence,
schema/evidence-ID integrity, and policy enforcement. Helpers may propose
fields or reject invalid output but may not silently veto or replace an
agent's semantic source/product decision.

The research path is implemented. Live `DiscoveryAgent` receives pre-fetched
results, can call bounded search/fetch SDK tools, and returns a decision for each
inspected source, including generic results. Live `ExtractionAgent` now
interprets persisted snapshots and can return multiple listings. One bounded
extraction-to-discovery handoff now sends up to twelve cited leads still
needing direct offers; Discovery chooses targeted official/retailer searches within
its four-call budget. The run inspects up to four new pages per cycle, and extraction
explicitly matches review evidence to found products. The fixture path now
replays typed `DiscoveryAgent` and `ExtractionAgent` outputs; unknown results
are inspected as uncertain and produce explicit gaps, not guessed listings.
The fixture-only
`ExtractionReviewAgent` is transitional compatibility, superseded by
`ExtractionAgent`; it is not the target extraction architecture. The catalog's
`planned_tool_boundaries` are design declarations; `approved_sdk_tools` is the
active allowlist. The live shopping run now repeats discovery, selected fetch,
extraction, and candidate/evidence review within four cycles, two follow-up
discovery calls, and twelve discovery-selected fetched pages (direct user-added
URLs are a separate input path). Live result persistence does not
inject monitor fixture products. Only the complete monitor replay is eligible
for its downstream comparison bundle. TV, furniture, and other unsupported
fixture categories receive no-strong-buy without unrelated products. Mixed
live-provider/fixture-agent mode emits a readiness warning because it cannot
test live agent-owned research.

The offline gate replays eight professional TV reviews and eighteen generic
Tavily shopping results through a persisted shopping run. All 26 reach
`DiscoveryAgent`; the fixture interpreter has no cited TV product facts, so the
result is no-strong-buy with no monitor product injection. This is not evidence
that a credentialed live run will always find TV listings; that remains an
opt-in live-model/provider check.

The executable catalog now also assigns `fast`, `strong`, or `default` run
profiles. Strong is assigned to complex research/analysis, listing trust,
comparison, and verification; fast is assigned to bounded intake, planning,
routing, guardrail, and `ExtractionAgent`. These are
operator-configured model/timeout/turn defaults, not a shopper-visible choice.

The executable catalog allowlists `search_sources`, `fetch_source`, and hosted `web_search` for `DiscoveryAgent`. It also approves hosted search for seller/listing trust and alongside each of the four source specialists' site tools. The provider tools' run-scoped adapter accepts
bounded query/intent/region/result-count choices and existing source IDs, then
persists provider results/snapshots before returning IDs and safe excerpts.
It does not expose provider credentials, vendor arguments, arbitrary-URL fetch,
or raw metadata. The isolated workbench lists the approved tools and can show
the adapter's tool activity in a fixture-only probe. In live workflow mode,
`DiscoveryAgent` receives the SDK tools and may search again or inspect a
same-run source by ID; fixture/mock modes make no live provider calls.
An exact-agent override wins over the catalog profile for model, reasoning
effort, timeout, and max turns, and omitted settings
fall back to the global OpenAI configuration. Profiles do not activate live
workflow mode or change the fixture-first default. The live Discovery SDK
agent exposes all three tools with `tool_choice=auto`. Actual hosted calls are
read from SDK `web_search_call` items, and cited public URLs become weak,
run-scoped search results, unextracted snapshots, and source-metadata evidence
with persisted IDs. The agent can reject those leads. A hosted citation alone
never verifies a listing, price, seller, or product claim; page extraction and
backend evidence checks remain necessary. Missing citations, failed hosted
calls, and incompatible model overrides surface as explicit gaps/errors.

Specialized product/domain agents should normally be invoked as typed sub-runs or agents-as-tools when the orchestrator needs a scoped analysis result. OpenAI Agents SDK handoffs should be used only when a specialist should actually take over control of a conversational turn.

The YouTube, Reddit, Amazon, and IKEA roles have model-running OpenAI Agents SDK implementations with bounded source-specific tools and optional site-scoped hosted search. In live-agent shopping runs, `SourceIntelligenceManagerAgent` chooses relevant specialists after deduplication and invokes them through SDK agent-as-tool delegation. Default fixture-provider runs remain network-free provider-backed simulations; a service call is never counted as a model run. Source agents return cited evidence, not recommendations. Hosted citations are persisted as weak source leads; only validated site-tool evidence supports transcripts, discussion signals, marketplace offers, or official IKEA claims.

The product must support broad shopping queries even when no deep specialist exists. The current generic analysis fallback remains; the target General owner can finish such requests itself.

## Accepted Scope Decisions

- `GenericProductAnalystAgent` is the current per-product analysis fallback for normal categories; target `GeneralShoppingAgent` owns the whole request and can finish broad categories.
- `ShoppingGuideAgent` is the user-facing guided intake role. It asks one plain-language question at a time, supports skip/reanswer behavior, and decides when enough information exists to start analysis without exposing internal workflow mechanics.
- `ShoppingScopeGuardrail` is the shopping-scope and safe-consumer-product guardrail. It blocks or redirects off-topic, unsafe, illegal, or inappropriate requests before discovery or analysis starts.
- `TechnologyDomainAnalystAgent` is an MVP domain layer so technology routing is modular from the beginning.
- MVP technology specialists are `MonitorSpecialistAgent`, `SmartphoneSpecialistAgent`, `LaptopSpecialistAgent`, `EarphonesHeadphonesSpecialistAgent`, `TVSpecialistAgent`, and `SmartwatchSpecialistAgent`.
- `YouTubeReviewIntelligenceAgent`, `RedditCommunityIntelligenceAgent`, `AmazonProductIntelligenceAgent`, and `IKEAStoreIntelligenceAgent` are approved as reusable `required-mvp` source intelligence capabilities, not as category specialists.
- Reusable source intelligence agents are evidence retrieval and normalization tools. They must not be limited to availability checks, and they must not make final purchase recommendations.
- YouTube metadata may use the official YouTube Data API when configured. Transcript text may be used only through authorized official caption access, future user-provided transcript input, or a separately approved third-party provider. The system must never assume transcript availability.
- Reddit community evidence should be gathered through approved search/extraction providers, for example domain-scoped web search for public `reddit.com` results. It must summarize recurring user-reported patterns with source links and quality warnings rather than treating anecdotes as authoritative product facts.
- Amazon product intelligence should retrieve product/listing identity, seller/fulfillment, regional availability or ship-to-region status, product-page information, and review signals when compliant provider access is available. It must preserve marketplace seller risk separately from product quality and must not add affiliate logic.
- IKEA store intelligence should retrieve official IKEA product/store evidence for the user's region when applicable, including regional product availability, product-page information, price/currency where available, and evidence gaps. It must not assume IKEA ships globally; it should check whether IKEA has a relevant country/region presence and whether the item is available there.
- The current IKEA adapter uses the configured general search provider with strict official domain and country-path filtering. Fixture mode is the default; unsupported regions and unavailable products return explicit gaps without implying cross-region shipping.
- Broad non-technology domain layers should remain `proposed-later` until multiple implemented specialists or shared domain rules justify them.
- Current invocation uses typed steps, tools, and sub-runs. The target live owner graph uses real SDK handoffs only when control transfers to Technology or an eligible specialist.

## Status Meanings

| Status | Meaning |
| --- | --- |
| `required-mvp` | Must exist before MVP acceptance. |
| `candidate-mvp` | Intended for MVP, pending explicit implementation and provider feasibility decisions. |
| `proposed-later` | Useful future capability; not required for MVP. |
| `implemented` | Change to this status only once code, tests, and eval coverage exist. |
| `transitional` | Compatibility contract retained for current fixtures/workbench; not a target MVP research role. |

## Current Product Analysis Route Hierarchy

```text
ShoppingRunOrchestrator                                      [required-mvp]
  ShoppingGuideAgent                                         [required-mvp]
  ShoppingScopeGuardrail                                     [required-mvp]
  IntakeAgent                                                [required-mvp]
  QueryPlannerAgent                                          [required-mvp]
  DiscoveryAgent                                             [required-mvp]
  ExtractionAgent                                            [required-mvp; live extraction]
  ExtractionReviewAgent                                      [transitional; compatibility only]
  DeduplicationReviewAgent                                   [required-mvp]
  CategoryRouterAgent                                        [required-mvp]
    GenericProductAnalystAgent (fallback for all categories) [required-mvp]
    TechnologyDomainAnalystAgent                             [required-mvp]
      MonitorSpecialistAgent                                 [required-mvp]
      SmartphoneSpecialistAgent                              [required-mvp]
      LaptopSpecialistAgent                                  [required-mvp]
      EarphonesHeadphonesSpecialistAgent                     [required-mvp]
      TVSpecialistAgent                                      [required-mvp]
      SmartwatchSpecialistAgent                              [required-mvp]
      MouseSpecialistAgent                                   [proposed-later]
    KitchenAppliancesDomainAnalystAgent                      [proposed-later]
  SellerListingTrustAgent                                    [required-mvp]
  ComparisonDecisionAgent                                    [required-mvp]
  VerifierCriticAgent                                        [required-mvp]
```

## Reusable Source Intelligence Agents

These agents can be called by the orchestrator, discovery flow, product analysts, or decision agents when their source type is relevant. They are not arranged under one product category.

```text
SourceIntelligenceLayer
  YouTubeReviewIntelligenceAgent                             [required-mvp]
  RedditCommunityIntelligenceAgent                           [required-mvp]
  AmazonProductIntelligenceAgent                             [required-mvp]
  IKEAStoreIntelligenceAgent                                 [required-mvp]
  MarketplaceProductIntelligenceAgent                        [proposed-later]
  OfficialBrandStoreAgent                                    [proposed-later]
  ProfessionalReviewSourceAgent                              [proposed-later]
  CommunityDiscussionSignalAgent                             [proposed-later]
```

## Ownership Boundaries

`ShoppingRunOrchestrator` owns workflow order, durable state, run events, retries, provider boundaries, trace IDs, and final result assembly. Agents return typed outputs; they do not own persistence or global control flow.

`ShoppingGuideAgent` owns the regular-person-facing intake sequence before
analysis starts. It returns the current question, inline choice-control
recommendation when genuinely useful, skip/reanswer metadata, and
enough-information-to-start-analysis state. It must prefer natural-language answers,
avoid one large upfront forms, avoid normal product-link requests, and avoid
exposing internal agent, prompt, provider, trace, or run details.

`ShoppingScopeGuardrail` owns early shopping-scope and safe-product checks. It
should return short user-safe redirection copy for off-topic, unsafe, illegal,
or inappropriate requests and prevent source retrieval or analysis from starting
for blocked requests.

Product/category analysts own fit analysis for a product bundle in the context of a shopping brief. They should evaluate tradeoffs, missing evidence, product-level strengths and weaknesses, and category-specific concerns. They should not decide final ranking alone.

`TechnologyDomainAnalystAgent` owns shared technology-product reasoning, routing to MVP technology specialists, and technology-domain fallback when no narrower specialist applies. It should cover technology products broadly enough that adding future specific technology specialists is modular.

The planned reusable source-intelligence agents will own source-specific discovery, extraction review, quality scoring, and evidence summarization. The current provider services package source evidence without model judgment. Both paths must return structured evidence with source references and confidence, not final purchase recommendations.

`SellerListingTrustAgent` owns listing and seller trust assessment independently of product quality. Its live SDK agent can choose hosted web search for the supplied seller/listing and buyer region, or use supplied evidence alone. Exact cited URLs are retained as weak, run-scoped trust leads with source/evidence IDs. These leads can identify a question to check but cannot verify seller reputation, policy terms, or a listing claim or raise trust. Suspicious deterministic trust flags cannot be silently overridden by agent output.

`ComparisonDecisionAgent` owns comparative recommendation modes from the same analysis pass. `VerifierCriticAgent` owns final checks for unsupported claims, source gaps, suspicious-listing handling, budget handling, fallback behavior, and output restraint.

## Why These Are Source Intelligence Agents

YouTube, Reddit, Amazon, and IKEA are reusable source-intelligence capabilities because each source can support many product categories. They should be callable by the orchestrator, discovery flow, product/domain analysts, or decision agents when the source is relevant to the user's shopping brief and candidate set.

They should not be product/category specialists. A monitor specialist, smartphone specialist, laptop specialist, headphone specialist, TV specialist, smartwatch specialist, office-chair analysis path, furniture analysis path, or generic product analyst may all request source-derived evidence.

Each source agent should produce structured evidence, not final recommendations. The output should be source-backed, tied to product/listing/source IDs where possible, explicit about unavailable or low-quality evidence, and safe for downstream analysts to cite or discount.

### YouTube Review Intelligence

YouTube product reviews are often valuable because reviewers discuss real-world usage, long-term issues, comparisons, ergonomics, subjective experience, and buyer regrets that product pages do not capture.

The YouTube agent should find relevant product review videos, assess source/channel/video quality, retrieve or ingest available transcripts when permitted, summarize product-specific claims, preserve timestamps/source links, identify recurring pros/cons, flag sponsorship/affiliate bias where visible, and hand source-backed evidence to downstream analysts.

The current provider implementation supports official YouTube Data API metadata
discovery in configured live mode plus deterministic fixture and disabled modes.
It returns video ID, neutral watch URL, title, description, channel, publish
date, and duration when available. Transcript availability remains explicitly
`not_checked`; transcript retrieval is not part of the metadata adapter. The
separate transcript-ingestion path accepts only declared authorized official,
user-provided, or approved third-party access, preserves language and
timestamps, records unavailable/provider-failure gaps, and refuses video claims
that are not present in cited transcript text. Product-claim summarization
remains later agent work.

### Reddit Community Intelligence

Reddit can surface owner complaints, failure patterns, setup issues, long-term impressions, support experiences, and "avoid this" stories that are not visible on retailer pages. The Reddit agent should use approved domain-scoped search/extraction, retrieve public thread/comment content where permitted, summarize recurring claims, record subreddit/thread/comment links, preserve recency and engagement signals when available, and flag anecdotal, brigaded, astroturfed, deleted, or low-context evidence.

Reddit evidence should be treated as qualitative community signal. It can raise concerns or corroborate patterns, but it should not become the sole basis for factual product claims such as specs, warranty, current price, or availability.

The current provider implementation discovers public Reddit thread/comment
URLs through the configured general search provider with both `site:reddit.com`
and `reddit.com` domain scope. It preserves subreddit/thread/comment context,
search excerpts or approved upstream extracted text, optional recency and
engagement metadata, deterministic source quality, anecdotal-evidence warnings,
and explicit gaps for removed, inaccessible, unextracted, or missing content.
It does not call Reddit directly or claim public-page extraction support.
The current provider service selects relevant supplied or
provider-discovered discussions, summarizes recurring qualitative owner signals
only when they are grounded in cited public summaries, preserves subreddit,
thread, comment, and source IDs, adds anecdotal/manipulation/low-context/stale
warnings, and returns `CommunityDiscussionEvidenceBundle` output rather than
recommendations or authoritative product facts.
The separate SDK Reddit specialist can search only through the approved public
community provider or read supplied persisted discussion snapshots. It selects
discussions and interprets qualitative patterns from bounded, exact cited public
excerpts. Its output preserves supporting quotes and source/thread/comment IDs;
independent threads are required before it marks a signal recurring. Removed or
inaccessible text, invalid citations, and provider/model failures become gaps.
The live-agent shopping-run source stage delegates through the SDK manager; fixture mode retains its provider-service simulation.

### Amazon Product Intelligence

Amazon can provide product-page data, listing identity, seller/fulfillment context, marketplace availability, ship-to-region signals, price/currency where available, review counts/ratings, review-pattern summaries, and review-quality warnings. The Amazon agent should match products conservatively, preserve ASIN/listing/marketplace identity where available, distinguish Amazon retail, fulfilled-by-Amazon, third-party marketplace sellers, and unknown sellers, and separate review evidence from seller/listing trust.

Amazon evidence is not inherently safe or authoritative. The agent must preserve marketplace risk, variant ambiguity, suspicious review patterns, stale or merged reviews, unavailable shipping, and regional marketplace differences.

The current provider implementation supports deterministic fixture and disabled
modes plus opt-in SerpApi Amazon Search/Product discovery. It conservatively
matches a product to an ASIN when needed, preserves marketplace and listing
identity, seller/ship-from context, ship-to-region evidence, product-page facts,
rating/review-summary signals, third-party seller and variant-review warnings,
and explicit gaps. All returned Amazon product links are neutral and contain no
affiliate parameters. Marketplace reviews remain unverified source signals, and
seller/listing trust remains a separate downstream concern.

The current provider service selects relevant supplied products and
listings, calls only the typed `AmazonProductIntelligenceProvider`, preserves
the provider-created `AmazonProductEvidenceBundle`, records disabled or empty
provider output as explicit gaps, and exposes fixture/mock workbench scenarios
for third-party seller regional-shipping gaps and variant-review ambiguity. It
does not add affiliate behavior or collapse seller/listing trust concerns into
product desirability.

### IKEA Store Intelligence

IKEA is relevant because it has official country/region store presence rather than universal global shipping. The IKEA agent should check whether IKEA is available in the user's selected region, retrieve official product-page information when a product or comparable IKEA candidate is relevant, capture regional price/currency and availability where available, and preserve pickup/delivery/store-region limitations as evidence.

IKEA evidence should be official-source evidence, not a generic marketplace substitute. If IKEA has no relevant presence, no matching product, or unavailable regional inventory, the agent should return a clear evidence gap rather than implying global availability.

## Due Diligence Notes For YouTube

- The official YouTube Data API can search/list video metadata, but caption listing/downloading is authorization-scoped and not a general public transcript API.
- The official captions API response does not include actual caption text from `captions.list`; `captions.download` is the relevant endpoint but requires OAuth scopes and permission to access the caption track.
- Unofficial transcript APIs and scrapers may be practical but carry reliability, quota, terms, and compliance risk. They must be treated as optional providers with explicit configuration and documented constraints.
- The MVP should avoid assuming all YouTube videos have accessible transcripts.
- Fallback behavior should include metadata-only evidence, video description evidence, user-provided transcript input if later added, or skipping unavailable transcripts with a clear evidence gap.

## Due Diligence Notes For Reddit, Amazon, And IKEA

- Reddit, Amazon, and IKEA provider choices must be verified at implementation time against current provider terms, allowed API use, crawling rules, privacy constraints, and rate limits.
- Reddit retrieval should prefer approved search-provider domain filters and compliant extraction of public pages. It must not use private, deleted, logged-in-only, or otherwise inaccessible content.
- Amazon retrieval should use compliant APIs, approved data providers, or permitted user-visible page access. It must avoid affiliate assumptions, preserve neutral outbound links, and keep marketplace seller/listing trust separate from product desirability.
- IKEA retrieval should prefer official IKEA country/region pages or approved provider paths. It must treat country/region availability as source-specific evidence and never infer global shipping from global brand presence.
- All three agents need fixture replay before live calls, explicit disabled-provider behavior, source-quality scoring, and eval cases for weak, missing, conflicting, or low-confidence evidence.

## Agent Catalog

| Agent | Status | Responsibility | Invocation Pattern | Input | Output | Fallback / Failure Behavior |
| --- | --- | --- | --- | --- | --- | --- |
| `ShoppingRunOrchestrator` | `required-mvp` | Controls stages, persistence, events, retries, tracing, and result assembly. | Application code | Session/run context | Persisted workflow state | Persist failure and provide retry/recovery path. |
| `ShoppingGuideAgent` | `required-mvp` | Ask one user-facing intake question at a time, decide when inline choices help, support skip/reanswer behavior, capture user-considered product names/descriptions without asking for links, and determine when enough information exists to start analysis. | Typed step before analysis | First shopping question, prior answers, local region setup state | Guided intake state or ready-for-analysis signal | Ask a plain-language follow-up, allow skip where safe, preserve uncertainty, or defer to guardrail when request is unsuitable. |
| `ShoppingScopeGuardrail` | `required-mvp` | Keep requests within shopping scope and safe consumer-product scope before discovery starts. | Early typed guardrail | Current user input and guided intake context | Allowed or blocked/redirection result | Return short regular-person-facing redirection copy and do not start discovery or analysis for blocked requests. |
| `IntakeAgent` | `required-mvp` | Interpret user goal, inferred category, region, budget, hard constraints, soft preferences, and clarification needs. | Typed step | Query and explicit controls | `ShoppingBrief` | Ask for correction or preserve uncertainty when critical intent is ambiguous. |
| `QueryPlannerAgent` | `required-mvp` | Plan region-aware searches and source strategy, including scoped lookup queries for user-considered product names/descriptions and when video-review search is useful. | Typed step | `ShoppingBrief` plus user-added product hints | `SearchPlan` | Generic shopping query plan. |
| `DiscoveryAgent` | `required-mvp` | Own semantic source classification/relevance, product leads from reviews, and bounded follow-up search/fetch decisions, including user-considered products. | Typed agent step with approved search/retrieval tools | Brief, plan, persisted provider results and cited leads | Per-source kind, confidence, reasons, treatment, candidate/model hints, next action, and selected IDs | Keep generic search results available for judgment; return explicit insufficient evidence if classification fails. |
| `ExtractionAgent` | `required-mvp` | Primarily interpret each persisted page, including review roundups and multi-product collection pages; separate product, listing, seller, and review facts. | Live typed agent step over approved persisted-snapshot reader | Assigned snapshot IDs, bounded page text, and cited leads on targeted follow-up pages | Zero/one/many cited products/listings, review mentions/evidence, lead matches, and gaps | Preserve unknowns; invalid citations/schema become explicit gaps. Bounded research cycles feed review/collection mentions to DiscoveryAgent before shortlist construction. |
| `ExtractionReviewAgent` | `transitional` | Existing fixture/workbench compatibility contract only; superseded by `ExtractionAgent`. | Fixture sub-run only; not the target live path | Existing snapshot/extracted fields | Legacy `ExtractionReviewAgentOutput` | Do not promote its fixture monitor output into an unrelated category. |
| `DeduplicationReviewAgent` | `required-mvp` | Review ambiguous duplicate candidates after deterministic matching. | Tool/sub-run only for uncertain pairs | Listings and match evidence | `DeduplicationDecision` | Preserve candidates as distinct when confidence is insufficient. |
| `CategoryRouterAgent` | `required-mvp` | Select implemented specialist or generic fallback. | Deterministic catalog plus typed routing decision where needed | Brief and candidates | Declared route | Always route unsupported/uncertain categories to generic fallback. |
| `GenericProductAnalystAgent` | `required-mvp` | Analyze product fit and tradeoffs for any shopping category. | Specialist tool/sub-run | Brief, product/evidence bundle | `CategoryAnalysis` | Mark limitations and evidence gaps instead of refusing unsupported categories. |
| `TechnologyDomainAnalystAgent` | `required-mvp` | Finish broad technology shopping requests after a validated SDK handoff; continue per-product technology analysis in the typed workflow. | General's SDK handoff target or domain tool/sub-run | Shopping brief and run-scoped research, or a typed product/evidence bundle | `GeneralShoppingDecisionDraft` as handoff owner; `CategoryAnalysis` in the per-product path | Reject non-technology handoffs; keep the typed generic fallback on per-product failures. |
| `MonitorSpecialistAgent` | `required-mvp` | Provide deeper monitor-specific analysis. | Specialist tool/sub-run through technology domain | Monitor brief/products/evidence | `CategoryAnalysis` | Fall back to technology-domain analysis, then generic analysis if needed. |
| `SmartphoneSpecialistAgent` | `required-mvp` | Provide deeper smartphone-specific analysis. | Specialist tool/sub-run through technology domain | Smartphone brief/products/evidence | `CategoryAnalysis` | Fall back to technology-domain analysis, then generic analysis if needed. |
| `LaptopSpecialistAgent` | `required-mvp` | Provide deeper laptop-specific analysis. | Specialist tool/sub-run through technology domain | Laptop brief/products/evidence | `CategoryAnalysis` | Fall back to technology-domain analysis, then generic analysis if needed. |
| `EarphonesHeadphonesSpecialistAgent` | `required-mvp` | Provide deeper earphone/headphone-specific analysis. | Specialist tool/sub-run through technology domain | Earphones/headphones brief/products/evidence | `CategoryAnalysis` | Fall back to technology-domain analysis, then generic analysis if needed. |
| `TVSpecialistAgent` | `required-mvp` | Provide deeper TV-specific analysis. | Specialist tool/sub-run through technology domain | TV brief/products/evidence | `CategoryAnalysis` | Fall back to technology-domain analysis, then generic analysis if needed. |
| `SmartwatchSpecialistAgent` | `required-mvp` | Provide deeper smartwatch-specific analysis. | Specialist tool/sub-run through technology domain | Smartwatch brief/products/evidence | `CategoryAnalysis` | Fall back to technology-domain analysis, then generic analysis if needed. |
| `MouseSpecialistAgent` | `proposed-later` | Deeper mouse analysis. | Not implemented | TBD | TBD | Technology domain or generic fallback when later approved. |
| `KitchenAppliancesDomainAnalystAgent` | `proposed-later` | Domain reasoning for kitchen appliance purchases. | Not implemented | TBD | TBD | Generic fallback until implemented. |
| `SellerListingTrustAgent` | `required-mvp` | Review seller/store/listing legitimacy, suspicious prices, and trust/red-flag evidence. | Cross-cutting typed step | Listings and source evidence | `ListingTrustAssessment` | Unknown trust if evidence is insufficient; suspicious deterministic flags cannot be silently overridden. |
| `YouTubeReviewIntelligenceAgent` | `required-mvp` | Discover relevant product review videos, collect permitted transcript/metadata evidence, summarize product-specific claims, and return timestamped source evidence. | Reusable source agent/tool | Brief, candidate products, optional source/video queries | `VideoReviewEvidenceBundle` | If transcripts are unavailable, return metadata-only evidence or explicit evidence gaps; never fabricate video claims. |
| `RedditCommunityIntelligenceAgent` | `required-mvp` | Discover relevant Reddit discussions, collect permitted public thread/comment evidence, summarize recurring owner/community signals, and flag anecdotal or low-quality evidence. | Reusable source agent/tool | Brief, candidate products, optional source/community queries | `CommunityDiscussionEvidenceBundle` | If relevant public content cannot be fetched or quality is weak, return explicit evidence gaps; never treat anecdotes as authoritative product facts. |
| `AmazonProductIntelligenceAgent` | `required-mvp` | Assess Amazon product/listing identity, seller/fulfillment, regional availability or ship-to-region status, product-page information, review signals, and suspicious marketplace/review patterns. | Reusable source agent/tool | Product/listing candidates and target region | `AmazonProductEvidenceBundle` | Use only compliant APIs/providers or permitted user-visible pages; preserve seller/listing trust concerns separately from product desirability. |
| `IKEAStoreIntelligenceAgent` | `required-mvp` | Check whether IKEA has relevant country/region presence, retrieve official IKEA product information, regional price/currency and availability where available, and store/delivery evidence gaps. | Reusable source agent/tool | Product/listing candidates, product/category intent, and target region | `IKEAStoreEvidenceBundle` | If IKEA is unavailable in region or product evidence is missing, return an evidence gap; never imply global shipping or availability. |
| `MarketplaceProductIntelligenceAgent` | `proposed-later` | Gather product-page, listing, review, availability, shipping, seller quality, and region-relevance evidence across mixed marketplaces. | Reusable source agent/tool | Product/listing candidates and region | Marketplace product evidence | Fall back to listing trust/source quality rules. |
| `OfficialBrandStoreAgent` | `proposed-later` | Locate official brand/store pages by country and assess official price, availability, warranty, and authorized sellers. | Reusable source agent/tool | Brand/product and region | Official-source evidence | Generic search/source extraction fallback. |
| `ProfessionalReviewSourceAgent` | `proposed-later` | Gather structured evidence from reputable written review sites and lab-test sources where available. | Reusable source agent/tool | Product/category and region | Review evidence | Generic source extraction fallback. |
| `CommunityDiscussionSignalAgent` | `proposed-later` | Summarize recurring owner complaints/praise from community discussions when allowed and source quality is adequate. | Reusable source agent/tool | Product/category and source set | Community signal evidence | Treat as lower-confidence qualitative signal, not definitive truth. |
| `ComparisonDecisionAgent` | `required-mvp` | Compare candidates and generate recommendation modes from one analysis pass. | Typed step | Brief and all assessed candidates | `RecommendationBundle` | Permit explicit "no strong buy" with next steps; emit avoid/rejected items only with explicit material reason codes, not for ordinary non-winners. |
| `VerifierCriticAgent` | `required-mvp` | Verify claim evidence, budgets, red flags, fallback behavior, duplicates, and output restraint. | Final typed step | Draft bundle, products, listings, evidence, trust, analyses, and dedupe context | Approved/revised/rejected bundle | Block unsupported or unsafe recommendation output. |

The current runtime includes live OpenAI Agents SDK `ShoppingGuideAgent`,
`IntakeAgent`, `QueryPlannerAgent`, `DiscoveryAgent`, `CategoryRouterAgent`,
`GenericProductAnalystAgent`, `TechnologyDomainAnalystAgent`,
`MonitorSpecialistAgent`, `SmartphoneSpecialistAgent`,
`LaptopSpecialistAgent`, `EarphonesHeadphonesSpecialistAgent`,
`TVSpecialistAgent`, `SmartwatchSpecialistAgent`,
`SellerListingTrustAgent`, `ComparisonDecisionAgent`, and
`VerifierCriticAgent` implementations
behind the typed `GuidedIntakeState`, `ShoppingBrief`,
`SearchPlan`, `DiscoveryAgentOutput`, `ProductAnalysisRoute`,
`CategoryAnalysis`, `ListingTrustAssessment`, `RecommendationBundle`, and
`VerificationReport`
protocols for isolated
mock/live workbench runs. The live
guide uses structured output, deterministic guardrail prechecks, mocked/live
workbench scenarios, and an `IntakeAgent` handoff only when it reaches
`ready_for_analysis`. The live query planner uses structured output with no
tools and falls back to a generic region-aware search plan rather than blocking
categories without specialists. The currently implemented live discovery agent
uses structured output with no tools and selects IDs from supplied search
results. This is transitional: it cannot search again or inspect a generic
result discarded by orchestration. The live category router uses structured output with
no tools, normalizes route decisions through the executable catalog, sends MVP
technology specialist categories through `TechnologyDomainAnalystAgent`, and
falls back to `GenericProductAnalystAgent` for unsupported or uncertain
categories. The live generic product analyst uses structured output with no
tools, analyzes supplied product/listing/evidence bundles for any normal
consumer category, preserves source and evidence IDs, and returns explicit
limitations instead of category refusal when evidence is weak. The live
technology domain analyst uses structured output with no tools, consumes only
supplied product/listing/evidence bundles plus the executable catalog route,
declares the MVP specialist route internally when one applies, analyzes broad
technology categories without a specialist, and falls back to generic analysis
for non-technology input or domain failure. The live monitor specialist uses
structured output with no tools, consumes only supplied monitor
product/listing/evidence bundles, covers monitor-specific panel, resolution,
refresh-rate, ergonomics, port, and tradeoff checks with source IDs, and falls
back to technology-domain or generic analysis for non-monitor input or
specialist failure. The live smartphone specialist uses structured output with
no tools, consumes only supplied smartphone product/listing/evidence bundles,
covers smartphone-specific camera, battery, update-support, performance, and
region/model caveat checks with source IDs, and falls back to technology-domain
or generic analysis for non-phone input or specialist failure. The live laptop
specialist uses structured output with no tools, consumes only supplied
laptop product/listing/evidence bundles, covers
laptop-specific CPU, RAM, storage, battery, display, port, weight, and
upgradeability checks with source IDs, and falls back to technology-domain or
generic analysis for non-laptop input or specialist failure. The live
earphones/headphones specialist uses structured output with no tools, consumes
only supplied earphone, headphone, earbud, or headset product/listing/evidence
bundles, covers ANC, comfort/fit, microphone, battery, codec/device fit, and
source IDs, and falls back to technology-domain or generic analysis for
non-audio input or specialist failure. The live TV specialist uses structured
output with no tools, consumes only supplied TV product/listing/evidence
bundles, covers panel/backlight, HDR, motion, gaming inputs, room brightness,
size fit, and source IDs, and falls back to technology-domain or generic
analysis for non-TV input or specialist failure. The live smartwatch specialist
uses structured output with no tools, consumes only supplied smartwatch
product/listing/evidence bundles, covers phone compatibility, health sensors,
battery, durability, app ecosystem, and source IDs, and falls back to
technology-domain or generic analysis for non-watch input or specialist
failure. The live seller/listing trust agent uses structured output with no
tools, consumes only the supplied listing, evidence, and deterministic
rule-based assessment, and preserves hard suspicious deterministic signals such
as implausibly low price or contradictory listing data rather than silently
overriding them. The live comparison decision agent uses structured output with
no tools, consumes only supplied assessed candidates, evidence, trust, and
dedupe inputs, returns a `RecommendationBundle`, and falls back to an explicit
no-strong-buy bundle when model output is invalid, times out, or cannot support
a safe best pick. The live Reddit community intelligence agent is
provider-backed through typed community-discussion results and
`CommunityEvidenceCreator`; it selects relevant public Reddit contexts,
summarizes recurring qualitative signals, keeps source/thread/comment IDs, and
returns explicit gaps for inaccessible content without making recommendations
or authoritative product claims. The normal full shopping workflow preserves
fixture-first behavior by default and can route through live agents only when
explicitly configured. Local routing eval cases now cover broad generic fallback,
technology-domain routing, every MVP technology specialist route, and
specialist fallback availability to technology-domain and generic analysis
without live model calls. The current runtime
invokes `QueryPlannerAgent`, executes
the resulting queries
through the configured `SearchProvider`, and persists accepted, policy-scored
search results. Eligible result pages then pass through the configured
`ExtractionProvider`; usable snapshots create persisted app-generated products,
listings, and shortlist memberships. Reusable source-intelligence providers run
after deduplication. The seller/listing trust stage now calls the typed
`SellerListingTrustAgent` contract in fixture mode, seeded by deterministic
trust rules, and persists `ListingTrustAssessment` rows through result
persistence. The full-workflow category analysis and recommendation stages
remain fixture-backed. Fixture mode stays the default when live providers are
disabled or configured credentials are unavailable.

## Required Routing Rules

Rules 1–5 describe the current Python-selected analysis path. The target
owner path instead starts every ordinary request at General, which can finish
without a specialist; Technology can also finish without a specialist. A
`ProductAnalysisRoute` is never evidence of an SDK handoff.

1. Every normal product query must be eligible for `GenericProductAnalystAgent`.
2. A product/category specialist may only receive queries within its declared scope.
3. Technology products should route through `TechnologyDomainAnalystAgent` before narrower technology specialists are selected.
4. If no product/category specialist matches, routing must fall back to domain analysis where applicable, then generic analysis rather than presenting an unsupported-category error.
5. If a specialist fails, times out, or has insufficient relevant evidence, technology-domain analysis and generic analysis must remain available.
6. Non-technology domain layers are optional and should only be implemented when they improve shared reasoning or routing.
7. Reusable source intelligence can be used across hierarchy levels and product categories, but must be scoped by product/category, region, source relevance, and provider compliance.
8. YouTube/video evidence must remain source-backed with video IDs, channel metadata where available, timestamps when available, transcript availability status, and confidence.
9. Reddit/community evidence must remain source-backed with thread/comment URLs where available, source context, recency/engagement signals when available, and confidence. It is qualitative evidence unless corroborated.
10. Amazon evidence must preserve marketplace, ASIN/listing identity where available, seller/fulfillment, review signal provenance, regional availability or ship-to-region status, and confidence.
11. IKEA evidence must preserve country/region context, official source URLs, local price/currency and availability where available, store/delivery limitations, and confidence.
12. Seller/listing trust assessment applies independently of category analysis and must be surfaced where it materially affects purchase safety.
13. Recommendation output must be verified after product, source, and trust outputs are combined.

## Tool, Handoff, And Control Policy

- The orchestrator controls the MVP workflow.
- Agents should be invoked as typed steps, tools, or sub-runs with explicit input and output schemas.
- Product/category specialists should receive scoped product/evidence bundles and return `CategoryAnalysis`.
- Domain agents should own shared domain reasoning and should route only to specialists declared in the validated runtime catalog.
- Reusable source agents should receive scoped source requests and return evidence bundles, not recommendations.
- Current per-product routing uses typed steps. The live owner run supports SDK General -> Technology -> catalog-approved product-specialist transfers, capped at two hops.
- Agent failures, timeouts, and low-confidence outputs must be persisted and routed through defined fallback behavior.

## Agent Tool Matrix

This table records current exposed tools and provider boundaries. Runtime code still
owns the executable allowlist, and this Markdown file must not be parsed at
runtime. `None` means the OpenAI Agents SDK agent should run with `tools=[]` for
that role. `Orchestrated provider/service boundary` means application code or a
typed wrapper may call the provider/service with fixed schemas, compliance
checks, timeouts, and persisted outputs; the model must not construct arbitrary
provider arguments or call vendor SDKs directly.

| Agent | Current SDK tools exposed directly to agent | Allowed typed sub-runs / agents-as-tools | Allowed provider/service boundaries | Forbidden direct actions |
| --- | --- | --- | --- | --- |
| `ShoppingScopeGuardrail` | None. Uses deterministic prechecks plus structured guardrail output. | None. | Shopping/safe-product deterministic guardrail service before model classification. | Starting search, extraction, analysis, or provider calls for blocked requests. |
| `ShoppingGuideAgent` | None. | `IntakeAgent` only after enough information exists. | Guided-intake state service and deterministic guardrail precheck. | Product recommendations, source retrieval, product links as normal intake, raw provider/tool controls. |
| `GeneralShoppingAgent` | Live SDK `web_search`, `search_sources`, `fetch_source`, `record_source_quote`, run-evidence lookup, evidence/candidate comparison, deterministic listing-trust check, and scoped source consultation. | One SDK handoff to Technology when its validated context matches the shopper's technology request; source specialists remain nested under the source manager. | Run-scoped provider search/fetch, persisted quote evidence, and backend-validated source/trust helpers. | Treating a hosted hit as a listing or making uncited price, availability, seller, or product claims. |
| `IntakeAgent` | None. | None. | None beyond supplied user/session input. | Search, extraction, source intelligence, recommendation generation, invented region/budget certainty. |
| `QueryPlannerAgent` | None. | None. | None directly. The workflow calls `SearchProvider` adapters after a validated `SearchPlan` is returned and may provide user-added product hints for scoped lookup queries. | Direct web search, browsing, provider SDK calls, category blocking because no specialist exists, asking users for product links. |
| `DiscoveryAgent` | `web_search` is a hosted SDK tool in live runs; `search_sources` and `fetch_source` remain bounded provider function tools. | None today. | Hosted URL citations are filtered and persisted as weak source leads with source/evidence IDs; supplied results and approved provider calls retain backend-owned policy and budgets. | Arbitrary URLs/provider arguments, vendor SDKs, unbounded browsing, fabricated source IDs, treating hosted snippets as verified listings or product facts. |
| `ExtractionAgent` | `read_source_snapshot`, limited to assigned same-run persisted IDs and bounded text. | None today. | Typed output with valid source/evidence IDs and zero/one/many products/listings; backend validates entity links, neutral listing URLs, cited price text, editorial-page listing exclusion, item-level URLs on collection pages, and review-evidence matches to follow-up products. | Direct scraping/vendor SDKs, invented facts/IDs, treating review articles as stores, collapsing multiple products into one page title. |
| `ExtractionReviewAgent` | Fixture/workbench compatibility only; no live SDK tools. | None in target architecture. | Existing legacy snapshot/extraction contract until replacement. | Being treated as the primary semantic interpreter or injecting monitor fixtures for unrelated requests. |
| `DeduplicationReviewAgent` | Not implemented live yet. | May be a typed sub-run only for uncertain duplicate pairs. | Supplied product/listing/evidence records and deterministic dedupe signals. | Collapsing uncertain products without evidence, fetching new source data. |
| `CategoryRouterAgent` | None. | None. | Executable agent catalog for allowed route normalization and fallback. | Calling analysts directly, inventing specialists, unsupported-category refusal for normal products. |
| `GenericProductAnalystAgent` | None. | May receive orchestrated source-intelligence outputs; may later request approved source-intelligence sub-runs only if explicitly implemented. | Supplied product/listing/evidence bundles and trust context. | Raw search, scraping, vendor SDK calls, unsupported-category refusal for normal products. |
| `TechnologyDomainAnalystAgent` | As handoff owner: hosted `web_search`, bounded provider search/fetch/quote, run-evidence lookup, evidence/candidate comparison, deterministic listing-trust check, and scoped source consultation; its separate per-product typed analyst has no tools. | May finish a broad technology request or SDK-handoff to one of six approved product specialists; source specialists remain nested tools. | Region-bound run-scoped research and validated persisted evidence. | Routing non-technology products into technology specialists, inventing undeclared specialists, arbitrary provider access, exposing internal agent names to shoppers. |
| `MonitorSpecialistAgent` | Hosted `web_search`, bounded provider search/fetch/quote, run-evidence lookup, evidence/candidate comparison, deterministic listing-trust check, and scoped source consultation as a handoff owner. | Terminal SDK handoff owner for monitors; separate typed per-product sub-run. | Supplied monitor context and previously recorded evidence. | Analyzing non-monitor products as monitor-scoped, raw provider access, unsupported factual claims. |
| `SmartphoneSpecialistAgent` | Hosted `web_search`, bounded provider search/fetch/quote, run-evidence lookup, evidence/candidate comparison, deterministic listing-trust check, and scoped source consultation as a handoff owner. | Terminal SDK handoff owner for phones; separate typed per-product sub-run. | Supplied phone context and previously recorded evidence. | Analyzing non-phone products as phone-scoped, raw provider access, unsupported factual claims. |
| `LaptopSpecialistAgent` | Hosted `web_search`, bounded provider search/fetch/quote, run-evidence lookup, evidence/candidate comparison, deterministic listing-trust check, and scoped source consultation as a handoff owner. | Terminal SDK handoff owner for laptops; separate typed per-product sub-run. | Supplied laptop context and previously recorded evidence. | Analyzing non-laptop products as laptop-scoped, raw provider access, unsupported factual claims. |
| `EarphonesHeadphonesSpecialistAgent` | Hosted `web_search`, bounded provider search/fetch/quote, run-evidence lookup, evidence/candidate comparison, deterministic listing-trust check, and scoped source consultation as a handoff owner. | Terminal SDK handoff owner for audio; separate typed per-product sub-run. | Supplied audio context and previously recorded evidence. | Analyzing non-audio products as headphone-scoped, raw provider access, unsupported factual claims. |
| `TVSpecialistAgent` | Hosted `web_search`, bounded provider search/fetch/quote, run-evidence lookup, evidence/candidate comparison, deterministic listing-trust check, and scoped source consultation as a handoff owner. | Terminal SDK handoff owner for TVs; separate typed per-product sub-run. | Supplied TV context and previously recorded evidence. | Analyzing non-TV products as TV-scoped, raw provider access, unsupported factual claims. |
| `SmartwatchSpecialistAgent` | Hosted `web_search`, bounded provider search/fetch/quote, run-evidence lookup, evidence/candidate comparison, deterministic listing-trust check, and scoped source consultation as a handoff owner. | Terminal SDK handoff owner for watches; separate typed per-product sub-run. | Supplied watch context and previously recorded evidence. | Analyzing non-watch products as watch-scoped, raw provider access, unsupported factual claims. |
| `SellerListingTrustAgent` | None. | None. | Supplied listing, evidence, deterministic trust-rule assessment, price-plausibility signals, and optional seller/listing-scoped hosted `web_search`. | Silently overriding hard suspicious flags, treating a search snippet or rating as verified seller trust, fetching arbitrary seller pages, treating product quality as listing trust. |
| `SourceIntelligenceManagerAgent` | Model-running post-dedupe parent in live-agent shopping runs; fixture mode has no parent model call. | Choose relevant source specialists and explain skipped sources. | Four SDK specialist agent-tools over server-supplied candidates and region. | Direct provider SDK access, invented evidence, bypassing specialist/capability budgets. |
| `YouTubeReviewIntelligenceAgent` | SDK agent-as-tool under the live source manager; isolated workbench fixture mode uses `YouTubeReviewIntelligenceService`. | Select review videos, interpret timestamped product-specific pros/cons/concerns and visible bias. | Bounded `search_videos`, `read_video_metadata`, `read_video_transcript`, and optional YouTube-scoped hosted `web_search`. | Direct `yt-dlp`, WebVTT parsing, arbitrary API args, fabricated transcript claims, final recommendations. |
| `RedditCommunityIntelligenceAgent` | SDK agent-as-tool under the live source manager; isolated workbench fixture mode uses `RedditCommunityIntelligenceService`. | Select public discussions and interpret cited qualitative owner signals. | Bounded `search_community_discussions`, `read_community_discussion`, and optional Reddit-scoped hosted `web_search`. | Private/deleted/logged-in access, treating anecdotes as authoritative facts, final recommendations. |
| `AmazonProductIntelligenceAgent` | SDK agent-as-tool under the live source manager; isolated workbench fixture mode uses `AmazonProductIntelligenceService`. | Select relevant marketplace sources, interpret ASIN/variant identity, and organize cited product, offer, seller, review, and region evidence. | Bounded `search_amazon_products`, `read_amazon_product`, and optional marketplace-scoped hosted `web_search` over approved provider results and persisted source context. | Affiliate links, unapproved scraping, invented prices/review counts/shipping, collapsing seller risk into product quality. |
| `IKEAStoreIntelligenceAgent` | SDK agent-as-tool under the live source manager; isolated workbench fixture mode uses `IKEAStoreIntelligenceService`. | Select relevant official regional product sources and interpret cited item, local price/currency, availability, and store/delivery context with gaps. | Bounded `search_ikea_products`, `read_ikea_product`, and optional official-region-scoped hosted `web_search` over approved results and persisted snapshots. | Global shipping inference, non-official source substitution, unapproved scraping, invented regional purchase claims. |
| `ComparisonDecisionAgent` | None. | None. | Supplied brief, category analyses, trust assessments, dedupe decisions, and evidence. | New search/extraction, unsupported product claims, recommending suspicious listings without blocking warning, forced avoid items for ordinary non-winners. |
| `VerifierCriticAgent` | Isolated live workbench implementation with deterministic output guardrails. | None. | Supplied draft recommendation bundle, products, listings, source evidence, trust assessments, category analyses, and dedupe decisions. | New provider calls, hidden rewriting without blocking issues, approving uncited factual claims or shopper-visible internal process language. |

### Research access: implemented and planned roles

| Role | Hosted OpenAI web search | Approved provider/other tools | Shopper ownership |
| --- | --- | --- | --- |
| `GeneralShoppingAgent` | Wired in opt-in live runs; model may use or skip it | Bounded provider search/fetch/quote plus run-evidence, comparison, listing-risk, and source-intelligence helpers | First live owner; may finish or SDK-handoff to Technology. |
| `TechnologyDomainAnalystAgent` | Wired in opt-in live runs; model may use or skip it | Same bounded owner research helpers with buyer-region and run scope | May finish broad technology requests or SDK-handoff to one matching approved specialist. |
| Six implemented product specialists | Wired in opt-in live runs; model may use or skip it | Same bounded owner research helpers with buyer-region and run scope | May finish as terminal SDK handoff owners with a `GeneralModelOutput` draft; their separate per-product typed runs still return `CategoryAnalysis`. |
| `DiscoveryAgent` | Wired in live SDK runs; model may use or skip it | Existing `search_sources` and `fetch_source` remain | Bounded research step, not request owner. |
| `SellerListingTrustAgent` | Wired in live SDK runs; model may use or skip it | Supplied deterministic trust signals and scoped seller/listing evidence | Trust evidence only. |
| YouTube, Reddit, Amazon, IKEA source specialists | Wired in live SDK runs, scoped to each source remit; model may use or skip it | Their existing site-specific search/read tools remain | Bounded evidence agents-as-tools only. |
| `SourceIntelligenceManagerAgent` | No unrestricted hosted search planned | Delegates to the four source specialists | Delegator only. |
| `ShoppingGuideAgent`, `IntakeAgent`, `ExtractionAgent`, `ComparisonDecisionAgent`, `VerifierCriticAgent`, and other intake/planning/routing-only roles | No hosted search planned under current remit | Existing scoped inputs/tools as listed above | No active shopper-request ownership. |

Attaching the tool does not claim that a call occurred. The active model chooses whether to use hosted search or an approved
provider tool; backend validation decides which results support claims. Search
hits alone are not verified listings or citations. The catalog separates
`planned_sdk_tools` and `target_handoff_agent_names` from today's
`approved_sdk_tools` and `ProductAnalysisRoute`.

## Schema Boundaries

- `ShoppingBrief` is owned by intake and user corrections.
- `SearchPlan` and source strategy are owned by query planning.
- `SearchResult` and `SourceSnapshot` are provider/persistence records, not semantic product classifications. Generic results remain eligible for agent inspection.
- Live `ExtractionAgent` output owns cited `CanonicalProduct`, `ProductListing`, product mentions, `SourceEvidence`, and explicit gaps; one snapshot may yield zero, one, or many entities. Deterministic parsing may provide signals, while schema/source-ID validation and policy checks remain hard backend gates. `ProductListingExtractor` remains a fixture/legacy helper, not the live semantic authority.
- `DeduplicationDecision` records duplicate reasoning and must preserve uncertain cases.
- `ReusableSourceIntelligenceRequest` is the orchestrator's shared source-capability request. The four typed specialist inputs carry run ID, brief, products, listings, persisted snapshots, source-specific query hints, and applicable region. Product/listing/snapshot IDs must be unique and listings must reference supplied products. The four bundle schemas require local source references for evidence and gaps, unique evidence IDs, and valid video/discussion/listing/store context links. Provider failures and unavailable source content produce explicit gaps or empty evidence, never invented claims. The SDK source manager uses a strong profile, each specialist uses its own fast profile, and the backend bounds calls, turns, tools, and accepted source/evidence IDs.
- `VideoReviewEvidenceBundle` is the YouTube/source-video evidence boundary. It must include transcript availability status, source references, timestamped transcript evidence where available, explicit transcript gaps where unavailable, and sponsorship/affiliate-bias signals.
- `CommunityDiscussionEvidenceBundle` is the Reddit/community evidence boundary. It includes thread/comment source references, extracted public snippets or summaries where allowed, exact supporting quotes for SDK-interpreted qualitative signals, recency/engagement context when available, evidence-quality warnings, and explicit gaps.
- `AmazonProductEvidenceBundle` is the Amazon evidence boundary. It must include product/listing identity, marketplace/region context, seller/fulfillment signals, product-page facts, review-summary signals, availability/ship-to-region evidence, and suspicious marketplace/review warnings.
- `IKEAStoreEvidenceBundle` is the IKEA evidence boundary. It must include country/region context, official product/store source references, product-page facts, regional price/currency where available, availability/store/delivery signals, and explicit gaps.
- `ListingTrustAssessment` is the seller/listing trust boundary and must remain separate from product desirability. It preserves deterministic signal rows for seller identity, established retailer/source type, review count, return/warranty clarity, suspicious price, missing metadata, and contradictory listing data.
- `CategoryAnalysis` is the product/category analysis boundary.
- `RecommendationBundle` is the comparison and decision boundary.
- Important output schemas should be versioned when implemented.
- Factual claims about products, listings, prices, sellers, reviews, source-only metadata, region availability, community discussion, marketplace evidence, official-store evidence, or video evidence must reference source IDs.
- Known, unknown, and inferred fields must remain distinguishable.
- Product-level and listing-level entities must not be collapsed.

## Provider And Compliance Constraints

- Providers must be configured through explicit adapters; agents should not directly call vendor SDKs or scrape pages outside approved tools.
- Provider adapters should expose capability and compliance flags so agents can distinguish disabled providers, metadata-only evidence, transcript access, community discussion retrieval, marketplace product/review retrieval, regional official-store lookup, and availability signals before using provider output.
- Provider keys, enabled-provider flags, timeouts, and capability flags belong in runtime configuration once implementation begins.
- Reseller-only platforms are excluded initially. Mixed marketplaces are allowed only when seller/listing trust can be assessed.
- YouTube metadata may come from the official YouTube Data API when configured.
- YouTube transcript text may be used only through authorized official caption access, future user-provided transcript input, or the accepted self-managed `YtDlpTranscriptProvider` public-caption path.
- `YtDlpTranscriptProvider` must remain behind the typed provider boundary with pinned `yt-dlp`/`yt-dlp-ejs` and Deno dependencies, fixed backend-owned arguments, no cookies or media downloads, bounded execution/storage, deterministic WebVTT parsing, and explicit metadata-only gaps for failed access.
- Video evidence must preserve video IDs, source URLs, channel metadata where available, timestamps when available, transcript availability status, and evidence confidence.
- Reddit evidence may use approved domain-scoped search and compliant extraction of public pages. It must preserve URLs and source context, avoid private/deleted/logged-in-only content, and represent anecdotal community evidence as lower-confidence unless corroborated.
- Amazon evidence may use compliant APIs, approved providers, or permitted user-visible pages. It must preserve neutral links, avoid affiliate behavior, keep product/listing/seller/review evidence separate, and represent unavailable regional shipping or missing review access as explicit gaps.
- IKEA evidence should use official country/region source pages or approved providers. It must preserve country/region context and must not infer global availability or shipping from brand presence.
- No source agent may fabricate unavailable transcript claims, review claims, seller details, prices, or warranty facts.

## Adding Or Moving An Agent

When introducing or changing an agent:

1. Edit this file, marking a new agent as `proposed-later`, `candidate-mvp`, or `required-mvp` according to the approved product scope.
2. Record the decision and rationale in `docs/DECISIONS.md`.
3. Identify ownership, routing scope, fallback, input/output schema, permitted tools/providers, guardrails, compliance constraints, trace expectations, and necessary eval cases.
4. Implement or update the executable registry only in the dedicated implementation task.
5. Implement the agent only in its dedicated implementation milestone.
6. Add routing tests, schema tests, trace expectations, provider fixtures where relevant, and eval cases.
7. Update status to `implemented` only after code, tests, and eval coverage pass.

Examples:

- Add a Mouse Analysis Agent: place it under the implemented technology domain and keep technology-domain plus generic fallback.
- Add a Kitchen Appliances domain agent: define the categories and shared domain rules first, then add any deeper appliance specialists later.
- Add a YouTube review capability: keep it in the reusable source intelligence layer and allow multiple product/domain agents to call it.
- Add a Reddit community capability: keep it in the reusable source intelligence layer and treat community discussion as qualitative source evidence, not definitive product truth.
- Add an Amazon product intelligence capability: keep it in the reusable source intelligence layer unless it becomes part of a broader marketplace product intelligence layer.
- Add an IKEA regional store capability: keep it in the reusable source intelligence layer because it is official source/store evidence that varies by country or region.
- Add a brand-store capability: make it region-aware because official stores, warranties, and availability vary by country.
- Move a specialist: update this file, the decision record, runtime registry, routing tests, and eval cases together.
- Change fallback: treat this as a behavior change requiring documented rationale and regression evaluation across affected categories.
