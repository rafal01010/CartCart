from app.db.repositories.refinements import RefinementRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.sessions import SessionRepository
from app.schemas.ids import SessionId
from app.schemas.runs import RefinementRequest, ShoppingRunRecord


class RefinementService:
    def __init__(
        self,
        session_repository: SessionRepository,
        run_repository: RunRepository,
        refinement_repository: RefinementRepository,
    ) -> None:
        self._session_repository = session_repository
        self._run_repository = run_repository
        self._refinement_repository = refinement_repository

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
        return stored_refinement, run
