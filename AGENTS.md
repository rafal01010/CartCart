# AGENTS.md

## Project

CartCart is a shopping discovery, comparison, and decision web application. It helps users decide what to buy, compare generated and user-added candidates, and avoid bad or suspicious purchases.
Keep in mind that this is a project that will be used by regular people and not by developers who already has information on what the project is about and what it does and how it works.
The user interface should not expose information that will not make sense to a regular person who has no developer experience. We should try and hide parts of the process that a user doesn't need to see unless there's a benefit of doing so.


## Working Rules

- Prefer small, verifiable implementation milestones.
- Keep public docs updated when architecture, API contracts, evals, or operations change.
- Use a Python backend, SvelteKit frontend, and OpenAI Agents SDK unless the project owner explicitly changes direction.
- Preserve broad category support with specialist fallback rather than hard-coding one product category.
- Treat seller/listing legitimacy as a first-class analysis concern.
- Keep local persistence and observability in scope for MVP.
- Do not add affiliate or monetization logic unless explicitly requested.
- Keep neutral outbound product links.

## Expected Docs

- `supported_agents.md`
- `docs/ARCHITECTURE.md`
- `docs/API.md`
- `docs/EVALUATION.md`
- `docs/OPERATIONS.md`

When adding, removing, moving, or changing fallback behavior for an agent or reusable source capability, update `supported_agents.md`, the runtime agent catalog once it exists, related routing tests, provider fixtures where relevant, and relevant eval cases together.




Before implementing features, read DESIGN.md.

Follow DESIGN.md for:

- app architecture

- folder structure

- major feature behavior

- backend/frontend boundaries

- agent hierarchy

- database/storage decisions

If DESIGN.md conflicts with this file, ask before changing architecture.