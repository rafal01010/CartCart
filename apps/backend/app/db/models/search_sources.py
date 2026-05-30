from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.schemas.search_sources import (
    SearchPlan,
    SearchResult,
    SourceEvidence,
    SourceSnapshot,
)


def _dump_json(
    value: SearchPlan | SearchResult | SourceSnapshot | SourceEvidence,
) -> dict[str, Any]:
    return value.model_dump(mode="json")


class SearchPlanRecord(Base):
    __tablename__ = "search_plans"
    __table_args__ = (Index("ix_search_plans_run_id", "run_id"),)

    plan_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[str] = mapped_column(String(35), nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        plan_id: UUID,
        run_id: UUID,
        plan: SearchPlan,
        created_at: datetime,
    ) -> "SearchPlanRecord":
        return cls(
            plan_id=str(plan_id),
            run_id=str(run_id),
            plan=_dump_json(plan),
            created_at=created_at.isoformat(),
        )

    def to_schema(self) -> SearchPlan:
        return SearchPlan.model_validate(self.plan)


class SearchResultRecord(Base):
    __tablename__ = "search_results"
    __table_args__ = (
        Index("ix_search_results_run_id", "run_id"),
        Index("ix_search_results_plan_id", "plan_id"),
        Index("ix_search_results_url", "url"),
        Index("ix_search_results_provider_name", "provider_name"),
        Index(
            "ix_search_results_provider_result_id",
            "provider_name",
            "provider_result_id",
        ),
        Index(
            "ix_search_results_provider_query_id",
            "provider_name",
            "provider_query_id",
        ),
    )

    source_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    plan_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("search_plans.plan_id"),
        nullable=True,
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_result_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    provider_query_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        run_id: UUID,
        result: SearchResult,
        plan_id: UUID | None = None,
    ) -> "SearchResultRecord":
        return cls(
            source_id=str(result.source_id),
            run_id=str(run_id),
            plan_id=str(plan_id) if plan_id is not None else None,
            url=str(result.url),
            provider_name=result.provider.provider_name,
            provider_result_id=result.provider.provider_result_id,
            provider_query_id=result.provider.query_id,
            result=_dump_json(result),
        )

    def to_schema(self) -> SearchResult:
        return SearchResult.model_validate(self.result)


class SourceSnapshotRecord(Base):
    __tablename__ = "source_snapshots"
    __table_args__ = (
        Index("ix_source_snapshots_run_id", "run_id"),
        Index("ix_source_snapshots_search_result_id", "search_result_id"),
        Index("ix_source_snapshots_url", "url"),
        Index("ix_source_snapshots_provider_name", "provider_name"),
        Index(
            "ix_source_snapshots_provider_result_id",
            "provider_name",
            "provider_result_id",
        ),
        Index(
            "ix_source_snapshots_provider_query_id",
            "provider_name",
            "provider_query_id",
        ),
    )

    source_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    search_result_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("search_results.source_id"),
        nullable=True,
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_result_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    provider_query_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    captured_at: Mapped[str] = mapped_column(String(35), nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        run_id: UUID,
        snapshot: SourceSnapshot,
        search_result_id: UUID | None = None,
    ) -> "SourceSnapshotRecord":
        return cls(
            source_id=str(snapshot.source_id),
            run_id=str(run_id),
            search_result_id=(
                str(search_result_id) if search_result_id is not None else None
            ),
            url=str(snapshot.url),
            provider_name=snapshot.provider.provider_name,
            provider_result_id=snapshot.provider.provider_result_id,
            provider_query_id=snapshot.provider.query_id,
            snapshot=_dump_json(snapshot),
            captured_at=snapshot.captured_at.isoformat(),
        )

    def to_schema(self) -> SourceSnapshot:
        return SourceSnapshot.model_validate(self.snapshot)


class SourceEvidenceRecord(Base):
    __tablename__ = "source_evidence"
    __table_args__ = (
        Index("ix_source_evidence_run_id", "run_id"),
        Index("ix_source_evidence_source_id", "source_id"),
    )

    evidence_id: Mapped[str] = mapped_column(String(36), primary_key=True)
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
    evidence_type: Mapped[str] = mapped_column(String(60), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        run_id: UUID,
        evidence: SourceEvidence,
    ) -> "SourceEvidenceRecord":
        return cls(
            evidence_id=str(evidence.evidence_id),
            run_id=str(run_id),
            source_id=str(evidence.source_id),
            evidence_type=evidence.evidence_type.value,
            evidence=_dump_json(evidence),
        )

    def to_schema(self) -> SourceEvidence:
        return SourceEvidence.model_validate(self.evidence)
