# Context retention review

Reviewed on 2026-10-08. This is an audit of current behavior and planned repairs,
not evidence that Task 211 or live acceptance has passed. No live model/provider
calls ran. The implementation remains at the existing 16,000 estimated-input
limit; Task 211 plans 19,000 input and 24,000 final-step reserves while retaining
the 150,000 workflow, 90,000 owner and 30,000 source-manager cumulative ceilings.

## What enters a model request

Each request contains current-role instructions, available tool and handoff
definitions, the required answer schema, and prepared input/history. Original
records in SQLite and internal Python objects do not consume model context
unless a prompt builder or tool reply serializes them into the request. Tool
caching avoids repeated provider work, but does not automatically remove a
cached result from the conversation. Each child agent has its own input/history
and contributes to shared usage. Owner handoffs continue the current conversation.

The current preparation removes JSON whitespace and certain exact duplicates.
An earlier fetched text leaves history only when one later exact quote covers
the entire text or an identical read remains elsewhere. Distinct unquoted text
survives. This avoids the earlier partial-quote warning loss, but lacks a general
processed-result lifecycle. Returning a result does not prove it has been read;
after consumption, useful facts and cautions should replace the bulky body.

The saved failed phone attempt has the following request composition:

| Component | Characters | Local estimated tokens |
| --- | ---: | ---: |
| Smartphone instructions | 5,739 | 1,913 |
| Tool/output schemas | 7,720 | 2,574 |
| Brief and accumulated history | 28,279 | 9,456 |

History includes 20,534 tool-result characters, 6,569 prior-turn/handoff
characters and 1,148 brief characters. The estimator uses UTF-8 bytes divided
by three, then applies 25% plus 256 to the combined estimate: 17,685. This
exceeded the application's 16,000 per-call guard before transport. Whole-run
settled usage was 22,976, including 21,986 owner tokens. The cumulative budget
was not exhausted, and actual tokens for the blocked call are unknown.
The 6,569-character group is not proven to consist entirely of removable handoff
text; the saved data does not contain a replayable full history for that group.

## Execution and coverage

The review covers 25 catalog contracts/initial input constructions and seven
constructed receiving owners. Initial fixtures are not 25 stages measured in
one live run. Actual SDK handoffs and research-tool counterexamples were run
offline with scripted models, fixture providers and network connections denied.
Current saved live evidence ends before fetching, source consultations and
downstream decisions. Their measurements below are constructed offline shapes.

| Stage | Current context use | Retention assessment |
| --- | --- | --- |
| Guide and Intake | Original request, effective answers, region, budget and question state | Keep shopper facts. Guide's generated ready brief is later overwritten by Intake; Task 212 removes this duplicate model output. |
| General, Technology, product owner | Current brief, owner instructions, tools and growing SDK conversation | Handoffs inherit history. Retire processed application results with compact useful state and SDK-valid receipts. |
| Owner research | Search previews, fetched spans, quotes, evidence readers, comparisons, trust and source bundles | Largest demonstrated replay. Caches and persistence currently do not supply a uniform consumption/retirement boundary. |
| Query planning and Discovery | Brief, research plan, candidate hints and search-lead projections | Scheduled after successful ownership. Some projections already exist; bound snippets and exclude unused fields without losing lead coverage. |
| Extraction | First bounded page view, deferred page IDs, hints and exact supporting spans | Existing selective retrieval is useful. Later completed reads still need retirement; unread material must remain accessible. |
| Source manager and source agents | Capability-scoped helper inputs, local reads and validated returned bundles | Child transcripts are isolated. Returned bundle details and repeated cached/local reads remain candidates for retirement. |
| Category analysis | One selected product, listings, evidence, category guidance and routing data | Remove irrelevant registry data and scope evidence to its subject; retain legitimate comparison/shared-source cautions. |
| Listing trust | One listing, regional evidence and deterministic risk assessment | Preserve hard flags. Repeated identical explanations can be represented once. |
| Comparison | Candidate/evidence graph and explanations | Normal owner-draft path assembles the comparison without another comparison model. No-owner/refinement paths use the model. Project referenced useful state without losing alternatives or graph edges. |
| Verification | Recommendation, candidate graph, evidence and canonical support descriptors | Plain-page originals are already locator-based. Nested source metadata and typed support can repeat; preserve independently validated support and scoped rereads. |
| Refinement and recovery | Current constraints and reusable artifacts; recovery starts a fresh bounded owner input | Refinement is fresh typed state, not replay of the old SDK conversation. Reuse compatible support; preserve invalidation and current gaps. Recovery does not replay the entire failed specialist history. |

Ordinary successful owner runs still schedule query planning, discovery and
extraction. Stage/candidate gates determine which agents actually run. This
audit does not prove those stages redundant and does not authorize removing
them. Their outputs may be needed to build and validate persisted entities.

## Demonstrated removable or reducible payloads

| Finding | Evidence | Planned replacement |
| --- | --- | --- |
| Full search snippets | Reconstructed replies for the 16 saved leads occupy 20,177 tool-result characters. Illustrative 200-character previews reduce that to 8,333, about 59%. This is not a warning-preservation proof. | Short previews and a bounded initial batch; all leads remain retrievable. After selection, carry selected/deferred/excluded state rather than the full lists. |
| Cached search replay | The actual cached tool returns its entire prior reply again; history retains both. | A compact unchanged-result receipt after the first view is consumed, with useful active lead state and lookup. |
| Consumed fetched bodies | Default fetch view is 4,000 characters; quotes are capped at 400. A body over 400 cannot equal one accepted quote. | Verified fact/quote/caution/gap state plus canonical source/version/span references. Do not require the entire page to be quoted. |
| Evidence readers and nested comparisons | Two actual 2,000-character evidence reads and a nested comparison retain 10,272 history characters after preparation, versus 10,361 before. | Facts/conflicts and quote references once; compact completed receipts instead of copied source objects. |
| Unmarked evidence truncation | Owner reader takes a 2,000-character prefix without an omission marker. A synthetic later caution is in the fetched original but absent from that prefix. | Explicit omitted/unreviewed status and offset/focus retrieval. Retain known late cautions before retiring the earlier body. This is not an observed live warning loss. |
| Repeated source reads and bundles | Two fixture-shaped Amazon reads retain 14,790 characters. Amazon/IKEA active provider-bundle projections retain 6,986/4,135 characters before final specialist selection. | Role-specific validated findings and safety state; original source/bundle lookup. Parent and purchasing owner may need different detail. |
| Reject-only owner bundle limit | Owner consultation rejects projected bundles over 12,000 characters after child work. It does not produce a smaller useful result. | A bounded usable result and continuation/retrieval. Establish durable or retained run-local original support before retiring body text. |
| Nested video descriptions | Four synthetic claim rows repeat a 4,480-character description. Removing only those repeated descriptions changes verifier input from 26,372 to 8,376 characters. | Source metadata once, referenced from claims. Retain sponsorship/bias warnings and validated description-dependent facts or scoped reads. |
| Full routing registry in assigned analyses | Removing the registry alone saves 974–1,009 characters per specialist and 1,242 for Technology in fixtures. | The selected route, required category coverage and relevant fallback/gap state. Backend catalog remains authoritative. |
| Unmatched evidence fallback | The real product-selection helper returns all three unrelated fixture records, 1,936 characters, when no exact match exists. | Explicit subject/relevance selection and an honest missing-evidence gap. Coordinate existing Task 188; do not erase legitimate shared cautions or comparison context. |
| Typed original support and explanations | A synthetic Amazon support descriptor adds 1,342 characters and repeats its claim three times. Trust/comparison also contain smaller exact repeated explanations. | One validated supporting fact with required provenance, warning and retrieval state; reference shared explanations without flattening distinct reasons. |
| Backend-owned output copies | A guide fixture generates a 608-character ready brief that Intake replaces. An unchanged verifier approval copies a 1,387-character bundle into a 1,568-character report. | Narrow internal model decisions and backend assembly of unchanged public state, in Task 212. Preserve actual revisions and independent verification. |

Cross-owner tools have fresh local caches/counters, so a new owner can repeat
finished research. Reuse compatible same-run completion state at transfers,
without treating failed/unprocessed work or old regional facts as current.
Small quote receipts, provenance wrappers and repetitive handoff explanations
are secondary candidates after the large bodies. Tool definitions may be
disabled when their quota is known closed; required schemas are not disposable
merely because they recur on each request.

## What must remain

Keep current shopper constraints and unlimited-versus-missing budget semantics,
product/variant/listing identity, exact quote evidence, source associations,
region/price/seller context, conflicts, known cautions and explicit unresolved
coverage. Keep canonical permitted originals and same-run retrieval. Preserve
new unprocessed views until interpreted. IDs alone cannot replace useful
findings or establish evidence. Do not discard opaque hosted-search/reasoning
items without supported SDK continuation proof.

The current source manager advertises only allowed capabilities and disables
called capabilities; a one-capability fixture has one tool. Source inputs do
not indiscriminately embed full snapshots/listings. YouTube/Reddit parent
projections already remove raw transcript/discussion bodies. Plain-page
verification already uses support locators with bounded rereads. These are
working controls, not fat to remove.

Owner consultation does not use the ordinary pipeline's full source-bundle
persistence hook. A retirement implementation must establish same-run durable
support or retain canonical bundle state for its lookup tool. A bare reference
to a record that was never saved would lose the information.

## Planned execution and evidence

Task 211 owns active-history retirement, purpose-specific input projection,
cached/result references, source metadata sharing, explicit truncation and
retrieval, and measured end-to-end offline behavior with added headroom.
Task 212, later priority, owns narrower model outputs for the guide and verifier.
Task 188 already covers product-specific evidence attachment and must not be
duplicated. Task 100A still requires real guided acceptance after P0 passes.

Repeatable tools and detailed slice reports are under
`data/artifacts/context-fat-20261008/`: census.py, owner.py, sources.py,
downstream.py and their JSON/report outputs. They contain no credentials or raw
private payloads. They do not implement these repairs, prove live savings or
establish buying-result quality. Fixed overhead still needs model-appropriate
calibration; it is not interchangeable with cumulative usage.

## Task 211 accepted repair

The findings above describe the pre-repair census. Task 211 is now accepted
with production processing/retrieval and downstream projection changes.
The actual scripted SDK phone/generic probes show 52.57%/52.62% post-search
tool-output reductions and supported decisions followed by approved
verification. Fresh measurements are in `data/artifacts/task211/acceptance.json`
and `data/artifacts/task211-downstream/measurements.json`; rerunnable tools
sit beside them. The complete deduplicated offline gate is recorded in
`data/artifacts/task211/gate-deduplicated.log`. Task 212's model-output findings
and Task 100A's real guided acceptance remain open.
