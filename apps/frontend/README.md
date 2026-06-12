# CartCart Frontend

SvelteKit TypeScript scaffold for the CartCart frontend.

The one-page workspace route has been replaced by a focused prompt-first
homepage following `../../DESIGN.md`. The first screen shows "Send your
question", a large natural-language textbox, rotating starter questions outside
the textbox, and local one-time region setup after first submit when no saved or
refused region exists. The guided intake flow creates a backend guided session,
asks one current fixture question at a time,
supports inline choices, Back/reanswer, `Skip question`, and `Skip all and start
analysis`, and avoids visible chat history.
Backend session, run, result, source evidence, user-considered product, and
refinement helpers remain in `src/lib` so guided screens can use existing
plumbing without restoring the old dashboard.

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

Hand-written API types live under `src/lib/api` until OpenAPI type generation is
added. The current route calls the guided fixture API for first-question session
creation, backend region submission, guided answers, skip/reanswer actions,
blocked guardrails, readiness, and starting the fixture analysis after readiness.
After analysis starts, the route subscribes to the existing SSE run events but
renders only shopper-safe progress labels, then reveals the recommendation first
with runner-ups, trust notes, warnings, and source details behind explicit
supporting-detail controls.
User-considered products are captured as product names or descriptions through
guided answers, not through a URL/manual entry panel. Budget, region, and
category changes appear as contextual prompts from the ready screen and submit
through the existing refinement endpoint.

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

Focused local region setup unit test:

```sh
pnpm --dir apps/frontend exec vitest run src/lib/guided/local-region.test.ts
```

Focused guided intake state test:

```sh
pnpm --dir apps/frontend exec vitest run src/lib/guided/guided-state.test.ts
```

Focused user-considered product prompt test:

```sh
pnpm --dir apps/frontend exec vitest run src/lib/user-products/contextual-product-prompt.test.ts
```

Focused contextual refinement prompt test:

```sh
pnpm --dir apps/frontend exec vitest run src/lib/refinements/contextual-refinement-prompt.test.ts
```

Focused result view unit test:

```sh
pnpm --dir apps/frontend exec vitest run src/lib/results/result-view.test.ts
```

Focused guided Playwright smoke test:

```sh
pnpm --dir apps/frontend exec playwright test tests/e2e/guided-flow-smoke.spec.ts
```

## Building

```sh
pnpm --dir apps/frontend build
```
