# CartCart Supported Agents And Source Capabilities

Status: Finalized design artifact for review before agent implementation
Last updated: 2026-06-21

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

## Architectural Decision

CartCart uses deterministic workflow orchestration with typed agent steps. The orchestrator owns workflow stages, persisted state, evidence, errors, retries, and tracing.

Specialized product/domain agents should normally be invoked as typed sub-runs or agents-as-tools when the orchestrator needs a scoped analysis result. OpenAI Agents SDK handoffs should be used only when a specialist should actually take over control of a conversational turn.

Reusable source intelligence agents should usually be agents-as-tools or deterministic services wrapped by an agent contract. They gather, normalize, summarize, and quality-score source-specific evidence, then hand structured evidence back to product analysis and decision agents. They should not make final purchase recommendations by themselves.

The product must support broad shopping queries even when no deep specialist exists. Generic fallback is mandatory.

## Accepted Scope Decisions

- `GenericProductAnalystAgent` is the buy-anything fallback for all normal shopping categories.
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
- MVP agent invocation should use typed steps, tools, or sub-runs. Handoffs are reserved for a later conversational use case where a specialist must take over a user turn.

## Status Meanings

| Status | Meaning |
| --- | --- |
| `required-mvp` | Must exist before MVP acceptance. |
| `candidate-mvp` | Intended for MVP, pending explicit implementation and provider feasibility decisions. |
| `proposed-later` | Useful future capability; not required for MVP. |
| `implemented` | Change to this status only once code, tests, and eval coverage exist. |

## Primary Product Analysis Hierarchy

```text
ShoppingRunOrchestrator                                      [required-mvp]
  ShoppingGuideAgent                                         [required-mvp]
  ShoppingScopeGuardrail                                     [required-mvp]
  IntakeAgent                                                [required-mvp]
  QueryPlannerAgent                                          [required-mvp]
  DiscoveryAgent                                             [required-mvp]
  ExtractionReviewAgent                                      [required-mvp]
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

Reusable source intelligence agents own source-specific discovery, extraction review, quality scoring, and evidence summarization. They must return structured evidence with source references and confidence. They do not make final purchase recommendations.

`SellerListingTrustAgent` owns listing and seller trust assessment independently of product quality. Suspicious deterministic trust flags cannot be silently overridden by agent output.

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
The current source-intelligence agent selects relevant supplied or
provider-discovered discussions, summarizes recurring qualitative owner signals
only when they are grounded in cited public summaries, preserves subreddit,
thread, comment, and source IDs, adds anecdotal/manipulation/low-context/stale
warnings, and returns `CommunityDiscussionEvidenceBundle` output rather than
recommendations or authoritative product facts.

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

The current source-intelligence agent selects relevant supplied products and
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
| `ShoppingGuideAgent` | `required-mvp` | Ask one user-facing intake question at a time, decide when inline choices help, support skip/reanswer behavior, and determine when enough information exists to start analysis. | Typed step before analysis | First shopping question, prior answers, local region setup state | Guided intake state or ready-for-analysis signal | Ask a plain-language follow-up, allow skip where safe, preserve uncertainty, or defer to guardrail when request is unsuitable. |
| `ShoppingScopeGuardrail` | `required-mvp` | Keep requests within shopping scope and safe consumer-product scope before discovery starts. | Early typed guardrail | Current user input and guided intake context | Allowed or blocked/redirection result | Return short regular-person-facing redirection copy and do not start discovery or analysis for blocked requests. |
| `IntakeAgent` | `required-mvp` | Interpret user goal, inferred category, region, budget, hard constraints, soft preferences, and clarification needs. | Typed step | Query and explicit controls | `ShoppingBrief` | Ask for correction or preserve uncertainty when critical intent is ambiguous. |
| `QueryPlannerAgent` | `required-mvp` | Plan region-aware searches and source strategy, including when video-review search is useful. | Typed step | `ShoppingBrief` | `SearchPlan` | Generic shopping query plan. |
| `DiscoveryAgent` | `required-mvp` | Select candidate products, listings, and evidence sources from search results for extraction. | Typed step | Brief, plan, search results | Candidate source selections | Keep only evidence-backed discovered items; report insufficient candidates. |
| `ExtractionReviewAgent` | `required-mvp` | Review structured extraction when deterministic extraction is incomplete or ambiguous. | Tool/sub-run only when needed | Source snapshot/extracted fields | Corrected `ProductListing` / `SourceEvidence` | Retain unknown fields; never invent missing facts. |
| `DeduplicationReviewAgent` | `required-mvp` | Review ambiguous duplicate candidates after deterministic matching. | Tool/sub-run only for uncertain pairs | Listings and match evidence | `DeduplicationDecision` | Preserve candidates as distinct when confidence is insufficient. |
| `CategoryRouterAgent` | `required-mvp` | Select implemented specialist or generic fallback. | Deterministic catalog plus typed routing decision where needed | Brief and candidates | Declared route | Always route unsupported/uncertain categories to generic fallback. |
| `GenericProductAnalystAgent` | `required-mvp` | Analyze product fit and tradeoffs for any shopping category. | Specialist tool/sub-run | Brief, product/evidence bundle | `CategoryAnalysis` | Mark limitations and evidence gaps instead of refusing unsupported categories. |
| `TechnologyDomainAnalystAgent` | `required-mvp` | Provide broad technology-product analysis, shared technology rules, and routing to implemented technology specialists. | Domain tool/sub-run | Technology brief/products/evidence | `CategoryAnalysis` or specialist route | Route non-technology products to generic analysis; fall back to generic if the domain layer fails. |
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
categories without specialists. The live discovery agent uses structured output
with no tools, selects only source IDs from supplied search results, rejects
weak/proxy-like selections, and returns an insufficient-candidates outcome when
no credible source remains. The live category router uses structured output with
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
- Handoffs are not the normal MVP routing mechanism. Use a handoff only in a future task where a specialist must own a conversational turn and the implementation still preserves persistence, traceability, fallback, and evaluation.
- Agent failures, timeouts, and low-confidence outputs must be persisted and routed through defined fallback behavior.

## Agent Tool Matrix

This table is the public tool/provider intent for each agent. Runtime code still
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
| `IntakeAgent` | None. | None. | None beyond supplied user/session input. | Search, extraction, source intelligence, recommendation generation, invented region/budget certainty. |
| `QueryPlannerAgent` | None. | None. | None directly. The workflow calls `SearchProvider` adapters after a validated `SearchPlan` is returned. | Direct web search, browsing, provider SDK calls, category blocking because no specialist exists. |
| `DiscoveryAgent` | None. | None. | None directly. It selects IDs only from supplied `SearchResult` records produced by workflow search providers. | Fabricating products/listings/source IDs, fetching pages, browsing, provider SDK calls. |
| `ExtractionReviewAgent` | Not implemented live yet. | May be a typed sub-run only for ambiguous or incomplete extraction. | Supplied `SourceSnapshot`, extracted fields, and deterministic extraction outputs. | Fetching new pages, scraping, inventing missing facts, bypassing extraction provider policy. |
| `DeduplicationReviewAgent` | Not implemented live yet. | May be a typed sub-run only for uncertain duplicate pairs. | Supplied product/listing/evidence records and deterministic dedupe signals. | Collapsing uncertain products without evidence, fetching new source data. |
| `CategoryRouterAgent` | None. | None. | Executable agent catalog for allowed route normalization and fallback. | Calling analysts directly, inventing specialists, unsupported-category refusal for normal products. |
| `GenericProductAnalystAgent` | None. | May receive orchestrated source-intelligence outputs; may later request approved source-intelligence sub-runs only if explicitly implemented. | Supplied product/listing/evidence bundles and trust context. | Raw search, scraping, vendor SDK calls, unsupported-category refusal for normal products. |
| `TechnologyDomainAnalystAgent` | None. | May route to declared MVP technology specialists through typed orchestration; current live workbench activity exposes the declared route while `CategoryAnalysis` remains the output contract. | Supplied product/listing/evidence bundles and executable catalog. | Routing non-technology products into technology specialists, inventing undeclared specialists, raw provider access, exposing internal agent names to shoppers. |
| `MonitorSpecialistAgent` | None. | Typed specialist sub-run under `TechnologyDomainAnalystAgent`. | Supplied monitor product/listing/evidence bundle. | Analyzing non-monitor products as monitor-scoped, raw provider access, unsupported factual claims. |
| `SmartphoneSpecialistAgent` | None. | Typed specialist sub-run under `TechnologyDomainAnalystAgent`. | Supplied smartphone product/listing/evidence bundle. | Analyzing non-phone products as phone-scoped, raw provider access, unsupported factual claims. |
| `LaptopSpecialistAgent` | None. | Typed specialist sub-run under `TechnologyDomainAnalystAgent`. | Supplied laptop product/listing/evidence bundle. | Analyzing non-laptop products as laptop-scoped, raw provider access, unsupported factual claims. |
| `EarphonesHeadphonesSpecialistAgent` | None. | Typed specialist sub-run under `TechnologyDomainAnalystAgent`. | Supplied earphone/headphone product/listing/evidence bundle. | Analyzing non-audio products as headphone-scoped, raw provider access, unsupported factual claims. |
| `TVSpecialistAgent` | None. | Typed specialist sub-run under `TechnologyDomainAnalystAgent`. | Supplied TV product/listing/evidence bundle. | Analyzing non-TV products as TV-scoped, raw provider access, unsupported factual claims. |
| `SmartwatchSpecialistAgent` | None. | Typed specialist sub-run under `TechnologyDomainAnalystAgent`. | Supplied smartwatch product/listing/evidence bundle. | Analyzing non-watch products as smartwatch-scoped, raw provider access, unsupported factual claims. |
| `SellerListingTrustAgent` | None. | None. | Supplied listing, evidence, deterministic trust-rule assessment, and price-plausibility signals. | Silently overriding hard suspicious flags, fetching seller pages directly, treating product quality as listing trust. |
| `YouTubeReviewIntelligenceAgent` | Provider-backed isolated workbench implementation. Typed provider/service access only. | Reusable source-intelligence agent/tool callable by orchestration or analysts when relevant. | `VideoSearchProvider`, `TranscriptProvider`, `YouTubeTranscriptIngestor`, `VideoReviewEvidenceCreator`, and supplied video/source metadata. | Direct `yt-dlp`, WebVTT parsing, Deno/EJS management, cookies, media downloads, arbitrary YouTube/API args, fabricated transcript claims, final purchase recommendations. |
| `RedditCommunityIntelligenceAgent` | Provider-backed isolated workbench implementation. Typed provider/service access only. | Reusable source-intelligence agent/tool callable by orchestration or analysts when relevant. | `CommunityDiscussionProvider`, approved public discussion summaries, `CommunityEvidenceCreator`, and source-quality warnings. | Direct Reddit API/page scraping unless approved, private/deleted/logged-in content, treating anecdotes as authoritative facts, final purchase recommendations. |
| `AmazonProductIntelligenceAgent` | Provider-backed isolated workbench implementation. Typed provider/service access only. | Reusable source-intelligence agent/tool callable by orchestration or analysts when relevant. | `AmazonProductIntelligenceProvider`, marketplace/listing identity context, regional ship-to evidence, review signals, and `AmazonProductEvidenceCreator` output. | Affiliate links, raw marketplace scraping outside approved providers, collapsing seller/listing risk into product quality. |
| `IKEAStoreIntelligenceAgent` | Provider-backed isolated workbench implementation. Typed provider/service access only. | Reusable source-intelligence agent/tool callable by orchestration or analysts when relevant. | IKEA regional official-store provider, official-source search adapter, regional availability/price evidence creator. | Global shipping inference, non-official IKEA source substitution, arbitrary scraping outside approved provider paths. |
| `ComparisonDecisionAgent` | None. | None. | Supplied brief, category analyses, trust assessments, dedupe decisions, and evidence. | New search/extraction, unsupported product claims, recommending suspicious listings without blocking warning, forced avoid items for ordinary non-winners. |
| `VerifierCriticAgent` | Isolated live workbench implementation with deterministic output guardrails. | None. | Supplied draft recommendation bundle, products, listings, source evidence, trust assessments, category analyses, and dedupe decisions. | New provider calls, hidden rewriting without blocking issues, approving uncited factual claims or shopper-visible internal process language. |

## Schema Boundaries

- `ShoppingBrief` is owned by intake and user corrections.
- `SearchPlan` and source strategy are owned by query planning.
- `ProductListing`, `SourceSnapshot`, and `SourceEvidence` are produced by deterministic extraction first, with extraction review only when needed.
- `DeduplicationDecision` records duplicate reasoning and must preserve uncertain cases.
- `ReusableSourceIntelligenceRequest` is the shared request boundary for source agents. It includes the shopping brief, target region, candidate product/listing/source IDs, optional source-specific query hints, requested source capabilities, and allowed-provider/capability descriptors.
- `VideoReviewEvidenceBundle` is the YouTube/source-video evidence boundary. It must include transcript availability status, source references, timestamped transcript evidence where available, explicit transcript gaps where unavailable, and sponsorship/affiliate-bias signals.
- `CommunityDiscussionEvidenceBundle` is the Reddit/community evidence boundary. It must include thread/comment source references, extracted public snippets or summaries where allowed, recurring claims, recency/engagement context when available, evidence-quality warnings, and explicit gaps.
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
