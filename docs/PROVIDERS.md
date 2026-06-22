# CartCart Provider Setup And Fixture Replay

Status: Provider setup and safety reference
Last updated: 2026-06-21

## Scope And Defaults

This document is the setup and safety reference for backend provider work. The
provider contracts and adapters live under `apps/backend/app/providers/`, typed
configuration lives in `apps/backend/app/core/settings.py`, and safe example
values live in `apps/backend/.env.example`.

Fixture behavior is the default. A normal local run, routine test, or Section J
gate must not require network access, provider credentials, quota, or live model
calls. `CARTCART_ENVIRONMENT=live` does not enable a provider by itself. Live
use requires the provider name, its enabled flag, and every required credential
or dependency to be configured explicitly.

## Provider Boundaries

| Boundary | Contract | Current implementation and limits |
| --- | --- | --- |
| General search | `SearchProvider` | Deterministic fake provider and live Tavily HTTP adapter. `brave` is reserved in settings but has no runtime adapter yet. Search returns normalized `SearchResult` records; it does not fetch or extract pages. |
| Extraction | `ExtractionProvider` | Fixture and disabled modes plus the concrete `HttpStaticExtractionProvider`. The shopping run orchestrator sends eligible discovered pages through this boundary, persists each snapshot linked to its search result, and creates shortlist candidates only from usable extraction outcomes. The configured adapter combines `HttpSourceFetcher` snapshot persistence with Trafilatura-backed `StaticPageTextExtractor` and returns one enriched `SourceSnapshot`. `DynamicExtractionPolicy` remains static-first and only marks browser extraction as an optional future fallback. No browser runtime is installed or invoked. |
| Shopping search | `ShoppingProvider` | Typed optional contract and fake provider for direct test substitution only. There is no generic shopping runtime setting. The SerpApi Amazon adapter is source-specific product intelligence, not the generic shopping provider. |
| Video metadata | `VideoSearchProvider` | Fake provider plus the official YouTube Data API metadata adapter. It uses `search.list` and `videos.list`; transcript availability remains unchecked. |
| Video transcripts | `TranscriptProvider` | Deterministic fake plus `YtDlpTranscriptProvider` for explicitly enabled public-caption retrieval. The live adapter requests manual subtitles before automatic captions, parses bounded WebVTT into timestamped language-aware segments, and returns explicit gaps instead of fixture text when access fails. |
| Community discussions | `CommunityDiscussionProvider` | Reddit discovery composes the configured general search provider with `reddit.com` scope. It does not call Reddit pages or APIs directly. |
| Amazon intelligence | `AmazonProductIntelligenceProvider` | Fake provider plus optional SerpApi Amazon Search/Product adapters for listing, seller, delivery, product, and review-summary evidence. |
| IKEA intelligence | `IKEAStoreIntelligenceProvider` | Fake provider plus official regional-domain discovery composed over general search. It does not fetch IKEA pages directly. |
| Generic marketplace/store lookup | `MarketplaceAvailabilityProvider`, `OfficialStoreProvider` | Typed contracts and fakes only. Dedicated Amazon and IKEA adapters remain separate source-intelligence boundaries. |

Provider options carry source policy, region, and result-limit context. Shared
timeout and rate-limit defaults live in runtime settings. Adapters return typed
records or explicit evidence gaps. Agents and workflow code must not call vendor
SDKs, scrape sites, or invent a second provider path around these boundaries.

Shopping runs invoke reusable source-intelligence providers after normal
discovery and extraction have produced candidate products/listings. The workflow
passes a scoped brief, region, selected product/listing/source IDs, provider
capability descriptors, and query hints. It persists source-specific evidence
bundles separately from normal web/listing evidence. YouTube transcript access is
always routed through the configured `TranscriptProvider`: fixture mode may use
`FakeTranscriptProvider`, while configured live transcript mode uses
`YtDlpTranscriptProvider` and returns explicit gaps instead of fixture text when
caption retrieval fails.

## Fixture, Live, And Disabled Behavior

| State | Expected behavior |
| --- | --- |
| Default fixture | Enabled flags are `false` and fixture/fake providers are returned. No key or network is required. |
| Explicit fixture | Selecting `fixture` returns deterministic fake or replay behavior even if an enabled flag is set. |
| Explicit disabled | Extraction returns an excluded snapshot without fetching. Source-intelligence providers that support `disabled` return typed disabled results with no evidence bundle. General search uses `CARTCART_SEARCH_PROVIDER_ENABLED=false` instead of a `disabled` name. |
| Live and ready | The live provider name, enabled flag, credential, and provider dependencies are present. An implemented runtime builder returns the live adapter. |
| Live key missing | Credentialed provider readiness reports the missing variable and existing credentialed builders preserve fixture/stub operation. The live transcript builder never substitutes a fake: it returns `YtDlpTranscriptProvider`, and missing or incompatible local runtime dependencies produce readiness warnings plus explicit transcript gaps. |
| Reserved adapter selected | A configured provider with no runtime adapter, such as live Brave search, raises a clear provider configuration error. Do not document a reserved value as usable live support. |

`GET /readyz` remains HTTP 200 when optional live credentials are missing. Its
provider and agent warning entries are operational guidance, not proof that a
live provider or model call was attempted.

## Environment Variables

Copy `apps/backend/.env.example` to the ignored `apps/backend/.env` only when a
local override or live provider is needed. Never commit `apps/backend/.env` or a
real credential.

Common provider settings:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CARTCART_DEFAULT_REGION_CODE` | `US` | Default provider region when a request does not supply one. |
| `CARTCART_PROVIDER_TIMEOUT_SECONDS` | `10` | Shared provider request timeout. |
| `CARTCART_PROVIDER_RATE_LIMIT_PER_MINUTE` | `60` | Shared local provider budget for adapters that enforce it. |

Provider selection and credentials:

| Capability | Selection variables | Live credential or dependency |
| --- | --- | --- |
| General search | `CARTCART_SEARCH_PROVIDER=fixture|tavily|brave` and `CARTCART_SEARCH_PROVIDER_ENABLED` | Tavily: `CARTCART_TAVILY_API_KEY`. Brave has no runtime adapter yet. |
| Extraction | `CARTCART_EXTRACTION_PROVIDER=disabled|fixture|http_static` and `CARTCART_EXTRACTION_PROVIDER_ENABLED` | No credential. Uses the configured source-fetch timeout, content limit, user agent, and raw snapshot directory. |
| YouTube metadata | `CARTCART_VIDEO_SEARCH_PROVIDER=disabled|fixture|youtube` and `CARTCART_VIDEO_SEARCH_PROVIDER_ENABLED` | `CARTCART_YOUTUBE_DATA_API_KEY`. |
| YouTube transcripts | `CARTCART_TRANSCRIPT_PROVIDER=disabled|fixture|yt_dlp` and `CARTCART_TRANSCRIPT_PROVIDER_ENABLED` | Pinned `yt-dlp[default]==2026.6.9`, `yt-dlp-ejs==0.8.0`, and Deno `>=2.3.0` (`2.8.1` in backend dependency metadata). No API key or cookies. |
| Amazon intelligence | `CARTCART_AMAZON_PRODUCT_INTELLIGENCE_PROVIDER=disabled|fixture|serpapi` and `CARTCART_AMAZON_PRODUCT_INTELLIGENCE_PROVIDER_ENABLED` | `CARTCART_SERPAPI_API_KEY`. |
| IKEA intelligence | `CARTCART_IKEA_STORE_INTELLIGENCE_PROVIDER=disabled|fixture|search` and `CARTCART_IKEA_STORE_INTELLIGENCE_PROVIDER_ENABLED` | A ready general search provider. Current live setup uses Tavily and `CARTCART_TAVILY_API_KEY`. |
| Reddit discovery | No separate variables | Uses the configured general search provider and its fixture/live behavior. |

## OpenAI Agent Runtime Configuration

OpenAI Agents SDK configuration is separate from source providers, but it
follows the same fixture-first rule. Fixture and mocked agent modes require no
OpenAI credential and must remain the default for local runs, routine tests, and
section gates. Live model calls require all of the following:

- `CARTCART_AGENT_WORKFLOW_MODE=live` for normal shopping runs, or an explicit
  local workbench `--mode live`
- `CARTCART_LIVE_AGENTS_ENABLED=true`
- `OPENAI_API_KEY` set locally by the project owner
- The implemented agent path explicitly requesting live mode

The backend also accepts `CARTCART_OPENAI_API_KEY` as a CartCart-prefixed local
compatibility alias, but `OPENAI_API_KEY` is preferred and takes precedence.
Neither variable is committed, logged, returned by readiness, or stored in test
fixtures.

Agent runtime settings:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CARTCART_AGENT_WORKFLOW_MODE` | `fixture` | Selects fixture or live-agent mode for normal shopping runs. |
| `CARTCART_LIVE_AGENTS_ENABLED` | `false` | Opt-in gate for live OpenAI agent calls. |
| `OPENAI_API_KEY` | unset | Standard OpenAI API key used only for explicitly requested live-agent mode. |
| `CARTCART_OPENAI_MODEL` | `gpt-5.4-mini` | Default model string passed to implemented OpenAI Agents SDK runs unless an agent task narrows it. |
| `CARTCART_OPENAI_AGENT_TIMEOUT_SECONDS` | `45` | Per-agent run timeout budget for live-agent runners. |
| `CARTCART_OPENAI_AGENT_MAX_TURNS` | `8` | Upper bound for later SDK runner turns. |
| `CARTCART_OPENAI_AGENT_TRACING_ENABLED` | `false` | Enables OpenAI Agents SDK tracing only when a live-agent runner uses it. |
| `CARTCART_OPENAI_AGENT_TRACE_INCLUDE_SENSITIVE_DATA` | `false` | Keeps inputs and outputs out of OpenAI trace payloads by default. |
| `CARTCART_OPENAI_AGENT_TRACE_WORKFLOW_NAME` | `cartcart-agent-run` | Trace workflow name used by live-agent runners. |

The current live-agent implementations cover shopping guardrails,
guided intake, intake parsing, query planning, discovery source selection,
category routing, generic product analysis, technology-domain analysis,
monitor-specialist analysis, smartphone-specialist analysis,
laptop-specialist analysis, earphones/headphones-specialist analysis,
TV-specialist analysis, smartwatch-specialist analysis, seller/listing trust,
comparison decision, verifier/critic output checks, provider-backed YouTube
review intelligence, provider-backed Reddit community intelligence,
provider-backed Amazon product intelligence, and provider-backed IKEA regional
store intelligence. The normal shopping-run orchestrator can call these typed
agents when `CARTCART_AGENT_WORKFLOW_MODE=live`; fixture mode remains default.
Discovery mode selects only source IDs from supplied search results and returns
`insufficient_candidates` when no credible source remains. Generic product
analysis consumes only supplied product/listing/evidence bundles, uses no direct
tools, and returns evidence limitations for weak inputs instead of blocking
ordinary categories. Technology-domain analysis also uses no direct tools,
consumes only supplied product/listing/evidence bundles and executable catalog
route context, and falls back to generic analysis for non-technology input or
domain failure. YouTube review intelligence uses only typed
`VideoSearchProvider`, `TranscriptProvider`, `YouTubeTranscriptIngestor`, and
`VideoEvidenceCreator` boundaries; it does not call `yt-dlp` directly, parse
WebVTT, build caption-provider command arguments, or create final purchase
recommendations. Monitor-specialist analysis uses no direct tools, consumes only
supplied monitor product/listing/evidence bundles, preserves source IDs for
monitor-specific claims, and falls back to technology-domain or generic analysis
when input is outside monitor scope or specialist output fails validation.
Smartphone-specialist analysis uses no direct tools, consumes only supplied
smartphone product/listing/evidence bundles, preserves source IDs for camera,
battery, update-support, performance, and region/model caveat claims, and falls
back to technology-domain or generic analysis when input is outside phone scope
or specialist output fails validation. Laptop-specialist analysis uses no direct
tools, consumes only supplied laptop product/listing/evidence bundles,
preserves source IDs for CPU, RAM, storage, battery, display, port, weight, and
upgradeability claims, and falls back to technology-domain or generic analysis
when input is outside laptop scope or specialist output fails validation.
Earphones/headphones-specialist analysis uses no direct tools, consumes only
supplied earphone, headphone, earbud, or headset product/listing/evidence
bundles, preserves source IDs for ANC, comfort/fit, microphone, battery, and
codec/device-fit claims, and falls back to technology-domain or generic
analysis when input is outside audio scope or specialist output fails
validation. TV-specialist analysis uses no direct tools, consumes only supplied
TV product/listing/evidence bundles, preserves source IDs for panel/backlight,
HDR, motion, gaming-input, room-brightness, and size-fit claims, and falls back
to technology-domain or generic analysis when input is outside TV scope or
specialist output fails validation. Smartwatch-specialist analysis uses no
direct tools, consumes only supplied smartwatch product/listing/evidence
bundles, preserves source IDs for phone-compatibility, health-sensor, battery,
durability, and app-ecosystem claims, and falls back to technology-domain or
generic analysis when input is outside watch scope or specialist output fails
validation. Comparison decision uses no direct tools, consumes only supplied
brief, analysis, trust, dedupe, and evidence context, and preserves source IDs
while producing recommendation modes or explicit no-strong-buy output. Verifier
critic uses no direct tools, consumes the draft recommendation bundle plus
supplied products, listings, evidence, trust, analyses, and dedupe context, and
blocks unsafe, uncited, suspicious-listing, hard-budget, duplicate, or
developer-facing output through deterministic output guardrails. When live
workflow mode is selected while `CARTCART_LIVE_AGENTS_ENABLED=false`, readiness
reports `agents:workflow` with `live_agents_disabled`. When live agents are
enabled without `OPENAI_API_KEY`, readiness reports `agents:openai` with
`missing_openai_api_key`. The fixture workflow and mocked agent tests remain
available. Runtime callers must call the configuration helper before making a
model request and must not silently fall through to a live call without the flag
and key.

### Live OpenAI Agent Example

```dotenv
CARTCART_AGENT_WORKFLOW_MODE=live
CARTCART_LIVE_AGENTS_ENABLED=true
CARTCART_OPENAI_MODEL=gpt-5.5
OPENAI_API_KEY=replace-with-your-real-key
```

These process-only guards are intentionally separate from runtime settings:

- `CARTCART_RUN_LIVE_PROVIDER_TESTS=1` permits tests marked `live_provider` to
  make credentialed external calls. Never set it for routine or section-gate
  verification.
- `CARTCART_RECORD_PROVIDER_FIXTURES=1` permits the explicit Tavily fixture
  recorder to make one live call. It does not enable application runtime calls.

### Live Search Example

```dotenv
CARTCART_SEARCH_PROVIDER=tavily
CARTCART_SEARCH_PROVIDER_ENABLED=true
CARTCART_TAVILY_API_KEY=replace-with-your-local-secret
```

### HTTP And Static Extraction Example

```dotenv
CARTCART_EXTRACTION_PROVIDER=http_static
CARTCART_EXTRACTION_PROVIDER_ENABLED=true
```

This is the single configured extraction path used by shopping runs. It performs
a normal HTTP HTML fetch, stores the bounded raw snapshot, and runs static text
extraction through the `ExtractionProvider` boundary. It requires no Tavily or
other extraction-provider credential. `disabled` performs no request, while
`fixture` remains deterministic and network-free.

### Live YouTube Metadata Example

```dotenv
CARTCART_VIDEO_SEARCH_PROVIDER=youtube
CARTCART_VIDEO_SEARCH_PROVIDER_ENABLED=true
CARTCART_YOUTUBE_DATA_API_KEY=replace-with-your-local-secret
```

### Live YouTube Transcript Example

Run `scripts/local/sync-backend.sh` after dependency changes, then verify the
backend-managed runtime with `cd apps/backend && uv run deno --version`. The
pinned Deno version is `2.8.1`; runtime readiness requires at least `2.3.0`.

```dotenv
CARTCART_TRANSCRIPT_PROVIDER=yt_dlp
CARTCART_TRANSCRIPT_PROVIDER_ENABLED=true
CARTCART_YOUTUBE_TRANSCRIPT_LANGUAGES='["en"]'
```

`GET /readyz` reports missing or incompatible `yt-dlp`, `yt-dlp-ejs`, or Deno
dependencies. The provider uses fixed arguments including `--skip-download`,
`--no-playlist`, WebVTT output, requested language selectors, and the configured
Deno runtime. It ignores local yt-dlp config, disallows plugins and remote EJS
components, and never reads browser, server-account, or user-uploaded cookies.

### Live Amazon Intelligence Example

```dotenv
CARTCART_AMAZON_PRODUCT_INTELLIGENCE_PROVIDER=serpapi
CARTCART_AMAZON_PRODUCT_INTELLIGENCE_PROVIDER_ENABLED=true
CARTCART_SERPAPI_API_KEY=replace-with-your-local-secret
```

### Search-Backed IKEA Example

```dotenv
CARTCART_SEARCH_PROVIDER=tavily
CARTCART_SEARCH_PROVIDER_ENABLED=true
CARTCART_TAVILY_API_KEY=replace-with-your-local-secret
CARTCART_IKEA_STORE_INTELLIGENCE_PROVIDER=search
CARTCART_IKEA_STORE_INTELLIGENCE_PROVIDER_ENABLED=true
```

## Fixture Replay

Committed provider cassettes and transcript fixtures live in
`apps/backend/tests/fixtures/providers/`. HTTP replay uses
`httpx.MockTransport` and requires the request method, base URL, non-secret query
parameters, and JSON body to match the fixture exactly. A mismatch fails instead
of falling through to the network.

Replay rules:

- Keep fixtures versioned, deterministic, small, and limited to fields required
  by the provider contract or evidence mapping under test.
- Use synthetic, non-personal queries, products, sellers, and source text.
- Never commit headers, cookies, credentials, access tokens, signed URLs,
  personal data, full raw pages, generated answers, image payloads, or excessive
  licensed text.
- Preserve explicit evidence gaps. Do not add fixture data merely to make an
  unavailable field appear supported.
- Inspect the complete fixture diff before committing. Automatic sanitization
  cannot recognize every secret, personal detail, or licensing restriction.
- Keep fixture replay as the default for tests and evals. Live provider tests
  remain separately marked and explicitly opt-in.

The fixture writer removes known secret-like fields, `answer`, `images`, and
`raw_content`; limits arrays to 20 items; limits strings to 1,000 characters;
rejects unsupported JSON types; checks supplied secret values against serialized
output; and writes sorted JSON. These checks reduce risk but do not replace
human review.

### Recording Tavily Search

Tavily search is the only provider with a recorder currently. From
`apps/backend`, deliberately replace its cassette with:

```sh
CARTCART_RECORD_PROVIDER_FIXTURES=1 uv run python \
  -m app.tools.record_tavily_search_fixture \
  tests/fixtures/providers/tavily_search.json \
  "best monitor reviews" \
  --region PH \
  --max-results 5
```

The recorder refuses to run without the recording guard, a local Tavily key,
and an output path under `apps/backend/tests/fixtures/providers/`. Recording is
a live, quota-consuming operation and is never part of a routine test or gate.
YouTube, Reddit, Amazon, and IKEA fixtures are synthetic replay fixtures; do not
claim that they were captured live unless a reviewed recorder is added later.

## Compliance Constraints

- Confirm current provider and source terms before enabling live calls. A valid
  credential does not establish permission to retrieve, retain, or redistribute
  content.
- Prefer documented APIs and approved domain-scoped search. Do not bypass
  authentication, robots controls, access restrictions, rate limits, or blocked
  content.
- Keep page extraction static-first. Browser automation is an optional fallback,
  disabled by default, and should be considered only after usable static HTML
  extraction fails. Enabling a dynamic provider must not bypass source policy or
  access restrictions.
- YouTube metadata access does not grant public transcript access. The approved
  MVP public-caption path is the explicitly configured, pinned
  `YtDlpTranscriptProvider`. It must not use cookies, accounts, remote-downloaded
  EJS components, browser impersonation configuration, or video/audio downloads.
  It preserves language and timestamps, records unavailable, restricted,
  rate-limited, challenge-failed, and other failed access as explicit gaps, and
  creates no transcript-backed claim when no supported transcript exists.
- Reddit search excerpts are qualitative community signals. Do not present them
  as authoritative product facts, and do not fetch Reddit pages directly from
  the current adapter. Community evidence creation accepts only claims grounded
  in each cited public summary, keeps recurring-claim context references, and
  preserves stale, low-context, anecdotal, and inaccessible-content warnings or
  gaps.
- Amazon evidence must preserve marketplace, listing, seller, fulfillment,
  region, variant, and review-quality context. Keep outbound links neutral and
  add no affiliate or tracking parameters.
- IKEA evidence is country/region-specific. Accept only the expected official
  regional domain/path and never infer global shipping from brand presence.
- Apply source allow/avoid and source-quality policy before accepting results.
  A matching URL is not sufficient when seller or listing trust is unknown.

Provider-specific decisions and reconsideration triggers are recorded in
`docs/DECISIONS.md`.

## Storage Boundaries

| Data | Storage boundary |
| --- | --- |
| Normalized queries, results, URLs, provider metadata, source references, evidence, and gaps | Structured SQLite records. |
| Sanitized deterministic test cassettes | `apps/backend/tests/fixtures/providers/`; reviewed and committed. |
| Bulky raw responses, page snapshots, extracted content, screenshots, trace exports, and eval output | Ignored local files under `data/artifacts/`, referenced from SQLite only when needed. `yt-dlp` caption files use bounded per-call temporary directories and are always deleted after normalization. |
| Credentials, request headers, cookies, tokens, signed URLs, and unreviewed provider payloads | Never committed and never stored in provider fixtures. |

Raw artifacts are opt-in and retention-limited. Defaults are 30 days for raw
source snapshots and extracted content, 7 days for screenshots, 30 days for
agent/eval artifacts, and 14 days for traces. Screenshots are disabled by
default. Use `scripts/local/cleanup-artifacts.sh --yes` when local raw artifacts
should be removed before provider work. See `docs/OPERATIONS.md` for the complete
artifact policy.

## Section J Fixture Gate

The Section J gate is fixture-only. It covers provider contracts and settings,
readiness behavior, source-agent boundaries, deterministic source policy,
provider replay adapters, search persistence/integration, and this setup
reference. It excludes tests marked `live_provider`, all live calls, frontend
verification, full backend suites, model calls, extraction tasks from Section K,
and later eval/E2E gates.

Run the focused gate from `apps/backend`:

```sh
uv run pytest -q -m "not live_provider" \
  tests/test_provider_contracts.py \
  tests/test_settings.py \
  tests/test_health.py \
  tests/test_agent_contracts.py \
  tests/test_agent_catalog.py \
  tests/test_search_source_schemas.py \
  tests/test_search_source_repository.py \
  tests/test_source_intelligence_repository.py \
  tests/test_search_provider_runtime.py \
  tests/test_tavily_search_provider.py \
  tests/test_source_quality.py \
  tests/test_youtube_video_provider.py \
  tests/test_reddit_community_provider.py \
  tests/test_amazon_product_provider.py \
  tests/test_ikea_store_provider.py \
  tests/test_shopping_run_orchestrator.py \
  tests/test_provider_documentation.py
```
