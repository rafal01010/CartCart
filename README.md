# CartCart

CartCart is a shopping discovery, comparison, and decision app.

It is meant to help answer:

> What should I buy, and am I about to buy the wrong thing?

CartCart is not intended to be only a product recommendation app, a price comparison site, or a shopping search box. The goal is to help a shopper understand their needs, discover good candidates, compare tradeoffs, and avoid bad purchases.

## Current Status

CartCart currently has a local, fixture-first full-stack workflow. The backend is a FastAPI app with SQLite persistence, migrations, health/readiness endpoints, typed API routes, fixture guided-intake endpoints, a shopping-run orchestrator with provider-backed discovery, extraction, reusable source-intelligence stages, and opt-in live-agent workflow support, plus exported OpenAPI docs. The SvelteKit frontend now opens on a dark, focused "Send your question" homepage with a large textbox, rotating starter questions, local one-time region setup, and a backend-wired guided fixture intake flow. User-safe progress and staged result reveal are still follow-up work.

The default local workflow does not require live provider credentials, live reusable source intelligence agents, live OpenAI model calls, affiliate links, or production deployment. Search, extraction, YouTube/video metadata, transcripts, Reddit/community evidence, Amazon product/listing/review evidence, and IKEA regional store evidence stay behind explicit provider boundaries and default to fixture behavior. YouTube transcript availability is not assumed; failed or unavailable captions become evidence gaps. Reddit remains qualitative, Amazon remains marketplace/listing-specific, and IKEA availability remains region-specific. Live normal shopping runs require `CARTCART_AGENT_WORKFLOW_MODE=live`, `CARTCART_LIVE_AGENTS_ENABLED=true`, and a local `OPENAI_API_KEY`; each stage records trace IDs, timing, sanitized tool activity, model names where applicable, and nullable usage/cost fields.

## Product Direction

CartCart is intended to start from a natural-language shopping goal, such as:

- "I want a monitor for coding and movies."
- "I need wireless headphones under a certain budget."
- "I want an office chair that is actually worth it."
- "Here is a product I already know about. Compare it against better options."

Over time, the app should then help with:

- understanding the user's needs, constraints, budget, and region
- finding relevant products
- building an app-generated shortlist
- letting the user add products they already know about
- comparing the generated shortlist plus user-added products
- identifying a best pick, runner-ups, and meaningful alternatives
- warning about weak, suspicious, or poor-fit listings
- using useful source evidence, including product pages, reviews, video reviews, Reddit/community discussions, Amazon product/listing/review signals, and region-aware official-store evidence such as IKEA where available

## Product Principles

CartCart should be calm, analytical, and decision-oriented.

It should help users avoid:

- buying the wrong product
- overpaying for features that do not matter
- trusting suspicious sellers or listings
- missing better-value options
- relying on shallow or low-quality search results

## Repository Layout

```text
apps/
  backend/       Python/FastAPI backend.
  frontend/      SvelteKit frontend.
docs/            Public architecture, API, evaluation, operations, UX, and decision docs.
scripts/
  local/         Local developer workflow scripts.
data/            Local SQLite database and bulky runtime artifacts; do not commit.
AGENTS.md        Contributor and agent working rules.
supported_agents.md
README.md
```

`data/` is created by local persistence workflows when needed. By default, the SQLite database lives at `data/cartcart.sqlite3`.

Backend configuration is loaded from `CARTCART_*` environment variables and optional local overrides in `apps/backend/.env`. Frontend local overrides can live in `apps/frontend/.env`. Start from `apps/backend/.env.example` if you need local path or runtime-mode overrides. No real secrets are required for the current fixture workflow. See `docs/PROVIDERS.md` before enabling live providers or recording fixtures.

## Run Locally

Use the committed `.sh` scripts under `scripts/local/` for setup, migrations, lifecycle management, and verification.

Prerequisites:

- `uv` for backend dependency management.
- Node.js and `pnpm` on `PATH` for frontend dependency management. If Node.js provides Corepack, run `corepack enable`, `corepack prepare pnpm@latest --activate`, and confirm with `pnpm --version`.

From a fresh checkout:

```sh
scripts/local/init-backend.sh
scripts/local/init-frontend.sh
scripts/local/migrate-backend.sh
scripts/local/start-app.sh
```

Then open `http://127.0.0.1:5173`.

For an existing checkout after dependencies are already installed:

```sh
scripts/local/sync-backend.sh
scripts/local/sync-frontend.sh
scripts/local/migrate-backend.sh
scripts/local/start-app.sh
```

Use these lifecycle scripts while manually testing:

- `scripts/local/start-app.sh` starts backend and frontend together.
- `scripts/local/stop-app.sh` stops both managed processes.
- `scripts/local/restart-app.sh` restarts both managed processes.
- `scripts/local/start-backend.sh` starts only the FastAPI backend on `127.0.0.1:8000` by default.
- `scripts/local/start-frontend.sh` starts only the SvelteKit dev server on `127.0.0.1:5173` by default.

Lifecycle scripts write PID files to `data/run/` and logs to `data/logs/` by default. Override bind addresses and ports with `CARTCART_BACKEND_HOST`, `CARTCART_BACKEND_PORT`, `CARTCART_FRONTEND_HOST`, and `CARTCART_FRONTEND_PORT`; override PID and log directories with `CARTCART_RUN_DIR` and `CARTCART_LOG_DIR`.

The backend can create sessions, guide staged intake, execute fixture or explicitly configured live-agent runs, stream stage progress, persist reusable source-intelligence evidence bundles, and return the latest recommendation bundle with trust notes, warnings, mode results, and source evidence links. The current frontend starts from guided intake and can begin fixture analysis after the backend reaches ready-for-analysis; later guided-flow work will add user-safe progress and staged results without restoring the obsolete workspace.

## Verification

Common local checks:

- `scripts/local/lint-backend.sh`
- `scripts/local/typecheck-backend.sh`
- `scripts/local/test-backend.sh`
- `scripts/local/lint-frontend.sh`
- `scripts/local/check-frontend.sh`
- `scripts/local/test-frontend.sh`
- `scripts/local/build-frontend.sh`
- `scripts/local/setup-playwright.sh`
- `pnpm --dir apps/frontend run test:e2e`

Run `scripts/local/setup-playwright.sh` once before the Playwright smoke test on a machine that does not already have the browser binaries installed. See `docs/OPERATIONS.md` for the full script reference, database reset command, cleanup command, and lifecycle environment variables.

## Project Docs

- `docs/ARCHITECTURE.md` - architecture and behavior rules.
- `docs/API.md` - intended API shape.
- `docs/DATABASE.md` - current SQLite schema, tables, indexes, and artifact boundary.
- `docs/EVALUATION.md` - evaluation and testing strategy.
- `docs/OPERATIONS.md` - local operations assumptions.
- `docs/PROVIDERS.md` - provider boundaries, live setup, fixture replay, compliance, and artifact safety.
- `docs/WORKFLOW.md` - current fixture-first workflow, opt-in live-agent mode, run lifecycle, event emission, and result versioning.
- `docs/UX.md` - desktop-first product surface guidance.
- `docs/FRONTEND_REPLACEMENT.md` - audit and replacement plan for the guided Svelte frontend.
- `docs/DECISIONS.md` - accepted and pending decisions.
- `supported_agents.md` - human-editable agent and reusable source-capability intent.
