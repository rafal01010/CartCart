# CartCart UX Information Architecture

Status: Guided shopping intake direction; the earlier one-page workspace shell is superseded
Last updated: 2026-06-12

## Purpose

This document defines the user-facing UX acceptance checklist for CartCart. The
old all-in-one homepage/workspace direction is not acceptable for the product
experience. Backend sessions, runs, results, source evidence, and refinement
plumbing can remain useful, but the frontend should not make shoppers think in
terms of starting runs, inspecting workflow mechanics, or managing a dense
research dashboard before CartCart has guided them.

CartCart should open with a focused shopping question prompt. It should feel
like a calm guided assistant for deciding what to buy, not a visible chat
history, a developer console, a raw search page, or a form-heavy comparison
tool.

See `docs/FRONTEND_REPLACEMENT.md` for the current frontend audit, the
keep/rewrite/delete map for existing Svelte files, and the planned guided
route/state structure for the replacement.

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

The first screen is a focused "Send your question" prompt with a large textbox.
It should not show the old workspace regions, progress timeline, source drawer,
shortlist, comparison table, result cards, or refinement panels before the user
starts a shopping decision.

Required first-screen elements:

- A clear "Send your question" prompt.
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

## Staged Result Reveal

The shortlist, comparison, recommendation, trust notes, warnings, and source
details should appear only when useful for the current step.

Expected reveal order:

1. First shopping question.
2. One-time region setup if needed.
3. Guided follow-up questions until enough information exists.
4. User-safe processing state.
5. Final recommendation or no-strong-buy outcome.
6. Runner-ups, modes, comparison, trust notes, warnings, and source details as
   supporting surfaces.

Do not show generated candidates as final recommendations before analysis
completes. Do not force users into a product table, source drawer, or comparison
matrix before they need those details.

## User-Considered Products

User-considered products are first-class candidates, but normal intake should
ask for names or descriptions rather than URLs.

Acceptance checklist:

- Let users mention considered products in the first question or a follow-up.
- Ask for product names/descriptions if the app needs clarification.
- Use CartCart lookup and matching to find candidate listings.
- Preserve evidence gaps when a product cannot be matched confidently.
- Let user-considered products win, become runner-up, appear in a recommendation
  mode, or be rejected/excluded for a meaningful reason.
- Keep product quality separate from listing or seller trust.
- Keep neutral outbound links when source/listing details are revealed.

URL entry can exist later as an advanced or corrective path, but it is not the
normal guided intake path.

In the current guided frontend, product mentions are captured from the guided
answer text as names or descriptions. The existing product endpoint remains
available behind that guided path rather than as a normal visible URL form.

## Recommendation Surface

The result area should focus on decision support, not raw output volume.

Required result surfaces when available:

- One final best pick or an explicit no-strong-buy outcome.
- Runner-ups.
- Recommendation modes from the same analysis pass.
- Meaningful comparison details.
- Seller/listing trust notes.
- Warnings and red flags.
- Rejected or avoid items only when there is a meaningful negative reason.
- Source links and evidence details behind supporting surfaces.
- When listing trust is linked to a recommended mode, show product fit and
  listing safety as separate ideas so a good product from a bad listing is not
  mistaken for a bad product.

No-strong-buy is a valid outcome, not an error. It should explain what blocked a
responsible recommendation and what the user can do next.

## Source And Trust Details

Source evidence should support inspection without becoming the main interface.

Acceptance checklist:

- Open evidence details from result claims, warnings, trust notes, and source
  references.
- Show source title, URL, source type, extraction status, and confidence/quality
  signals when useful.
- Show evidence gaps and conflicts when they affect the recommendation.
- Show video transcript availability and timestamps when relevant.
- Show Reddit/community context as qualitative signal, not product truth.
- Show Amazon marketplace/listing/seller/fulfillment and regional availability
  context where available.
- Show IKEA country/region, official product/store URL, price/currency,
  availability, and store/delivery context where available.
- Keep outbound product/source links neutral.
- Do not show secrets, raw private provider payloads, or full sensitive traces.

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

- The first route is a focused "Send your question" prompt, not the old
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
