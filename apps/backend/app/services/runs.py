from app.core.errors import ApplicationError
from app.agents.research_tools import AgentResearchTools, HostedCitationStore
from app.agents.extraction_tools import SnapshotInterpretationTools
from app.agents.live_extraction import LiveExtractionAgent
from app.agents.live_source_intelligence_manager import SourceIntelligenceManagerAgent
from app.core.settings import AgentWorkflowMode, Settings
from app.agents import (
    AmazonProductIntelligenceService,
    LiveCategoryRouterAgent,
    LiveComparisonDecisionAgent,
    LiveDiscoveryAgent,
    LiveEarphonesHeadphonesSpecialistAgent,
    LiveGenericProductAnalystAgent,
    LiveGeneralShoppingAgent,
    IKEAStoreIntelligenceService,
    LiveIntakeAgent,
    LiveLaptopSpecialistAgent,
    LiveMonitorSpecialistAgent,
    RedditCommunityIntelligenceService,
    LiveSellerListingTrustAgent,
    LiveShoppingScopeGuardrail,
    LiveSmartphoneSpecialistAgent,
    LiveSmartwatchSpecialistAgent,
    LiveTVSpecialistAgent,
    LiveTechnologyDomainAnalystAgent,
    LiveVerifierCriticAgent,
    YouTubeReviewIntelligenceService,
    LiveQueryPlannerAgent,
    OpenAIAgentConfigurationError,
    ShoppingScopeGuardrailInput,
    build_openai_agent_run_configuration,
    require_live_openai_agent_configuration,
)
from app.db.repositories.products import ProductRepository
from app.db.repositories.refinements import RefinementRepository
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
from app.orchestration.shopping_runs import ReusedRefinementArtifacts
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
from app.schemas.runs import (
    RecomputePlan,
    RecomputeStage,
    RunEvent,
    RunStatus,
    ShoppingRunRecord,
)
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

        orchestrator = self._orchestrator()
        try:
            await orchestrator.run(
                run.run_id,
                session.current_brief,
                original_input=session.original_input,
            )
        except Exception:
            failed_run = await self._run_repository.get(run.run_id)
            if failed_run is not None and failed_run.status == RunStatus.FAILED:
                return failed_run
            raise
        return await self._run_repository.get(run.run_id)

    async def execute_refinement(
        self, session_id: SessionId, plan: RecomputePlan, instruction: str
    ) -> ShoppingRunRecord:
        run = await self.get_run_status(session_id, plan.run_id)
        if run is None or run.status != RunStatus.PENDING:
            raise ApplicationError(
                "refinement_not_pending",
                "This refinement cannot be started again.",
                status_code=409,
            )
        if (
            self._result_repository is None
            or self._search_source_repository is None
            or self._product_repository is None
        ):
            raise ValueError(
                "Refinement execution requires result and research repositories."
            )
        prior = await self._result_repository.load_result_bundle_by_version(
            plan.prior_result_version_id
        )
        latest = await self._result_repository.load_latest_result_bundle_for_session(
            session_id
        )
        if (
            prior is None
            or latest is None
            or prior.result_version.run_id != plan.prior_run_id
            or latest.result_version.result_version_id != plan.prior_result_version_id
        ):
            raise ApplicationError(
                "refinement_base_changed",
                "A newer shopping result is available. Start a new refinement from it.",
                status_code=409,
            )
        session = await self._session_repository.get(session_id)
        assert session is not None
        if session.current_brief != plan.base_brief:
            raise ApplicationError(
                "refinement_brief_changed",
                "Shopping details changed. Start a new refinement from the current result.",
                status_code=409,
            )
        refined_request = (
            f"{session.original_input.query}\n{instruction}\n"
            f"{plan.target_brief.category or ''}"
        )
        blocked_guardrail = blocked_guardrail_or_none(refined_request)
        if blocked_guardrail is not None:
            raise ApplicationError(
                "shopping_guardrail_blocked",
                blocked_guardrail.message
                or "This request is outside ordinary shopping help.",
                status_code=409,
                details={"reason": blocked_guardrail.reason},
            )
        await self._check_live_agent_start(refined_request)
        reused = None
        if RecomputeStage.SEARCH not in plan.stages:
            research_run_id = await RefinementRepository(
                self._search_source_repository.session
            ).research_run_for(plan.prior_run_id)
            products = await self._product_repository.list_canonical_products_for_run(
                research_run_id
            )
            listings = await self._product_repository.list_product_listings_for_run(
                research_run_id
            )
            evidence = await self._search_source_repository.list_source_evidence(
                research_run_id
            )
            snapshots = await self._search_source_repository.list_source_snapshots(
                research_run_id
            )
            product_ids = {item.product_id for item in products}
            listing_ids = {item.listing_id for item in listings}
            candidate_ids = {
                item.candidate_id
                for item in await self._product_repository.list_shortlist_memberships(
                    research_run_id
                )
            }
            source_ids = {item.source_id for item in snapshots}
            if (
                not products
                or not evidence
                or any(item.source_id not in source_ids for item in evidence)
                or not any(
                    item.target.product_id in product_ids
                    or item.target.listing_id in listing_ids
                    or item.target.candidate_id in candidate_ids
                    for item in evidence
                )
            ):
                raise ApplicationError(
                    "refinement_evidence_changed",
                    "Saved research is no longer usable. Start a new refinement to research again.",
                    status_code=409,
                )
            reused = ReusedRefinementArtifacts(
                products=products,
                listings=listings,
                evidence=evidence,
                trust_assessments=prior.trust_assessments,
                category_analyses=prior.category_analyses,
                recommendation=prior.recommendation_bundle,
                user_added_products=await self._product_repository.list_user_added_products_for_run(
                    session_id, research_run_id
                ),
            )
        original_input = session.original_input
        if RecomputeStage.RE_INTAKE in plan.stages:
            original_input = original_input.model_copy(
                update={
                    "query": f"{original_input.query}\nRefinement: {instruction}"[:4000]
                }
            )
        try:
            await self._orchestrator().run(
                plan.run_id,
                plan.target_brief,
                original_input=original_input,
                refinement_plan=plan,
                reused_artifacts=reused,
            )
        except Exception:
            failed_run = await self._run_repository.get(plan.run_id)
            if failed_run is not None and failed_run.status == RunStatus.FAILED:
                return failed_run
            raise
        completed = await self._run_repository.get(plan.run_id)
        assert completed is not None
        if completed.status == RunStatus.SUCCEEDED:
            await self._session_repository.update_current_brief(
                session_id, plan.target_brief
            )
        return completed

    def _orchestrator(self) -> ShoppingRunOrchestrator:
        return ShoppingRunOrchestrator(
            RepositoryShoppingRunPersistenceHooks(
                run_repository=self._run_repository,
                result_repository=self._result_repository,
                search_source_repository=self._search_source_repository,
                product_repository=self._product_repository,
                source_intelligence_repository=self._source_intelligence_repository,
                video_review_repository=self._video_review_repository,
            ),
            agent_workflow_mode=self._agent_workflow_mode,
            agent_model_resolver=(
                self._resolved_agent_model if self._settings is not None else None
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

    def _resolved_agent_model(self, agent_name: str) -> str:
        if self._settings is None:
            raise RuntimeError("Agent model resolution requires backend settings.")
        return build_openai_agent_run_configuration(
            self._settings, agent_name=agent_name
        ).model

    async def _check_live_agent_start(self, user_input: str) -> None:
        if self._settings is not None and any(
            warning.code == "fixture_agents_with_live_providers"
            for warning in self._settings.agent_readiness_warnings()
        ):
            raise ApplicationError(
                "research_mode_mismatch",
                "CartCart cannot research this request because sample-data mode "
                "is combined with live research settings. Enable live research "
                "or use sample data, then restart CartCart.",
                status_code=409,
                details={
                    "agent_workflow_mode": "fixture",
                    "required_settings": {
                        "CARTCART_AGENT_WORKFLOW_MODE": "live",
                        "CARTCART_LIVE_AGENTS_ENABLED": "true",
                    },
                },
            )
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
        if (
            self._settings is None
            or self._agent_workflow_mode != AgentWorkflowMode.LIVE
        ):
            return {}
        snapshot_session = (
            self._search_source_repository.session
            if self._search_source_repository is not None
            else None
        )

        source_manager = SourceIntelligenceManagerAgent(
            settings=self._settings,
            video_provider=self._video_search_provider,
            transcript_provider=self._transcript_provider,
            community_provider=self._community_discussion_provider,
            amazon_provider=self._amazon_product_intelligence_provider,
            ikea_provider=self._ikea_store_intelligence_provider,
            citation_store_factory=(
                lambda run_id: HostedCitationStore(
                    run_id=run_id,
                    shared_session=self._search_source_repository.session,
                )
            )
            if self._search_source_repository is not None
            else None,
        )
        return {
            "intake_agent": LiveIntakeAgent(settings=self._settings),
            "general_shopping_agent": LiveGeneralShoppingAgent(
                settings=self._settings,
                source_intelligence_manager=source_manager,
                shared_session=self._search_source_repository.session
                if self._search_source_repository is not None
                else None,
                regional_research_tools_factory=(
                    lambda run_id, region_code: AgentResearchTools(
                        agent_name="GeneralShoppingAgent",
                        run_id=run_id,
                        session_factory=None,
                        shared_session=self._search_source_repository.session,
                        search_provider=self._search_provider,
                        extraction_provider=self._extraction_provider,
                        required_region_code=region_code,
                    )
                )
                if self._search_source_repository is not None
                and self._search_provider is not None
                and self._extraction_provider is not None
                else None,
                technology_research_tools_factory=(
                    lambda run_id, region_code: AgentResearchTools(
                        agent_name="TechnologyDomainAnalystAgent",
                        run_id=run_id,
                        session_factory=None,
                        shared_session=self._search_source_repository.session,
                        search_provider=self._search_provider,
                        extraction_provider=self._extraction_provider,
                        required_region_code=region_code,
                    )
                )
                if self._search_source_repository is not None
                and self._search_provider is not None
                and self._extraction_provider is not None
                else None,
            ),
            "query_planner": LiveQueryPlannerAgent(settings=self._settings),
            "discovery_agent": LiveDiscoveryAgent(
                settings=self._settings,
                research_tools_factory=(
                    lambda run_id: AgentResearchTools(
                        agent_name="DiscoveryAgent",
                        run_id=run_id,
                        session_factory=None,
                        shared_session=self._search_source_repository.session,
                        search_provider=self._search_provider,
                        extraction_provider=self._extraction_provider,
                    )
                )
                if self._search_source_repository is not None
                and self._search_provider is not None
                and self._extraction_provider is not None
                else None,
            ),
            "extraction_agent": LiveExtractionAgent(
                settings=self._settings,
                snapshot_tools_factory=lambda request: SnapshotInterpretationTools(
                    run_id=request.run_id,
                    allowed_snapshot_ids=request.snapshot_ids,
                    shared_session=self._search_source_repository.session,
                ),
            )
            if self._search_source_repository is not None
            else None,
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
                settings=self._settings,
                citation_store_factory=(
                    lambda run_id: HostedCitationStore(
                        run_id=run_id,
                        shared_session=self._search_source_repository.session,
                    )
                )
                if self._search_source_repository is not None
                else None,
            ),
            "comparison_decision_agent": LiveComparisonDecisionAgent(
                settings=self._settings
            ),
            "verifier_critic_agent": LiveVerifierCriticAgent(
                settings=self._settings,
                snapshot_tools_factory=(
                    lambda request: SnapshotInterpretationTools(
                        run_id=request.run_id,
                        allowed_snapshot_ids=tuple(
                            {item.source_id for item in request.evidence}
                        ),
                        shared_session=snapshot_session,
                        agent_name="VerifierCriticAgent",
                    )
                )
                if self._search_source_repository is not None
                else None,
            ),
            "source_intelligence_manager": source_manager,
            "youtube_review_intelligence_service": YouTubeReviewIntelligenceService(
                settings=self._settings,
                video_search_provider=self._video_search_provider,
                transcript_provider=self._transcript_provider,
            ),
            "reddit_community_intelligence_service": (
                RedditCommunityIntelligenceService(
                    settings=self._settings,
                    community_provider=self._community_discussion_provider,
                )
            ),
            "amazon_product_intelligence_service": AmazonProductIntelligenceService(
                settings=self._settings,
                amazon_provider=self._amazon_product_intelligence_provider,
            ),
            "ikea_store_intelligence_service": IKEAStoreIntelligenceService(
                settings=self._settings,
                ikea_provider=self._ikea_store_intelligence_provider,
            ),
        }
