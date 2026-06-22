from dataclasses import dataclass

import pytest

from app.agents import LiveIKEAStoreIntelligenceAgent
from app.agents.contracts import IKEAStoreIntelligenceAgentInput
from app.providers import (
    IKEAStoreIntelligenceProviderOptions,
    IKEAStoreIntelligenceProviderResult,
    ProviderCapabilityFlags,
    ProviderRunStatus,
)
from app.schemas.analysis import RecommendationBundle
from app.schemas.ids import new_id
from app.schemas.intake import FieldSource, ShoppingBrief
from app.schemas.money import Money
from app.schemas.products import CanonicalProduct, ProductListing, SellerProfile
from app.schemas.regions import Region
from app.schemas.search_sources import (
    EvidenceTarget,
    EvidenceTargetType,
    IKEAEvidenceFactType,
    IKEAStoreContext,
    IKEAStoreEvidenceBundle,
    RegionalStoreAvailability,
    SourceEvidenceGap,
    SourceIntelligenceCapability,
    SourceQuality,
    SourceQualityLevel,
)
from app.schemas.source_references import SourceReference
from app.services.ikea_evidence_creation import (
    IKEAStoreEvidenceCreator,
    IKEAStoreEvidenceInput,
)


@pytest.mark.asyncio
async def test_ikea_agent_preserves_available_regional_product_evidence() -> None:
    product, listing = _product_and_listing()
    agent = LiveIKEAStoreIntelligenceAgent(
        ikea_provider=_FixtureIKEAProvider(mode="available"),
    )

    output = await agent.run(
        IKEAStoreIntelligenceAgentInput(
            run_id=new_id(),
            brief=_brief(region_code="PH", currency="PHP"),
            products=(product,),
            listings=(listing,),
            product_queries=("MICKE desk IKEA Philippines",),
            target_region_code="PH",
        )
    )

    assert not isinstance(output, RecommendationBundle)
    assert len(output.source_references) == 1
    assert len(output.store_contexts) == 1

    source = output.source_references[0]
    context = output.store_contexts[0]
    assert context.source_id == source.source_id
    assert str(source.url) == "https://www.ikea.com/ph/en/p/micke-desk-white-90214308/"
    assert context.country_code == "PH"
    assert context.product_code == "902.143.08"
    assert context.price is not None
    assert str(context.price.amount) == "3990"
    assert context.price.currency == "PHP"
    assert context.availability == RegionalStoreAvailability.AVAILABLE
    assert context.delivery_area == "Available for delivery in Metro Manila."

    evidence_by_type = {item.fact_type: item for item in output.evidence}
    assert {
        IKEAEvidenceFactType.OFFICIAL_PRODUCT_FACT,
        IKEAEvidenceFactType.REGIONAL_PRICE,
        IKEAEvidenceFactType.REGIONAL_AVAILABILITY,
        IKEAEvidenceFactType.STORE_DELIVERY_CONTEXT,
    } <= set(evidence_by_type)
    assert all(item.source_id == source.source_id for item in output.evidence)
    assert all(
        item.target.target_type != EvidenceTargetType.REGION
        or item.target.region_code == "PH"
        for item in output.evidence
    )
    warnings = " ".join(
        warning for item in output.evidence for warning in item.evidence_quality_warnings
    ).casefold()
    assert "shipping elsewhere" in warnings
    assert "global shipping" not in " ".join(item.claim for item in output.evidence)
    assert [activity["tool_name"] for activity in agent.workbench_activity] == [
        "IKEAStoreIntelligenceProvider.fetch_store_evidence",
        "IKEAStoreEvidenceBundle.returned",
    ]


@pytest.mark.asyncio
async def test_ikea_agent_preserves_unavailable_inventory_as_gap() -> None:
    product, listing = _product_and_listing(name="KALLAX shelf unit", model="KALLAX")
    agent = LiveIKEAStoreIntelligenceAgent(
        ikea_provider=_FixtureIKEAProvider(mode="unavailable"),
    )

    output = await agent.run(
        IKEAStoreIntelligenceAgentInput(
            run_id=new_id(),
            brief=_brief(region_code="US", currency="USD"),
            products=(product,),
            listings=(listing,),
            product_queries=("KALLAX shelf unit IKEA US",),
            target_region_code="US",
        )
    )

    assert output.store_contexts[0].availability == (
        RegionalStoreAvailability.OUT_OF_STOCK
    )
    assert any(
        item.fact_type == IKEAEvidenceFactType.REGIONAL_AVAILABILITY
        and "out_of_stock" in item.claim
        for item in output.evidence
    )
    assert any(
        "out of stock" in gap.summary.casefold()
        for gap in output.evidence_gaps
    )


@pytest.mark.asyncio
async def test_ikea_agent_returns_no_regional_presence_gap_without_global_inference() -> (
    None
):
    product, listing = _product_and_listing()
    agent = LiveIKEAStoreIntelligenceAgent(
        ikea_provider=_FixtureIKEAProvider(mode="no_region"),
    )

    output = await agent.run(
        IKEAStoreIntelligenceAgentInput(
            run_id=new_id(),
            brief=_brief(region_code="AQ", currency="USD"),
            products=(product,),
            listings=(listing,),
            product_queries=("MICKE desk IKEA Antarctica",),
            target_region_code="AQ",
        )
    )

    assert output.source_references == ()
    assert output.store_contexts == ()
    assert output.evidence == ()
    assert output.evidence_gaps
    gap = output.evidence_gaps[0]
    assert gap.target is not None
    assert gap.target.target_type == EvidenceTargetType.REGION
    assert gap.target.region_code == "AQ"
    assert "No supported IKEA regional presence" in gap.summary
    gap_text = f"{gap.summary} {gap.reason or ''}".casefold()
    assert "global" not in gap_text
    assert "shipping" not in gap_text


@pytest.mark.asyncio
async def test_ikea_agent_returns_explicit_gap_when_provider_disabled() -> None:
    product, listing = _product_and_listing()
    agent = LiveIKEAStoreIntelligenceAgent(
        ikea_provider=_FixtureIKEAProvider(disabled=True),
    )

    output = await agent.run(
        IKEAStoreIntelligenceAgentInput(
            run_id=new_id(),
            brief=_brief(region_code="US", currency="USD"),
            products=(product,),
            listings=(listing,),
            target_region_code="US",
        )
    )

    assert output.source_references == ()
    assert output.store_contexts == ()
    assert output.evidence == ()
    assert output.evidence_gaps
    assert "disabled" in (output.evidence_gaps[0].reason or "").casefold()


def _brief(*, region_code: str, currency: str) -> ShoppingBrief:
    return ShoppingBrief(
        original_query=f"Can I buy an IKEA desk in {region_code}?",
        category="desk",
        category_source=FieldSource.INFERRED,
        region={
            "region": Region(country_code=region_code, currency=currency),
            "source": FieldSource.USER_PROVIDED,
        },
    )


def _product_and_listing(
    *,
    name: str = "MICKE desk",
    model: str = "MICKE",
) -> tuple[CanonicalProduct, ProductListing]:
    source_id = new_id()
    product = CanonicalProduct(
        name=name,
        brand="IKEA",
        model=model,
        category="desk",
        source_ids=(source_id,),
    )
    listing = ProductListing(
        product_id=product.product_id,
        title=f"{name} - IKEA official store",
        url="https://www.ikea.com/ph/en/p/micke-desk-white-90214308/",
        seller=SellerProfile(seller_name="IKEA"),
        source_ids=(source_id,),
    )
    product = product.model_copy(update={"listing_ids": (listing.listing_id,)})
    return product, listing


@dataclass(frozen=True)
class _FixtureIKEAProvider:
    mode: str = "available"
    disabled: bool = False

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name="fixture-ikea-agent-provider",
            enabled=not self.disabled,
            supports_domain_scoped_search=True,
            supports_official_store_lookup=True,
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
        if self.mode == "no_region":
            return IKEAStoreIntelligenceProviderResult(
                status=ProviderRunStatus.SUCCEEDED,
                capabilities=self.capabilities,
                bundle=IKEAStoreEvidenceBundle(
                    evidence_gaps=(
                        SourceEvidenceGap(
                            capability=(
                                SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE
                            ),
                            target=EvidenceTarget(
                                target_type=EvidenceTargetType.REGION,
                                region_code=region_code or "AQ",
                            ),
                            summary=(
                                "No supported IKEA regional presence is configured "
                                f"for {region_code or 'AQ'}."
                            ),
                            reason=(
                                "The fixture regional source catalog has no official "
                                "country or region path for this target."
                            ),
                        ),
                    ),
                ),
            )
        return IKEAStoreIntelligenceProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            bundle=_ikea_bundle(product, mode=self.mode, region_code=region_code or "PH"),
        )


def _ikea_bundle(
    product: CanonicalProduct,
    *,
    mode: str,
    region_code: str,
) -> IKEAStoreEvidenceBundle:
    source_id = new_id()
    unavailable = mode == "unavailable"
    url = (
        "https://www.ikea.com/us/en/p/kallax-shelf-unit-white-80275887/"
        if unavailable
        else "https://www.ikea.com/ph/en/p/micke-desk-white-90214308/"
    )
    return IKEAStoreEvidenceCreator().create(
        (
            IKEAStoreEvidenceInput(
                product_id=product.product_id,
                source_reference=SourceReference(
                    source_id=source_id,
                    url=url,
                    title=f"{product.name} - IKEA",
                ),
                store_context=IKEAStoreContext(
                    source_id=source_id,
                    country_code=region_code,
                    official_url=url,
                    product_code="802.758.87" if unavailable else "902.143.08",
                    product_name=product.name,
                    store_name="IKEA US" if unavailable else "IKEA Pasay City",
                    delivery_area=(
                        "Not available for delivery in this ZIP code."
                        if unavailable
                        else "Available for delivery in Metro Manila."
                    ),
                    price=(
                        Money(amount="89.99", currency="USD")
                        if unavailable
                        else Money(amount="3990", currency="PHP")
                    ),
                    availability=(
                        RegionalStoreAvailability.OUT_OF_STOCK
                        if unavailable
                        else RegionalStoreAvailability.AVAILABLE
                    ),
                ),
                source_quality=SourceQuality(
                    level=SourceQualityLevel.STRONG,
                    score=0.93,
                ),
                product_page_claim=(
                    f"Official IKEA product page: {product.name}. "
                    "Product number: "
                    f"{'802.758.87' if unavailable else '902.143.08'}."
                ),
            ),
        )
    )
