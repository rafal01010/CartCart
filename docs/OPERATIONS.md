# CartCart Operations

Status: Initial local operations assumptions for planning
Last updated: 2026-05-29

## Local MVP Assumptions

The MVP is local-first:

- One local user.
- No authentication or account system.
- Local SQLite persistence.
- Local file artifacts under `data/` when needed.
- No cross-session user preference profiling.
- External search, extraction, model, and source-intelligence providers are configured explicitly by environment variables when implementation reaches those milestones.

The initial monorepo skeleton exists under `apps/backend`, `apps/frontend`, `docs`, and `scripts/local`. The backend Python project can be initialized with `scripts/local/init-backend.sh`, synced with `scripts/local/sync-backend.sh`, and started with `scripts/local/start-backend.sh`. Frontend, stop/restart, and full-app lifecycle scripts have not been scaffolded yet, so the rest of this document describes intended operational direction where implementation has not reached a runnable command.

## Current Local Scripts

`scripts/local/init-backend.sh` initializes `apps/backend/pyproject.toml` when it is missing, pins the backend to Python 3.12, and delegates dependency installation to `scripts/local/sync-backend.sh`.

Run it:

- after a fresh checkout before backend development

`scripts/local/sync-backend.sh` syncs the backend environment from `apps/backend/pyproject.toml` and `apps/backend/uv.lock`.

Run it:

- after backend dependency metadata changes
- when `apps/backend/.venv` is missing or stale
- before backend verification commands if dependencies may have changed

`scripts/local/start-backend.sh` starts the local FastAPI backend with Uvicorn. It reads shell environment variables and `apps/backend/.env` when present.

Run it:

- when manually checking backend endpoints such as `GET /healthz` and `GET /readyz`
- when a later frontend or integration step needs the backend running locally

Do not use setup/sync scripts as test checkpoint commands. Dedicated lint, type-check, test, stop/restart, and full-app lifecycle scripts will be added with the backend and frontend milestones that need them.

## Expected Services

Backend:

- FastAPI application.
- SQLite database.
- Alembic migrations.
- Structured JSON logs.
- OpenTelemetry instrumentation.
- Optional Logfire or another OpenTelemetry backend for local development.

Frontend:

- SvelteKit development server.
- TypeScript checks and frontend tests once implemented.

Later local deployment-like operation may add Docker Compose, persistent volumes, and release scripts.

## Configuration Direction

Backend configuration is loaded through typed settings from environment variables and optional local overrides in `apps/backend/.env`. Use `apps/backend/.env.example` as the safe placeholder template. Do not commit `apps/backend/.env`.

Current backend variables:

- `CARTCART_ENVIRONMENT`: runtime mode. Allowed values are `local`, `test`, `fixture`, `live`, and `production`. Defaults to `local`.
- `CARTCART_BACKEND_HOST`: local backend bind host. Defaults to `127.0.0.1`.
- `CARTCART_BACKEND_PORT`: local backend bind port. Defaults to `8000`.
- `CARTCART_BACKEND_RELOAD`: local startup reload toggle used by `scripts/local/start-backend.sh`. Defaults to `true`.
- `CARTCART_LOG_LEVEL`: backend structured log level. Defaults to `INFO`.
- `CARTCART_FRONTEND_ORIGINS`: JSON array of allowed frontend origins for CORS. Defaults to local SvelteKit origins.
- `CARTCART_TELEMETRY_ENABLED`: enables OpenTelemetry FastAPI instrumentation when `true`. Defaults to `false`.
- `CARTCART_TELEMETRY_EXPORTER`: telemetry exporter. Allowed values are `console` and `otlp`. Defaults to `console`.
- `CARTCART_TELEMETRY_SERVICE_NAME`: OpenTelemetry service name. Defaults to `cartcart-backend`.
- `CARTCART_TELEMETRY_OTLP_ENDPOINT`: OTLP HTTP traces endpoint for a local collector. Defaults to `http://127.0.0.1:4318/v1/traces`.
- `CARTCART_DATA_DIR`: local data directory. Defaults to the repository-level `data/` directory.
- `CARTCART_DATABASE_PATH`: SQLite database path. Defaults to `data/cartcart.sqlite3`.
- `CARTCART_ARTIFACT_DIR`: local artifact directory. Defaults to `data/artifacts`.

No real secrets are required for the current backend settings. The project owner only needs to set these variables manually when overriding local paths or runtime mode. Use absolute paths for local path overrides. Provider and model keys will be introduced in later milestones and must be supplied locally by the project owner rather than committed.

Future configuration areas include:

- OpenAI API key and model settings.
- OpenAI Agents SDK tracing options.
- Search provider keys and enabled-provider flags.
- Extraction provider options and timeouts.
- Optional YouTube/video provider keys and transcript strategy.
- Telemetry enabled/disabled flag.
- Logfire or OTEL exporter settings.
- Provider timeout and rate-limit settings.
- Artifact retention settings.

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

- HTML snapshots.
- Extracted Markdown.
- Screenshots if used.
- Trace exports.
- Eval exports.

Before live provider use, retention and deletion rules should be documented for large artifacts and sensitive source content.

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

The current baseline instruments FastAPI requests only. OpenAI Agents SDK traces, workflow-stage spans, provider spans, database spans, metrics, and Logfire wiring are later observability work.

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

`GET /readyz` currently reports configuration readiness. Database availability and configured provider readiness will be added when persistence and provider milestones exist. Optional providers should be reported as disabled or warning states when not configured.

`GET /metrics` may be added when a Prometheus-compatible exporter or equivalent monitoring path exists.

## Provider Operations

Provider integrations should be adapter-based and fixture-testable. Live provider calls should be opt-in for tests and evals.

Operational rules:

- Respect provider terms and legal constraints.
- Store provider response metadata for debugging and evals.
- Use explicit timeouts and content limits.
- Handle rate limits with clear user-safe errors.
- Keep SerpApi and other shopping-specific providers optional.
- Do not assume all YouTube videos have accessible transcripts.
- Treat unofficial transcript providers as optional and explicitly configured if ever used.

## Privacy And Safety Direction

MVP should avoid storing cross-session preference profiles. Persist local evidence and intermediate outputs only for session continuity, auditing, debugging, and evaluation.

Logs and traces should avoid secrets and should not include full sensitive source content by default. Environment variables and provider keys must not be committed.

Seller/listing legitimacy is operationally important. Suspicious deterministic flags should not be silently overridden by agent output, and user-visible warnings should be preserved where they materially affect buying safety.
