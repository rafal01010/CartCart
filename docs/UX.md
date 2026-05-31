# CartCart UX Information Architecture

Status: Workspace shell with session creation, stub run progress, and fixture result rendering wired; remaining items are acceptance guidance
Last updated: 2026-05-31

## Purpose

This document defines the MVP user experience structure before UI implementation. It should be used as the acceptance checklist for the first SvelteKit workspace shell, fixture result UI, and later live workflow UI.

CartCart should open directly into the shopping research workspace. Do not build a marketing landing page as the first screen.

The current frontend route implements the first workspace shell with query controls, region and budget fields, user-added product entry, refinement controls, inferred brief summary, progress timeline, shortlist, comparison, recommendation, trust notes, and source evidence panels. The query/region/budget form creates a persisted backend session through `POST /api/sessions`, stores the session ID in the URL, and reloads that session on refresh. The user-added product controls persist URL placeholders and manual product details through `POST /api/sessions/{session_id}/products`, render the returned session state, and reset stale run/result state before the next run. The refinement controls submit category, region, budget, and preference corrections through `POST /api/sessions/{session_id}/refinements`, show created refinement runs, and keep the current result version/run visible. The run action starts the fixture backend run, renders stage events from the SSE stream, and fetches the latest fixture recommendation bundle on completion. The result UI shows the final pick, why it wins, runner-ups, recommendation modes from the same analysis, trust notes, warnings/red flags, meaningful rejected items only when present, and inspectable source links. Workspace notices cover no session, loading, no result, run in progress, failed run, partial data, weak evidence, conflicting signals, warning/red-flag result, and API-error states.

## UX Principles

- Natural language comes first. Optional controls should clarify the request, not replace the main query.
- The interface is desktop-first and optimized for comparison, scanning, and repeated refinement.
- Mobile should remain usable, but dense desktop workflows are the priority.
- The app should show what it inferred and let the user correct it.
- Source evidence, trust notes, and warnings should be inspectable without overwhelming the main result.
- User-added products should be treated as first-class candidates.
- Recommendation modes should come from the same stored analysis pass, not from separate reruns.
- Rejected or "why not" output should appear only when there is a meaningful reason.

## First Screen Layout

The first screen should be a work surface with these regions:

- Query and controls area.
- Inferred brief summary.
- User-added products area.
- Run progress timeline.
- Generated shortlist and candidate comparison area.
- Result and recommendation area.
- Source/evidence drawer or side panel.

The layout should make the current shopping session, run status, and latest result visible without forcing the user through chat history.

## Query Entry

Acceptance checklist:

- Provide a prominent natural-language query input for the shopping goal.
- Support examples through placeholder or empty-state copy only if they do not dominate the interface.
- Include lightweight optional controls for region, budget, hard/soft budget semantics, and key preferences.
- Do not require the user to choose a product category before starting.
- Allow the query to mention known products, stores, constraints, use cases, and deal-breakers.
- Show validation errors near the relevant input.
- Keep the primary action focused on starting or updating a shopping run.

## Inferred Brief

The UI should show a compact brief derived from intake:

- Inferred product category.
- Region.
- Budget and whether it is a hard cap or preferred budget.
- Usage context.
- Hard constraints.
- Soft preferences.
- Uncertainty or clarification flags.

Acceptance checklist:

- The inferred category must be visible after intake.
- The category must be correctable before rerun/refinement.
- Region and budget must be editable.
- Correcting category, region, budget, or preferences should create an explicit refinement or rerun path rather than silently mutating prior results.
- Unknown or inferred fields should be visually distinguishable from user-confirmed fields.

## Region And Budget Controls

Acceptance checklist:

- Region is visible and editable.
- If a default region is used, it is marked as defaulted/inferred until user-confirmed.
- Budget entry supports amount and currency where known.
- Budget entry supports hard cap vs preferred budget.
- The UI should explain budget behavior through concise field labels and result treatment, not long instructional text.
- Results should show when a recommendation is within budget, outside a soft budget as a stretch, or invalid under a hard cap.

## Progress Timeline

The run timeline should make long-running workflow stages understandable.

Expected stages:

- Intake.
- Query planning.
- Discovery/search.
- Source extraction.
- Deduplication.
- Category/domain analysis.
- Seller/listing trust analysis.
- Comparison and decision.
- Verification.
- Result ready.

Acceptance checklist:

- Show pending, running, succeeded, failed, and skipped states.
- Show user-safe messages for provider failures, weak evidence, no candidates, and partial results.
- Preserve completed stages after a run finishes.
- Do not expose internal prompts or raw provider payloads in the normal timeline.
- Make retry or refinement available when a recoverable stage fails.

## Generated Shortlist

The generated shortlist should show app-discovered candidates before and after analysis.

Acceptance checklist:

- Show product identity separately from listing identity when both are known.
- Show enough information for scanning: name, brand when known, price when known, seller/store, region availability, source count, and trust status.
- Mark missing, inferred, or low-confidence fields.
- Preserve duplicate/listing differences when seller trust, price, or availability differs.
- Show when a candidate was excluded because of source policy or listing trust.
- Do not present the generated shortlist as final recommendations before analysis completes.

## User-Added Products

Acceptance checklist:

- Allow adding a product by URL.
- Allow adding manual product details when URL extraction is unavailable or not yet implemented.
- Clearly label user-added products.
- Include user-added products in the same dedupe, trust, analysis, and decision flow as generated candidates.
- Show extraction/evidence gaps for manual entries.
- Let user-added products win, become runner-up, appear in a mode, or be rejected/excluded for meaningful reasons.
- Preserve user-added products across refinements in the session.

## Result Area

The result area should focus on decision support, not a raw list.

Required result surfaces:

- Final best pick or explicit no-strong-buy outcome.
- Runner-ups.
- Recommendation modes from one analysis pass.
- Comparison table or matrix.
- Seller/listing trust notes.
- Warnings and red flags.
- Meaningful-only rejected items.
- Source links and evidence access.

Acceptance checklist:

- Show exactly one final best pick unless the result is explicitly no-strong-buy.
- No-strong-buy should be presented as a valid outcome with next steps, not as an error.
- Make product quality and listing trust visually separable.
- If a product is good but the listing is unsafe, the UI should show that distinction.
- Do not show a forced rejected/why-not section when there are no meaningful rejected items.
- Avoid affiliate, sponsored, or monetized link treatment.

## Recommendation Modes

Recommendation modes should let users inspect the same analysis through different priorities.

Expected modes:

- Best overall.
- Best value.
- Best within budget.
- Stretch upgrade when justified.
- No-strong-buy when applicable.

Acceptance checklist:

- Switching modes must not start a new search or analysis run.
- The active mode should be clear.
- Each mode should identify the selected candidate or explain why no candidate qualifies.
- Modes should preserve the same source and trust evidence.
- Stretch mode should be unavailable or empty when no justified stretch exists.

## Trust Notes And Warnings

Acceptance checklist:

- Show trust level for listings where assessed: `strong`, `reasonable`, `mixed`, `weak`, `suspicious`, or `unknown`.
- Surface material red flags near affected recommendations.
- Link trust notes to evidence or listing signals where available.
- Distinguish suspicious listing concerns from product fit concerns.
- Blocking listing concerns should be visible before any outbound purchase link.
- Avoid generic warnings that do not affect the buying decision.

## Source Drawer

The source drawer or side panel should support evidence inspection without cluttering the main decision view.

Acceptance checklist:

- Open from source references, trust notes, factual claims, warnings, and result cards.
- Show source title, URL, provider, source type, extraction status, and quality/confidence signals.
- Show claim/evidence snippets when available.
- Show video IDs, channel metadata, timestamps, and transcript availability for video evidence when relevant.
- Show evidence gaps and conflicts.
- Keep outbound links neutral.
- Do not show secrets, raw private provider payloads, or full sensitive traces.

## Rejected Items And Why-Not Output

Acceptance checklist:

- Show rejected or avoid items only when a meaningful negative reason exists.
- Meaningful reasons include suspicious listing, poor fit, hard-budget violation, overpaying, missing critical feature, materially weak evidence, duplicate inferior listing, region unavailability, or better equivalent alternative.
- Ordinary non-winning candidates can remain in comparison without a negative explanation.
- Empty rejected state should not render as an artificial section.

## Refinement Loop

The user should be able to iterate without losing the session.

Supported refinements:

- Change budget.
- Change region.
- Correct inferred category.
- Add or remove constraints.
- Add user-known products.
- Ask for a targeted recompute where cached artifacts can be reused.

Acceptance checklist:

- Refinements create a new run/result version rather than silently overwriting prior output.
- The UI distinguishes original run, refinement runs, and current result version.
- When possible, refinements should reuse cached candidates/evidence instead of restarting from zero.
- Changing category can trigger a new search or analysis path.
- Changing budget can recompute modes from stored analysis when possible.
- The user can inspect prior result versions.

## Empty, Loading, And Failure States

Acceptance checklist:

- No session: show the query entry and optional controls.
- Session created, no run: show inferred/default fields and a clear run action.
- Run in progress: show timeline and partial known state.
- No candidates: show a recoverable message and refinement suggestions.
- Weak evidence: show low confidence and source gaps.
- Conflicting evidence: show the conflict and where it affects the decision.
- Suspicious listing: show red flag treatment and safe next step.
- Failed run: show failed stage, user-safe reason, and retry/refinement path.

## Frontend Acceptance Checklist

Before the MVP frontend is accepted:

- The first route is the CartCart workspace, not a landing page.
- Natural-language query entry is the primary input.
- Optional controls include region and budget.
- Inferred category is visible and correctable.
- Progress timeline displays stage states.
- Generated shortlist is visible and distinct from final recommendation.
- User-added products can be represented and tracked.
- Result modes switch without rerunning analysis.
- Final result supports best pick and no-strong-buy.
- Trust notes and red flags are visible.
- Meaningful-only rejected items render correctly.
- Source drawer exposes evidence and gaps.
- Refinement loop preserves result versions.
- Mobile layout is usable, but desktop comparison remains the primary design target.
