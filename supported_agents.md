# CartCart Supported Agents And Source Capabilities

## Validated final output, Task 224

All retained model paths share structured final-output validation. An incomplete response stays a technical failure. A normal or saved shopping owner may make one affordable tools-free completion from retained research within the same attempt and spent ledgers. It keeps the same owner/model/reasoning and model-authored choices. The saved-decision cap alone increases from 2,000 to the existing 6,667 ceiling. No agent, source capability, routing edge or provider fallback is added.

YouTube literal focus misses retain available captions and point to keyword or unfiltered reads of the saved transcript. They never establish a caption-access gap. Whole validated speech and cautions remain required for interpreted evidence.


## Task 223 source lifecycle contract

`SourceIntelligenceManagerAgent` owns `SourceConsultationOutcome`. YouTube, Reddit, Amazon and IKEA SDK returns share honest `no_attempt`, `interrupted`, `technical_failure`, `provider_gap`, `partial` and `succeeded` classification. Empty evidence-gap bundles are not successful consultations. Accepted evidence survives later execution failure with safe diagnostics. The runtime catalog declares this contract without changing ownership, providers, profiles or tool allowlists.

Only the video path has durable raw discovery/metadata/caption progress and consumed-operation recovery. Its catalog flag is `durable_video_progress`. Explicit focused source retry is restricted to that capability. Existing other-source provider gaps remain available context, and a technical SDK failure is never converted into provider unavailability. No source consultation, channel or video is mandatory for a shopping journey.

The YouTube specialist promptly confirms identity and attempts approved captions for a relevant discovered review before redundant searches or metadata reads. Real caption gaps can motivate reasonable relevant public alternatives within current bounds. Raw titles, metadata and hosted snippets remain leads. Whole accepted speech with video/source/segment IDs, timestamps, URL and hash reaches the normal owner and optional neutral sources below advice. Source legitimacy, disclosures and substance remain material; production polish alone establishes no credibility.


## Funded completion, Task 222

All retained model paths use the approved 4/3 token scaling. General, Technology
and terminal owner handoffs share one starting 120,000-token allocation. A source
manager and its supported YouTube, Reddit, Amazon and IKEA specialists share a
starting 40,000-token allocation inside the same 200,000-token attempt. Bounded
transfers secure actual requests and active completion paths. Inactive stages
hold no allocation, and unaffordable hosted search can leave native tools eligible.

Completion follows the output contract. Normal owners give concise buying
advice. Source specialists return metadata, interpreted speech, provenance and
accurate gaps. Standalone `CategoryAnalysis` agents finish structured analysis.
An optional source funding gap is retryable and does not establish provider or
caption unavailability. Useful owner work can still finish through the normal
saved-result path. No agent hierarchy, source capability, provider selection or
routing fallback changed. [The context policy](docs/CONTEXT_MANAGEMENT.md#limits-and-accounting)
defines funding and accounting; [the handoff](docs/TASK_222_IMPLEMENTATION_HANDOFF.md)
lists every retained consumer and focused control. Task 221 remains incomplete.

## Shopper prose ownership, Task 219

The General shopping owner, its Technology/specialist handoffs, retained category/comparison agents and optional editorial verifier share concise what-to-buy guidance. Reasons, meaningful relative tradeoffs, budget/value explanations and major product limitations belong in advice. Confidence, evidence gaps and process cautions remain internal. Routine seller, availability, checkout and launch-absence work is not part of the normal question.

Agent identities, hierarchy, catalog routes, tool permissions and provider fallback are unchanged. Optional investigation of a concrete adverse listing concern remains available to the owner. No mandatory seller-check stage or model call is added. Controlled fixture copy avoids developer labels without editing canonical evidence or filtering real words. Live validation deferred to Task 221.

## Choice authoring, Task 218

The current General shopping owner, its Technology/specialist handoffs and the retained comparison agent author distinct primary choices and optional runners-up. Live owner candidates carry `choice_group`; persisted bundles carry `primary_product_ids` and `runner_up_product_ids`, with per-product explanations retained in mode records. Primary choices have a maximum of three, runners a maximum of two. One or two primary choices and no runners are valid.

Useful company/provider variety is model guidance, not an eligibility registry. Same-company family/size variants usually belong among runners, unless an exclusive preference or meaningful difference warrants primary choices. The model weighs suitability, adverse information and supported modest budget stretches. Missing sources or offer details do not suppress advice.

Agent identities, hierarchy, catalog routes, tool permissions and source-provider fallback remain unchanged. This task changes the authored/retained choice contract, not the routing catalog. Historical bundles and owner checkpoints remain readable. Live validation is deferred to Task 221; the implementation conversation authorizes no model, research or caption calls.

## Current recommendation policy, Task 216

Ordinary shopping gathers information where available and passes it with buyer preferences to the owning LLM. The model recommends by default and weighs strong adverse information. Missing sources, reviews, prices, stock, warranty or support details are unknowns, not reasons for automatic rejection. Source quality, comparison and seller scores are advisory. Official stores need no mandatory background check. Budgets inform the model, including explained slightly over-budget alternatives. Unlimited budget remains distinct from missing budget.

Advice and source associations are independent. Recommendation evidence IDs, sources, comparison matrices, checked listings and mode records are optional. The UI leads with recommendations, reasons and meaningful tradeoffs, then shows available page sources and search snippets. Unknowns remain diagnostic fields. A snippet is labeled as a snippet. A source note is not a verbatim quotation. No exact substring, quote visibility, span membership or hash equality admits recommendations or retries.

The normal, refinement and saved-retry workflows do not invoke a mandatory verifier. The active owner remains General -> Technology -> the appropriate specialist for supported technology, including Smartphone. `VerifierCriticAgent` remains an explicit optional tool-free editorial workbench capability. It cannot block or replace the owner's buying judgment. Its configured model/profile and authorized 180-second override remain available when explicitly invoked. Request refusal uses the installed OpenAI Agents SDK input guardrail, with no application phrase tripwires. Classifier timeout or invalid output is a retryable technical error.

The owner resumed live calls on 2026-10-11. Tasks 216, 214, 215 and 100A passed revised guided-browser acceptance. See [saved IDs, browser evidence, SQLite/API matches, usage and checks](docs/TASK_216_LIVE_ACCEPTANCE.md). No P1 work started. Historical policies and recorded tests below are superseded wherever they require citations, exact provenance, source counts, mandatory verification, seller exclusions or hard budget vetoes.


Status: Agent-first research runtime with fixture limitations called out below
Last updated: 2026-10-06

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
- The 2026-06-12 guided-intake backfill adds fixture-mode `ShoppingGuideAgent` and `ShoppingScopeGuardrail` contracts to the runtime catalog. The live OpenAI Agents SDK `ShoppingScopeGuardrail`, `IntakeAgent`, `ShoppingGuideAgent`, `QueryPlannerAgent`, `DiscoveryAgent`, `CategoryRouterAgent`, `GenericProductAnalystAgent`, `TechnologyDomainAnalystAgent`, `MonitorSpecialistAgent`, `SmartphoneSpecialistAgent`, `LaptopSpecialistAgent`, `EarphonesHeadphonesSpecialistAgent`, `TVSpecialistAgent`, `SmartwatchSpecialistAgent`, `SellerListingTrustAgent`, `ComparisonDecisionAgent`, and `VerifierCriticAgent` are available through their typed protocols in the isolated workbench and, when explicitly configured, applicable shopping-run stages. The verifier is an optional workbench capability and is omitted from shopping runs. The 2026-06-21 reusable source-intelligence implementations for YouTube, Reddit, Amazon, and IKEA are provider-backed through typed provider/service and evidence-creation boundaries in the isolated workbench and opt-in normal workflow. The normal full shopping workflow remains fixture-first by default; live-agent workflow mode requires explicit configuration and credentials.
- Four source SDK specialists and their parent agent-as-tool wiring are implemented and passed the Task 89P gate: focused offline checks cover all four specialists and parent delegation, and an authorized unsandboxed OpenAI smoke confirmed a real Sol parent invoking the Luna IKEA specialist as an SDK tool over an in-process fixture, returning validated cited evidence. Real source providers and the normal end-to-end live shopping workflow were not exercised; local app settings still select fixture-agent mode by default.

## Architectural Decision

CartCart uses deterministic workflow orchestration with typed agent steps. The orchestrator owns workflow stages, persisted state, evidence, errors, retries, and tracing.

### Shopper ownership

Today the guided API gathers a brief, then the live run enters
`GeneralShoppingAgent` after intake and before query planning, discovery, or
category routing. The last SDK owner authors the persisted result after
operational parsing and persistence without a mandatory verifier.
`CategoryRouterAgent` returns a `ProductAnalysisRoute`; domain/specialist calls
return `CategoryAnalysis`; `ComparisonDecisionAgent` remains a separate typed
capability, not the live result author.
These route strings, Python sub-runs, and source agents-as-tools are **not**
OpenAI Agents SDK handoffs. General now has one real SDK handoff option to
`TechnologyDomainAnalystAgent`. The SDK's completed handoff item, validated
reason/context, resolved models, and `last_agent` are recorded in the run trace
and result provenance.
`GeneralShoppingAgent` has an SDK runner in
the normal opt-in live workflow and the isolated workbench. Live
`DiscoveryAgent`, listing trust, the four source-intelligence specialists,
General, Technology, and all six product specialists have scoped hosted OpenAI
`WebSearchTool` access in live runs;
Discovery's separate
`search_sources` and `fetch_source` tools call application providers only.

The guided API retains progressive questions, skipping/reanswering,
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

`GenericProductAnalystAgent` remains an evidence-only per-product analysis
fallback returning `CategoryAnalysis`; it is distinct from General and is not
a shopper-request handoff target. `ComparisonDecisionAgent` remains available
for isolated typed/fixture use; it no longer authors the live owner result.
`DiscoveryAgent` and `ExtractionAgent` supply bounded research and cited
entities. `SellerListingTrustAgent` supplies separate listing-risk evidence.
Manual fallback entries are labeled user reports. They can inform model recommendations without a checked offer or independent citation. Source and seller tools provide advisory context without taking ownership. The actual last owner authors concise reasons, tradeoffs, unknowns and specific warnings. Backend code preserves run identity, credentials, bounded context/spending, neutral links, actual ownership and immutable result versions. Source associations are optional and cannot erase advice.

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
operational identity and access checks remain necessary. Missing citations, failed hosted
calls, and incompatible model overrides surface as explicit gaps/errors.
Models are selected through the existing environment settings, run profiles,
and exact-agent overrides. Hosted-tool attachment does not use a model-name
allowlist. The OpenAI API validates model availability, hosted-tool support,
and the submitted reasoning settings during the bounded request. CartCart
does not change the selected model for an agent or drop required tools after
an API rejection. Technology owner recovery after a specialist failure remains
a separately recorded run.

Specialized product/domain agents should normally be invoked as typed sub-runs or agents-as-tools when the orchestrator needs a scoped analysis result. OpenAI Agents SDK handoffs should be used only when a specialist should actually take over control of a conversational turn.

The YouTube, Reddit, Amazon, and IKEA roles have model-running OpenAI Agents SDK implementations with bounded source-specific tools and optional site-scoped hosted search. In the normal live-agent path, the current shopping owner may call `consult_source_intelligence` for a relevant candidate. `SourceIntelligenceManagerAgent` delegates the requested capability through SDK agents-as-tools. Retained comparison workflows can also invoke the separate source stage. Default fixture-provider runs remain network-free provider-backed simulations; a service call is never counted as a model run. Source agents return cited evidence, not recommendations. Hosted citations are persisted as weak source leads; only validated site-tool evidence supports transcripts, discussion signals, marketplace offers, or official IKEA claims.

The product supports broad shopping queries when no deep specialist exists. The
generic per-product analysis fallback remains, and the live General owner can
finish the shopper request itself.

Shared SDK configuration supplies current-date and regional research guidance
to hosted-search roles, including the four source specialists and listing trust.
The catalog's `CurrentRegionalResearchGuidance` and
`ShoppingRunFailureReporting` owner boundaries document that behavior. Source
specialists retain their site restrictions and return evidence rather than
recommendations. Agents without research tools use supplied evidence; the shared
prompt does not grant new tool permissions.

`SmartphoneSpecialistAgent` also declares `PhoneReleaseAndLaunchGuidance`.
Its owner prompt prioritizes releases from the past 365 days, considers one- to
two-year-old phones for value, and researches credible imminent launches before
advising whether to buy now. Explicit unlimited budget favors current flagships;
unspecified budget remains unspecified. Official regional availability and
warranty are checked separately from global reviews. An official product or
launch page can inform a qualified product-only option
without a priced listing or independent review. Reviews improve comparative
confidence. Broad questions begin with category, buyer-intent and regional discovery,
then follow useful results into relevant companies and products. Named families are
preferences unless explicitly exclusive. No manufacturer list or preferred video
channel controls eligibility. Optional video review consultation uses approved
public captions for substantive review claims, never titles as a transcript. Known prices inform model judgment; checked offers and modes are optional. General and Technology
are instructed to delegate known phone categories early, with real SDK handoff
records proving whether the phone owner actually ran.

Reusable source specialists declare `LiveProviderEvidenceGaps`: in a normal live
workflow, unavailable or unconfigured source providers return disabled/empty
evidence, never fixture transcripts, discussions, reviews or offers. Fixture
workflows and explicit offline provider injection retain deterministic replay.

An unrecovered technical owner failure is retained in tool activity as
`research_failed` and stops the shopping workflow with a failed run. A completed owner call may make an explicit no-option judgment. Missing evidence alone does not force that judgment. Normal shopping APIs reject live providers combined with fixture agents
before research begins. Fixture-only runs and isolated provider probes remain
available.

## Accepted Scope Decisions

- `GenericProductAnalystAgent` is the per-product analysis fallback for normal categories; live `GeneralShoppingAgent` owns the whole request and can finish broad categories.
- `ShoppingGuideAgent` is the user-facing guided intake role. It asks one plain-language question at a time, supports skip/reanswer behavior, and decides when enough information exists to start analysis without exposing internal workflow mechanics.
- `ShoppingScopeGuardrail` is the shopping-scope and safe-consumer-product guardrail. It blocks or redirects off-topic, unsafe, illegal, or inappropriate requests before discovery or analysis starts.
- `TechnologyDomainAnalystAgent` is an MVP domain layer so technology routing is modular from the beginning.
- MVP technology specialists are `MonitorSpecialistAgent`, `SmartphoneSpecialistAgent`, `LaptopSpecialistAgent`, `EarphonesHeadphonesSpecialistAgent`, `TVSpecialistAgent`, and `SmartwatchSpecialistAgent`.
- `YouTubeReviewIntelligenceAgent`, `RedditCommunityIntelligenceAgent`, `AmazonProductIntelligenceAgent`, and `IKEAStoreIntelligenceAgent` are approved as reusable `required-mvp` source intelligence capabilities, not as category specialists.
- Reusable source intelligence agents are evidence retrieval and normalization tools. They must not be limited to availability checks, and they must not make final purchase recommendations.
- YouTube metadata may use the official YouTube Data API when configured. Approved public-caption access is implemented by the self-managed `YtDlpTranscriptProvider` behind the typed `TranscriptProvider` boundary. Authorized official captions and future user-provided transcript input remain distinct access strategies. The system must never assume transcript availability.
- YouTube model or validation failures return metadata-only evidence with an explicit gap. Visible sponsorship and affiliate disclosures, channel signals, observed transcript availability, and source references remain attached to the fallback. Transcript text comes only from approved tools; failed model claims do not enter evidence. The catalog declares the fixture evidence-gap fallback.
- Reddit community evidence should be gathered through approved search/extraction providers, for example domain-scoped web search for public `reddit.com` results. It must summarize recurring user-reported patterns with source links and quality warnings rather than treating anecdotes as authoritative product facts.
- Amazon product intelligence should retrieve product/listing identity, seller/fulfillment, regional availability or ship-to-region status, product-page information, and review signals when compliant provider access is available. It must preserve marketplace seller risk separately from product quality and must not add affiliate logic.
- IKEA store intelligence should retrieve official IKEA product/store evidence for the user's region when applicable, including regional product availability, product-page information, price/currency where available, and evidence gaps. It must not assume IKEA ships globally; it should check whether IKEA has a relevant country/region presence and whether the item is available there.
- The current IKEA adapter uses the configured general search provider with strict official domain and country-path filtering. Fixture mode is the default; unsupported regions and unavailable products return explicit gaps without implying cross-region shipping.
- Broad non-technology domain layers should remain `proposed-later` until multiple implemented specialists or shared domain rules justify them.
- Current invocation uses typed steps, tools, sub-runs, and real SDK handoffs only when live shopper ownership transfers to Technology or an eligible specialist.

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
  VerifierCriticAgent                                        [implemented]
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

The implemented reusable source-intelligence SDK agents own scoped source
selection and interpretation in live runs; fixture provider services package
source evidence without model judgment. Both paths return structured evidence
with source references and confidence, not final purchase recommendations.

`SellerListingTrustAgent` evaluates seller context separately from product fit. The model may improve or worsen a rule-derived assessment using supplied information. An official store provides acceptable context without a mandatory background check. Source identity and actual concerns are preserved with their scope. Missing reviews, policy details and scores cannot reject a recommendation.

`ComparisonDecisionAgent` remains the owning model for retained comparison and refinement paths. Ranked candidates and lowered advisory scores inform its judgment. It may recommend options without prices, sources, mode records or a decisive winner. `VerifierCriticAgent` remains optional editorial assistance in the isolated workbench and is omitted from shopping runs.

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
separate transcript-ingestion path uses the accepted self-managed
`YtDlpTranscriptProvider` for approved public captions. It preserves language and
timestamps, records unavailable/provider-failure gaps, and refuses video claims
that are not present in cited transcript text. The current model-running
`YouTubeReviewIntelligenceAgent` interprets product-specific review claims through
bounded tools, validates cited transcript excerpts, and returns evidence rather
than purchase recommendations. The provider uses pinned local dependencies,
fixed arguments, no cookies, no media downloads, and no remote EJS components.
Execution and temporary storage are bounded. Failed access or interpretation
retains metadata-only context and explicit gaps.

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
| `ExtractionAgent` | `required-mvp` | Interpret each persisted page, including review roundups and multi-product collection pages; separate product, listing, seller, and review facts and judge whether cited listings match a shopper-considered product. | Live typed agent step over approved persisted-snapshot reader | Assigned snapshot IDs, bounded page text, cited leads, and user-added product hints | Zero/one/many cited products/listings, review mentions/evidence, lead matches, confirmed/possible user-added matches, and gaps | Preserve unknowns and ambiguous variants; invalid citations/schema become explicit gaps. Bounded research cycles feed review/collection mentions to DiscoveryAgent before shortlist construction. |
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
| `SellerListingTrustAgent` | `required-mvp` | Review seller/store/listing legitimacy, suspicious prices, and trust/red-flag evidence. | Cross-cutting typed step | Listings and source evidence | `ListingTrustAssessment` | Unknown trust remains an unknown. The model may improve or worsen the rule-derived assessment; scores and concerns are advisory. |
| `YouTubeReviewIntelligenceAgent` | `required-mvp` | Discover relevant product review videos, collect permitted transcript/metadata evidence, summarize product-specific claims, and return timestamped source evidence. | Reusable source agent/tool | Brief, candidate products, optional source/video queries | `VideoReviewEvidenceBundle` | If transcripts are unavailable, return metadata-only evidence or explicit evidence gaps; never fabricate video claims. |
| `RedditCommunityIntelligenceAgent` | `required-mvp` | Discover relevant Reddit discussions, collect permitted public thread/comment evidence, summarize recurring owner/community signals, and flag anecdotal or low-quality evidence. | Reusable source agent/tool | Brief, candidate products, optional source/community queries | `CommunityDiscussionEvidenceBundle` | If relevant public content cannot be fetched or quality is weak, return explicit evidence gaps; never treat anecdotes as authoritative product facts. |
| `AmazonProductIntelligenceAgent` | `required-mvp` | Assess Amazon product/listing identity, seller/fulfillment, regional availability or ship-to-region status, product-page information, review signals, and suspicious marketplace/review patterns. | Reusable source agent/tool | Product/listing candidates and target region | `AmazonProductEvidenceBundle` | Use only compliant APIs/providers or permitted user-visible pages; preserve seller/listing trust concerns separately from product desirability. |
| `IKEAStoreIntelligenceAgent` | `required-mvp` | Check whether IKEA has relevant country/region presence, retrieve official IKEA product information, regional price/currency and availability where available, and store/delivery evidence gaps. | Reusable source agent/tool | Product/listing candidates, product/category intent, and target region | `IKEAStoreEvidenceBundle` | If IKEA is unavailable in region or product evidence is missing, return an evidence gap; never imply global shipping or availability. |
| `MarketplaceProductIntelligenceAgent` | `proposed-later` | Gather product-page, listing, review, availability, shipping, seller quality, and region-relevance evidence across mixed marketplaces. | Reusable source agent/tool | Product/listing candidates and region | Marketplace product evidence | Fall back to listing trust/source quality rules. |
| `OfficialBrandStoreAgent` | `proposed-later` | Locate official brand/store pages by country and assess official price, availability, warranty, and authorized sellers. | Reusable source agent/tool | Brand/product and region | Official-source evidence | Generic search/source extraction fallback. |
| `ProfessionalReviewSourceAgent` | `proposed-later` | Gather structured evidence from reputable written review sites and lab-test sources where available. | Reusable source agent/tool | Product/category and region | Review evidence | Generic source extraction fallback. |
| `CommunityDiscussionSignalAgent` | `proposed-later` | Summarize recurring owner complaints/praise from community discussions when allowed and source quality is adequate. | Reusable source agent/tool | Product/category and source set | Community signal evidence | Treat as lower-confidence qualitative signal, not definitive truth. |
| `ComparisonDecisionAgent` | `required-mvp` | Compare candidates and generate recommendation modes from one analysis pass. | Typed step | Brief and all assessed candidates, including source-free manual fallback entries | `RecommendationBundle` | Recommend by default from available context. User-reported candidates may inform advice without a checked offer. Scores, sources, prices and modes are optional; meaningful rejections remain model-authored. |
| `VerifierCriticAgent` | `implemented` | Offer optional editorial suggestions when explicitly invoked. | Tool subrun in the workbench | Draft advice and available context | Nonblocking editorial notes preserving the owner choice | No per-claim source revalidation or buying veto. Normal runs omit this stage. |

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
guide uses structured output, SDK input-guardrail checks, mocked/live
workbench scenarios, and an `IntakeAgent` handoff only when it reaches
`ready_for_analysis`. The live query planner uses structured output with no
tools and falls back to a generic region-aware search plan rather than blocking
categories without specialists. The live discovery agent uses structured
output, bounded provider search/fetch tools, and optional hosted web search.
It can judge generic results and perform bounded follow-up research. The live
category router uses structured output with
no tools, normalizes route decisions through the executable catalog, sends MVP
technology specialist categories through `TechnologyDomainAnalystAgent`, and
falls back to `GenericProductAnalystAgent` for unsupported or uncertain
categories. The live generic product analyst uses structured output with no
tools, analyzes supplied product/listing/evidence bundles for any normal
consumer category, preserves source and evidence IDs, and returns explicit
limitations instead of category refusal when evidence is weak. The following
technology and specialist descriptions refer to their separate per-product
`CategoryAnalysis` runs; as handoff owners, they have the scoped research tools
listed in the tool matrix below. The per-product live
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
failure. The live seller/listing trust agent consumes the supplied listing,
evidence, and deterministic assessment. It may use seller/listing-scoped
hosted web search and may improve or worsen the advisory rule-derived assessment.
Actual concerns retain their scope. The live comparison decision agent uses
structured output with no tools, consumes supplied candidates, optional evidence,
trust, budget and dedupe context, and returns a `RecommendationBundle`.
Model/output failure is a retryable technical error with saved research.
In the live source-intelligence stage, a model-running
manager delegates to YouTube, Reddit, Amazon, and IKEA SDK agents-as-tools.
Those agents use bounded source tools and return cited evidence bundles;
fixture runs use provider services without model calls. The normal shopping
workflow remains fixture-first and uses live agents only when explicitly
configured. Phone routing accepts `phone`, `smartphone`, `mobile phone`,
`phones`, `smartphones`, and `mobile phones` through the existing catalog.
Both SDK handoff callbacks validate the requested category and buyer's brief;
plural aliases do not change the owner graph or fallback chain.
Category rejections retain bounded `rejected_handoff` metadata in internal
owner activity. Unrecognized category labels become `null`.
Local routing eval cases cover broad generic fallback,
technology-domain routing, every MVP technology specialist route, and
specialist fallback availability to technology-domain and generic analysis
without live model calls. The current runtime
invokes `QueryPlannerAgent`, executes
the resulting queries
through the configured `SearchProvider`, and persists accepted, policy-scored
search results. Eligible result pages then pass through the configured
`ExtractionProvider`; usable snapshots create persisted app-generated products,
listings, and shortlist memberships. Reusable source intelligence runs after
deduplication. The seller/listing trust stage calls the typed
`SellerListingTrustAgent` contract in fixture mode, seeded by deterministic
trust rules, and persists `ListingTrustAssessment` rows through result
persistence. Fixture mode uses fixture category analysis and comparison output;
live typed analysis supplies evidence to the active owner's result. Fixture
mode remains the default; live agent and
provider modes require explicit configuration.

## Required Routing Rules

Rules 1–5 describe the current Python-selected analysis path. The live
owner path starts every ordinary request at General, which can finish
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
13. The owning model decides from available product, source and trust context. Normal output has no mandatory verifier; editorial workbench assistance is optional and nonblocking.

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
| `ShoppingScopeGuardrail` | SDK input guardrail with structured classifier output. | None. | Semantic request classification before research. | Starting retrieval after a blocked input; converting classifier errors into shopping judgments. |
| `ShoppingGuideAgent` | None. | `IntakeAgent` only after enough information exists. | Guided-intake state service and deterministic guardrail precheck. | Product recommendations, source retrieval, product links as normal intake, raw provider/tool controls. |
| `GeneralShoppingAgent` | Live SDK `web_search`, `search_sources`, `fetch_source`, `record_source_quote`, run-evidence lookup, evidence/candidate comparison, deterministic listing-trust check, and scoped source consultation. | One SDK handoff to Technology when its validated context matches the shopper's technology request; source specialists remain nested under the source manager. | Run-scoped provider search/fetch, persisted quote evidence, and backend-validated source/trust helpers. | Treating a hosted hit as a listing or making uncited price, availability, seller, or product claims. |
| `IntakeAgent` | None. | None. | None beyond supplied user/session input. | Search, extraction, source intelligence, recommendation generation, invented region/budget certainty. |
| `QueryPlannerAgent` | None. | None. | None directly. The workflow calls `SearchProvider` adapters after a validated `SearchPlan` is returned and may provide user-added product hints for scoped lookup queries. | Direct web search, browsing, provider SDK calls, category blocking because no specialist exists, asking users for product links. |
| `DiscoveryAgent` | `web_search` is a hosted SDK tool in live runs; `search_sources` and `fetch_source` remain bounded provider function tools. | None today. | Hosted URL citations are filtered and persisted as weak source leads with source/evidence IDs; supplied results and approved provider calls retain backend-owned policy and budgets. | Arbitrary URLs/provider arguments, vendor SDKs, unbounded browsing, fabricated source IDs, treating hosted snippets as verified listings or product facts. |
| `ExtractionAgent` | `read_source_snapshot`, limited to assigned same-run persisted IDs and bounded text. | None today. | Typed output with valid source/evidence IDs and zero/one/many products/listings; backend validates entity links, neutral listing URLs, optional source associations and available price context, editorial-page listing exclusion, item-level URLs on collection pages, review-evidence matches, and user-added candidate/listing links. | Direct scraping/vendor SDKs, invented facts/IDs, treating review articles as stores, or treating a user-added lookup hit as a confirmed identity. |
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
| `SellerListingTrustAgent` | None. | None. | Supplied listing, evidence, deterministic trust-rule assessment, price-plausibility signals, and optional seller/listing-scoped hosted `web_search`. | Inventing seller facts, fetching arbitrary seller pages or treating product quality as listing trust. Rule-derived flags remain advisory and can be revised by the model. |
| `SourceIntelligenceManagerAgent` | Model-running post-dedupe parent in live-agent shopping runs; fixture mode has no parent model call. | Choose relevant source specialists and explain skipped sources. | Four SDK specialist agent-tools over server-supplied candidates and region. | Direct provider SDK access, invented evidence, bypassing specialist/capability budgets. |
| `YouTubeReviewIntelligenceAgent` | SDK agent-as-tool under the live source manager; isolated workbench fixture mode uses `YouTubeReviewIntelligenceService`. | Select review videos, interpret timestamped product-specific pros/cons/concerns and visible bias. | Bounded `search_videos`, `read_video_metadata`, `read_video_transcript`, and optional YouTube-scoped hosted `web_search`. | Direct `yt-dlp`, WebVTT parsing, arbitrary API args, fabricated transcript claims, final recommendations. |
| `RedditCommunityIntelligenceAgent` | SDK agent-as-tool under the live source manager; isolated workbench fixture mode uses `RedditCommunityIntelligenceService`. | Select public discussions and interpret cited qualitative owner signals. | Bounded `search_community_discussions`, `read_community_discussion`, and optional Reddit-scoped hosted `web_search`. | Private/deleted/logged-in access, treating anecdotes as authoritative facts, final recommendations. |
| `AmazonProductIntelligenceAgent` | SDK agent-as-tool under the live source manager; isolated workbench fixture mode uses `AmazonProductIntelligenceService`. | Select relevant marketplace sources, interpret ASIN/variant identity, and organize cited product, offer, seller, review, and region evidence. | Bounded `search_amazon_products`, `read_amazon_product`, and optional marketplace-scoped hosted `web_search` over approved provider results and persisted source context. | Affiliate links, unapproved scraping, invented prices/review counts/shipping, collapsing seller risk into product quality. |
| `IKEAStoreIntelligenceAgent` | SDK agent-as-tool under the live source manager; isolated workbench fixture mode uses `IKEAStoreIntelligenceService`. | Select relevant official regional product sources and interpret cited item, local price/currency, availability, and store/delivery context with gaps. | Bounded `search_ikea_products`, `read_ikea_product`, and optional official-region-scoped hosted `web_search` over approved results and persisted snapshots. | Global shipping inference, non-official source substitution, unapproved scraping, invented regional purchase claims. |
| `ComparisonDecisionAgent` | None. | None. | Supplied brief, category analyses, trust assessments, dedupe decisions, and evidence. | New search/extraction, invented current facts or links, deterministic trust/budget/source eligibility and forced avoid items for ordinary non-winners. |
| `VerifierCriticAgent` | None. | None. | Supplied advice, products, listings, optional sources, trust assessments, category analyses and dedupe context. Optional wording suggestions preserve the owner choices. | Provider calls, per-claim source revalidation, buying vetoes or replacement of the owner choices. |

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
- Live `ExtractionAgent` output owns cited `CanonicalProduct`, `ProductListing`, product mentions, `SourceEvidence`, and explicit gaps; one snapshot may yield zero, one, or many entities. Deterministic parsing may provide signals, while schema, run/source identity and access protections remain operational boundaries. `ProductListingExtractor` remains a fixture/legacy helper, not the live semantic authority.
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
- Recommendation source associations are optional. Preserve available sources and qualify unknown facts without inventing prices, quotations, reviews or source links.
- Known, unknown, and inferred fields must remain distinguishable.
- Product-level and listing-level entities must not be collapsed.

## Provider And Compliance Constraints

- Providers must be configured through explicit adapters; agents should not directly call vendor SDKs or scrape pages outside approved tools.
- Provider adapters should expose capability and compliance flags so agents can distinguish disabled providers, metadata-only evidence, transcript access, community discussion retrieval, marketplace product/review retrieval, regional official-store lookup, and availability signals before using provider output.
- Provider keys, enabled-provider flags, timeouts, and capability flags belong in runtime configuration once implementation begins.
- Domain classifications and marketplace trust are advisory. Unknown or previously excluded domains may supply useful content through approved access paths. Actual seller concerns retain their scope and source.
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


## Bounded research context

Model-running roles use the shared bounded SDK gateway for request preparation
and cumulative reservations. Existing ownership, source permissions and spending
limits remain. Irreducible oversized requests fail technically. Page/source tools
retain run-scoped IDs, bounded offset/focus reads and retrievable originals.
Hashes and offsets describe versions; they do not admit advice or retries.

Owners and research roles retain approved `complete_research_result`,
`read_research_result`, `read_search_results` and `read_source_bundle` controls
where their runtime catalog permits them. Processing preserves useful notes,
source identity, cautions and gaps without requiring exact quote coverage.
The optional verifier has no research or original-read tools.

General, Technology and specialist owners share useful leads through existing
run state. Source quality and domain labels inform selection without discarding
usable content solely for a score or reputation. Source specialists retain their
site-specific provider/access contracts and return bounded source context.
Failed optional sources remain gaps while the owner uses available information.

Task 216 closes research directly to model synthesis when operational limits
require it. It removes quote-capture rounds and mandatory verification. Saved
owner checkpoints support tool-free final retries with existing research.
Basic phone research favors dated official announcements and product pages,
including relevant Apple, Samsung, Oppo and Xiaomi options. Reviews are optional.
Company claims, publication dates and release dates remain distinguishable.
Broad categories and generic fallback remain available.

## Task 221 intake and provenance compatibility

Agent identities, SDK permissions, catalog mapping and source fallback remain unchanged. Guided word matching no longer classifies headphones as phones. The live intake model may correct an earlier inferred category while explicit user category stays authoritative. Supported audio still uses General -> Technology -> EarphonesHeadphones ownership, and phone uses General -> Technology -> Smartphone. A validated parent recovery may author a result while both completed SDK transfers remain factual saved provenance. Research/history and prose repairs add no model stage or public result schema.

## Task 225 source coverage

Existing shopping owners and `ComparisonDecisionAgent` use `SourceDecisionProjection` to retain useful attributed candidate/question coverage before final input, saved completion and compaction. Broad discovery follows the buyer's needs and actual results without developer company seeds. Category-first discovery is optional for every product. Repeated coverage does not receive extra candidate breadth credit; useful independent perspectives and contrary findings can still support the same product.

`SourceIntelligenceManagerAgent` and `YouTubeReviewIntelligenceAgent` reuse shared run/capability video progress and the same bounded source allowance across candidate requests. Request-sensitive result caching remains separate. Comparative videos can support exact claims for several products using one source and saved transcript. Metadata and leads do not become accepted speech. Compatible historical checkpoints import read-only. No agent, routing edge, provider fallback, model stage or operational limit is added. Task 226 final-choice behavior is described below and is offline-complete.

## Task 226 final option selection

General, Technology and terminal shopping owners share one final option-set policy with retained comparison and owner completion. They select useful primaries, consider worthwhile runners, then optionally prefer a primary. Strong alternatives keep their distinct benefits when a winner is named. Three primaries and two runners remain maxima. Genuine constraints, exclusivity and material adverse findings can justify smaller sets.

Buyer-specific synthesis weighs attributed findings and credible disagreements against the full brief. Article rankings, popularity, source counts and transcript availability do not determine suitability. Open-ended owners can recommend useful researched alternatives absent from prior recommendations. Retained comparison continues to select supplied product IDs. Catalog boundary `BuyerComparativeOptionSet` records this responsibility. No agent, route, model stage, provider fallback or allowance changes.

## Buyer-validated transfers and retained recovery

General and Technology SDK transfer tools accept a nonblank reason. Each tool fixes its destination, which application code validates against the buyer's existing catalog route and the permitted hierarchy. The model does not supply another category label. Stored category context comes from the buyer brief and catalog. Wrong targets, non-technology transfers and repeated/deep transfers remain rejected. Broad technology stays with Technology; ordinary categories stay with General and retain the existing generic typed-analysis fallback.

After an eligible specialist failure, the existing Technology owner completes from retained source packets, products, listing cautions and the full buyer brief. It has no research tools, archive-reader tool or handoffs. Explicit closed-tool settings also suppress automatic archive-tool injection. The same attempt ledger, remaining timeout, normal Technology output cap and two-turn recovery bound apply. No saved-retry output allowance, new agent or research attempt is added. Failed recovery remains a technical failure with consumed usage preserved. Runtime catalog boundaries are `BuyerValidatedOwnerTransfer` and `RetainedOwnerRecovery`.

Recovery retains nonvideo consultation claims and their source-specific qualifications through selected attributed packets. It merges shared source URLs with existing packets and retains exact evidence and supporting-source identities. Video claims already persisted with accepted speech are not duplicated through raw consultation bundles.
