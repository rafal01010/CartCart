# CartCart

CartCart is a shopping discovery, comparison, and decision app.

It is meant to help answer:

> What should I buy, and am I about to buy the wrong thing?

CartCart is not intended to be only a product recommendation app, a price comparison site, or a shopping search box. The goal is to help a shopper understand their needs, discover good candidates, compare tradeoffs, and avoid bad purchases.

## Current Status

The repository is in early setup. The backend can start locally, exposes health/readiness endpoints, and has local SQLite persistence/migrations for the current backend data model. Product API behavior, live agents, and frontend scaffolding have not been implemented yet.

## What CartCart Should Do

CartCart starts from a natural-language shopping goal, such as:

- "I want a monitor for coding and movies."
- "I need wireless headphones under a certain budget."
- "I want an office chair that is actually worth it."
- "Here is a product I already know about. Compare it against better options."

The app should then help with:

- understanding the user's needs, constraints, budget, and region
- finding relevant products
- building an app-generated shortlist
- letting the user add products they already know about
- comparing the generated shortlist plus user-added products
- identifying a best pick, runner-ups, and meaningful alternatives
- warning about weak, suspicious, or poor-fit listings
- using useful source evidence, including product pages, reviews, and video reviews where available

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
  backend/       Python/FastAPI backend will live here.
  frontend/      SvelteKit frontend will live here.
docs/            Public architecture, API, evaluation, operations, UX, and decision docs.
scripts/
  local/         Local developer workflow scripts will live here.
data/            Local SQLite database and bulky runtime artifacts; do not commit.
AGENTS.md        Contributor and agent working rules.
supported_agents.md
README.md
```

`data/` is created by local persistence workflows when needed. By default, the SQLite database lives at `data/cartcart.sqlite3`.

Backend configuration is loaded from `CARTCART_*` environment variables and optional local overrides in `apps/backend/.env`. Start from `apps/backend/.env.example` if you need local path or runtime-mode overrides. No real secrets are required yet.

## Local Workflow

Use committed scripts under `scripts/local/` for repeatable local setup and operations rather than ad hoc commands.

Current scripts:

- `scripts/local/init-backend.sh` initializes the backend Python project in `apps/backend` if needed, then syncs dependencies. Run it after a fresh checkout before backend work.
- `scripts/local/sync-backend.sh` syncs the backend environment from `apps/backend/pyproject.toml` and `apps/backend/uv.lock`. Run it after backend dependency metadata changes, when `apps/backend/.venv` is missing or stale, and before backend verification commands if dependencies may have changed.
- `scripts/local/start-backend.sh` starts the local FastAPI backend. Run it when you want to manually exercise the backend API, such as checking `GET /healthz` or `GET /readyz`.
- `scripts/local/reset-db.sh --yes` deletes the configured local SQLite database and sidecar files. Run it when you need a clean local database before rerunning Alembic migrations.
- `scripts/local/cleanup-artifacts.sh --yes` deletes local artifact files according to configured retention windows. Run it when raw snapshots, extracted content, screenshots, traces, or eval outputs should be cleaned.

Dedicated lint, type-check, test, stop, full-app startup, and frontend setup scripts will be added when those workflows exist.

Script conventions:

- Use `.sh` files with explicit names such as `init-backend.sh`, `sync-frontend.sh`, or `start-app.sh`.
- Keep scripts small and composable.
- Make scripts runnable from a clean checkout by resolving paths from the repository root or script location.
- Prefer strict shell options such as `set -euo pipefail`.
- Document new scripts in this README or `docs/OPERATIONS.md` when they become useful.

## Project Docs

- `docs/ARCHITECTURE.md` - architecture and behavior rules.
- `docs/API.md` - intended API shape.
- `docs/DATABASE.md` - current SQLite schema, tables, indexes, and artifact boundary.
- `docs/EVALUATION.md` - evaluation and testing strategy.
- `docs/OPERATIONS.md` - local operations assumptions.
- `docs/UX.md` - desktop-first product surface guidance.
- `docs/DECISIONS.md` - accepted and pending decisions.
- `supported_agents.md` - human-editable agent and source-capability intent.
