# CartCart UX Information Architecture

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
- Accept a product link the shopper volunteers in the first question or a
  follow-up, whether it appears alone or inside a sentence. Preserve the
  surrounding shopping question and check the linked listing separately.
- Use CartCart lookup and matching to find candidate listings.
- Preserve evidence gaps when a product cannot be matched confidently.
- Let user-considered products win, become runner-up, appear in a recommendation
  mode, or be rejected/excluded for a meaningful reason.
- Keep product quality separate from listing or seller trust.
- Keep neutral outbound links when source/listing details are revealed.

An optional link correction path can appear after research, but normal guided
intake should not ask shoppers to find or paste links.

Guided intake captures HTTP(S) links volunteered in the main question or a
later answer as listing candidates, and explicit product names as separate
research hints. A link by itself leads to a short question about the shopper's
goal. Links do not establish product identity or seller safety. Direct URL
submission is also available through the product API. On the result screen,
shoppers can optionally open “Check a listing,” add a full link, and see the
refreshed decision in the same session. The response distinguishes a checked
listing, an unreadable page, and an uncertain match. A checked listing still
shows seller and trust context; an unreadable page offers another-link recovery.

After research, the result screen names shopper-requested products that still
have no confirmed match. The shopper can then open “Add what you know” for that
candidate, or correct a product CartCart matched incorrectly. The optional form
accepts a product name and any known seller, price and currency, availability,
review, warranty, or specifications. It saves to the same candidate and reruns
the decision in the same session. The refreshed result labels supplied details
as the shopper's own and displays missing fields as unknown. Manual details
never create a verified listing or purchase link. The ordinary guided path
continues to need only a product name or description.

After the decision, “Products considered” shows each product the shopper asked
CartCart to check as matched, possibly matched, unresolved, excluded for a
meaningful reason, or supplied from manual details. The saved comparison lists
the run's shortlisted products and available criteria. Missing scores, prices,
and sellers appear as unknown. Shopper-reported details stay labeled as such;
they do not become verified offers or purchase links. Listing concerns remain
separate from product fit, including when there is no strong buy.

## Recommendation Surface

The result area should focus on decision support, not raw output volume.

Required result surfaces when available:

- One final best pick or an explicit no-strong-buy outcome.
- Runner-ups.
- Recommendation modes from the same analysis pass.
- Switching between result modes should be a local view change over the stored
  result bundle. The best-overall summary remains visible and the UI must not
  imply that another search or analysis run has started.
- Meaningful comparison details.
- Seller/listing trust notes.
- Warnings and red flags.
- Rejected or avoid items only when there is a meaningful negative reason.
- Source links and evidence details behind supporting surfaces.
- When listing trust is linked to a recommended mode, show product fit and
  listing safety as separate ideas so a good product from a bad listing is not
  mistaken for a bad product.

No-strong-buy is a valid outcome, not an error. It should say that none of the
candidates are strong buys, explain what blocked a responsible recommendation,
and give the user a concrete next step such as checking safer sellers, looking
for stronger evidence, adjusting budget, or asking for more candidates.

## Refining A Decision

The completed result offers one “Refine this decision” action. It opens a
prompt asking what to change, with budget, buying region, kind of product, and
priorities as inline choices. The next screen asks one question about that
change. Budget accepts an amount with the current currency and an optional
maximum; region uses the country selector. Back returns to the choices or the
saved decision without submitting a change.

Submitting creates and executes a saved refinement in the same session. A
short “Updating your decision” message appears above the previous result,
which stays readable. Conflicting updates are disabled while work is pending.
Success opens the new result; a successful region change also updates the
browser's saved buying region. Failure keeps the previous result and offers
“Try refining again.” A lost execution response is checked against saved run
status before showing recovery.

A collapsed “Decision history” panel shows the original question, each
successful decision's shopping context, and the requested change. Shoppers
can open old results, including their comparison, sources, and considered
products, then return to the latest decision. Refinements and product
corrections are available on the latest result. Failed and pending attempts do
not appear as completed decisions. History is a view over persisted results;
it contains no chat transcript, agent names, or processing stages.

## Source And Trust Details

Source evidence should support inspection without becoming the main interface.
The frontend keeps source inspection collapsed by default. Recommendation
rationales, warnings/red flags, trust notes, avoid reasons, and source cards
should each open the evidence snippets and source metadata that support the
displayed claim, using neutral outbound links and omitting provider/debug
payloads.

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
