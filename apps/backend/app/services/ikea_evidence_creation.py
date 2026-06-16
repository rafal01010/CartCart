from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import Field, model_validator

from app.core.ikea_regions import IKEA_REGION_PATHS
from app.schemas.base import CartCartBaseModel
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import ProductId
from app.schemas.search_sources import (
    EvidenceTarget,
    EvidenceTargetType,
    IKEAEvidenceFactType,
    IKEAStoreContext,
    IKEAStoreEvidence,
    IKEAStoreEvidenceBundle,
    RegionalStoreAvailability,
    SourceEvidenceGap,
    SourceIntelligenceCapability,
    SourceQuality,
)
from app.schemas.source_references import SourceReference


class IKEAStoreEvidenceCreationError(ValueError):
    """Raised when IKEA evidence is not grounded in regional official context."""


class IKEAStoreEvidenceInput(CartCartBaseModel):
    product_id: ProductId
    source_reference: SourceReference
    store_context: IKEAStoreContext
    source_quality: SourceQuality
    product_page_claim: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def _source_context_must_match(self) -> "IKEAStoreEvidenceInput":
        if self.source_reference.source_id != self.store_context.source_id:
            raise ValueError("IKEA source and store context IDs must match.")
        if str(self.source_reference.url) != str(self.store_context.official_url):
            raise ValueError("IKEA source and store context URLs must match.")
        return self


class IKEAStoreEvidenceCreator:
    """Create source-backed IKEA evidence from approved regional store data."""

    def create(
        self,
        inputs: tuple[IKEAStoreEvidenceInput, ...],
        *,
        evidence_gaps: tuple[SourceEvidenceGap, ...] = (),
    ) -> IKEAStoreEvidenceBundle:
        source_references: list[SourceReference] = []
        store_contexts: list[IKEAStoreContext] = []
        evidence: list[IKEAStoreEvidence] = []
        gaps = list(evidence_gaps)

        for item in inputs:
            self._validate_regional_official_url(item)
            source_references.append(item.source_reference)
            store_contexts.append(item.store_context)
            item_evidence, item_gaps = self._create_item(item)
            evidence.extend(item_evidence)
            gaps.extend(item_gaps)

        return IKEAStoreEvidenceBundle(
            source_references=tuple(source_references),
            store_contexts=tuple(store_contexts),
            evidence=tuple(evidence),
            evidence_gaps=tuple(gaps),
        )

    def _validate_regional_official_url(self, item: IKEAStoreEvidenceInput) -> None:
        context = item.store_context
        regional_path = IKEA_REGION_PATHS.get(context.country_code)
        if regional_path is None:
            raise IKEAStoreEvidenceCreationError(
                "IKEA store evidence requires a supported regional context."
            )

        expected_domain, expected_path = regional_path
        parsed = urlsplit(str(context.official_url))
        hostname = (parsed.hostname or "").casefold().removeprefix("www.")
        normalized_path = parsed.path.casefold().rstrip("/")
        normalized_expected_path = expected_path.casefold().rstrip("/")
        domain_matches = hostname == expected_domain or hostname.endswith(
            f".{expected_domain}"
        )
        path_matches = not normalized_expected_path or normalized_path.startswith(
            normalized_expected_path
        )
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not domain_matches
            or not path_matches
        ):
            raise IKEAStoreEvidenceCreationError(
                "IKEA evidence requires a neutral official URL for the declared region."
            )

    def _create_item(
        self,
        item: IKEAStoreEvidenceInput,
    ) -> tuple[list[IKEAStoreEvidence], list[SourceEvidenceGap]]:
        context = item.store_context
        region_target = EvidenceTarget(
            target_type=EvidenceTargetType.REGION,
            region_code=context.country_code,
        )
        evidence: list[IKEAStoreEvidence] = []
        gaps: list[SourceEvidenceGap] = []

        if item.product_page_claim is not None:
            evidence.append(
                _evidence(
                    item,
                    EvidenceTarget(
                        target_type=EvidenceTargetType.PRODUCT,
                        product_id=item.product_id,
                    ),
                    IKEAEvidenceFactType.OFFICIAL_PRODUCT_FACT,
                    item.product_page_claim,
                    0.9,
                    ConfidenceLevel.HIGH,
                    "The fact came from approved official regional IKEA product data.",
                )
            )
        else:
            gaps.append(
                _gap(
                    item,
                    EvidenceTarget(
                        target_type=EvidenceTargetType.PRODUCT,
                        product_id=item.product_id,
                    ),
                    "Official IKEA product-page facts were unavailable.",
                    "The provider returned regional store context without usable product facts.",
                )
            )

        if context.price is not None:
            evidence.append(
                _evidence(
                    item,
                    region_target,
                    IKEAEvidenceFactType.REGIONAL_PRICE,
                    (
                        f"The official IKEA {context.country_code} source lists "
                        f"{context.price.currency} {context.price.amount}."
                    ),
                    0.82,
                    ConfidenceLevel.HIGH,
                    "The price and currency came from the declared IKEA region.",
                )
            )
        else:
            gaps.append(
                _gap(
                    item,
                    region_target,
                    "A regional IKEA price was unavailable.",
                    "The approved regional source did not provide a price and currency.",
                )
            )

        if context.availability in {
            RegionalStoreAvailability.UNKNOWN,
            RegionalStoreAvailability.REGION_UNSUPPORTED,
        }:
            gaps.append(
                _gap(
                    item,
                    region_target,
                    "Regional IKEA availability was not confirmed.",
                    "The approved regional source did not establish stock, pickup, or delivery availability.",
                )
            )
        else:
            evidence.append(
                _evidence(
                    item,
                    region_target,
                    IKEAEvidenceFactType.REGIONAL_AVAILABILITY,
                    (
                        f"The official IKEA {context.country_code} source reports "
                        f"availability as {context.availability.value}."
                    ),
                    0.8,
                    ConfidenceLevel.HIGH,
                    "Availability is limited to the declared IKEA region.",
                )
            )
            if context.availability in {
                RegionalStoreAvailability.OUT_OF_STOCK,
                RegionalStoreAvailability.DELIVERY_UNAVAILABLE,
            }:
                gaps.append(
                    _gap(
                        item,
                        region_target,
                        (
                            f"The product is {context.availability.value.replace('_', ' ')} "
                            f"in the IKEA {context.country_code} region."
                        ),
                        "The official regional source reported that the purchase path is unavailable.",
                    )
                )

        store_delivery_claim = _store_delivery_claim(context)
        if store_delivery_claim is not None:
            evidence.append(
                _evidence(
                    item,
                    region_target,
                    IKEAEvidenceFactType.STORE_DELIVERY_CONTEXT,
                    store_delivery_claim,
                    0.76,
                    ConfidenceLevel.MEDIUM,
                    "Store and delivery details apply only to the declared IKEA region.",
                )
            )
        else:
            gaps.append(
                _gap(
                    item,
                    region_target,
                    "IKEA store, pickup, or delivery context was unavailable.",
                    "The approved regional source did not identify a store or delivery area.",
                )
            )

        return evidence, gaps


def _evidence(
    item: IKEAStoreEvidenceInput,
    target: EvidenceTarget,
    fact_type: IKEAEvidenceFactType,
    claim: str,
    score: float,
    level: ConfidenceLevel,
    rationale: str,
) -> IKEAStoreEvidence:
    region_warning = (
        f"IKEA price, stock, pickup, and delivery evidence applies only to "
        f"{item.store_context.country_code}; it does not establish availability or "
        "shipping elsewhere."
    )
    return IKEAStoreEvidence(
        source_id=item.source_reference.source_id,
        target=target,
        fact_type=fact_type,
        claim=claim,
        confidence=Confidence(score=score, level=level, rationale=rationale),
        source_quality=item.source_quality,
        store_context_source_id=item.store_context.source_id,
        evidence_quality_warnings=(region_warning,),
    )


def _gap(
    item: IKEAStoreEvidenceInput,
    target: EvidenceTarget,
    summary: str,
    reason: str,
) -> SourceEvidenceGap:
    return SourceEvidenceGap(
        capability=SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
        target=target,
        source_id=item.source_reference.source_id,
        summary=summary,
        reason=reason,
        source_quality=item.source_quality,
        confidence=Confidence(
            score=0.9,
            level=ConfidenceLevel.HIGH,
            rationale=reason,
        ),
    )


def _store_delivery_claim(context: IKEAStoreContext) -> str | None:
    details: list[str] = []
    if context.store_name is not None:
        details.append(f"store: {context.store_name}")
    if context.delivery_area is not None:
        details.append(f"delivery or pickup context: {context.delivery_area}")
    if not details:
        return None
    return f"For IKEA {context.country_code}, " + "; ".join(details) + "."
