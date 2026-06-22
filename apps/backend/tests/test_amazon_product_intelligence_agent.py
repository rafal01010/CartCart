from dataclasses import dataclass

import pytest

from app.agents import LiveAmazonProductIntelligenceAgent
from app.agents.contracts import AmazonProductIntelligenceAgentInput
from app.providers import (
    AmazonProductIntelligenceProviderOptions,
    AmazonProductIntelligenceProviderResult,
    ProviderCapabilityFlags,
    ProviderRunStatus,
)
from app.schemas.analysis import RecommendationBundle
from app.schemas.ids import new_id
from app.schemas.intake import FieldSource, ShoppingBrief
from app.schemas.products import CanonicalProduct, ProductListing, SellerProfile
from app.schemas.regions import Region
from app.schemas.search_sources import (
    AmazonEvidenceFactType,
    AmazonListingContext,
    AmazonProductEvidenceBundle,
    EvidenceTargetType,
    SourceQuality,
    SourceQualityLevel,
)
from app.schemas.source_references import SourceReference
from app.services.amazon_evidence_creation import (
    AmazonProductEvidenceCreator,
    AmazonProductEvidenceInput,
)


@pytest.mark.asyncio
async def test_amazon_agent_preserves_third_party_seller_region_gap_and_neutral_links() -> (
    None
):
    product, listing = _product_and_listing()
    agent = LiveAmazonProductIntelligenceAgent(
        amazon_provider=_FixtureAmazonProvider(mode="region_gap"),
    )

    output = await agent.run(
        AmazonProductIntelligenceAgentInput(
            run_id=new_id(),
            brief=_brief(),
            products=(product,),
            listings=(listing,),
            product_queries=("fixture monitor third-party amazon",),
            target_region_code="PH",
        )
    )

    assert not isinstance(output, RecommendationBundle)
    assert len(output.source_references) == 1
    assert "tag=" not in str(output.source_references[0].url)
    assert "serpapi" not in str(output.source_references[0].url)

    context = output.listing_contexts[0]
    assert context.marketplace_name == "Amazon"
    assert context.marketplace_domain == "amazon.com"
    assert context.marketplace_country_code == "US"
    assert context.asin == "B0CART5901"
    assert context.seller_name == "Fixture Deals"
    assert context.fulfillment == "Ships from Fixture Deals"
    assert context.ships_to_region_code == "PH"
    assert context.ships_to_region is None
    assert context.review_count == 1287
    assert context.average_rating == 4.4

    evidence_by_type = {item.fact_type: item for item in output.evidence}
    assert AmazonEvidenceFactType.LISTING_IDENTITY in evidence_by_type
    assert AmazonEvidenceFactType.PRODUCT_PAGE_FACT in evidence_by_type
    assert AmazonEvidenceFactType.SELLER_FULFILLMENT in evidence_by_type
    assert AmazonEvidenceFactType.REVIEW_SUMMARY in evidence_by_type
    assert AmazonEvidenceFactType.REVIEW_QUALITY_WARNING in evidence_by_type
    assert AmazonEvidenceFactType.MARKETPLACE_WARNING in evidence_by_type
    assert "listing trust must be assessed separately from product quality" in (
        evidence_by_type[AmazonEvidenceFactType.MARKETPLACE_WARNING].claim
    )
    assert any(
        gap.target is not None
        and gap.target.target_type == EvidenceTargetType.REGION
        and gap.target.region_code == "PH"
        and "could not be confirmed" in gap.summary
        for gap in output.evidence_gaps
    )
    assert [activity["tool_name"] for activity in agent.workbench_activity] == [
        "AmazonProductIntelligenceProvider.fetch_product_evidence",
        "AmazonProductEvidenceBundle.returned",
    ]


@pytest.mark.asyncio
async def test_amazon_agent_preserves_variant_review_ambiguity_warning() -> None:
    product, listing = _product_and_listing(name="Fixture Monitor Variant")
    agent = LiveAmazonProductIntelligenceAgent(
        amazon_provider=_FixtureAmazonProvider(mode="variant"),
    )

    output = await agent.run(
        AmazonProductIntelligenceAgentInput(
            run_id=new_id(),
            brief=_brief(),
            products=(product,),
            listings=(listing,),
            product_queries=("fixture monitor variant amazon",),
            target_region_code="US",
        )
    )

    context = output.listing_contexts[0]
    assert context.asin == "B0CARTVAR1"
    assert context.variant_label == "Color: Space Gray; Size: 27 inch"

    review_warnings = " ".join(
        warning
        for item in output.evidence
        for warning in item.evidence_quality_warnings
    )
    assert "multiple Amazon variants" in review_warnings
    assert any(
        item.fact_type == AmazonEvidenceFactType.REVIEW_QUALITY_WARNING
        and "multiple Amazon variants" in item.claim
        for item in output.evidence
    )


@pytest.mark.asyncio
async def test_amazon_agent_returns_explicit_gap_when_provider_disabled() -> None:
    product, listing = _product_and_listing()
    agent = LiveAmazonProductIntelligenceAgent(
        amazon_provider=_FixtureAmazonProvider(disabled=True),
    )

    output = await agent.run(
        AmazonProductIntelligenceAgentInput(
            run_id=new_id(),
            brief=_brief(),
            products=(product,),
            listings=(listing,),
            target_region_code="US",
        )
    )

    assert output.source_references == ()
    assert output.listing_contexts == ()
    assert output.evidence == ()
    assert output.evidence_gaps
    assert "disabled" in (output.evidence_gaps[0].reason or "").casefold()


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


def _product_and_listing(
    *,
    name: str = "Fixture Monitor",
) -> tuple[CanonicalProduct, ProductListing]:
    source_id = new_id()
    product = CanonicalProduct(
        name=name,
        brand="Fixture",
        model="Monitor 1",
        category="monitor",
        source_ids=(source_id,),
    )
    listing = ProductListing(
        product_id=product.product_id,
        title=f"{name} - Official Store",
        url="https://example.com/monitor/fixture-monitor",
        seller=SellerProfile(seller_name="Fixture Official"),
        source_ids=(source_id,),
    )
    product = product.model_copy(update={"listing_ids": (listing.listing_id,)})
    return product, listing


@dataclass(frozen=True)
class _FixtureAmazonProvider:
    mode: str = "region_gap"
    disabled: bool = False

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name="test-amazon-product-intelligence",
            enabled=not self.disabled,
            supports_amazon_product_intelligence=True,
            supports_amazon_listing_identity=True,
            supports_amazon_review_signals=True,
            supports_regional_ship_to_evidence=True,
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
                notes=("Amazon fixture provider is disabled.",),
            )
        region_code = options.region_code if options is not None else "US"
        return AmazonProductIntelligenceProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            bundle=_amazon_bundle(
                product,
                listing=listings[0] if listings else None,
                region_code=region_code or "US",
                variant=self.mode == "variant",
                shipping_known=self.mode != "region_gap",
            ),
        )


def _amazon_bundle(
    product: CanonicalProduct,
    *,
    listing: ProductListing | None,
    region_code: str,
    variant: bool,
    shipping_known: bool,
) -> AmazonProductEvidenceBundle:
    source_id = new_id()
    listing_id = listing.listing_id if listing is not None else new_id()
    asin = "B0CARTVAR1" if variant else "B0CART5901"
    url = f"https://www.amazon.com/dp/{asin}"
    review_warning = (
        "Review totals or summaries may combine multiple Amazon variants; "
        "the selected ASIN must be checked before applying review claims."
        if variant
        else None
    )
    return AmazonProductEvidenceCreator().create(
        (
            AmazonProductEvidenceInput(
                product_id=product.product_id,
                listing_id=listing_id,
                source_reference=SourceReference(
                    source_id=source_id,
                    url=url,
                    title=product.name,
                ),
                listing_context=AmazonListingContext(
                    source_id=source_id,
                    marketplace_name="Amazon",
                    marketplace_domain="amazon.com",
                    marketplace_country_code="US",
                    listing_url=url,
                    asin=asin,
                    external_listing_id=asin,
                    product_title=product.name,
                    variant_label="Color: Space Gray; Size: 27 inch"
                    if variant
                    else "Size: 27 inch",
                    seller_name="Fixture Deals",
                    fulfillment="Ships from Fixture Deals",
                    ships_to_region_code=region_code,
                    ships_to_region=True if shipping_known else None,
                    review_count=1287,
                    average_rating=4.4,
                ),
                source_quality=SourceQuality(
                    level=SourceQualityLevel.ADEQUATE,
                    score=0.76,
                ),
                product_page_claim=(
                    "Amazon product page states: 27-inch QHD monitor with USB-C."
                ),
                price_claim="Amazon displayed price: $289.99.",
                review_summary_claim=(
                    "Average rating 4.4 out of 5 from 1,287 reviews."
                ),
                review_quality_warnings=(
                    (review_warning,) if review_warning is not None else ()
                ),
            ),
        )
    )
