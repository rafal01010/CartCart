from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.results import (
    AgentRunRecordModel,
    CategoryAnalysisRecord,
    ComparisonMatrixRecord,
    ListingTrustAssessmentRecord,
    RecommendationBundleRecord,
    ResultVersionRecord,
)
from app.db.models.runs import ShoppingRunRecordModel
from app.schemas.analysis import (
    CategoryAnalysis,
    ComparisonMatrix,
    ListingTrustAssessment,
    RecommendationBundle,
)
from app.schemas.ids import CandidateId, RunId, SessionId, new_id
from app.schemas.runs import AgentRunRecord
from app.schemas.timestamps import utc_now


@dataclass(frozen=True)
class ResultVersion:
    result_version_id: CandidateId
    run_id: RunId
    version: int
    recommendation_bundle_id: CandidateId
    comparison_matrix_id: CandidateId


@dataclass(frozen=True)
class SavedResultBundle:
    result_version: ResultVersion
    trust_assessments: tuple[ListingTrustAssessment, ...]
    category_analyses: tuple[CategoryAnalysis, ...]
    agent_records: tuple[AgentRunRecord, ...]
    comparison_matrix: ComparisonMatrix
    recommendation_bundle: RecommendationBundle


class ResultRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_listing_trust_assessment(
        self,
        run_id: RunId,
        assessment: ListingTrustAssessment,
    ) -> ListingTrustAssessment:
        record = ListingTrustAssessmentRecord.from_schema(
            trust_assessment_id=new_id(),
            run_id=run_id,
            assessment=assessment,
        )
        self._session.add(record)
        await self._session.flush()
        return record.to_schema()

    async def list_listing_trust_assessments(
        self,
        run_id: RunId,
    ) -> tuple[ListingTrustAssessment, ...]:
        statement: Select[tuple[ListingTrustAssessmentRecord]] = (
            select(ListingTrustAssessmentRecord)
            .where(ListingTrustAssessmentRecord.run_id == str(run_id))
            .order_by(
                ListingTrustAssessmentRecord.listing_id,
                ListingTrustAssessmentRecord.assessed_at,
            )
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)

    async def add_category_analysis(
        self,
        run_id: RunId,
        analysis: CategoryAnalysis,
    ) -> CategoryAnalysis:
        record = CategoryAnalysisRecord.from_schema(
            analysis_id=new_id(),
            run_id=run_id,
            analysis=analysis,
        )
        self._session.add(record)
        await self._session.flush()
        return record.to_schema()

    async def list_category_analyses(
        self,
        run_id: RunId,
    ) -> tuple[CategoryAnalysis, ...]:
        statement: Select[tuple[CategoryAnalysisRecord]] = (
            select(CategoryAnalysisRecord)
            .where(CategoryAnalysisRecord.run_id == str(run_id))
            .order_by(CategoryAnalysisRecord.product_id, CategoryAnalysisRecord.category)
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)

    async def add_agent_record(self, record: AgentRunRecord) -> AgentRunRecord:
        db_record = AgentRunRecordModel.from_schema(record)
        self._session.add(db_record)
        await self._session.flush()
        return db_record.to_schema()

    async def list_agent_records(self, run_id: RunId) -> tuple[AgentRunRecord, ...]:
        statement: Select[tuple[AgentRunRecordModel]] = (
            select(AgentRunRecordModel)
            .where(AgentRunRecordModel.run_id == str(run_id))
            .order_by(AgentRunRecordModel.started_at, AgentRunRecordModel.agent_name)
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)

    async def add_comparison_matrix(
        self,
        run_id: RunId,
        matrix: ComparisonMatrix,
        *,
        matrix_id: CandidateId | None = None,
    ) -> CandidateId:
        created_matrix_id = matrix_id or new_id()
        record = ComparisonMatrixRecord.from_schema(
            matrix_id=created_matrix_id,
            run_id=run_id,
            matrix=matrix,
            created_at=utc_now().isoformat(),
        )
        self._session.add(record)
        await self._session.flush()
        return created_matrix_id

    async def get_comparison_matrix(
        self,
        matrix_id: CandidateId,
    ) -> ComparisonMatrix | None:
        record = await self._session.get(ComparisonMatrixRecord, str(matrix_id))
        if record is None:
            return None
        return record.to_schema()

    async def add_recommendation_bundle(
        self,
        run_id: RunId,
        bundle: RecommendationBundle,
        *,
        comparison_matrix_id: CandidateId,
    ) -> RecommendationBundle:
        record = RecommendationBundleRecord.from_schema(
            run_id=run_id,
            comparison_matrix_id=comparison_matrix_id,
            bundle=bundle,
        )
        self._session.add(record)
        await self._session.flush()
        return record.to_schema()

    async def get_recommendation_bundle(
        self,
        bundle_id: CandidateId,
    ) -> RecommendationBundle | None:
        record = await self._session.get(RecommendationBundleRecord, str(bundle_id))
        if record is None:
            return None
        return record.to_schema()

    async def save_result_bundle(
        self,
        run_id: RunId,
        *,
        trust_assessments: tuple[ListingTrustAssessment, ...],
        category_analyses: tuple[CategoryAnalysis, ...],
        agent_records: tuple[AgentRunRecord, ...],
        recommendation_bundle: RecommendationBundle,
    ) -> SavedResultBundle:
        for assessment in trust_assessments:
            await self.add_listing_trust_assessment(run_id, assessment)
        for analysis in category_analyses:
            await self.add_category_analysis(run_id, analysis)
        for record in agent_records:
            await self.add_agent_record(record)

        matrix_id = await self.add_comparison_matrix(
            run_id,
            recommendation_bundle.comparison_matrix,
        )
        stored_bundle = await self.add_recommendation_bundle(
            run_id,
            recommendation_bundle,
            comparison_matrix_id=matrix_id,
        )
        version = await self._next_result_version(run_id)
        result_version = ResultVersion(
            result_version_id=new_id(),
            run_id=run_id,
            version=version,
            recommendation_bundle_id=stored_bundle.bundle_id,
            comparison_matrix_id=matrix_id,
        )
        self._session.add(
            ResultVersionRecord(
                result_version_id=str(result_version.result_version_id),
                run_id=str(run_id),
                version=version,
                recommendation_bundle_id=str(stored_bundle.bundle_id),
                comparison_matrix_id=str(matrix_id),
                created_at=utc_now().isoformat(),
            )
        )
        await self._session.flush()
        return SavedResultBundle(
            result_version=result_version,
            trust_assessments=trust_assessments,
            category_analyses=category_analyses,
            agent_records=agent_records,
            comparison_matrix=recommendation_bundle.comparison_matrix,
            recommendation_bundle=stored_bundle,
        )

    async def load_latest_result_bundle(
        self,
        run_id: RunId,
    ) -> SavedResultBundle | None:
        version_statement: Select[tuple[ResultVersionRecord]] = (
            select(ResultVersionRecord)
            .where(ResultVersionRecord.run_id == str(run_id))
            .order_by(ResultVersionRecord.version.desc())
            .limit(1)
        )
        version_record = await self._session.scalar(version_statement)
        if version_record is None:
            return None

        return await self._load_result_bundle_from_version(version_record)

    async def load_latest_result_bundle_for_session(
        self,
        session_id: SessionId,
    ) -> SavedResultBundle | None:
        version_statement: Select[tuple[ResultVersionRecord]] = (
            select(ResultVersionRecord)
            .join(
                ShoppingRunRecordModel,
                ResultVersionRecord.run_id == ShoppingRunRecordModel.run_id,
            )
            .where(ShoppingRunRecordModel.session_id == str(session_id))
            .order_by(
                ResultVersionRecord.created_at.desc(),
                ResultVersionRecord.version.desc(),
            )
            .limit(1)
        )
        version_record = await self._session.scalar(version_statement)
        if version_record is None:
            return None

        return await self._load_result_bundle_from_version(version_record)

    async def _next_result_version(self, run_id: RunId) -> int:
        statement = select(func.max(ResultVersionRecord.version)).where(
            ResultVersionRecord.run_id == str(run_id)
        )
        current_version = await self._session.scalar(statement)
        if current_version is None:
            return 1
        return current_version + 1

    async def _load_result_bundle_from_version(
        self,
        version_record: ResultVersionRecord,
    ) -> SavedResultBundle | None:
        run_id = UUID(version_record.run_id)
        comparison_matrix = await self.get_comparison_matrix(
            UUID(version_record.comparison_matrix_id)
        )
        recommendation_bundle = await self.get_recommendation_bundle(
            UUID(version_record.recommendation_bundle_id)
        )
        if comparison_matrix is None or recommendation_bundle is None:
            return None

        return SavedResultBundle(
            result_version=_to_result_version(version_record),
            trust_assessments=await self.list_listing_trust_assessments(run_id),
            category_analyses=await self.list_category_analyses(run_id),
            agent_records=await self.list_agent_records(run_id),
            comparison_matrix=comparison_matrix,
            recommendation_bundle=recommendation_bundle,
        )


def _to_result_version(record: ResultVersionRecord) -> ResultVersion:
    return ResultVersion(
        result_version_id=UUID(record.result_version_id),
        run_id=UUID(record.run_id),
        version=record.version,
        recommendation_bundle_id=UUID(record.recommendation_bundle_id),
        comparison_matrix_id=UUID(record.comparison_matrix_id),
    )
