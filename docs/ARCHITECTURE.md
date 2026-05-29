# CartCart Architecture

Status: Initial public architecture notes for planning
Last updated: 2026-05-29

## Product Model

CartCart is a shopping discovery, comparison, and decision application. It should help a user answer what to buy, whether a candidate is a bad fit, and whether a listing or seller looks unsafe.

The product should use a research workspace model rather than a chat-only model. The first application surface should support:

- Natural-language shopping goal input.
- Region, budget, and lightweight preference controls.
- Optional user-added products.
- Run progress and stage history.
- Results with a final recommendation, runner-ups, alternate recommendation modes, comparison details, trust notes, warnings, rejected items when meaningful, and inspectable source evidence.

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

## Intended Repository Shape

The application has not been scaffolded yet. The intended shape is:

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
AGENTS.md
supported_agents.md
```

## Workflow Architecture

CartCart should use deterministic workflow orchestration around typed agent steps. A backend `ShoppingRunOrchestrator` should own workflow state, persistence, retries, trace IDs, provider boundaries, and emitted progress events.

Agents should produce typed outputs at each stage. Search, fetch, extraction, persistence, and scoring support should live behind tools or services with clear contracts. OpenAI Agents SDK handoffs should be used sparingly for specialist ownership, not as the primary control plane.

Recommended stages:

1. User creates a shopping session from a query, region, budget, and optional preferences.
2. Intake produces a typed `ShoppingBrief`.
3. Query planning creates region-aware search and source plans.
4. Search provider adapters collect web, product, or source-intelligence results.
5. Fetch and extraction store source snapshots and structured evidence.
6. Candidate generation normalizes product and listing data.
7. Deduplication groups obvious duplicates and preserves uncertain cases.
8. Category analysis evaluates product fit, specs, tradeoffs, and evidence gaps.
9. Seller/listing trust analysis evaluates buyer-safety signals.
10. Decision produces recommendation modes and a final best pick or an explicit no-strong-buy result.
11. Verification checks source support, trust handling, budget handling, duplicate handling, and output restraint.
12. The frontend renders the result bundle and supports targeted refinement from cached artifacts.

## Agent And Source Capability Model

`supported_agents.md` is the public, human-editable source of intent for supported agents, reusable source capabilities, routing, and fallback behavior. Runtime code must not parse that Markdown file. When implementation reaches the agent catalog task, the approved hierarchy should be represented in a validated code registry such as `apps/backend/app/agents/catalog.py`.

Required MVP agent roles include:

- `ShoppingRunOrchestrator`
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

`GenericProductAnalystAgent` is the buy-anything fallback for normal shopping categories. `TechnologyDomainAnalystAgent` is an MVP domain layer so technology routing is modular from the beginning. MVP technology specialists cover monitors, smartphones, laptops, earphones/headphones, TVs, and smartwatches. Candidate or later reusable source capabilities include YouTube review intelligence, marketplace availability, official brand-store lookup, professional review sources, and community discussion signals. Generic product analysis must remain available when no narrower specialist exists or when a specialist/domain fallback is needed.

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

- Factual claims about products, prices, sellers, reviews, warranties, availability, or video evidence must reference source IDs.
- Evidence quality and analysis confidence are separate fields. A product can be desirable with weak evidence, or well-evidenced but still a poor fit.
- Unknown, inferred, and source-confirmed values must remain distinguishable.
- Conflicting evidence should be preserved as conflicting records and surfaced when material to the decision.
- Weak evidence should reduce confidence and may lead to no-strong-buy, but it should not force the system to invent certainty.
- Video-derived claims must include transcript availability status and timestamps when available. Missing transcripts must be represented as an evidence gap.
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
- User-added products may be provided as URLs or manual details.
- URL-based user-added products should fetch and extract through the normal source/listing pipeline when that capability exists.
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

Do not build cross-session user preference profiling for MVP. OpenAI Agents SDK session memory may be used for conversational context only if it improves refinement; it must not be the only application state store.

Vector search is deferred. Use SQLite indexes and possibly FTS5 first. Consider LanceDB later only if semantic retrieval over saved source snapshots becomes materially useful.

## Source And Retrieval Architecture

Search and extraction should be adapter-based. Initial provider interfaces should cover:

- General web search.
- Source extraction.
- Optional shopping-specific product search.
- Later reusable source-intelligence providers such as video search, transcripts, marketplace availability, and official store lookup.

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
