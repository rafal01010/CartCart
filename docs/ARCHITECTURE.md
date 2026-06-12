# CartCart Architecture

Status: Initial public architecture notes with guided intake direction
Last updated: 2026-06-12

## Product Model

CartCart is a shopping discovery, comparison, and decision application. It should help a user answer what to buy, whether a candidate is a bad fit, and whether a listing or seller looks unsafe.

The product should use a guided shopping decision model. The first application
surface is a focused "Send your question" prompt with a large textbox, not a
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

The initial monorepo skeleton exists. Backend Python project metadata, initial runtime/test dependencies, typed settings, a FastAPI app factory, health/readiness endpoints, structured request logging, configurable FastAPI OpenTelemetry instrumentation, the async SQLite/Alembic persistence baseline, persisted shopping sessions/briefs, run lifecycle/event records, search plans/results, source snapshots/evidence, video review evidence, reusable source-intelligence evidence schemas/persistence, product/listing records, result bundle records, a fixture-only shopping run orchestrator, required reusable source-agent contracts/catalog entries, and a SvelteKit TypeScript frontend scaffold with Tailwind CSS, shadcn-svelte configuration, Bits UI dependencies, base UI tokens, and hand-written API client utilities have been added.

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

Intended application shape after backend, frontend, and local scripts are scaffolded:

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
      telemetry/
      tests/
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
deterministic analysis run.

Region setup is outside the main shopping question flow. If no region preference
or explicit refusal is saved locally, the frontend can show a lightweight setup
prompt explaining that location helps show products the user can actually buy.
The user can provide a region or refuse to answer. If region setup interrupts an
already-submitted shopping question, the frontend should automatically resume
the pending guided flow after either choice. Backend defaults remain allowed for
fixture/local operation, but must be marked as defaulted or inferred rather than
user-confirmed.

Guardrail behavior should run before costly discovery or analysis. Off-topic,
unsafe, illegal, or inappropriate product requests should receive short
regular-person-facing redirection copy and should not start source retrieval or
analysis.

## Workflow Architecture

CartCart should use deterministic workflow orchestration around typed agent steps. The backend `ShoppingRunOrchestrator` owns workflow state, persistence hooks, trace IDs, emitted progress events, and a fixture monitor-shopping result bundle. The current implementation is fixture-only; `POST /api/sessions/{session_id}/runs` executes it synchronously and records deterministic stages plus persisted search/source, product/listing, user-added item, trust, analysis, and recommendation output without live providers or model calls.

Agents should produce typed outputs at each stage. Search, fetch, extraction, persistence, and scoring support should live behind tools or services with clear contracts. OpenAI Agents SDK handoffs should be used sparingly for specialist ownership, not as the primary control plane.

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
7. Search provider adapters collect web, product, or source-intelligence results.
8. Fetch and extraction store source snapshots and structured evidence.
9. Candidate generation normalizes product and listing data.
10. Deduplication groups obvious duplicates and preserves uncertain cases.
11. Category analysis evaluates product fit, specs, tradeoffs, and evidence gaps.
12. Seller/listing trust analysis evaluates buyer-safety signals.
13. Decision produces recommendation modes and a final best pick or an explicit no-strong-buy result.
14. Verification checks source support, trust handling, budget handling, duplicate handling, and output restraint.
15. The frontend renders staged results and supports targeted refinement from cached artifacts.

## Agent And Source Capability Model

`supported_agents.md` is the public, human-editable source of intent for supported agents, reusable source capabilities, routing, and fallback behavior. Runtime code must not parse that Markdown file. Agent wrapper contracts, deterministic fake implementations, and the validated executable catalog live under `apps/backend/app/agents`; these define typed input/output boundaries, current routing categories, fallback paths, reusable source capabilities, provider requirements, and invocation modes without live model calls. In fixture mode, `ShoppingGuideAgent` and `ShoppingScopeGuardrail` use the guided intake schemas to return user-facing question state, skip/reanswer metadata, ready-for-analysis briefs, or short blocked-request redirections before discovery starts.

Required MVP agent roles include:

- `ShoppingRunOrchestrator`
- `ShoppingGuideAgent`
- `ShoppingScopeGuardrail`
- `IntakeAgent`
- `QueryPlannerAgent`
- `DiscoveryAgent`
- `ExtractionReviewAgent`
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

`GenericProductAnalystAgent` is the buy-anything fallback for normal shopping categories. `TechnologyDomainAnalystAgent` is an MVP domain layer so technology routing is modular from the beginning. MVP technology specialists cover monitors, smartphones, laptops, earphones/headphones, TVs, and smartwatches. Reusable source intelligence capabilities include required MVP YouTube, Reddit, Amazon, and IKEA source agents plus later marketplace product intelligence, official brand-store lookup, professional review sources, and broader community discussion signals. Generic product analysis must remain available when no narrower specialist exists or when a specialist/domain fallback is needed.

Required MVP reusable source intelligence roles include:

- `YouTubeReviewIntelligenceAgent`
- `RedditCommunityIntelligenceAgent`
- `AmazonProductIntelligenceAgent`
- `IKEAStoreIntelligenceAgent`

Reusable source intelligence agents are not category specialists and are not final decision agents. They retrieve, normalize, quality-score, and summarize source-specific evidence that can be reused by discovery, product/domain analysts, trust analysis, and the final decision flow. Their scope is usable evidence retrieval, not availability-only checks. Depending on the source, they may return product-page information, review summaries, recurring owner complaints, seller/fulfillment signals, price/currency, regional availability, shipping/store context, warranty/return context, and explicit evidence gaps.

## MVP Behavior Rules

These rules define the minimum behavior expected from schemas, tests, agents, source policy, and result rendering.

### Budget Handling

- Budget input must distinguish a hard cap from a preferred budget.
- If the user explicitly says a budget is strict, final picks must not exceed it unless the result is an explicit no-strong-buy outcome explaining why no acceptable option was found.
- If the budget is a preference, the app may recommend a stretch option only when the tradeoff is explicit and a within-budget option or no-strong-buy alternative is also represented.
- Recommendation modes should be computed from the same stored analysis pass, including best overall, best value, best within budget, and stretch pick when applicable.
- Products should not be discarded solely for exceeding a soft budget. They may be ranked lower, moved to a stretch mode, or rejected for overpaying when the price/value case is weak.
- Tests should cover hard cap, soft/preferred budget, missing budget, currency/region mismatch, and justified stretch behavior.

### Source And Marketplace Policy

- Reseller-only platforms are excluded from MVP discovery and recommendation candidates.
- A source known to be reseller-only should be marked excluded with a reason, not quietly used as evidence for a recommendation.
- Mixed marketplaces may be included only when seller/listing legitimacy can be assessed with available signals.
- Mixed-marketplace listings must preserve listing identity separately from product identity because the same product can be safe from one seller and risky from another.
- A mixed-marketplace listing with unknown seller identity, unclear fulfillment, unclear return/warranty policy, suspicious price, or sparse/contradictory metadata must not be treated as equivalent to an established retailer or official source.
- The system must not recommend a matching listing merely because it matches the query.
- Tests should cover excluded reseller-only sources, allowed established retailers, mixed marketplaces with strong seller signals, and mixed marketplaces with weak or suspicious seller signals.

### Seller And Listing Trust

- Product quality and listing trust are separate dimensions.
- `ListingTrustAssessment` should support at least `strong`, `reasonable`, `mixed`, `weak`, `suspicious`, and `unknown`.
- Suspicious deterministic signals cannot be silently overridden by an agent.
- A suspicious listing must not be the final purchase link unless the result clearly blocks or warns against buying from that listing.
- A good product from a bad listing should be shown as a product/listing mismatch, not as a safe buy.
- Trust notes should cite the source or listing signals that support them when available.

### Evidence And Confidence

- Factual claims about products, prices, sellers, reviews, warranties, availability, community discussion, official-store evidence, marketplace evidence, or video evidence must reference source IDs.
- Evidence quality and analysis confidence are separate fields. A product can be desirable with weak evidence, or well-evidenced but still a poor fit.
- Unknown, inferred, and source-confirmed values must remain distinguishable.
- Conflicting evidence should be preserved as conflicting records and surfaced when material to the decision.
- Weak evidence should reduce confidence and may lead to no-strong-buy, but it should not force the system to invent certainty.
- Reusable source-intelligence schemas use explicit evidence targets so product, listing, seller, review, source-only metadata, and region-specific facts do not collapse into recommendation fields.
- Video-derived claims must include transcript availability status and timestamps when available. Missing transcripts must be represented as an evidence gap.
- Reddit/community-derived claims must identify the source thread/comment context where available and remain qualitative unless corroborated by stronger sources.
- Amazon-derived claims must preserve marketplace/listing/seller/fulfillment and regional availability context instead of collapsing Amazon evidence into generic product truth.
- IKEA-derived claims must preserve country/region context and must not imply global shipping or availability.
- Tests should reject unsupported factual claims and verify confidence/evidence-quality separation.

### Broad Category Fallback

- Every normal shopping query must be eligible for `GenericProductAnalystAgent`.
- Technology products should route through `TechnologyDomainAnalystAgent` and then to an MVP technology specialist when the category matches monitors, smartphones, laptops, earphones/headphones, TVs, or smartwatches.
- If no specialist matches, the technology domain may analyze the product broadly when it is technology-related.
- If the technology domain does not apply, fails, times out, or produces insufficient confidence, generic analysis remains available.
- The app should not show an unsupported-category error for ordinary consumer products solely because no specialist exists.
- Tests should cover non-technology generic fallback, technology-domain routing, each MVP technology specialist route, and fallback from specialist to domain to generic.

### User-Added Products

- User-added products must enter the same deduplication, extraction, trust, analysis, and decision pipeline as app-generated candidates.
- Normal guided intake should ask for product names or descriptions, not product URLs.
- URL-based user-added products can exist later as an advanced or corrective path and should fetch and extract through the normal source/listing pipeline when that capability exists.
- Manual user-added products must preserve missing evidence rather than inventing specs, price, seller, or review claims.
- A user-added product can win, place as a runner-up, be rejected for a meaningful reason, or be excluded because the listing is unsafe.
- User-added products should be marked as user-supplied in stored state and result output so the UI can distinguish them from discovered candidates.

### No-Strong-Buy Outcome

- The recommendation bundle must support either one final best pick or an explicit no-strong-buy result.
- No-strong-buy is appropriate when all candidates are materially unsafe, poor fits, over budget under a hard cap, unsupported by adequate evidence, unavailable in the selected region, or too conflicted to recommend responsibly.
- No-strong-buy should include actionable next steps, such as changing budget, broadening constraints, waiting for better evidence, checking safer retailers, or adding more candidates.
- No-strong-buy is not an error state. It is a valid decision outcome.
- Tests should enforce that final output cannot contain both an unqualified best pick and a no-strong-buy outcome.

### Red Flags And Warnings

- Red flags should be reserved for material concerns that can affect purchase safety or recommendation quality.
- Red flags include suspicious seller/listing signals, extreme price outliers, unclear warranty/returns, region mismatch, likely counterfeit or misleading listing, critical missing product feature, material evidence conflict, or weak evidence for a high-impact claim.
- Warnings should be visible in the result bundle and linked to affected products/listings and source evidence where possible.
- Do not add generic warnings solely to fill a UI section.
- A blocking concern should prevent a listing from being the safe final purchase option even if the product itself ranks highly.

### Conditional Why-Not Output

- Rejected-item or "why not" output should appear only when there is a meaningful negative reason.
- Meaningful reasons include suspicious listing, poor fit for stated constraints, hard-budget violation, overpaying, missing critical feature, materially weak evidence, duplicate/near-duplicate inferior listing, region unavailability, or better equivalent alternative.
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

The implemented backend provider boundary lives under `apps/backend/app/providers`.
`SearchProvider`, `ExtractionProvider`, and optional `ShoppingProvider` are async
protocols that return existing typed source and product schemas. Provider options
carry a `SourceAllowAvoidPolicy` so orchestration can pass explicit allow and
avoid rules without hard-coding a single marketplace, source category, or search
vendor. Deterministic fake providers live beside the contracts and are intended
for fixture-mode tests until real adapters are configured.

Reusable source-intelligence providers are also defined in the provider layer.
The agent contract and executable catalog layer exposes required reusable source
tools for YouTube, Reddit, Amazon, and IKEA. Those source agents return evidence
bundles for usable source intelligence rather than recommendations or
availability-only checks. The provider boundary exposes enabled state, supported
capabilities, official/user-authorized access, domain-scoped search support,
public-page extraction support, Amazon product/listing/review support, regional
ship-to evidence support, IKEA regional official-store support, and compliance
notes. Fake implementations can return metadata-only video evidence, available
transcript segments, explicit unavailable-transcript gaps, Reddit/community
evidence gaps or recurring discussion signals, Amazon product/listing/review
evidence, IKEA regional store evidence, and disabled-provider results without
making live calls.

Provider runtime configuration is typed in backend settings. Search, extraction,
and optional shopping providers have explicit provider names, enabled flags,
shared timeout/rate-limit defaults, a default region, and local secret fields.
Missing keys for enabled live providers surface as readiness warnings rather
than blocking fixture or stub operation.

The MVP should start with one general web search provider when implementation reaches provider work. Tavily is preferred if a key is available because search and extraction both matter for agent workflows. Brave is a credible alternative. SerpApi should remain optional because it introduces cost, dependency, and terms considerations.

Source policy:

- Prefer official manufacturer pages, established retailers, reputable review sources, and region-relevant retailers.
- Exclude reseller-only platforms initially.
- Allow mixed marketplaces only when seller/listing legitimacy can be meaningfully assessed.
- Preserve source evidence and conflicts rather than flattening incompatible claims.
- Do not recommend a listing merely because it matches the query; source quality and buyer safety are part of candidacy.

## Recommendation Principles

CartCart should distinguish product quality from listing trust. A good product sold through a suspicious listing should not become a safe recommendation.

Recommendations should support:

- One best pick or an explicit no-strong-buy outcome.
- Runner-ups.
- Best value, within-budget, and stretch modes when supported by the same analysis pass.
- Budget semantics that distinguish hard caps from preferences.
- Material warnings and red flags.
- Rejected or "why not" output only when there is a meaningful negative reason.
- Source-backed factual claims with confidence and evidence quality represented separately.
