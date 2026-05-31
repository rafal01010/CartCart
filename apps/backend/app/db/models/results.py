from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.schemas.analysis import (
    CategoryAnalysis,
    ComparisonMatrix,
    ListingTrustAssessment,
    RecommendationBundle,
)
from app.schemas.runs import AgentRunRecord


def _dump_json(
    value: (
        ListingTrustAssessment
        | CategoryAnalysis
        | AgentRunRecord
        | ComparisonMatrix
        | RecommendationBundle
    ),
) -> dict[str, Any]:
    return value.model_dump(mode="json")


class ListingTrustAssessmentRecord(Base):
    __tablename__ = "listing_trust_assessments"
    __table_args__ = (
        Index("ix_listing_trust_assessments_run_id", "run_id"),
        Index("ix_listing_trust_assessments_listing_id", "listing_id"),
    )

    trust_assessment_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    listing_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("product_listings.listing_id"),
        nullable=False,
    )
    level: Mapped[str] = mapped_column(String(40), nullable=False)
    assessed_at: Mapped[str] = mapped_column(String(35), nullable=False)
    assessment: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        trust_assessment_id: UUID,
        run_id: UUID,
        assessment: ListingTrustAssessment,
    ) -> "ListingTrustAssessmentRecord":
        return cls(
            trust_assessment_id=str(trust_assessment_id),
            run_id=str(run_id),
            listing_id=str(assessment.listing_id),
            level=assessment.level.value,
            assessed_at=assessment.assessed_at.isoformat(),
            assessment=_dump_json(assessment),
        )

    def to_schema(self) -> ListingTrustAssessment:
        return ListingTrustAssessment.model_validate(self.assessment)


class CategoryAnalysisRecord(Base):
    __tablename__ = "category_analyses"
    __table_args__ = (
        Index("ix_category_analyses_run_id", "run_id"),
        Index("ix_category_analyses_product_id", "product_id"),
        Index("ix_category_analyses_category", "category"),
    )

    analysis_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    product_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("canonical_products.product_id"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String(200), nullable=False)
    analysis: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        analysis_id: UUID,
        run_id: UUID,
        analysis: CategoryAnalysis,
    ) -> "CategoryAnalysisRecord":
        return cls(
            analysis_id=str(analysis_id),
            run_id=str(run_id),
            product_id=str(analysis.product_id),
            category=analysis.category,
            analysis=_dump_json(analysis),
        )

    def to_schema(self) -> CategoryAnalysis:
        return CategoryAnalysis.model_validate(self.analysis)


class AgentRunRecordModel(Base):
    __tablename__ = "agent_run_records"
    __table_args__ = (
        Index("ix_agent_run_records_run_id", "run_id"),
        Index("ix_agent_run_records_stage", "stage"),
        Index("ix_agent_run_records_agent_name", "agent_name"),
        Index("ix_agent_run_records_trace_id", "trace_id"),
    )

    record_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    stage: Mapped[str] = mapped_column(String(60), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    started_at: Mapped[str] = mapped_column(String(35), nullable=False)
    ended_at: Mapped[str | None] = mapped_column(String(35), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    record: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(cls, record: AgentRunRecord) -> "AgentRunRecordModel":
        return cls(
            record_id=str(record.record_id),
            run_id=str(record.run_id),
            stage=record.stage.value,
            agent_name=record.agent_name,
            status=record.status.value,
            started_at=record.started_at.isoformat(),
            ended_at=record.ended_at.isoformat() if record.ended_at else None,
            trace_id=record.trace_id,
            record=_dump_json(record),
        )

    def to_schema(self) -> AgentRunRecord:
        return AgentRunRecord.model_validate(self.record)


class ComparisonMatrixRecord(Base):
    __tablename__ = "comparison_matrices"
    __table_args__ = (Index("ix_comparison_matrices_run_id", "run_id"),)

    matrix_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    matrix: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[str] = mapped_column(String(35), nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        matrix_id: UUID,
        run_id: UUID,
        matrix: ComparisonMatrix,
        created_at: str,
    ) -> "ComparisonMatrixRecord":
        return cls(
            matrix_id=str(matrix_id),
            run_id=str(run_id),
            matrix=_dump_json(matrix),
            created_at=created_at,
        )

    def to_schema(self) -> ComparisonMatrix:
        return ComparisonMatrix.model_validate(self.matrix)


class RecommendationBundleRecord(Base):
    __tablename__ = "recommendation_bundles"
    __table_args__ = (
        Index("ix_recommendation_bundles_run_id", "run_id"),
        Index("ix_recommendation_bundles_final_product_id", "final_product_id"),
        Index("ix_recommendation_bundles_final_listing_id", "final_listing_id"),
    )

    bundle_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    comparison_matrix_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("comparison_matrices.matrix_id"),
        nullable=False,
    )
    final_product_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("canonical_products.product_id"),
        nullable=True,
    )
    final_listing_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("product_listings.listing_id"),
        nullable=True,
    )
    no_strong_buy: Mapped[bool] = mapped_column(nullable=False)
    bundle: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        run_id: UUID,
        comparison_matrix_id: UUID,
        bundle: RecommendationBundle,
    ) -> "RecommendationBundleRecord":
        return cls(
            bundle_id=str(bundle.bundle_id),
            run_id=str(run_id),
            comparison_matrix_id=str(comparison_matrix_id),
            final_product_id=(
                str(bundle.final_product_id) if bundle.final_product_id else None
            ),
            final_listing_id=(
                str(bundle.final_listing_id) if bundle.final_listing_id else None
            ),
            no_strong_buy=bundle.no_strong_buy,
            bundle=_dump_json(bundle),
        )

    def to_schema(self) -> RecommendationBundle:
        return RecommendationBundle.model_validate(self.bundle)


class ResultVersionRecord(Base):
    __tablename__ = "result_versions"
    __table_args__ = (
        Index("ix_result_versions_run_id", "run_id"),
        Index("ix_result_versions_run_id_version", "run_id", "version"),
        UniqueConstraint("run_id", "version", name="uq_result_versions_run_id_version"),
    )

    result_version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(nullable=False)
    recommendation_bundle_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("recommendation_bundles.bundle_id"),
        nullable=False,
    )
    comparison_matrix_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("comparison_matrices.matrix_id"),
        nullable=False,
    )
    created_at: Mapped[str] = mapped_column(String(35), nullable=False)
