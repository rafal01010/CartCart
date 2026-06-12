# Frontend Replacement Note

Status: Guided frontend rebuild gate passed
Last updated: 2026-06-12

## Purpose

The original SvelteKit one-page workspace proved useful backend plumbing, but
its dashboard-style UI is superseded. The root route now uses a dark focused
homepage prompt from `DESIGN.md`: "Send your question", a large natural-language
textbox, animated starter questions outside the textbox, and local one-time
region setup after first submit when no saved or refused region exists. It now
connects that guided intake surface to the backend fixture guided API: the
frontend submits the first shopping question, renders the current backend prompt
or inline control, submits answers, supports Back/reanswer, `Skip question`, and
`Skip all and start analysis`, handles provided/refused region setup, and shows
short user-safe guardrail blocks. Future frontend work should build on this
session, guided-intake, run, result, source, and refinement plumbing without
restoring the all-in-one workspace.

## Visual And Interaction References

- `DESIGN.md` is the visual system reference: near-black canvas, restrained
  monochrome surfaces, compact typography, subtle borders/shadows, and one
  primary action per screen.
- `sample_screenshots/sample_gemini_homepage.png` is the primary interaction
  composition reference for the homepage and most guided intake screens. Keep a
  stable prompt-like composition where the displayed question changes while the
  rest of the surface remains calm and focused.
- `sample_screenshots/linear_app1.png` and
  `sample_screenshots/linear_app2.png` are supporting references for dark
  spacing, quiet navigation, subtle dividers, and restrained product/result
  surfaces.
- `docs/UX.md` is the acceptance checklist for user-facing behavior.

The homepage starter-question animation currently uses Svelte state plus a small
CSS transition. No Lottie dependency was added in the homepage pass; any later
Lottie work should use a Svelte-compatible player and must not introduce a
React-only path.

## Current Frontend State

The main route at `apps/frontend/src/routes/+page.svelte` has been replaced with
a focused "Send your question" surface. It keeps the first screen dark,
prompt-led, and free of visible session/run/result mechanics. Region setup is
cached locally, but the selected or refused value is also sent to the guided
fixture API. The current guided sequence comes from backend fixture state rather
than a frontend-only reducer:

1. First shopping question creates a guided backend session.
2. Missing local region setup pauses the visible flow and resumes the same
   session after the user provides or refuses a region.
3. Backend prompts can be textbox, yes/no inline choice, or justified
   two-option-plus-type-answer controls.
4. The combined optional prompt asks for budget, must-haves, or products already
   being considered by name or description in one textbox.
5. Ready-for-analysis appears only after the backend says enough information
   exists; the existing fixture analysis can then be started without exposing
   run IDs or developer mechanics.
6. User-considered products stay in the guided answer path as product names or
   descriptions; there is no normal-flow URL/manual product-entry panel.
7. Budget, region, and category changes open one contextual prompt from the
   ready screen and submit through the existing refinement endpoint without a
   permanent refinement panel.

The old 1,248-line workspace was removed. Its useful API, progress, and result
projection helpers remain under `src/lib` for later guided-flow wiring.

## Preserve

Keep these pieces unless a later implementation task discovers a direct
conflict:

| Area | Files | Reason |
| --- | --- | --- |
| API configuration and errors | `src/lib/api/config.ts`, `src/lib/api/errors.ts`, `src/lib/api/index.ts` | Backend URL and error handling stay useful. |
| HTTP and SSE client primitives | `src/lib/api/client.ts`, `src/lib/api/sse.ts` | Existing session/run/result endpoints and SSE progress remain useful plumbing. Add guided-intake methods here rather than creating a second client. |
| API type baseline | `src/lib/api/types.ts` | Keep existing run/session/result types and extend with generated or hand-written guided-intake types until OpenAPI generation replaces them. |
| Result projection helpers | `src/lib/results/result-view.ts` and tests | Useful after analysis completes, but should feed staged result surfaces rather than the homepage. |
| Run progress reducer | `src/lib/run-progress/run-progress.ts` and tests | Keep the reducer, but map output to user-safe progress copy and hide run IDs/stage mechanics in normal UI. |
| Button primitive | `src/lib/components/ui/button/*` | Keep as a base primitive and restyle in the Linear-inspired visual foundation. |
| Shared utilities | `src/lib/utils.ts`, app shell files | Keep unless replaced by the visual foundation task. |

## Rewrite Or Move Behind Guided Flow

These pieces contain useful transformation logic, but their current form
reinforces the old all-in-one workspace:

| Area | Files | Rebuild direction |
| --- | --- | --- |
| Session form state | `src/lib/session/session-form.ts` and tests | Split into first-question submission, local region setup, and guided answer helpers. Do not keep visible budget/region/preference fields on the homepage. |
| User-considered product prompt state | `src/lib/user-products/contextual-product-prompt.ts` and tests | Normal flow now accepts product names/descriptions. URL support should become advanced/corrective later, not a first-screen control. |
| Contextual refinement prompt state | `src/lib/refinements/contextual-refinement-prompt.ts` and tests | Budget, region, category, and preference changes are one-prompt contextual edits, not a permanent refinement form. |
| Workspace notices | `src/lib/workspace-states/workspace-states.ts` and tests | Replace with guided empty, blocked, region setup, current-question, ready, processing, and result states. |
| Card primitive | `src/lib/components/ui/card/*` | Restyled for the dark foundation. Avoid card-heavy page sections and nested cards. Use cards only for repeated result/source items or focused tools. |
| E2E smoke path | `tests/e2e/visual-foundation-smoke.spec.ts` | Covers the prompt-first guided fixture flow until the broader Task 53H smoke replaces it. |

## Delete Or Replace

Remove these UI patterns during the replacement:

- The all-in-one homepage/workspace layout.
- Always-visible shopping goal, region, budget, budget mode, and priorities
  form panels.
- Always-visible user-added product URL/manual entry panel.
- Always-visible refinement panel.
- First-screen progress timeline, result summaries, comparison tables, source
  drawer, and run/session metadata.
- User-facing labels such as `Create session`, `Start run`, `Run progress`,
  `Run {id}`, `Saved session`, `fixture`, `stage`, `agent`, `provider`, `trace`,
  or other developer/process language.
- Normal-flow product URL requests.
- Textbox placeholders containing example answers or suggested shopping
  questions.

Removed in the visual foundation pass:

- The all-in-one `+page.svelte` workspace implementation.
- The legacy `tests/e2e/stub-run-smoke.spec.ts` path that depended on workspace
  labels such as `Create session`, `Start run`, and `Run progress`.

## Guided Route Structure

Use a single primary SvelteKit route for the guided application experience:

```text
/
  homepage prompt
  one-time region setup when needed
  current guided question
  user-safe processing state
  staged recommendation result
```

Avoid a visible chat transcript and avoid adding a separate route per question.
The normal experience should update the current state in place.

Recommended frontend state shape:

```text
home
  no active question yet
region_setup
  missing local region/refusal, outside the main shopping flow
guiding
  one current question, answer surface, choices, skip/back controls
ready_for_analysis
  enough information exists; can start backend analysis
processing
  user-safe progress while preserving run plumbing internally
result
  staged recommendation and source details on demand
blocked
  short user-safe redirection for off-topic or unsafe requests
error
  recoverable API or network problem
```

Persist locally:

- Region value or explicit refusal.
- Pending first shopping question when region setup interrupts submission.
- Current session ID when useful for refresh recovery.

Keep internally but do not expose as the user's mental model:

- Session IDs.
- Run IDs.
- Run stages.
- Result versions.
- Source IDs.

## Planned Frontend Module Shape

The replacement can keep the existing `src/lib/api` and add guided modules:

```text
src/lib/guided/
  local-region.ts
  starter-questions.ts
  guided-state.ts
  copy.ts
src/lib/results/
  result-view.ts
src/lib/run-progress/
  run-progress.ts
src/routes/+page.svelte
```

Component extraction should happen only where it reduces real complexity. Good
initial candidates are:

- `PromptSurface.svelte`
- `RegionSetup.svelte`
- `GuidedQuestion.svelte`
- `InlineChoiceBlock.svelte`
- `ProcessingState.svelte`
- `RecommendationResult.svelte`

## Focused Checks For Replacement Tasks

For guided frontend changes, focused checks should prefer:

- `pnpm --dir apps/frontend exec vitest run src/lib/api/client.test.ts`
- `pnpm --dir apps/frontend exec vitest run src/lib/guided/guided-state.test.ts`
- `pnpm --dir apps/frontend exec vitest run src/lib/guided/local-region.test.ts`
- `pnpm --dir apps/frontend exec vitest run src/lib/results/result-view.test.ts`
- `pnpm --dir apps/frontend exec vitest run src/lib/run-progress/run-progress.test.ts`
- `pnpm --dir apps/frontend check`

The current route renders user-safe processing progress and a staged
recommendation result from the fixture run. Playwright coverage now exercises
the full guided path, responsive prompt composition, final recommendation,
supporting-detail toggle, source-detail toggle, and blocked guardrail state.

## Task 53I Gate Closeout

The post-Task-53 guided frontend rebuild gate is complete. The old all-in-one
workspace remains superseded, and provider/model live work can continue without
depending on that obsolete homepage.

Gate review outcome:

- First screen is the focused `Send your question` prompt with one large
  textbox and animated starter questions outside the textbox.
- Normal guided intake keeps the prompt-led composition: one displayed question,
  one answer surface, and no visible chat transcript.
- Textbox placeholders are neutral, and `Continue` is disabled until the active
  textbox has an answer.
- Inline choices are limited to the fixture cases where they reduce effort:
  yes/no monitor setup and two-option-plus-type-answer comparison priority.
- Optional context is one natural-language prompt, not a multi-row mini-form.
- `Skip question`, `Skip all and start analysis`, Back/reanswer, and
  first-question Back to the homepage-style edit surface are covered.
- Region setup stores provided/refused choices locally and resumes the pending
  submitted question automatically.
- Normal intake captures considered products by name/description and does not
  ask for product links.
- Shopper screens avoid session IDs, run IDs, agent names, provider mechanics,
  trace IDs, fixture labels, and other developer/process language.
- Progress and result reveal use plain shopping language with recommendation,
  warnings, seller/listing checks, and source details behind explicit controls.

Focused gate checks:

```sh
uv run pytest apps/backend/tests/test_guided_intake_api.py apps/backend/tests/test_guided_intake_schemas.py
pnpm --dir apps/frontend exec vitest run \
  src/lib/api/client.test.ts \
  src/lib/guided/guided-state.test.ts \
  src/lib/guided/local-region.test.ts \
  src/lib/results/result-view.test.ts \
  src/lib/run-progress/run-progress.test.ts \
  src/lib/refinements/contextual-refinement-prompt.test.ts \
  src/lib/user-products/contextual-product-prompt.test.ts
pnpm --dir apps/frontend check
pnpm --dir apps/frontend build
pnpm --dir apps/frontend exec playwright test tests/e2e/guided-flow-smoke.spec.ts
```
