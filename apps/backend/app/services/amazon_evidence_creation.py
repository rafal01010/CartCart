from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import Field, model_validator

from app.schemas.base import CartCartBaseModel
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import ListingId, ProductId
from app.schemas.search_sources import (
    AmazonEvidenceFactType,
    AmazonListingContext,
    AmazonProductEvidence,
    AmazonProductEvidenceBundle,
    EvidenceTarget,
    EvidenceTargetType,
    SourceEvidenceGap,
    SourceIntelligenceCapability,
    SourceQuality,
)
from app.schemas.source_references import SourceReference


_REVIEW_PROVENANCE_WARNING = (
    "Amazon review signals are marketplace-provided and were not independently "
    "authenticated."
)


class AmazonEvidenceCreationError(ValueError):
    """Raised when Amazon evidence is not grounded in neutral listing context."""


class AmazonProductEvidenceInput(CartCartBaseModel):
    product_id: ProductId
    listing_id: ListingId
    source_reference: SourceReference
    listing_context: AmazonListingContext
    source_quality: SourceQuality
    product_page_claim: str | None = Field(default=None, min_length=1, max_length=2000)
    price_claim: str | None = Field(default=None, min_length=1, max_length=2000)
    review_summary_claim: str | None = Field(
        default=None,
        min_length=1,
        max_length=2000,
    )
    review_quality_warnings: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _source_context_must_match(self) -> "AmazonProductEvidenceInput":
        if self.source_reference.source_id != self.listing_context.source_id:
            raise ValueError("Amazon source and listing context IDs must match.")
        if str(self.source_reference.url) != str(self.listing_context.listing_url):
            raise ValueError("Amazon source and listing context URLs must match.")
        return self


class AmazonProductEvidenceCreator:
    """Create source-backed Amazon evidence from approved normalized provider data."""

    def create(
        self,
        inputs: tuple[AmazonProductEvidenceInput, ...],
    ) -> AmazonProductEvidenceBundle:
        source_references: list[SourceReference] = []
        listing_contexts: list[AmazonListingContext] = []
        evidence: list[AmazonProductEvidence] = []
        gaps: list[SourceEvidenceGap] = []

        for item in inputs:
            self._validate_neutral_listing(item)
            source_references.append(item.source_reference)
            listing_contexts.append(item.listing_context)
            item_evidence, item_gaps = self._create_item(item)
            evidence.extend(item_evidence)
            gaps.extend(item_gaps)

        return AmazonProductEvidenceBundle(
            source_references=tuple(source_references),
            listing_contexts=tuple(listing_contexts),
            evidence=tuple(evidence),
            evidence_gaps=tuple(gaps),
        )

    def _validate_neutral_listing(self, item: AmazonProductEvidenceInput) -> None:
        context = item.listing_context
        parsed = urlsplit(str(context.listing_url))
        hostname = (parsed.hostname or "").casefold().removeprefix("www.")
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or hostname != context.marketplace_domain.casefold().removeprefix("www.")
        ):
            raise AmazonEvidenceCreationError(
                "Amazon evidence requires a neutral marketplace listing URL."
            )
        if context.asin is not None and f"/dp/{context.asin}" not in parsed.path:
            raise AmazonEvidenceCreationError(
                "Amazon listing URLs must preserve the bundled ASIN identity."
            )

    def _create_item(
        self,
        item: AmazonProductEvidenceInput,
    ) -> tuple[list[AmazonProductEvidence], list[SourceEvidenceGap]]:
        context = item.listing_context
        source_id = context.source_id
        listing_identity = context.asin or context.external_listing_id or "unknown"
        title = context.product_title or "title unavailable"
        evidence = [
            _evidence(
                item,
                EvidenceTarget(
                    target_type=EvidenceTargetType.LISTING,
                    listing_id=item.listing_id,
                ),
                AmazonEvidenceFactType.LISTING_IDENTITY,
                (
                    f"Amazon listing {listing_identity} on {context.marketplace_domain} "
                    f"is titled '{title}'."
                ),
                0.94,
                ConfidenceLevel.HIGH,
                "Listing identity came from approved structured marketplace data.",
            )
        ]
        gaps: list[SourceEvidenceGap] = []

        if item.product_page_claim is not None:
            evidence.append(
                _evidence(
                    item,
                    EvidenceTarget(
                        target_type=EvidenceTargetType.PRODUCT,
                        product_id=item.product_id,
                    ),
                    AmazonEvidenceFactType.PRODUCT_PAGE_FACT,
                    item.product_page_claim,
                    0.72,
                    ConfidenceLevel.MEDIUM,
                    "Product-page details are marketplace-provided and may vary by variant.",
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
                    "Amazon product-page facts were unavailable.",
                    "The provider returned listing identity without usable product-page facts.",
                )
            )

        if context.seller_name is not None or context.fulfillment is not None:
            seller_label = context.seller_name or "unknown seller"
            fulfillment_label = context.fulfillment or "fulfillment not stated"
            evidence.append(
                _evidence(
                    item,
                    EvidenceTarget(
                        target_type=EvidenceTargetType.SELLER,
                        listing_id=item.listing_id,
                        seller_name=context.seller_name,
                    ),
                    AmazonEvidenceFactType.SELLER_FULFILLMENT,
                    f"Sold by {seller_label}; {fulfillment_label}.",
                    0.82,
                    ConfidenceLevel.HIGH,
                    "Seller and fulfillment came from the selected marketplace offer.",
                )
            )
            if context.seller_name is not None and not _is_amazon_party(
                context.seller_name
            ):
                evidence.append(
                    _evidence(
                        item,
                        EvidenceTarget(
                            target_type=EvidenceTargetType.LISTING,
                            listing_id=item.listing_id,
                        ),
                        AmazonEvidenceFactType.MARKETPLACE_WARNING,
                        (
                            "This offer is sold by third-party marketplace seller "
                            f"{context.seller_name}; listing trust must be assessed "
                            "separately from product quality."
                        ),
                        0.9,
                        ConfidenceLevel.HIGH,
                        "The selected offer names a non-Amazon seller.",
                    )
                )
        else:
            gaps.append(
                _gap(
                    item,
                    EvidenceTarget(
                        target_type=EvidenceTargetType.LISTING,
                        listing_id=item.listing_id,
                    ),
                    "Amazon seller and fulfillment details were unavailable.",
                    "The provider did not identify the selected offer's seller or fulfillment party.",
                )
            )

        if item.price_claim is not None:
            evidence.append(
                _evidence(
                    item,
                    EvidenceTarget(
                        target_type=EvidenceTargetType.LISTING,
                        listing_id=item.listing_id,
                    ),
                    AmazonEvidenceFactType.PRICE,
                    item.price_claim,
                    0.7,
                    ConfidenceLevel.MEDIUM,
                    "Marketplace price is time- and region-sensitive.",
                )
            )

        if context.ships_to_region_code is not None:
            region_target = EvidenceTarget(
                target_type=EvidenceTargetType.REGION,
                region_code=context.ships_to_region_code,
            )
            if context.ships_to_region is None:
                gaps.append(
                    _gap(
                        item,
                        region_target,
                        (
                            "Amazon shipping to "
                            f"{context.ships_to_region_code} could not be confirmed."
                        ),
                        "The provider returned no conclusive ship-to-region status.",
                    )
                )
            else:
                status = (
                    "showed delivery or availability for"
                    if context.ships_to_region
                    else "was unavailable for delivery to"
                )
                evidence.append(
                    _evidence(
                        item,
                        region_target,
                        AmazonEvidenceFactType.REGIONAL_AVAILABILITY,
                        f"The selected Amazon offer {status} {context.ships_to_region_code}.",
                        0.78,
                        ConfidenceLevel.MEDIUM,
                        "Ship-to-region status came from the selected offer context.",
                    )
                )

        review_target = EvidenceTarget(
            target_type=EvidenceTargetType.REVIEW,
            review_id=(
                f"amazon:{context.marketplace_domain}:"
                f"{context.asin or context.external_listing_id or source_id}:summary"
            ),
        )
        review_warnings = tuple(
            dict.fromkeys(
                (_REVIEW_PROVENANCE_WARNING, *item.review_quality_warnings)
            )
        )
        if item.review_summary_claim is None:
            gaps.append(
                _gap(
                    item,
                    review_target,
                    "Amazon review signals were unavailable.",
                    "The provider returned no rating, review count, or review-summary signal.",
                )
            )
        else:
            evidence.extend(
                (
                    _evidence(
                        item,
                        review_target,
                        AmazonEvidenceFactType.REVIEW_SUMMARY,
                        item.review_summary_claim,
                        0.65,
                        ConfidenceLevel.MEDIUM,
                        "Review totals and summaries came from the marketplace product page.",
                        warnings=review_warnings,
                    ),
                    _evidence(
                        item,
                        review_target,
                        AmazonEvidenceFactType.REVIEW_QUALITY_WARNING,
                        " ".join(review_warnings),
                        0.9,
                        ConfidenceLevel.HIGH,
                        "These are explicit limits of marketplace review metadata.",
                        warnings=review_warnings,
                    ),
                )
            )

        return evidence, gaps


def _evidence(
    item: AmazonProductEvidenceInput,
    target: EvidenceTarget,
    fact_type: AmazonEvidenceFactType,
    claim: str,
    score: float,
    level: ConfidenceLevel,
    rationale: str,
    *,
    warnings: tuple[str, ...] = (),
) -> AmazonProductEvidence:
    return AmazonProductEvidence(
        source_id=item.source_reference.source_id,
        target=target,
        fact_type=fact_type,
        claim=claim,
        confidence=Confidence(score=score, level=level, rationale=rationale),
        source_quality=item.source_quality,
        listing_context_source_id=item.listing_context.source_id,
        evidence_quality_warnings=warnings,
    )


def _gap(
    item: AmazonProductEvidenceInput,
    target: EvidenceTarget,
    summary: str,
    reason: str,
) -> SourceEvidenceGap:
    return SourceEvidenceGap(
        capability=SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW,
        target=target,
        source_id=item.source_reference.source_id,
        summary=summary,
        reason=reason,
        source_quality=item.source_quality,
        confidence=Confidence(
            score=0.86,
            level=ConfidenceLevel.HIGH,
            rationale=reason,
        ),
    )


def _is_amazon_party(value: str) -> bool:
    return "amazon" in value.casefold()
