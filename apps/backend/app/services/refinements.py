from app.db.repositories.products import ProductRepository
from app.db.repositories.refinements import RefinementRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.orchestration import (
    RepositoryShoppingRunPersistenceHooks,
    ShoppingRunOrchestrator,
)
from app.schemas.ids import SessionId
from app.schemas.runs import RefinementRequest, ShoppingRunRecord


class RefinementService:
    def __init__(
        self,
        session_repository: SessionRepository,
        run_repository: RunRepository,
        refinement_repository: RefinementRepository,
        result_repository: ResultRepository | None = None,
        search_source_repository: SearchSourceRepository | None = None,
        product_repository: ProductRepository | None = None,
    ) -> None:
        self._session_repository = session_repository
        self._run_repository = run_repository
        self._refinement_repository = refinement_repository
        self._result_repository = result_repository
        self._search_source_repository = search_source_repository
        self._product_repository = product_repository

    async def create_stub_refinement_run(
        self,
        session_id: SessionId,
        request: RefinementRequest,
    ) -> tuple[RefinementRequest, ShoppingRunRecord] | None:
        session = await self._session_repository.get(session_id)
        if session is None:
            return None

        run = await self._run_repository.create(session_id)
        refinement = request.model_copy(
            update={
                "session_id": session_id,
                "run_id": run.run_id,
            }
        )
        stored_refinement = await self._refinement_repository.create(refinement)
        if (
            self._result_repository is None
            or self._search_source_repository is None
            or self._product_repository is None
        ):
            return stored_refinement, run

        orchestrator = ShoppingRunOrchestrator(
            RepositoryShoppingRunPersistenceHooks(
                run_repository=self._run_repository,
                result_repository=self._result_repository,
                search_source_repository=self._search_source_repository,
                product_repository=self._product_repository,
            )
        )
        await orchestrator.run(run.run_id)
        updated_run = await self._run_repository.get(run.run_id)
        return stored_refinement, updated_run or run
