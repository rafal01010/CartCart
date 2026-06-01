from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.source_intelligence import (
    AmazonListingContextRecord,
    AmazonProductEvidenceBundleRecord,
    AmazonProductEvidenceRecord,
    CommunityDiscussionContextRecord,
    CommunityDiscussionEvidenceBundleRecord,
    CommunityDiscussionEvidenceRecord,
    IKEAStoreContextRecord,
    IKEAStoreEvidenceBundleRecord,
    IKEAStoreEvidenceRecord,
    ReusableSourceEvidenceGapRecord,
)
from app.schemas.ids import CandidateId, ListingId, ProductId, RunId, SourceId, new_id
from app.schemas.regions import RegionCode
from app.schemas.search_sources import (
    AmazonListingContext,
    AmazonProductEvidence,
    AmazonProductEvidenceBundle,
    CommunityDiscussionContext,
    CommunityDiscussionEvidence,
    CommunityDiscussionEvidenceBundle,
    EvidenceTargetType,
    IKEAStoreContext,
    IKEAStoreEvidence,
    IKEAStoreEvidenceBundle,
    SourceEvidenceGap,
    SourceIntelligenceCapability,
)


@dataclass(frozen=True)
class SourceIntelligenceEvidenceLink:
    evidence_id: SourceId
    capability: SourceIntelligenceCapability
    run_id: RunId
    source_id: SourceId
    target_type: EvidenceTargetType
    product_id: ProductId | None
    listing_id: ListingId | None
    candidate_id: CandidateId | None
    seller_name: str | None
    review_id: str | None
    region_code: RegionCode | None
    source_target_id: SourceId | None
    recommendation_claim_id: str | None


@dataclass(frozen=True)
class SourceIntelligenceGapLink:
    gap_id: SourceId
    capability: SourceIntelligenceCapability
    run_id: RunId
    source_id: SourceId | None
    bundle_id: SourceId
    bundle_kind: str
    target_type: EvidenceTargetType | None
    product_id: ProductId | None
    listing_id: ListingId | None
    candidate_id: CandidateId | None
    seller_name: str | None
    review_id: str | None
    region_code: RegionCode | None
    source_target_id: SourceId | None
    recommendation_claim_id: str | None


class SourceIntelligenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_community_discussion_bundle(
        self,
        run_id: RunId,
        bundle: CommunityDiscussionEvidenceBundle,
        *,
        recommendation_claim_ids: Mapping[SourceId, str] | None = None,
        gap_recommendation_claim_ids: Mapping[SourceId, str] | None = None,
    ) -> CommunityDiscussionEvidenceBundle:
        bundle_record = CommunityDiscussionEvidenceBundleRecord.from_schema(
            run_id=run_id,
            bundle=bundle,
        )
        self._session.add(bundle_record)
        await self._session.flush()

        for discussion in bundle.discussions:
            self._session.add(
                CommunityDiscussionContextRecord.from_schema(
                    context_record_id=new_id(),
                    run_id=run_id,
                    bundle_id=bundle.bundle_id,
                    context=discussion,
                )
            )

        for evidence in bundle.evidence:
            self._session.add(
                CommunityDiscussionEvidenceRecord.from_schema(
                    run_id=run_id,
                    bundle_id=bundle.bundle_id,
                    evidence=evidence,
                    recommendation_claim_id=(recommendation_claim_ids or {}).get(
                        evidence.evidence_id
                    ),
                )
            )

        self._add_gap_records(
            run_id,
            bundle.bundle_id,
            "community_discussion",
            bundle.evidence_gaps,
            gap_recommendation_claim_ids,
        )
        await self._session.flush()
        return bundle_record.to_schema()

    async def get_community_discussion_bundle(
        self,
        bundle_id: SourceId,
    ) -> CommunityDiscussionEvidenceBundle | None:
        record = await self._session.get(
            CommunityDiscussionEvidenceBundleRecord,
            str(bundle_id),
        )
        if record is None:
            return None
        return record.to_schema()

    async def list_community_discussions(
        self,
        run_id: RunId,
    ) -> tuple[CommunityDiscussionContext, ...]:
        statement: Select[tuple[CommunityDiscussionContextRecord]] = (
            select(CommunityDiscussionContextRecord)
            .where(CommunityDiscussionContextRecord.run_id == str(run_id))
            .order_by(
                CommunityDiscussionContextRecord.thread_id,
                CommunityDiscussionContextRecord.comment_id,
                CommunityDiscussionContextRecord.source_id,
            )
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)

    async def list_community_evidence(
        self,
        run_id: RunId,
    ) -> tuple[CommunityDiscussionEvidence, ...]:
        statement: Select[tuple[CommunityDiscussionEvidenceRecord]] = (
            select(CommunityDiscussionEvidenceRecord)
            .where(CommunityDiscussionEvidenceRecord.run_id == str(run_id))
            .order_by(CommunityDiscussionEvidenceRecord.evidence_id)
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)

    async def add_amazon_product_bundle(
        self,
        run_id: RunId,
        bundle: AmazonProductEvidenceBundle,
        *,
        recommendation_claim_ids: Mapping[SourceId, str] | None = None,
        gap_recommendation_claim_ids: Mapping[SourceId, str] | None = None,
    ) -> AmazonProductEvidenceBundle:
        bundle_record = AmazonProductEvidenceBundleRecord.from_schema(
            run_id=run_id,
            bundle=bundle,
        )
        self._session.add(bundle_record)
        await self._session.flush()

        for context in bundle.listing_contexts:
            self._session.add(
                AmazonListingContextRecord.from_schema(
                    context_record_id=new_id(),
                    run_id=run_id,
                    bundle_id=bundle.bundle_id,
                    context=context,
                )
            )

        for evidence in bundle.evidence:
            self._session.add(
                AmazonProductEvidenceRecord.from_schema(
                    run_id=run_id,
                    bundle_id=bundle.bundle_id,
                    evidence=evidence,
                    recommendation_claim_id=(recommendation_claim_ids or {}).get(
                        evidence.evidence_id
                    ),
                )
            )

        self._add_gap_records(
            run_id,
            bundle.bundle_id,
            "amazon_product",
            bundle.evidence_gaps,
            gap_recommendation_claim_ids,
        )
        await self._session.flush()
        return bundle_record.to_schema()

    async def get_amazon_product_bundle(
        self,
        bundle_id: SourceId,
    ) -> AmazonProductEvidenceBundle | None:
        record = await self._session.get(AmazonProductEvidenceBundleRecord, str(bundle_id))
        if record is None:
            return None
        return record.to_schema()

    async def list_amazon_listing_contexts(
        self,
        run_id: RunId,
    ) -> tuple[AmazonListingContext, ...]:
        statement: Select[tuple[AmazonListingContextRecord]] = (
            select(AmazonListingContextRecord)
            .where(AmazonListingContextRecord.run_id == str(run_id))
            .order_by(
                AmazonListingContextRecord.marketplace_domain,
                AmazonListingContextRecord.asin,
                AmazonListingContextRecord.source_id,
            )
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)

    async def list_amazon_evidence(
        self,
        run_id: RunId,
    ) -> tuple[AmazonProductEvidence, ...]:
        statement: Select[tuple[AmazonProductEvidenceRecord]] = (
            select(AmazonProductEvidenceRecord)
            .where(AmazonProductEvidenceRecord.run_id == str(run_id))
            .order_by(
                AmazonProductEvidenceRecord.fact_type,
                AmazonProductEvidenceRecord.evidence_id,
            )
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)

    async def add_ikea_store_bundle(
        self,
        run_id: RunId,
        bundle: IKEAStoreEvidenceBundle,
        *,
        recommendation_claim_ids: Mapping[SourceId, str] | None = None,
        gap_recommendation_claim_ids: Mapping[SourceId, str] | None = None,
    ) -> IKEAStoreEvidenceBundle:
        bundle_record = IKEAStoreEvidenceBundleRecord.from_schema(
            run_id=run_id,
            bundle=bundle,
        )
        self._session.add(bundle_record)
        await self._session.flush()

        for context in bundle.store_contexts:
            self._session.add(
                IKEAStoreContextRecord.from_schema(
                    context_record_id=new_id(),
                    run_id=run_id,
                    bundle_id=bundle.bundle_id,
                    context=context,
                )
            )

        for evidence in bundle.evidence:
            self._session.add(
                IKEAStoreEvidenceRecord.from_schema(
                    run_id=run_id,
                    bundle_id=bundle.bundle_id,
                    evidence=evidence,
                    recommendation_claim_id=(recommendation_claim_ids or {}).get(
                        evidence.evidence_id
                    ),
                )
            )

        self._add_gap_records(
            run_id,
            bundle.bundle_id,
            "ikea_store",
            bundle.evidence_gaps,
            gap_recommendation_claim_ids,
        )
        await self._session.flush()
        return bundle_record.to_schema()

    async def get_ikea_store_bundle(
        self,
        bundle_id: SourceId,
    ) -> IKEAStoreEvidenceBundle | None:
        record = await self._session.get(IKEAStoreEvidenceBundleRecord, str(bundle_id))
        if record is None:
            return None
        return record.to_schema()

    async def list_ikea_store_contexts(
        self,
        run_id: RunId,
    ) -> tuple[IKEAStoreContext, ...]:
        statement: Select[tuple[IKEAStoreContextRecord]] = (
            select(IKEAStoreContextRecord)
            .where(IKEAStoreContextRecord.run_id == str(run_id))
            .order_by(
                IKEAStoreContextRecord.country_code,
                IKEAStoreContextRecord.product_code,
                IKEAStoreContextRecord.source_id,
            )
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)

    async def list_ikea_evidence(
        self,
        run_id: RunId,
    ) -> tuple[IKEAStoreEvidence, ...]:
        statement: Select[tuple[IKEAStoreEvidenceRecord]] = (
            select(IKEAStoreEvidenceRecord)
            .where(IKEAStoreEvidenceRecord.run_id == str(run_id))
            .order_by(
                IKEAStoreEvidenceRecord.fact_type,
                IKEAStoreEvidenceRecord.evidence_id,
            )
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)

    async def list_reusable_source_evidence_gaps(
        self,
        run_id: RunId,
    ) -> tuple[SourceEvidenceGap, ...]:
        statement: Select[tuple[ReusableSourceEvidenceGapRecord]] = (
            select(ReusableSourceEvidenceGapRecord)
            .where(ReusableSourceEvidenceGapRecord.run_id == str(run_id))
            .order_by(
                ReusableSourceEvidenceGapRecord.capability,
                ReusableSourceEvidenceGapRecord.gap_id,
            )
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)

    async def list_reusable_source_evidence_links(
        self,
        run_id: RunId,
    ) -> tuple[SourceIntelligenceEvidenceLink, ...]:
        community_statement: Select[tuple[CommunityDiscussionEvidenceRecord]] = (
            select(CommunityDiscussionEvidenceRecord)
            .where(CommunityDiscussionEvidenceRecord.run_id == str(run_id))
            .order_by(CommunityDiscussionEvidenceRecord.evidence_id)
        )
        amazon_statement: Select[tuple[AmazonProductEvidenceRecord]] = (
            select(AmazonProductEvidenceRecord)
            .where(AmazonProductEvidenceRecord.run_id == str(run_id))
            .order_by(AmazonProductEvidenceRecord.evidence_id)
        )
        ikea_statement: Select[tuple[IKEAStoreEvidenceRecord]] = (
            select(IKEAStoreEvidenceRecord)
            .where(IKEAStoreEvidenceRecord.run_id == str(run_id))
            .order_by(IKEAStoreEvidenceRecord.evidence_id)
        )
        community_records = (await self._session.scalars(community_statement)).all()
        amazon_records = (await self._session.scalars(amazon_statement)).all()
        ikea_records = (await self._session.scalars(ikea_statement)).all()
        return (
            *(
                _to_evidence_link(
                    record,
                    SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
                )
                for record in community_records
            ),
            *(
                _to_evidence_link(
                    record,
                    SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW,
                )
                for record in amazon_records
            ),
            *(
                _to_evidence_link(
                    record,
                    SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
                )
                for record in ikea_records
            ),
        )

    async def list_reusable_source_gap_links(
        self,
        run_id: RunId,
    ) -> tuple[SourceIntelligenceGapLink, ...]:
        statement: Select[tuple[ReusableSourceEvidenceGapRecord]] = (
            select(ReusableSourceEvidenceGapRecord)
            .where(ReusableSourceEvidenceGapRecord.run_id == str(run_id))
            .order_by(
                ReusableSourceEvidenceGapRecord.capability,
                ReusableSourceEvidenceGapRecord.gap_id,
            )
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(_to_gap_link(record) for record in records)

    def _add_gap_records(
        self,
        run_id: RunId,
        bundle_id: SourceId,
        bundle_kind: str,
        gaps: tuple[SourceEvidenceGap, ...],
        recommendation_claim_ids: Mapping[SourceId, str] | None,
    ) -> None:
        for gap in gaps:
            self._session.add(
                ReusableSourceEvidenceGapRecord.from_schema(
                    run_id=run_id,
                    bundle_id=bundle_id,
                    bundle_kind=bundle_kind,
                    gap=gap,
                    recommendation_claim_id=(recommendation_claim_ids or {}).get(
                        gap.gap_id
                    ),
                )
            )


def _optional_uuid(value: str | None) -> UUID | None:
    return UUID(value) if value else None


def _to_evidence_link(
    record: (
        AmazonProductEvidenceRecord
        | CommunityDiscussionEvidenceRecord
        | IKEAStoreEvidenceRecord
    ),
    capability: SourceIntelligenceCapability,
) -> SourceIntelligenceEvidenceLink:
    return SourceIntelligenceEvidenceLink(
        evidence_id=UUID(record.evidence_id),
        capability=capability,
        run_id=UUID(record.run_id),
        source_id=UUID(record.source_id),
        target_type=EvidenceTargetType(record.target_type),
        product_id=_optional_uuid(record.product_id),
        listing_id=_optional_uuid(record.listing_id),
        candidate_id=_optional_uuid(record.candidate_id),
        seller_name=record.seller_name,
        review_id=record.review_id,
        region_code=record.region_code,
        source_target_id=_optional_uuid(record.source_target_id),
        recommendation_claim_id=record.recommendation_claim_id,
    )


def _to_gap_link(record: ReusableSourceEvidenceGapRecord) -> SourceIntelligenceGapLink:
    return SourceIntelligenceGapLink(
        gap_id=UUID(record.gap_id),
        capability=SourceIntelligenceCapability(record.capability),
        run_id=UUID(record.run_id),
        source_id=_optional_uuid(record.source_id),
        bundle_id=UUID(record.bundle_id),
        bundle_kind=record.bundle_kind,
        target_type=(
            EvidenceTargetType(record.target_type) if record.target_type else None
        ),
        product_id=_optional_uuid(record.product_id),
        listing_id=_optional_uuid(record.listing_id),
        candidate_id=_optional_uuid(record.candidate_id),
        seller_name=record.seller_name,
        review_id=record.review_id,
        region_code=record.region_code,
        source_target_id=_optional_uuid(record.source_target_id),
        recommendation_claim_id=record.recommendation_claim_id,
    )
