# CartCart

CartCart is a shopping discovery, comparison, and decision app. It helps answer:

> What should I buy, and am I about to buy the wrong thing?

A shopper can start with a request like:

- "I want a monitor for coding and movies."
- "I need wireless headphones under a certain budget."
- "Here's a product I'm considering. How does it compare with other options?"

CartCart asks a few focused questions, then helps the shopper:

- Find relevant products and compare them with any products they added.
- Weigh tradeoffs, prices, and source evidence to choose a best pick or recognize when there is no strong buy.
- Spot poor fits and suspicious sellers or listings.

After a result, shoppers can adjust their budget, buying region, product category, or priorities and review earlier decisions in the same session.

This helps shoppers avoid overpaying, missing better options, and trusting weak search results.

The SvelteKit frontend provides the guided shopping flow. A Python/FastAPI backend handles research, analysis, the API, and local SQLite persistence. The default local workflow uses fixtures and needs no provider or model credentials; live research is opt-in.

## Repository Layout

```text
apps/
  backend/       FastAPI backend and database migrations.
  frontend/      SvelteKit frontend.
docs/            Architecture, API, workflow, and other project references.
scripts/local/   Setup and app lifecycle scripts.
data/            Generated SQLite database, logs, and runtime artifacts.
AGENTS.md        Contributor and agent working rules.
supported_agents.md
README.md
```

`data/` is created as needed and is not committed. The default database is `data/cartcart.sqlite3`.

## Run Locally

Install `uv`, Node.js, and `pnpm`, then run from the repository root:

```sh
scripts/local/init-backend.sh
scripts/local/init-frontend.sh
scripts/local/migrate-backend.sh
scripts/local/start-app.sh
```

Open <http://127.0.0.1:5173>. Stop the app with `scripts/local/stop-app.sh`. After dependency changes, use `scripts/local/sync-backend.sh` or `scripts/local/sync-frontend.sh` to update the corresponding local environment.

Local backend settings can go in `apps/backend/.env`; start from `apps/backend/.env.example` when overrides are needed. Frontend overrides can go in `apps/frontend/.env`. The default fixture workflow works without secrets. See [Provider setup](docs/PROVIDERS.md) before enabling live providers or models, and [Operations](docs/OPERATIONS.md) for scripts and configuration.

## Project Docs

- [Architecture](docs/ARCHITECTURE.md) — system structure and behavior rules.
- [API](docs/API.md) — endpoints and data contracts.
- [Workflow](docs/WORKFLOW.md) — shopping run stages and result lifecycle.
- [Database](docs/DATABASE.md) — SQLite schema and stored artifacts.
- [UX](docs/UX.md) — guided shopping flow and result presentation.
- [Providers](docs/PROVIDERS.md) — external sources, fixture behavior, and live setup.
- [Operations](docs/OPERATIONS.md) — local scripts and runtime configuration.
- [Evaluation](docs/EVALUATION.md) — testing and evaluation strategy.
- [Decisions](docs/DECISIONS.md) — accepted and pending project decisions.
- [Supported agents](supported_agents.md) — agent roles, routing, and source capabilities.
