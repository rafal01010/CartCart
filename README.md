# CartCart

CartCart is a shopping discovery, comparison, and decision app.

It is meant to help answer:

> What should I buy, and am I about to buy the wrong thing?

CartCart is not intended to be only a product recommendation app, a price comparison site, or a shopping search box. The goal is to help a shopper understand their needs, discover good candidates, compare tradeoffs, and avoid bad purchases.

## Current Status

The repository is in early setup. The monorepo skeleton exists, but the backend, frontend, dependencies, runtime scripts, and local app workflow have not been scaffolded yet.

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
data/            Future local SQLite database and bulky runtime artifacts; do not commit.
AGENTS.md        Contributor and agent working rules.
supported_agents.md
README.md
```

`data/` is not created yet. It is reserved for local persistence and artifacts once the backend reaches that milestone.

## Local Workflow

There are no setup, install, start, test, or verification scripts yet. When those workflows are added, use committed scripts under `scripts/local/` rather than ad hoc commands.

Script conventions:

- Use `.sh` files with explicit names such as `init-backend.sh`, `sync-frontend.sh`, or `start-app.sh`.
- Keep scripts small and composable.
- Make scripts runnable from a clean checkout by resolving paths from the repository root or script location.
- Prefer strict shell options such as `set -euo pipefail`.
- Document new scripts in this README or `docs/OPERATIONS.md` when they become useful.

## Project Docs

- `docs/ARCHITECTURE.md` - architecture and behavior rules.
- `docs/API.md` - intended API shape.
- `docs/EVALUATION.md` - evaluation and testing strategy.
- `docs/OPERATIONS.md` - local operations assumptions.
- `docs/UX.md` - desktop-first product surface guidance.
- `docs/DECISIONS.md` - accepted and pending decisions.
- `supported_agents.md` - human-editable agent and source-capability intent.
