from dataclasses import dataclass

from pydantic import AnyHttpUrl

from app.providers.contracts import (
    ExtractionProviderOptions,
    MarketplaceAvailabilityProviderOptions,
    MarketplaceAvailabilityProviderResult,
    OfficialStoreProviderOptions,
    OfficialStoreProviderResult,
    ProviderCapabilityFlags,
    ProviderRunStatus,
    SearchProviderOptions,
    ShoppingProviderOptions,
    TranscriptProviderOptions,
    TranscriptProviderResult,
    VideoSearchProviderOptions,
    VideoSearchProviderResult,
)
from app.schemas.ids import new_id
from app.schemas.products import CanonicalProduct, ProductListing, SellerProfile
from app.schemas.search_sources import (
    EvidenceTarget,
    EvidenceTargetType,
    ExtractionStatus,
    ProviderMetadata,
    SearchQuery,
    SearchResult,
    SourceQuality,
    SourceQualityLevel,
    SourceSnapshot,
    SourceType,
    TranscriptAvailability,
    VideoReviewEvidence,
    VideoReviewEvidenceBundle,
    VideoSource,
    VideoTranscriptSegment,
)
from app.schemas.source_references import SourceReference


@dataclass(frozen=True)
class FakeSearchProvider:
    results: tuple[SearchResult, ...] | None = None
    provider_name: str = "fixture-search"

    async def search(
        self,
        query: SearchQuery,
        options: SearchProviderOptions | None = None,
    ) -> tuple[SearchResult, ...]:
        if self.results is not None:
            return self.results
        max_results = options.max_results if options is not None else 1
        return tuple(
            _search_result(query, self.provider_name, index)
            for index in range(max_results)
        )


@dataclass(frozen=True)
class FakeExtractionProvider:
    snapshot: SourceSnapshot | None = None
    provider_name: str = "fixture-extraction"

    async def extract(
        self,
        url: AnyHttpUrl,
        options: ExtractionProviderOptions | None = None,
    ) -> SourceSnapshot:
        if self.snapshot is not None:
            return self.snapshot
        return SourceSnapshot(
            url=url,
            source_type=SourceType.PRODUCT_PAGE,
            provider=ProviderMetadata(provider_name=self.provider_name),
            title="Fixture extracted source",
            extraction_status=ExtractionStatus.SUCCEEDED,
            quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.7),
        )


@dataclass(frozen=True)
class FakeShoppingProvider:
    listings: tuple[ProductListing, ...] | None = None
    provider_name: str = "fixture-shopping"

    async def search_products(
        self,
        query: str,
        options: ShoppingProviderOptions | None = None,
    ) -> tuple[ProductListing, ...]:
        if self.listings is not None:
            return self.listings
        product_id = new_id()
        source_id = new_id()
        return (
            ProductListing(
                product_id=product_id,
                title=f"{query} - fixture listing",
                url=AnyHttpUrl("https://example.com/products/fixture-listing"),
                seller=SellerProfile(seller_name="Fixture Official"),
                source_ids=(source_id,),
            ),
        )


@dataclass(frozen=True)
class FakeVideoSearchProvider:
    bundle: VideoReviewEvidenceBundle | None = None
    provider_name: str = "fixture-video-search"
    disabled: bool = False
    transcript_availability: TranscriptAvailability = TranscriptAvailability.NOT_CHECKED
    metadata_only: bool = True

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name=self.provider_name,
            enabled=not self.disabled,
            uses_official_api=True,
            supports_video_search=True,
            supports_transcripts=False,
            permits_transcript_text=False,
            compliance_notes=("Fixture video metadata provider.",),
        )

    async def search_videos(
        self,
        query: str,
        options: VideoSearchProviderOptions | None = None,
    ) -> VideoSearchProviderResult:
        if self.disabled:
            return VideoSearchProviderResult(
                status=ProviderRunStatus.DISABLED,
                capabilities=self.capabilities,
                notes=("Video search provider is disabled.",),
            )
        return VideoSearchProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            bundle=self.bundle
            or _video_bundle(
                provider_name=self.provider_name,
                query=query,
                transcript_availability=self.transcript_availability,
                metadata_only=self.metadata_only,
            ),
        )


@dataclass(frozen=True)
class FakeTranscriptProvider:
    provider_name: str = "fixture-transcript"
    disabled: bool = False
    availability: TranscriptAvailability = TranscriptAvailability.AVAILABLE

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name=self.provider_name,
            enabled=not self.disabled,
            uses_official_api=True,
            supports_transcripts=True,
            permits_transcript_text=not self.disabled,
            requires_user_authorization=True,
            compliance_notes=("Fixture transcript provider.",),
        )

    async def fetch_transcript(
        self,
        video: VideoSource,
        options: TranscriptProviderOptions | None = None,
    ) -> TranscriptProviderResult:
        if self.disabled:
            return TranscriptProviderResult(
                status=ProviderRunStatus.DISABLED,
                capabilities=self.capabilities,
                video=video,
                availability=TranscriptAvailability.NOT_CHECKED,
                gap_notes=("Transcript provider is disabled.",),
            )
        if self.availability == TranscriptAvailability.UNAVAILABLE:
            return TranscriptProviderResult(
                status=ProviderRunStatus.SUCCEEDED,
                capabilities=self.capabilities,
                video=video.model_copy(
                    update={
                        "transcript_availability": TranscriptAvailability.UNAVAILABLE
                    }
                ),
                availability=TranscriptAvailability.UNAVAILABLE,
                gap_notes=("Transcript unavailable in fixture provider.",),
            )
        segment = VideoTranscriptSegment(
            video_id=video.video_id,
            start_seconds=12.0,
            end_seconds=24.0,
            text="Fixture transcript segment with product-specific review evidence.",
        )
        return TranscriptProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            video=video.model_copy(
                update={"transcript_availability": self.availability}
            ),
            availability=self.availability,
            segments=(segment,),
        )


@dataclass(frozen=True)
class FakeMarketplaceAvailabilityProvider:
    provider_name: str = "fixture-marketplace-availability"
    disabled: bool = False

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name=self.provider_name,
            enabled=not self.disabled,
            supports_marketplace_availability=True,
            compliance_notes=("Fixture marketplace availability provider.",),
        )

    async def check_availability(
        self,
        product: CanonicalProduct,
        listings: tuple[ProductListing, ...] = (),
        options: MarketplaceAvailabilityProviderOptions | None = None,
    ) -> MarketplaceAvailabilityProviderResult:
        if self.disabled:
            return MarketplaceAvailabilityProviderResult(
                status=ProviderRunStatus.DISABLED,
                capabilities=self.capabilities,
                notes=("Marketplace availability provider is disabled.",),
            )
        return MarketplaceAvailabilityProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            listings=listings,
            notes=(f"Fixture availability checked for {product.name}.",),
        )


@dataclass(frozen=True)
class FakeOfficialStoreProvider:
    provider_name: str = "fixture-official-store"
    disabled: bool = False

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name=self.provider_name,
            enabled=not self.disabled,
            supports_official_store_lookup=True,
            compliance_notes=("Fixture official-store provider.",),
        )

    async def find_official_sources(
        self,
        product: CanonicalProduct,
        options: OfficialStoreProviderOptions | None = None,
    ) -> OfficialStoreProviderResult:
        if self.disabled:
            return OfficialStoreProviderResult(
                status=ProviderRunStatus.DISABLED,
                capabilities=self.capabilities,
                notes=("Official-store provider is disabled.",),
            )
        snapshot = SourceSnapshot(
            url=AnyHttpUrl("https://example.com/official/fixture-product"),
            source_type=SourceType.OFFICIAL_BRAND_PAGE,
            provider=ProviderMetadata(provider_name=self.provider_name),
            title=f"{product.name} official page",
            extraction_status=ExtractionStatus.NOT_ATTEMPTED,
            quality=SourceQuality(level=SourceQualityLevel.STRONG, score=0.85),
        )
        return OfficialStoreProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            source_snapshots=(snapshot,),
        )


def _search_result(
    query: SearchQuery,
    provider_name: str,
    index: int,
) -> SearchResult:
    return SearchResult(
        query=query,
        url=AnyHttpUrl(f"https://example.com/search-result-{index + 1}"),
        title=f"Fixture search result {index + 1}",
        snippet="Fixture provider result.",
        source_type=(
            query.required_source_types[0]
            if query.required_source_types
            else SourceType.SEARCH_RESULT
        ),
        provider=ProviderMetadata(
            provider_name=provider_name,
            provider_result_id=f"fixture-result-{index + 1}",
            raw={"intent": query.intent.value},
        ),
        quality=SourceQuality(level=SourceQualityLevel.UNKNOWN),
    )


def _video_bundle(
    *,
    provider_name: str,
    query: str,
    transcript_availability: TranscriptAvailability,
    metadata_only: bool,
) -> VideoReviewEvidenceBundle:
    source_id = new_id()
    video = VideoSource(
        video_id="fixture-video-1",
        url=AnyHttpUrl("https://www.youtube.com/watch?v=fixture-video-1"),
        title=f"{query} fixture video from {provider_name}",
        channel_name="Fixture Reviews",
        transcript_availability=transcript_availability,
    )
    source_reference = SourceReference(
        source_id=source_id,
        url=video.url,
        title=video.title,
    )
    if metadata_only:
        return VideoReviewEvidenceBundle(
            videos=(video,),
            source_references=(source_reference,),
            evidence=(
                VideoReviewEvidence(
                    source_id=source_id,
                    target=EvidenceTarget(
                        target_type=EvidenceTargetType.SOURCE_METADATA,
                        source_id=source_id,
                    ),
                    video_id=video.video_id,
                    claim="Fixture video metadata is available.",
                    confidence={"score": 0.5, "level": "medium"},
                    source_quality=SourceQuality(level=SourceQualityLevel.UNKNOWN),
                    metadata_only=True,
                ),
            ),
        )
    segment = VideoTranscriptSegment(
        video_id=video.video_id,
        start_seconds=8.0,
        end_seconds=18.0,
        text="Fixture transcript evidence from a video review.",
    )
    return VideoReviewEvidenceBundle(
        videos=(video,),
        source_references=(source_reference,),
        transcript_segments=(segment,),
        evidence=(
            VideoReviewEvidence(
                source_id=source_id,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.SOURCE_METADATA,
                    source_id=source_id,
                ),
                video_id=video.video_id,
                claim="Fixture transcript evidence is available.",
                confidence={"score": 0.7, "level": "medium"},
                source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE),
                transcript_segment_ids=(segment.segment_id,),
            ),
        ),
    )
