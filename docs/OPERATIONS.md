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

The application has not been scaffolded yet. Commands in this document describe intended operational direction, not current runnable app commands.

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

Configuration should come from environment variables with typed settings in the backend. Expected configuration areas include:

- Environment mode.
- Backend host and port.
- Frontend origin for CORS.
- SQLite database path.
- Local artifact directory.
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

## Health And Readiness

`GET /healthz` should report process liveness and remain cheap.

`GET /readyz` should report database availability and configured provider readiness. Optional providers should be reported as disabled or warning states when not configured.

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

