from app.core.errors import ApplicationError
from app.db.repositories.products import ProductRepository
from app.db.repositories.refinements import RefinementRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.schemas.ids import SessionId
from app.schemas.runs import RecomputePlan, RefinementRequest, ShoppingRunRecord
from app.services.refinement_planning import build_recompute_plan


class RefinementService:
    def __init__(
        self,
        session_repository: SessionRepository,
        run_repository: RunRepository,
        refinement_repository: RefinementRepository,
        result_repository: ResultRepository,
        search_source_repository: SearchSourceRepository,
        product_repository: ProductRepository,
    ) -> None:
        self._session_repository = session_repository
        self._run_repository = run_repository
        self._refinement_repository = refinement_repository
        self._result_repository = result_repository
        self._search_source_repository = search_source_repository
        self._product_repository = product_repository

    async def create_refinement_plan(
        self,
        session_id: SessionId,
        request: RefinementRequest,
    ) -> tuple[RefinementRequest, ShoppingRunRecord, RecomputePlan] | None:
        session = await self._session_repository.get(session_id)
        if session is None:
            return None
        prior_result = (
            await self._result_repository.load_latest_result_bundle_for_session(
                session_id
            )
        )
        if prior_result is None:
            raise ApplicationError(
                "refinement_requires_result",
                "Finish an initial shopping result before refining it.",
                status_code=409,
            )

        prior_run_id = prior_result.result_version.run_id
        prior_run = await self._run_repository.get(prior_run_id)
        prior_plan = await self._refinement_repository.get_plan_for_run(prior_run_id)
        research_run_id = await self._refinement_repository.research_run_for(
            prior_run_id
        )
        products = await self._product_repository.list_canonical_products_for_run(
            research_run_id
        )
        has_saved_candidates = (
            prior_run is not None
            and (
                (
                    prior_plan is not None
                    and session.current_brief == prior_plan.target_brief
                )
                or (prior_plan is None and session.updated_at <= prior_run.created_at)
            )
            and bool(products)
        )

        run = await self._run_repository.create(session_id)
        refinement = request.model_copy(
            update={"session_id": session_id, "run_id": run.run_id}
        )
        stored_refinement = await self._refinement_repository.create(refinement)
        plan = build_recompute_plan(
            session_id=session_id,
            run_id=run.run_id,
            refinement=stored_refinement,
            prior_result=prior_result,
            base_brief=session.current_brief,
            has_saved_candidates=has_saved_candidates,
        )
        stored_plan = await self._refinement_repository.save_plan(plan)
        return stored_refinement, run, stored_plan
