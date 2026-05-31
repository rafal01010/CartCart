from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.db.repositories.results import ResultRepository, SavedResultBundle
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import get_db_session
from app.schemas.analysis import (
    CategoryAnalysis,
    ComparisonMatrix,
    ListingTrustAssessment,
    RecommendationBundle,
)
from app.schemas.base import CartCartBaseModel
from app.schemas.ids import CandidateId, RunId, SessionId
from app.schemas.runs import AgentRunRecord
from app.schemas.search_sources import SourceEvidence, SourceSnapshot


router = APIRouter(prefix="/api/sessions/{session_id}/results", tags=["results"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


class ResultVersionResponse(CartCartBaseModel):
    result_version_id: CandidateId
    run_id: RunId
    version: int
    recommendation_bundle_id: CandidateId
    comparison_matrix_id: CandidateId


class SessionResultsResponse(CartCartBaseModel):
    result_version: ResultVersionResponse
    trust_assessments: tuple[ListingTrustAssessment, ...]
    category_analyses: tuple[CategoryAnalysis, ...]
    agent_records: tuple[AgentRunRecord, ...]
    comparison_matrix: ComparisonMatrix
    recommendation_bundle: RecommendationBundle
    source_snapshots: tuple[SourceSnapshot, ...]
    source_evidence: tuple[SourceEvidence, ...]


@router.get("", response_model=SessionResultsResponse)
async def get_session_results(
    session_id: SessionId,
    db_session: DbSession,
) -> SessionResultsResponse:
    session = await SessionRepository(db_session).get(session_id)
    if session is None:
        raise _session_not_found(session_id)

    saved_result = (
        await ResultRepository(db_session).load_latest_result_bundle_for_session(
            session_id
        )
    )
    if saved_result is None:
        raise _result_not_ready(session_id)

    source_repository = SearchSourceRepository(db_session)
    source_snapshots = await source_repository.list_source_snapshots(
        saved_result.result_version.run_id,
    )
    source_evidence = await source_repository.list_source_evidence(
        saved_result.result_version.run_id,
    )

    return _to_response(saved_result, source_snapshots, source_evidence)


def _to_response(
    saved_result: SavedResultBundle,
    source_snapshots: tuple[SourceSnapshot, ...],
    source_evidence: tuple[SourceEvidence, ...],
) -> SessionResultsResponse:
    return SessionResultsResponse(
        result_version=ResultVersionResponse(
            result_version_id=saved_result.result_version.result_version_id,
            run_id=saved_result.result_version.run_id,
            version=saved_result.result_version.version,
            recommendation_bundle_id=saved_result.result_version.recommendation_bundle_id,
            comparison_matrix_id=saved_result.result_version.comparison_matrix_id,
        ),
        trust_assessments=saved_result.trust_assessments,
        category_analyses=saved_result.category_analyses,
        agent_records=saved_result.agent_records,
        comparison_matrix=saved_result.comparison_matrix,
        recommendation_bundle=saved_result.recommendation_bundle,
        source_snapshots=source_snapshots,
        source_evidence=source_evidence,
    )


def _session_not_found(session_id: SessionId) -> ApplicationError:
    return ApplicationError(
        "session_not_found",
        "Session not found.",
        status_code=status.HTTP_404_NOT_FOUND,
        details={"session_id": str(session_id)},
    )


def _result_not_ready(session_id: SessionId) -> ApplicationError:
    return ApplicationError(
        "result_not_ready",
        "Result is not ready.",
        status_code=status.HTTP_404_NOT_FOUND,
        details={"session_id": str(session_id)},
    )
