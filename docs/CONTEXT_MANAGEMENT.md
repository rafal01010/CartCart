# Context management

Task 100B is complete with bounded SDK inputs and shared accounting. Its gate is
recorded in [EVALUATION.md](EVALUATION.md#context-management-gate). Live phone
acceptance remains Task 100A and requires separate authorization.

## What caused the investigation

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

The existing owner and QueryPlanner already rewrite shopper wording into
purpose-specific regional research queries. Their unlimited-budget/current-date
repair remains intact. Context management must retain the distinction between
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
brief, especially for extraction. Synthetic eight-page history shrinks from
95,276 characters, estimated 31,759 tokens, to 6,143 characters, estimated 2,048
tokens. Exact quotes, arguments, source IDs, warnings and call pairs remain.
SDK replay tests exercise both ownership transfers, generic decisions, refinement
region changes and nested source delegation. Their usage is deliberately
simulated. They prove transport/accounting contracts, not live reasoning quality.

## Stage and field handling

| Stage or field | Handling | Information retained and why |
| --- | --- | --- |
| Intake, guide and scope | Exact strings; deterministic JSON projection | Original wording, answer order, explicit preferences, missing versus unlimited money, budget and region. No answer deduplication. |
| General, Technology and product ownership | Project exact typed state; defer completed page bodies | Keep original brief, ownership transfers, arguments, source IDs, gaps and recorded exact quotes. Keep every unquoted read so it can be cited, including later reads of a previously quoted source. |
| SDK prior turns and bookkeeping | Remove completed body text; minify structured results | Every tool call/output pair, unquoted read and handoff remains. Opaque hosted-search/reasoning items remain; arbitrary deletion could break SDK history. |
| QueryPlanner and discovery | Preserve derived queries separately; deduplicate identical research | Queries use purpose, identity, current region/date and gaps. Original request stays unchanged. Cache keys include query, intent, region and result limit. |
| Extraction | Bounded deferred page retrieval; exact validation | Default 4,000-character reads support offset/focus lookup. Large prefetched page sets use metadata/handles instead. Interpret only text actually read; canonical snapshots remain complete. |
| Products, listings, evidence, analysis and trust | Project JSON; remove byte-identical records with IDs | Preserve differing variants, sellers, prices, currencies, sources, dates, conflicts and hard flags. Same ID with different content is not a duplicate. |
| Dedupe | Existing deterministic service | No extra model or parallel summary state. Full source URLs distinguish offer variants. |
| YouTube | Bounded deferred permitted captions; existing typed model interpretation | Six segments per read, at most 1,000 characters each; focus/segment offsets reach late facts. Original segment IDs/text/timestamps remain canonical. Canonical disclosures and stronger bias warnings survive selection. |
| Reddit | Bounded deferred permitted public text; existing typed model interpretation | 1,600-character views support focus/offset. Public provenance, dates, independent supporting quotes, qualitative caveats and access gaps remain. No private/deleted content fallback. |
| Amazon and IKEA | Exact typed fact projection; existing scoped tools | Marketplace, ASIN/variant/seller, regional price/stock, review risks, official-store country and shipping limits remain. A global page is not local availability. |
| Comparison and verification | Exact typed canonical support; JSON projection | Original evidence claims/IDs, listings, amounts, conflicts and trust flags pass unchanged. Verifier checks canonical support rather than a replacement narrative summary. |
| Recovery and refinement reuse | Current typed state; same bounded gateway | Recovery uses the original owner allowance. New refinements get a new run ledger and use current intent/region; persisted support retains original provenance. |
| Extra model summarizer | Not added | Measured mechanical savings avoid another model call. Existing typed interpretation is semantic work; its output cannot establish a fact without validated original support. |

A page read leaves active history only after a subsequent successful quote from
that source. A prior quote cannot hide a newer focused read. The replacement
contains size and hash metadata. The same approved tool can reread a bounded
span from the canonical source. No model can supply an arbitrary filesystem path. Tool quotas
remain bounded, and exhaustion removes that tool from subsequent requests.
Unquoted narrative may need another focused read; removing a page body does not
assert that its omitted content was understood or summarized.

Source managers and owner consultations project validated source bundles into
exact cited evidence and metadata without replaying raw caption/discussion text.
Full canonical support remains available for persistence and validation. Both
YouTube and Reddit require quotes to match an exact span actually read.

The recording boundary verifies exact quotes against the original snapshot and
an observed span. Activity retains snapshot ID, offsets and full-content SHA-256;
canonical `SourceEvidence.claim` retains the exact quote. Tests reconstruct
late-page quotes and reject unread, fabricated or cross-run support. Canonical
quote records reach the verifier intact; original snapshot tools reload support
by assigned same-run ID when extraction needs more context. Existing owner
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
| Known input per model request | 16,000 estimated tokens, including instructions and schemas |
| Output per request | Lower of role limit and 5,000 tokens |
| Whole shopping pipeline | 150,000 cumulative tokens |
| Owner plus nested sources and recovery | Existing 90,000-token ceiling |
| Source manager plus nested specialists | Existing 30,000-token ceiling |
| Reserved final comparison | 10,000 tokens |
| Reserved verification | 8,000 tokens |
| Hosted search uncertainty per enabled request | 8,000 tokens |

The whole-pipeline bound also covers stages outside the existing owner ceiling.
It does not enlarge the 90,000-token owner allowance. Known-input estimates add
25% plus 256 tokens for tokenizer/wrapper uncertainty; output and hosted reserves
are additional. These defaults are conservative offline assumptions, not a
calibrated guarantee about hosted-tool internals or a model's context window.
Large exact inputs fail explicitly rather than silently truncating constraints.

Reservations happen synchronously before awaiting transport, so concurrent
nested calls share remaining capacity. Actual response usage settles the
reservation once per transport request. Parent SDK aggregate usage is not added
again to the shared ledger. Owner/source allowances enforce their own subset
ceilings; their totals are not summed into run usage. Failed, cancelled or
zero-usage requests consume their full reservation because actual cost is unknown.
No SDK retry advice is supplied. Provider/client-internal network retry costs
cannot be inferred from local input sizes; returned usage and the completion
backstop remain necessary.

Before research consumes reserved decision/verification room, the adapter closes
research tools and handoffs and requests a bounded final output from existing
support. If that final output cannot be funded or violates the input bound, or
if the model keeps requesting a closed tool, the run stops with
`ContextBudgetExceeded`. Owner recovery does not retry this failure. An empty
owner result under forced finalization is also a technical failure. It cannot
become a completed no-strong-buy judgment. Original completion guards remain.

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
