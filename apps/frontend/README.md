# CartCart Frontend

SvelteKit TypeScript scaffold for the CartCart frontend.

The frontend uses Tailwind CSS through the Vite plugin, shadcn-svelte project
configuration, copied local UI components under `src/lib/components/ui`, and
Bits UI headless primitives for accessible interaction building blocks.

## Setup

From the repository root:

```sh
scripts/local/init-frontend.sh
```

This script creates the SvelteKit project when needed and installs dependencies with `pnpm`.

To refresh an existing frontend install from the lockfile:

```sh
scripts/local/sync-frontend.sh
```

## API Configuration

The browser client defaults to `http://127.0.0.1:8000`.

Override it for local development with:

```sh
PUBLIC_CARTCART_API_BASE_URL=http://127.0.0.1:8000 pnpm --dir apps/frontend dev
```

Hand-written API types live under `src/lib/api` until OpenAPI type generation is added.

The first route can create a persisted shopping session through the backend
`POST /api/sessions` endpoint. After creation, the route stores the session ID in
the `session` URL query parameter so refreshing the page reloads the saved
session state.

The user-added product controls persist URL placeholders and manual product
details through `POST /api/sessions/{session_id}/products`. The route renders the
returned `user_added_products` from session state and clears stale run/result
state so the next stub run starts from the updated session.

The refinement controls submit category, region, budget, and preference
corrections through `POST /api/sessions/{session_id}/refinements`. The returned
refinement run is shown in the workspace, the run timeline subscribes to its SSE
events, and the current result version/run is shown when the latest fixture
result loads.

The workspace state band covers no session, loading, no result, run in progress,
failed run, partial data, weak evidence, conflicting signals, warning/red-flag
results, and API errors. Most states are derived from fixture data or mocked
frontend data until later live-provider workflows exist.

With a saved session, the route can start the fixture run through
`POST /api/sessions/{session_id}/runs` and display stage progress from the run
events SSE endpoint. When the run completes, it fetches
`GET /api/sessions/{session_id}/results` and renders the fixture recommendation
bundle, including modes, runner-ups, trust notes, warnings, meaningful why-not
items, and source evidence links.

## Developing

```sh
pnpm --dir apps/frontend dev
```

## Checking

```sh
pnpm --dir apps/frontend check
```

Focused API client unit test:

```sh
pnpm --dir apps/frontend exec vitest run src/lib/api/client.test.ts
```

Focused user-added product form test:

```sh
pnpm --dir apps/frontend exec vitest run src/lib/user-products/user-product-form.test.ts
```

Focused refinement form test:

```sh
pnpm --dir apps/frontend exec vitest run src/lib/refinements/refinement-form.test.ts
```

Focused workspace state test:

```sh
pnpm --dir apps/frontend exec vitest run src/lib/workspace-states/workspace-states.test.ts
```

Focused result view unit test:

```sh
pnpm --dir apps/frontend exec vitest run src/lib/results/result-view.test.ts
```

## Building

```sh
pnpm --dir apps/frontend build
```
