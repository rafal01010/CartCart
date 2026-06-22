from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.contracts import AmazonProductIntelligenceAgentInput
from app.core.settings import Settings
from app.providers import (
    AmazonProductIntelligenceProvider,
    AmazonProductIntelligenceProviderOptions,
    AmazonProductIntelligenceProviderResult,
    ProviderRunStatus,
    build_amazon_product_intelligence_provider,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import ProductId
from app.schemas.products import CanonicalProduct, ProductListing
from app.schemas.regions import RegionCode
from app.schemas.search_sources import (
    AmazonListingContext,
    AmazonProductEvidence,
    AmazonProductEvidenceBundle,
    EvidenceTarget,
    EvidenceTargetType,
    SourceEvidenceGap,
    SourceIntelligenceCapability,
)
from app.schemas.source_references import SourceReference


AMAZON_PRODUCT_INTELLIGENCE_AGENT_NAME = "AmazonProductIntelligenceAgent"
_MAX_PRODUCTS = 3


@dataclass
class LiveAmazonProductIntelligenceAgent:
    settings: Settings | None = None
    amazon_provider: AmazonProductIntelligenceProvider | None = None
    max_products: int = _MAX_PRODUCTS
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
        repr=False,
    )

    async def run(
        self,
        input_data: AmazonProductIntelligenceAgentInput,
    ) -> AmazonProductEvidenceBundle:
        provider = self._amazon_provider()
        activity: list[dict[str, Any]] = []
        selected_products = _select_relevant_products(
            input_data,
            limit=self.max_products,
        )

        if not selected_products:
            output = AmazonProductEvidenceBundle(
                evidence_gaps=(_missing_product_gap(),),
            )
            self._workbench_activity = (
                {
                    "tool_name": "AmazonProductIntelligenceProvider.fetch_product_evidence",
                    "status": "not_started_missing_product",
                    "input": {
                        "agent": AMAZON_PRODUCT_INTELLIGENCE_AGENT_NAME,
                        "allowed_tools": ["AmazonProductIntelligenceProvider"],
                    },
                    "output": {"gap_count": len(output.evidence_gaps)},
                },
            )
            return output

        bundles: list[AmazonProductEvidenceBundle] = []
        provider_gaps: list[SourceEvidenceGap] = []
        target_region = _target_region_code(input_data)
        for product in selected_products:
            listings = _select_relevant_listings(input_data.listings, product)
            result = await provider.fetch_product_evidence(
                product,
                listings=listings,
                options=AmazonProductIntelligenceProviderOptions(
                    region_code=target_region,
                ),
            )
            activity.append(_provider_activity(provider, product, listings, result))
            if (
                result.status == ProviderRunStatus.SUCCEEDED
                and result.bundle is not None
            ):
                bundles.append(result.bundle)
            else:
                provider_gaps.append(_provider_gap(product, result))

        output = _merge_amazon_bundles(tuple(bundles), tuple(provider_gaps))
        if not (
            output.source_references
            or output.listing_contexts
            or output.evidence
            or output.evidence_gaps
        ):
            output = AmazonProductEvidenceBundle(
                evidence_gaps=(_empty_provider_gap(selected_products[0]),),
            )

        activity.append(
            {
                "tool_name": "AmazonProductEvidenceBundle.returned",
                "status": "amazon_product_evidence_ready",
                "input": {
                    "agent": AMAZON_PRODUCT_INTELLIGENCE_AGENT_NAME,
                    "allowed_tools": [],
                    "selected_product_count": len(selected_products),
                },
                "output": {
                    "source_count": len(output.source_references),
                    "listing_context_count": len(output.listing_contexts),
                    "evidence_count": len(output.evidence),
                    "gap_count": len(output.evidence_gaps),
                },
            }
        )
        self._workbench_activity = tuple(activity)
        return output

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return self._workbench_activity

    def _amazon_provider(self) -> AmazonProductIntelligenceProvider:
        if self.amazon_provider is not None:
            return self.amazon_provider
        if self.settings is None:
            raise ValueError("settings are required to build the Amazon provider.")
        return build_amazon_product_intelligence_provider(self.settings)


def _provider_activity(
    provider: AmazonProductIntelligenceProvider,
    product: CanonicalProduct,
    listings: tuple[ProductListing, ...],
    result: AmazonProductIntelligenceProviderResult,
) -> dict[str, Any]:
    return {
        "tool_name": "AmazonProductIntelligenceProvider.fetch_product_evidence",
        "status": result.status.value,
        "input": {
            "agent": AMAZON_PRODUCT_INTELLIGENCE_AGENT_NAME,
            "allowed_tools": ["AmazonProductIntelligenceProvider"],
            "product_id": product.product_id,
            "listing_ids": [listing.listing_id for listing in listings],
            "provider_name": provider.capabilities.provider_name,
        },
        "output": {
            "source_count": len(result.bundle.source_references)
            if result.bundle is not None
            else 0,
            "listing_context_count": len(result.bundle.listing_contexts)
            if result.bundle is not None
            else 0,
            "evidence_count": len(result.bundle.evidence)
            if result.bundle is not None
            else 0,
            "gap_count": len(result.bundle.evidence_gaps)
            if result.bundle is not None
            else 0,
            "notes": result.notes,
        },
    }


def _select_relevant_products(
    input_data: AmazonProductIntelligenceAgentInput,
    *,
    limit: int,
) -> tuple[CanonicalProduct, ...]:
    if len(input_data.products) <= limit:
        return input_data.products

    scored = [
        (_product_relevance_score(product, input_data), index, product)
        for index, product in enumerate(input_data.products)
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(product for _, _, product in scored[:limit])


def _select_relevant_listings(
    listings: tuple[ProductListing, ...],
    product: CanonicalProduct,
) -> tuple[ProductListing, ...]:
    product_listings = tuple(
        listing for listing in listings if listing.product_id == product.product_id
    )
    if not product_listings:
        return ()
    amazon_listings = tuple(
        listing for listing in product_listings if _is_amazon_url(str(listing.url))
    )
    return amazon_listings or product_listings


def _product_relevance_score(
    product: CanonicalProduct,
    input_data: AmazonProductIntelligenceAgentInput,
) -> int:
    haystack = _normalized_text(
        " ".join(
            value
            for value in (
                product.name,
                product.brand,
                product.model,
                product.category,
            )
            if value
        )
    )
    haystack_tokens = set(haystack.split())
    needles = (
        *input_data.product_queries,
        input_data.brief.original_query,
        input_data.brief.category or "",
    )
    score = 0
    for needle in needles:
        normalized_needle = _normalized_text(needle)
        if not normalized_needle:
            continue
        needle_tokens = set(normalized_needle.split())
        if normalized_needle in haystack or haystack_tokens & needle_tokens:
            score += 1
    return score


def _target_region_code(
    input_data: AmazonProductIntelligenceAgentInput,
) -> RegionCode | None:
    if input_data.target_region_code is not None:
        return input_data.target_region_code
    if input_data.brief.region is None:
        return None
    return input_data.brief.region.region.country_code


def _provider_gap(
    product: CanonicalProduct,
    result: AmazonProductIntelligenceProviderResult,
) -> SourceEvidenceGap:
    return SourceEvidenceGap(
        capability=SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW,
        target=_product_target(product.product_id),
        summary="Amazon product/listing/review evidence was unavailable.",
        reason=(
            "Amazon product intelligence provider returned "
            f"{result.status.value}."
        ),
        confidence=_confidence(
            0.2,
            ConfidenceLevel.LOW,
            "Amazon provider did not return usable evidence.",
        ),
    )


def _missing_product_gap() -> SourceEvidenceGap:
    return SourceEvidenceGap(
        capability=SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW,
        summary="Amazon product intelligence needs a candidate product.",
        reason=(
            "No product candidate was supplied, so marketplace/listing/review "
            "evidence could not be selected."
        ),
        confidence=_confidence(
            0.95,
            ConfidenceLevel.HIGH,
            "The source-intelligence request contained no products.",
        ),
    )


def _empty_provider_gap(product: CanonicalProduct) -> SourceEvidenceGap:
    return SourceEvidenceGap(
        capability=SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW,
        target=_product_target(product.product_id),
        summary="No relevant Amazon product/listing/review evidence was selected.",
        reason=(
            "The Amazon provider returned no source references, listing contexts, "
            "evidence, or explicit gaps for the selected product."
        ),
        confidence=_confidence(
            0.4,
            ConfidenceLevel.MEDIUM,
            "Amazon provider output was empty.",
        ),
    )


def _merge_amazon_bundles(
    bundles: tuple[AmazonProductEvidenceBundle, ...],
    provider_gaps: tuple[SourceEvidenceGap, ...],
) -> AmazonProductEvidenceBundle:
    source_references_by_id: dict[str, SourceReference] = {}
    listing_contexts_by_id: dict[str, AmazonListingContext] = {}
    evidence: list[AmazonProductEvidence] = []
    evidence_gaps: list[SourceEvidenceGap] = list(provider_gaps)

    for bundle in bundles:
        source_references_by_id.update(
            {reference.source_id: reference for reference in bundle.source_references}
        )
        listing_contexts_by_id.update(
            {context.source_id: context for context in bundle.listing_contexts}
        )
        evidence.extend(bundle.evidence)
        evidence_gaps.extend(bundle.evidence_gaps)

    return AmazonProductEvidenceBundle(
        source_references=tuple(source_references_by_id.values()),
        listing_contexts=tuple(listing_contexts_by_id.values()),
        evidence=tuple(evidence),
        evidence_gaps=tuple(evidence_gaps),
    )


def _product_target(product_id: ProductId) -> EvidenceTarget:
    return EvidenceTarget(
        target_type=EvidenceTargetType.PRODUCT,
        product_id=product_id,
    )


def _is_amazon_url(value: str) -> bool:
    normalized = value.casefold()
    return "://www.amazon." in normalized or "://amazon." in normalized


def _normalized_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _confidence(
    score: float,
    level: ConfidenceLevel,
    rationale: str,
) -> Confidence:
    return Confidence(score=score, level=level, rationale=rationale)
