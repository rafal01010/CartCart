from app.core.errors import ApplicationError
from app.core.settings import AgentWorkflowMode, Settings
from app.agents import (
    LiveAmazonProductIntelligenceAgent,
    LiveCategoryRouterAgent,
    LiveComparisonDecisionAgent,
    LiveDiscoveryAgent,
    LiveEarphonesHeadphonesSpecialistAgent,
    LiveGenericProductAnalystAgent,
    LiveIKEAStoreIntelligenceAgent,
    LiveIntakeAgent,
    LiveLaptopSpecialistAgent,
    LiveMonitorSpecialistAgent,
    LiveRedditCommunityIntelligenceAgent,
    LiveSellerListingTrustAgent,
    LiveShoppingScopeGuardrail,
    LiveSmartphoneSpecialistAgent,
    LiveSmartwatchSpecialistAgent,
    LiveTVSpecialistAgent,
    LiveTechnologyDomainAnalystAgent,
    LiveVerifierCriticAgent,
    LiveYouTubeReviewIntelligenceAgent,
    LiveQueryPlannerAgent,
    OpenAIAgentConfigurationError,
    ShoppingScopeGuardrailInput,
    require_live_openai_agent_configuration,
)
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
from app.schemas.guided_intake import ShoppingGuardrailDecision
from app.schemas.regions import RegionCode
from app.schemas.runs import RunEvent, ShoppingRunRecord
from app.services.shopping_guardrails import blocked_guardrail_or_none


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
        settings: Settings | None = None,
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
        self._settings = settings

    async def create_stub_run(
        self,
        session_id: SessionId,
    ) -> ShoppingRunRecord | None:
        session = await self._session_repository.get(session_id)
        if session is None:
            return None

        blocked_guardrail = blocked_guardrail_or_none(
            session.current_brief.original_query,
        )
        if blocked_guardrail is not None:
            raise ApplicationError(
                "shopping_guardrail_blocked",
                blocked_guardrail.message
                or "This request is outside ordinary shopping help.",
                status_code=409,
                details={"reason": blocked_guardrail.reason},
            )

        await self._check_live_agent_start(session.original_input.query)

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
            agent_workflow_mode=self._agent_workflow_mode,
            agent_model_name=(
                self._settings.openai_model
                if self._agent_workflow_mode == AgentWorkflowMode.LIVE
                and self._settings is not None
                else None
            ),
            **self._live_agent_kwargs(),
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
        await orchestrator.run(
            run.run_id,
            session.current_brief,
            original_input=session.original_input,
        )
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

    @property
    def _agent_workflow_mode(self) -> AgentWorkflowMode:
        if self._settings is None:
            return AgentWorkflowMode.FIXTURE
        return self._settings.agent_workflow_mode

    async def _check_live_agent_start(self, user_input: str) -> None:
        if self._agent_workflow_mode != AgentWorkflowMode.LIVE:
            return
        if self._settings is None:
            return
        try:
            require_live_openai_agent_configuration(
                self._settings,
                agent_name="ShoppingRunOrchestrator",
            )
        except OpenAIAgentConfigurationError as exc:
            raise ApplicationError(
                "live_agents_not_configured",
                str(exc),
                status_code=409,
                details={"agent_workflow_mode": AgentWorkflowMode.LIVE.value},
            ) from exc

        guardrail = await LiveShoppingScopeGuardrail(settings=self._settings).run(
            ShoppingScopeGuardrailInput(user_input=user_input)
        )
        if guardrail.decision == ShoppingGuardrailDecision.BLOCKED:
            raise ApplicationError(
                "shopping_guardrail_blocked",
                guardrail.message or "This request is outside ordinary shopping help.",
                status_code=409,
                details={"reason": guardrail.reason},
            )

    def _live_agent_kwargs(self) -> dict[str, object]:
        if self._settings is None or self._agent_workflow_mode != AgentWorkflowMode.LIVE:
            return {}

        return {
            "intake_agent": LiveIntakeAgent(settings=self._settings),
            "query_planner": LiveQueryPlannerAgent(settings=self._settings),
            "discovery_agent": LiveDiscoveryAgent(settings=self._settings),
            "category_router_agent": LiveCategoryRouterAgent(settings=self._settings),
            "generic_product_analyst_agent": LiveGenericProductAnalystAgent(
                settings=self._settings
            ),
            "technology_domain_analyst_agent": LiveTechnologyDomainAnalystAgent(
                settings=self._settings
            ),
            "monitor_specialist_agent": LiveMonitorSpecialistAgent(
                settings=self._settings
            ),
            "smartphone_specialist_agent": LiveSmartphoneSpecialistAgent(
                settings=self._settings
            ),
            "laptop_specialist_agent": LiveLaptopSpecialistAgent(
                settings=self._settings
            ),
            "earphones_headphones_specialist_agent": (
                LiveEarphonesHeadphonesSpecialistAgent(settings=self._settings)
            ),
            "tv_specialist_agent": LiveTVSpecialistAgent(settings=self._settings),
            "smartwatch_specialist_agent": LiveSmartwatchSpecialistAgent(
                settings=self._settings
            ),
            "seller_listing_trust_agent": LiveSellerListingTrustAgent(
                settings=self._settings
            ),
            "comparison_decision_agent": LiveComparisonDecisionAgent(
                settings=self._settings
            ),
            "verifier_critic_agent": LiveVerifierCriticAgent(settings=self._settings),
            "youtube_review_intelligence_agent": LiveYouTubeReviewIntelligenceAgent(
                settings=self._settings,
                video_search_provider=self._video_search_provider,
                transcript_provider=self._transcript_provider,
            ),
            "reddit_community_intelligence_agent": (
                LiveRedditCommunityIntelligenceAgent(
                    settings=self._settings,
                    community_provider=self._community_discussion_provider,
                )
            ),
            "amazon_product_intelligence_agent": LiveAmazonProductIntelligenceAgent(
                settings=self._settings,
                amazon_provider=self._amazon_product_intelligence_provider,
            ),
            "ikea_store_intelligence_agent": LiveIKEAStoreIntelligenceAgent(
                settings=self._settings,
                ikea_provider=self._ikea_store_intelligence_provider,
            ),
        }
