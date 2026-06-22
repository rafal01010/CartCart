from dataclasses import dataclass

import pytest

from app.agents import LiveYouTubeReviewIntelligenceAgent
from app.agents.contracts import YouTubeReviewIntelligenceAgentInput
from app.providers import (
    ProviderCapabilityFlags,
    ProviderRunStatus,
    TranscriptAccessStrategy,
    TranscriptProviderOptions,
    TranscriptProviderResult,
)
from app.schemas.analysis import RecommendationBundle
from app.schemas.ids import new_id
from app.schemas.intake import FieldSource, ShoppingBrief
from app.schemas.products import CanonicalProduct, ProductListing, SellerProfile
from app.schemas.regions import Region
from app.schemas.search_sources import (
    ChannelSignal,
    EvidenceTargetType,
    ExtractionStatus,
    ProviderMetadata,
    SourceQuality,
    SourceQualityLevel,
    SourceSnapshot,
    SourceType,
    TranscriptAvailability,
    VideoSource,
    VideoTranscriptSegment,
)


@pytest.mark.asyncio
async def test_youtube_review_agent_creates_timestamped_pro_con_concern_evidence() -> (
    None
):
    product, listing, snapshot = _product_listing_and_video_snapshot(
        "ccMonitor01",
        description=(
            "Sponsored review fixture. Affiliate links are visible in the "
            "description."
        ),
    )
    agent = LiveYouTubeReviewIntelligenceAgent(
        transcript_provider=_FixtureTranscriptProvider(),
    )

    output = await agent.run(
        YouTubeReviewIntelligenceAgentInput(
            run_id=new_id(),
            brief=_brief(),
            products=(product,),
            listings=(listing,),
            source_snapshots=(snapshot,),
            video_queries=("fixture monitor review transcript",),
        )
    )

    assert not isinstance(output, RecommendationBundle)
    assert output.videos[0].sponsorship_disclosed is True
    assert output.videos[0].affiliate_links_disclosed is True
    assert ChannelSignal.SPONSORSHIP_DISCLOSED in output.videos[0].channel_signals
    assert ChannelSignal.AFFILIATE_LINKS_DISCLOSED in output.videos[0].channel_signals
    assert len(output.transcript_segments) == 3

    claims = {item.claim for item in output.evidence if not item.metadata_only}
    assert claims == {
        "Pro: the Fixture Monitor has sharp text and strong brightness for coding.",
        "Con: the built-in speakers are weak and HDR looks washed out.",
        (
            "Concern: the stand can wobble on light desks, and this video has "
            "sponsored disclosure plus affiliate links."
        ),
    }
    assert {
        item.timestamp_references[0].start_seconds
        for item in output.evidence
        if not item.metadata_only
    } == {15.0, 64.0, 132.0}
    assert all(
        item.source_id == snapshot.source_id
        and item.video_id == snapshot.video.video_id
        and item.target.target_type == EvidenceTargetType.PRODUCT
        and item.target.product_id == product.product_id
        and item.transcript_segment_ids
        and item.affiliate_bias_risk is not None
        and item.affiliate_bias_risk.score >= 0.7
        for item in output.evidence
        if not item.metadata_only
    )
    assert [activity["tool_name"] for activity in agent.workbench_activity] == [
        "supplied_video_metadata",
        "TranscriptProvider.fetch_transcript",
        "VideoEvidenceCreator.create",
    ]


@pytest.mark.asyncio
async def test_youtube_review_agent_selects_relevant_review_video() -> None:
    product, listing, relevant_snapshot = _product_listing_and_video_snapshot(
        "ccMonitor01",
        title="Fixture Monitor review for coding and movies",
    )
    _, _, unrelated_snapshot = _product_listing_and_video_snapshot(
        "ccCoffee001",
        title="Coffee grinder teardown",
    )
    agent = LiveYouTubeReviewIntelligenceAgent(
        transcript_provider=_FixtureTranscriptProvider(),
        max_review_videos=1,
    )

    output = await agent.run(
        YouTubeReviewIntelligenceAgentInput(
            run_id=new_id(),
            brief=_brief(),
            products=(product,),
            listings=(listing,),
            source_snapshots=(unrelated_snapshot, relevant_snapshot),
            video_queries=("Fixture Monitor review",),
        )
    )

    assert [video.video_id for video in output.videos] == ["ccMonitor01"]
    assert output.source_references[0].source_id == relevant_snapshot.source_id


@pytest.mark.asyncio
async def test_youtube_review_agent_preserves_no_transcript_metadata_gap() -> None:
    product, listing, snapshot = _product_listing_and_video_snapshot("ccNoTrans01")
    agent = LiveYouTubeReviewIntelligenceAgent(
        transcript_provider=_FixtureTranscriptProvider(),
    )

    output = await agent.run(
        YouTubeReviewIntelligenceAgentInput(
            run_id=new_id(),
            brief=_brief(),
            products=(product,),
            listings=(listing,),
            source_snapshots=(snapshot,),
            video_queries=("fixture monitor review without captions",),
        )
    )

    assert output.videos[0].transcript_availability == (
        TranscriptAvailability.UNAVAILABLE
    )
    assert output.transcript_segments == ()
    assert output.transcript_gap_notes
    assert len(output.evidence) == 1
    evidence = output.evidence[0]
    assert evidence.metadata_only is True
    assert evidence.target.target_type == EvidenceTargetType.SOURCE_METADATA
    assert evidence.target.source_id == snapshot.source_id
    assert evidence.timestamp_references == ()
    assert evidence.transcript_segment_ids == ()
    assert evidence.transcript_gap is not None
    assert "Pro:" not in evidence.claim
    assert "sharp text" not in evidence.claim


def _brief() -> ShoppingBrief:
    return ShoppingBrief(
        original_query="I need a 27-inch monitor for coding and movies.",
        category="monitor",
        category_source=FieldSource.INFERRED,
        region={
            "region": Region(country_code="US", currency="USD"),
            "source": FieldSource.USER_PROVIDED,
        },
    )


def _product_listing_and_video_snapshot(
    video_id: str,
    *,
    title: str = "Fixture Monitor review for coding and movies",
    description: str = "Fixture monitor review video.",
) -> tuple[CanonicalProduct, ProductListing, SourceSnapshot]:
    source_id = new_id()
    product = CanonicalProduct(
        name="Fixture Monitor",
        brand="Fixture",
        model="Monitor 1",
        category="monitor",
        source_ids=(source_id,),
    )
    listing = ProductListing(
        product_id=product.product_id,
        title="Fixture Monitor - Official Store",
        url="https://example.com/monitor/fixture-monitor",
        seller=SellerProfile(seller_name="Fixture Official"),
        source_ids=(source_id,),
    )
    product = product.model_copy(update={"listing_ids": (listing.listing_id,)})
    video = VideoSource(
        video_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
        title=title,
        description=description,
        channel_name="Fixture Reviews",
        transcript_availability=TranscriptAvailability.NOT_CHECKED,
    )
    snapshot = SourceSnapshot(
        source_id=source_id,
        url=video.url,
        source_type=SourceType.VIDEO,
        provider=ProviderMetadata(provider_name="test-youtube-fixture"),
        title=video.title,
        extraction_status=ExtractionStatus.NOT_ATTEMPTED,
        quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.7),
        video=video,
    )
    return product, listing, snapshot


@dataclass(frozen=True)
class _FixtureTranscriptProvider:
    provider_name: str = "test-youtube-transcripts"

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name=self.provider_name,
            enabled=True,
            supports_transcripts=True,
            permits_transcript_text=True,
            transcript_access_strategy=TranscriptAccessStrategy.USER_PROVIDED,
        )

    async def fetch_transcript(
        self,
        video: VideoSource,
        options: TranscriptProviderOptions | None = None,
    ) -> TranscriptProviderResult:
        del options
        if video.video_id == "ccNoTrans01":
            return TranscriptProviderResult(
                status=ProviderRunStatus.SUCCEEDED,
                capabilities=self.capabilities,
                video=video.model_copy(
                    update={
                        "transcript_availability": TranscriptAvailability.UNAVAILABLE
                    }
                ),
                availability=TranscriptAvailability.UNAVAILABLE,
                gap_notes=("No captions are available for this fixture video.",),
            )

        segments = (
            VideoTranscriptSegment(
                video_id=video.video_id,
                start_seconds=15.0,
                end_seconds=26.0,
                language="en",
                text=(
                    "Pro: the Fixture Monitor has sharp text and strong brightness "
                    "for coding."
                ),
            ),
            VideoTranscriptSegment(
                video_id=video.video_id,
                start_seconds=64.0,
                end_seconds=75.0,
                language="en",
                text="Con: the built-in speakers are weak and HDR looks washed out.",
            ),
            VideoTranscriptSegment(
                video_id=video.video_id,
                start_seconds=132.0,
                end_seconds=145.0,
                language="en",
                text=(
                    "Concern: the stand can wobble on light desks, and this video "
                    "has sponsored disclosure plus affiliate links."
                ),
            ),
        )
        return TranscriptProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            video=video.model_copy(
                update={"transcript_availability": TranscriptAvailability.AVAILABLE}
            ),
            availability=TranscriptAvailability.AVAILABLE,
            segments=segments,
        )
