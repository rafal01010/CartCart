# Context management

Task 212 removes backend-owned state from isolated guide output. The guide's
model-facing schema has no shopping brief or navigation/region/start state.
Intake still receives the effective request and independently authors the ready
brief. Optional verifier output uses candidate-bound editorial references
instead of a full bundle. Public state and downstream consumers retain their
complete schemas. Measurements distinguish the current compact null approval
introduced by Task 216 from the historical full-report baseline; unchanged
approval was already small before Task 212.

## Final-output validation and recovery, Task 224

The Responses adapter preserves the provider response status that the installed Agents SDK omits from `ModelResponse`. Transport rejects incomplete final output before SDK validation or result persistence. Schema validation still rejects truncated or malformed JSON. Reaching an output cap alone does not invalidate a completed response.

One tools-free owner completion may reuse the prepared research and buyer constraints. It keeps the current model and reasoning, all enclosing ledgers, spent usage and existing timeout. It reserves and settles another actual call under existing funding policy. A failed or unaffordable completion remains a technical failure. It cannot start a fresh owner ledger, reopen research, reuse an old success or trigger another Technology recovery.

Saved-owner decision output alone increases from 2,000 to 6,667 under the owner's targeted authorization. Every other role cap and the 6,667 global ceiling remain unchanged. Main 200,000, owner starting 120,000 and source starting 40,000 remain unchanged. The retained-cap audit reuses Task 222's 44 construction sites.


## Current recommendation policy, Task 216

Ordinary shopping gathers information where available and passes it with buyer preferences to the owning LLM. The model recommends by default and weighs strong adverse information. Missing sources, reviews, prices, stock, warranty or support details are unknowns, not reasons for automatic rejection. Source quality, comparison and seller scores are advisory. Official stores need no mandatory background check. Budgets inform the model, including explained slightly over-budget alternatives. Unlimited budget remains distinct from missing budget.

Advice and source associations are independent. Recommendation evidence IDs, sources, comparison matrices, checked listings and mode records are optional. The UI leads with recommendations, reasons, tradeoffs and unknowns, then shows available page sources and search snippets. A snippet is labeled as a snippet. A source note is not a verbatim quotation. No exact substring, quote visibility, span membership or hash equality admits recommendations or retries.

The normal, refinement and saved-retry workflows do not invoke a mandatory verifier. The active owner remains General -> Technology -> the appropriate specialist for supported technology, including Smartphone. `VerifierCriticAgent` remains an explicit optional tool-free editorial workbench capability. It cannot block or replace the owner's buying judgment. Its configured model/profile and authorized 180-second override remain available when explicitly invoked. Request refusal uses the installed OpenAI Agents SDK input guardrail, with no application phrase tripwires. Classifier timeout or invalid output is a retryable technical error.

Tasks 216, 214, 215 and 100A passed their revised live checkpoint. Tasks 217-220
are implementation-complete. Task 222 repairs shared funding offline before
remaining Task 221 live acceptance. No live work starts from an implementation
invocation. Historical policies below are superseded wherever they require
citations, exact provenance, source counts, mandatory verification, seller
exclusions or hard budget vetoes. See [Task 216](TASK_216.md),
[Task 222](TASK_222.md) and [the saved live handoff](TASK_221_IMPLEMENTATION_HANDOFF.md).


Task 100B passed its offline acceptance gate on 2026-10-04 after completing
prerequisite Task 209. The [gate results](EVALUATION.md#context-management-gate)
record affected regressions, the refreshed audit and quick 27/27 before full
110/110. The stage/field handling matrix and spending limits below describe the
existing context repairs. The prerequisite corrected synthetic eval inputs and
bridge copy without changing production verification or independent criteria.
Live phone acceptance remains Task 100A and requires explicit live authorization.

The authorized guided attempt on 2026-10-07 exposed a separate per-call gap.
Both phone ownership transfers and three searches succeeded, saving 16 leads.
The next model call was blocked before transport at 17,685 estimated input tokens
against the unchanged 16,000 limit. History preparation changed 28,356 input
characters to 28,279; tool results contributed 20,534 characters. Shared settled
usage was 22,976 tokens, so the 90,000-token owner/source allowance was not
exhausted. Distinct search outputs receive JSON whitespace compaction but no
bounded lead projection. No source fetch, quote or recommendation was reached.
Task 211 covers this gap before Task 100A resumes. Existing offline acceptance
and synthetic page-body savings do not prove real search-history capacity.
Matching safe diagnostics are in
`data/artifacts/task100a-20261007/attempt3-safe-diagnostics.json`.

## Automatic request fitting

Task 211 passed its offline controls, but the authorized 2026-10-08 guided retry
exposed a gap with fresh distinct replies. The next call's base estimate was
17,443 tokens. Instructions contributed 2,123, schemas 3,752 and prepared
input/history 11,568. The shared guard applies `ceil(base * 1.25) + 256`, producing
22,060 against the 19,000 cap. This is a conservative rejected estimate, not
measured provider input. The call never reached transport. Its active tool replies
occupied 27,084 of 34,601 input characters. History preparation removed only 77
characters. No explicit research-result completion was recorded before the block.
The matching diagnostics are in
`data/artifacts/task100a-20261008/attempt2-safe-diagnostics.json`.

The shared `BudgetedModel` transport boundary projects reducible text,
deduplicates identical state and measures the complete request with instructions,
schemas and the unchanged conservative buffer. Task 214 replaced paid span
selection with deterministic whole-exchange archives and bounded original views.
No extra model call fits or fact-checks the recommendation.

Originals remain in invocation-scoped `ResearchHistory` and canonical SQLite
records. Derived views preserve buyer constraints, identities, neutral URLs,
amounts, useful source notes, cautions and lookup handles. SDK function
call/output pairs remain intact. Hashes and offsets are diagnostics, not advice
or retry prerequisites. A source note may paraphrase fetched content. Literal
quotations are labeled separately when available.

Research selection ranks relevance, novelty, source role, dates and regional
context. Domain quality is advisory. Duplicate suppression and bounded shortlists
remain; exact candidate text, fact coverage, professional reviews and minimum
domain counts do not determine whether research or advice can proceed.
Search snippets and fetched pages are useful context without quote capture.

When limits require closure, tools and handoffs close and the owner synthesizes
from available research and buyer preferences. Task 216 removes funded quote
capture and follow-up fetch rounds. Missing sources, seller details or prices do
not alone exclude a candidate. A final-call failure is a retryable technical
failure with saved research, not a no-option buying judgment. Ordinary runs
persist owner advice without a verifier pass. Historical acceptance measurements
below describe their original implementations and do not establish Task 216.

## What caused the investigation

The [2026-10-08 retention review](CONTEXT_REVIEW.md) inventories the current
pipeline's remaining context fat. It confirms replay of cached search/evidence
reads, consumed source bundles, repeated nested source metadata and unrelated
analysis context. Task 211 now covers their compact useful replacements and
retrieval, plus the planned headroom increase. Task 212 covers model-generated
output that the backend replaces or copies unchanged. The review describes the pre-repair baseline. Task 211 implements these input
repairs below. Task 212 and live acceptance remain separate checkpoints.

Live run `a4b4c70c-4587-4784-99b0-53a0fa1ef831` completed General -> Technology ->
Smartphone ownership transfers. The completion guard rejected 247,313 input
plus 3,956 output tokens, totaling 251,269. This is cumulative usage across
calls, not proof of a single context-window overflow. Eight persisted pages
contain 49,067 text characters. Historical per-turn inputs, schema overhead,
hosted-tool context and usage were not saved and remain unknown.

Previously the SDK replayed research history without application compaction;
page bodies accumulated across turns. Extraction prefetched every page into
its initial input, and downstream typed records used formatted JSON. The
90,000-token owner guard ran after the SDK finished. Nested source runs had a
separate completion guard. Downstream work had no common cumulative ledger.

The owner and QueryPlanner receive explicit purpose-specific query guidance,
the current UTC date and a separate specified/unlimited/missing budget status.
Derived queries use candidate identity, buying region and unresolved gaps;
original shopper wording stays unchanged. Offline tests verify these contracts
and provider query records, not live model relevance. Context management must retain the distinction between
missing and unlimited budgets. It must not infer a cheap-phone preference from
"budget is not a problem".

## Repeatable measurements

Run from `apps/backend` using the installed environment:

```bash
.venv/bin/python -m app.tools.audit_context --output ../../data/artifacts/context/task100b-after.json
```

The audit loads no `.env`, makes no SDK/provider/model requests, and uses an
in-memory SQLite database and capture-only wrappers. It inventories 25 typed
workbench contracts, 25 initial input constructions, and seven receiving owner
contracts. Deterministic dedupe has no model boundary. Recovery shares the owner
contract and ledger; refinement reuse shares the current brief/evidence stage
contracts. Their historical turn costs remain unknown. Instructions, tool/output
schemas and initial fields have separate counts. Reports contain safe sizes and
role names, not shopper/source payloads or credentials.

The initial audit is `data/artifacts/context/task100b-baseline.json`; the completed
audit is `data/artifacts/context/task100b-after.json`. The baseline captured 20
initial constructions before the extraction/full-owner/source-manager captures
were added and before SDK dictionary-schema construction was corrected. Compare
shared boundaries directly; do not treat added coverage as a measured saving.
The completed report records deterministic before/after projection for each input.
The historical verifier measurement included the then-production bounded snapshot tool; its audited
fixture input does not include a persisted original-support reload. That extra
input is measured by focused SDK tests, not invented in the audit.

| Boundary | Initial input characters before / after | Instruction estimate | Schema estimate |
| --- | --- | --- | --- |
| Complete General owner | 282 / 260 | 1,861 | 2,725 |
| QueryPlanner | 620 / 575 | 836 | 477 |
| Smartphone analysis | 5,982 / 5,612 | 1,717 | 585 |
| Comparison | 10,020 / 9,413 | 584 | 2,115 |
| Verifier | 4,883 / 4,578 | 474 | 2,301 |
| Extraction, scoped page handles | 661 / 625 | 891 | 5,796 |
| Source manager | 433 / 401 | 381 | 916 |

These are local UTF-8 byte-size estimates divided by three, rounded up, not
provider tokenization or measured model usage. Schema overhead can exceed the
brief, especially for extraction. The initial eight-page history saving was invalid: partial quotes did not cover
all removed text. The repaired audit reports lossless history preparation and
bounded retrieval separately. Task 211 adds explicit processing checkpoints.
New and unprocessed partial reads retain their exact text; processed reads can
retire into retained facts, bounded cautions, gaps and original lookup references.
Omitted support remains unreviewed. Full canonical pages, exact quotes,
arguments, source IDs, warnings and SDK call pairs remain available.
SDK replay tests exercise both ownership transfers, generic decisions, refinement
region changes and nested source delegation. Their usage is deliberately
simulated. They prove transport/accounting contracts, not live reasoning quality.

## Stage and field handling

| Stage or field | Handling | Information retained and why |
| --- | --- | --- |
| Intake, guide and scope | Exact strings; deterministic JSON projection | Original wording, answer order, explicit preferences, missing versus unlimited money, budget and region. No answer deduplication. |
| General, Technology and product ownership | Project exact typed state; defer completed page bodies | Keep original brief, ownership transfers, arguments, source IDs, gaps and recorded exact quotes. Keep new and unprocessed reads, including distinct spans. Explicitly processed bodies can retire into exact facts, caution/gap coverage and original lookup references without quoting the entire page. |
| SDK prior turns and bookkeeping | Remove completed body text; minify structured results | Every tool call/output pair and handoff remains; distinct unprocessed text remains exact. Processed cached bodies share one useful state and unchanged receipts. Opaque hosted-search/reasoning items remain; arbitrary deletion could break SDK history. |
| QueryPlanner and discovery | Preserve derived queries separately; deduplicate identical research | Queries use purpose, identity, current region/date and gaps. Original request stays unchanged. Cache keys include query, intent, region and result limit. |
| Extraction | Bounded deferred page retrieval | Default 4,000-character reads support offset/focus lookup. The first assigned snapshot enters initial input; remaining IDs are deferred. Available original context informs typed interpretation without per-claim substring or hash admission. |
| Products, listings, evidence, analysis and trust | Project JSON; remove byte-identical records with IDs | Preserve differing variants, sellers, prices, currencies, sources, dates, conflicts and hard flags. Same ID with different content is not a duplicate. |
| Dedupe | Existing deterministic service | No extra model or parallel summary state. Full source URLs distinguish offer variants. |
| YouTube | Bounded deferred permitted captions; existing typed model interpretation | Six segments per read, at most 1,000 characters each; segment and character cursors reach late facts, including within a single long segment. Any omitted text is reported as truncated. Original segment IDs/text/timestamps remain canonical. Canonical disclosures and stronger bias warnings survive selection. |
| Reddit | Bounded deferred permitted public text; existing typed model interpretation | 1,600-character views support focus/offset. Public provenance, dates, independent supporting quotes, qualitative caveats and access gaps remain. No private/deleted content fallback. |
| Amazon and IKEA | Exact typed fact projection; existing scoped tools | Marketplace, ASIN/variant/seller, regional price/stock, review risks, official-store country and shipping limits remain. A global page is not local availability. |
| Comparison and optional editorial assistance | Bounded supplied context; JSON projection | Comparison receives saved candidates, prices, available sources, limitations and advisory trust. The optional tool-free verifier preserves owner choices and returns notes without per-claim revalidation. Normal run/refinement/retry stages omit it. |
| Recovery and refinement reuse | Current typed state; same bounded gateway | Recovery uses the original owner allowance. New refinements get a new run ledger and current constraints. Same-region/currency budget refinements reuse saved evidence; region/currency changes invalidate reuse. Persisted support retains original provenance. |
| Extra model summarizer | Not added | Measured mechanical savings avoid another model call. Existing typed interpretation uses available context and qualifies unknowns; it does not require a new fact-check call. |

Completed bodies can retire into useful notes, cautions, gaps and original lookup
references. SDK pairs remain intact. Scoped original reads retain run/source
identity and bounded text; arbitrary filesystem paths are not accepted.
Source-manager and owner-consultation views retain useful bounded context.
Reusable source specialists preserve their existing provider and access contracts.
Unavailable optional source content becomes a gap while the owner uses other
information. No per-claim source reread is required to finish advice.

The source-note boundary preserves run-scoped associations and bounded content.
Offsets and hashes may describe literal source spans. They cannot veto note
admission, candidate selection or saved retry. Exact substring matching is used
only to distinguish an available literal quotation from a paraphrase. Product
and listing interpretation remains in typed entity fields. External content
remains untrusted information. The final model prompt asks for honest uncertainty
and forbids invented facts, prices, quotations, reviews or source links.

## Limits and accounting

Every production SDK wrapper uses `BoundedRunner` and a model-provider adapter.
The SDK input filter runs on each turn, including transfers and nested
`Agent.as_tool` runs. Configured model names resolve through the adapter; direct
model objects, hidden remote conversation history and uncomposed input filters
are rejected to prevent bypasses. Shopping uses non-streaming runs.

| Bound | Default |
| --- | --- |
| Known input per model request | 25,334 estimated tokens, including instructions and schemas |
| Output per request | Lower of role limit and 6,667 tokens |
| One orchestration attempt | 200,000 cumulative tokens |
| Owner plus nested sources and recovery | Starting allocation of 120,000 tokens |
| Source manager plus nested specialists | Starting allocation of 40,000 tokens |
| Eligible comparison completion | Configured 32,000-token nontransferable allocation |
| Requested optional verification | Configured 32,000-token nontransferable allocation |
| Hosted search uncertainty per eligible request | 10,667 tokens |

The attempt bound also covers model stages outside the owner. Nested counters
are overlapping views of the same charges, not added token pools. Starting
owner/source allocations can expand by the exact admitted shortfall from
uncommitted ancestor capacity. Every enclosing scope must fund the request and
active completion promises. Transfers change funded ceilings without resetting
spent or reserved balances. The main ceiling never expands.

Known-input estimates start with UTF-8 bytes divided by three, then add 25%
and 256 tokens. After a response without executed hosted search, observed input
usage can increase the attempt's multiplier, bounded at 2.0, with 10% headroom.
The multiplier never decreases. Actual executed hosted expansion is recorded
separately because its hidden input cannot be measured locally. Output and
hosted reservations are additional. These are conservative planning bounds,
not guarantees about provider tokenization or a model's context window.
Reducible oversized inputs receive automatic derived views. Irreducible exact
contracts fail explicitly rather than truncating buyer constraints.

Reservations happen synchronously before awaiting transport, so concurrent
nested calls share remaining capacity. Actual response usage settles the
reservation once per transport request. Parent SDK aggregate usage is not added
again to the shared ledger. Owner/source allowances enforce their own subset
ceilings; their totals are not summed into run usage. Failed, cancelled or
zero-usage requests consume their full reservation because actual cost is unknown.
No SDK retry advice is supplied. Provider/client-internal network retry costs
cannot be inferred from local input sizes; returned usage and the completion
backstop remain necessary. Completion checks use the settled ledger interval
when transport events exist. Injected runners without events use owner SDK
usage plus source consultation aggregates once; child activity is diagnostic.

Before research is admitted, the adapter prepares and funds a purpose-specific
completion request. Its checkpoint contains actual retained input, instructions,
output allowance and a bounded retained-return input allowance. The next
completion is compacted against that funded input ceiling under funding
pressure. Ample uncommitted funds can secure a refreshed larger completion.
Raw tool results may
be much larger; complete useful records and cautions survive in the retained
return while omitted originals remain unreviewed and retrievable. Suspended
owner and source-manager completions stay protected during specialist work.
If research cannot also fund completion, the adapter closes tools and handoffs.
Sources finish metadata, interpreted speech and accurate gaps. Structured stages
finish their own contracts. Shopping owners finish concise advice. If the
call cannot be funded or fit, it raises `ContextBudgetExceeded`. The run fails
technically with saved research. Missing citations, warranty, trust or price
cannot substitute an empty buying judgment for a failed final model call.
An optional cleanup failure uses deterministic saved-original checkpoints.
Useful saved source notes survive that fallback. Cleanup never adds a paid
summarizer, research round or automatic retry. All changes to tools, handoffs,
instructions or input trigger a fresh full-request estimate. Unknown, failed
and cancelled calls keep their complete reservations. Abandoned actor holds
are released without refunding those charges. Paid valid final responses after
actual overage still reach ordinary validation/persistence; further calls are
blocked by exhausted ledgers. See [Task 222 handoff](TASK_222_IMPLEMENTATION_HANDOFF.md).

Persisted `context_call` activity separates estimated inputs from actual input
and output usage, before/after sizes, instruction/schema overhead, source/evidence
field counts, replayed items, stage/agent and finalization state. Nested field
counts overlap their enclosing input groups and must not be summed. Diagnostics
omit raw text, exception bodies and secrets. This is task-specific instrumentation;
Task 101's broader telemetry work remains unstarted.

## Storage and lifecycle

Context preparation creates no disposable runtime files or second evidence
store. Full pages stay in existing SQLite snapshots/artifacts. Source-tool caches
are confined to the current run/brief/region and exact source identity; recorded
spans may carry hashes for diagnostics. Hash equality is not an advice or retry gate.
Concurrent/refined runs cannot reuse another run's handles or mutable ledger.

Success, failure, timeout and cancellation reset in-memory context scopes.
Process exit discards them, so there are no abandoned context files to reclaim.
Tests cover cancellation during a model request, concurrent scopes, durable page
preservation and invalid/cross-run/path handles. Audit reports and test scratch
stay under ignored repository `data/artifacts`; gate scripts remove disposable
test/cache directories on exit. Canonical evidence and useful diagnostics follow
[existing artifact retention](OPERATIONS.md#persistence-and-artifacts).

## Verification

Task 222 uses the focused offline control command from the repository root:

```bash
scripts/local/verify-task222.sh
```

It exercises one shared funding/cleanup boundary matrix, actual nested source
SDK tools, useful reduced-context SQLite/API saved completion and safe effective
configuration inspection. It makes no external calls. Real captions and final
browser acceptance remain in Task 221. The older Task 100B gate below is
historical and is not a Task 222 requirement.

The Task 100B gate was run from the repository root:

```bash
scripts/local/verify-context.sh
```

It runs affected context/SDK/provider/storage/decision regressions, scoped lint
and typing, the offline audit, and the Section Q gate with quick evals before
full. The corpus adds late-caption and late-public-discussion focused-read cases
without weakening existing scorer criteria. Live relevance, hosted-search
internal cost and the actual phone recommendation remain Task 100A acceptance.
Full repository suites, builds and browser E2E remain deferred.

## Task 211 processing and retrieval

The processing checkpoint is explicit. Large local SDK tool replies carry a
`_research_view.view_id`. `complete_research_result` accepts 1 to 12 exact
original passages of at most 400 characters each. The backend validates those
passages against the original view and keeps source, evidence, candidate and
listing identities, detected exact cautions, structured warnings and gaps.
Unrepresented and omitted passages remain explicitly unreviewed. Processing
a snippet does not make it verified evidence or establish seller safety.
The owner receives bounded caution and uncertainty context. It weighs actual
adverse information and qualifies positive claims itself. Historical categorical
safety/warranty assertion vetoes and `unreviewed_research` completion gates are
removed by Task 216. Exact retained passages are not an advice prerequisite.
Batch independent processing calls with the next independent research calls
to avoid a model turn for each receipt.

Only processed bodies can become compact useful state and original references.
New or changed results stay visible. Unprocessed partial quotes retain their
remaining text. SDK function call/output pairs and handoff arguments remain
valid; preparation removes JSON whitespace without deleting required arguments.
Tool exhaustion is associated with the agent that issued the recorded SDK call.
A parent owner's closed quota cannot disable a fresh child's same-named tool.
Tiny replies below 900 characters keep their original representation. A
replacement that is larger than the original is not used.

`read_research_result` provides bounded offset or focus reads of canonical
original tool views within the current shopping invocation. Nested source runs
and compatible ownership transfers share that state. Independent root
invocations have separate lookup namespaces. SQLite retains original search
leads, pages and evidence. Direct owner consultations also retain their complete
validated bundles and consultation notes in run-local canonical state before
returning bounded useful views. `read_source_bundle` uses saved bundle or consultation identity and can fall back to the available saved version. Diagnostic hash mismatches do not veto reuse. The combined owner reply is capped at
11,000 characters before lifecycle metadata, using consistent UTF-8 JSON. A missing original or wrong run cannot
authorize lookup or retirement. Source-specific tools remain the authority for
full page, transcript, discussion and typed regional-store support.

Search returns at most four initial leads with 200-character previews. Deferred
IDs and a next offset make omitted leads explicit. `read_search_results` pages
the original same-run batch or reads a full original snippet by source ID with
focus and offsets. Snippet cautions are discovery cautions, never page support.
Changed snippet/title records get distinct identities; variants and sellers
remain separate. Compatible run, region, policy and provider instances share
completed query and observed-source state across ownership transfers. Changed consultation constraints remain distinct. Optional diagnostic source versions do not veto saved-context reuse.

Owner evidence reads expose offsets, hashes, total size and unresolved coverage.
They retain up to six exact caution previews of at most 300 characters from
the canonical original, including ones beyond the first 2,000-character span.
Deferred or truncated cautions carry counts, focus terms and an explicit
unreviewed marker. Full original lookup remains available. Empty default
metadata is omitted from model-facing views. Assigned category analysts receive
the selected route rather than the whole routing registry. Unmatched products
receive an explicit evidence gap, not unrelated evidence. Repeated identical
video metadata is represented once with exact per-claim references. Typed original-support projection retains useful bounded context; ordinary completion has no canonical verification pass. Distinct recommendation and refinement
graphs, seller flags, quotes and citation edges remain intact.

The configured models are GPT-6 Sol and Luna. Their documented context windows
accommodate the 19,000 input plus 5,000 output application bounds.
[GPT-6 Sol](https://developers.openai.com/api/docs/models/gpt-6-sol) and
[GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) were checked
on 2026-10-08. These are application limits, not provider-window measurements.
The 150,000 workflow, 90,000 owner and 30,000 source-manager cumulative ceilings
and all existing role output caps remain unchanged.

The Task 211 offline SDK probe compares the old 16,000 limit and retained history,
19,000 headroom alone, and the complete repair. Its transport payloads measure
instructions, schemas, history and tool outputs separately. Scripted transport
usage is simulated, not paid-model token savings. Acceptance evidence is
recorded in the implementation plan after the complete shared gate passes.

Task 211 passed on 2026-10-08. Actual scripted SDK probes reduced post-search
tool output by 52.57% for phones and 52.62% for a generic lamp request; both
reached literal cited decisions and approved verification. Maximum estimated
input was 18,364 and 18,568. Original leads and support remain retrievable.
`data/artifacts/task211/acceptance.json` separates instructions, schemas, active
history and simulated usage. The deduplicated shared gate passed 499 affected
tests plus 393 Section Q tests, with 27 quick eval cases before 117 full cases.
See `data/artifacts/task211/gate-deduplicated.log` and the implementation plan
for the final manifest and repair evidence. These results do not complete
Task 100A's live guided acceptance.

## Guided phone retry on 2026-10-08

The authorized Task 100A retry `0c85a922-efb3-42b1-b2cc-2c1b8fa855d4`
used the owner's configured `gpt-6.1-sol`. Both SDK handoffs and three searches
completed. Four fetched snapshots and one quoted evidence record were saved.
The next model request failed the application input guard at 22,060 estimated
tokens against 19,000. Input preparation reduced 34,678 characters to 34,601.
Active tool replies contributed 27,084 characters, with no recorded research
completion call. Distinct unprocessed bodies remain active; one quote cannot
justify discarding their unreviewed support or cautions.

Shared settled usage was 53,145 tokens, including 52,155 owner tokens. Neither
cumulative ceiling was exhausted. The blocked call's actual usage and final
SDK aggregate usage are unknown. This was not an observed OpenAI context-window
rejection. Task 213 must address active research admission/processing under the
existing limits. Task 211's passing offline gate does not establish that this
live failure shape is resolved. No buying result was saved and Task 100A remains
unchecked. Matching diagnostics and source-tool activity are in
`data/artifacts/task100a-20261008/attempt2-safe-diagnostics.json` and
`attempt2-tool-summary.json`.


## Task 213 acceptance

Task 213 passed on 2026-10-09 local time. The final offline gate passed 619
affected tests and 393 shared tests, with 27 quick eval cases before 117 full
cases. Eight network-denied SDK probes preserve the expected saved decisions
and safety outcomes. The blocked baseline estimates 23,653 tokens; every repaired
main request is at most 18,990 under the unchanged 19,000 cap. Scripted usage is
simulated and separate from conservative estimates. Identical noisy inputs
reduce admitted lead data from 2,464 to 862 bytes, repeated history from 75,365
to 12,317 UTF-8 bytes, and fetches from ten to three while retaining literal
expected support and the seller warning.

Installed Chrome rendered three matching saved SQLite-backed API results,
including the visible research limitation. The fixture guide opens already
accepted offline runs; this does not establish live guided acceptance. Reports
and rerunnable scripts are under `data/artifacts/task213/`; `verification.json`
links the final gate, SDK, browser and independent review evidence. The eval
manifest is `data/artifacts/evals/suite-full-20261008T184011524550Z.json`.
Task 100A remains the next main P0 and requires separate live authorization.

## Guided acceptance failures after Task 213, 2026-10-10

The required offline gate passed again before two authorized guided attempts.
Both retained the selected live models, PH unlimited-budget intent, separate
`iPhone` candidate and actual General -> Technology -> Smartphone handoffs.
Both failed before candidate validation with no canonical exact evidence or
saved result. New P0 Task 214 precedes the next Task 100A checkpoint.

| Final request | First attempt | Bounded retry |
| --- | ---: | ---: |
| Input characters before preparation | 58,642 | 58,552 |
| Input characters after preparation | 33,216 | 36,559 |
| Base input estimate | 14,286 | 15,395 |
| Added input headroom | 3,828 | 4,105 |
| Final input estimate | 18,114 | 19,500 |
| Active Smartphone output allowance | 1,500 | 1,500 |
| Settled owner tokens | 70,849 | 66,798 |
| Remaining owner allowance | 19,151 | 23,202 |
| Settled shared tokens | 71,924 | 67,868 |
| Failing gate | Owner reservation short by 463 | Input cap exceeded by 500 |

These are recorded conservative estimates and settled ledger values, not actual
input usage for blocked calls. Neither blocked request reached transport. The
first run's two shortening fallbacks consumed unknown-usage reservations of
3,797 and 4,684 tokens. Their exception causes remain unknown because the
fallback records omit them. Do not remove those charges to make completion fit.

The current selector targets the input ceiling before finalization changes
instructions and schemas; it does not target the currently affordable owner
continuation. Protected request structure can still exceed its target after
all selectable narrative is shortened. Simultaneous spending/context pressure
then removes all quote/read tools, leaving fetched-but-unquoted support without
a funded path to canonical evidence. Task 214 must secure that path earlier,
plan against the final request shape and every active allowance, and preserve
processed-history reduction, original lookup, exact cautions and SDK pairing.
It must distinguish the active role's output cap from General's summary cap and
record safe rewrite-failure and blocking classifications.

The per-call cap remains 19,000, owner/source allowance 90,000 and shared ceiling
150,000. Both downstream reserves remain 24,000. No context behavior changed
in this acceptance invocation. Evidence is under
`data/artifacts/task100a-20261010/`, including both safe diagnostics, tool
summaries and the independent root-cause review. Phone age/support, launch
uncertainty and final seller/citation acceptance remain pending Task 100A.

## Historical Task 214 transport repair

This section records the pre-Task-216 implementation and failed live attempts. Its quote-capture and verifier policy was superseded by Task 216.

The owner replaced the broad offline gate for this invocation with actual guided
live runs and authorized reruns. Narrow Ruff and compilation checks establish
launch readiness only. They do not establish shopping acceptance.

The failed premise was that shortening narrative fields could bound history
while every old call, argument and protocol item remained. The saved second
100A failure held 24,479 tool-result characters and 10,864 prior-turn/handoff
characters. The shopper brief was roughly 1,148 characters. These sizes exclude
instruction and schema overhead. The 150,000 allowance counts repeated input
and output across calls; it is not one request's available context window.

Task 214 removes paid span-selection calls. It projects complete old response
batches into scope-bound exact archives and a bounded derived checkpoint.
Native reasoning, hosted outputs and paired external calls move together.
Recent batches and unmatched calls remain available. Canonical evidence stays
in SQLite and full research originals remain retrievable. Checkpoint omissions
are unreviewed and do not establish listing or warranty safety.

Fitting starts at 75 percent of the affordable request and targets 60 percent
where reducible content permits it. It measures final instructions, tool and
output schemas, the active role's output allowance, remaining ledgers and
eligible completion promises. Emergency fitting retires more complete history. A funded
capture phase keeps existing-source reads and parallel exact-quote recording
before output-only completion. Diagnostics identify the phase, active output
cap, reservation, remaining balances and exact blocking condition.

The first new live attempt exposed invalid projection metadata on an SDK item.
The second exposed a hosted-search item separated from its required reasoning.
Both failed without a saved buying result. Repairs restrict metadata to payload
bodies and keep complete native response sequences together. Bounded archive
rereads compute text and attributed source spans from one decoded representation,
while original archive bytes retain their own hash and size. Verification
artifacts are in `data/artifacts/task214/`. Acceptance remains pending until a
matching fresh saved result is inspected and visible in the browser.

The sixth repair run recorded four official quotes but produced no product suggestion.
A failed HTTP403 review read had been reported as success, and fixed capture turns
closed while16,977owner tokens remained. Capture now chooses a bounded unquoted
source or replacement from actual evidence state and reserves its quote follow-up
and completion before fetching. Empty/failed reads expose a source-switch gap.
Planning projections no longer mutate transport caches; only actual sent packets
commit visibility. Typed stage JSON is projected inside SDK text envelopes.

Before Task 216, the owner revised product selection so trusted official exact support could
establish a product-only option without a second review domain. Manufacturer
claims stay attributed and unknown stock, price, warranty and support stay
qualified. That earlier policy still required independent reviews for unsupported comparisons. Task 216 removes this admission requirement. Basic research starts with two focused
queries and three hits each; deferred discovery leads remain uncertain/unreviewed.
The earlier result contract expected up to three verified options with tradeoffs and citations. Task 216 makes source associations optional. This policy revision is owner-authorized, not evidence
that the sixth no-option result passed acceptance.

The pre-Task-216 verifier repair loaded stored quote/hash context and retained
independent factual, seller and budget checks. Those buying-policy gates are
removed by Task 216. The owner-authorized timeout change from 60 to 180 seconds
remains configured for explicit optional workbench use. No revised live
acceptance is claimed.

Saved retries retain the existing research and owner checkpoints. They finish
with tools disabled and do not repeat source research or verification. Missing
quotes, offsets or hashes cannot prevent saved-context reuse. Operational run,
request and source identity still apply. Failed final calls remain technical
failures, with prior immutable result versions available.

### Task 225 selected source coverage

The owner selects attributed source packets before final request preparation. Saved decisions and retained comparison final inputs no longer use the first provider/URL-ordered search records. Retired tool receipts recover their archived attribution when preparing later turns, without restoring duplicate source bodies to the request. Candidate coverage can include discovered products before recommendation persistence. Comparative sources retain one body and exact product/claim bindings. The selector prioritizes unresolved candidate/question coverage, useful independent perspectives and material disagreement without an equal-coverage quota.

The selected projection survives existing context compaction and tools-free funded completion. Source originals stay in the archive, and omitted material remains explicitly unreviewed. Selection receipts report unique source and meaningful candidate coverage plus source-content and complete-request local size measurements. The local UTF-8 estimator is separate from reported actual provider usage. Source count alone establishes neither context consumption nor breadth.

### Task 226 alternative retention

The existing `SourceDecisionProjection` remains the owner evidence structure. Its complete packets carry candidate/question annotations, attributed findings, perspectives, exact speech and material cautions. No second candidate index or new source-count, per-product or token ceiling is added. The original complete buyer brief remains protected.

Packet cleanup evaluates marginal coverage against the remaining packets after each removal. Repeated support can yield before the only useful facts about another alternative. Distinct disagreements and adverse findings affect removal even when they address the same candidate/question. Retained evidence stays whole. An impossible faithful projection follows the existing technical-failure route rather than treating omitted evidence as proof that a product is unsuitable.


Task 212's affected context acceptance exposed a lookup prerequisite. Compact
owner receipts retain search-batch identity, deferred source IDs and pagination
fields. Reprojecting a receipt preserves its verified original archive handle
instead of archiving the receipt as a new original. These handles permit the
existing scoped lookup tools to retrieve deferred leads. They do not establish
reviewed evidence, replace original cautions or change budget limits. The runtime
catalog records this boundary as `StableSourceLookupReceipts`.

Ordinary nonvideo source-note receipts retain their persisted citation IDs.
Page and snippet projection removes runs of at least three consecutive identical
sentences before source eviction. Retained passages are exact original spans.
Explicit quotes, source notes and transcript support bypass this deduplication.
Full originals remain retrievable, and omitted material stays unreviewed.
