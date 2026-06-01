from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.schemas.search_sources import (
    AmazonListingContext,
    AmazonProductEvidence,
    AmazonProductEvidenceBundle,
    CommunityDiscussionContext,
    CommunityDiscussionEvidence,
    CommunityDiscussionEvidenceBundle,
    EvidenceTarget,
    EvidenceTargetType,
    IKEAStoreContext,
    IKEAStoreEvidence,
    IKEAStoreEvidenceBundle,
    SourceEvidenceGap,
)


def _dump_json(
    value: (
        AmazonListingContext
        | AmazonProductEvidence
        | AmazonProductEvidenceBundle
        | CommunityDiscussionContext
        | CommunityDiscussionEvidence
        | CommunityDiscussionEvidenceBundle
        | IKEAStoreContext
        | IKEAStoreEvidence
        | IKEAStoreEvidenceBundle
        | SourceEvidenceGap
    ),
) -> dict[str, Any]:
    return value.model_dump(mode="json")


def _source_target_id(target: EvidenceTarget) -> str | None:
    if (
        target.target_type == EvidenceTargetType.SOURCE_METADATA
        and target.source_id
    ):
        return str(target.source_id)
    return None


class CommunityDiscussionEvidenceBundleRecord(Base):
    __tablename__ = "community_discussion_evidence_bundles"
    __table_args__ = (
        Index("ix_community_discussion_evidence_bundles_run_id", "run_id"),
    )

    bundle_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    bundle: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        run_id: UUID,
        bundle: CommunityDiscussionEvidenceBundle,
    ) -> "CommunityDiscussionEvidenceBundleRecord":
        return cls(
            bundle_id=str(bundle.bundle_id),
            run_id=str(run_id),
            bundle=_dump_json(bundle),
        )

    def to_schema(self) -> CommunityDiscussionEvidenceBundle:
        return CommunityDiscussionEvidenceBundle.model_validate(self.bundle)


class CommunityDiscussionContextRecord(Base):
    __tablename__ = "community_discussion_contexts"
    __table_args__ = (
        Index("ix_community_discussion_contexts_bundle_id", "bundle_id"),
        Index("ix_community_discussion_contexts_run_id", "run_id"),
        Index("ix_community_discussion_contexts_source_id", "source_id"),
        Index("ix_community_discussion_contexts_thread_id", "thread_id"),
        Index("ix_community_discussion_contexts_comment_id", "comment_id"),
    )

    context_record_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    bundle_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("community_discussion_evidence_bundles.bundle_id"),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("source_snapshots.source_id"),
        nullable=False,
    )
    platform: Mapped[str] = mapped_column(String(80), nullable=False)
    community_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    thread_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    comment_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    posted_at: Mapped[str | None] = mapped_column(String(35), nullable=True)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        context_record_id: UUID,
        run_id: UUID,
        bundle_id: UUID,
        context: CommunityDiscussionContext,
    ) -> "CommunityDiscussionContextRecord":
        return cls(
            context_record_id=str(context_record_id),
            bundle_id=str(bundle_id),
            run_id=str(run_id),
            source_id=str(context.source_id),
            platform=context.platform,
            community_name=context.community_name,
            thread_id=context.thread_id,
            comment_id=context.comment_id,
            posted_at=context.posted_at.isoformat() if context.posted_at else None,
            context=_dump_json(context),
        )

    def to_schema(self) -> CommunityDiscussionContext:
        return CommunityDiscussionContext.model_validate(self.context)


class CommunityDiscussionEvidenceRecord(Base):
    __tablename__ = "community_discussion_evidence"
    __table_args__ = (
        Index("ix_community_discussion_evidence_bundle_id", "bundle_id"),
        Index("ix_community_discussion_evidence_run_id", "run_id"),
        Index("ix_community_discussion_evidence_source_id", "source_id"),
        Index("ix_community_discussion_evidence_product_id", "product_id"),
        Index("ix_community_discussion_evidence_listing_id", "listing_id"),
        Index("ix_community_discussion_evidence_candidate_id", "candidate_id"),
        Index("ix_community_discussion_evidence_review_id", "review_id"),
        Index("ix_community_discussion_evidence_region_code", "region_code"),
        Index(
            "ix_community_discussion_evidence_recommendation_claim_id",
            "recommendation_claim_id",
        ),
    )

    evidence_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    bundle_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("community_discussion_evidence_bundles.bundle_id"),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("source_snapshots.source_id"),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(String(60), nullable=False)
    product_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    listing_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    candidate_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    seller_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    review_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    region_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    source_target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    recommendation_claim_id: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    recurring_signal: Mapped[bool] = mapped_column(nullable=False)
    qualitative_signal: Mapped[bool] = mapped_column(nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        run_id: UUID,
        bundle_id: UUID,
        evidence: CommunityDiscussionEvidence,
        recommendation_claim_id: str | None = None,
    ) -> "CommunityDiscussionEvidenceRecord":
        target = evidence.target
        return cls(
            evidence_id=str(evidence.evidence_id),
            bundle_id=str(bundle_id),
            run_id=str(run_id),
            source_id=str(evidence.source_id),
            target_type=target.target_type.value,
            product_id=str(target.product_id) if target.product_id else None,
            listing_id=str(target.listing_id) if target.listing_id else None,
            candidate_id=str(target.candidate_id) if target.candidate_id else None,
            seller_name=target.seller_name,
            review_id=target.review_id,
            region_code=target.region_code,
            source_target_id=_source_target_id(target),
            recommendation_claim_id=recommendation_claim_id,
            recurring_signal=evidence.recurring_signal,
            qualitative_signal=evidence.qualitative_signal,
            evidence=_dump_json(evidence),
        )

    def to_schema(self) -> CommunityDiscussionEvidence:
        return CommunityDiscussionEvidence.model_validate(self.evidence)


class AmazonProductEvidenceBundleRecord(Base):
    __tablename__ = "amazon_product_evidence_bundles"
    __table_args__ = (Index("ix_amazon_product_evidence_bundles_run_id", "run_id"),)

    bundle_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    bundle: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        run_id: UUID,
        bundle: AmazonProductEvidenceBundle,
    ) -> "AmazonProductEvidenceBundleRecord":
        return cls(
            bundle_id=str(bundle.bundle_id),
            run_id=str(run_id),
            bundle=_dump_json(bundle),
        )

    def to_schema(self) -> AmazonProductEvidenceBundle:
        return AmazonProductEvidenceBundle.model_validate(self.bundle)


class AmazonListingContextRecord(Base):
    __tablename__ = "amazon_listing_contexts"
    __table_args__ = (
        Index("ix_amazon_listing_contexts_bundle_id", "bundle_id"),
        Index("ix_amazon_listing_contexts_run_id", "run_id"),
        Index("ix_amazon_listing_contexts_source_id", "source_id"),
        Index("ix_amazon_listing_contexts_marketplace_domain", "marketplace_domain"),
        Index("ix_amazon_listing_contexts_asin", "asin"),
        Index("ix_amazon_listing_contexts_seller_name", "seller_name"),
        Index("ix_amazon_listing_contexts_ships_to_region_code", "ships_to_region_code"),
    )

    context_record_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    bundle_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("amazon_product_evidence_bundles.bundle_id"),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("source_snapshots.source_id"),
        nullable=False,
    )
    marketplace_name: Mapped[str] = mapped_column(String(120), nullable=False)
    marketplace_domain: Mapped[str] = mapped_column(String(200), nullable=False)
    marketplace_country_code: Mapped[str | None] = mapped_column(
        String(12),
        nullable=True,
    )
    asin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    external_listing_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    seller_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ships_to_region_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    ships_to_region: Mapped[bool | None] = mapped_column(nullable=True)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        context_record_id: UUID,
        run_id: UUID,
        bundle_id: UUID,
        context: AmazonListingContext,
    ) -> "AmazonListingContextRecord":
        return cls(
            context_record_id=str(context_record_id),
            bundle_id=str(bundle_id),
            run_id=str(run_id),
            source_id=str(context.source_id),
            marketplace_name=context.marketplace_name,
            marketplace_domain=context.marketplace_domain,
            marketplace_country_code=context.marketplace_country_code,
            asin=context.asin,
            external_listing_id=context.external_listing_id,
            seller_name=context.seller_name,
            ships_to_region_code=context.ships_to_region_code,
            ships_to_region=context.ships_to_region,
            context=_dump_json(context),
        )

    def to_schema(self) -> AmazonListingContext:
        return AmazonListingContext.model_validate(self.context)


class AmazonProductEvidenceRecord(Base):
    __tablename__ = "amazon_product_evidence"
    __table_args__ = (
        Index("ix_amazon_product_evidence_bundle_id", "bundle_id"),
        Index("ix_amazon_product_evidence_run_id", "run_id"),
        Index("ix_amazon_product_evidence_source_id", "source_id"),
        Index("ix_amazon_product_evidence_fact_type", "fact_type"),
        Index("ix_amazon_product_evidence_product_id", "product_id"),
        Index("ix_amazon_product_evidence_listing_id", "listing_id"),
        Index("ix_amazon_product_evidence_candidate_id", "candidate_id"),
        Index("ix_amazon_product_evidence_seller_name", "seller_name"),
        Index("ix_amazon_product_evidence_review_id", "review_id"),
        Index("ix_amazon_product_evidence_region_code", "region_code"),
        Index(
            "ix_amazon_product_evidence_listing_context_source_id",
            "listing_context_source_id",
        ),
        Index(
            "ix_amazon_product_evidence_recommendation_claim_id",
            "recommendation_claim_id",
        ),
    )

    evidence_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    bundle_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("amazon_product_evidence_bundles.bundle_id"),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("source_snapshots.source_id"),
        nullable=False,
    )
    fact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(60), nullable=False)
    product_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    listing_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    candidate_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    seller_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    review_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    region_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    source_target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    listing_context_source_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("source_snapshots.source_id"),
        nullable=True,
    )
    recommendation_claim_id: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        run_id: UUID,
        bundle_id: UUID,
        evidence: AmazonProductEvidence,
        recommendation_claim_id: str | None = None,
    ) -> "AmazonProductEvidenceRecord":
        target = evidence.target
        return cls(
            evidence_id=str(evidence.evidence_id),
            bundle_id=str(bundle_id),
            run_id=str(run_id),
            source_id=str(evidence.source_id),
            fact_type=evidence.fact_type.value,
            target_type=target.target_type.value,
            product_id=str(target.product_id) if target.product_id else None,
            listing_id=str(target.listing_id) if target.listing_id else None,
            candidate_id=str(target.candidate_id) if target.candidate_id else None,
            seller_name=target.seller_name,
            review_id=target.review_id,
            region_code=target.region_code,
            source_target_id=_source_target_id(target),
            listing_context_source_id=(
                str(evidence.listing_context_source_id)
                if evidence.listing_context_source_id
                else None
            ),
            recommendation_claim_id=recommendation_claim_id,
            evidence=_dump_json(evidence),
        )

    def to_schema(self) -> AmazonProductEvidence:
        return AmazonProductEvidence.model_validate(self.evidence)


class IKEAStoreEvidenceBundleRecord(Base):
    __tablename__ = "ikea_store_evidence_bundles"
    __table_args__ = (Index("ix_ikea_store_evidence_bundles_run_id", "run_id"),)

    bundle_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    bundle: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        run_id: UUID,
        bundle: IKEAStoreEvidenceBundle,
    ) -> "IKEAStoreEvidenceBundleRecord":
        return cls(
            bundle_id=str(bundle.bundle_id),
            run_id=str(run_id),
            bundle=_dump_json(bundle),
        )

    def to_schema(self) -> IKEAStoreEvidenceBundle:
        return IKEAStoreEvidenceBundle.model_validate(self.bundle)


class IKEAStoreContextRecord(Base):
    __tablename__ = "ikea_store_contexts"
    __table_args__ = (
        Index("ix_ikea_store_contexts_bundle_id", "bundle_id"),
        Index("ix_ikea_store_contexts_run_id", "run_id"),
        Index("ix_ikea_store_contexts_source_id", "source_id"),
        Index("ix_ikea_store_contexts_country_code", "country_code"),
        Index("ix_ikea_store_contexts_product_code", "product_code"),
        Index("ix_ikea_store_contexts_availability", "availability"),
    )

    context_record_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    bundle_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ikea_store_evidence_bundles.bundle_id"),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("source_snapshots.source_id"),
        nullable=False,
    )
    country_code: Mapped[str] = mapped_column(String(12), nullable=False)
    product_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    store_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    availability: Mapped[str] = mapped_column(String(40), nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        context_record_id: UUID,
        run_id: UUID,
        bundle_id: UUID,
        context: IKEAStoreContext,
    ) -> "IKEAStoreContextRecord":
        return cls(
            context_record_id=str(context_record_id),
            bundle_id=str(bundle_id),
            run_id=str(run_id),
            source_id=str(context.source_id),
            country_code=context.country_code,
            product_code=context.product_code,
            store_name=context.store_name,
            availability=context.availability.value,
            context=_dump_json(context),
        )

    def to_schema(self) -> IKEAStoreContext:
        return IKEAStoreContext.model_validate(self.context)


class IKEAStoreEvidenceRecord(Base):
    __tablename__ = "ikea_store_evidence"
    __table_args__ = (
        Index("ix_ikea_store_evidence_bundle_id", "bundle_id"),
        Index("ix_ikea_store_evidence_run_id", "run_id"),
        Index("ix_ikea_store_evidence_source_id", "source_id"),
        Index("ix_ikea_store_evidence_fact_type", "fact_type"),
        Index("ix_ikea_store_evidence_product_id", "product_id"),
        Index("ix_ikea_store_evidence_listing_id", "listing_id"),
        Index("ix_ikea_store_evidence_candidate_id", "candidate_id"),
        Index("ix_ikea_store_evidence_region_code", "region_code"),
        Index("ix_ikea_store_evidence_store_context_source_id", "store_context_source_id"),
        Index(
            "ix_ikea_store_evidence_recommendation_claim_id",
            "recommendation_claim_id",
        ),
    )

    evidence_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    bundle_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ikea_store_evidence_bundles.bundle_id"),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("source_snapshots.source_id"),
        nullable=False,
    )
    fact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(60), nullable=False)
    product_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    listing_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    candidate_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    seller_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    review_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    region_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    source_target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    store_context_source_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("source_snapshots.source_id"),
        nullable=True,
    )
    recommendation_claim_id: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        run_id: UUID,
        bundle_id: UUID,
        evidence: IKEAStoreEvidence,
        recommendation_claim_id: str | None = None,
    ) -> "IKEAStoreEvidenceRecord":
        target = evidence.target
        return cls(
            evidence_id=str(evidence.evidence_id),
            bundle_id=str(bundle_id),
            run_id=str(run_id),
            source_id=str(evidence.source_id),
            fact_type=evidence.fact_type.value,
            target_type=target.target_type.value,
            product_id=str(target.product_id) if target.product_id else None,
            listing_id=str(target.listing_id) if target.listing_id else None,
            candidate_id=str(target.candidate_id) if target.candidate_id else None,
            seller_name=target.seller_name,
            review_id=target.review_id,
            region_code=target.region_code,
            source_target_id=_source_target_id(target),
            store_context_source_id=(
                str(evidence.store_context_source_id)
                if evidence.store_context_source_id
                else None
            ),
            recommendation_claim_id=recommendation_claim_id,
            evidence=_dump_json(evidence),
        )

    def to_schema(self) -> IKEAStoreEvidence:
        return IKEAStoreEvidence.model_validate(self.evidence)


class ReusableSourceEvidenceGapRecord(Base):
    __tablename__ = "reusable_source_evidence_gaps"
    __table_args__ = (
        Index("ix_reusable_source_evidence_gaps_bundle_id", "bundle_id"),
        Index("ix_reusable_source_evidence_gaps_run_id", "run_id"),
        Index("ix_reusable_source_evidence_gaps_source_id", "source_id"),
        Index("ix_reusable_source_evidence_gaps_capability", "capability"),
        Index("ix_reusable_source_evidence_gaps_product_id", "product_id"),
        Index("ix_reusable_source_evidence_gaps_listing_id", "listing_id"),
        Index("ix_reusable_source_evidence_gaps_review_id", "review_id"),
        Index("ix_reusable_source_evidence_gaps_region_code", "region_code"),
        Index(
            "ix_reusable_source_evidence_gaps_recommendation_claim_id",
            "recommendation_claim_id",
        ),
    )

    gap_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    bundle_id: Mapped[str] = mapped_column(String(36), nullable=False)
    bundle_kind: Mapped[str] = mapped_column(String(60), nullable=False)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    source_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("source_snapshots.source_id"),
        nullable=True,
    )
    capability: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    product_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    listing_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    candidate_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    seller_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    review_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    region_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    source_target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    recommendation_claim_id: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    gap: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        run_id: UUID,
        bundle_id: UUID,
        bundle_kind: str,
        gap: SourceEvidenceGap,
        recommendation_claim_id: str | None = None,
    ) -> "ReusableSourceEvidenceGapRecord":
        target = gap.target
        return cls(
            gap_id=str(gap.gap_id),
            bundle_id=str(bundle_id),
            bundle_kind=bundle_kind,
            run_id=str(run_id),
            source_id=str(gap.source_id) if gap.source_id else None,
            capability=gap.capability.value,
            target_type=target.target_type.value if target else None,
            product_id=(
                str(target.product_id) if target and target.product_id else None
            ),
            listing_id=(
                str(target.listing_id) if target and target.listing_id else None
            ),
            candidate_id=(
                str(target.candidate_id) if target and target.candidate_id else None
            ),
            seller_name=target.seller_name if target else None,
            review_id=target.review_id if target else None,
            region_code=target.region_code if target else None,
            source_target_id=_source_target_id(target) if target else None,
            recommendation_claim_id=recommendation_claim_id,
            gap=_dump_json(gap),
        )

    def to_schema(self) -> SourceEvidenceGap:
        return SourceEvidenceGap.model_validate(self.gap)
