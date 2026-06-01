from pathlib import Path

import pytest

from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.repositories.source_intelligence import SourceIntelligenceRepository
from app.db.repositories.video_sources import VideoReviewRepository
from app.db.session import create_database_engine, create_session_factory
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import new_id
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.money import Money
from app.schemas.search_sources import (
    AmazonEvidenceFactType,
    AmazonListingContext,
    AmazonProductEvidence,
    AmazonProductEvidenceBundle,
    CommunityDiscussionContext,
    CommunityDiscussionEvidence,
    CommunityDiscussionEvidenceBundle,
    EvidenceTarget,
    EvidenceTargetType,
    ExtractionStatus,
    IKEAEvidenceFactType,
    IKEAStoreContext,
    IKEAStoreEvidence,
    IKEAStoreEvidenceBundle,
    ProviderMetadata,
    RegionalStoreAvailability,
    SourceEvidenceGap,
    SourceIntelligenceCapability,
    SourceQuality,
    SourceQualityLevel,
    SourceReference,
    SourceSnapshot,
    SourceType,
    TimestampReference,
    TranscriptAvailability,
    VideoReviewEvidence,
    VideoReviewEvidenceBundle,
    VideoSource,
    VideoTranscriptSegment,
)


def make_provider(provider_name: str) -> ProviderMetadata:
    return ProviderMetadata(provider_name=provider_name, raw={"fixture": True})


def make_quality(level: SourceQualityLevel = SourceQualityLevel.ADEQUATE) -> SourceQuality:
    return SourceQuality(level=level, score=0.72, rationale="Fixture evidence.")


def make_confidence(score: float = 0.74) -> Confidence:
    return Confidence(score=score, level=ConfidenceLevel.MEDIUM)


async def create_run(session_factory) -> tuple:
    async with session_factory() as db_session:
        shopping_session = await SessionRepository(db_session).create(
            original_input=CreateSessionRequest(query="Need a durable desk chair"),
            current_brief=ShoppingBrief(original_query="Need a durable desk chair"),
        )
        run = await RunRepository(db_session).create(shopping_session.session_id)
        await db_session.commit()
    return shopping_session, run


def make_source_reference(snapshot: SourceSnapshot) -> SourceReference:
    return SourceReference(
        source_id=snapshot.source_id,
        url=snapshot.url,
        title=snapshot.title,
    )


@pytest.mark.asyncio
async def test_reusable_source_intelligence_fixture_records_round_trip_without_collapsing_targets(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "source-intelligence.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        _shopping_session, run = await create_run(session_factory)

        product_id = new_id()
        listing_id = new_id()
        youtube_snapshot, video_bundle = make_video_fixture(product_id)
        reddit_snapshot, reddit_bundle = make_reddit_fixture(product_id)
        amazon_snapshot, amazon_bundle = make_amazon_fixture(product_id, listing_id)
        ikea_snapshot, ikea_bundle = make_ikea_fixture(product_id)

        async with session_factory() as db_session:
            source_repository = SearchSourceRepository(db_session)
            for snapshot in (
                youtube_snapshot,
                reddit_snapshot,
                amazon_snapshot,
                ikea_snapshot,
            ):
                await source_repository.add_source_snapshot(run.run_id, snapshot)

            await VideoReviewRepository(db_session).add_video_review_bundle(
                run.run_id,
                video_bundle,
                recommendation_claim_ids={
                    video_bundle.evidence[0].evidence_id: "claims.youtube.product"
                },
            )
            source_intelligence_repository = SourceIntelligenceRepository(db_session)
            await source_intelligence_repository.add_community_discussion_bundle(
                run.run_id,
                reddit_bundle,
                recommendation_claim_ids={
                    reddit_bundle.evidence[0].evidence_id: "claims.reddit.product"
                },
            )
            await source_intelligence_repository.add_amazon_product_bundle(
                run.run_id,
                amazon_bundle,
                recommendation_claim_ids={
                    evidence.evidence_id: f"claims.amazon.{evidence.target.target_type}"
                    for evidence in amazon_bundle.evidence
                },
                gap_recommendation_claim_ids={
                    amazon_bundle.evidence_gaps[0].gap_id: "claims.amazon.review_gap"
                },
            )
            await source_intelligence_repository.add_ikea_store_bundle(
                run.run_id,
                ikea_bundle,
                recommendation_claim_ids={
                    evidence.evidence_id: f"claims.ikea.{evidence.target.target_type}"
                    for evidence in ikea_bundle.evidence
                },
            )
            await db_session.commit()

        async with session_factory() as db_session:
            video_repository = VideoReviewRepository(db_session)
            source_intelligence_repository = SourceIntelligenceRepository(db_session)
            loaded_video_bundle = await video_repository.get_video_review_bundle(
                video_bundle.bundle_id,
            )
            loaded_reddit_bundle = (
                await source_intelligence_repository.get_community_discussion_bundle(
                    reddit_bundle.bundle_id,
                )
            )
            loaded_amazon_bundle = (
                await source_intelligence_repository.get_amazon_product_bundle(
                    amazon_bundle.bundle_id,
                )
            )
            loaded_ikea_bundle = (
                await source_intelligence_repository.get_ikea_store_bundle(
                    ikea_bundle.bundle_id,
                )
            )
            video_links = await video_repository.list_video_evidence_links(run.run_id)
            evidence_links = (
                await source_intelligence_repository.list_reusable_source_evidence_links(
                    run.run_id,
                )
            )
            gap_links = (
                await source_intelligence_repository.list_reusable_source_gap_links(
                    run.run_id,
                )
            )
            amazon_contexts = (
                await source_intelligence_repository.list_amazon_listing_contexts(
                    run.run_id,
                )
            )
            ikea_contexts = (
                await source_intelligence_repository.list_ikea_store_contexts(
                    run.run_id,
                )
            )

        assert loaded_video_bundle is not None
        assert loaded_reddit_bundle is not None
        assert loaded_amazon_bundle is not None
        assert loaded_ikea_bundle is not None
        assert video_links[0].product_id == product_id
        assert video_links[0].recommendation_claim_id == "claims.youtube.product"
        assert loaded_reddit_bundle.discussions[0].community_name == "r/OfficeChairs"

        amazon_targets = {
            link.target_type: link
            for link in evidence_links
            if link.capability
            == SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW
        }
        assert amazon_targets[EvidenceTargetType.PRODUCT].product_id == product_id
        assert amazon_targets[EvidenceTargetType.LISTING].listing_id == listing_id
        assert amazon_targets[EvidenceTargetType.SELLER].listing_id == listing_id
        assert amazon_targets[EvidenceTargetType.REVIEW].review_id == "review-summary"
        assert amazon_targets[EvidenceTargetType.REGION].region_code == "US"
        assert amazon_targets[EvidenceTargetType.REGION].recommendation_claim_id
        assert amazon_contexts[0].asin == "B012345678"

        ikea_region_evidence = [
            item
            for item in loaded_ikea_bundle.evidence
            if item.target.target_type == EvidenceTargetType.REGION
        ]
        assert ikea_contexts[0].country_code == "US"
        assert ikea_contexts[0].price == Money(amount="129.99", currency="USD")
        assert len(ikea_region_evidence) == 2
        assert gap_links[0].review_id == "review-summary"
        assert gap_links[0].recommendation_claim_id == "claims.amazon.review_gap"

    finally:
        await engine.dispose()


def make_video_fixture(product_id):
    video = VideoSource(
        video_id="video-123",
        url="https://www.youtube.com/watch?v=video-123",
        title="Desk chair long-term review",
        channel_name="Review Channel",
        transcript_availability=TranscriptAvailability.AVAILABLE,
    )
    snapshot = SourceSnapshot(
        url=video.url,
        source_type=SourceType.VIDEO,
        provider=make_provider("fixture-youtube"),
        title=video.title,
        extraction_status=ExtractionStatus.SUCCEEDED,
        quality=make_quality(),
        video=video,
    )
    segment = VideoTranscriptSegment(
        video_id=video.video_id,
        start_seconds=12.0,
        end_seconds=18.0,
        text="The seat cushion held up after a year.",
    )
    evidence = VideoReviewEvidence(
        source_id=snapshot.source_id,
        target=EvidenceTarget(
            target_type=EvidenceTargetType.PRODUCT,
            product_id=product_id,
        ),
        video_id=video.video_id,
        claim="The reviewer says the seat cushion held up after a year.",
        confidence=make_confidence(),
        source_quality=make_quality(),
        timestamp_references=(TimestampReference(start_seconds=12.0, end_seconds=18.0),),
        transcript_segment_ids=(segment.segment_id,),
    )
    return snapshot, VideoReviewEvidenceBundle(
        videos=(video,),
        source_references=(make_source_reference(snapshot),),
        transcript_segments=(segment,),
        evidence=(evidence,),
    )


def make_reddit_fixture(product_id):
    snapshot = SourceSnapshot(
        url="https://www.reddit.com/r/OfficeChairs/comments/thread123/example/",
        source_type=SourceType.COMMUNITY_DISCUSSION,
        provider=make_provider("fixture-reddit-search"),
        title="Long-term desk chair experiences",
        extraction_status=ExtractionStatus.PARTIAL,
        quality=make_quality(SourceQualityLevel.MIXED),
    )
    discussion = CommunityDiscussionContext(
        source_id=snapshot.source_id,
        url=snapshot.url,
        community_name="r/OfficeChairs",
        thread_id="thread123",
        comment_id="comment456",
        extracted_public_summary="Owners repeatedly mention loose armrests.",
    )
    evidence = CommunityDiscussionEvidence(
        source_id=snapshot.source_id,
        target=EvidenceTarget(
            target_type=EvidenceTargetType.PRODUCT,
            product_id=product_id,
        ),
        claim="Owners repeatedly mention loose armrests after extended use.",
        confidence=make_confidence(0.58),
        source_quality=make_quality(SourceQualityLevel.MIXED),
        context_source_ids=(snapshot.source_id,),
        recurring_signal=True,
        evidence_quality_warnings=("Anecdotal community discussion.",),
    )
    gap = SourceEvidenceGap(
        capability=SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
        target=EvidenceTarget(
            target_type=EvidenceTargetType.PRODUCT,
            product_id=product_id,
        ),
        source_id=snapshot.source_id,
        summary="No official warranty fact was available from Reddit.",
    )
    return snapshot, CommunityDiscussionEvidenceBundle(
        source_references=(make_source_reference(snapshot),),
        discussions=(discussion,),
        evidence=(evidence,),
        evidence_gaps=(gap,),
    )


def make_amazon_fixture(product_id, listing_id):
    snapshot = SourceSnapshot(
        url="https://www.amazon.com/dp/B012345678",
        source_type=SourceType.RETAILER_LISTING,
        provider=make_provider("fixture-amazon-provider"),
        title="Fixture Desk Chair",
        extraction_status=ExtractionStatus.SUCCEEDED,
        quality=make_quality(),
    )
    context = AmazonListingContext(
        source_id=snapshot.source_id,
        marketplace_name="Amazon",
        marketplace_domain="amazon.com",
        marketplace_country_code="US",
        listing_url=snapshot.url,
        asin="B012345678",
        product_title="Fixture Desk Chair",
        seller_name="Third Party Seller",
        fulfillment="Fulfilled by Amazon",
        ships_to_region_code="US",
        ships_to_region=True,
        review_count=128,
        average_rating=4.2,
    )
    evidence = (
        AmazonProductEvidence(
            source_id=snapshot.source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product_id,
            ),
            fact_type=AmazonEvidenceFactType.PRODUCT_PAGE_FACT,
            claim="The product page describes adjustable armrests.",
            confidence=make_confidence(),
            source_quality=make_quality(),
            listing_context_source_id=snapshot.source_id,
        ),
        AmazonProductEvidence(
            source_id=snapshot.source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.LISTING,
                listing_id=listing_id,
            ),
            fact_type=AmazonEvidenceFactType.LISTING_IDENTITY,
            claim="The listing is identified by ASIN B012345678.",
            confidence=make_confidence(),
            source_quality=make_quality(),
            listing_context_source_id=snapshot.source_id,
        ),
        AmazonProductEvidence(
            source_id=snapshot.source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.SELLER,
                listing_id=listing_id,
            ),
            fact_type=AmazonEvidenceFactType.SELLER_FULFILLMENT,
            claim="The listing names a third-party seller with FBA fulfillment.",
            confidence=make_confidence(),
            source_quality=make_quality(SourceQualityLevel.MIXED),
            listing_context_source_id=snapshot.source_id,
        ),
        AmazonProductEvidence(
            source_id=snapshot.source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.REVIEW,
                review_id="review-summary",
            ),
            fact_type=AmazonEvidenceFactType.REVIEW_SUMMARY,
            claim="The listing shows 128 reviews with a 4.2 average rating.",
            confidence=make_confidence(),
            source_quality=make_quality(SourceQualityLevel.MIXED),
            listing_context_source_id=snapshot.source_id,
        ),
        AmazonProductEvidence(
            source_id=snapshot.source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.REGION,
                region_code="US",
            ),
            fact_type=AmazonEvidenceFactType.REGIONAL_AVAILABILITY,
            claim="The listing is marked as shipping to the US.",
            confidence=make_confidence(),
            source_quality=make_quality(),
            listing_context_source_id=snapshot.source_id,
        ),
    )
    gap = SourceEvidenceGap(
        capability=SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW,
        target=EvidenceTarget(
            target_type=EvidenceTargetType.REVIEW,
            review_id="review-summary",
        ),
        source_id=snapshot.source_id,
        summary="Individual review text was not available in the fixture.",
    )
    return snapshot, AmazonProductEvidenceBundle(
        source_references=(make_source_reference(snapshot),),
        listing_contexts=(context,),
        evidence=evidence,
        evidence_gaps=(gap,),
    )


def make_ikea_fixture(product_id):
    snapshot = SourceSnapshot(
        url="https://www.ikea.com/us/en/p/example-chair-12345678/",
        source_type=SourceType.OFFICIAL_BRAND_PAGE,
        provider=make_provider("fixture-ikea-provider"),
        title="Example chair",
        extraction_status=ExtractionStatus.SUCCEEDED,
        quality=make_quality(SourceQualityLevel.STRONG),
    )
    context = IKEAStoreContext(
        source_id=snapshot.source_id,
        country_code="US",
        official_url=snapshot.url,
        product_code="12345678",
        product_name="Example chair",
        store_name="IKEA US",
        delivery_area="US online delivery",
        price=Money(amount="129.99", currency="USD"),
        availability=RegionalStoreAvailability.AVAILABLE,
    )
    evidence = (
        IKEAStoreEvidence(
            source_id=snapshot.source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product_id,
            ),
            fact_type=IKEAEvidenceFactType.OFFICIAL_PRODUCT_FACT,
            claim="The official IKEA US page identifies product code 12345678.",
            confidence=make_confidence(),
            source_quality=make_quality(SourceQualityLevel.STRONG),
            store_context_source_id=snapshot.source_id,
        ),
        IKEAStoreEvidence(
            source_id=snapshot.source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.REGION,
                region_code="US",
            ),
            fact_type=IKEAEvidenceFactType.REGIONAL_PRICE,
            claim="The IKEA US page lists the regional price as 129.99 USD.",
            confidence=make_confidence(),
            source_quality=make_quality(SourceQualityLevel.STRONG),
            store_context_source_id=snapshot.source_id,
        ),
        IKEAStoreEvidence(
            source_id=snapshot.source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.REGION,
                region_code="US",
            ),
            fact_type=IKEAEvidenceFactType.REGIONAL_AVAILABILITY,
            claim="The IKEA US page marks the product as available.",
            confidence=make_confidence(),
            source_quality=make_quality(SourceQualityLevel.STRONG),
            store_context_source_id=snapshot.source_id,
        ),
    )
    gap = SourceEvidenceGap(
        capability=SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
        target=EvidenceTarget(
            target_type=EvidenceTargetType.REGION,
            region_code="PH",
        ),
        summary="No IKEA Philippines official-store evidence was checked.",
    )
    return snapshot, IKEAStoreEvidenceBundle(
        source_references=(make_source_reference(snapshot),),
        store_contexts=(context,),
        evidence=evidence,
        evidence_gaps=(gap,),
    )
