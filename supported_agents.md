# CartCart Supported Agents And Source Capabilities

Status: Finalized design artifact for review before agent implementation
Last updated: 2026-05-30

## Purpose

This file is the human-editable source of intent for CartCart's supported agents and agent-like source capabilities. It covers both:

- Hierarchical product/domain analysis agents, such as generic product analysis, technology analysis, or monitor analysis.
- Reusable cross-cutting agents-as-tools, such as YouTube review intelligence, seller/listing trust, retailer availability, or official brand-store lookup.

This is intentionally broader than an agent hierarchy file. Some agents belong in the product-analysis hierarchy; others are reusable source intelligence tools that can be called by agents at different hierarchy levels.

## Relationship To Runtime Code

- This file is design documentation and approved product/source-routing intent.
- The application must not parse this Markdown file at runtime.
- Once implementation reaches the agent catalog task, runtime configuration will live in a validated code registry such as `apps/backend/app/agents/catalog.py`.
- The code registry, agent tests, routing evals, and this file must be updated together whenever an implemented agent is added, removed, moved, or assigned a new fallback.
- A proposed future agent can appear here before it is implemented, but its status must clearly be `proposed-later` or `candidate-mvp` rather than `implemented`.

## Architectural Decision

CartCart uses deterministic workflow orchestration with typed agent steps. The orchestrator owns workflow stages, persisted state, evidence, errors, retries, and tracing.

Specialized product/domain agents should normally be invoked as typed sub-runs or agents-as-tools when the orchestrator needs a scoped analysis result. OpenAI Agents SDK handoffs should be used only when a specialist should actually take over control of a conversational turn.

Reusable source intelligence agents should usually be agents-as-tools or deterministic services wrapped by an agent contract. They gather, normalize, summarize, and quality-score source-specific evidence, then hand structured evidence back to product analysis and decision agents. They should not make final purchase recommendations by themselves.

The product must support broad shopping queries even when no deep specialist exists. Generic fallback is mandatory.

## Accepted Scope Decisions

- `GenericProductAnalystAgent` is the buy-anything fallback for all normal shopping categories.
- `TechnologyDomainAnalystAgent` is an MVP domain layer so technology routing is modular from the beginning.
- MVP technology specialists are `MonitorSpecialistAgent`, `SmartphoneSpecialistAgent`, `LaptopSpecialistAgent`, `EarphonesHeadphonesSpecialistAgent`, `TVSpecialistAgent`, and `SmartwatchSpecialistAgent`.
- `YouTubeReviewIntelligenceAgent` is approved as a reusable `candidate-mvp` source intelligence capability, not as a required MVP blocker and not as a category specialist.
- YouTube metadata may use the official YouTube Data API when configured. Transcript text may be used only through authorized official caption access, future user-provided transcript input, or a separately approved third-party provider. The system must never assume transcript availability.
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
  YouTubeReviewIntelligenceAgent                             [candidate-mvp]
  MarketplaceAvailabilityAgent                               [proposed-later]
    AmazonAvailabilityAgent                                  [proposed-later]
  OfficialBrandStoreAgent                                    [proposed-later]
  ProfessionalReviewSourceAgent                              [proposed-later]
  CommunityDiscussionSignalAgent                             [proposed-later]
```

## Ownership Boundaries

`ShoppingRunOrchestrator` owns workflow order, durable state, run events, retries, provider boundaries, trace IDs, and final result assembly. Agents return typed outputs; they do not own persistence or global control flow.

Product/category analysts own fit analysis for a product bundle in the context of a shopping brief. They should evaluate tradeoffs, missing evidence, product-level strengths and weaknesses, and category-specific concerns. They should not decide final ranking alone.

`TechnologyDomainAnalystAgent` owns shared technology-product reasoning, routing to MVP technology specialists, and technology-domain fallback when no narrower specialist applies. It should cover technology products broadly enough that adding future specific technology specialists is modular.

Reusable source intelligence agents own source-specific discovery, extraction review, quality scoring, and evidence summarization. They must return structured evidence with source references and confidence. They do not make final purchase recommendations.

`SellerListingTrustAgent` owns listing and seller trust assessment independently of product quality. Suspicious deterministic trust flags cannot be silently overridden by agent output.

`ComparisonDecisionAgent` owns comparative recommendation modes from the same analysis pass. `VerifierCriticAgent` owns final checks for unsupported claims, source gaps, suspicious-listing handling, budget handling, fallback behavior, and output restraint.

## Why YouTube Is A Source Intelligence Agent

YouTube product reviews are often valuable because reviewers discuss real-world usage, long-term issues, comparisons, ergonomics, subjective experience, and buyer regrets that product pages do not capture.

It should not be a category specialist because it is useful across categories. A monitor specialist, smartphone specialist, laptop specialist, headphone specialist, TV specialist, smartwatch specialist, office-chair analysis path, or generic product analyst may all request YouTube-derived evidence.

The YouTube agent should produce structured evidence, not final recommendations. It should find relevant product review videos, assess source/channel/video quality, retrieve or ingest available transcripts when permitted, summarize product-specific claims, preserve timestamps/source links, identify recurring pros/cons, flag sponsorship/affiliate bias where visible, and hand source-backed evidence to downstream analysts.

## Due Diligence Notes For YouTube

- The official YouTube Data API can search/list video metadata, but caption listing/downloading is authorization-scoped and not a general public transcript API.
- The official captions API response does not include actual caption text from `captions.list`; `captions.download` is the relevant endpoint but requires OAuth scopes and permission to access the caption track.
- Unofficial transcript APIs and scrapers may be practical but carry reliability, quota, terms, and compliance risk. They must be treated as optional providers with explicit configuration and documented constraints.
- The MVP should avoid assuming all YouTube videos have accessible transcripts.
- Fallback behavior should include metadata-only evidence, video description evidence, user-provided transcript input if later added, or skipping unavailable transcripts with a clear evidence gap.

## Agent Catalog

| Agent | Status | Responsibility | Invocation Pattern | Input | Output | Fallback / Failure Behavior |
| --- | --- | --- | --- | --- | --- | --- |
| `ShoppingRunOrchestrator` | `required-mvp` | Controls stages, persistence, events, retries, tracing, and result assembly. | Application code | Session/run context | Persisted workflow state | Persist failure and provide retry/recovery path. |
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
| `YouTubeReviewIntelligenceAgent` | `candidate-mvp` | Discover relevant product review videos, collect permitted transcript/metadata evidence, summarize product-specific claims, and return timestamped source evidence. | Reusable source agent/tool | Brief, candidate products, optional source/video queries | `VideoReviewEvidenceBundle` | If transcripts are unavailable, return metadata-only evidence or explicit evidence gaps; never fabricate video claims. |
| `MarketplaceAvailabilityAgent` | `proposed-later` | Check marketplace listing availability, shipping constraints, seller quality, and region relevance across mixed marketplaces. | Reusable source agent/tool | Product/listing candidates and region | Marketplace evidence | Fall back to listing trust/source quality rules. |
| `AmazonAvailabilityAgent` | `proposed-later` | Assess Amazon listing identity, seller, fulfillment, global shipping, regional availability, and suspicious marketplace signals. | Reusable marketplace source agent/tool | Product candidates and target region | Amazon listing evidence | Use only compliant APIs/providers or user-visible pages permitted by policy. |
| `OfficialBrandStoreAgent` | `proposed-later` | Locate official brand/store pages by country and assess official price, availability, warranty, and authorized sellers. | Reusable source agent/tool | Brand/product and region | Official-source evidence | Generic search/source extraction fallback. |
| `ProfessionalReviewSourceAgent` | `proposed-later` | Gather structured evidence from reputable written review sites and lab-test sources where available. | Reusable source agent/tool | Product/category and region | Review evidence | Generic source extraction fallback. |
| `CommunityDiscussionSignalAgent` | `proposed-later` | Summarize recurring owner complaints/praise from community discussions when allowed and source quality is adequate. | Reusable source agent/tool | Product/category and source set | Community signal evidence | Treat as lower-confidence qualitative signal, not definitive truth. |
| `ComparisonDecisionAgent` | `required-mvp` | Compare candidates and generate recommendation modes from one analysis pass. | Typed step | Brief and all assessed candidates | `RecommendationBundle` | Permit explicit "no strong buy". |
| `VerifierCriticAgent` | `required-mvp` | Verify claim evidence, budgets, red flags, fallback behavior, duplicates, and output restraint. | Final typed step | Draft bundle and evidence | Approved/revised/rejected bundle | Block unsupported or unsafe recommendation output. |

## Required Routing Rules

1. Every normal product query must be eligible for `GenericProductAnalystAgent`.
2. A product/category specialist may only receive queries within its declared scope.
3. Technology products should route through `TechnologyDomainAnalystAgent` before narrower technology specialists are selected.
4. If no product/category specialist matches, routing must fall back to domain analysis where applicable, then generic analysis rather than presenting an unsupported-category error.
5. If a specialist fails, times out, or has insufficient relevant evidence, technology-domain analysis and generic analysis must remain available.
6. Non-technology domain layers are optional and should only be implemented when they improve shared reasoning or routing.
7. Source intelligence agents can be used across hierarchy levels and product categories.
8. YouTube/video evidence must remain source-backed with video IDs, channel metadata where available, timestamps when available, transcript availability status, and confidence.
9. Seller/listing trust assessment applies independently of category analysis and must be surfaced where it materially affects purchase safety.
10. Recommendation output must be verified after product, source, and trust outputs are combined.

## Tool, Handoff, And Control Policy

- The orchestrator controls the MVP workflow.
- Agents should be invoked as typed steps, tools, or sub-runs with explicit input and output schemas.
- Product/category specialists should receive scoped product/evidence bundles and return `CategoryAnalysis`.
- Domain agents should own shared domain reasoning and should route only to specialists declared in the validated runtime catalog.
- Reusable source agents should receive scoped source requests and return evidence bundles, not recommendations.
- Handoffs are not the normal MVP routing mechanism. Use a handoff only in a future task where a specialist must own a conversational turn and the implementation still preserves persistence, traceability, fallback, and evaluation.
- Agent failures, timeouts, and low-confidence outputs must be persisted and routed through defined fallback behavior.

## Schema Boundaries

- `ShoppingBrief` is owned by intake and user corrections.
- `SearchPlan` and source strategy are owned by query planning.
- `ProductListing`, `SourceSnapshot`, and `SourceEvidence` are produced by deterministic extraction first, with extraction review only when needed.
- `DeduplicationDecision` records duplicate reasoning and must preserve uncertain cases.
- `VideoReviewEvidenceBundle` is the YouTube/source-video evidence boundary. It must include transcript availability status, source references, timestamped transcript evidence where available, explicit transcript gaps where unavailable, and sponsorship/affiliate-bias signals.
- `ListingTrustAssessment` is the seller/listing trust boundary and must remain separate from product desirability.
- `CategoryAnalysis` is the product/category analysis boundary.
- `RecommendationBundle` is the comparison and decision boundary.
- Important output schemas should be versioned when implemented.
- Factual claims about products, prices, sellers, and reviews must reference source IDs.
- Known, unknown, and inferred fields must remain distinguishable.
- Product-level and listing-level entities must not be collapsed.

## Provider And Compliance Constraints

- Providers must be configured through explicit adapters; agents should not directly call vendor SDKs or scrape pages outside approved tools.
- Provider keys, enabled-provider flags, timeouts, and capability flags belong in runtime configuration once implementation begins.
- Reseller-only platforms are excluded initially. Mixed marketplaces are allowed only when seller/listing trust can be assessed.
- YouTube metadata may come from the official YouTube Data API when configured.
- YouTube transcript text may be used only through authorized official caption access, future user-provided transcript input, or an explicitly approved third-party transcript provider.
- Unofficial transcript providers require a separate accepted decision covering terms, reliability, quotas, and fallback behavior.
- Video evidence must preserve video IDs, source URLs, channel metadata where available, timestamps when available, transcript availability status, and evidence confidence.
- No source agent may fabricate unavailable transcript claims, review claims, seller details, prices, or warranty facts.

## Adding Or Moving An Agent

When introducing or changing an agent:

1. Edit this file, marking a new agent as `proposed-later` or `candidate-mvp` until approved.
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
- Add an Amazon global-shipping capability: keep it in the reusable source intelligence layer unless it becomes part of a broader marketplace availability layer.
- Add a brand-store capability: make it region-aware because official stores, warranties, and availability vary by country.
- Move a specialist: update this file, the decision record, runtime registry, routing tests, and eval cases together.
- Change fallback: treat this as a behavior change requiring documented rationale and regression evaluation across affected categories.
