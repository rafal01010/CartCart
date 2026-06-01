from dataclasses import dataclass

from pydantic import AnyHttpUrl

from app.providers.contracts import (
    AmazonProductIntelligenceProviderOptions,
    AmazonProductIntelligenceProviderResult,
    CommunityDiscussionProviderOptions,
    CommunityDiscussionProviderResult,
    ExtractionProviderOptions,
    IKEAStoreIntelligenceProviderOptions,
    IKEAStoreIntelligenceProviderResult,
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
    SearchQuery,
    SearchResult,
    SourceEvidenceGap,
    SourceIntelligenceCapability,
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
class FakeCommunityDiscussionProvider:
    bundle: CommunityDiscussionEvidenceBundle | None = None
    provider_name: str = "fixture-community-discussion"
    disabled: bool = False

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name=self.provider_name,
            enabled=not self.disabled,
            supports_domain_scoped_search=True,
            supports_public_page_extraction=True,
            supports_community_discussion_retrieval=True,
            compliance_notes=("Fixture domain-scoped public community provider.",),
        )

    async def search_discussions(
        self,
        query: str,
        products: tuple[CanonicalProduct, ...] = (),
        options: CommunityDiscussionProviderOptions | None = None,
    ) -> CommunityDiscussionProviderResult:
        if self.disabled:
            return CommunityDiscussionProviderResult(
                status=ProviderRunStatus.DISABLED,
                capabilities=self.capabilities,
                notes=("Community discussion provider is disabled.",),
            )
        return CommunityDiscussionProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            bundle=self.bundle
            or _community_bundle(
                provider_name=self.provider_name,
                query=query,
                product_id=products[0].product_id if products else None,
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
class FakeAmazonProductIntelligenceProvider:
    bundle: AmazonProductEvidenceBundle | None = None
    provider_name: str = "fixture-amazon-product-intelligence"
    disabled: bool = False

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name=self.provider_name,
            enabled=not self.disabled,
            supports_amazon_product_intelligence=True,
            supports_amazon_listing_identity=True,
            supports_amazon_review_signals=True,
            supports_regional_ship_to_evidence=True,
            compliance_notes=("Fixture Amazon product/listing/review provider.",),
        )

    async def fetch_product_evidence(
        self,
        product: CanonicalProduct,
        listings: tuple[ProductListing, ...] = (),
        options: AmazonProductIntelligenceProviderOptions | None = None,
    ) -> AmazonProductIntelligenceProviderResult:
        if self.disabled:
            return AmazonProductIntelligenceProviderResult(
                status=ProviderRunStatus.DISABLED,
                capabilities=self.capabilities,
                notes=("Amazon product intelligence provider is disabled.",),
            )
        region_code = options.region_code if options is not None else None
        return AmazonProductIntelligenceProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            bundle=self.bundle
            or _amazon_bundle(
                product=product,
                listing=listings[0] if listings else None,
                region_code=region_code or "US",
            ),
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


@dataclass(frozen=True)
class FakeIKEAStoreIntelligenceProvider:
    bundle: IKEAStoreEvidenceBundle | None = None
    provider_name: str = "fixture-ikea-store-intelligence"
    disabled: bool = False

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name=self.provider_name,
            enabled=not self.disabled,
            uses_official_api=True,
            supports_ikea_regional_store_lookup=True,
            supports_ikea_product_pages=True,
            supports_ikea_store_delivery_context=True,
            compliance_notes=("Fixture IKEA regional official-store provider.",),
        )

    async def fetch_store_evidence(
        self,
        product: CanonicalProduct,
        options: IKEAStoreIntelligenceProviderOptions | None = None,
    ) -> IKEAStoreIntelligenceProviderResult:
        if self.disabled:
            return IKEAStoreIntelligenceProviderResult(
                status=ProviderRunStatus.DISABLED,
                capabilities=self.capabilities,
                notes=("IKEA store intelligence provider is disabled.",),
            )
        region_code = options.region_code if options is not None else None
        return IKEAStoreIntelligenceProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            bundle=self.bundle
            or _ikea_bundle(
                product=product,
                region_code=region_code or "US",
            ),
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


def _community_bundle(
    *,
    provider_name: str,
    query: str,
    product_id: str | None,
) -> CommunityDiscussionEvidenceBundle:
    source_id = new_id()
    target_product_id = product_id or new_id()
    url = AnyHttpUrl("https://www.reddit.com/r/BuyItForLife/comments/fixture/thread/")
    discussion = CommunityDiscussionContext(
        source_id=source_id,
        url=url,
        community_name="r/BuyItForLife",
        thread_id="fixture-thread",
        thread_title=f"{query} fixture discussion from {provider_name}",
        comment_count=14,
        extracted_public_summary="Fixture public discussion summary.",
    )
    return CommunityDiscussionEvidenceBundle(
        source_references=(
            SourceReference(
                source_id=source_id,
                url=url,
                title=discussion.thread_title,
            ),
        ),
        discussions=(discussion,),
        evidence=(
            CommunityDiscussionEvidence(
                source_id=source_id,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.PRODUCT,
                    product_id=target_product_id,
                ),
                claim="Fixture community thread reports recurring owner concerns.",
                confidence={"score": 0.6, "level": "medium"},
                source_quality=SourceQuality(level=SourceQualityLevel.MIXED, score=0.6),
                context_source_ids=(source_id,),
                recurring_signal=True,
                evidence_quality_warnings=("Community evidence is qualitative.",),
            ),
        ),
        evidence_gaps=(
            SourceEvidenceGap(
                capability=SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.PRODUCT,
                    product_id=target_product_id,
                ),
                source_id=source_id,
                summary="Fixture provider does not fetch private or deleted content.",
            ),
        ),
    )


def _amazon_bundle(
    *,
    product: CanonicalProduct,
    listing: ProductListing | None,
    region_code: str,
) -> AmazonProductEvidenceBundle:
    source_id = new_id()
    listing_id = listing.listing_id if listing is not None else new_id()
    url = AnyHttpUrl("https://www.amazon.com/dp/B012345678")
    context = AmazonListingContext(
        source_id=source_id,
        marketplace_name="Amazon",
        marketplace_domain="amazon.com",
        marketplace_country_code=region_code,
        listing_url=url,
        asin="B012345678",
        product_title=product.name,
        seller_name="Fixture Marketplace Seller",
        fulfillment="Fulfilled by Amazon",
        ships_to_region_code=region_code,
        ships_to_region=True,
        review_count=128,
        average_rating=4.2,
    )
    return AmazonProductEvidenceBundle(
        source_references=(
            SourceReference(source_id=source_id, url=url, title=product.name),
        ),
        listing_contexts=(context,),
        evidence=(
            AmazonProductEvidence(
                source_id=source_id,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.PRODUCT,
                    product_id=product.product_id,
                ),
                fact_type=AmazonEvidenceFactType.PRODUCT_PAGE_FACT,
                claim="Fixture Amazon page provides product-page facts.",
                confidence={"score": 0.7, "level": "medium"},
                source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE),
                listing_context_source_id=source_id,
            ),
            AmazonProductEvidence(
                source_id=source_id,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.LISTING,
                    listing_id=listing_id,
                ),
                fact_type=AmazonEvidenceFactType.LISTING_IDENTITY,
                claim="Fixture Amazon listing preserves ASIN identity.",
                confidence={"score": 0.75, "level": "high"},
                source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE),
                listing_context_source_id=source_id,
            ),
            AmazonProductEvidence(
                source_id=source_id,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.SELLER,
                    listing_id=listing_id,
                ),
                fact_type=AmazonEvidenceFactType.SELLER_FULFILLMENT,
                claim="Fixture seller and fulfillment context is separate evidence.",
                confidence={"score": 0.65, "level": "medium"},
                source_quality=SourceQuality(level=SourceQualityLevel.MIXED),
                listing_context_source_id=source_id,
            ),
            AmazonProductEvidence(
                source_id=source_id,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.REVIEW,
                    review_id="fixture-review-summary",
                ),
                fact_type=AmazonEvidenceFactType.REVIEW_SUMMARY,
                claim="Fixture Amazon review summary is source-specific evidence.",
                confidence={"score": 0.6, "level": "medium"},
                source_quality=SourceQuality(level=SourceQualityLevel.MIXED),
                listing_context_source_id=source_id,
            ),
            AmazonProductEvidence(
                source_id=source_id,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.REGION,
                    region_code=region_code,
                ),
                fact_type=AmazonEvidenceFactType.REGIONAL_AVAILABILITY,
                claim="Fixture Amazon listing includes ship-to-region evidence.",
                confidence={"score": 0.65, "level": "medium"},
                source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE),
                listing_context_source_id=source_id,
            ),
        ),
        evidence_gaps=(
            SourceEvidenceGap(
                capability=SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.REVIEW,
                    review_id="fixture-review-summary",
                ),
                source_id=source_id,
                summary="Fixture provider does not retrieve individual review text.",
            ),
        ),
    )


def _ikea_bundle(
    *,
    product: CanonicalProduct,
    region_code: str,
) -> IKEAStoreEvidenceBundle:
    source_id = new_id()
    url = AnyHttpUrl("https://www.ikea.com/us/en/p/fixture-product-12345678/")
    context = IKEAStoreContext(
        source_id=source_id,
        country_code=region_code,
        official_url=url,
        product_code="12345678",
        product_name=product.name,
        store_name=f"IKEA {region_code}",
        delivery_area=f"{region_code} online delivery",
        availability=RegionalStoreAvailability.UNKNOWN,
    )
    return IKEAStoreEvidenceBundle(
        source_references=(
            SourceReference(source_id=source_id, url=url, title=product.name),
        ),
        store_contexts=(context,),
        evidence=(
            IKEAStoreEvidence(
                source_id=source_id,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.PRODUCT,
                    product_id=product.product_id,
                ),
                fact_type=IKEAEvidenceFactType.OFFICIAL_PRODUCT_FACT,
                claim="Fixture IKEA page preserves official product context.",
                confidence={"score": 0.7, "level": "medium"},
                source_quality=SourceQuality(level=SourceQualityLevel.STRONG),
                store_context_source_id=source_id,
            ),
            IKEAStoreEvidence(
                source_id=source_id,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.REGION,
                    region_code=region_code,
                ),
                fact_type=IKEAEvidenceFactType.STORE_DELIVERY_CONTEXT,
                claim="Fixture IKEA evidence is scoped to the requested region.",
                confidence={"score": 0.65, "level": "medium"},
                source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE),
                store_context_source_id=source_id,
            ),
        ),
        evidence_gaps=(
            SourceEvidenceGap(
                capability=SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.REGION,
                    region_code=region_code,
                ),
                source_id=source_id,
                summary="Fixture provider does not assert live IKEA inventory.",
            ),
        ),
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
