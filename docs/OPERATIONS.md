# CartCart Operations

Status: Initial local operations assumptions for planning
Last updated: 2026-05-30

## Local MVP Assumptions

The MVP is local-first:

- One local user.
- No authentication or account system.
- Local SQLite persistence.
- Local file artifacts under `data/` when needed.
- No cross-session user preference profiling.
- External search, extraction, model, and source-intelligence providers are configured explicitly by environment variables when implementation reaches those milestones.

The initial monorepo skeleton exists under `apps/backend`, `apps/frontend`, `docs`, and `scripts/local`. The backend Python project can be initialized with `scripts/local/init-backend.sh`, synced with `scripts/local/sync-backend.sh`, started with `scripts/local/start-backend.sh`, reset with `scripts/local/reset-db.sh`, cleaned with `scripts/local/cleanup-artifacts.sh`, and migrated with Alembic from `apps/backend`. Frontend, stop/restart, migration wrapper, and full-app lifecycle scripts have not been scaffolded yet, so the rest of this document describes intended operational direction where implementation has not reached a runnable command.

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

`scripts/local/reset-db.sh --yes` deletes the configured local SQLite database file plus SQLite sidecar files (`-journal`, `-shm`, and `-wal`). It reads `apps/backend/.env` when present and respects `CARTCART_DATABASE_PATH` or `CARTCART_DATA_DIR`.

Run it:

- when local persistence needs a clean schema/data reset
- before rerunning migrations from scratch against the default local database

`scripts/local/cleanup-artifacts.sh --yes` deletes local artifact files according to the configured retention windows. It reads `apps/backend/.env` when present and respects `CARTCART_ARTIFACT_DIR`, `CARTCART_DATA_DIR`, and the artifact retention settings.

Run it:

- before live-provider development if previous raw snapshots, extraction outputs, traces, or eval artifacts should be cleaned
- periodically during local development to control disk usage

Do not use setup/sync scripts as test checkpoint commands. Dedicated lint, type-check, test, stop/restart, and full-app lifecycle scripts will be added with the backend and frontend milestones that need them.

## Database Migrations

Alembic is configured in `apps/backend/alembic.ini` and uses the backend settings module to resolve the SQLite path. By default, migrations create or update the repository-level `data/cartcart.sqlite3` database. The current schema reference lives in `docs/DATABASE.md`.

The current pre-release migration history is squashed into one initial persistence baseline. If a local database was created from the earlier task-by-task migration chain, reset it before applying the current baseline.

Run migrations from the backend project directory:

```sh
cd apps/backend
uv run alembic -c alembic.ini upgrade head
```

Override `CARTCART_DATABASE_PATH` or `CARTCART_DATA_DIR` to migrate a different local SQLite database. Use absolute paths for overrides.

Reset the default local database and rebuild the schema:

```sh
scripts/local/reset-db.sh --yes
cd apps/backend
uv run alembic -c alembic.ini upgrade head
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
- `CARTCART_RAW_SOURCE_SNAPSHOT_RETENTION_DAYS`: retention window for raw source snapshots. Defaults to `30`.
- `CARTCART_EXTRACTED_CONTENT_RETENTION_DAYS`: retention window for extracted text/Markdown. Defaults to `30`.
- `CARTCART_SCREENSHOT_RETENTION_DAYS`: retention window for optional screenshots. Defaults to `7`.
- `CARTCART_AGENT_OUTPUT_RETENTION_DAYS`: retention window for bulky agent output artifacts. Defaults to `30`.
- `CARTCART_TRACE_RETENTION_DAYS`: retention window for local trace export files. Defaults to `14`.
- `CARTCART_EVAL_ARTIFACT_RETENTION_DAYS`: retention window for eval output artifacts. Defaults to `30`.
- `CARTCART_SCREENSHOTS_ENABLED`: enables optional screenshot capture when a later provider/extraction workflow supports it. Defaults to `false`.
- `CARTCART_CROSS_SESSION_PREFERENCE_PROFILING_ENABLED`: must remain `false` for MVP. Attempts to set it to `true` are rejected by settings validation.

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

Current persistence implementation stores shopping sessions in SQLite with the original session request, original query, current shopping brief, and create/update timestamps. It also stores shopping runs and ordered run events so the latest run status can be loaded from the run record while the event history remains inspectable. Search plans, search results, source snapshots, and source evidence are stored with run links and provider metadata.

Lookup indexes currently cover session/run relationships, ordered run events, source and product URLs, provider names and provider result/query IDs, video/source/product/listing target IDs, product brand/model/category identifiers, agent record names/stages/trace IDs, and result version lookup by run/version.

Video review evidence persistence stores video sources, transcript availability, permitted transcript segments or explicit transcript gaps, channel metadata, source-backed video evidence bundles, and link metadata for run IDs, source snapshot IDs, target product/listing/candidate IDs, and future recommendation claim IDs.

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

Cross-session preference profiling is explicitly out of scope for MVP. CartCart may persist session-local briefs, candidates, evidence, and result artifacts for continuity and reproducibility, but it must not build durable per-user preference profiles across sessions. The settings module rejects `CARTCART_CROSS_SESSION_PREFERENCE_PROFILING_ENABLED=true`.

Logs and traces should avoid secrets and should not include full sensitive source content by default. Environment variables and provider keys must not be committed.

Seller/listing legitimacy is operationally important. Suspicious deterministic flags should not be silently overridden by agent output, and user-visible warnings should be preserved where they materially affect buying safety.
