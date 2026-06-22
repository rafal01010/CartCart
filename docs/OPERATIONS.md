# CartCart Operations

Status: Initial local operations assumptions for planning
Last updated: 2026-06-21

## Local MVP Assumptions

The MVP is local-first:

- One local user.
- No authentication or account system.
- Local SQLite persistence.
- Local file artifacts under `data/` when needed.
- No cross-session user preference profiling.
- External search, extraction, model, and source-intelligence providers are configured explicitly by environment variables when implementation reaches those milestones.

The initial monorepo skeleton exists under `apps/backend`, `apps/frontend`, `docs`, and `scripts/local`. The backend Python project can be initialized with `scripts/local/init-backend.sh`, synced with `scripts/local/sync-backend.sh`, linted with `scripts/local/lint-backend.sh`, type checked with `scripts/local/typecheck-backend.sh`, tested with `scripts/local/test-backend.sh`, migrated with `scripts/local/migrate-backend.sh`, started with `scripts/local/start-backend.sh`, exported to OpenAPI with `scripts/local/export-openapi.sh`, reset with `scripts/local/reset-db.sh`, and cleaned with `scripts/local/cleanup-artifacts.sh`. The frontend can be initialized with `scripts/local/init-frontend.sh`, synced with `scripts/local/sync-frontend.sh`, linted with `scripts/local/lint-frontend.sh`, checked with `scripts/local/check-frontend.sh`, tested with `scripts/local/test-frontend.sh`, built with `scripts/local/build-frontend.sh`, prepared for browser checks with `scripts/local/setup-playwright.sh`, and started with `scripts/local/start-frontend.sh`. The local app can be started, stopped, and restarted with `scripts/local/start-app.sh`, `scripts/local/stop-app.sh`, and `scripts/local/restart-app.sh`.

Manual local prerequisites:

- Install `uv` before backend setup.
- Install Node.js before frontend setup.
- Make `pnpm` available on `PATH` before frontend setup. With a Node.js installation that includes Corepack, run `corepack enable`, `corepack prepare pnpm@latest --activate`, then verify with `pnpm --version`.

## Current Local Scripts

`scripts/local/init-backend.sh` initializes `apps/backend/pyproject.toml` when it is missing, pins the backend to Python 3.12, and delegates dependency installation to `scripts/local/sync-backend.sh`.

Run it:

- after a fresh checkout before backend development

`scripts/local/init-frontend.sh` initializes `apps/frontend/package.json` when it is missing by running the Svelte CLI with the minimal SvelteKit template, TypeScript, no add-ons, and `pnpm` dependency installation. It also runs `pnpm --dir apps/frontend install` so repeated invocations refresh dependencies from the lockfile.

Run it:

- after a fresh checkout before frontend development
- when `apps/frontend/node_modules` is missing or stale

`scripts/local/sync-frontend.sh` syncs frontend dependencies from `apps/frontend/package.json` and `apps/frontend/pnpm-lock.yaml`.

Run it:

- after frontend dependency metadata changes
- when `apps/frontend/node_modules` is missing or stale

Frontend browser API configuration defaults to `http://127.0.0.1:8000`. Override it with `PUBLIC_CARTCART_API_BASE_URL` when the backend is available at another origin.

`scripts/local/lint-frontend.sh` runs strict frontend lint-style Svelte diagnostics. It currently uses `svelte-check --fail-on-warnings`, so warning output is treated as actionable.

Run it:

- before submitting frontend changes when Svelte diagnostics or warnings need to be checked
- with additional `svelte-check` arguments after the script name when needed

`scripts/local/check-frontend.sh` runs the frontend SvelteKit type/component check.

Run it:

- before submitting frontend changes that affect Svelte components, routes, or TypeScript contracts
- after changing frontend API types, form state, route code, or shared UI utilities

`scripts/local/test-frontend.sh` runs frontend unit tests through Vitest. Pass Vitest arguments after the script name for focused checks.

Run it:

- before submitting frontend behavior changes
- with a focused test path for task-local checks, such as `scripts/local/test-frontend.sh src/lib/api/client.test.ts`

`scripts/local/build-frontend.sh` builds the frontend production bundle.

Run it:

- before release-like local checks
- after changes to routing, SvelteKit config, build config, or browser-only imports

`scripts/local/setup-playwright.sh` installs Playwright browser binaries using the frontend-local Playwright CLI.

Run it:

- after `scripts/local/sync-frontend.sh` on a machine that needs browser/E2E checks
- before running later Playwright smoke tests

`pnpm --dir apps/frontend run test:e2e` runs the Playwright smoke test. The Playwright config starts the backend and frontend on `127.0.0.1:8000` and `127.0.0.1:5173` by default, runs Alembic migrations against `data/e2e/cartcart-e2e.sqlite3`, then drives the browser through session creation, a fixture run, progress observation, and final-pick rendering.

Run it:

- at the Section I local developer workflow gate
- after `scripts/local/setup-playwright.sh` has installed browser binaries
- when the first stubbed browser workflow needs verification

Stop the managed local app first if it is already using the default ports, or override E2E ports and database path with `CARTCART_E2E_BACKEND_HOST`, `CARTCART_E2E_BACKEND_PORT`, `CARTCART_E2E_FRONTEND_HOST`, `CARTCART_E2E_FRONTEND_PORT`, and `CARTCART_E2E_DATABASE_PATH`.

`scripts/local/start-frontend.sh` starts the SvelteKit development server in the background. It reads `apps/backend/.env` and `apps/frontend/.env` when present, derives `PUBLIC_CARTCART_API_BASE_URL` from the backend host and port when that variable is not already set, and writes logs and a PID file.

Run it:

- when manually exercising the frontend without starting the backend through `start-app.sh`
- after frontend dependencies have been synced

`scripts/local/sync-backend.sh` syncs the backend environment from `apps/backend/pyproject.toml` and `apps/backend/uv.lock`.

Run it:

- after backend dependency metadata changes
- when `apps/backend/.venv` is missing or stale
- before backend verification commands if dependencies may have changed

`scripts/local/lint-backend.sh` runs Ruff against backend application and test code.

Run it:

- before submitting backend changes when lint failures need to be checked
- with additional Ruff arguments after the script name when needed, such as `--fix`

`scripts/local/typecheck-backend.sh` runs mypy against backend application code.

Run it:

- before submitting backend changes that affect typed application contracts
- after changing schemas, repositories, services, API routes, or orchestration code

`scripts/local/test-backend.sh` runs the backend pytest suite. Pass pytest arguments after the script name for focused checks.

Run it:

- before submitting backend behavior changes
- with a focused test path for task-local checks, such as `scripts/local/test-backend.sh tests/test_health.py`

`scripts/local/migrate-backend.sh` runs Alembic migrations from the backend project. It upgrades to `head` by default, and accepts an optional revision as the first argument.

Run it:

- after a fresh dependency sync when the local SQLite database has not been created yet
- after database model or migration changes
- after `scripts/local/reset-db.sh --yes` when rebuilding the default local database

`scripts/local/start-backend.sh` starts the local FastAPI backend with Uvicorn in the background. It reads shell environment variables and `apps/backend/.env` when present, then writes logs and a PID file.

Run it:

- when manually checking backend endpoints such as `GET /healthz` and `GET /readyz`
- when a later frontend or integration step needs the backend running locally

`scripts/local/start-app.sh` starts the managed backend and frontend processes. The command is idempotent for already-running managed services with valid PID files.

Run it:

- after backend and frontend dependencies have been synced
- when manually using the local CartCart app

`scripts/local/stop-app.sh` stops the managed frontend process first, then the managed backend process. Missing or stale PID files are handled as already-stopped services.

Run it:

- when finished with manual local app usage
- before changing lifecycle environment variables such as ports or run/log directories

`scripts/local/restart-app.sh` runs `stop-app.sh`, then `start-app.sh`.

Run it:

- after changing backend or frontend code when a clean local process restart is easier than relying on reload behavior
- after changing lifecycle environment variables

`scripts/local/export-openapi.sh` exports the FastAPI OpenAPI contract to `docs/openapi.json` by default. It accepts an optional output path.

Run it:

- after backend API or schema changes
- before generating frontend API types once that workflow exists
- when reviewing the current implemented endpoint/schema contract

`scripts/local/reset-db.sh --yes` deletes the configured local SQLite database file plus SQLite sidecar files (`-journal`, `-shm`, and `-wal`). It reads `apps/backend/.env` when present and respects `CARTCART_DATABASE_PATH` or `CARTCART_DATA_DIR`.

Run it:

- when local persistence needs a clean schema/data reset
- before rerunning migrations from scratch against the default local database

`scripts/local/cleanup-artifacts.sh --yes` deletes local artifact files according to the configured retention windows. It reads `apps/backend/.env` when present and respects `CARTCART_ARTIFACT_DIR`, `CARTCART_DATA_DIR`, and the artifact retention settings.

Run it:

- before live-provider development if previous raw snapshots, extraction outputs, traces, or eval artifacts should be cleaned
- periodically during local development to control disk usage

Do not use setup/sync scripts as test checkpoint commands. Use the dedicated backend verification wrappers for backend lint, type check, test, migration, startup, and OpenAPI export workflows. Use the dedicated frontend wrappers for frontend lint, check, test, build, and Playwright browser setup workflows. Use the lifecycle scripts for manual local app startup, shutdown, and restart.

## App Lifecycle

Default service URLs:

- Backend: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:5173`

Lifecycle state is stored under `data/` by default:

- Backend PID: `data/run/backend.pid`
- Frontend PID: `data/run/frontend.pid`
- Backend log: `data/logs/backend.log`
- Frontend log: `data/logs/frontend.log`

Start the full local app:

```sh
scripts/local/start-app.sh
```

Stop the full local app:

```sh
scripts/local/stop-app.sh
```

Restart the full local app:

```sh
scripts/local/restart-app.sh
```

Start only one side when needed:

```sh
scripts/local/start-backend.sh
scripts/local/start-frontend.sh
```

`start-backend.sh` and `start-frontend.sh` refuse to start a duplicate managed service when the PID file points to a running process. If the PID file is stale, the start script removes it and starts a new process. `stop-app.sh` treats missing or stale PID files as already stopped. If a service exits during the first startup second, the start script prints the last log lines and removes its PID file.

Lifecycle environment variables:

- `CARTCART_BACKEND_HOST`: backend bind host. Defaults to `127.0.0.1`.
- `CARTCART_BACKEND_PORT`: backend bind port. Defaults to `8000`.
- `CARTCART_BACKEND_RELOAD`: backend Uvicorn reload toggle. Defaults to `true`.
- `CARTCART_FRONTEND_HOST`: frontend bind host. Defaults to `127.0.0.1`.
- `CARTCART_FRONTEND_PORT`: frontend bind port. Defaults to `5173`.
- `PUBLIC_CARTCART_API_BASE_URL`: frontend browser API base URL. Defaults to the configured backend URL.
- `CARTCART_RUN_DIR`: PID directory. Defaults to `data/run`.
- `CARTCART_LOG_DIR`: lifecycle log directory. Defaults to `data/logs`.
- `CARTCART_E2E_BACKEND_HOST`: Playwright backend host. Defaults to `127.0.0.1`.
- `CARTCART_E2E_BACKEND_PORT`: Playwright backend port. Defaults to `8000`.
- `CARTCART_E2E_FRONTEND_HOST`: Playwright frontend host. Defaults to `127.0.0.1`.
- `CARTCART_E2E_FRONTEND_PORT`: Playwright frontend port. Defaults to `5173`.
- `CARTCART_E2E_DATABASE_PATH`: Playwright SQLite database path. Defaults to `data/e2e/cartcart-e2e.sqlite3`.

Set backend lifecycle variables in the shell or in `apps/backend/.env`. Set frontend-specific variables in the shell or in `apps/frontend/.env`. Keep `CARTCART_RUN_DIR` and `CARTCART_LOG_DIR` common for the local app so the start and stop scripts agree on managed process locations.

The current local vertical slice is fixture-only. Creating a session, starting a stub run, streaming progress, and rendering the final fixture recommendation do not require external search provider keys, live model credentials, live web access, or OpenAI agent calls.

The Section I local workflow gate covers:

- backend lint, type check, tests, migration, app startup, and OpenAPI export
- frontend lint, check, unit tests, build, Playwright browser setup, and E2E smoke test
- lifecycle start/stop behavior with managed PID and log files

## Database Migrations

Alembic is configured in `apps/backend/alembic.ini` and uses the backend settings module to resolve the SQLite path. By default, migrations create or update the repository-level `data/cartcart.sqlite3` database. The current schema reference lives in `docs/DATABASE.md`.

The current pre-release migration history is squashed into one initial persistence baseline. If a local database was created from the earlier task-by-task migration chain, reset it before applying the current baseline.

Run migrations through the local wrapper:

```sh
scripts/local/migrate-backend.sh
```

Override `CARTCART_DATABASE_PATH` or `CARTCART_DATA_DIR` to migrate a different local SQLite database. Use absolute paths for overrides.

Reset the default local database and rebuild the schema:

```sh
scripts/local/reset-db.sh --yes
scripts/local/migrate-backend.sh
```

The reset script deletes only the configured SQLite database and sidecar files. It does not delete `data/artifacts/`, traces, eval output, or source snapshot files. Use `scripts/local/cleanup-artifacts.sh --yes` for artifact cleanup.

## Expected Services

Backend:

- FastAPI application.
- SQLite database.
- Alembic migrations for the current local SQLite schema.
- Structured JSON logs.
- OpenTelemetry instrumentation.
- Optional Logfire or another OpenTelemetry backend for local development.

Frontend:

- SvelteKit development server.
- TypeScript checks and focused frontend tests.

Later local deployment-like operation may add Docker Compose, persistent volumes, and release scripts.

## Configuration Direction

Backend configuration is loaded through typed settings from environment variables and optional local overrides in `apps/backend/.env`. Use `apps/backend/.env.example` as the safe placeholder template. Do not commit `apps/backend/.env`.

Current backend variables:

- `CARTCART_ENVIRONMENT`: runtime mode. Allowed values are `local`, `test`, `fixture`, `live`, and `production`. Defaults to `local`.
- `CARTCART_BACKEND_HOST`: local backend bind host. Defaults to `127.0.0.1`.
- `CARTCART_BACKEND_PORT`: local backend bind port. Defaults to `8000`.
- `CARTCART_BACKEND_RELOAD`: local startup reload toggle used by `scripts/local/start-backend.sh`. Defaults to `true`.
- `CARTCART_FRONTEND_HOST`: local frontend bind host. Defaults to `127.0.0.1`.
- `CARTCART_FRONTEND_PORT`: local frontend bind port. Defaults to `5173`.
- `CARTCART_RUN_DIR`: lifecycle PID directory. Defaults to `data/run`.
- `CARTCART_LOG_DIR`: lifecycle log directory. Defaults to `data/logs`.
- `CARTCART_LOG_LEVEL`: backend structured log level. Defaults to `INFO`.
- `CARTCART_FRONTEND_ORIGINS`: JSON array of allowed frontend origins for CORS. Defaults to local SvelteKit origins.
- `PUBLIC_CARTCART_API_BASE_URL`: frontend browser API base URL. Defaults in code to `http://127.0.0.1:8000`.
- `CARTCART_TELEMETRY_ENABLED`: enables OpenTelemetry FastAPI instrumentation when `true`. Defaults to `false`.
- `CARTCART_TELEMETRY_EXPORTER`: telemetry exporter. Allowed values are `console` and `otlp`. Defaults to `console`.
- `CARTCART_TELEMETRY_SERVICE_NAME`: OpenTelemetry service name. Defaults to `cartcart-backend`.
- `CARTCART_TELEMETRY_OTLP_ENDPOINT`: OTLP HTTP traces endpoint for a local collector. Defaults to `http://127.0.0.1:4318/v1/traces`.
- `CARTCART_DEFAULT_REGION_CODE`: default provider region code. Defaults to `US`.
- `CARTCART_PROVIDER_TIMEOUT_SECONDS`: default provider call timeout. Defaults to `10`.
- `CARTCART_PROVIDER_RATE_LIMIT_PER_MINUTE`: default local provider rate-limit budget. Defaults to `60`.
- `CARTCART_AGENT_WORKBENCH_ENABLED`: enables the local-only isolated agent workbench when `true`. Defaults to `false`.
- `CARTCART_AGENT_WORKFLOW_MODE`: normal shopping-run agent mode. Allowed values are `fixture` and `live`. Defaults to `fixture`.
- `CARTCART_LIVE_AGENTS_ENABLED`: opt-in gate for live OpenAI agent calls. Defaults to `false`.
- `CARTCART_OPENAI_MODEL`: model string for implemented OpenAI Agents SDK runners. Defaults to `gpt-5.4-mini`.
- `CARTCART_OPENAI_AGENT_TIMEOUT_SECONDS`: per-agent timeout for live runners. Defaults to `45`.
- `CARTCART_OPENAI_AGENT_MAX_TURNS`: max SDK runner turns. Defaults to `8`.
- `CARTCART_OPENAI_AGENT_TRACING_ENABLED`: enables OpenAI Agents SDK tracing when live runners use it. Defaults to `false`.
- `CARTCART_OPENAI_AGENT_TRACE_INCLUDE_SENSITIVE_DATA`: controls whether OpenAI trace payloads may include inputs/outputs. Defaults to `false`.
- `CARTCART_OPENAI_AGENT_TRACE_WORKFLOW_NAME`: OpenAI trace workflow name. Defaults to `cartcart-agent-run`.
- `OPENAI_API_KEY`: local OpenAI API key. Required only for explicitly enabled live-agent mode.
- `CARTCART_OPENAI_API_KEY`: compatibility alias for local OpenAI API key; `OPENAI_API_KEY` is preferred.
- `CARTCART_SEARCH_PROVIDER`: general web search provider. Allowed values are `fixture`, `tavily`, and `brave`. Defaults to `fixture`.
- `CARTCART_SEARCH_PROVIDER_ENABLED`: enables live general web search provider use when `true`. Defaults to `false`.
- `CARTCART_EXTRACTION_PROVIDER`: source extraction provider. Allowed values are `disabled`, `fixture`, and `http_static`. Defaults to `fixture`.
- `CARTCART_EXTRACTION_PROVIDER_ENABLED`: enables the configured HTTP/static extraction adapter when `true`. Defaults to `false`.
- `CARTCART_VIDEO_SEARCH_PROVIDER`: video metadata provider. Allowed values are `disabled`, `fixture`, and `youtube`. Defaults to `fixture`.
- `CARTCART_VIDEO_SEARCH_PROVIDER_ENABLED`: enables live video metadata provider use when `true`. Defaults to `false`.
- `CARTCART_AMAZON_PRODUCT_INTELLIGENCE_PROVIDER`: Amazon product/listing/review provider. Allowed values are `disabled`, `fixture`, and `serpapi`. Defaults to `fixture`.
- `CARTCART_AMAZON_PRODUCT_INTELLIGENCE_PROVIDER_ENABLED`: enables live Amazon product intelligence when `true`. Defaults to `false`.
- `CARTCART_IKEA_STORE_INTELLIGENCE_PROVIDER`: IKEA regional official-store provider. Allowed values are `disabled`, `fixture`, and `search`. Defaults to `fixture`.
- `CARTCART_IKEA_STORE_INTELLIGENCE_PROVIDER_ENABLED`: enables search-backed IKEA regional discovery when `true`. Defaults to `false`.
- `CARTCART_TAVILY_API_KEY`: local Tavily API key. Required only when Tavily-backed search is enabled.
- `CARTCART_BRAVE_SEARCH_API_KEY`: local Brave Search API key. Required only when Brave search is enabled.
- `CARTCART_SERPAPI_API_KEY`: local SerpApi key. Required only when SerpApi Amazon product intelligence is enabled.
- `CARTCART_YOUTUBE_DATA_API_KEY`: local YouTube Data API key. Required only when live YouTube metadata search is enabled.
- `CARTCART_DATA_DIR`: local data directory. Defaults to the repository-level `data/` directory.
- `CARTCART_DATABASE_PATH`: SQLite database path. Defaults to `data/cartcart.sqlite3`.
- `CARTCART_ARTIFACT_DIR`: local artifact directory. Defaults to `data/artifacts`.
- `CARTCART_SOURCE_FETCH_MAX_CONTENT_BYTES`: maximum decoded HTML response body stored by the source fetcher. Defaults to `2097152` bytes.
- `CARTCART_SOURCE_FETCH_USER_AGENT`: explicit user agent sent by the source fetcher. Defaults to `CartCart/0.1 source-fetcher`; do not configure browser impersonation or access-control bypass behavior.
- `CARTCART_RAW_SOURCE_SNAPSHOT_RETENTION_DAYS`: retention window for raw source snapshots. Defaults to `30`.
- `CARTCART_EXTRACTED_CONTENT_RETENTION_DAYS`: retention window for extracted text/Markdown. Defaults to `30`.
- `CARTCART_SCREENSHOT_RETENTION_DAYS`: retention window for optional screenshots. Defaults to `7`.
- `CARTCART_AGENT_OUTPUT_RETENTION_DAYS`: retention window for bulky agent output artifacts. Defaults to `30`.
- `CARTCART_TRACE_RETENTION_DAYS`: retention window for local trace export files. Defaults to `14`.
- `CARTCART_EVAL_ARTIFACT_RETENTION_DAYS`: retention window for eval output artifacts. Defaults to `30`.
- `CARTCART_SCREENSHOTS_ENABLED`: enables optional screenshot capture when a later provider/extraction workflow supports it. Defaults to `false`.
- `CARTCART_CROSS_SESSION_PREFERENCE_PROFILING_ENABLED`: must remain `false` for MVP. Attempts to set it to `true` are rejected by settings validation.

No real secrets are required for default fixture/stub operation. The project
owner only needs to set variables manually when overriding local paths, changing
runtime mode, or opting into live provider mode. Use absolute paths for local
path overrides. Provider and model keys must be supplied locally by the project
owner rather than committed.

`docs/PROVIDERS.md` is the authoritative provider setup, fixture replay,
compliance, disabled-provider, and raw-artifact safety reference. The notes below
summarize the adapters currently available for local operation.

The provider layer defines backend interfaces, fake providers, typed runtime
configuration, and a Tavily general web search adapter. Normal tests load a
versioned, sanitized HTTP cassette and replay it through `httpx.MockTransport`;
they do not use a real key or make a network call. Replay requires the outgoing
method, URL, query parameters, and JSON request to match the cassette exactly.
Runtime query
planning and discovery resolve the configured search provider. Fixture mode
remains the default. When Tavily is selected, enabled, and supplied with a key,
runs call Tavily and persist scored search-result metadata. Missing live
credentials fall back to fixture search after producing the existing readiness
warning. Provider results are not fetched or extracted in this stage.
Brave remains a reserved configuration value until a runtime adapter is added;
enabling it with credentials currently produces a clear configuration error.

Page extraction has one configured non-fixture path:
`CARTCART_EXTRACTION_PROVIDER=http_static` with
`CARTCART_EXTRACTION_PROVIDER_ENABLED=true`. The runtime builder composes the
bounded HTTP fetcher, raw snapshot persistence, and Trafilatura static extractor
behind `ExtractionProvider`. It requires no provider credential. `fixture`
returns deterministic snapshots, and `disabled` returns an excluded snapshot
without making a request. The removed Tavily extraction and generic SerpApi
shopping settings must not be used; SerpApi remains available only for the
Amazon intelligence adapter.

For local Tavily credentials, copy `apps/backend/.env.example` to
`apps/backend/.env` and set:

```dotenv
CARTCART_SEARCH_PROVIDER=tavily
CARTCART_SEARCH_PROVIDER_ENABLED=true
CARTCART_TAVILY_API_KEY=replace-with-your-real-key
```

The root `.gitignore` ignores `.env` and `.env.*` files except committed example
templates, so `apps/backend/.env` must remain local. A live adapter test is
available only when explicitly enabled with
`CARTCART_RUN_LIVE_PROVIDER_TESTS=1`; otherwise it is skipped. Live provider
calls spend provider quota and are not part of routine or section-gate checks.

Provider fixture recordings live under
`apps/backend/tests/fixtures/providers/`. The cassette writer never stores HTTP
headers, removes secret-like and excessive raw-content fields, bounds response
lists and strings, and writes stable sorted JSON. Record only synthetic,
non-personal queries and inspect the complete fixture diff before committing it;
automatic scrubbing cannot identify every form of sensitive or licensed text.

To deliberately replace the Tavily search fixture, run this from
`apps/backend`:

```sh
CARTCART_RECORD_PROVIDER_FIXTURES=1 uv run python \
  -m app.tools.record_tavily_search_fixture \
  tests/fixtures/providers/tavily_search.json \
  "best monitor reviews" \
  --region PH \
  --max-results 5
```

The recorder refuses to run without the explicit recording flag, a configured
Tavily key, and an output path under the provider fixture directory. This is a
live provider call and must not be included in routine tests or section-gate
verification.

YouTube metadata discovery has an official API adapter in addition to fixture
and disabled modes. It uses API-key-authenticated `search.list` and
`videos.list` requests, sends the key in the `X-Goog-Api-Key` header rather than
the URL, and stores only normalized metadata in its result bundle. It does not
call caption endpoints or assume transcript access. Configure live metadata
search locally with:

```dotenv
CARTCART_VIDEO_SEARCH_PROVIDER=youtube
CARTCART_VIDEO_SEARCH_PROVIDER_ENABLED=true
CARTCART_YOUTUBE_DATA_API_KEY=replace-with-your-real-key
```

Without the key, readiness reports `CARTCART_YOUTUBE_DATA_API_KEY` as missing
and runtime provider selection falls back to fixture behavior. Explicit
`disabled` mode returns a typed disabled result. Synthetic YouTube replay
fixtures cover the search and duration-detail requests without live calls or
quota use.

Amazon product intelligence has a SerpApi adapter in addition to fixture and
disabled modes. It calls SerpApi's documented Amazon Search and Amazon Product
engines, uses `shipping_location` when a target region is available, and
normalizes results into marketplace/listing/seller/review/region evidence. It
never exposes SerpApi result links or Amazon affiliate parameters; outbound
evidence links use the neutral `https://www.<marketplace>/dp/<ASIN>` form.
Configure live Amazon discovery locally with:

```dotenv
CARTCART_AMAZON_PRODUCT_INTELLIGENCE_PROVIDER=serpapi
CARTCART_AMAZON_PRODUCT_INTELLIGENCE_PROVIDER_ENABLED=true
CARTCART_SERPAPI_API_KEY=replace-with-your-real-key
```

Without the key, readiness reports `CARTCART_SERPAPI_API_KEY` as missing and
runtime selection falls back to fixture behavior. Explicit `disabled` mode
returns a typed disabled result. Synthetic SerpApi replay fixtures cover search
and product-detail calls without network access or quota use. Live tests require
both credentials and `CARTCART_RUN_LIVE_PROVIDER_TESTS=1`; they are not part of
routine or section-gate verification. SerpApi remains optional, and operators
must confirm that their account and intended use comply with current provider
terms before enabling live calls.

IKEA regional store intelligence has a domain-scoped search adapter in addition
to fixture and disabled modes. It reuses the configured general search provider
and accepts only official IKEA results matching the target country or region
path. Configure search-backed IKEA discovery locally with:

```dotenv
CARTCART_SEARCH_PROVIDER=tavily
CARTCART_SEARCH_PROVIDER_ENABLED=true
CARTCART_TAVILY_API_KEY=replace-with-your-real-key
CARTCART_IKEA_STORE_INTELLIGENCE_PROVIDER=search
CARTCART_IKEA_STORE_INTELLIGENCE_PROVIDER_ENABLED=true
```

If live general search is disabled or its credential is unavailable, readiness
reports the existing search warning or an IKEA provider-dependency warning and
runtime selection falls back to fixture behavior. Explicit `disabled` mode
returns a typed disabled result. Synthetic IKEA replay fixtures cover available
and unavailable products; unsupported regions return a gap without a provider
call. Search snippets remain metadata evidence and do not establish global
shipping.

OpenAI live agents are configured separately from source providers. Fixture and
mocked agents remain the default and require no OpenAI credential. A live
OpenAI agent call requires `CARTCART_LIVE_AGENTS_ENABLED=true`, a local
`OPENAI_API_KEY`, and an implemented agent runner or workbench path explicitly
requesting live mode. To route normal shopping runs through live agents, also
set `CARTCART_AGENT_WORKFLOW_MODE=live`; otherwise the normal workflow remains
fixture-first even when the workbench can request live mode. The backend accepts
`CARTCART_OPENAI_API_KEY` as a CartCart-prefixed compatibility alias, but the
standard `OPENAI_API_KEY` is preferred and takes precedence. Configure local
live-agent workflow mode with:

```dotenv
CARTCART_AGENT_WORKFLOW_MODE=live
CARTCART_LIVE_AGENTS_ENABLED=true
CARTCART_OPENAI_MODEL=gpt-5.5
OPENAI_API_KEY=replace-with-your-real-key
```

Without `OPENAI_API_KEY`, readiness reports `agents:openai` with
`missing_openai_api_key`, while fixture and mocked agent modes remain available.
The runtime configuration also carries per-agent timeout, max-turn, and tracing
metadata settings. OpenAI trace payloads exclude sensitive data by default.

The isolated agent workbench is a local debugging surface for one typed agent at
a time. It is disabled by default and is mounted only for `local`, `test`, or
`fixture` backend environments when explicitly enabled:

```dotenv
CARTCART_AGENT_WORKBENCH_ENABLED=true
```

The primary terminal runner is:

```bash
scripts/local/run-agent-workbench.sh \
  --agent ShoppingScopeGuardrail \
  --scenario guardrail/allowed-coffee-grinder \
  --mode fixture
```

Fixture mode uses deterministic fake agents and does not make provider or model
calls. Mock mode uses mocked model runners for implemented live agents; for
`ShoppingScopeGuardrail`, `guardrail/blocked-dangerous-product` proves an
obvious unsafe request is blocked before the model runner starts. For
`ShoppingGuideAgent`, `guide/headphones-missing-budget` checks a concise
follow-up without recommendation output, while `guide/ready-monitor-brief`
checks the ready-for-analysis transition and `IntakeAgent` handoff. For
`IntakeAgent`, `intake/monitor-ph-budget` checks structured category, region,
budget, and preference inference, while `intake/ambiguous-category` checks that
uncertain category intent remains uncertain. For `QueryPlannerAgent`,
`query-planner/coffee-grinder-us` checks region-aware shopping and review
queries for a non-specialist category, while
`query-planner/unknown-category-generic` checks generic fallback strategy
without artificial category blocking. For `DiscoveryAgent`,
`discovery/select-valid-sources` checks that eligible retailer and review source
IDs are selected while weak proxy sources are rejected, while
`discovery/no-good-results` checks the `insufficient_candidates` fallback
without product-detail fabrication. For `CategoryRouterAgent`,
`router/monitor-to-specialist` checks the route path
`TechnologyDomainAnalystAgent` to `MonitorSpecialistAgent`, while
`router/office-chair-generic` checks direct `GenericProductAnalystAgent`
fallback with no unsupported-category error. For `GenericProductAnalystAgent`,
`generic/office-chair-analysis` checks a non-tech office-chair
`CategoryAnalysis` with fit tradeoffs, evidence gaps, and preserved
evidence/source IDs, while `generic/weak-evidence` checks low-confidence
limitations instead of category refusal. For `TechnologyDomainAnalystAgent`,
`technology/router-monitor` checks the declared `MonitorSpecialistAgent` route
in internal tool activity, while `technology/router-keyboard-domain` checks
broad technology-domain analysis for a technology category without an MVP
specialist. For `MonitorSpecialistAgent`,
`monitor/coding-movies-1440p` checks source-backed monitor analysis covering
panel type, resolution, refresh rate, ergonomics, ports, tradeoffs, and source
IDs, while `monitor/non-monitor-reject` checks fallback instead of forced
monitor analysis for non-monitor input. For `SmartphoneSpecialistAgent`,
`smartphone/midrange-camera-battery` checks source-backed smartphone analysis
covering camera, battery, update support, performance, region/model caveats,
and source IDs, while `smartphone/non-phone-reject` checks fallback instead of
forced smartphone analysis for non-phone input. For `LaptopSpecialistAgent`,
`laptop/student-portable`
checks source-backed laptop analysis covering CPU, RAM, storage, battery,
display, ports, weight, upgradeability, and source IDs, while
`laptop/non-laptop-reject` checks fallback instead of forced laptop analysis
for non-laptop input. For `EarphonesHeadphonesSpecialistAgent`,
`headphones/noise-cancelling-commute` checks source-backed headphone analysis
covering ANC, comfort/fit, microphone, battery, codec/device fit, and source
IDs, while `headphones/non-audio-reject` checks fallback instead of forced
headphone analysis for non-audio input. For `TVSpecialistAgent`,
`tv/55-inch-movies-gaming` checks source-backed TV analysis covering
panel/backlight, HDR, motion, gaming inputs, room brightness, size fit, and
source IDs, while `tv/non-tv-reject` checks fallback instead of forced TV
analysis for non-TV input. For `SmartwatchSpecialistAgent`,
`smartwatch/fitness-android` checks source-backed smartwatch analysis covering
phone compatibility, health sensors, battery, durability, app ecosystem, and
source IDs, while `smartwatch/non-watch-reject` checks fallback instead of
forced smartwatch analysis for non-watch input. For `SellerListingTrustAgent`,
`trust/unknown-marketplace-cheap` checks that an unknown marketplace seller with
a far-below-comparable price and unclear return policy is weak or suspicious,
while `trust/established-retailer` checks reasonable trust when seller/source
evidence supports it. Hard deterministic suspicious flags remain visible in the
final `ListingTrustAssessment` instead of being silently overridden. For
`YouTubeReviewIntelligenceAgent`, `youtube/monitor-review-transcript` checks
timestamped transcript evidence while `youtube/no-transcript-gap` checks
metadata-only gaps. For `RedditCommunityIntelligenceAgent`,
`reddit/headphones-recurring-complaint` checks recurring qualitative community
signals with subreddit/thread/source context and anecdotal/manipulation
warnings, while `reddit/inaccessible-gap` checks explicit inaccessible-content
gaps. For `AmazonProductIntelligenceAgent`,
`amazon/third-party-seller-region-gap` checks marketplace/listing, seller,
review, and regional shipping-gap context. For `IKEAStoreIntelligenceAgent`,
`ikea/available-regional-product` checks official regional price/currency,
availability, and source IDs, while `ikea/no-regional-presence` checks an
explicit unsupported-region gap without global-shipping inference. For
`ComparisonDecisionAgent`, `comparison/monitor-shortlist` checks a
source-backed three-monitor shortlist with best overall, best value,
within-budget, stretch, and runner-up modes, while
`comparison/no-strong-buy` checks an explicit no-strong-buy outcome when trust
and evidence do not support a safe recommendation. For `VerifierCriticAgent`,
`verifier/unsupported-claim-block` checks that an uncited product/spec claim
blocks output, while `verifier/suspicious-listing-warning` checks that a
suspicious final listing without a trust caveat is rejected or made visibly
unsafe for display. `--mode live` still requires
`CARTCART_LIVE_AGENTS_ENABLED=true`, `OPENAI_API_KEY`, and a live runner
registered for the selected agent; otherwise the workbench returns a typed
configuration error. The local browser page is available at
`/internal/agent-workbench` on the frontend dev server when the backend
workbench endpoints are enabled. The workbench never accepts arbitrary agent
names, system prompts, tool definitions, or provider arguments.

Source-intelligence provider interfaces use fake implementations where a
dedicated adapter has not been added or local live configuration is unavailable.
Provider protocols return source evidence bundles or explicit gaps without
calling vendor SDKs directly from source agents.

Future configuration areas include:

- Additional source-intelligence provider keys and enabled-provider flags.
- Provider-specific timeout and rate-limit settings beyond the shared defaults.
- Reddit/domain-scoped community search and extraction provider configuration.
- Telemetry enabled/disabled flag.
- Logfire or OTEL exporter settings.
- Provider timeout and rate-limit settings.

Missing optional provider keys should produce readiness warnings or disabled-provider behavior, not break fixture or stub mode.

## Persistence And Artifacts

SQLite should hold canonical structured state. Bulky raw artifacts should be files referenced from SQLite.

Local persistence should cover:

- Sessions.
- Inputs and corrected briefs.
- Runs and events.
- Source metadata, snapshots, and evidence.
- Product listings and canonical groups.
- Trust assessments.
- Agent outputs.
- Recommendation bundles.
- Refinement history.
- Eval summaries where useful.

Local artifact storage may include:

- Raw source snapshots under `data/artifacts/raw-sources/`.
- Extracted text or Markdown under `data/artifacts/extracted-content/`.
- Optional screenshots under `data/artifacts/screenshots/`; screenshot capture is disabled by default.
- Bulky agent output artifacts under `data/artifacts/agent-outputs/` when they are too large or sensitive for normal structured records.
- Trace exports under `data/artifacts/traces/`.
- Eval exports under `data/artifacts/evals/`.

Structured references, IDs, URLs, provider metadata, evidence records, and result records belong in SQLite. Large raw source bodies, extracted page text, screenshots, trace exports, and eval output belong in files referenced from SQLite when later live-provider tasks need them.

Retention defaults for local artifacts:

| Artifact type | Directory | Default retention | Notes |
| --- | --- | ---: | --- |
| Raw source snapshots | `data/artifacts/raw-sources/` | 30 days | Store only when useful for audit, debugging, extraction replay, or eval fixtures. |
| Extracted content | `data/artifacts/extracted-content/` | 30 days | Store extracted text/Markdown separately from structured evidence. |
| Screenshots | `data/artifacts/screenshots/` | 7 days | Disabled by default and only captured when explicitly enabled. |
| Agent output artifacts | `data/artifacts/agent-outputs/` | 30 days | Use for bulky intermediate outputs; concise structured records remain in SQLite. |
| Trace exports | `data/artifacts/traces/` | 14 days | Keep local trace files short-lived by default. |
| Eval artifacts | `data/artifacts/evals/` | 30 days | Keep local eval outputs fixture-oriented and avoid live-provider secrets. |

Set a retention value to `0` to delete that artifact class on the next cleanup. Retention settings do not delete SQLite records.

Current persistence implementation stores shopping sessions in SQLite with the original session request, original query, current shopping brief, and create/update timestamps. It also stores shopping runs, ordered run events, and refinement requests linked to their stub runs so the latest run status can be loaded from the run record while the event history and refinement history remain inspectable. Search plans, search results, source snapshots, and source evidence are stored with run links and provider metadata.

Lookup indexes currently cover session/run/refinement relationships, ordered run events, source and product URLs, provider names and provider result/query IDs, video/source/product/listing target IDs, product brand/model/category identifiers, agent record names/stages/trace IDs, and result version lookup by run/version.

Video review evidence persistence stores video sources, transcript availability, permitted transcript segments or explicit transcript gaps, channel metadata, source-backed video evidence bundles, and link metadata for run IDs, source snapshot IDs, target product/listing/candidate IDs, and future recommendation claim IDs.

Reusable source-intelligence persistence also stores Reddit/community discussion evidence, Amazon product/listing/review evidence, and IKEA regional official-store evidence before live source-intelligence mode. Those records preserve source links, source-specific context, confidence, evidence gaps, and product/listing/seller/review/region targets without storing unnecessary raw provider payloads in SQLite.

Product persistence stores canonical products, distinct product listings, candidate shortlist membership, and user-added products. Multiple listings can point to one canonical product while preserving listing-specific seller, URL, price, availability, and source details.

Result persistence stores listing trust assessments, category analysis outputs, agent run records, comparison matrices, recommendation bundles, and result versions. Result versions point to the saved recommendation bundle and comparison matrix for a run so the latest complete fixture result can be loaded without recomputing analysis.

## Observability

Every run should have:

- `session_id`
- `run_id`
- `trace_id`
- OpenAI Agents SDK trace metadata when live agents are enabled.
- OpenTelemetry spans for API requests, workflow stages, search calls, extraction calls, agent runs, database operations, and eval runs.
- Structured logs with stable fields.

Backend request logs are emitted as one JSON object per line. The baseline fields are `timestamp`, `level`, `logger`, `message`, `event`, `request_id`, and an `http` object with request method, path, status code, and duration. `session_id` and `run_id` are included when a route or request state exposes them. Unhandled exceptions include an `exception` object with type, message, and traceback.

Request logging does not include request bodies, headers, cookies, query strings, provider payloads, or environment variables by default.

OpenTelemetry is disabled by default. To inspect local spans without running a collector, set:

```sh
CARTCART_TELEMETRY_ENABLED=true
CARTCART_TELEMETRY_EXPORTER=console
```

To send spans to a local OTLP HTTP collector, set:

```sh
CARTCART_TELEMETRY_ENABLED=true
CARTCART_TELEMETRY_EXPORTER=otlp
CARTCART_TELEMETRY_OTLP_ENDPOINT=http://127.0.0.1:4318/v1/traces
```

The current OpenTelemetry baseline instruments FastAPI requests only. Workflow
stages also persist local `AgentRunRecord` rows with trace IDs, runtime mode,
stage timing, model name when applicable, sanitized allowed-tool activity,
fallback/error outcome, and nullable token/cost fields. Hosted observability
backends such as Logfire or OTLP collectors require project-owner configuration;
do not add hosted exporter secrets to committed files.

Minimum operational signals:

- Run count, success count, and failure count.
- Run duration by stage.
- Search provider latency and failure rate.
- Extraction success and failure rate.
- Candidate count and dedupe count.
- Token usage and approximate cost by run or stage.
- Number of source-backed claims.
- Eval pass rate.
- User-visible error count.

## Request IDs And Errors

The backend attaches `X-Request-ID` to responses. If a request supplies that header, the backend echoes it; otherwise it generates a new ID. Validation errors and project application errors return the shared `ErrorEnvelope` JSON shape documented in `docs/API.md`.

## Health And Readiness

`GET /healthz` reports process liveness and remains cheap.

`GET /readyz` reports configuration readiness, provider warnings, and live-agent
configuration warnings. Missing keys for enabled live providers or live OpenAI
agents return warning entries while the endpoint still returns HTTP 200 and
`status: ready`, so fixture/stub mode is not blocked. Enabled `yt_dlp`
transcript mode also checks the exact pinned `yt-dlp` and `yt-dlp-ejs` packages
plus Deno `>=2.3.0`; missing or incompatible dependencies are reported without
replacing live transcript retrieval with fixture text. Database availability
checks may be added later.

`GET /metrics` may be added when a Prometheus-compatible exporter or equivalent monitoring path exists.

## Provider Operations

Provider integrations should be adapter-based and fixture-testable. Live provider calls should be opt-in for tests and evals.

Operational rules:

- Respect provider terms and legal constraints.
- Store provider response metadata for debugging and evals.
- Use explicit timeouts and content limits.
- Fetch static pages with the configured CartCart user agent and HTML accept policy. Redirects are followed, but blocked, rate-limited, non-HTML, oversized, and other unsuccessful responses are not persisted as raw snapshots.
- Handle rate limits with clear user-safe errors.
- Keep SerpApi and other shopping-specific providers optional.
- Do not assume all YouTube videos have accessible transcripts.
- Keep `YtDlpTranscriptProvider` explicitly configured and disabled by default. It uses pinned `yt-dlp[default]==2026.6.9`, `yt-dlp-ejs==0.8.0`, and locked Deno `2.8.1` (minimum `2.3.0`).
- Never pass agent-supplied yt-dlp arguments, use cookies/accounts, allow runtime-downloaded EJS components, or download video/audio for transcript retrieval.
- Bound transcript subprocess time, process output, caption/temp storage, and normalized segment count; always delete temporary caption files.
- Preserve unavailable, restricted, rate-limited, challenge-failed, and no-caption outcomes as explicit metadata-only evidence gaps.
- Treat Reddit/community evidence as qualitative and source-context dependent; do not use private, deleted, logged-in-only, or otherwise inaccessible content.
- Treat Amazon evidence as marketplace/listing-specific. Preserve seller/fulfillment, variant, review, and regional availability context, and do not add affiliate behavior.
- Treat IKEA evidence as country/region-specific official-source evidence. Do not infer global shipping from global brand presence.

## Privacy And Safety Direction

MVP should avoid storing cross-session preference profiles. Persist local evidence and intermediate outputs only for session continuity, auditing, debugging, and evaluation.

Cross-session preference profiling is explicitly out of scope for MVP. CartCart may persist session-local briefs, candidates, evidence, and result artifacts for continuity and reproducibility, but it must not build durable per-user preference profiles across sessions. The settings module rejects `CARTCART_CROSS_SESSION_PREFERENCE_PROFILING_ENABLED=true`.

Logs and traces should avoid secrets and should not include full sensitive source content by default. Environment variables and provider keys must not be committed.

Seller/listing legitimacy is operationally important. Suspicious deterministic flags should not be silently overridden by agent output, and user-visible warnings should be preserved where they materially affect buying safety.
