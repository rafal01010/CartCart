from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.db.repositories.results import ResultRepository, SavedResultBundle
from app.db.repositories.refinements import RefinementRepository
from app.db.repositories.products import CandidateShortlistMembership, ProductRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import get_db_session
from app.schemas.analysis import (
    CategoryAnalysis,
    ComparisonMatrix,
    ListingTrustAssessment,
    RecommendationBundle,
    RecommendationMode,
)
from app.schemas.base import CartCartBaseModel
from app.schemas.ids import CandidateId, ListingId, ProductId, RunId, SessionId
from app.schemas.runs import AgentRunRecord, RunStatus
from app.schemas.intake import ShoppingBrief
from app.schemas.products import CanonicalProduct, ProductListing, UserAddedProduct
from app.schemas.search_sources import SourceEvidence, SourceSnapshot


router = APIRouter(prefix="/api/sessions/{session_id}/results", tags=["results"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


class ResultVersionResponse(CartCartBaseModel):
    result_version_id: CandidateId
    run_id: RunId
    version: int
    recommendation_bundle_id: CandidateId
    comparison_matrix_id: CandidateId
    refinement_id: CandidateId | None = None
    prior_result_version_id: CandidateId | None = None
    requested_result_mode: RecommendationMode | None = None


class ShortlistItemResponse(CartCartBaseModel):
    candidate_id: CandidateId
    product_id: ProductId
    listing_id: ListingId | None
    position: int | None


class ConsideredProductOutcomeResponse(CartCartBaseModel):
    candidate: UserAddedProduct
    status: Literal["confirmed", "possible", "unresolved", "manual", "excluded"]
    exclusion_reason: str | None = None


class SessionResultsResponse(CartCartBaseModel):
    result_version: ResultVersionResponse
    trust_assessments: tuple[ListingTrustAssessment, ...]
    category_analyses: tuple[CategoryAnalysis, ...]
    agent_records: tuple[AgentRunRecord, ...]
    comparison_matrix: ComparisonMatrix
    recommendation_bundle: RecommendationBundle
    products: tuple[CanonicalProduct, ...]
    listings: tuple[ProductListing, ...]
    shortlist: tuple[ShortlistItemResponse, ...]
    considered_products: tuple[ConsideredProductOutcomeResponse, ...]
    source_snapshots: tuple[SourceSnapshot, ...]
    source_evidence: tuple[SourceEvidence, ...]


class DecisionHistoryEntry(CartCartBaseModel):
    result_version_id: CandidateId
    version: int
    brief: ShoppingBrief
    change: str | None = None


class DecisionHistoryResponse(CartCartBaseModel):
    original_query: str
    versions: tuple[DecisionHistoryEntry, ...]


@router.get("", response_model=SessionResultsResponse)
async def get_session_results(
    session_id: SessionId,
    db_session: DbSession,
) -> SessionResultsResponse:
    session = await SessionRepository(db_session).get(session_id)
    if session is None:
        raise _session_not_found(session_id)

    saved_result = await ResultRepository(
        db_session
    ).load_latest_result_bundle_for_session(session_id)
    if saved_result is None:
        raise _result_not_ready(session_id)

    return await _load_response(session_id, saved_result, db_session)


@router.get("/history", response_model=DecisionHistoryResponse)
async def get_decision_history(
    session_id: SessionId, db_session: DbSession
) -> DecisionHistoryResponse:
    session = await SessionRepository(db_session).get(session_id)
    if session is None:
        raise _session_not_found(session_id)
    versions = await ResultRepository(db_session).list_successful_versions(session_id)
    refinements = RefinementRepository(db_session)
    requests = await refinements.list_for_session(session_id)
    plans = [
        plan
        for item in requests
        if (plan := await refinements.get_plan(item.refinement_id)) is not None
    ]
    # The first plan retains the completed intake context before any refinement.
    # A plan's target becomes history only after its run has succeeded.
    brief = plans[0].base_brief if plans else session.current_brief
    instructions = {item.run_id: item.instruction for item in requests}
    entries: list[DecisionHistoryEntry] = []
    for version in versions:
        run_id = UUID(version.run_id)
        plan = next((item for item in plans if item.run_id == run_id), None)
        if plan is not None:
            brief = plan.target_brief
        entries.append(
            DecisionHistoryEntry(
                result_version_id=UUID(version.result_version_id),
                version=version.version,
                brief=brief,
                change=instructions.get(run_id)
                or ("Products updated." if entries else None),
            )
        )
    return DecisionHistoryResponse(
        original_query=session.original_input.query, versions=tuple(entries)
    )


@router.get("/{result_version_id}", response_model=SessionResultsResponse)
async def get_result_version(
    session_id: SessionId,
    result_version_id: CandidateId,
    db_session: DbSession,
) -> SessionResultsResponse:
    saved_result = await ResultRepository(db_session).load_result_bundle_by_version(
        result_version_id
    )
    if saved_result is None:
        raise _result_not_ready(session_id)
    from app.db.repositories.runs import RunRepository

    run = await RunRepository(db_session).get(saved_result.result_version.run_id)
    if run is None or run.session_id != session_id or run.status != RunStatus.SUCCEEDED:
        raise _result_not_ready(session_id)
    return await _load_response(session_id, saved_result, db_session)


async def _load_response(
    session_id: SessionId,
    saved_result: SavedResultBundle,
    db_session: AsyncSession,
) -> SessionResultsResponse:
    plan = await RefinementRepository(db_session).get_plan_for_run(
        saved_result.result_version.run_id
    )
    artifact_run_id = await RefinementRepository(db_session).research_run_for(
        saved_result.result_version.run_id
    )
    source_repository = SearchSourceRepository(db_session)
    source_snapshots = await source_repository.list_source_snapshots(
        artifact_run_id,
    )
    source_evidence = await source_repository.list_source_evidence(
        artifact_run_id,
    )
    product_repository = ProductRepository(db_session)
    products = await product_repository.list_canonical_products_for_run(
        artifact_run_id,
    )
    listings = await product_repository.list_product_listings_for_run(
        artifact_run_id,
    )
    shortlist = await product_repository.list_shortlist_memberships(
        artifact_run_id,
    )
    considered_products = await product_repository.list_user_added_products_for_run(
        session_id,
        artifact_run_id,
    )

    return _to_response(
        saved_result,
        products,
        listings,
        shortlist,
        considered_products,
        source_snapshots,
        source_evidence,
        refinement_id=plan.refinement_id if plan else None,
        prior_result_version_id=plan.prior_result_version_id if plan else None,
        requested_result_mode=plan.requested_result_mode if plan else None,
    )


def _to_response(
    saved_result: SavedResultBundle,
    products: tuple[CanonicalProduct, ...],
    listings: tuple[ProductListing, ...],
    shortlist: tuple[CandidateShortlistMembership, ...],
    considered_products: tuple[UserAddedProduct, ...],
    source_snapshots: tuple[SourceSnapshot, ...],
    source_evidence: tuple[SourceEvidence, ...],
    *,
    refinement_id: CandidateId | None = None,
    prior_result_version_id: CandidateId | None = None,
    requested_result_mode: RecommendationMode | None = None,
) -> SessionResultsResponse:
    return SessionResultsResponse(
        result_version=ResultVersionResponse(
            result_version_id=saved_result.result_version.result_version_id,
            run_id=saved_result.result_version.run_id,
            version=saved_result.result_version.version,
            recommendation_bundle_id=saved_result.result_version.recommendation_bundle_id,
            comparison_matrix_id=saved_result.result_version.comparison_matrix_id,
            refinement_id=refinement_id,
            prior_result_version_id=prior_result_version_id,
            requested_result_mode=requested_result_mode,
        ),
        trust_assessments=saved_result.trust_assessments,
        category_analyses=saved_result.category_analyses,
        agent_records=saved_result.agent_records,
        comparison_matrix=saved_result.comparison_matrix,
        recommendation_bundle=saved_result.recommendation_bundle,
        products=products,
        listings=listings,
        shortlist=tuple(
            ShortlistItemResponse(
                candidate_id=item.candidate_id,
                product_id=item.product_id,
                listing_id=item.listing_id,
                position=item.position,
            )
            for item in shortlist
        ),
        considered_products=tuple(
            _considered_outcome(
                _candidate_in_run(item, products, listings),
                saved_result.recommendation_bundle,
            )
            for item in considered_products
        ),
        source_snapshots=source_snapshots,
        source_evidence=source_evidence,
    )


def _candidate_in_run(
    candidate: UserAddedProduct,
    products: tuple[CanonicalProduct, ...],
    listings: tuple[ProductListing, ...],
) -> UserAddedProduct:
    product_ids = {product.product_id for product in products}
    listing_ids = {listing.listing_id for listing in listings}
    product = (
        candidate.product
        if candidate.product and candidate.product.product_id in product_ids
        else None
    )
    listing = (
        candidate.listing
        if candidate.listing and candidate.listing.listing_id in listing_ids
        else None
    )
    return candidate.model_copy(
        update={
            "product": product,
            "listing": listing if product is not None else None,
            "possible_product_ids": tuple(
                product_id
                for product_id in candidate.possible_product_ids
                if product_id in product_ids
            ),
        }
    )


def _considered_outcome(
    candidate: UserAddedProduct,
    bundle: RecommendationBundle,
) -> ConsideredProductOutcomeResponse:
    product_id = candidate.product.product_id if candidate.product else None
    listing_id = candidate.listing.listing_id if candidate.listing else None
    exclusion = next(
        (
            item.reason
            for item in bundle.rejected_items
            if (listing_id is not None and item.listing_id == listing_id)
            or (product_id is not None and item.product_id == product_id)
            if item.severity.value in {"medium", "high", "blocking"}
        ),
        None,
    )
    status: Literal["confirmed", "possible", "unresolved", "manual", "excluded"]
    if exclusion is not None and candidate.listing is not None:
        status = "excluded"
    elif candidate.listing is not None:
        status = "confirmed"
    elif candidate.manual_fallback_reason is not None:
        status = "manual"
    elif candidate.possible_product_ids:
        status = "possible"
    else:
        status = "unresolved"
    return ConsideredProductOutcomeResponse(
        candidate=candidate,
        status=status,
        exclusion_reason=exclusion,
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
