from pathlib import Path

import pytest
from pydantic import AnyHttpUrl

import app.db.models  # noqa: F401
from app.agents import SellerListingTrustAgentInput
from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.repositories.source_intelligence import SourceIntelligenceRepository
from app.db.repositories.video_sources import VideoReviewRepository
from app.db.session import create_database_engine, create_session_factory
from app.orchestration import (
    RepositoryShoppingRunPersistenceHooks,
    ShoppingRunOrchestrator,
)
from app.providers import (
    ExtractionProviderOptions,
    ProviderCapabilityFlags,
    ProviderRunStatus,
    SearchProviderOptions,
    TranscriptAccessStrategy,
    TranscriptProviderOptions,
    TranscriptProviderResult,
)
from app.schemas.analysis import ListingTrustAssessment
from app.schemas.intake import CreateSessionRequest, FieldSource, ShoppingBrief
from app.schemas.runs import RunStage, RunStatus
from app.schemas.search_sources import (
    ExtractedPageContent,
    ExtractionStatus,
    ProviderMetadata,
    SearchQuery,
    SearchResult,
    SourceQuality,
    SourceQualityLevel,
    SourceSnapshot,
    SourceType,
    TranscriptAvailability,
    VideoSource,
    VideoTranscriptSegment,
)


class RecordingSearchProvider:
    provider_name = "recording-search"

    def __init__(self) -> None:
        self.calls: list[tuple[SearchQuery, SearchProviderOptions | None]] = []

    async def search(
        self,
        query: SearchQuery,
        options: SearchProviderOptions | None = None,
    ) -> tuple[SearchResult, ...]:
        self.calls.append((query, options))
        return (
            SearchResult(
                query=query,
                url=AnyHttpUrl(
                    "https://www.rtings.com/monitor/reviews/example?utm_source=fixture"
                ),
                title="Measured monitor review",
                snippet="Instrumented review results.",
                provider=ProviderMetadata(provider_name=self.provider_name),
                quality=SourceQuality(level=SourceQualityLevel.UNKNOWN),
            ),
            SearchResult(
                query=query,
                url=AnyHttpUrl("https://www.aliexpress.com/item/fixture.html"),
                title="Excluded reseller result",
                provider=ProviderMetadata(provider_name=self.provider_name),
            ),
        )


class ListingSearchProvider:
    provider_name = "fixture-listing-search"

    async def search(
        self,
        query: SearchQuery,
        options: SearchProviderOptions | None = None,
    ) -> tuple[SearchResult, ...]:
        del options
        return (
            SearchResult(
                query=query,
                url=AnyHttpUrl("https://shop.example/northstar-arc-27"),
                title="Northstar Arc 27 USB-C Monitor",
                snippet="Fixture retailer result.",
                source_type=SourceType.RETAILER_LISTING,
                provider=ProviderMetadata(provider_name=self.provider_name),
            ),
        )


class DuplicateListingSearchProvider:
    provider_name = "fixture-duplicate-listing-search"

    async def search(
        self,
        query: SearchQuery,
        options: SearchProviderOptions | None = None,
    ) -> tuple[SearchResult, ...]:
        del options
        return (
            SearchResult(
                query=query,
                url=AnyHttpUrl("https://shop.example/northstar-arc-27?utm_source=one"),
                title="Northstar Arc 27 USB-C Monitor",
                snippet="Fixture retailer result.",
                source_type=SourceType.RETAILER_LISTING,
                provider=ProviderMetadata(provider_name=self.provider_name),
            ),
            SearchResult(
                query=query,
                url=AnyHttpUrl(
                    "https://www.shop.example/northstar-arc-27?utm_campaign=two"
                ),
                title="Northstar Arc 27 USB-C Monitor",
                snippet="Duplicate fixture retailer result.",
                source_type=SourceType.RETAILER_LISTING,
                provider=ProviderMetadata(provider_name=self.provider_name),
            ),
        )


class RecordingExtractionProvider:
    provider_name = "recording-extraction"

    def __init__(self) -> None:
        self.calls: list[tuple[AnyHttpUrl, ExtractionProviderOptions | None]] = []

    async def extract(
        self,
        url: AnyHttpUrl,
        options: ExtractionProviderOptions | None = None,
    ) -> SourceSnapshot:
        self.calls.append((url, options))
        text = (
            "Brand: Northstar\nPrice: USD 329.99\nSeller: Metro Office\n"
            "Region: US\nA 27 inch USB-C monitor for office work."
        )
        return SourceSnapshot(
            url=url,
            source_type=SourceType.RETAILER_LISTING,
            provider=ProviderMetadata(provider_name=self.provider_name),
            title="Northstar Arc 27 USB-C Monitor",
            extraction_status=ExtractionStatus.SUCCEEDED,
            extracted_content=ExtractedPageContent(
                text=text,
                extractor="fixture-static",
                site_name="Metro Office",
                word_count=len(text.split()),
            ),
        )


class RecordingTranscriptProvider:
    provider_name = "recording-transcript"

    def __init__(self) -> None:
        self.calls: list[tuple[VideoSource, TranscriptProviderOptions | None]] = []

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name=self.provider_name,
            enabled=True,
            supports_transcripts=True,
            permits_transcript_text=True,
            transcript_access_strategy=TranscriptAccessStrategy.APPROVED_THIRD_PARTY,
            compliance_notes=("Records transcript requests for orchestrator tests.",),
        )

    async def fetch_transcript(
        self,
        video: VideoSource,
        options: TranscriptProviderOptions | None = None,
    ) -> TranscriptProviderResult:
        self.calls.append((video, options))
        segment = VideoTranscriptSegment(
            video_id=video.video_id,
            start_seconds=5.0,
            end_seconds=12.0,
            language="en",
            text="Fixture transcript segment from the configured transcript provider.",
        )
        return TranscriptProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            video=video.model_copy(
                update={"transcript_availability": TranscriptAvailability.AVAILABLE}
            ),
            availability=TranscriptAvailability.AVAILABLE,
            segments=(segment,),
        )


class RecordingSellerListingTrustAgent:
    def __init__(self) -> None:
        self.calls: list[SellerListingTrustAgentInput] = []

    async def run(
        self,
        input_data: SellerListingTrustAgentInput,
    ) -> ListingTrustAssessment:
        self.calls.append(input_data)
        assert input_data.rule_based_assessment is not None
        return input_data.rule_based_assessment.model_copy(
            update={
                "summary": (
                    f"Trust agent reviewed listing {input_data.listing.listing_id}."
                )
            }
        )


@pytest.mark.asyncio
async def test_shopping_run_orchestrator_records_all_expected_fixture_stages(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            shopping_session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query="Need a 27 inch monitor"),
                current_brief=ShoppingBrief(original_query="Need a 27 inch monitor"),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            run_repository = RunRepository(db_session)
            result_repository = ResultRepository(db_session)
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=run_repository,
                    result_repository=result_repository,
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                )
            )

            context = await orchestrator.run(run.run_id, shopping_session.current_brief)
            await db_session.commit()

        async with session_factory() as db_session:
            run_repository = RunRepository(db_session)
            result_repository = ResultRepository(db_session)
            loaded_run = await run_repository.get(run.run_id)
            events = await run_repository.list_events(run.run_id)
            agent_records = await result_repository.list_agent_records(run.run_id)

        expected_stages = ShoppingRunOrchestrator.stage_order()
        executable_stages = ShoppingRunOrchestrator.executable_stage_order()

        assert loaded_run is not None
        assert loaded_run.status == RunStatus.SUCCEEDED
        assert loaded_run.current_stage == RunStage.COMPLETE
        assert context.session_id == shopping_session.session_id
        assert context.trace_id == f"fixture-run-{run.run_id}"
        assert tuple(event.stage for event in events) == expected_stages
        assert tuple(event.sequence for event in events) == tuple(
            range(len(expected_stages))
        )
        expected_statuses = (RunStatus.RUNNING,) * len(executable_stages) + (
            RunStatus.SUCCEEDED,
        )
        assert tuple(event.status for event in events) == expected_statuses
        assert tuple(context.stage_outputs) == executable_stages
        assert context.search_plan is not None
        assert context.search_plan.queries[0].query == "Need a 27 inch monitor reviews"
        assert context.search_plan.queries[0].region_code == "US"
        assert context.search_results
        assert {result.provider.provider_name for result in context.search_results} == {
            "fixture-search"
        }
        assert {record.stage for record in agent_records} == set(executable_stages)
        assert {record.trace_id for record in agent_records} == {
            f"{context.trace_id}:{stage.value}" for stage in executable_stages
        }

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_shopping_run_orchestrator_persists_monitor_fixture_output(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator-fixture.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            shopping_session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query="Need a 27 inch monitor"),
                current_brief=ShoppingBrief(original_query="Need a 27 inch monitor"),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(db_session),
                    result_repository=ResultRepository(db_session),
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                )
            )

            context = await orchestrator.run(run.run_id, shopping_session.current_brief)
            await db_session.commit()

        assert context.fixture_output is not None

        async with session_factory() as db_session:
            search_repository = SearchSourceRepository(db_session)
            product_repository = ProductRepository(db_session)
            result_repository = ResultRepository(db_session)
            source_intelligence_repository = SourceIntelligenceRepository(db_session)
            video_repository = VideoReviewRepository(db_session)
            search_results = await search_repository.list_search_results(run.run_id)
            source_snapshots = await search_repository.list_source_snapshots(run.run_id)
            source_evidence = await search_repository.list_source_evidence(run.run_id)
            video_sources = await video_repository.list_video_sources(run.run_id)
            community_evidence = (
                await source_intelligence_repository.list_community_evidence(run.run_id)
            )
            amazon_evidence = await source_intelligence_repository.list_amazon_evidence(
                run.run_id
            )
            shortlist = await product_repository.list_shortlist_memberships(run.run_id)
            user_added = await product_repository.list_user_added_products(
                shopping_session.session_id
            )
            result = await result_repository.load_latest_result_bundle(run.run_id)
            listing_count_items: list[int] = []
            for product in context.fixture_output.products:
                product_listings = await product_repository.list_listings_for_product(
                    product.product_id
                )
                listing_count_items.append(len(product_listings))
            listing_counts = tuple(listing_count_items)

        fixture = context.fixture_output
        assert context.source_intelligence is not None
        source_intelligence_source_count = _source_intelligence_source_reference_count(
            context.source_intelligence
        )
        assert len(search_results) == len(context.search_results)
        assert all(
            result.provider.provider_name == "fixture-search"
            for result in search_results
        )
        assert len(source_snapshots) == (
            len(fixture.source_snapshots)
            + len(context.source_extractions)
            + source_intelligence_source_count
        )
        assert len(source_evidence) == len(fixture.source_evidence)
        assert video_sources
        assert community_evidence
        assert amazon_evidence
        assert len(shortlist) == len(context.source_extractions)
        assert all(
            item.listing_extraction is not None for item in context.source_extractions
        )
        assert len(user_added) == 1
        assert user_added[0].listing is not None
        assert user_added[0].listing.seller.seller_name == "FlashDealz Outlet"
        assert result is not None
        assert result.result_version.version == 1
        assert result.recommendation_bundle.final_rationale is not None
        assert result.recommendation_bundle.final_product_id == (
            fixture.recommendation_bundle.final_product_id
        )
        assert len(result.recommendation_bundle.runner_up_product_ids) == 2
        assert result.recommendation_bundle.rejected_items[0].listing_id == (
            user_added[0].listing.listing_id
        )
        blocked_listing_ids = {
            item.listing_id
            for item in result.recommendation_bundle.rejected_items
            if item.severity.value == "blocking"
        }
        assert fixture.listings[1].listing_id in blocked_listing_ids
        assert fixture.listings[0].listing_id not in blocked_listing_ids
        assert any(
            "product may still be worth considering" in item.reason
            for item in result.recommendation_bundle.rejected_items
        )
        assert any(
            assessment.level.value == "suspicious"
            for assessment in result.trust_assessments
        )
        assert any(count > 1 for count in listing_counts)

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_listing_trust_stage_uses_agent_contract_and_persists_output(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator-trust-agent.sqlite3",
    )
    engine = create_database_engine(settings)
    trust_agent = RecordingSellerListingTrustAgent()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            shopping_session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query="Need a 27 inch monitor"),
                current_brief=ShoppingBrief(original_query="Need a 27 inch monitor"),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(db_session),
                    result_repository=ResultRepository(db_session),
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                ),
                seller_listing_trust_agent=trust_agent,
            )

            context = await orchestrator.run(run.run_id, shopping_session.current_brief)
            await db_session.commit()

        async with session_factory() as db_session:
            result = await ResultRepository(db_session).load_latest_result_bundle(
                run.run_id
            )
            agent_records = await ResultRepository(db_session).list_agent_records(
                run.run_id
            )

        assert result is not None
        trust_stage = context.stage_outputs[RunStage.LISTING_TRUST]
        assert trust_stage.payload["assessment_count"] == str(len(trust_agent.calls))
        assert len(result.trust_assessments) == len(trust_agent.calls)
        assert {assessment.listing_id for assessment in result.trust_assessments} == {
            call.listing.listing_id for call in trust_agent.calls
        }
        assert all(
            assessment.summary.startswith("Trust agent reviewed listing ")
            for assessment in result.trust_assessments
        )
        assert any(
            assessment.level.value == "suspicious"
            for assessment in result.trust_assessments
        )
        assert any(
            record.stage == RunStage.LISTING_TRUST
            and record.agent_name == "SellerListingTrustAgent"
            for record in agent_records
        )

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_query_planning_calls_provider_and_persists_scored_results_only(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator-search.sqlite3",
    )
    engine = create_database_engine(settings)
    provider = RecordingSearchProvider()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            shopping_session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query="Need a 27 inch monitor"),
                current_brief=ShoppingBrief(original_query="Need a 27 inch monitor"),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(db_session),
                    result_repository=ResultRepository(db_session),
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                ),
                search_provider=provider,
                default_region_code="US",
            )
            context = await orchestrator.run(
                run.run_id,
                shopping_session.current_brief,
            )
            await db_session.commit()

        async with session_factory() as db_session:
            repository = SearchSourceRepository(db_session)
            persisted_results = await repository.list_search_results(run.run_id)
            snapshots = await repository.list_source_snapshots(run.run_id)

        assert len(provider.calls) == 1
        called_query, called_options = provider.calls[0]
        assert called_query.query == "Need a 27 inch monitor reviews"
        assert called_query.region_code == "US"
        assert called_options is not None
        assert called_options.region_code == "US"
        assert len(context.search_results) == 1
        assert len(persisted_results) == 1
        assert str(persisted_results[0].url).startswith("https://rtings.com/")
        assert "utm_source" not in str(persisted_results[0].url)
        assert persisted_results[0].quality.level == SourceQualityLevel.ADEQUATE
        assert persisted_results[0].provider.raw["source_class"] == "review_testing"
        extracted_snapshot = next(
            snapshot
            for snapshot in snapshots
            if snapshot.provider.provider_name == "fixture-extraction"
        )
        assert extracted_snapshot.url == persisted_results[0].url
        assert extracted_snapshot.provider.raw["search_result_source_id"] == str(
            persisted_results[0].source_id
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_extraction_provider_creates_persisted_generated_shortlist(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator-extraction.sqlite3",
    )
    engine = create_database_engine(settings)
    extraction_provider = RecordingExtractionProvider()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            shopping_session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query="Need a USB-C monitor"),
                current_brief=ShoppingBrief(
                    original_query="Need a USB-C monitor",
                    category="monitor",
                    category_source=FieldSource.USER_PROVIDED,
                ),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(db_session),
                    result_repository=ResultRepository(db_session),
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                ),
                search_provider=ListingSearchProvider(),
                extraction_provider=extraction_provider,
                default_region_code="US",
            )
            context = await orchestrator.run(
                run.run_id,
                shopping_session.current_brief,
            )
            await db_session.commit()

        async with session_factory() as db_session:
            search_repository = SearchSourceRepository(db_session)
            product_repository = ProductRepository(db_session)
            snapshots = await search_repository.list_source_snapshots(run.run_id)
            shortlist = await product_repository.list_shortlist_memberships(run.run_id)
            events = await RunRepository(db_session).list_events(run.run_id)

            assert len(extraction_provider.calls) == 1
            called_url, called_options = extraction_provider.calls[0]
            assert str(called_url) == "https://shop.example/northstar-arc-27"
            assert called_options is not None
            assert called_options.source_type == SourceType.RETAILER_LISTING

            assert len(context.source_extractions) == 1
            generated = context.source_extractions[0]
            assert generated.listing_extraction is not None
            assert generated.listing_extraction.product.brand == "Northstar"
            assert generated.listing_extraction.product.category == "monitor"
            assert generated.listing_extraction.listing.price is not None
            assert generated.listing_extraction.listing.price.currency == "USD"

            extracted_snapshot = next(
                snapshot
                for snapshot in snapshots
                if snapshot.provider.provider_name == "recording-extraction"
            )
            assert extracted_snapshot.provider.raw["search_result_source_id"] == str(
                generated.search_result.source_id
            )
            assert len(shortlist) == 1
            assert (
                shortlist[0].product_id
                == generated.listing_extraction.product.product_id
            )
            assert (
                shortlist[0].listing_id
                == generated.listing_extraction.listing.listing_id
            )

            extraction_event = next(
                event for event in events if event.stage == RunStage.EXTRACTION
            )
            assert extraction_event.message == (
                "Checked 1 shopping source and added 1 product to compare."
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_deduplication_stage_groups_extracted_candidates_before_later_stages(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator-deduplication.sqlite3",
    )
    engine = create_database_engine(settings)
    extraction_provider = RecordingExtractionProvider()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            shopping_session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query="Need a USB-C monitor"),
                current_brief=ShoppingBrief(
                    original_query="Need a USB-C monitor",
                    category="monitor",
                    category_source=FieldSource.USER_PROVIDED,
                ),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(db_session),
                    result_repository=ResultRepository(db_session),
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                ),
                search_provider=DuplicateListingSearchProvider(),
                extraction_provider=extraction_provider,
                default_region_code="US",
            )
            context = await orchestrator.run(
                run.run_id,
                shopping_session.current_brief,
            )
            await db_session.commit()

        async with session_factory() as db_session:
            product_repository = ProductRepository(db_session)
            events = await RunRepository(db_session).list_events(run.run_id)
            shortlist = await product_repository.list_shortlist_memberships(run.run_id)
            listings = await product_repository.list_listings_for_product(
                shortlist[0].product_id
            )

        assert len(extraction_provider.calls) == 2
        assert context.deduplication is not None
        assert context.deduplication.pre_dedupe_count == 2
        assert context.deduplication.post_dedupe_count == 1
        assert context.deduplication.collapsed_count == 1
        assert context.stage_outputs[RunStage.DEDUPLICATION].payload == {
            "pre_dedupe_count": "2",
            "post_dedupe_count": "1",
            "listing_count": "2",
            "collapsed_count": "1",
        }

        event_stages = [event.stage for event in events]
        assert event_stages.index(RunStage.EXTRACTION) < event_stages.index(
            RunStage.DEDUPLICATION
        )
        assert event_stages.index(RunStage.DEDUPLICATION) < event_stages.index(
            RunStage.SOURCE_INTELLIGENCE
        )
        deduplication_event = next(
            event for event in events if event.stage == RunStage.DEDUPLICATION
        )
        assert deduplication_event.message == (
            "Grouped 2 extracted products into 1 product group and kept "
            "2 listings; 1 duplicate collapsed."
        )

        assert len(shortlist) == 1
        assert len(listings) == 2
        assert {listing.product_id for listing in listings} == {shortlist[0].product_id}
        assert context.source_intelligence is not None
        assert context.source_intelligence.request.product_ids == (
            shortlist[0].product_id,
        )
        assert set(context.source_intelligence.request.listing_ids) == {
            listing.listing_id for listing in listings
        }

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_source_intelligence_stage_persists_required_fixture_bundles(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator-source-intelligence.sqlite3",
    )
    engine = create_database_engine(settings)
    transcript_provider = RecordingTranscriptProvider()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            shopping_session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(
                    query="Need a durable office chair"
                ),
                current_brief=ShoppingBrief(
                    original_query="Need a durable office chair",
                    category="office chair",
                    category_source=FieldSource.USER_PROVIDED,
                ),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(db_session),
                    result_repository=ResultRepository(db_session),
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                    source_intelligence_repository=SourceIntelligenceRepository(
                        db_session
                    ),
                    video_review_repository=VideoReviewRepository(db_session),
                ),
                search_provider=ListingSearchProvider(),
                extraction_provider=RecordingExtractionProvider(),
                transcript_provider=transcript_provider,
                default_region_code="US",
            )
            context = await orchestrator.run(
                run.run_id,
                shopping_session.current_brief,
            )
            await db_session.commit()

        async with session_factory() as db_session:
            run_repository = RunRepository(db_session)
            video_repository = VideoReviewRepository(db_session)
            source_intelligence_repository = SourceIntelligenceRepository(db_session)
            events = await run_repository.list_events(run.run_id)
            video_sources = await video_repository.list_video_sources(run.run_id)
            transcript_segments = await video_repository.list_transcript_segments(
                run.run_id
            )
            community_evidence = (
                await source_intelligence_repository.list_community_evidence(run.run_id)
            )
            amazon_evidence = await source_intelligence_repository.list_amazon_evidence(
                run.run_id
            )
            ikea_evidence = await source_intelligence_repository.list_ikea_evidence(
                run.run_id
            )
            reusable_gaps = (
                await source_intelligence_repository.list_reusable_source_evidence_gaps(
                    run.run_id
                )
            )

        assert context.source_intelligence is not None
        assert len(transcript_provider.calls) == 1
        assert transcript_provider.calls[0][1] is not None
        assert len(context.source_intelligence.video_bundles) == 1
        assert len(context.source_intelligence.community_bundles) == 1
        assert len(context.source_intelligence.amazon_bundles) == 1
        assert len(context.source_intelligence.ikea_bundles) == 1
        assert (
            video_sources[0].transcript_availability == TranscriptAvailability.AVAILABLE
        )
        assert transcript_segments[0].text is not None
        assert community_evidence
        assert amazon_evidence
        assert ikea_evidence
        assert reusable_gaps

        source_intelligence_event = next(
            event for event in events if event.stage == RunStage.SOURCE_INTELLIGENCE
        )
        assert source_intelligence_event.message.startswith(
            "Checked review videos, community discussions, Amazon listings"
        )

    finally:
        await engine.dispose()


def _source_intelligence_source_reference_count(output) -> int:
    return sum(
        len(bundle.source_references)
        for bundles in (
            output.video_bundles,
            output.community_bundles,
            output.amazon_bundles,
            output.ikea_bundles,
        )
        for bundle in bundles
    )
