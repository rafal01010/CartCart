from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.contracts import IKEAStoreIntelligenceAgentInput
from app.core.settings import Settings
from app.providers import (
    IKEAStoreIntelligenceProvider,
    IKEAStoreIntelligenceProviderOptions,
    IKEAStoreIntelligenceProviderResult,
    ProviderRunStatus,
    build_ikea_store_intelligence_provider,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import ProductId
from app.schemas.products import CanonicalProduct
from app.schemas.regions import RegionCode
from app.schemas.search_sources import (
    EvidenceTarget,
    EvidenceTargetType,
    IKEAStoreContext,
    IKEAStoreEvidence,
    IKEAStoreEvidenceBundle,
    SourceEvidenceGap,
    SourceIntelligenceCapability,
)
from app.schemas.source_references import SourceReference


IKEA_STORE_INTELLIGENCE_AGENT_NAME = "IKEAStoreIntelligenceAgent"
_MAX_PRODUCTS = 3
_REGIONAL_SCOPE_WARNING = (
    "IKEA official-store evidence applies only to the declared country or "
    "region; it does not establish availability or shipping elsewhere."
)


@dataclass
class LiveIKEAStoreIntelligenceAgent:
    settings: Settings | None = None
    ikea_provider: IKEAStoreIntelligenceProvider | None = None
    max_products: int = _MAX_PRODUCTS
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
        repr=False,
    )

    async def run(
        self,
        input_data: IKEAStoreIntelligenceAgentInput,
    ) -> IKEAStoreEvidenceBundle:
        provider = self._ikea_provider()
        activity: list[dict[str, Any]] = []
        selected_products = _select_relevant_products(
            input_data,
            limit=self.max_products,
        )

        if not selected_products:
            output = IKEAStoreEvidenceBundle(evidence_gaps=(_missing_product_gap(),))
            self._workbench_activity = (
                {
                    "tool_name": "IKEAStoreIntelligenceProvider.fetch_store_evidence",
                    "status": "not_started_missing_product",
                    "input": {
                        "agent": IKEA_STORE_INTELLIGENCE_AGENT_NAME,
                        "allowed_tools": ["IKEAStoreIntelligenceProvider"],
                    },
                    "output": {"gap_count": len(output.evidence_gaps)},
                },
            )
            return output

        bundles: list[IKEAStoreEvidenceBundle] = []
        provider_gaps: list[SourceEvidenceGap] = []
        target_region = _target_region_code(input_data)
        for product in selected_products:
            result = await provider.fetch_store_evidence(
                product,
                options=IKEAStoreIntelligenceProviderOptions(
                    region_code=target_region,
                ),
            )
            activity.append(_provider_activity(provider, product, result))
            if (
                result.status == ProviderRunStatus.SUCCEEDED
                and result.bundle is not None
            ):
                bundles.append(_ensure_regional_scope_warnings(result.bundle))
            else:
                provider_gaps.append(_provider_gap(product, result))

        output = _merge_ikea_bundles(tuple(bundles), tuple(provider_gaps))
        if not (
            output.source_references
            or output.store_contexts
            or output.evidence
            or output.evidence_gaps
        ):
            output = IKEAStoreEvidenceBundle(
                evidence_gaps=(_empty_provider_gap(selected_products[0]),),
            )

        activity.append(
            {
                "tool_name": "IKEAStoreEvidenceBundle.returned",
                "status": "ikea_store_evidence_ready",
                "input": {
                    "agent": IKEA_STORE_INTELLIGENCE_AGENT_NAME,
                    "allowed_tools": [],
                    "selected_product_count": len(selected_products),
                    "target_region_code": target_region,
                },
                "output": {
                    "source_count": len(output.source_references),
                    "store_context_count": len(output.store_contexts),
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

    def _ikea_provider(self) -> IKEAStoreIntelligenceProvider:
        if self.ikea_provider is not None:
            return self.ikea_provider
        if self.settings is None:
            raise ValueError("settings are required to build the IKEA provider.")
        return build_ikea_store_intelligence_provider(self.settings)


def _provider_activity(
    provider: IKEAStoreIntelligenceProvider,
    product: CanonicalProduct,
    result: IKEAStoreIntelligenceProviderResult,
) -> dict[str, Any]:
    return {
        "tool_name": "IKEAStoreIntelligenceProvider.fetch_store_evidence",
        "status": result.status.value,
        "input": {
            "agent": IKEA_STORE_INTELLIGENCE_AGENT_NAME,
            "allowed_tools": ["IKEAStoreIntelligenceProvider"],
            "product_id": product.product_id,
            "provider_name": provider.capabilities.provider_name,
        },
        "output": {
            "source_count": len(result.bundle.source_references)
            if result.bundle is not None
            else 0,
            "store_context_count": len(result.bundle.store_contexts)
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
    input_data: IKEAStoreIntelligenceAgentInput,
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


def _product_relevance_score(
    product: CanonicalProduct,
    input_data: IKEAStoreIntelligenceAgentInput,
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
    score = 1 if "ikea" in haystack_tokens else 0
    for needle in needles:
        normalized_needle = _normalized_text(needle)
        if not normalized_needle:
            continue
        needle_tokens = set(normalized_needle.split())
        if "ikea" in needle_tokens:
            score += 1
        if normalized_needle in haystack or haystack_tokens & needle_tokens:
            score += 1
    return score


def _target_region_code(
    input_data: IKEAStoreIntelligenceAgentInput,
) -> RegionCode | None:
    if input_data.target_region_code is not None:
        return input_data.target_region_code
    if input_data.brief.region is None:
        return None
    return input_data.brief.region.region.country_code


def _provider_gap(
    product: CanonicalProduct,
    result: IKEAStoreIntelligenceProviderResult,
) -> SourceEvidenceGap:
    return SourceEvidenceGap(
        capability=SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
        target=_product_target(product.product_id),
        summary="IKEA regional official-store evidence was unavailable.",
        reason=(
            "IKEA store intelligence provider returned "
            f"{result.status.value}."
        ),
        confidence=_confidence(
            0.2,
            ConfidenceLevel.LOW,
            "IKEA provider did not return usable regional official-store evidence.",
        ),
    )


def _missing_product_gap() -> SourceEvidenceGap:
    return SourceEvidenceGap(
        capability=SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
        summary="IKEA store intelligence needs a candidate product.",
        reason=(
            "No product candidate was supplied, so regional official-store "
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
        capability=SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
        target=_product_target(product.product_id),
        summary="No relevant IKEA regional official-store evidence was selected.",
        reason=(
            "The IKEA provider returned no source references, store contexts, "
            "evidence, or explicit gaps for the selected product."
        ),
        confidence=_confidence(
            0.4,
            ConfidenceLevel.MEDIUM,
            "IKEA provider output was empty.",
        ),
    )


def _merge_ikea_bundles(
    bundles: tuple[IKEAStoreEvidenceBundle, ...],
    provider_gaps: tuple[SourceEvidenceGap, ...],
) -> IKEAStoreEvidenceBundle:
    source_references_by_id: dict[str, SourceReference] = {}
    store_contexts_by_id: dict[str, IKEAStoreContext] = {}
    evidence: list[IKEAStoreEvidence] = []
    evidence_gaps: list[SourceEvidenceGap] = list(provider_gaps)

    for bundle in bundles:
        source_references_by_id.update(
            {reference.source_id: reference for reference in bundle.source_references}
        )
        store_contexts_by_id.update(
            {context.source_id: context for context in bundle.store_contexts}
        )
        evidence.extend(bundle.evidence)
        evidence_gaps.extend(bundle.evidence_gaps)

    return IKEAStoreEvidenceBundle(
        source_references=tuple(source_references_by_id.values()),
        store_contexts=tuple(store_contexts_by_id.values()),
        evidence=tuple(evidence),
        evidence_gaps=tuple(evidence_gaps),
    )


def _ensure_regional_scope_warnings(
    bundle: IKEAStoreEvidenceBundle,
) -> IKEAStoreEvidenceBundle:
    context_by_id = {context.source_id: context for context in bundle.store_contexts}
    evidence = tuple(
        _ensure_evidence_warning(item, context_by_id) for item in bundle.evidence
    )
    return bundle.model_copy(update={"evidence": evidence})


def _ensure_evidence_warning(
    item: IKEAStoreEvidence,
    context_by_id: dict[str, IKEAStoreContext],
) -> IKEAStoreEvidence:
    warning_text = " ".join(item.evidence_quality_warnings).casefold()
    if "shipping elsewhere" in warning_text or "global" in warning_text:
        return item

    context = (
        context_by_id.get(item.store_context_source_id)
        if item.store_context_source_id is not None
        else None
    )
    region_label = (
        context.country_code
        if context is not None
        else item.target.region_code
        if item.target.region_code is not None
        else "the declared country or region"
    )
    warning = _REGIONAL_SCOPE_WARNING.replace(
        "the declared country or region",
        region_label,
    )
    return item.model_copy(
        update={
            "evidence_quality_warnings": (
                *item.evidence_quality_warnings,
                warning,
            ),
        }
    )


def _product_target(product_id: ProductId) -> EvidenceTarget:
    return EvidenceTarget(
        target_type=EvidenceTargetType.PRODUCT,
        product_id=product_id,
    )


def _normalized_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _confidence(
    score: float,
    level: ConfidenceLevel,
    rationale: str,
) -> Confidence:
    return Confidence(score=score, level=level, rationale=rationale)
