from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.repositories.source_intelligence import SourceIntelligenceRepository
from app.db.repositories.video_sources import VideoReviewRepository
from app.orchestration import (
    RepositoryShoppingRunPersistenceHooks,
    ShoppingRunOrchestrator,
)
from app.providers import (
    AmazonProductIntelligenceProvider,
    CommunityDiscussionProvider,
    ExtractionProvider,
    IKEAStoreIntelligenceProvider,
    SearchProvider,
    TranscriptProvider,
    VideoSearchProvider,
)
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
        source_intelligence_repository: SourceIntelligenceRepository | None = None,
        video_review_repository: VideoReviewRepository | None = None,
        search_provider: SearchProvider | None = None,
        extraction_provider: ExtractionProvider | None = None,
        video_search_provider: VideoSearchProvider | None = None,
        transcript_provider: TranscriptProvider | None = None,
        community_discussion_provider: CommunityDiscussionProvider | None = None,
        amazon_product_intelligence_provider: (
            AmazonProductIntelligenceProvider | None
        ) = None,
        ikea_store_intelligence_provider: IKEAStoreIntelligenceProvider | None = None,
        default_region_code: RegionCode = "US",
    ) -> None:
        self._session_repository = session_repository
        self._run_repository = run_repository
        self._result_repository = result_repository
        self._search_source_repository = search_source_repository
        self._product_repository = product_repository
        self._source_intelligence_repository = source_intelligence_repository
        self._video_review_repository = video_review_repository
        self._search_provider = search_provider
        self._extraction_provider = extraction_provider
        self._video_search_provider = video_search_provider
        self._transcript_provider = transcript_provider
        self._community_discussion_provider = community_discussion_provider
        self._amazon_product_intelligence_provider = (
            amazon_product_intelligence_provider
        )
        self._ikea_store_intelligence_provider = ikea_store_intelligence_provider
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
                source_intelligence_repository=self._source_intelligence_repository,
                video_review_repository=self._video_review_repository,
            ),
            search_provider=self._search_provider,
            extraction_provider=self._extraction_provider,
            video_search_provider=self._video_search_provider,
            transcript_provider=self._transcript_provider,
            community_discussion_provider=self._community_discussion_provider,
            amazon_product_intelligence_provider=(
                self._amazon_product_intelligence_provider
            ),
            ikea_store_intelligence_provider=self._ikea_store_intelligence_provider,
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
