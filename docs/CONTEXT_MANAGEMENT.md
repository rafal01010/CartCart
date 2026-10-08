# Context management

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
The verifier schema includes its production bounded snapshot tool; its audited
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
| Extraction | Bounded deferred page retrieval; exact validation | Default 4,000-character reads support offset/focus lookup. Only the first assigned snapshot is read into initial input; remaining IDs are deferred without consuming read quota. Interpret and validate only spans actually supplied to the model; canonical snapshots remain complete. |
| Products, listings, evidence, analysis and trust | Project JSON; remove byte-identical records with IDs | Preserve differing variants, sellers, prices, currencies, sources, dates, conflicts and hard flags. Same ID with different content is not a duplicate. |
| Dedupe | Existing deterministic service | No extra model or parallel summary state. Full source URLs distinguish offer variants. |
| YouTube | Bounded deferred permitted captions; existing typed model interpretation | Six segments per read, at most 1,000 characters each; segment and character cursors reach late facts, including within a single long segment. Any omitted text is reported as truncated. Original segment IDs/text/timestamps remain canonical. Canonical disclosures and stronger bias warnings survive selection. |
| Reddit | Bounded deferred permitted public text; existing typed model interpretation | 1,600-character views support focus/offset. Public provenance, dates, independent supporting quotes, qualitative caveats and access gaps remain. No private/deleted content fallback. |
| Amazon and IKEA | Exact typed fact projection; existing scoped tools | Marketplace, ASIN/variant/seller, regional price/stock, review risks, official-store country and shipping limits remain. A global page is not local availability. |
| Comparison and verification | Exact typed canonical support; JSON projection | Original evidence claims/IDs, listings, amounts, conflicts and trust flags pass unchanged. Verifier reloads same-run canonical evidence and checks exact page support or validated specialist source records before model approval. Its bounded snapshot tool can reload context; derived analyses cannot establish new factual support. |
| Recovery and refinement reuse | Current typed state; same bounded gateway | Recovery uses the original owner allowance. New refinements get a new run ledger and current constraints. Same-region/currency budget refinements reuse saved evidence; region/currency changes invalidate reuse. Persisted support retains original provenance. |
| Extra model summarizer | Not added | Measured mechanical savings avoid another model call. Existing typed interpretation is semantic work; its output cannot establish a fact without validated original support. |

An explicitly processed body can leave active history after exact retained facts,
cautions, gaps and unresolved coverage are recorded with original lookup.
Without that checkpoint, only complete exact quotation or an identical retained
read can replace a body. A partial quote alone cannot retire a different read or
assess its unquoted remainder. SDK pairs remain intact. The approved lookup
reloads a bounded canonical span; no model can supply an arbitrary filesystem
path. Tool exhaustion closes only that issuing owner's quota. Omitted passages
remain unreviewed, and categorical safety assurances require the completion
checks described below.

Source managers and owner consultations project validated source bundles into
exact cited evidence and metadata without replaying raw caption/discussion text.
Full canonical support remains available for persistence and validation. Both
YouTube and Reddit require quotes to match an exact span actually read.

Verification reloads original permitted captions and public discussion text for
semantic review records. It revalidates quotes with the existing source creators
and keeps only bounded exact support plus IDs, timestamps, dates and full-text
hashes in the prompt. Its snapshot tool can reload bounded caption/discussion
spans when a metadata-only snapshot has no page body. Full captions, discussion
text and descriptions stay canonical. Amazon provider facts selected unchanged
by the model remain exact canonical provider records; derived marketplace/store
statements are reconstructed from persisted seller, region, price and stock
fields. Derived narrative cannot establish a new product fact.

The recording boundary verifies exact quotes against the original snapshot and
an observed span. Activity retains snapshot ID, offsets and full-content SHA-256;
canonical `SourceEvidence.claim` retains the exact quote. Tests reconstruct
late-page quotes and reject unread, fabricated or cross-run support. Canonical
quote records reach the verifier intact. Extraction and verification reload
original support by assigned same-run ID. Extraction claims must be exact
substrings of one observed span, not fabricated paraphrases or spliced reads;
product/listing interpretation remains in the typed entity fields. Existing owner
validation checks support against persisted snapshots before accepting a draft.
A valid ID alone never authorizes a fabricated claim. External content remains
untrusted after projection. No recursive model summaries replace source records.

## Limits and accounting

Every production SDK wrapper uses `BoundedRunner` and a model-provider adapter.
The SDK input filter runs on each turn, including transfers and nested
`Agent.as_tool` runs. Configured model names resolve through the adapter; direct
model objects, hidden remote conversation history and uncomposed input filters
are rejected to prevent bypasses. Shopping uses non-streaming runs.

| Bound | Default |
| --- | --- |
| Known input per model request | 19,000 estimated tokens, including instructions and schemas |
| Output per request | Lower of role limit and 5,000 tokens |
| Whole shopping pipeline | 150,000 cumulative tokens |
| Owner plus nested sources and recovery | Existing 90,000-token ceiling |
| Source manager plus nested specialists | Existing 30,000-token ceiling |
| Reserved final comparison | 24,000 tokens |
| Reserved verification | 24,000 tokens |
| Hosted search uncertainty per enabled request | 8,000 tokens |

The whole-pipeline bound also covers stages outside the existing owner ceiling.
It does not enlarge the 90,000-token owner allowance. Known-input estimates add
25% plus 256 tokens for tokenizer/wrapper uncertainty; output and hosted reserves
are additional. These defaults are conservative offline assumptions, not a
calibrated guarantee about hosted-tool internals or a model's context window.
Each final-step reserve funds the maximum known input plus output bound.
Large exact inputs fail explicitly rather than silently truncating constraints.

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

Before research consumes reserved decision/verification room, the adapter closes
research tools and handoffs and requests a bounded final output from existing
support. If that final output cannot be funded or violates the input bound, or
if the model keeps requesting a closed tool, the run stops with
`ContextBudgetExceeded`. Owner recovery does not retry this failure. An empty
owner result under forced finalization is also a technical failure. It cannot
become a completed no-strong-buy judgment. The same guard applies to recovery. Owner rationale now carries bounded exact
quotes instead of describing review provenance as a product fact; purchase
price, regional availability and seller trust remain explicitly unchecked. Budget exceptions wrapped by SDK tool
errors propagate as technical failures. The completion guards retain their
90,000/30,000-token ceilings without adding overlapping child totals.

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
spans carry content hashes so a changed snapshot cannot reuse stale quote proof.
Concurrent/refined runs cannot reuse another run's handles or mutable ledger.

Success, failure, timeout and cancellation reset in-memory context scopes.
Process exit discards them, so there are no abandoned context files to reclaim.
Tests cover cancellation during a model request, concurrent scopes, durable page
preservation and invalid/cross-run/path handles. Audit reports and test scratch
stay under ignored repository `data/artifacts`; gate scripts remove disposable
test/cache directories on exit. Canonical evidence and useful diagnostics follow
[existing artifact retention](OPERATIONS.md#persistence-and-artifacts).

## Verification

Run the Task 100B gate from the repository root:

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
The owner completion boundary rejects categorical safety, legitimacy and
warranty assurances over relevant unreviewed support. It checks cited source
rows separately so another variant cannot supply safety or conflict context.
Local-warranty assertions need an exact cited passage and cannot override a
known conflicting or deferred warranty caution. The technical failure code
`unreviewed_research` returns a precise gap and does not trigger an automatic
recovery attempt. This deterministic safeguard covers explicit assurance
forms, including safe purchases, reputable or authentic sellers/products and
no-warning claims; it is not a general semantic judge.
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
returning bounded useful views. `read_source_bundle` reloads exact versions
by bundle or consultation identity. The combined owner reply is capped at
11,000 characters before lifecycle metadata, using consistent UTF-8 JSON. A missing original or wrong run cannot
authorize lookup or retirement. Source-specific tools remain the authority for
full page, transcript, discussion and typed regional-store support.

Search returns at most four initial leads with 200-character previews. Deferred
IDs and a next offset make omitted leads explicit. `read_search_results` pages
the original same-run batch or reads a full original snippet by source ID with
focus and offsets. Snippet cautions are discovery cautions, never page support.
Changed snippet/title records get distinct identities; variants and sellers
remain separate. Compatible run, region, policy and provider instances share
completed query and observed-source state across ownership transfers. Changed
consultation constraints or source versions invalidate reuse.

Owner evidence reads expose offsets, hashes, total size and unresolved coverage.
They retain up to six exact caution previews of at most 300 characters from
the canonical original, including ones beyond the first 2,000-character span.
Deferred or truncated cautions carry counts, focus terms and an explicit
unreviewed marker. Full original lookup remains available. Empty default
metadata is omitted from model-facing views. Assigned category analysts receive
the selected route rather than the whole routing registry. Unmatched products
receive an explicit evidence gap, not unrelated evidence. Repeated identical
video metadata is represented once with exact per-claim references. Canonical
verification runs before typed original-support projection; bounded rereads
retain the full original support. Distinct recommendation and refinement
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
