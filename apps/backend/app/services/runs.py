from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.orchestration import (
    RepositoryShoppingRunPersistenceHooks,
    ShoppingRunOrchestrator,
)
from app.providers import ExtractionProvider, SearchProvider
from app.schemas.ids import RunId, SessionId
from app.schemas.regions import RegionCode
from app.schemas.runs import RunEvent, ShoppingRunRecord


class RunService:
    def __init__(
        self,
        session_repository: SessionRepository,
        run_repository: RunRepository,
        result_repository: ResultRepository | None = None,
        search_source_repository: SearchSourceRepository | None = None,
        product_repository: ProductRepository | None = None,
        search_provider: SearchProvider | None = None,
        extraction_provider: ExtractionProvider | None = None,
        default_region_code: RegionCode = "US",
    ) -> None:
        self._session_repository = session_repository
        self._run_repository = run_repository
        self._result_repository = result_repository
        self._search_source_repository = search_source_repository
        self._product_repository = product_repository
        self._search_provider = search_provider
        self._extraction_provider = extraction_provider
        self._default_region_code = default_region_code

    async def create_stub_run(
        self,
        session_id: SessionId,
    ) -> ShoppingRunRecord | None:
        session = await self._session_repository.get(session_id)
        if session is None:
            return None

        run = await self._run_repository.create(session_id)
        if (
            self._result_repository is None
            or self._search_source_repository is None
            or self._product_repository is None
        ):
            return run

        orchestrator = ShoppingRunOrchestrator(
            RepositoryShoppingRunPersistenceHooks(
                run_repository=self._run_repository,
                result_repository=self._result_repository,
                search_source_repository=self._search_source_repository,
                product_repository=self._product_repository,
            ),
            search_provider=self._search_provider,
            extraction_provider=self._extraction_provider,
            default_region_code=self._default_region_code,
        )
        await orchestrator.run(run.run_id, session.current_brief)
        return await self._run_repository.get(run.run_id)

    async def get_run_status(
        self,
        session_id: SessionId,
        run_id: RunId,
    ) -> ShoppingRunRecord | None:
        session = await self._session_repository.get(session_id)
        if session is None:
            return None

        run = await self._run_repository.get(run_id)
        if run is None or run.session_id != session_id:
            return None
        return run

    async def list_run_events(
        self,
        session_id: SessionId,
        run_id: RunId,
    ) -> tuple[RunEvent, ...] | None:
        run = await self.get_run_status(session_id, run_id)
        if run is None:
            return None

        return await self._run_repository.list_events(run_id)
