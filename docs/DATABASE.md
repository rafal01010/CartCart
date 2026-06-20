# CartCart Database

Status: Initial SQLite persistence reference
Last updated: 2026-06-02

This document describes the current local database schema implemented by SQLAlchemy
ORM models and Alembic migrations `0001_initial_persistence_schema` and
`0002_reusable_source_intelligence_persistence`.

The database is a local SQLite database. By default it lives at
`data/cartcart.sqlite3`; `CARTCART_DATABASE_PATH` can override it. Large raw
artifacts belong in files under `data/artifacts/`, not in SQLite. SQLite stores
structured records, IDs, provider metadata, links, evidence summaries, and JSON
snapshots of typed Pydantic objects.

## Operational Notes

- Migration config: `apps/backend/alembic.ini`.
- Current baseline migration: `apps/backend/alembic/versions/0001_initial_persistence_schema.py`.
- Current source-intelligence backfill migration:
  `apps/backend/alembic/versions/0002_reusable_source_intelligence_persistence.py`.
- ORM base: `apps/backend/app/db/base.py`.
- ORM models: `apps/backend/app/db/models/`.
- Repository classes: `apps/backend/app/db/repositories/`.
- Naming convention: primary keys use `pk_<table>`, foreign keys use
  `fk_<table>_<column>_<referred_table>`, indexes use explicit names.
- Timestamp columns are ISO-8601 strings with length 35.
- Entity IDs are UUID strings with length 36 unless noted.
- JSON columns store validated Pydantic payloads as structured JSON.
- No database triggers are currently defined.
- No FTS, vector index, or materialized view exists yet.

## Schema Overview

The schema is organized around a shopping session, one or more runs, source and
product evidence gathered during runs, and versioned recommendation results.

```text
shopping_sessions
  -> shopping_runs
     -> run_events
     -> refinement_requests
     -> search_plans -> search_results -> source_snapshots -> source_evidence
     -> video_sources / video_transcript_segments / video_review_evidence_bundles
     -> community_discussion_evidence_bundles / community_discussion_contexts
     -> amazon_product_evidence_bundles / amazon_listing_contexts
     -> ikea_store_evidence_bundles / ikea_store_contexts
     -> reusable_source_evidence_gaps
     -> canonical_products -> product_listings
     -> candidate_shortlist_memberships
     -> listing_trust_assessments / category_analyses
     -> comparison_matrices -> recommendation_bundles -> result_versions

shopping_sessions
  -> user_added_products
```

## Tables

### `shopping_sessions`

Stores the user-facing session, original input, and current shopping brief.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `session_id` | `String(36)` | No | Primary key. |
| `original_query` | `String(4000)` | No | Original natural-language shopping query. |
| `original_input` | `JSON` | No | Full create-session request payload. |
| `current_brief` | `JSON` | No | Current `ShoppingBrief`, including corrections. |
| `created_at` | `String(35)` | No | Creation timestamp. |
| `updated_at` | `String(35)` | No | Last update timestamp. |

### `shopping_runs`

Stores each workflow run for a session and its latest status.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `run_id` | `String(36)` | No | Primary key. |
| `session_id` | `String(36)` | No | FK to `shopping_sessions.session_id`. |
| `status` | `String(30)` | No | Latest run status. |
| `current_stage` | `String(60)` | Yes | Current or latest workflow stage. |
| `created_at` | `String(35)` | No | Creation timestamp. |
| `started_at` | `String(35)` | Yes | Run start timestamp. |
| `completed_at` | `String(35)` | Yes | Completion timestamp. |
| `error` | `JSON` | Yes | User-safe structured error details. |

### `run_events`

Stores ordered progress events for a run, suitable for status history and SSE.
The deduplication stage event includes the pre-dedupe extracted product count,
post-dedupe product-group count, preserved listing count, and collapsed duplicate
count in its user-safe message.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `event_id` | `String(36)` | No | Primary key. |
| `run_id` | `String(36)` | No | FK to `shopping_runs.run_id`. |
| `sequence` | `Integer` | No | Per-run event order. |
| `stage` | `String(60)` | No | Workflow stage. |
| `status` | `String(30)` | No | Event status. |
| `message` | `String(1000)` | No | User-safe progress message. |
| `occurred_at` | `String(35)` | No | Event timestamp. |
| `error` | `JSON` | Yes | Optional structured error details. |

Constraint: unique `(run_id, sequence)`.

### `refinement_requests`

Stores user refinement requests and links each request to the new stub run that
will eventually execute the refinement.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `refinement_id` | `String(36)` | No | Primary key. |
| `session_id` | `String(36)` | No | FK to `shopping_sessions.session_id`. |
| `run_id` | `String(36)` | No | FK to the new `shopping_runs.run_id`. |
| `instruction` | `String(1000)` | No | User-supplied refinement instruction. |
| `created_at` | `String(35)` | No | Creation timestamp. |
| `refinement` | `JSON` | No | Full `RefinementRequest` payload. |

### `search_plans`

Stores the query/source strategy generated for a run.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `plan_id` | `String(36)` | No | Primary key. |
| `run_id` | `String(36)` | No | FK to `shopping_runs.run_id`. |
| `plan` | `JSON` | No | Full `SearchPlan` payload. |
| `created_at` | `String(35)` | No | Creation timestamp. |

### `search_results`

Stores provider search result records before source snapshot/extraction.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `source_id` | `String(36)` | No | Primary key and stable source identifier. |
| `run_id` | `String(36)` | No | FK to `shopping_runs.run_id`. |
| `plan_id` | `String(36)` | Yes | FK to `search_plans.plan_id`. |
| `url` | `String(2048)` | No | Result URL. |
| `provider_name` | `String(120)` | No | Search provider name. |
| `provider_result_id` | `String(300)` | Yes | Provider-specific result ID when available. |
| `provider_query_id` | `String(300)` | Yes | Provider-specific query ID when available. |
| `result` | `JSON` | No | Full `SearchResult` payload. |

### `source_snapshots`

Stores structured source snapshot metadata linked to a run and optional search
result. Successful HTTP fetches store large raw page bodies as files beneath the
configured raw-source artifact directory. The JSON payload references the file by
relative path and records its content type, byte size, SHA-256 hash, and HTTP status.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `source_id` | `String(36)` | No | Primary key. |
| `run_id` | `String(36)` | No | FK to `shopping_runs.run_id`. |
| `search_result_id` | `String(36)` | Yes | FK to `search_results.source_id`. |
| `url` | `String(2048)` | No | Snapshot URL. |
| `provider_name` | `String(120)` | No | Provider/fetcher name. |
| `provider_result_id` | `String(300)` | Yes | Provider-specific result ID when available. |
| `provider_query_id` | `String(300)` | Yes | Provider-specific query ID when available. |
| `snapshot` | `JSON` | No | Full `SourceSnapshot` payload. |
| `captured_at` | `String(35)` | No | Capture timestamp. |

### `source_evidence`

Stores source-backed claims or extracted evidence snippets.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `evidence_id` | `String(36)` | No | Primary key. |
| `run_id` | `String(36)` | No | FK to `shopping_runs.run_id`. |
| `source_id` | `String(36)` | No | FK to `source_snapshots.source_id`. |
| `evidence_type` | `String(60)` | No | Evidence category. |
| `evidence` | `JSON` | No | Full `SourceEvidence` payload. |

### `video_sources`

Stores video source metadata and transcript availability, without assuming
transcripts are available.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `video_record_id` | `String(36)` | No | Primary key for the persisted video record. |
| `run_id` | `String(36)` | No | FK to `shopping_runs.run_id`. |
| `source_id` | `String(36)` | No | FK to `source_snapshots.source_id`. |
| `video_id` | `String(128)` | No | Provider video ID. |
| `url` | `String(2048)` | No | Video URL. |
| `channel_id` | `String(128)` | Yes | Provider channel ID. |
| `channel_name` | `String(200)` | Yes | Display channel name. |
| `transcript_availability` | `String(40)` | No | Transcript availability state. |
| `channel_metadata` | `JSON` | No | Channel signals and bias metadata. |
| `video` | `JSON` | No | Full `VideoSource` payload. |

### `video_transcript_segments`

Stores transcript segments only where permitted or explicit transcript gaps when
segments are unavailable.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `segment_id` | `String(36)` | No | Primary key. |
| `run_id` | `String(36)` | No | FK to `shopping_runs.run_id`. |
| `video_id` | `String(128)` | No | Provider video ID. |
| `start_seconds` | `Float` | No | Segment start timestamp. |
| `end_seconds` | `Float` | Yes | Segment end timestamp. |
| `availability` | `String(40)` | No | Segment/transcript availability state. |
| `text` | `String(5000)` | Yes | Transcript text when permitted. |
| `gap_reason` | `String(500)` | Yes | Reason transcript text is unavailable. |
| `segment` | `JSON` | No | Full `VideoTranscriptSegment` payload. |

### `video_review_evidence_bundles`

Stores grouped video-review evidence output for a run.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `bundle_id` | `String(36)` | No | Primary key. |
| `run_id` | `String(36)` | No | FK to `shopping_runs.run_id`. |
| `bundle` | `JSON` | No | Full `VideoReviewEvidenceBundle` payload. |

### `video_review_evidence`

Stores timestamped video evidence and links it to products, listings, candidates,
sources, runs, bundles, and future recommendation claims.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `evidence_id` | `String(36)` | No | Primary key. |
| `bundle_id` | `String(36)` | No | FK to `video_review_evidence_bundles.bundle_id`. |
| `run_id` | `String(36)` | No | FK to `shopping_runs.run_id`. |
| `source_id` | `String(36)` | No | FK to `source_snapshots.source_id`. |
| `video_id` | `String(128)` | No | Provider video ID. |
| `target_type` | `String(60)` | No | Product/listing/candidate/seller/source target type. |
| `product_id` | `String(36)` | Yes | Target canonical product ID. |
| `listing_id` | `String(36)` | Yes | Target listing ID. |
| `candidate_id` | `String(36)` | Yes | Target candidate ID. |
| `seller_name` | `String(200)` | Yes | Target seller name. |
| `source_target_id` | `String(36)` | Yes | Target source ID for source-only metadata. |
| `recommendation_claim_id` | `String(120)` | Yes | Future link to a recommendation claim. |
| `metadata_only` | `Boolean` | No | True when evidence is metadata-only. |
| `evidence` | `JSON` | No | Full `VideoReviewEvidence` payload. |

### Reusable source-intelligence evidence tables

Task 24B backfills persistence for required reusable source intelligence beyond
YouTube. The new tables store typed bundle JSON for exact round trips and
separate indexed target columns so downstream code can query product-level,
listing-level, seller-level, review-level, and region-level facts without
collapsing them into one generic evidence blob.

| Table | Purpose |
| --- | --- |
| `community_discussion_evidence_bundles` | Full `CommunityDiscussionEvidenceBundle` payloads for Reddit/community source-intelligence runs. |
| `community_discussion_contexts` | Reddit/community thread and comment context, linked to source snapshots. |
| `community_discussion_evidence` | Community claims with run/source/bundle links, confidence, target columns, recurring-signal flags, and optional future recommendation-claim IDs. |
| `amazon_product_evidence_bundles` | Full `AmazonProductEvidenceBundle` payloads for product/listing/review marketplace evidence. |
| `amazon_listing_contexts` | Marketplace, ASIN/listing, seller, fulfillment, rating, and regional shipping context linked to source snapshots. |
| `amazon_product_evidence` | Amazon product-page, listing identity, seller/fulfillment, review, price/warranty, marketplace warning, and regional availability facts. |
| `ikea_store_evidence_bundles` | Full `IKEAStoreEvidenceBundle` payloads for official regional IKEA evidence. |
| `ikea_store_contexts` | Official country/store/product-code, price, delivery-area, and availability context linked to source snapshots. |
| `ikea_store_evidence` | IKEA official product facts and regional price/availability/store-delivery facts. |
| `reusable_source_evidence_gaps` | Missing or low-quality evidence gaps from Reddit, Amazon, and IKEA bundles, preserving capability, source, target, and optional recommendation-claim links. |

The evidence tables intentionally mirror the target shape used by
`video_review_evidence`: `run_id`, `source_id`, `bundle_id`, `target_type`,
`product_id`, `listing_id`, `candidate_id`, `seller_name`, `review_id`,
`region_code`, `source_target_id`, `recommendation_claim_id`, and a full JSON
payload. Amazon and IKEA evidence also persist source-context links
(`listing_context_source_id` or `store_context_source_id`) so listing/store
facts remain tied to the source snapshot that produced them.

### `canonical_products`

Stores deduplicated product identities. Multiple listings can point to one
canonical product.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `product_id` | `String(36)` | No | Primary key. |
| `run_id` | `String(36)` | No | FK to `shopping_runs.run_id`. |
| `name` | `String(300)` | No | Canonical product name. |
| `brand` | `String(200)` | Yes | Brand identifier when known. |
| `model` | `String(200)` | Yes | Model identifier when known. |
| `category` | `String(200)` | Yes | Product category when known. |
| `product` | `JSON` | No | Full `CanonicalProduct` payload, including optional SKU/UPC/EAN identity fields when known. |

### `product_listings`

Stores listing-specific identity, seller, price, availability, and source-quality
details for a canonical product. Listing identity is not collapsed during
deduplication.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `listing_id` | `String(36)` | No | Primary key. |
| `run_id` | `String(36)` | No | FK to `shopping_runs.run_id`. |
| `product_id` | `String(36)` | No | FK to `canonical_products.product_id`. |
| `title` | `String(300)` | No | Listing title. |
| `url` | `String(2048)` | No | Listing URL. |
| `seller_name` | `String(200)` | No | Seller/store display name. |
| `seller_trust_signal` | `String(40)` | No | Extracted seller trust signal. |
| `captured_at` | `String(35)` | No | Capture timestamp. |
| `listing` | `JSON` | No | Full `ProductListing` payload, including optional canonical URL, retailer product ID, SKU, UPC, or EAN identity hints when known, plus listing-specific price, region availability, seller trust signal, and source quality. |

### `candidate_shortlist_memberships`

Links shortlist candidate IDs to canonical products and optional listings for a
run. After workflow deduplication, app-generated shortlist membership is one row
per grouped canonical product while all listing variants remain in
`product_listings`.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `membership_id` | `String(36)` | No | Primary key. |
| `run_id` | `String(36)` | No | FK to `shopping_runs.run_id`. |
| `candidate_id` | `String(36)` | No | Candidate identifier. |
| `product_id` | `String(36)` | No | FK to `canonical_products.product_id`. |
| `listing_id` | `String(36)` | Yes | FK to `product_listings.listing_id`. |
| `position` | `Integer` | Yes | Shortlist position. |
| `created_at` | `String(35)` | No | Creation timestamp. |

Constraint: unique `(run_id, candidate_id)`.

### `user_added_products`

Stores products or product URLs manually supplied by the user.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `candidate_id` | `String(36)` | No | Primary key and candidate identifier. |
| `session_id` | `String(36)` | No | FK to `shopping_sessions.session_id`. |
| `run_id` | `String(36)` | Yes | FK to `shopping_runs.run_id` when tied to a run. |
| `product_id` | `String(36)` | Yes | FK to `canonical_products.product_id`. |
| `listing_id` | `String(36)` | Yes | FK to `product_listings.listing_id`. |
| `input_text` | `String(1000)` | Yes | Manual user text. |
| `url` | `String(2048)` | Yes | User-supplied product/listing URL. |
| `created_at` | `String(35)` | No | Creation timestamp. |
| `user_added` | `JSON` | No | Full `UserAddedProduct` payload. |

### `listing_trust_assessments`

Stores trust analysis for a specific product listing. The JSON assessment
payload preserves deterministic signal rows for seller identity, established
retailer/source type, review count, return/warranty clarity, suspicious price,
missing metadata, and contradictory listing data so later agent output cannot
erase rule-based red flags.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `trust_assessment_id` | `String(36)` | No | Primary key. |
| `run_id` | `String(36)` | No | FK to `shopping_runs.run_id`. |
| `listing_id` | `String(36)` | No | FK to `product_listings.listing_id`. |
| `level` | `String(40)` | No | Trust level. |
| `assessed_at` | `String(35)` | No | Assessment timestamp. |
| `assessment` | `JSON` | No | Full `ListingTrustAssessment` payload. |

### `category_analyses`

Stores category/product analysis output for a canonical product.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `analysis_id` | `String(36)` | No | Primary key. |
| `run_id` | `String(36)` | No | FK to `shopping_runs.run_id`. |
| `product_id` | `String(36)` | No | FK to `canonical_products.product_id`. |
| `category` | `String(200)` | No | Analysis category. |
| `analysis` | `JSON` | No | Full `CategoryAnalysis` payload. |

### `agent_run_records`

Stores per-agent/stage execution records, including trace linkage when present.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `record_id` | `String(36)` | No | Primary key. |
| `run_id` | `String(36)` | No | FK to `shopping_runs.run_id`. |
| `stage` | `String(60)` | No | Workflow stage. |
| `agent_name` | `String(200)` | No | Agent or tool name. |
| `status` | `String(30)` | No | Agent run status. |
| `started_at` | `String(35)` | No | Start timestamp. |
| `ended_at` | `String(35)` | Yes | End timestamp. |
| `trace_id` | `String(300)` | Yes | Local or provider trace ID. |
| `record` | `JSON` | No | Full `AgentRunRecord` payload. |

### `comparison_matrices`

Stores saved comparison matrix output for a run.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `matrix_id` | `String(36)` | No | Primary key. |
| `run_id` | `String(36)` | No | FK to `shopping_runs.run_id`. |
| `matrix` | `JSON` | No | Full `ComparisonMatrix` payload. |
| `created_at` | `String(35)` | No | Creation timestamp. |

### `recommendation_bundles`

Stores final recommendation output and links to its comparison matrix and final
pick when one exists.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `bundle_id` | `String(36)` | No | Primary key. |
| `run_id` | `String(36)` | No | FK to `shopping_runs.run_id`. |
| `comparison_matrix_id` | `String(36)` | No | FK to `comparison_matrices.matrix_id`. |
| `final_product_id` | `String(36)` | Yes | FK to `canonical_products.product_id`. |
| `final_listing_id` | `String(36)` | Yes | FK to `product_listings.listing_id`. |
| `no_strong_buy` | `Boolean` | No | True when the result intentionally has no winner. |
| `bundle` | `JSON` | No | Full `RecommendationBundle` payload. |

### `result_versions`

Stores version pointers for run results so later refinements do not silently
overwrite previous outputs.

| Column | Type | Null | Purpose |
| --- | --- | --- | --- |
| `result_version_id` | `String(36)` | No | Primary key. |
| `run_id` | `String(36)` | No | FK to `shopping_runs.run_id`. |
| `version` | `Integer` | No | Version number within the run. |
| `recommendation_bundle_id` | `String(36)` | No | FK to `recommendation_bundles.bundle_id`. |
| `comparison_matrix_id` | `String(36)` | No | FK to `comparison_matrices.matrix_id`. |
| `created_at` | `String(35)` | No | Creation timestamp. |

Constraint: unique `(run_id, version)`.

## Indexes

Indexes currently support session/run lookup, ordered event retrieval, provider
lookup, URL lookup, product/model lookup, evidence linkage, and result version
lookup.

| Table | Indexes |
| --- | --- |
| `shopping_runs` | `ix_shopping_runs_session_id(session_id)` |
| `run_events` | `ix_run_events_run_id(run_id)`, `ix_run_events_run_id_sequence(run_id, sequence)` |
| `refinement_requests` | `ix_refinement_requests_session_id(session_id)`, `ix_refinement_requests_run_id(run_id)` |
| `search_plans` | `ix_search_plans_run_id(run_id)` |
| `search_results` | `ix_search_results_run_id(run_id)`, `ix_search_results_plan_id(plan_id)`, `ix_search_results_url(url)`, `ix_search_results_provider_name(provider_name)`, `ix_search_results_provider_result_id(provider_name, provider_result_id)`, `ix_search_results_provider_query_id(provider_name, provider_query_id)` |
| `source_snapshots` | `ix_source_snapshots_run_id(run_id)`, `ix_source_snapshots_search_result_id(search_result_id)`, `ix_source_snapshots_url(url)`, `ix_source_snapshots_provider_name(provider_name)`, `ix_source_snapshots_provider_result_id(provider_name, provider_result_id)`, `ix_source_snapshots_provider_query_id(provider_name, provider_query_id)` |
| `source_evidence` | `ix_source_evidence_run_id(run_id)`, `ix_source_evidence_source_id(source_id)` |
| `video_sources` | `ix_video_sources_run_id(run_id)`, `ix_video_sources_source_id(source_id)`, `ix_video_sources_video_id(video_id)`, `ix_video_sources_channel_id(channel_id)` |
| `video_transcript_segments` | `ix_video_transcript_segments_run_id(run_id)`, `ix_video_transcript_segments_video_id(video_id)` |
| `video_review_evidence_bundles` | `ix_video_review_evidence_bundles_run_id(run_id)` |
| `video_review_evidence` | `ix_video_review_evidence_bundle_id(bundle_id)`, `ix_video_review_evidence_run_id(run_id)`, `ix_video_review_evidence_source_id(source_id)`, `ix_video_review_evidence_video_id(video_id)`, `ix_video_review_evidence_product_id(product_id)`, `ix_video_review_evidence_listing_id(listing_id)`, `ix_video_review_evidence_candidate_id(candidate_id)`, `ix_video_review_evidence_recommendation_claim_id(recommendation_claim_id)` |
| `canonical_products` | `ix_canonical_products_run_id(run_id)`, `ix_canonical_products_name(name)`, `ix_canonical_products_brand_model(brand, model)`, `ix_canonical_products_model(model)`, `ix_canonical_products_category(category)` |
| `product_listings` | `ix_product_listings_run_id(run_id)`, `ix_product_listings_product_id(product_id)`, `ix_product_listings_url(url)`, `ix_product_listings_seller_name(seller_name)` |
| `candidate_shortlist_memberships` | `ix_candidate_shortlist_memberships_run_id(run_id)`, `ix_candidate_shortlist_memberships_product_id(product_id)`, `ix_candidate_shortlist_memberships_listing_id(listing_id)` |
| `user_added_products` | `ix_user_added_products_session_id(session_id)`, `ix_user_added_products_run_id(run_id)`, `ix_user_added_products_product_id(product_id)`, `ix_user_added_products_listing_id(listing_id)`, `ix_user_added_products_url(url)` |
| `listing_trust_assessments` | `ix_listing_trust_assessments_run_id(run_id)`, `ix_listing_trust_assessments_listing_id(listing_id)` |
| `category_analyses` | `ix_category_analyses_run_id(run_id)`, `ix_category_analyses_product_id(product_id)`, `ix_category_analyses_category(category)` |
| `agent_run_records` | `ix_agent_run_records_run_id(run_id)`, `ix_agent_run_records_stage(stage)`, `ix_agent_run_records_agent_name(agent_name)`, `ix_agent_run_records_trace_id(trace_id)` |
| `comparison_matrices` | `ix_comparison_matrices_run_id(run_id)` |
| `recommendation_bundles` | `ix_recommendation_bundles_run_id(run_id)`, `ix_recommendation_bundles_final_product_id(final_product_id)`, `ix_recommendation_bundles_final_listing_id(final_listing_id)` |
| `result_versions` | `ix_result_versions_run_id(run_id)`, `ix_result_versions_run_id_version(run_id, version)` |

## Unique Constraints

| Table | Constraint | Purpose |
| --- | --- | --- |
| `run_events` | `uq_run_events_run_id_sequence(run_id, sequence)` | Ensures event ordering is stable and non-duplicated per run. |
| `candidate_shortlist_memberships` | `uq_candidate_shortlist_memberships_run_id_candidate_id(run_id, candidate_id)` | Prevents the same candidate from being added twice to one run shortlist. |
| `result_versions` | `uq_result_versions_run_id_version(run_id, version)` | Prevents silent overwrite of a result version within a run. |

## Triggers

There are no database triggers in the current schema. Timestamp updates,
event sequencing, result versioning, and cleanup behavior are handled in
application/repository code or local scripts.

## Artifact Boundary

SQLite should not store bulky raw HTML, full extracted page text, screenshots,
trace exports, or eval output blobs by default. Those artifacts belong under:

- `data/artifacts/raw-sources/`
- `data/artifacts/extracted-content/`
- `data/artifacts/screenshots/`
- `data/artifacts/agent-outputs/`
- `data/artifacts/traces/`
- `data/artifacts/evals/`

SQLite records may store structured references to those files when later
provider/extraction tasks need them.

## Known Future Schema Areas

Future checklist sections may add or alter schema for provider fixture
recording/replay, extraction normalization, deduplication decisions, richer
trust signals, live agent cost/token tracking, eval run summaries, telemetry
privacy controls, backup/restore metadata, or a future Postgres migration path.
New shipped schema changes should be represented as incremental Alembic
migrations after the current `0001` baseline.
