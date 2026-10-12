# CartCart UX Information Architecture

## Concise advice, Task 219

The result leads with direct reasons and concise relative tradeoffs. It retains supported budget/value explanations, product limitations that change the choice and neutral links. Cards no longer add confidence scores, Worth checking lists or generic price, stock and seller-check rituals. Diagnostic warnings do not become a What to watch section. Source details retain names, claims, links, timestamps and useful disclosures without confidence or process-quality scores.

Product names, seller names, user input, source titles and evidence claims remain literal, including light fixture and FixtureSeller Electronics. Controlled fixture writers avoid deliberately generated developer labels. Saved authored reasons and tradeoffs are not rewritten; older wording can remain in historical results. Future generated wording is validated only in Task 221. Task 220 implements the final page and top restart action. Live validation deferred to Task 221.

## Primary choices and optional runners-up, Task 218

The result shows up to three authored primary choices in the main card grid. Three cards appear side by side at desktop widths of 1024 pixels and above; narrow screens stack them. Up to two optional runners-up appear once in a separate, quieter section after the primary cards. Each group retains its product reasons, useful tradeoffs, supported budget notes and neutral available links. One or two primary choices and no runners are valid.

The owning model prefers useful company/provider variety while respecting exclusive preferences. Counts and brands are not quotas, and a family/size variant can remain primary when the shopper's needs warrant it. Display group membership comes from saved authored IDs rather than mode labels or hiding extra cards. Historical saved answers keep their distinct final/runner membership through a read projection.

Task 219 removes generated diagnostic and checking copy. Task 220 removes history, duplicate comparison and refinement controls and implements top restart. Offline saved-data browser checks establish grouping and layout only; live validation is deferred to Task 221.

Status: Implemented guided shopping flow and UX guidance
Last updated: 2026-10-02

## Purpose

This document defines the user-facing UX acceptance checklist for CartCart. The
old all-in-one homepage/workspace direction is not acceptable for the product
experience. Backend sessions, runs, results, source evidence, and refinement
plumbing can remain useful, but the frontend should not make shoppers think in
terms of starting runs, inspecting workflow mechanics, or managing a dense
research dashboard before CartCart has guided them.

CartCart opens with a focused shopping question prompt. It should feel
like a calm guided assistant for deciding what to buy, not a visible chat
history, a developer console, a raw search page, or a form-heavy comparison
tool.

`docs/FRONTEND_REPLACEMENT.md` records the completed frontend replacement and
the earlier file audit. The current flow lives in `apps/frontend/src/routes/+page.svelte`
and its guided, progress, and result components.

## UX Principles

- Start with one natural-language shopping question.
- Ask one useful follow-up question at a time.
- Reveal only the next naturally needed step.
- Prefer the main answer textbox for normal guided intake.
- Use inline constrained choices only when choosing is clearly easier than
  typing.
- Do not show visible chat history in the normal flow.
- Do not expose agent names, prompts, providers, trace IDs, raw run mechanics, or
  developer-oriented process language to regular shoppers.
- Use regular-person language for actions, progress, failures, warnings, and
  results.
- Keep seller/listing legitimacy visible when it affects buying safety.
- Preserve source evidence and result versioning internally, but reveal details
  only when they help the current decision.

## Visual Direction

Follow `DESIGN.md` for the frontend visual reference:

- Dark Linear-inspired canvas.
- Restrained surfaces with thin borders and compact spacing.
- One primary action per screen.
- Acid-lime filled treatment only for the primary action.
- Quiet secondary actions in gray text or subtle outlines.
- Large prompt-led question text on intake screens.
- Main textbox as the dominant input surface.
- No decorative clutter, marketing hero layout, or card-heavy dashboard on the
  first screen.

The UI should feel precise and calm. It should not use bright multi-accent
decoration, large explanatory panels, or visible implementation terminology to
fill space.

## First Screen

The first screen asks "What are you looking for?" above a large textbox.
It should not show the old workspace regions, progress timeline, source drawer,
shortlist, comparison table, result cards, or refinement panels before the user
starts a shopping decision.

Required first-screen elements:

- A clear shopping-question prompt.
- A large natural-language textbox.
- A single primary send/continue action.
- Starter-question templates animated as part of the large main prompt text,
  outside the textbox, such as:
  - "Which phone should I buy?"
  - "Which laptop should I buy?"
  - "Which camera should I buy?"
  - "Which desk should I buy?"
  - "Between an iPhone and a Samsung, which is better?"
- Minimal navigation or setup affordances only when they are needed.

Textbox placeholders must stay neutral and short. Do not put suggested answers
or examples inside answer textboxes.

## Guided Intake Flow

After the first shopping question, CartCart should keep the same prompt-led
composition for most intake steps: one displayed question, one main answer
surface, and a small set of relevant actions.

Acceptance checklist:

- Ask only the next useful question.
- Prefer natural-language answer capture over structured mini-forms.
- Put the full user-facing question in the large main text. Do not add eyebrow
  copy above or helper copy below ordinary guided intake questions.
- Ask budget as its own question when it matters.
- Ask products the user wants CartCart to check as a separate product-name or
  description question when it matters.
- Do not split ordinary intake into multiple compact rows such as separate
  Budget, Product, Region, and Preference fields.
- Do not ask users to find or paste product links during normal intake.
- Ask for product names or descriptions when the user is considering specific
  products, then let CartCart find and verify listings.
- On textbox-based steps, disable and visually mute `Continue` while the textbox
  is empty.
- Use visible `Skip` and `Skip all` buttons for optional guided questions.
- Start analysis automatically when the guide has enough information instead of
  showing a separate confirmation screen.
- Let the user go back and reanswer prior guided questions before analysis
  starts.
- Do not display prior questions and answers as a chat transcript.
- The normal flow should use directional navigation such as Back rather than
  separate shortcut edit buttons like changing budget, changing region, or
  correcting category.

## Inline Choice Blocks

Constrained answers should normally render inline in the main window/main div,
near the active question. They should not open popups for ordinary intake.

Use constrained controls sparingly:

- Use simple yes/no choices for genuinely binary questions.
- Use two-option choices when both options are specific and useful.
- Use two-option-plus-type-answer only when the first two choices are specific
  useful paths and the third path lets the user type something else.
- Keep "type my answer" as a real input path, not a fake choice that still forces
  another separate form.
- Do not use constrained controls just to make the screen look busy.

The default answer surface remains the main textbox. Choice blocks are a
shortcut when they reduce effort.

## Region Setup

Region is important because availability, shipping, warranty, prices, currency,
retailers, and seller risk vary by location. The app should collect region
through a one-time lightweight setup prompt outside the main shopping question
flow when no saved region preference exists.

Required behavior:

- Explain in regular-person language that region helps CartCart show products
  the user can actually buy.
- Allow the user to provide a country/region.
- Allow the user to explicitly choose not to answer.
- Store the provided region or refusal locally in browser storage or cookies
  where appropriate.
- Let the user edit the saved region later.
- Do not treat region setup as a normal skippable guided question.
- If region setup interrupts an already-submitted shopping question, resume the
  pending guided flow automatically after the user provides a region or refuses
  to answer.
- If no region is provided, any backend fallback/default region must remain
  marked as defaulted or inferred rather than user-confirmed.
- Country/region display names should come from maintained standards, preferably
  Unicode CLDR display names through `Intl.DisplayNames` backed by ISO 3166-1
  alpha-2 region codes. App-specific currency and locale defaults should remain
  separate metadata.

## Processing And Progress

Processing messages should be user-safe and plain-language. The UI can say that
CartCart is checking options, comparing evidence, verifying availability, or
looking for risky listings.

Do not show:

- Internal agent names.
- Prompt text.
- Tool or provider names.
- Trace IDs.
- Raw API payloads.
- Developer labels such as "run", "stage execution", "fixture orchestrator", or
  "agent record" in normal shopper screens.

Progress should be minimal during guided intake. Detailed progress, source
status, and evidence inspection belong after analysis has started and only when
they help explain the recommendation or a recoverable problem.

## Final result

The result presents one authoritative answer after intake and processing. Up to three primary choices and up to two optional runners-up retain authored reasons, meaningful tradeoffs, useful budget explanations and neutral links. Counts and brands are not quotas. Available sources follow the advice and remain optional. No candidate or partial research is presented as a completed answer before analysis finishes.

An explicit Ask another question action appears before the result heading and remains usable on desktop and mobile without scrolling. It supports keyboard focus and activation. Restart clears the displayed flow and saved-link parameters, preserves local region preference and leaves saved backend records intact. Late responses cannot reopen old intake, show old errors or clear a newer request's pending state.

The page removes Decision history, Products considered, Saved comparison, empty Supporting details, missing seller/price/criteria boilerplate, the original-question/price-change footer and post-result refinement/product-entry controls. Known offer values and useful adverse advice may remain. Missing optional fields never erase recommendations. Technical failures keep explicit retry with saved information reuse.

## Initial product ideas

Shoppers may volunteer product names, descriptions and links in the first question or intake answers. The initial prompt can invite product ideas and a budget without requiring either. The bounded first-question repair retains an explicitly named model in ordinary suitability wording, including "Is the ThinkPad X1 Carbon good for travel?". Captured names remain unverified hints with session-local provenance. The original goal stays intact. Existing lookup and matching owns identity resolution.

Generic shopping requests and non-product budget/preference answers do not create invented candidates. Comparison, standalone model, volunteered URL and reanswer-cleanup behavior remains. Intake asks for names/descriptions when useful and never requires links. The normal result does not offer listing checks or manual product correction after completion. Product and listing concerns can influence the advice without routine buying rituals.

## Internal history and recovery

Immutable result versions, diagnostic history, sources and session/run associations remain saved. Backend history, refinement and user-product APIs remain available internally. They do not appear as shopper controls. Reading or reloading a saved result performs reads and never starts or retries a shopping run. Explicit technical retry retains its existing recovery path.

## Available sources

Available sources appear below the advice. Hide the section when no sources exist. Keep literal titles, snippets, claims, neutral links, relevant video timestamps and factual disclosures. Source evidence remains secondary and inspectable. Do not aggregate confidence, diagnostic warnings or missing-source/offer fields into shopper warning panels. Material adverse findings belong in useful advice and available evidence. Saved historical wording is not rewritten. Live validation deferred to Task 221.

## Empty, Blocked, Loading, And Failure States

Acceptance checklist:

- No question yet: show the focused "Send your question" screen.
- Missing saved region: show one-time region setup outside the main flow.
- Optional question unanswered: allow `Skip` when the question is skippable.
- Enough information exists: allow `Skip all` on optional questions, then start
  analysis automatically.
- Off-topic, unsafe, illegal, or inappropriate requests: show a short
  regular-person-safe redirection and do not start discovery.
- Processing: show calm, user-safe progress copy.
- No candidates: explain the issue and offer a recovery path.
- Weak evidence: show low confidence and source gaps where they affect the
  decision.
- Conflicting evidence: show the conflict where it changes the recommendation.
- Suspicious listing: show the red flag before any outbound purchase link.
- Failed analysis: show a recoverable message and next action, without exposing
  internals.

## Frontend Acceptance Checklist

Before the guided frontend is accepted:

- The first route is a focused shopping-question prompt, not the old
  all-in-one workspace.
- The UI is prompt-led but does not show visible chat history.
- Textboxes do not contain suggested answers or examples.
- `Continue` is disabled/greyed out while a required textbox is empty.
- Normal guided intake asks one useful question at a time.
- Ordinary intake does not use multi-row mini-forms.
- Inline choice blocks are used only when they reduce effort.
- `Skip` works for skippable optional questions.
- `Skip all` appears once enough information exists and starts analysis without
  a separate confirmation screen.
- The user can go back and reanswer prior guided questions before analysis
  starts.
- Region setup is one-time, local, outside the main flow, editable later, and
  resumes pending questions after region provided/refused.
- Normal intake asks for product names/descriptions, not product links.
- Processing messages are user-safe and hide internal mechanics.
- Result details are staged and do not overwhelm the prompt-led flow.
- The visual system follows `DESIGN.md`: dark, restrained, compact, and one
  primary action per screen.
