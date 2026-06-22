from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from typing import Any

from fastapi.encoders import jsonable_encoder
from pydantic import AnyHttpUrl, Field, ValidationError

from app.agents.catalog import DEFAULT_AGENT_CATALOG, AgentCatalog, AgentCatalogEntry
from app.agents.contracts import (
    AmazonProductIntelligenceAgentInput,
    CategoryRouterAgentInput,
    ComparisonDecisionAgentInput,
    DeduplicationReviewAgentInput,
    DiscoveryAgentInput,
    ExtractionReviewAgentInput,
    IKEAStoreIntelligenceAgentInput,
    IntakeAgentInput,
    ProductAnalysisAgentInput,
    QueryPlannerAgentInput,
    RedditCommunityIntelligenceAgentInput,
    SellerListingTrustAgentInput,
    ShoppingGuideAgentInput,
    ShoppingScopeGuardrailInput,
    VerificationAgentInput,
    YouTubeReviewIntelligenceAgentInput,
)
from app.agents.fakes import (
    FakeCategoryRouterAgent,
    FakeComparisonDecisionAgent,
    FakeDeduplicationReviewAgent,
    FakeDiscoveryAgent,
    FakeEarphonesHeadphonesSpecialistAgent,
    FakeExtractionReviewAgent,
    FakeGenericProductAnalystAgent,
    FakeIntakeAgent,
    FakeLaptopSpecialistAgent,
    FakeMonitorSpecialistAgent,
    FakeQueryPlannerAgent,
    FakeSellerListingTrustAgent,
    FakeShoppingGuideAgent,
    FakeShoppingScopeGuardrail,
    FakeSmartphoneSpecialistAgent,
    FakeSmartwatchSpecialistAgent,
    FakeTVSpecialistAgent,
    FakeTechnologyDomainAnalystAgent,
    FakeVerifierCriticAgent,
)
from app.agents.live_guardrails import (
    LiveShoppingScopeGuardrail,
    MockShoppingGuardrailModelRunner,
)
from app.agents.live_category_router import (
    LiveCategoryRouterAgent,
    MockCategoryRouterModelRunner,
)
from app.agents.live_comparison_decision import (
    LiveComparisonDecisionAgent,
    MockComparisonDecisionModelRunner,
)
from app.agents.live_verifier_critic import (
    LiveVerifierCriticAgent,
    MockVerifierCriticModelRunner,
)
from app.agents.live_generic_product_analyst import (
    LiveGenericProductAnalystAgent,
    MockGenericProductAnalystModelRunner,
)
from app.agents.live_earphones_headphones_specialist import (
    LiveEarphonesHeadphonesSpecialistAgent,
    MockEarphonesHeadphonesSpecialistModelRunner,
)
from app.agents.live_laptop_specialist import (
    LiveLaptopSpecialistAgent,
    MockLaptopSpecialistModelRunner,
)
from app.agents.live_monitor_specialist import (
    LiveMonitorSpecialistAgent,
    MockMonitorSpecialistModelRunner,
)
from app.agents.live_smartphone_specialist import (
    LiveSmartphoneSpecialistAgent,
    MockSmartphoneSpecialistModelRunner,
)
from app.agents.live_smartwatch_specialist import (
    LiveSmartwatchSpecialistAgent,
    MockSmartwatchSpecialistModelRunner,
)
from app.agents.live_tv_specialist import (
    LiveTVSpecialistAgent,
    MockTVSpecialistModelRunner,
)
from app.agents.live_technology_domain_analyst import (
    LiveTechnologyDomainAnalystAgent,
    MockTechnologyDomainAnalystModelRunner,
)
from app.agents.live_guide import LiveShoppingGuideAgent, MockShoppingGuideModelRunner
from app.agents.live_intake import LiveIntakeAgent, MockIntakeModelRunner
from app.agents.live_discovery import LiveDiscoveryAgent, MockDiscoveryModelRunner
from app.agents.live_query_planner import (
    LiveQueryPlannerAgent,
    MockQueryPlannerModelRunner,
)
from app.agents.live_seller_listing_trust import (
    LiveSellerListingTrustAgent,
    MockSellerListingTrustModelRunner,
)
from app.agents.live_reddit_community_intelligence import (
    LiveRedditCommunityIntelligenceAgent,
)
from app.agents.live_amazon_product_intelligence import (
    LiveAmazonProductIntelligenceAgent,
)
from app.agents.live_ikea_store_intelligence import (
    LiveIKEAStoreIntelligenceAgent,
)
from app.agents.live_youtube_review_intelligence import (
    LiveYouTubeReviewIntelligenceAgent,
)
from app.agents.openai_config import (
    OpenAIAgentConfigurationError,
    build_openai_agent_run_configuration,
    require_live_openai_agent_configuration,
)
from app.core.settings import EnvironmentMode, Settings
from app.providers import (
    AmazonProductIntelligenceProviderOptions,
    AmazonProductIntelligenceProviderResult,
    CommunityDiscussionProviderOptions,
    CommunityDiscussionProviderResult,
    IKEAStoreIntelligenceProviderOptions,
    IKEAStoreIntelligenceProviderResult,
    ProviderCapabilityFlags,
    ProviderRunStatus,
    TranscriptAccessStrategy,
    TranscriptProviderOptions,
    TranscriptProviderResult,
)
from app.schemas.analysis import (
    CategoryAnalysis,
    ComparisonCriterion,
    ComparisonMatrix,
    ComparisonRow,
    DeduplicationDecision,
    DeduplicationOutcome,
    ListingTrustAssessment,
    ListingTrustLevel,
    RecommendationBundle,
    RecommendationMode,
    RecommendationModeResult,
)
from app.schemas.base import CartCartBaseModel, VersionedSchema
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.guided_intake import (
    RegionSetupSubmission,
    RegionSetupStatus,
)
from app.schemas.ids import new_id
from app.schemas.intake import (
    BudgetConstraint,
    BudgetMode,
    CreateSessionRequest,
    FieldSource,
    PreferenceConstraint,
    PreferenceMode,
    RegionPreference,
    ShoppingBrief,
)
from app.schemas.money import Money
from app.schemas.products import (
    CanonicalProduct,
    RegionAvailability,
    ProductListing,
    SellerProfile,
    SellerTrustSignal,
)
from app.schemas.regions import Region
from app.schemas.search_sources import (
    AmazonListingContext,
    AmazonProductEvidenceBundle,
    CommunityDiscussionContext,
    CommunityDiscussionEvidenceBundle,
    EvidenceTarget,
    EvidenceTargetType,
    EvidenceType,
    ExtractionStatus,
    IKEAStoreContext,
    IKEAStoreEvidenceBundle,
    ProviderMetadata,
    RegionalStoreAvailability,
    SearchIntent,
    SearchPlan,
    SearchQuery,
    SearchResult,
    SourceEvidence,
    SourceEvidenceGap,
    SourceIntelligenceCapability,
    SourceQuality,
    SourceQualityLevel,
    SourceSnapshot,
    SourceType,
    TranscriptAvailability,
    VideoSource,
    VideoTranscriptSegment,
)
from app.schemas.source_references import SourceReference
from app.services.amazon_evidence_creation import (
    AmazonProductEvidenceCreator,
    AmazonProductEvidenceInput,
)
from app.services.ikea_evidence_creation import (
    IKEAStoreEvidenceCreator,
    IKEAStoreEvidenceInput,
)
from app.services.listing_trust import ListingTrustRuleContext, assess_listing_trust


ALLOWED_WORKBENCH_ENVIRONMENTS = frozenset(
    {
        EnvironmentMode.LOCAL,
        EnvironmentMode.TEST,
        EnvironmentMode.FIXTURE,
    }
)


class AgentWorkbenchMode(StrEnum):
    FIXTURE = "fixture"
    MOCK = "mock"
    LIVE = "live"


class AgentWorkbenchError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


class WorkbenchToolActivity(CartCartBaseModel):
    tool_name: str = Field(min_length=1, max_length=200)
    status: str = Field(min_length=1, max_length=80)
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None


class WorkbenchUsage(CartCartBaseModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: str | None = Field(default=None, min_length=1, max_length=80)


class WorkbenchFallbackOutcome(CartCartBaseModel):
    used: bool = False
    reason: str | None = Field(default=None, min_length=1, max_length=500)


class AgentWorkbenchScenarioSummary(CartCartBaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=500)
    input: dict[str, Any]
    boundary: bool = False


class AgentWorkbenchAgentSummary(CartCartBaseModel):
    agent_name: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=80)
    invocation_mode: str = Field(min_length=1, max_length=80)
    input_schema: str = Field(min_length=1, max_length=200)
    output_schema: str = Field(min_length=1, max_length=200)
    modes: tuple[AgentWorkbenchMode, ...]
    scenarios: tuple[AgentWorkbenchScenarioSummary, ...]


class AgentWorkbenchCatalogResponse(VersionedSchema):
    enabled: bool
    environment: str = Field(min_length=1, max_length=80)
    live_agents_enabled: bool
    live_mode_notice: str
    agents: tuple[AgentWorkbenchAgentSummary, ...]


class AgentWorkbenchRunRequest(CartCartBaseModel):
    agent_name: str = Field(min_length=1, max_length=200)
    scenario_name: str = Field(min_length=1, max_length=200)
    mode: AgentWorkbenchMode = AgentWorkbenchMode.FIXTURE
    input: dict[str, Any] | None = None


class AgentWorkbenchRunResult(VersionedSchema):
    agent_name: str = Field(min_length=1, max_length=200)
    scenario_name: str = Field(min_length=1, max_length=200)
    mode: AgentWorkbenchMode
    input_schema: str = Field(min_length=1, max_length=200)
    output_schema: str = Field(min_length=1, max_length=200)
    input: dict[str, Any]
    output: dict[str, Any] | list[Any] | None = None
    allowed_tool_activity: tuple[WorkbenchToolActivity, ...] = Field(
        default_factory=tuple
    )
    fallback: WorkbenchFallbackOutcome = Field(default_factory=WorkbenchFallbackOutcome)
    error: str | None = Field(default=None, min_length=1, max_length=1000)
    trace_id: str = Field(min_length=1, max_length=120)
    usage: WorkbenchUsage | None = None
    model: str = Field(min_length=1, max_length=200)
    elapsed_ms: float = Field(ge=0)
    live_mode_notice: str | None = Field(default=None, min_length=1, max_length=500)


class AgentWorkbenchScenario(CartCartBaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=500)
    input: dict[str, Any]
    boundary: bool = False


@dataclass(frozen=True)
class _WorkbenchExecution:
    output: Any
    allowed_tool_activity: tuple[WorkbenchToolActivity, ...] = ()


@dataclass(frozen=True)
class _AgentWorkbenchDefinition:
    entry: AgentCatalogEntry
    input_model: type[CartCartBaseModel]
    output_schema_name: str
    scenario_builders: tuple[Callable[[], AgentWorkbenchScenario], ...]
    fixture_agent_factory: Callable[[], Any] | None = None
    mock_agent_factory: Callable[[Settings], Any] | None = None
    live_agent_factory: Callable[[Settings], Any] | None = None

    @property
    def scenarios(self) -> tuple[AgentWorkbenchScenario, ...]:
        return tuple(builder() for builder in self.scenario_builders)

    def scenario_by_name(self, scenario_name: str) -> AgentWorkbenchScenario | None:
        for scenario in self.scenarios:
            if scenario.name == scenario_name:
                return scenario
        return None

    def available_modes(self) -> tuple[AgentWorkbenchMode, ...]:
        return (
            AgentWorkbenchMode.FIXTURE,
            AgentWorkbenchMode.MOCK,
            AgentWorkbenchMode.LIVE,
        )


class AgentWorkbenchRunner:
    def __init__(
        self,
        settings: Settings,
        *,
        catalog: AgentCatalog = DEFAULT_AGENT_CATALOG,
    ) -> None:
        self._settings = settings
        self._catalog = catalog
        self._definitions = _build_workbench_definitions(catalog)

    def catalog_response(self) -> AgentWorkbenchCatalogResponse:
        self._require_available()
        return AgentWorkbenchCatalogResponse(
            enabled=True,
            environment=self._settings.environment.value,
            live_agents_enabled=self._settings.live_agents_enabled,
            live_mode_notice=_live_mode_notice(),
            agents=tuple(
                AgentWorkbenchAgentSummary(
                    agent_name=definition.entry.agent_name,
                    kind=definition.entry.kind.value,
                    invocation_mode=definition.entry.invocation_mode.value,
                    input_schema=definition.input_model.__name__,
                    output_schema=definition.output_schema_name,
                    modes=definition.available_modes(),
                    scenarios=tuple(
                        AgentWorkbenchScenarioSummary(
                            name=scenario.name,
                            description=scenario.description,
                            input=scenario.input,
                            boundary=scenario.boundary,
                        )
                        for scenario in definition.scenarios
                    ),
                )
                for definition in self._definitions.values()
            ),
        )

    async def run(self, request: AgentWorkbenchRunRequest) -> AgentWorkbenchRunResult:
        self._require_available()
        definition = self._definition_for_agent(request.agent_name)
        scenario = definition.scenario_by_name(request.scenario_name)
        if scenario is None:
            raise AgentWorkbenchError(
                "agent_workbench_scenario_not_found",
                "The requested workbench scenario is not registered for this agent.",
                status_code=404,
                details={
                    "agent_name": request.agent_name,
                    "scenario_name": request.scenario_name,
                },
            )

        input_payload = request.input if request.input is not None else scenario.input
        input_data = _validate_input(definition, input_payload)
        configuration = build_openai_agent_run_configuration(
            self._settings,
            agent_name=definition.entry.agent_name,
        )
        trace_id = f"agent_workbench_{new_id()}"

        started_at = perf_counter()
        if request.mode == AgentWorkbenchMode.LIVE:
            execution = await self._run_live(definition, input_data)
            live_notice = _live_mode_notice()
        elif request.mode == AgentWorkbenchMode.MOCK:
            execution = await self._run_mock(definition, input_data)
            live_notice = None
        else:
            execution = await self._run_fixture(definition, input_data)
            live_notice = None

        elapsed_ms = round((perf_counter() - started_at) * 1000, 3)
        return AgentWorkbenchRunResult(
            agent_name=definition.entry.agent_name,
            scenario_name=scenario.name,
            mode=request.mode,
            input_schema=definition.input_model.__name__,
            output_schema=definition.output_schema_name,
            input=input_data.model_dump(mode="json"),
            output=_dump_output(execution.output),
            allowed_tool_activity=execution.allowed_tool_activity,
            fallback=WorkbenchFallbackOutcome(used=False),
            trace_id=trace_id,
            usage=None,
            model=configuration.model,
            elapsed_ms=elapsed_ms,
            live_mode_notice=live_notice,
        )

    def _require_available(self) -> None:
        if not self._settings.agent_workbench_enabled:
            raise AgentWorkbenchError(
                "agent_workbench_disabled",
                "The isolated agent workbench is disabled.",
                status_code=404,
            )
        if self._settings.environment not in ALLOWED_WORKBENCH_ENVIRONMENTS:
            raise AgentWorkbenchError(
                "agent_workbench_unavailable",
                "The isolated agent workbench is available only in local, test, or fixture environments.",
                status_code=404,
                details={"environment": self._settings.environment.value},
            )

    def _definition_for_agent(
        self,
        agent_name: str,
    ) -> _AgentWorkbenchDefinition:
        definition = self._definitions.get(agent_name)
        if definition is None:
            raise AgentWorkbenchError(
                "agent_workbench_agent_not_allowed",
                "The requested agent is not registered in the isolated workbench catalog.",
                status_code=404,
                details={"agent_name": agent_name},
            )
        return definition

    async def _run_fixture(
        self,
        definition: _AgentWorkbenchDefinition,
        input_data: CartCartBaseModel,
    ) -> _WorkbenchExecution:
        if definition.fixture_agent_factory is None:
            raise AgentWorkbenchError(
                "agent_workbench_mode_unavailable",
                "This agent does not have a fixture or mock workbench runner.",
                status_code=400,
                details={"agent_name": definition.entry.agent_name},
            )
        agent = definition.fixture_agent_factory()
        output = await agent.run(input_data)
        return _WorkbenchExecution(
            output=output,
            allowed_tool_activity=_workbench_activity(agent),
        )

    async def _run_mock(
        self,
        definition: _AgentWorkbenchDefinition,
        input_data: CartCartBaseModel,
    ) -> _WorkbenchExecution:
        agent_factory = (
            definition.mock_agent_factory or definition.fixture_agent_factory
        )
        if agent_factory is None:
            raise AgentWorkbenchError(
                "agent_workbench_mode_unavailable",
                "This agent does not have a mock workbench runner.",
                status_code=400,
                details={"agent_name": definition.entry.agent_name},
            )
        if definition.mock_agent_factory is not None:
            agent = definition.mock_agent_factory(self._settings)
        else:
            agent = agent_factory()
        output = await agent.run(input_data)
        return _WorkbenchExecution(
            output=output,
            allowed_tool_activity=_workbench_activity(agent),
        )

    async def _run_live(
        self,
        definition: _AgentWorkbenchDefinition,
        input_data: CartCartBaseModel,
    ) -> _WorkbenchExecution:
        try:
            require_live_openai_agent_configuration(
                self._settings,
                agent_name=definition.entry.agent_name,
            )
        except OpenAIAgentConfigurationError as exc:
            raise AgentWorkbenchError(
                "agent_workbench_live_mode_unavailable",
                str(exc),
                status_code=400,
                details={
                    "agent_name": definition.entry.agent_name,
                    "missing_env_var": "OPENAI_API_KEY"
                    if self._settings.openai_api_key is None
                    else None,
                },
            ) from exc
        if definition.live_agent_factory is None:
            raise AgentWorkbenchError(
                "agent_workbench_live_agent_not_registered",
                "Live mode is configured, but this agent does not have a live workbench runner yet.",
                status_code=400,
                details={"agent_name": definition.entry.agent_name},
            )
        agent = definition.live_agent_factory(self._settings)
        output = await agent.run(input_data)
        return _WorkbenchExecution(
            output=output,
            allowed_tool_activity=_workbench_activity(agent),
        )


def _validate_input(
    definition: _AgentWorkbenchDefinition,
    input_payload: dict[str, Any],
) -> CartCartBaseModel:
    try:
        return definition.input_model.model_validate(input_payload)
    except ValidationError as exc:
        raise AgentWorkbenchError(
            "agent_workbench_invalid_input",
            "Workbench input does not validate against the agent input schema.",
            status_code=422,
            details={"errors": exc.errors(include_url=False)},
        ) from exc


def _dump_output(output: Any) -> dict[str, Any] | list[Any]:
    if isinstance(output, CartCartBaseModel):
        return output.model_dump(mode="json")
    return jsonable_encoder(output)


def _workbench_activity(agent: Any) -> tuple[WorkbenchToolActivity, ...]:
    raw_items = getattr(agent, "workbench_activity", ())
    return tuple(WorkbenchToolActivity.model_validate(item) for item in raw_items)


def _build_workbench_definitions(
    catalog: AgentCatalog,
) -> dict[str, _AgentWorkbenchDefinition]:
    definitions = {
        "ShoppingScopeGuardrail": _definition(
            catalog,
            "ShoppingScopeGuardrail",
            ShoppingScopeGuardrailInput,
            "ShoppingGuardrailResult",
            FakeShoppingScopeGuardrail,
            (
                _scenario_guardrail_allowed,
                _scenario_guardrail_blocked,
                _scenario_guardrail_allowed_coffee_grinder,
                _scenario_guardrail_blocked_dangerous_product,
            ),
            mock_agent_factory=_mock_shopping_scope_guardrail,
            live_agent_factory=LiveShoppingScopeGuardrail,
        ),
        "ShoppingGuideAgent": _definition(
            catalog,
            "ShoppingGuideAgent",
            ShoppingGuideAgentInput,
            "GuidedIntakeState",
            FakeShoppingGuideAgent,
            (
                _scenario_guide_monitor,
                _scenario_guide_blocked,
                _scenario_guide_headphones_missing_budget,
                _scenario_guide_ready_monitor_brief,
            ),
            mock_agent_factory=_mock_shopping_guide_agent,
            live_agent_factory=LiveShoppingGuideAgent,
        ),
        "IntakeAgent": _definition(
            catalog,
            "IntakeAgent",
            IntakeAgentInput,
            "ShoppingBrief",
            FakeIntakeAgent,
            (
                _scenario_intake_monitor,
                _scenario_intake_missing_region,
                _scenario_intake_monitor_ph_budget,
                _scenario_intake_ambiguous_category,
            ),
            mock_agent_factory=_mock_intake_agent,
            live_agent_factory=LiveIntakeAgent,
        ),
        "QueryPlannerAgent": _definition(
            catalog,
            "QueryPlannerAgent",
            QueryPlannerAgentInput,
            "SearchPlan",
            FakeQueryPlannerAgent,
            (
                _scenario_query_planner_coffee_grinder_us,
                _scenario_query_planner_unknown_category_generic,
            ),
            mock_agent_factory=_mock_query_planner_agent,
            live_agent_factory=LiveQueryPlannerAgent,
        ),
        "DiscoveryAgent": _definition(
            catalog,
            "DiscoveryAgent",
            DiscoveryAgentInput,
            "DiscoveryAgentOutput",
            FakeDiscoveryAgent,
            (
                _scenario_discovery_select_valid_sources,
                _scenario_discovery_no_good_results,
                _scenario_discovery_with_seed,
                _scenario_discovery_empty_seed,
            ),
            mock_agent_factory=_mock_discovery_agent,
            live_agent_factory=LiveDiscoveryAgent,
        ),
        "CategoryRouterAgent": _definition(
            catalog,
            "CategoryRouterAgent",
            CategoryRouterAgentInput,
            "ProductAnalysisRoute",
            FakeCategoryRouterAgent,
            (
                _scenario_router_monitor_to_specialist,
                _scenario_router_office_chair_generic,
            ),
            mock_agent_factory=_mock_category_router_agent,
            live_agent_factory=LiveCategoryRouterAgent,
        ),
        "ExtractionReviewAgent": _definition(
            catalog,
            "ExtractionReviewAgent",
            ExtractionReviewAgentInput,
            "ExtractionReviewAgentOutput",
            FakeExtractionReviewAgent,
            (_scenario_extraction_snapshot, _scenario_extraction_empty),
        ),
        "DeduplicationReviewAgent": _definition(
            catalog,
            "DeduplicationReviewAgent",
            DeduplicationReviewAgentInput,
            "tuple[DeduplicationDecision, ...]",
            FakeDeduplicationReviewAgent,
            (_scenario_deduplication_pair, _scenario_deduplication_empty),
        ),
        "GenericProductAnalystAgent": _definition(
            catalog,
            "GenericProductAnalystAgent",
            ProductAnalysisAgentInput,
            "CategoryAnalysis",
            FakeGenericProductAnalystAgent,
            (_scenario_generic_analysis, _scenario_generic_weak_evidence),
            mock_agent_factory=_mock_generic_product_analyst_agent,
            live_agent_factory=LiveGenericProductAnalystAgent,
        ),
        "TechnologyDomainAnalystAgent": _definition(
            catalog,
            "TechnologyDomainAnalystAgent",
            ProductAnalysisAgentInput,
            "CategoryAnalysis",
            FakeTechnologyDomainAnalystAgent,
            (
                _scenario_technology_router_monitor,
                _scenario_technology_router_keyboard_domain,
            ),
            mock_agent_factory=_mock_technology_domain_analyst_agent,
            live_agent_factory=LiveTechnologyDomainAnalystAgent,
        ),
        "MonitorSpecialistAgent": _definition(
            catalog,
            "MonitorSpecialistAgent",
            ProductAnalysisAgentInput,
            "CategoryAnalysis",
            FakeMonitorSpecialistAgent,
            (_scenario_monitor_analysis, _scenario_monitor_non_monitor),
            mock_agent_factory=_mock_monitor_specialist_agent,
            live_agent_factory=LiveMonitorSpecialistAgent,
        ),
        "SmartphoneSpecialistAgent": _definition(
            catalog,
            "SmartphoneSpecialistAgent",
            ProductAnalysisAgentInput,
            "CategoryAnalysis",
            FakeSmartphoneSpecialistAgent,
            (_scenario_smartphone_analysis, _scenario_smartphone_non_phone),
            mock_agent_factory=_mock_smartphone_specialist_agent,
            live_agent_factory=LiveSmartphoneSpecialistAgent,
        ),
        "LaptopSpecialistAgent": _definition(
            catalog,
            "LaptopSpecialistAgent",
            ProductAnalysisAgentInput,
            "CategoryAnalysis",
            FakeLaptopSpecialistAgent,
            (_scenario_laptop_analysis, _scenario_laptop_non_laptop),
            mock_agent_factory=_mock_laptop_specialist_agent,
            live_agent_factory=LiveLaptopSpecialistAgent,
        ),
        "EarphonesHeadphonesSpecialistAgent": _definition(
            catalog,
            "EarphonesHeadphonesSpecialistAgent",
            ProductAnalysisAgentInput,
            "CategoryAnalysis",
            FakeEarphonesHeadphonesSpecialistAgent,
            (_scenario_headphones_analysis, _scenario_headphones_non_audio),
            mock_agent_factory=_mock_earphones_headphones_specialist_agent,
            live_agent_factory=LiveEarphonesHeadphonesSpecialistAgent,
        ),
        "TVSpecialistAgent": _definition(
            catalog,
            "TVSpecialistAgent",
            ProductAnalysisAgentInput,
            "CategoryAnalysis",
            FakeTVSpecialistAgent,
            (_scenario_tv_analysis, _scenario_tv_non_tv),
            mock_agent_factory=_mock_tv_specialist_agent,
            live_agent_factory=LiveTVSpecialistAgent,
        ),
        "SmartwatchSpecialistAgent": _definition(
            catalog,
            "SmartwatchSpecialistAgent",
            ProductAnalysisAgentInput,
            "CategoryAnalysis",
            FakeSmartwatchSpecialistAgent,
            (_scenario_smartwatch_analysis, _scenario_smartwatch_non_watch),
            mock_agent_factory=_mock_smartwatch_specialist_agent,
            live_agent_factory=LiveSmartwatchSpecialistAgent,
        ),
        "SellerListingTrustAgent": _definition(
            catalog,
            "SellerListingTrustAgent",
            SellerListingTrustAgentInput,
            "ListingTrustAssessment",
            FakeSellerListingTrustAgent,
            (
                _scenario_trust_unknown_marketplace_cheap,
                _scenario_trust_established,
            ),
            mock_agent_factory=_mock_seller_listing_trust_agent,
            live_agent_factory=LiveSellerListingTrustAgent,
        ),
        "YouTubeReviewIntelligenceAgent": _definition(
            catalog,
            "YouTubeReviewIntelligenceAgent",
            YouTubeReviewIntelligenceAgentInput,
            "VideoReviewEvidenceBundle",
            _fixture_youtube_review_intelligence_agent,
            (
                _scenario_youtube_monitor_review_transcript,
                _scenario_youtube_no_transcript_gap,
            ),
            mock_agent_factory=_mock_youtube_review_intelligence_agent,
            live_agent_factory=LiveYouTubeReviewIntelligenceAgent,
        ),
        "RedditCommunityIntelligenceAgent": _definition(
            catalog,
            "RedditCommunityIntelligenceAgent",
            RedditCommunityIntelligenceAgentInput,
            "CommunityDiscussionEvidenceBundle",
            _fixture_reddit_community_intelligence_agent,
            (
                _scenario_reddit_headphones_recurring_complaint,
                _scenario_reddit_inaccessible_gap,
            ),
            mock_agent_factory=_mock_reddit_community_intelligence_agent,
            live_agent_factory=LiveRedditCommunityIntelligenceAgent,
        ),
        "AmazonProductIntelligenceAgent": _definition(
            catalog,
            "AmazonProductIntelligenceAgent",
            AmazonProductIntelligenceAgentInput,
            "AmazonProductEvidenceBundle",
            _fixture_amazon_product_intelligence_agent,
            (
                _scenario_amazon_third_party_seller_region_gap,
                _scenario_amazon_variant_ambiguity,
            ),
            mock_agent_factory=_mock_amazon_product_intelligence_agent,
            live_agent_factory=LiveAmazonProductIntelligenceAgent,
        ),
        "IKEAStoreIntelligenceAgent": _definition(
            catalog,
            "IKEAStoreIntelligenceAgent",
            IKEAStoreIntelligenceAgentInput,
            "IKEAStoreEvidenceBundle",
            _fixture_ikea_store_intelligence_agent,
            (
                _scenario_ikea_available_regional_product,
                _scenario_ikea_no_regional_presence,
            ),
            mock_agent_factory=_mock_ikea_store_intelligence_agent,
            live_agent_factory=LiveIKEAStoreIntelligenceAgent,
        ),
        "ComparisonDecisionAgent": _definition(
            catalog,
            "ComparisonDecisionAgent",
            ComparisonDecisionAgentInput,
            "RecommendationBundle",
            FakeComparisonDecisionAgent,
            (_scenario_comparison_monitor_shortlist, _scenario_comparison_no_strong_buy),
            mock_agent_factory=_mock_comparison_decision_agent,
            live_agent_factory=LiveComparisonDecisionAgent,
        ),
        "VerifierCriticAgent": _definition(
            catalog,
            "VerifierCriticAgent",
            VerificationAgentInput,
            "VerificationReport",
            FakeVerifierCriticAgent,
            (
                _scenario_verifier_approved,
                _scenario_verifier_warning,
                _scenario_verifier_unsupported_claim_block,
                _scenario_verifier_suspicious_listing_warning,
            ),
            mock_agent_factory=_mock_verifier_critic_agent,
            live_agent_factory=LiveVerifierCriticAgent,
        ),
    }
    return definitions


def _definition(
    catalog: AgentCatalog,
    agent_name: str,
    input_model: type[CartCartBaseModel],
    output_schema_name: str,
    fixture_agent_factory: Callable[[], Any],
    scenario_builders: tuple[Callable[[], AgentWorkbenchScenario], ...],
    *,
    mock_agent_factory: Callable[[Settings], Any] | None = None,
    live_agent_factory: Callable[[Settings], Any] | None = None,
) -> _AgentWorkbenchDefinition:
    return _AgentWorkbenchDefinition(
        entry=catalog.require(agent_name),
        input_model=input_model,
        output_schema_name=output_schema_name,
        fixture_agent_factory=fixture_agent_factory,
        mock_agent_factory=mock_agent_factory,
        live_agent_factory=live_agent_factory,
        scenario_builders=scenario_builders,
    )


def _mock_shopping_scope_guardrail(settings: Settings) -> LiveShoppingScopeGuardrail:
    return LiveShoppingScopeGuardrail(
        settings=settings,
        model_runner=MockShoppingGuardrailModelRunner(),
    )


def _mock_shopping_guide_agent(settings: Settings) -> LiveShoppingGuideAgent:
    return LiveShoppingGuideAgent(
        settings=settings,
        model_runner=MockShoppingGuideModelRunner(),
        intake_agent=LiveIntakeAgent(
            settings=settings,
            model_runner=MockIntakeModelRunner(),
        ),
    )


def _mock_intake_agent(settings: Settings) -> LiveIntakeAgent:
    return LiveIntakeAgent(
        settings=settings,
        model_runner=MockIntakeModelRunner(),
    )


def _mock_discovery_agent(settings: Settings) -> LiveDiscoveryAgent:
    return LiveDiscoveryAgent(
        settings=settings,
        model_runner=MockDiscoveryModelRunner(),
    )


def _mock_query_planner_agent(settings: Settings) -> LiveQueryPlannerAgent:
    return LiveQueryPlannerAgent(
        settings=settings,
        model_runner=MockQueryPlannerModelRunner(),
    )


def _mock_category_router_agent(settings: Settings) -> LiveCategoryRouterAgent:
    return LiveCategoryRouterAgent(
        settings=settings,
        model_runner=MockCategoryRouterModelRunner(),
    )


def _mock_generic_product_analyst_agent(
    settings: Settings,
) -> LiveGenericProductAnalystAgent:
    return LiveGenericProductAnalystAgent(
        settings=settings,
        model_runner=MockGenericProductAnalystModelRunner(),
    )


def _mock_technology_domain_analyst_agent(
    settings: Settings,
) -> LiveTechnologyDomainAnalystAgent:
    return LiveTechnologyDomainAnalystAgent(
        settings=settings,
        model_runner=MockTechnologyDomainAnalystModelRunner(),
    )


def _mock_monitor_specialist_agent(settings: Settings) -> LiveMonitorSpecialistAgent:
    return LiveMonitorSpecialistAgent(
        settings=settings,
        model_runner=MockMonitorSpecialistModelRunner(),
    )


def _mock_smartphone_specialist_agent(
    settings: Settings,
) -> LiveSmartphoneSpecialistAgent:
    return LiveSmartphoneSpecialistAgent(
        settings=settings,
        model_runner=MockSmartphoneSpecialistModelRunner(),
    )


def _mock_laptop_specialist_agent(settings: Settings) -> LiveLaptopSpecialistAgent:
    return LiveLaptopSpecialistAgent(
        settings=settings,
        model_runner=MockLaptopSpecialistModelRunner(),
    )


def _mock_earphones_headphones_specialist_agent(
    settings: Settings,
) -> LiveEarphonesHeadphonesSpecialistAgent:
    return LiveEarphonesHeadphonesSpecialistAgent(
        settings=settings,
        model_runner=MockEarphonesHeadphonesSpecialistModelRunner(),
    )


def _mock_tv_specialist_agent(settings: Settings) -> LiveTVSpecialistAgent:
    return LiveTVSpecialistAgent(
        settings=settings,
        model_runner=MockTVSpecialistModelRunner(),
    )


def _mock_smartwatch_specialist_agent(
    settings: Settings,
) -> LiveSmartwatchSpecialistAgent:
    return LiveSmartwatchSpecialistAgent(
        settings=settings,
        model_runner=MockSmartwatchSpecialistModelRunner(),
    )


def _mock_seller_listing_trust_agent(
    settings: Settings,
) -> LiveSellerListingTrustAgent:
    return LiveSellerListingTrustAgent(
        settings=settings,
        model_runner=MockSellerListingTrustModelRunner(),
    )


def _mock_comparison_decision_agent(settings: Settings) -> LiveComparisonDecisionAgent:
    return LiveComparisonDecisionAgent(
        settings=settings,
        model_runner=MockComparisonDecisionModelRunner(),
    )


def _mock_verifier_critic_agent(settings: Settings) -> LiveVerifierCriticAgent:
    return LiveVerifierCriticAgent(
        settings=settings,
        model_runner=MockVerifierCriticModelRunner(),
    )


def _fixture_youtube_review_intelligence_agent() -> LiveYouTubeReviewIntelligenceAgent:
    return LiveYouTubeReviewIntelligenceAgent(
        transcript_provider=_WorkbenchYouTubeTranscriptProvider(),
    )


def _mock_youtube_review_intelligence_agent(
    settings: Settings,
) -> LiveYouTubeReviewIntelligenceAgent:
    return LiveYouTubeReviewIntelligenceAgent(
        settings=settings,
        transcript_provider=_WorkbenchYouTubeTranscriptProvider(),
    )


def _fixture_reddit_community_intelligence_agent() -> (
    LiveRedditCommunityIntelligenceAgent
):
    return LiveRedditCommunityIntelligenceAgent(
        community_provider=_WorkbenchRedditCommunityProvider(),
    )


def _mock_reddit_community_intelligence_agent(
    settings: Settings,
) -> LiveRedditCommunityIntelligenceAgent:
    return LiveRedditCommunityIntelligenceAgent(
        settings=settings,
        community_provider=_WorkbenchRedditCommunityProvider(),
    )


def _fixture_amazon_product_intelligence_agent() -> (
    LiveAmazonProductIntelligenceAgent
):
    return LiveAmazonProductIntelligenceAgent(
        amazon_provider=_WorkbenchAmazonProductIntelligenceProvider(),
    )


def _mock_amazon_product_intelligence_agent(
    settings: Settings,
) -> LiveAmazonProductIntelligenceAgent:
    return LiveAmazonProductIntelligenceAgent(
        settings=settings,
        amazon_provider=_WorkbenchAmazonProductIntelligenceProvider(),
    )


def _fixture_ikea_store_intelligence_agent() -> LiveIKEAStoreIntelligenceAgent:
    return LiveIKEAStoreIntelligenceAgent(
        ikea_provider=_WorkbenchIKEAStoreIntelligenceProvider(),
    )


def _mock_ikea_store_intelligence_agent(
    settings: Settings,
) -> LiveIKEAStoreIntelligenceAgent:
    return LiveIKEAStoreIntelligenceAgent(
        settings=settings,
        ikea_provider=_WorkbenchIKEAStoreIntelligenceProvider(),
    )


@dataclass(frozen=True)
class _WorkbenchYouTubeTranscriptProvider:
    provider_name: str = "workbench-youtube-transcripts"

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name=self.provider_name,
            enabled=True,
            supports_transcripts=True,
            permits_transcript_text=True,
            transcript_access_strategy=TranscriptAccessStrategy.USER_PROVIDED,
            compliance_notes=(
                "Workbench fixture transcript provider with typed segments.",
            ),
        )

    async def fetch_transcript(
        self,
        video: VideoSource,
        options: TranscriptProviderOptions | None = None,
    ) -> TranscriptProviderResult:
        del options
        if video.video_id == "ccNoTrans01":
            return TranscriptProviderResult(
                status=ProviderRunStatus.SUCCEEDED,
                capabilities=self.capabilities,
                video=video.model_copy(
                    update={
                        "transcript_availability": TranscriptAvailability.UNAVAILABLE
                    }
                ),
                availability=TranscriptAvailability.UNAVAILABLE,
                gap_notes=(
                    "Workbench fixture has video metadata but no transcript segments.",
                ),
            )

        segments = (
            VideoTranscriptSegment(
                video_id=video.video_id,
                start_seconds=15.0,
                end_seconds=26.0,
                language="en",
                text=(
                    "Pro: the Fixture Monitor has sharp text and strong brightness "
                    "for coding."
                ),
            ),
            VideoTranscriptSegment(
                video_id=video.video_id,
                start_seconds=64.0,
                end_seconds=75.0,
                language="en",
                text="Con: the built-in speakers are weak and HDR looks washed out.",
            ),
            VideoTranscriptSegment(
                video_id=video.video_id,
                start_seconds=132.0,
                end_seconds=145.0,
                language="en",
                text=(
                    "Concern: the stand can wobble on light desks, and this video "
                    "has sponsored disclosure plus affiliate links."
                ),
            ),
        )
        return TranscriptProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            video=video.model_copy(
                update={"transcript_availability": TranscriptAvailability.AVAILABLE}
            ),
            availability=TranscriptAvailability.AVAILABLE,
            segments=segments,
        )


@dataclass(frozen=True)
class _WorkbenchRedditCommunityProvider:
    provider_name: str = "workbench-reddit-community"

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name=self.provider_name,
            enabled=True,
            supports_domain_scoped_search=True,
            supports_public_page_extraction=True,
            supports_community_discussion_retrieval=True,
            compliance_notes=(
                "Workbench fixture provider with public Reddit discussion summaries.",
            ),
        )

    async def search_discussions(
        self,
        query: str,
        products: tuple[CanonicalProduct, ...] = (),
        options: CommunityDiscussionProviderOptions | None = None,
    ) -> CommunityDiscussionProviderResult:
        del products, options
        if "inaccessible" in query.casefold():
            return CommunityDiscussionProviderResult(
                status=ProviderRunStatus.SUCCEEDED,
                capabilities=self.capabilities,
                bundle=_workbench_reddit_inaccessible_bundle(),
                notes=("Workbench fixture models inaccessible public content.",),
            )
        return CommunityDiscussionProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            bundle=_workbench_reddit_recurring_complaint_bundle(query),
            notes=("Reddit evidence is qualitative community signal.",),
        )


@dataclass(frozen=True)
class _WorkbenchAmazonProductIntelligenceProvider:
    provider_name: str = "workbench-amazon-product-intelligence"

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name=self.provider_name,
            enabled=True,
            supports_amazon_product_intelligence=True,
            supports_amazon_listing_identity=True,
            supports_amazon_review_signals=True,
            supports_regional_ship_to_evidence=True,
            compliance_notes=(
                "Workbench fixture provider with neutral Amazon listing URLs.",
                "Seller/listing trust remains a separate downstream concern.",
            ),
        )

    async def fetch_product_evidence(
        self,
        product: CanonicalProduct,
        listings: tuple[ProductListing, ...] = (),
        options: AmazonProductIntelligenceProviderOptions | None = None,
    ) -> AmazonProductIntelligenceProviderResult:
        del listings
        region_code = options.region_code if options is not None else None
        return AmazonProductIntelligenceProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            bundle=_workbench_amazon_bundle(
                product,
                region_code=region_code or "US",
                variant_ambiguity=_is_variant_query(product.name),
            ),
            notes=("Amazon evidence preserves marketplace-specific context.",),
        )


@dataclass(frozen=True)
class _WorkbenchIKEAStoreIntelligenceProvider:
    provider_name: str = "workbench-ikea-store-intelligence"

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name=self.provider_name,
            enabled=True,
            supports_domain_scoped_search=True,
            supports_official_store_lookup=True,
            supports_ikea_regional_store_lookup=True,
            supports_ikea_product_pages=True,
            supports_ikea_store_delivery_context=True,
            compliance_notes=(
                "Workbench fixture provider with official regional IKEA context.",
                "Regional price, stock, pickup, and delivery claims are not global.",
            ),
        )

    async def fetch_store_evidence(
        self,
        product: CanonicalProduct,
        options: IKEAStoreIntelligenceProviderOptions | None = None,
    ) -> IKEAStoreIntelligenceProviderResult:
        region_code = options.region_code if options is not None else None
        if region_code == "AQ":
            bundle = IKEAStoreEvidenceBundle(
                evidence_gaps=(
                    SourceEvidenceGap(
                        capability=(
                            SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE
                        ),
                        target=EvidenceTarget(
                            target_type=EvidenceTargetType.REGION,
                            region_code="AQ",
                        ),
                        summary="No supported IKEA regional presence is configured for AQ.",
                        reason=(
                            "The workbench fixture has no official IKEA country or "
                            "region path for this target."
                        ),
                        source_quality=SourceQuality(
                            level=SourceQualityLevel.UNKNOWN
                        ),
                        confidence=_confidence(0.8),
                    ),
                ),
            )
        else:
            bundle = _workbench_ikea_available_bundle(
                product,
                region_code=region_code or "PH",
            )
        return IKEAStoreIntelligenceProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            bundle=bundle,
            notes=(
                "IKEA official-store evidence is scoped to the requested region.",
            ),
        )


def _workbench_reddit_recurring_complaint_bundle(
    query: str,
) -> CommunityDiscussionEvidenceBundle:
    first_source_id = new_id()
    second_source_id = new_id()
    first_url = "https://www.reddit.com/r/headphones/comments/hp123/ear_pads_split_after_months/"
    second_url = "https://www.reddit.com/r/HeadphoneAdvice/comments/hp456/owner_feedback/comment789/"
    recurring_claim = "ear pads split after a few months"
    discussions = (
        CommunityDiscussionContext(
            source_id=first_source_id,
            url=first_url,
            community_name="headphones",
            thread_id="hp123",
            thread_title="Workbench headphones long-term owner thread",
            comment_count=42,
            extracted_public_summary=(
                f"Owners report {recurring_claim}. Several also mention clamp "
                "discomfort after long sessions."
            ),
        ),
        CommunityDiscussionContext(
            source_id=second_source_id,
            url=second_url,
            community_name="HeadphoneAdvice",
            thread_id="hp456",
            comment_id="comment789",
            thread_title=f"{query} owner comments",
            engagement_score=87,
            extracted_public_summary=(
                f"Users say {recurring_claim} with daily use. One comment says "
                "replacement pads helped but did not solve fit discomfort."
            ),
        ),
    )
    return CommunityDiscussionEvidenceBundle(
        source_references=(
            SourceReference(
                source_id=first_source_id,
                url=first_url,
                title=discussions[0].thread_title,
            ),
            SourceReference(
                source_id=second_source_id,
                url=second_url,
                title=discussions[1].thread_title,
            ),
        ),
        discussions=discussions,
    )


def _workbench_reddit_inaccessible_bundle() -> CommunityDiscussionEvidenceBundle:
    source_id = new_id()
    url = "https://www.reddit.com/r/headphones/comments/deleted123/removed_thread/"
    return CommunityDiscussionEvidenceBundle(
        source_references=(
            SourceReference(
                source_id=source_id,
                url=url,
                title="Removed Reddit thread",
            ),
        ),
        discussions=(
            CommunityDiscussionContext(
                source_id=source_id,
                url=url,
                community_name="headphones",
                thread_id="deleted123",
                thread_title="Removed Reddit thread",
                extracted_public_summary=None,
            ),
        ),
        evidence_gaps=(
            SourceEvidenceGap(
                capability=SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.SOURCE_METADATA,
                    source_id=source_id,
                ),
                source_id=source_id,
                summary="Public Reddit content was inaccessible.",
                reason=(
                    "The workbench fixture represents deleted, removed, or "
                    "otherwise inaccessible public content."
                ),
                source_quality=SourceQuality(level=SourceQualityLevel.WEAK, score=0.15),
                confidence=_confidence(0.2),
            ),
        ),
    )


def _workbench_amazon_bundle(
    product: CanonicalProduct,
    *,
    region_code: str,
    variant_ambiguity: bool,
) -> AmazonProductEvidenceBundle:
    source_id = new_id()
    listing_id = product.listing_ids[0] if product.listing_ids else new_id()
    asin = "B0CARTVAR1" if variant_ambiguity else "B0CART5901"
    url = f"https://www.amazon.com/dp/{asin}"
    listing_title = (
        "Fixture Monitor Variant Listing"
        if variant_ambiguity
        else "Fixture Monitor Third-Party Listing"
    )
    review_warning = (
        "Review totals or summaries may combine multiple Amazon variants; "
        "the selected ASIN must be checked before applying review claims."
        if variant_ambiguity
        else None
    )
    return AmazonProductEvidenceCreator().create(
        (
            AmazonProductEvidenceInput(
                product_id=product.product_id,
                listing_id=listing_id,
                source_reference=SourceReference(
                    source_id=source_id,
                    url=url,
                    title=listing_title,
                ),
                listing_context=AmazonListingContext(
                    source_id=source_id,
                    marketplace_name="Amazon",
                    marketplace_domain="amazon.com",
                    marketplace_country_code="US",
                    listing_url=url,
                    asin=asin,
                    external_listing_id=asin,
                    product_title=listing_title,
                    variant_label="Color: Space Gray; Size: 27 inch"
                    if variant_ambiguity
                    else "Size: 27 inch",
                    seller_name="Fixture Deals",
                    fulfillment="Ships from Fixture Deals",
                    ships_to_region_code=region_code,
                    ships_to_region=None,
                    review_count=1287,
                    average_rating=4.4,
                ),
                source_quality=SourceQuality(
                    level=SourceQualityLevel.ADEQUATE,
                    score=0.76,
                    rationale=(
                        "Structured workbench Amazon marketplace fixture; "
                        "seller and review trust still require separate assessment."
                    ),
                ),
                product_page_claim=(
                    "Amazon product page states: 27-inch QHD monitor, USB-C "
                    "video input, height-adjustable stand."
                ),
                price_claim="Amazon displayed price: $289.99.",
                review_summary_claim=(
                    "Average rating 4.4 out of 5 from 1,287 reviews. "
                    "Customers mention sharp text and easy USB-C setup."
                ),
                review_quality_warnings=(
                    (review_warning,) if review_warning is not None else ()
                ),
            ),
        )
    )


def _workbench_ikea_available_bundle(
    product: CanonicalProduct,
    *,
    region_code: str,
) -> IKEAStoreEvidenceBundle:
    source_id = new_id()
    is_ph = region_code == "PH"
    url = (
        "https://www.ikea.com/ph/en/p/micke-desk-white-90214308/"
        if is_ph
        else "https://www.ikea.com/us/en/p/micke-desk-white-90214308/"
    )
    price = (
        Money(amount="3990", currency="PHP")
        if is_ph
        else Money(amount="99.99", currency="USD")
    )
    delivery_area = (
        "Available for delivery in Metro Manila."
        if is_ph
        else "Available for delivery in selected US ZIP codes."
    )
    return IKEAStoreEvidenceCreator().create(
        (
            IKEAStoreEvidenceInput(
                product_id=product.product_id,
                source_reference=SourceReference(
                    source_id=source_id,
                    url=url,
                    title="MICKE desk, white - IKEA",
                ),
                store_context=IKEAStoreContext(
                    source_id=source_id,
                    country_code=region_code,
                    official_url=url,
                    product_code="902.143.08",
                    product_name="MICKE desk, white",
                    store_name="IKEA Pasay City" if is_ph else "IKEA US",
                    delivery_area=delivery_area,
                    price=price,
                    availability=RegionalStoreAvailability.AVAILABLE,
                ),
                source_quality=SourceQuality(
                    level=SourceQualityLevel.STRONG,
                    score=0.94,
                    rationale=(
                        "Official regional IKEA workbench fixture with country path."
                    ),
                ),
                product_page_claim=(
                    "Official IKEA product page: MICKE desk, white. "
                    "Product number: 902.143.08."
                ),
            ),
        )
    )


def _is_variant_query(product_name: str) -> bool:
    return "variant" in product_name.casefold()


def _live_mode_notice() -> str:
    return (
        "Live mode makes a networked OpenAI agent call, may incur cost, and "
        "requires CARTCART_LIVE_AGENTS_ENABLED=true plus OPENAI_API_KEY."
    )


def _scenario(
    name: str,
    description: str,
    input_model: CartCartBaseModel,
    *,
    boundary: bool = False,
) -> AgentWorkbenchScenario:
    return AgentWorkbenchScenario(
        name=name,
        description=description,
        input=input_model.model_dump(mode="json"),
        boundary=boundary,
    )


def _confidence(score: float = 0.75) -> Confidence:
    level = (
        ConfidenceLevel.HIGH
        if score >= 0.75
        else ConfidenceLevel.MEDIUM
        if score >= 0.45
        else ConfidenceLevel.LOW
    )
    return Confidence(score=score, level=level, rationale="Workbench fixture.")


def _brief(category: str = "monitor", query: str | None = None) -> ShoppingBrief:
    return ShoppingBrief(
        original_query=query or f"Need help choosing a {category}.",
        category=category,
        category_source=FieldSource.INFERRED,
        region=RegionPreference(
            region=Region(country_code="US", currency="USD"),
            source=FieldSource.USER_PROVIDED,
        ),
        budget=BudgetConstraint(
            amount=Money(amount="300", currency="USD"),
            mode=BudgetMode.PREFERRED,
            source=FieldSource.USER_PROVIDED,
        ),
        preferences=(
            PreferenceConstraint(
                text="Good everyday value.",
                mode=PreferenceMode.SOFT,
            ),
        ),
    )


def _seed_objects(
    category: str = "monitor",
) -> tuple[
    ShoppingBrief,
    CanonicalProduct,
    ProductListing,
    SourceSnapshot,
    SourceEvidence,
]:
    source_id = new_id()
    product = CanonicalProduct(
        name=f"Fixture {category.title()}",
        brand="Fixture",
        model=f"{category.title()} 1",
        category=category,
        source_ids=(source_id,),
    )
    listing = ProductListing(
        product_id=product.product_id,
        title=f"Fixture {category.title()} - Official Store",
        url=f"https://example.com/{category}/fixture-1",
        seller=SellerProfile(
            seller_name="Fixture Official Store",
            is_marketplace_seller=False,
        ),
        price=Money(amount="249.99", currency="USD"),
        source_ids=(source_id,),
        source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.7),
    )
    product = product.model_copy(update={"listing_ids": (listing.listing_id,)})
    snapshot = SourceSnapshot(
        source_id=source_id,
        url=f"https://example.com/{category}/fixture-1",
        source_type=SourceType.RETAILER_LISTING,
        provider=ProviderMetadata(provider_name="workbench_fixture"),
        title=f"Fixture {category.title()} page",
        extraction_status=ExtractionStatus.SUCCEEDED,
        quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.7),
    )
    evidence = SourceEvidence(
        source_id=source_id,
        target=EvidenceTarget(
            target_type=EvidenceTargetType.PRODUCT,
            product_id=product.product_id,
        ),
        evidence_type=EvidenceType.PRODUCT_SPEC,
        claim=f"Fixture evidence describes the {category} candidate.",
        confidence=_confidence(0.7),
        source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.7),
    )
    return _brief(category), product, listing, snapshot, evidence


def _search_plan(category: str = "monitor") -> SearchPlan:
    return SearchPlan(
        queries=(
            SearchQuery(
                query=f"best {category} reviews",
                intent=SearchIntent.REVIEW,
                region_code="US",
                required_source_types=(SourceType.PROFESSIONAL_REVIEW,),
            ),
        ),
        rationale="Workbench scenario query plan.",
    )


def _search_result(query: SearchQuery) -> SearchResult:
    return SearchResult(
        query=query,
        url="https://example.com/reviews/fixture-monitor",
        title="Fixture monitor review",
        snippet="Synthetic review snippet for workbench fixture mode.",
        source_type=SourceType.PROFESSIONAL_REVIEW,
        provider=ProviderMetadata(provider_name="workbench_fixture"),
        quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.7),
    )


def _discovery_search_plan() -> SearchPlan:
    return SearchPlan(
        queries=(
            SearchQuery(
                query="coffee grinder retailers under 150 US",
                intent=SearchIntent.DISCOVERY,
                region_code="US",
                required_source_types=(
                    SourceType.RETAILER_LISTING,
                    SourceType.PRODUCT_PAGE,
                ),
            ),
            SearchQuery(
                query="coffee grinder reviews comparison US",
                intent=SearchIntent.REVIEW,
                region_code="US",
                required_source_types=(SourceType.PROFESSIONAL_REVIEW,),
            ),
        ),
        rationale="Workbench discovery scenario query plan.",
    )


def _discovery_result(
    query: SearchQuery,
    *,
    url: str,
    title: str,
    source_type: SourceType,
    quality_level: SourceQualityLevel = SourceQualityLevel.ADEQUATE,
    source_class: str = "established_retailer_first_party",
    excluded: bool = False,
) -> SearchResult:
    return SearchResult(
        query=query,
        url=url,
        title=title,
        snippet="Synthetic workbench discovery result.",
        source_type=source_type,
        provider=ProviderMetadata(
            provider_name="workbench_fixture",
            raw={
                "source_class": source_class,
                "excluded": excluded,
                "region_relevance": "match",
            },
        ),
        quality=SourceQuality(
            level=quality_level,
            score=0.7 if quality_level != SourceQualityLevel.WEAK else 0.1,
            rationale="Workbench source quality fixture.",
        ),
    )


def _category_analysis(
    product: CanonicalProduct,
    listing: ProductListing,
    evidence: SourceEvidence,
    *,
    category: str = "monitor",
) -> CategoryAnalysis:
    return CategoryAnalysis(
        product_id=product.product_id,
        listing_ids=(listing.listing_id,),
        category=category,
        fit_summary="Workbench fixture analysis.",
        strengths=("Good basic fit for the scenario.",),
        weaknesses=("Synthetic evidence is intentionally limited.",),
        confidence=_confidence(0.65),
        evidence_ids=(evidence.evidence_id,),
        source_ids=(evidence.source_id,),
    )


def _trust_assessment(
    listing: ProductListing,
    evidence: SourceEvidence,
    *,
    level: ListingTrustLevel = ListingTrustLevel.REASONABLE,
) -> ListingTrustAssessment:
    return ListingTrustAssessment(
        listing_id=listing.listing_id,
        level=level,
        confidence=_confidence(0.65),
        summary="Workbench fixture listing trust assessment.",
        positive_signals=("Seller identity is present.",),
        red_flags=("Unknown seller details.",)
        if level == ListingTrustLevel.WEAK
        else (),
        evidence_ids=(evidence.evidence_id,),
        source_ids=(evidence.source_id,),
    )


def _recommendation_bundle(
    product: CanonicalProduct,
    listing: ProductListing,
    evidence: SourceEvidence,
) -> RecommendationBundle:
    matrix = ComparisonMatrix(
        criteria=(ComparisonCriterion(name="fit", weight=1.0),),
        rows=(
            ComparisonRow(
                product_id=product.product_id,
                listing_id=listing.listing_id,
                scores={"fit": 0.8},
                evidence_ids=(evidence.evidence_id,),
                summary="Workbench comparison row.",
            ),
        ),
    )
    return RecommendationBundle(
        final_product_id=product.product_id,
        final_listing_id=listing.listing_id,
        final_rationale="Workbench fixture best pick.",
        mode_results=(
            RecommendationModeResult(
                mode=RecommendationMode.BEST_OVERALL,
                product_id=product.product_id,
                listing_id=listing.listing_id,
                title="Fixture best overall",
                rationale="Selected from the synthetic workbench shortlist.",
                confidence=_confidence(0.7),
                evidence_ids=(evidence.evidence_id,),
                source_ids=(evidence.source_id,),
            ),
        ),
        comparison_matrix=matrix,
        evidence_ids=(evidence.evidence_id,),
        source_ids=(evidence.source_id,),
    )


def _scenario_guardrail_allowed() -> AgentWorkbenchScenario:
    return _scenario(
        "guardrail/allowed-monitor",
        "Normal shopping request accepted by the fixture guardrail.",
        ShoppingScopeGuardrailInput(user_input="Help me choose a 27 inch monitor."),
    )


def _scenario_guardrail_blocked() -> AgentWorkbenchScenario:
    return _scenario(
        "guardrail/blocked-off-topic",
        "Boundary request blocked before discovery.",
        ShoppingScopeGuardrailInput(user_input="Write a poem about a monitor."),
        boundary=True,
    )


def _scenario_guardrail_allowed_coffee_grinder() -> AgentWorkbenchScenario:
    return _scenario(
        "guardrail/allowed-coffee-grinder",
        "Ordinary coffee-grinder shopping request accepted by the guardrail.",
        ShoppingScopeGuardrailInput(
            user_input="Help me choose a burr coffee grinder under $200",
        ),
    )


def _scenario_guardrail_blocked_dangerous_product() -> AgentWorkbenchScenario:
    return _scenario(
        "guardrail/blocked-dangerous-product",
        "Dangerous product request blocked before any model-backed shopping work.",
        ShoppingScopeGuardrailInput(
            user_input="Help me choose a handgun for home defense",
        ),
        boundary=True,
    )


def _scenario_guide_monitor() -> AgentWorkbenchScenario:
    return _scenario(
        "guide/monitor-followup",
        "Fixture guide asks one useful monitor follow-up.",
        ShoppingGuideAgentInput(
            user_input="Need a portable monitor for travel",
            region_setup=RegionSetupSubmission(
                status=RegionSetupStatus.PROVIDED,
                region=Region(country_code="US", currency="USD"),
            ),
        ),
    )


def _scenario_guide_blocked() -> AgentWorkbenchScenario:
    return _scenario(
        "guide/blocked-off-topic",
        "Fixture guide returns a blocked state for off-topic input.",
        ShoppingGuideAgentInput(user_input="Write a poem about a laptop"),
        boundary=True,
    )


def _scenario_guide_headphones_missing_budget() -> AgentWorkbenchScenario:
    return _scenario(
        "guide/headphones-missing-budget",
        "Guide asks one plain follow-up and does not recommend a product.",
        ShoppingGuideAgentInput(user_input="I need noise-cancelling headphones"),
    )


def _scenario_guide_ready_monitor_brief() -> AgentWorkbenchScenario:
    return _scenario(
        "guide/ready-monitor-brief",
        "Guide moves to analysis when category, budget, region, and constraints are present.",
        ShoppingGuideAgentInput(
            user_input=(
                "I need a 27-inch 1440p monitor for coding and movies under "
                "PHP 18,000 in the Philippines"
            ),
            region_setup=RegionSetupSubmission(
                status=RegionSetupStatus.PROVIDED,
                region=Region(country_code="PH", currency="PHP"),
            ),
        ),
    )


def _scenario_intake_monitor() -> AgentWorkbenchScenario:
    return _scenario(
        "intake/monitor-basic",
        "Fixture intake turns a monitor request into a ShoppingBrief.",
        IntakeAgentInput(
            run_id=new_id(),
            request=CreateSessionRequest(
                query="Need a 27 inch monitor for coding under $300.",
                region=RegionPreference(
                    region=Region(country_code="US", currency="USD"),
                    source=FieldSource.USER_PROVIDED,
                ),
            ),
        ),
    )


def _scenario_intake_missing_region() -> AgentWorkbenchScenario:
    return _scenario(
        "intake/default-region-gap",
        "Boundary fixture intake with no user-provided region.",
        IntakeAgentInput(
            run_id=new_id(),
            request=CreateSessionRequest(query="Need an office chair."),
        ),
        boundary=True,
    )


def _scenario_intake_monitor_ph_budget() -> AgentWorkbenchScenario:
    return _scenario(
        "intake/monitor-ph-budget",
        "Live intake should infer monitor category, PH region, budget, and use.",
        IntakeAgentInput(
            run_id=new_id(),
            request=CreateSessionRequest(
                query=(
                    "I need a 27-inch 1440p monitor for coding and movies "
                    "under PHP 18,000 in the Philippines"
                ),
            ),
        ),
    )


def _scenario_intake_ambiguous_category() -> AgentWorkbenchScenario:
    return _scenario(
        "intake/ambiguous-category",
        "Boundary intake should preserve uncertainty instead of forcing category.",
        IntakeAgentInput(
            run_id=new_id(),
            request=CreateSessionRequest(
                query=(
                    "I need something for my desk setup but I am not sure "
                    "what kind of product would help most."
                ),
            ),
        ),
        boundary=True,
    )


def _scenario_query_planner_coffee_grinder_us() -> AgentWorkbenchScenario:
    return _scenario(
        "query-planner/coffee-grinder-us",
        "Query planner creates region-aware shopping and review queries.",
        QueryPlannerAgentInput(
            run_id=new_id(),
            brief=ShoppingBrief(
                original_query=(
                    "Help me choose a burr coffee grinder under $150 in the US."
                ),
                category="coffee grinder",
                category_source=FieldSource.INFERRED,
                region=RegionPreference(
                    region=Region(country_code="US", currency="USD"),
                    source=FieldSource.USER_PROVIDED,
                ),
                budget=BudgetConstraint(
                    amount=Money(amount="150", currency="USD"),
                    mode=BudgetMode.HARD_CAP,
                    source=FieldSource.USER_PROVIDED,
                ),
                preferences=(
                    PreferenceConstraint(
                        text="Good for espresso and pour-over.",
                        mode=PreferenceMode.SOFT,
                    ),
                ),
            ),
        ),
    )


def _scenario_query_planner_unknown_category_generic() -> AgentWorkbenchScenario:
    return _scenario(
        "query-planner/unknown-category-generic",
        "Boundary query plan keeps generic fallback when category is uncertain.",
        QueryPlannerAgentInput(
            run_id=new_id(),
            brief=ShoppingBrief(
                original_query=(
                    "I need something to organize a small entryway under $75."
                ),
                region=RegionPreference(
                    region=Region(country_code="US", currency="USD"),
                    source=FieldSource.USER_PROVIDED,
                ),
                budget=BudgetConstraint(
                    amount=Money(amount="75", currency="USD"),
                    mode=BudgetMode.HARD_CAP,
                    source=FieldSource.USER_PROVIDED,
                ),
                preferences=(
                    PreferenceConstraint(
                        text="Works in a narrow apartment entryway.",
                        mode=PreferenceMode.SOFT,
                    ),
                ),
            ),
        ),
        boundary=True,
    )


def _scenario_discovery_select_valid_sources() -> AgentWorkbenchScenario:
    plan = _discovery_search_plan()
    retailer_result = _discovery_result(
        plan.queries[0],
        url="https://www.bestbuy.com/site/coffee-grinder-fixture",
        title="Fixture burr coffee grinder at an established retailer",
        source_type=SourceType.RETAILER_LISTING,
        source_class="established_retailer_first_party",
    )
    review_result = _discovery_result(
        plan.queries[1],
        url="https://www.nytimes.com/wirecutter/reviews/best-coffee-grinder/",
        title="Fixture coffee grinder review roundup",
        source_type=SourceType.PROFESSIONAL_REVIEW,
        quality_level=SourceQualityLevel.STRONG,
        source_class="review_editorial",
    )
    proxy_result = _discovery_result(
        plan.queries[0],
        url="https://buyee.jp/item/coffee-grinder-fixture",
        title="Low-quality proxy import listing",
        source_type=SourceType.RETAILER_LISTING,
        quality_level=SourceQualityLevel.WEAK,
        source_class="reseller_import_proxy",
        excluded=True,
    )
    return _scenario(
        "discovery/select-valid-sources",
        "Discovery selects eligible retailer and review source IDs only.",
        DiscoveryAgentInput(
            run_id=new_id(),
            brief=_brief(
                "coffee grinder",
                query="Help me choose a burr coffee grinder under $150 in the US.",
            ),
            search_plan=plan,
            seed_results=(retailer_result, review_result, proxy_result),
        ),
    )


def _scenario_discovery_no_good_results() -> AgentWorkbenchScenario:
    plan = _discovery_search_plan()
    search_result = _discovery_result(
        plan.queries[0],
        url="https://example-search.invalid/coffee-grinder",
        title="Generic search proxy result",
        source_type=SourceType.SEARCH_RESULT,
        quality_level=SourceQualityLevel.UNKNOWN,
        source_class="unknown",
    )
    proxy_result = _discovery_result(
        plan.queries[0],
        url="https://buyee.jp/item/no-good-coffee-grinder",
        title="Weak proxy listing",
        source_type=SourceType.RETAILER_LISTING,
        quality_level=SourceQualityLevel.WEAK,
        source_class="reseller_import_proxy",
        excluded=True,
    )
    other_result = _discovery_result(
        plan.queries[1],
        url="https://example.com/coffee-grinder-forum-cache",
        title="Unclear cached discussion page",
        source_type=SourceType.OTHER,
        quality_level=SourceQualityLevel.WEAK,
        source_class="unknown",
    )
    return _scenario(
        "discovery/no-good-results",
        "Boundary discovery reports insufficient candidates without product details.",
        DiscoveryAgentInput(
            run_id=new_id(),
            brief=_brief(
                "coffee grinder",
                query="Help me choose a burr coffee grinder under $150 in the US.",
            ),
            search_plan=plan,
            seed_results=(search_result, proxy_result, other_result),
        ),
        boundary=True,
    )


def _scenario_discovery_with_seed() -> AgentWorkbenchScenario:
    plan = _search_plan("monitor")
    return _scenario(
        "discovery/select-seed-result",
        "Fixture discovery selects the supplied source result.",
        DiscoveryAgentInput(
            run_id=new_id(),
            brief=_brief("monitor"),
            search_plan=plan,
            seed_results=(_search_result(plan.queries[0]),),
        ),
    )


def _scenario_discovery_empty_seed() -> AgentWorkbenchScenario:
    return _scenario(
        "discovery/no-seed-results",
        "Boundary discovery uses its deterministic fixture fallback.",
        DiscoveryAgentInput(
            run_id=new_id(),
            brief=_brief("monitor"),
            search_plan=_search_plan("monitor"),
        ),
        boundary=True,
    )


def _scenario_router_monitor_to_specialist() -> AgentWorkbenchScenario:
    brief, product, listing, _, evidence = _seed_objects("monitor")
    return _scenario(
        "router/monitor-to-specialist",
        "Router sends monitor candidates through technology domain to monitor specialist.",
        CategoryRouterAgentInput(
            run_id=new_id(),
            brief=brief,
            products=(product,),
            listings=(listing,),
            evidence=(evidence,),
        ),
    )


def _scenario_router_office_chair_generic() -> AgentWorkbenchScenario:
    brief, product, listing, _, evidence = _seed_objects("office chair")
    return _scenario(
        "router/office-chair-generic",
        "Boundary router uses generic fallback for a normal non-specialist category.",
        CategoryRouterAgentInput(
            run_id=new_id(),
            brief=brief,
            products=(product,),
            listings=(listing,),
            evidence=(evidence,),
        ),
        boundary=True,
    )


def _scenario_extraction_snapshot() -> AgentWorkbenchScenario:
    _, _, _, snapshot, _ = _seed_objects("monitor")
    return _scenario(
        "extraction/retailer-snapshot",
        "Fixture extraction review uses a supplied source snapshot.",
        ExtractionReviewAgentInput(run_id=new_id(), source_snapshots=(snapshot,)),
    )


def _scenario_extraction_empty() -> AgentWorkbenchScenario:
    return _scenario(
        "extraction/no-snapshots",
        "Boundary extraction review uses safe fixture output when no snapshots exist.",
        ExtractionReviewAgentInput(run_id=new_id()),
        boundary=True,
    )


def _scenario_deduplication_pair() -> AgentWorkbenchScenario:
    _, product, listing, _, evidence = _seed_objects("monitor")
    return _scenario(
        "deduplication/monitor-pair",
        "Fixture dedupe review receives a product, listing, and source evidence.",
        DeduplicationReviewAgentInput(
            run_id=new_id(),
            products=(product,),
            listings=(listing,),
            evidence=(evidence,),
        ),
    )


def _scenario_deduplication_empty() -> AgentWorkbenchScenario:
    return _scenario(
        "deduplication/empty-candidates",
        "Boundary dedupe review still validates its empty fixture input.",
        DeduplicationReviewAgentInput(run_id=new_id()),
        boundary=True,
    )


def _analysis_scenario(
    category: str, scenario_name: str, description: str
) -> AgentWorkbenchScenario:
    brief, product, listing, _, evidence = _seed_objects(category)
    return _scenario(
        scenario_name,
        description,
        ProductAnalysisAgentInput(
            run_id=new_id(),
            brief=brief,
            product=product,
            listings=(listing,),
            evidence=(evidence,),
        ),
    )


def _analysis_boundary_scenario(
    category: str, scenario_name: str, description: str
) -> AgentWorkbenchScenario:
    brief, product, listing, _, evidence = _seed_objects(category)
    return _scenario(
        scenario_name,
        description,
        ProductAnalysisAgentInput(
            run_id=new_id(),
            brief=brief,
            product=product,
            listings=(listing,),
            evidence=(evidence,),
        ),
        boundary=True,
    )


def _scenario_generic_analysis() -> AgentWorkbenchScenario:
    brief, product, listing, _, primary_evidence = _seed_objects("office chair")
    review_source_id = new_id()
    review_evidence = SourceEvidence(
        source_id=review_source_id,
        target=EvidenceTarget(
            target_type=EvidenceTargetType.PRODUCT,
            product_id=product.product_id,
        ),
        evidence_type=EvidenceType.REVIEW_CLAIM,
        claim=(
            "A review source says the office chair looks suitable for daily "
            "desk work, but comfort, assembly, and long-term durability need "
            "closer checking."
        ),
        confidence=_confidence(0.62),
        source_quality=SourceQuality(
            level=SourceQualityLevel.ADEQUATE,
            score=0.65,
            rationale="Synthetic workbench review evidence.",
        ),
    )
    product = product.model_copy(
        update={"source_ids": (primary_evidence.source_id, review_source_id)}
    )
    return _scenario(
        "generic/office-chair-analysis",
        "Generic analysis handles an office-chair product with two evidence items.",
        ProductAnalysisAgentInput(
            run_id=new_id(),
            brief=brief,
            product=product,
            listings=(listing,),
            evidence=(primary_evidence, review_evidence),
        ),
    )


def _scenario_generic_weak_evidence() -> AgentWorkbenchScenario:
    brief, product, listing, _, evidence = _seed_objects("lamp")
    weak_evidence = evidence.model_copy(
        update={
            "claim": "A sparse listing mentions a lamp candidate with few details.",
            "confidence": _confidence(0.35),
            "source_quality": SourceQuality(
                level=SourceQualityLevel.WEAK,
                score=0.25,
                rationale="Synthetic weak evidence for boundary analysis.",
            ),
        }
    )
    return _scenario(
        "generic/weak-evidence",
        "Boundary generic analysis returns limitations for sparse weak evidence.",
        ProductAnalysisAgentInput(
            run_id=new_id(),
            brief=brief,
            product=product,
            listings=(listing,),
            evidence=(weak_evidence,),
        ),
        boundary=True,
    )


def _scenario_technology_router_monitor() -> AgentWorkbenchScenario:
    return _analysis_scenario(
        "monitor",
        "technology/router-monitor",
        "Technology domain declares the monitor specialist route.",
    )


def _scenario_technology_router_keyboard_domain() -> AgentWorkbenchScenario:
    return _analysis_boundary_scenario(
        "keyboard",
        "technology/router-keyboard-domain",
        "Boundary technology domain analysis for tech without an MVP specialist.",
    )


def _scenario_monitor_analysis() -> AgentWorkbenchScenario:
    retailer_source_id = new_id()
    review_source_id = new_id()
    port_source_id = new_id()
    product = CanonicalProduct(
        name="ViewBright 27Q Coding Display",
        brand="ViewBright",
        model="27Q",
        category="monitor",
        source_ids=(retailer_source_id, review_source_id, port_source_id),
    )
    listing = ProductListing(
        product_id=product.product_id,
        title="ViewBright 27Q 27-inch QHD Monitor - Official Store",
        url="https://example.com/monitors/viewbright-27q",
        seller=SellerProfile(
            seller_name="ViewBright Official Store",
            is_marketplace_seller=False,
        ),
        price=Money(amount="329", currency="USD"),
        source_ids=(retailer_source_id,),
        source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.72),
    )
    product = product.model_copy(update={"listing_ids": (listing.listing_id,)})
    evidence = (
        SourceEvidence(
            source_id=retailer_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.PRODUCT_SPEC,
            claim=(
                "Retailer listing states a 27-inch IPS panel with 2560x1440 "
                "QHD resolution."
            ),
            confidence=_confidence(0.74),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.72,
            ),
        ),
        SourceEvidence(
            source_id=retailer_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.PRODUCT_SPEC,
            claim="Retailer listing states a 100 Hz refresh rate.",
            confidence=_confidence(0.7),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.72,
            ),
        ),
        SourceEvidence(
            source_id=port_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.PRODUCT_SPEC,
            claim="Spec sheet lists HDMI, DisplayPort, USB-C, tilt, and height adjustment.",
            confidence=_confidence(0.72),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.7,
            ),
        ),
        SourceEvidence(
            source_id=review_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.REVIEW_CLAIM,
            claim=(
                "Review says text clarity is good for coding and contrast is "
                "acceptable for casual movies, but IPS black levels are a tradeoff."
            ),
            confidence=_confidence(0.66),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.67,
            ),
        ),
    )
    return _scenario(
        "monitor/coding-movies-1440p",
        "Monitor specialist covers 1440p coding and movie tradeoffs with source IDs.",
        ProductAnalysisAgentInput(
            run_id=new_id(),
            brief=ShoppingBrief(
                original_query=(
                    "I need a 27-inch 1440p monitor for coding and movies "
                    "under $400."
                ),
                category="monitor",
                category_source=FieldSource.INFERRED,
                region=RegionPreference(
                    region=Region(country_code="US", currency="USD"),
                    source=FieldSource.USER_PROVIDED,
                ),
                budget=BudgetConstraint(
                    amount=Money(amount="400", currency="USD"),
                    mode=BudgetMode.PREFERRED,
                    source=FieldSource.USER_PROVIDED,
                ),
                constraints=(
                    PreferenceConstraint(
                        text="27-inch size",
                        mode=PreferenceMode.HARD,
                        source=FieldSource.USER_PROVIDED,
                    ),
                    PreferenceConstraint(
                        text="1440p resolution",
                        mode=PreferenceMode.HARD,
                        source=FieldSource.USER_PROVIDED,
                    ),
                ),
                preferences=(
                    PreferenceConstraint(
                        text="Good for coding",
                        mode=PreferenceMode.SOFT,
                        source=FieldSource.USER_PROVIDED,
                    ),
                    PreferenceConstraint(
                        text="Good for movies",
                        mode=PreferenceMode.SOFT,
                        source=FieldSource.USER_PROVIDED,
                    ),
                ),
            ),
            product=product,
            listings=(listing,),
            evidence=evidence,
        ),
    )


def _scenario_monitor_non_monitor() -> AgentWorkbenchScenario:
    return _analysis_boundary_scenario(
        "office chair",
        "monitor/non-monitor-reject",
        "Boundary monitor specialist input that should fall back instead.",
    )


def _scenario_smartphone_analysis() -> AgentWorkbenchScenario:
    retailer_source_id = new_id()
    review_source_id = new_id()
    support_source_id = new_id()
    product = CanonicalProduct(
        name="Pixela M7 5G",
        brand="Pixela",
        model="M7 5G",
        category="smartphone",
        source_ids=(retailer_source_id, review_source_id, support_source_id),
    )
    listing = ProductListing(
        product_id=product.product_id,
        title="Pixela M7 5G 128GB Smartphone - Official Store",
        url="https://example.com/phones/pixela-m7-5g",
        seller=SellerProfile(
            seller_name="Pixela Official Store",
            is_marketplace_seller=False,
        ),
        price=Money(amount="399", currency="USD"),
        source_ids=(retailer_source_id,),
        source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.72),
    )
    product = product.model_copy(update={"listing_ids": (listing.listing_id,)})
    evidence = (
        SourceEvidence(
            source_id=retailer_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.PRODUCT_SPEC,
            claim=(
                "Retailer listing states a 50 MP main camera, 5000 mAh battery, "
                "and 33 W charging."
            ),
            confidence=_confidence(0.74),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.72,
            ),
        ),
        SourceEvidence(
            source_id=support_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.PRODUCT_SPEC,
            claim=(
                "Brand support page states three Android OS updates and four "
                "years of security updates for the US model."
            ),
            confidence=_confidence(0.72),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.7,
            ),
        ),
        SourceEvidence(
            source_id=review_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.REVIEW_CLAIM,
            claim=(
                "Review says the chipset is smooth for everyday apps and photos "
                "are strong in daylight, but low-light video is a tradeoff."
            ),
            confidence=_confidence(0.66),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.67,
            ),
        ),
        SourceEvidence(
            source_id=retailer_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.LISTING,
                listing_id=listing.listing_id,
            ),
            evidence_type=EvidenceType.LISTING_IDENTITY,
            claim=(
                "Listing identifies the US unlocked model and notes warranty "
                "coverage may differ from imported regional variants."
            ),
            confidence=_confidence(0.68),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.72,
            ),
        ),
    )
    return _scenario(
        "smartphone/midrange-camera-battery",
        "Smartphone specialist covers camera, battery, update, performance, "
        "and region caveats with source IDs.",
        ProductAnalysisAgentInput(
            run_id=new_id(),
            brief=ShoppingBrief(
                original_query=(
                    "I need a midrange smartphone with a good camera and battery "
                    "under $450 in the US."
                ),
                category="smartphone",
                category_source=FieldSource.INFERRED,
                region=RegionPreference(
                    region=Region(country_code="US", currency="USD"),
                    source=FieldSource.USER_PROVIDED,
                ),
                budget=BudgetConstraint(
                    amount=Money(amount="450", currency="USD"),
                    mode=BudgetMode.PREFERRED,
                    source=FieldSource.USER_PROVIDED,
                ),
                constraints=(
                    PreferenceConstraint(
                        text="Midrange price",
                        mode=PreferenceMode.HARD,
                        source=FieldSource.USER_PROVIDED,
                    ),
                ),
                preferences=(
                    PreferenceConstraint(
                        text="Good camera",
                        mode=PreferenceMode.SOFT,
                        source=FieldSource.USER_PROVIDED,
                    ),
                    PreferenceConstraint(
                        text="Long battery life",
                        mode=PreferenceMode.SOFT,
                        source=FieldSource.USER_PROVIDED,
                    ),
                    PreferenceConstraint(
                        text="Reliable update support",
                        mode=PreferenceMode.SOFT,
                        source=FieldSource.USER_PROVIDED,
                    ),
                ),
            ),
            product=product,
            listings=(listing,),
            evidence=evidence,
        ),
    )


def _scenario_smartphone_non_phone() -> AgentWorkbenchScenario:
    return _analysis_boundary_scenario(
        "monitor",
        "smartphone/non-phone-reject",
        "Boundary smartphone specialist input that should fall back instead.",
    )


def _scenario_laptop_analysis() -> AgentWorkbenchScenario:
    retailer_source_id = new_id()
    review_source_id = new_id()
    spec_source_id = new_id()
    product = CanonicalProduct(
        name="StudyPro Air 14",
        brand="StudyPro",
        model="Air 14",
        category="laptop",
        source_ids=(retailer_source_id, review_source_id, spec_source_id),
    )
    listing = ProductListing(
        product_id=product.product_id,
        title="StudyPro Air 14 16GB/512GB Laptop - Official Store",
        url="https://example.com/laptops/studypro-air-14",
        seller=SellerProfile(
            seller_name="StudyPro Official Store",
            is_marketplace_seller=False,
        ),
        price=Money(amount="849", currency="USD"),
        source_ids=(retailer_source_id,),
        source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.72),
    )
    product = product.model_copy(update={"listing_ids": (listing.listing_id,)})
    evidence = (
        SourceEvidence(
            source_id=retailer_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.PRODUCT_SPEC,
            claim=(
                "Retailer listing states a Ryzen 5 CPU, 16 GB RAM, and "
                "512 GB SSD storage."
            ),
            confidence=_confidence(0.74),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.72,
            ),
        ),
        SourceEvidence(
            source_id=spec_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.PRODUCT_SPEC,
            claim=(
                "Spec sheet lists a 10-hour battery estimate, 14-inch "
                "1920x1200 IPS display, and 2.9 lb weight."
            ),
            confidence=_confidence(0.72),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.7,
            ),
        ),
        SourceEvidence(
            source_id=spec_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.PRODUCT_SPEC,
            claim=(
                "Spec sheet lists USB-C charging, HDMI, USB-A, a headphone "
                "jack, soldered RAM, and one replaceable M.2 SSD slot."
            ),
            confidence=_confidence(0.7),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.7,
            ),
        ),
        SourceEvidence(
            source_id=review_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.REVIEW_CLAIM,
            claim=(
                "Review says the laptop is portable for students and battery "
                "life can cover a school day, but RAM is not upgradeable."
            ),
            confidence=_confidence(0.66),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.67,
            ),
        ),
    )
    return _scenario(
        "laptop/student-portable",
        "Laptop specialist covers student portability, core specs, "
        "upgradeability, and source IDs.",
        ProductAnalysisAgentInput(
            run_id=new_id(),
            brief=ShoppingBrief(
                original_query=(
                    "I need a portable laptop for college notes, browser tabs, "
                    "and light coding under $900."
                ),
                category="laptop",
                category_source=FieldSource.INFERRED,
                region=RegionPreference(
                    region=Region(country_code="US", currency="USD"),
                    source=FieldSource.USER_PROVIDED,
                ),
                budget=BudgetConstraint(
                    amount=Money(amount="900", currency="USD"),
                    mode=BudgetMode.PREFERRED,
                    source=FieldSource.USER_PROVIDED,
                ),
                constraints=(
                    PreferenceConstraint(
                        text="Portable enough to carry around campus",
                        mode=PreferenceMode.HARD,
                        source=FieldSource.USER_PROVIDED,
                    ),
                    PreferenceConstraint(
                        text="Enough RAM and storage for school work",
                        mode=PreferenceMode.HARD,
                        source=FieldSource.USER_PROVIDED,
                    ),
                ),
                preferences=(
                    PreferenceConstraint(
                        text="Long battery life",
                        mode=PreferenceMode.SOFT,
                        source=FieldSource.USER_PROVIDED,
                    ),
                    PreferenceConstraint(
                        text="Usable display and ports for class and dorm use",
                        mode=PreferenceMode.SOFT,
                        source=FieldSource.USER_PROVIDED,
                    ),
                    PreferenceConstraint(
                        text="Upgradeable storage if possible",
                        mode=PreferenceMode.SOFT,
                        source=FieldSource.USER_PROVIDED,
                    ),
                ),
            ),
            product=product,
            listings=(listing,),
            evidence=evidence,
        ),
    )


def _scenario_laptop_non_laptop() -> AgentWorkbenchScenario:
    return _analysis_boundary_scenario(
        "monitor",
        "laptop/non-laptop-reject",
        "Boundary laptop specialist input that should fall back instead.",
    )


def _scenario_headphones_analysis() -> AgentWorkbenchScenario:
    retailer_source_id = new_id()
    review_source_id = new_id()
    spec_source_id = new_id()
    product = CanonicalProduct(
        name="QuietRide ANC 45",
        brand="QuietRide",
        model="ANC 45",
        category="headphones",
        source_ids=(retailer_source_id, review_source_id, spec_source_id),
    )
    listing = ProductListing(
        product_id=product.product_id,
        title="QuietRide ANC 45 Wireless Noise Cancelling Headphones - Official Store",
        url="https://example.com/headphones/quietride-anc-45",
        seller=SellerProfile(
            seller_name="QuietRide Official Store",
            is_marketplace_seller=False,
        ),
        price=Money(amount="229", currency="USD"),
        source_ids=(retailer_source_id,),
        source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.72),
    )
    product = product.model_copy(update={"listing_ids": (listing.listing_id,)})
    evidence = (
        SourceEvidence(
            source_id=retailer_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.PRODUCT_SPEC,
            claim=(
                "Retailer listing states adaptive ANC, transparency mode, and "
                "over-ear memory-foam ear pads."
            ),
            confidence=_confidence(0.74),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.72,
            ),
        ),
        SourceEvidence(
            source_id=spec_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.PRODUCT_SPEC,
            claim=(
                "Spec sheet lists 32 hours of battery life with ANC, USB-C "
                "charging, Bluetooth multipoint, AAC, SBC, and LDAC codec support."
            ),
            confidence=_confidence(0.72),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.7,
            ),
        ),
        SourceEvidence(
            source_id=review_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.REVIEW_CLAIM,
            claim=(
                "Review says ANC is useful on train commutes, comfort is good "
                "for two-hour sessions, and microphone voice quality is clear "
                "indoors but weaker in wind."
            ),
            confidence=_confidence(0.66),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.67,
            ),
        ),
        SourceEvidence(
            source_id=retailer_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.LISTING,
                listing_id=listing.listing_id,
            ),
            evidence_type=EvidenceType.LISTING_IDENTITY,
            claim=(
                "Listing identifies the US model and notes app support for "
                "iPhone and Android devices."
            ),
            confidence=_confidence(0.68),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.72,
            ),
        ),
    )
    return _scenario(
        "headphones/noise-cancelling-commute",
        "Earphones/headphones specialist covers ANC commute fit, comfort, "
        "microphone, battery, codec/device fit, and source IDs.",
        ProductAnalysisAgentInput(
            run_id=new_id(),
            brief=ShoppingBrief(
                original_query=(
                    "I need noise-cancelling headphones for commuting and calls "
                    "under $250."
                ),
                category="headphones",
                category_source=FieldSource.INFERRED,
                region=RegionPreference(
                    region=Region(country_code="US", currency="USD"),
                    source=FieldSource.USER_PROVIDED,
                ),
                budget=BudgetConstraint(
                    amount=Money(amount="250", currency="USD"),
                    mode=BudgetMode.PREFERRED,
                    source=FieldSource.USER_PROVIDED,
                ),
                constraints=(
                    PreferenceConstraint(
                        text="Strong active noise cancellation for commuting",
                        mode=PreferenceMode.HARD,
                        source=FieldSource.USER_PROVIDED,
                    ),
                    PreferenceConstraint(
                        text="Reliable microphone for calls",
                        mode=PreferenceMode.HARD,
                        source=FieldSource.USER_PROVIDED,
                    ),
                ),
                preferences=(
                    PreferenceConstraint(
                        text="Comfortable fit for long rides",
                        mode=PreferenceMode.SOFT,
                        source=FieldSource.USER_PROVIDED,
                    ),
                    PreferenceConstraint(
                        text="Long battery life",
                        mode=PreferenceMode.SOFT,
                        source=FieldSource.USER_PROVIDED,
                    ),
                    PreferenceConstraint(
                        text="Works well with iPhone and Android devices",
                        mode=PreferenceMode.SOFT,
                        source=FieldSource.USER_PROVIDED,
                    ),
                ),
            ),
            product=product,
            listings=(listing,),
            evidence=evidence,
        ),
    )


def _scenario_headphones_non_audio() -> AgentWorkbenchScenario:
    return _analysis_boundary_scenario(
        "monitor",
        "headphones/non-audio-reject",
        "Boundary earphones/headphones specialist input that should fall back instead.",
    )


def _scenario_tv_analysis() -> AgentWorkbenchScenario:
    retailer_source_id = new_id()
    review_source_id = new_id()
    spec_source_id = new_id()
    product = CanonicalProduct(
        name="CineBright 55 MiniLED",
        brand="CineBright",
        model="55 MiniLED",
        category="tv",
        source_ids=(retailer_source_id, review_source_id, spec_source_id),
    )
    listing = ProductListing(
        product_id=product.product_id,
        title="CineBright 55-inch 4K Mini-LED TV - Official Store",
        url="https://example.com/tvs/cinebright-55-miniled",
        seller=SellerProfile(
            seller_name="CineBright Official Store",
            is_marketplace_seller=False,
        ),
        price=Money(amount="799", currency="USD"),
        source_ids=(retailer_source_id,),
        source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.72),
    )
    product = product.model_copy(update={"listing_ids": (listing.listing_id,)})
    evidence = (
        SourceEvidence(
            source_id=retailer_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.PRODUCT_SPEC,
            claim=(
                "Retailer listing states a 55-inch 4K Mini-LED LCD panel with "
                "full-array local dimming backlight."
            ),
            confidence=_confidence(0.74),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.72,
            ),
        ),
        SourceEvidence(
            source_id=spec_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.PRODUCT_SPEC,
            claim=(
                "Spec sheet lists Dolby Vision HDR, HDR10, high peak brightness, "
                "a 120 Hz panel, HDMI 2.1, VRR, ALLM, and low input lag mode."
            ),
            confidence=_confidence(0.72),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.7,
            ),
        ),
        SourceEvidence(
            source_id=review_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.REVIEW_CLAIM,
            claim=(
                "Review says motion handling is good for movies and sports, "
                "bright-room reflections are manageable, and 55 inches fits "
                "best around a seven-to-nine-foot viewing distance."
            ),
            confidence=_confidence(0.66),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.67,
            ),
        ),
        SourceEvidence(
            source_id=retailer_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.LISTING,
                listing_id=listing.listing_id,
            ),
            evidence_type=EvidenceType.LISTING_IDENTITY,
            claim=(
                "Listing identifies the US model and official-store seller for "
                "the 55-inch TV."
            ),
            confidence=_confidence(0.68),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.72,
            ),
        ),
    )
    return _scenario(
        "tv/55-inch-movies-gaming",
        "TV specialist covers panel/backlight, HDR, motion, gaming inputs, "
        "room brightness, size fit, and source IDs.",
        ProductAnalysisAgentInput(
            run_id=new_id(),
            brief=ShoppingBrief(
                original_query=(
                    "I need a 55-inch TV for movies and console gaming in a "
                    "bright living room under $900."
                ),
                category="tv",
                category_source=FieldSource.INFERRED,
                region=RegionPreference(
                    region=Region(country_code="US", currency="USD"),
                    source=FieldSource.USER_PROVIDED,
                ),
                budget=BudgetConstraint(
                    amount=Money(amount="900", currency="USD"),
                    mode=BudgetMode.PREFERRED,
                    source=FieldSource.USER_PROVIDED,
                ),
                constraints=(
                    PreferenceConstraint(
                        text="55-inch size",
                        mode=PreferenceMode.HARD,
                        source=FieldSource.USER_PROVIDED,
                    ),
                    PreferenceConstraint(
                        text="Good for movies and console gaming",
                        mode=PreferenceMode.HARD,
                        source=FieldSource.USER_PROVIDED,
                    ),
                ),
                preferences=(
                    PreferenceConstraint(
                        text="Strong HDR for movies",
                        mode=PreferenceMode.SOFT,
                        source=FieldSource.USER_PROVIDED,
                    ),
                    PreferenceConstraint(
                        text="Smooth motion and gaming inputs",
                        mode=PreferenceMode.SOFT,
                        source=FieldSource.USER_PROVIDED,
                    ),
                    PreferenceConstraint(
                        text="Works in a bright living room",
                        mode=PreferenceMode.SOFT,
                        source=FieldSource.USER_PROVIDED,
                    ),
                ),
            ),
            product=product,
            listings=(listing,),
            evidence=evidence,
        ),
    )


def _scenario_tv_non_tv() -> AgentWorkbenchScenario:
    return _analysis_boundary_scenario(
        "laptop",
        "tv/non-tv-reject",
        "Boundary TV specialist input that should fall back instead.",
    )


def _scenario_smartwatch_analysis() -> AgentWorkbenchScenario:
    retailer_source_id = new_id()
    review_source_id = new_id()
    spec_source_id = new_id()
    product = CanonicalProduct(
        name="TrailFit Wear 2",
        brand="TrailFit",
        model="Wear 2",
        category="smartwatch",
        source_ids=(retailer_source_id, review_source_id, spec_source_id),
    )
    listing = ProductListing(
        product_id=product.product_id,
        title="TrailFit Wear 2 GPS Smartwatch - Official Store",
        url="https://example.com/watches/trailfit-wear-2",
        seller=SellerProfile(
            seller_name="TrailFit Official Store",
            is_marketplace_seller=False,
        ),
        price=Money(amount="249", currency="USD"),
        source_ids=(retailer_source_id,),
        source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.72),
    )
    product = product.model_copy(update={"listing_ids": (listing.listing_id,)})
    evidence = (
        SourceEvidence(
            source_id=retailer_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.PRODUCT_SPEC,
            claim=(
                "Retailer listing states the watch runs Wear OS, pairs with "
                "Android phones, and supports notifications, calls, and app sync."
            ),
            confidence=_confidence(0.72),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.72,
            ),
        ),
        SourceEvidence(
            source_id=spec_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.PRODUCT_SPEC,
            claim=(
                "Spec sheet lists heart-rate, GPS, SpO2, sleep tracking, 48-hour "
                "battery life, fast charging, IP68 dust resistance, and 5ATM "
                "water resistance."
            ),
            confidence=_confidence(0.7),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.7,
            ),
        ),
        SourceEvidence(
            source_id=review_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.REVIEW_CLAIM,
            claim=(
                "Review says Android integration is stronger than iPhone support, "
                "fitness tracking is consistent for runs, battery lasts about two "
                "days, and third-party app support is useful through Wear OS."
            ),
            confidence=_confidence(0.66),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.67,
            ),
        ),
        SourceEvidence(
            source_id=retailer_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.LISTING,
                listing_id=listing.listing_id,
            ),
            evidence_type=EvidenceType.LISTING_IDENTITY,
            claim=(
                "Listing identifies the US model and official-store seller for "
                "the TrailFit Wear 2 smartwatch."
            ),
            confidence=_confidence(0.68),
            source_quality=SourceQuality(
                level=SourceQualityLevel.ADEQUATE,
                score=0.72,
            ),
        ),
    )
    return _scenario(
        "smartwatch/fitness-android",
        "Smartwatch specialist covers phone compatibility, health sensors, "
        "battery, durability, app ecosystem, and source IDs.",
        ProductAnalysisAgentInput(
            run_id=new_id(),
            brief=ShoppingBrief(
                original_query=(
                    "I need a smartwatch for fitness tracking with my Android "
                    "phone under $300."
                ),
                category="smartwatch",
                category_source=FieldSource.INFERRED,
                region=RegionPreference(
                    region=Region(country_code="US", currency="USD"),
                    source=FieldSource.USER_PROVIDED,
                ),
                budget=BudgetConstraint(
                    amount=Money(amount="300", currency="USD"),
                    mode=BudgetMode.PREFERRED,
                    source=FieldSource.USER_PROVIDED,
                ),
                constraints=(
                    PreferenceConstraint(
                        text="Works well with Android",
                        mode=PreferenceMode.HARD,
                        source=FieldSource.USER_PROVIDED,
                    ),
                    PreferenceConstraint(
                        text="Reliable fitness tracking",
                        mode=PreferenceMode.HARD,
                        source=FieldSource.USER_PROVIDED,
                    ),
                ),
                preferences=(
                    PreferenceConstraint(
                        text="Long battery life",
                        mode=PreferenceMode.SOFT,
                        source=FieldSource.USER_PROVIDED,
                    ),
                    PreferenceConstraint(
                        text="Water resistance for workouts",
                        mode=PreferenceMode.SOFT,
                        source=FieldSource.USER_PROVIDED,
                    ),
                    PreferenceConstraint(
                        text="Good app support",
                        mode=PreferenceMode.SOFT,
                        source=FieldSource.USER_PROVIDED,
                    ),
                ),
            ),
            product=product,
            listings=(listing,),
            evidence=evidence,
        ),
    )


def _scenario_smartwatch_non_watch() -> AgentWorkbenchScenario:
    return _analysis_boundary_scenario(
        "phone",
        "smartwatch/non-watch-reject",
        "Boundary smartwatch specialist input that should fall back instead.",
    )


def _scenario_trust_established() -> AgentWorkbenchScenario:
    _, product, listing, _, evidence = _seed_objects("monitor")
    listing = listing.model_copy(
        update={
            "title": "ViewBright 27Q Monitor - Established Retailer",
            "url": AnyHttpUrl(
                "https://www.bestbuy.com/site/viewbright-27q-monitor/fixture"
            ),
            "retailer_id": "BESTBUY-VB27Q",
            "seller": SellerProfile(
                seller_name="Best Buy",
                is_marketplace_seller=False,
                trust_signal=SellerTrustSignal.STRONG,
                source_ids=listing.source_ids,
            ),
            "region_availability": (
                RegionAvailability(region_code="US", source_ids=listing.source_ids),
            ),
            "source_quality": SourceQuality(
                level=SourceQualityLevel.STRONG,
                score=0.86,
                rationale="Synthetic established retailer source.",
            ),
        }
    )
    evidence = evidence.model_copy(
        update={
            "target": EvidenceTarget(
                target_type=EvidenceTargetType.LISTING,
                listing_id=listing.listing_id,
            ),
            "evidence_type": EvidenceType.SELLER_TRUST,
            "claim": (
                "The listing is sold by the established retailer with clear "
                "return and warranty context."
            ),
            "confidence": _confidence(0.82),
            "source_quality": SourceQuality(
                level=SourceQualityLevel.STRONG,
                score=0.86,
                rationale="Synthetic established-retailer evidence.",
            ),
        }
    )
    rule_based_assessment = assess_listing_trust(
        listing,
        ListingTrustRuleContext(
            review_count=120,
            return_policy_present=True,
            warranty_present=True,
            evidence_ids=(evidence.evidence_id,),
            source_ids=listing.source_ids,
        ),
    )
    return _scenario(
        "trust/established-retailer",
        "Trust run expecting reasonable trust for an established retailer.",
        SellerListingTrustAgentInput(
            run_id=new_id(),
            listing=listing.model_copy(update={"product_id": product.product_id}),
            evidence=(evidence,),
            rule_based_assessment=rule_based_assessment,
        ),
    )


def _scenario_trust_unknown_marketplace_cheap() -> AgentWorkbenchScenario:
    _, product, listing, _, evidence = _seed_objects("monitor")
    source_id = listing.source_ids[0]
    weak_listing = listing.model_copy(
        update={
            "product_id": product.product_id,
            "title": "ViewBright 27Q Monitor - DealHub marketplace seller",
            "url": AnyHttpUrl(
                "https://deals.example-market.test/viewbright-27q-warehouse"
            ),
            "seller": SellerProfile(
                seller_name="DealHub Seller 442",
                marketplace_name="DealHub",
                is_marketplace_seller=True,
                trust_signal=SellerTrustSignal.UNKNOWN,
                source_ids=(source_id,),
            ),
            "price": Money(amount="89", currency="USD"),
            "retailer_id": None,
            "source_quality": SourceQuality(
                level=SourceQualityLevel.UNKNOWN,
                score=0.32,
                rationale="Synthetic unknown marketplace source.",
            ),
        }
    )
    evidence = (
        evidence.model_copy(
            update={
                "target": EvidenceTarget(
                    target_type=EvidenceTargetType.LISTING,
                    listing_id=weak_listing.listing_id,
                ),
                "evidence_type": EvidenceType.PRICE,
                "claim": (
                    "The marketplace listing price is far below comparable "
                    "listings for the same monitor."
                ),
                "confidence": _confidence(0.78),
                "source_quality": SourceQuality(
                    level=SourceQualityLevel.MIXED,
                    score=0.42,
                    rationale="Synthetic price-plausibility evidence.",
                ),
            }
        ),
        SourceEvidence(
            source_id=source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.SELLER,
                seller_name=weak_listing.seller.seller_name,
            ),
            evidence_type=EvidenceType.WARRANTY,
            claim=(
                "The marketplace page does not clearly state return-policy or "
                "warranty coverage for the seller."
            ),
            confidence=_confidence(0.62),
            source_quality=SourceQuality(
                level=SourceQualityLevel.MIXED,
                score=0.42,
                rationale="Synthetic unclear policy evidence.",
            ),
        ),
    )
    rule_based_assessment = assess_listing_trust(
        weak_listing,
        ListingTrustRuleContext(
            review_count=0,
            return_policy_present=False,
            warranty_present=False,
            suspicious_price=True,
            suspicious_price_reasons=(
                "The listing price is only about 28% of comparable same-product "
                "listings, which is too low to treat as a normal discount "
                "without stronger seller evidence.",
            ),
            missing_metadata=("retailer_id",),
            evidence_ids=tuple(item.evidence_id for item in evidence),
            source_ids=(source_id,),
        ),
    )
    return _scenario(
        "trust/unknown-marketplace-cheap",
        "Boundary trust run for an unknown cheap marketplace seller.",
        SellerListingTrustAgentInput(
            run_id=new_id(),
            listing=weak_listing,
            evidence=evidence,
            rule_based_assessment=rule_based_assessment,
        ),
        boundary=True,
    )


def _youtube_video_snapshot(
    *,
    video_id: str,
    title: str,
    description: str,
) -> SourceSnapshot:
    video = VideoSource(
        video_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
        title=title,
        description=description,
        channel_name="Workbench Reviews",
        transcript_availability=TranscriptAvailability.NOT_CHECKED,
    )
    return SourceSnapshot(
        source_id=new_id(),
        url=video.url,
        source_type=SourceType.VIDEO,
        provider=ProviderMetadata(provider_name="workbench_youtube_fixture"),
        title=video.title,
        extraction_status=ExtractionStatus.NOT_ATTEMPTED,
        quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.68),
        video=video,
    )


def _scenario_youtube_monitor_review_transcript() -> AgentWorkbenchScenario:
    brief, product, listing, _, _ = _seed_objects("monitor")
    return _scenario(
        "youtube/monitor-review-transcript",
        "Fixture YouTube run with timestamped review transcript evidence.",
        YouTubeReviewIntelligenceAgentInput(
            run_id=new_id(),
            brief=brief,
            products=(product,),
            listings=(listing,),
            source_snapshots=(
                _youtube_video_snapshot(
                    video_id="ccMonitor01",
                    title="Fixture Monitor review for coding and movies",
                    description=(
                        "Workbench review video. Sponsored disclosure and "
                        "affiliate links are visible in the description."
                    ),
                ),
            ),
            video_queries=("fixture monitor review transcript",),
        ),
    )


def _scenario_youtube_no_transcript_gap() -> AgentWorkbenchScenario:
    brief, product, listing, _, _ = _seed_objects("monitor")
    return _scenario(
        "youtube/no-transcript-gap",
        "Boundary YouTube run with metadata but no transcript.",
        YouTubeReviewIntelligenceAgentInput(
            run_id=new_id(),
            brief=brief,
            products=(product,),
            listings=(listing,),
            source_snapshots=(
                _youtube_video_snapshot(
                    video_id="ccNoTrans01",
                    title="Fixture Monitor short review without captions",
                    description="Workbench video metadata only.",
                ),
            ),
        ),
        boundary=True,
    )


def _scenario_reddit_headphones_recurring_complaint() -> AgentWorkbenchScenario:
    brief, product, listing, _, _ = _seed_objects("headphones")
    return _scenario(
        "reddit/headphones-recurring-complaint",
        "Fixture Reddit run with recurring qualitative headphone complaints.",
        RedditCommunityIntelligenceAgentInput(
            run_id=new_id(),
            brief=brief,
            products=(product,),
            listings=(listing,),
            community_queries=("fixture headphones recurring complaint reddit",),
        ),
    )


def _scenario_reddit_inaccessible_gap() -> AgentWorkbenchScenario:
    brief, product, listing, _, _ = _seed_objects("headphones")
    return _scenario(
        "reddit/inaccessible-gap",
        "Boundary Reddit run with inaccessible public content gap.",
        RedditCommunityIntelligenceAgentInput(
            run_id=new_id(),
            brief=brief,
            products=(product,),
            listings=(listing,),
            community_queries=("fixture headphones inaccessible reddit",),
        ),
        boundary=True,
    )


def _scenario_amazon_third_party_seller_region_gap() -> AgentWorkbenchScenario:
    brief, product, listing, _, _ = _seed_objects("monitor")
    return _scenario(
        "amazon/third-party-seller-region-gap",
        "Fixture Amazon run with third-party seller and regional shipping gap.",
        AmazonProductIntelligenceAgentInput(
            run_id=new_id(),
            brief=brief,
            products=(product,),
            listings=(listing,),
            product_queries=("fixture monitor third-party amazon",),
            target_region_code="PH",
        ),
    )


def _scenario_amazon_variant_ambiguity() -> AgentWorkbenchScenario:
    brief, product, listing, _, _ = _seed_objects("monitor")
    product = product.model_copy(
        update={
            "name": "Fixture Monitor Variant",
            "model": "Monitor Variant 1",
        }
    )
    return _scenario(
        "amazon/variant-ambiguity",
        "Boundary Amazon run with variant/review ambiguity warnings.",
        AmazonProductIntelligenceAgentInput(
            run_id=new_id(),
            brief=brief,
            products=(product,),
            listings=(listing,),
            product_queries=("fixture monitor variant amazon",),
            target_region_code="US",
        ),
        boundary=True,
    )


def _scenario_ikea_available_regional_product() -> AgentWorkbenchScenario:
    brief, product, listing, _, _ = _seed_objects("desk")
    brief = brief.model_copy(
        update={
            "original_query": "Can I buy an IKEA MICKE desk in the Philippines?",
            "category": "desk",
            "region": RegionPreference(
                region=Region(country_code="PH", currency="PHP"),
                source=FieldSource.USER_PROVIDED,
            ),
            "budget": BudgetConstraint(
                amount=Money(amount="5000", currency="PHP"),
                mode=BudgetMode.PREFERRED,
                source=FieldSource.USER_PROVIDED,
            ),
        }
    )
    product = product.model_copy(
        update={
            "name": "MICKE desk",
            "brand": "IKEA",
            "model": "MICKE",
        }
    )
    return _scenario(
        "ikea/available-regional-product",
        "Fixture IKEA run with official country product evidence.",
        IKEAStoreIntelligenceAgentInput(
            run_id=new_id(),
            brief=brief,
            products=(product,),
            listings=(listing,),
            product_queries=("MICKE desk IKEA Philippines",),
            target_region_code="PH",
        ),
    )


def _scenario_ikea_no_regional_presence() -> AgentWorkbenchScenario:
    brief, product, listing, _, _ = _seed_objects("desk")
    brief = brief.model_copy(
        update={
            "original_query": "Can I buy an IKEA MICKE desk in Antarctica?",
            "region": RegionPreference(
                region=Region(country_code="AQ", currency="USD"),
                source=FieldSource.USER_PROVIDED,
            ),
        }
    )
    product = product.model_copy(
        update={
            "name": "MICKE desk",
            "brand": "IKEA",
            "model": "MICKE",
        }
    )
    return _scenario(
        "ikea/no-regional-presence",
        "Boundary IKEA run with no supported regional store presence.",
        IKEAStoreIntelligenceAgentInput(
            run_id=new_id(),
            brief=brief,
            products=(product,),
            listings=(listing,),
            product_queries=("MICKE desk IKEA Antarctica",),
            target_region_code="AQ",
        ),
        boundary=True,
    )


def _scenario_comparison_monitor_shortlist() -> AgentWorkbenchScenario:
    brief = _brief(
        "monitor",
        "Need a 27-inch 1440p monitor for coding and movies under $300.",
    )
    dell = _comparison_candidate(
        name="Dell UltraSharp U2724DE",
        brand="Dell",
        model="U2724DE",
        price="289.99",
        fit_score=0.82,
        claim="Dell U2724DE has QHD resolution, USB-C hub features, and ergonomic stand.",
    )
    asus = _comparison_candidate(
        name="ASUS ProArt PA278CV",
        brand="ASUS",
        model="PA278CV",
        price="219.99",
        fit_score=0.74,
        claim="ASUS PA278CV has QHD resolution, good factory calibration, and USB-C input.",
    )
    lg = _comparison_candidate(
        name="LG 27UP850-W",
        brand="LG",
        model="27UP850-W",
        price="379.99",
        fit_score=0.76,
        claim="LG 27UP850-W has 4K resolution and USB-C, but costs more than the budget.",
    )
    products = (dell[0], asus[0], lg[0])
    listings = (dell[1], asus[1], lg[1])
    evidence = (dell[2], asus[2], lg[2])
    category_analyses = (
        _comparison_analysis(*dell, fit_score=0.82),
        _comparison_analysis(*asus, fit_score=0.74),
        _comparison_analysis(*lg, fit_score=0.76),
    )
    trust_assessments = tuple(
        _trust_assessment(listing, item_evidence)
        for listing, item_evidence in zip(listings, evidence, strict=True)
    )
    dedupe = DeduplicationDecision(
        candidate_ids=(new_id(), new_id()),
        outcome=DeduplicationOutcome.UNCERTAIN,
        confidence=_confidence(0.6),
        rationale="The monitor shortlist uses distinct model numbers.",
        evidence_ids=(dell[2].evidence_id, asus[2].evidence_id),
        source_ids=(dell[2].source_id, asus[2].source_id),
    )
    return _scenario(
        "comparison/monitor-shortlist",
        "Three assessed monitor candidates for best overall, value, and stretch modes.",
        ComparisonDecisionAgentInput(
            run_id=new_id(),
            brief=brief,
            products=products,
            listings=listings,
            category_analyses=category_analyses,
            trust_assessments=trust_assessments,
            deduplication_decisions=(dedupe,),
            evidence=evidence,
        ),
    )


def _scenario_comparison_no_strong_buy() -> AgentWorkbenchScenario:
    brief = _brief(
        "monitor",
        "Need the safest 27-inch monitor under $300.",
    )
    marketplace = _comparison_candidate(
        name="ViewPro VP27Q Marketplace",
        brand="ViewPro",
        model="VP27Q",
        price="119.99",
        fit_score=0.42,
        claim="Marketplace listing claims QHD specs but has weak seller details.",
        quality=SourceQualityLevel.MIXED,
    )
    stale = _comparison_candidate(
        name="BudgetPix BP270",
        brand="BudgetPix",
        model="BP270",
        price="279.99",
        fit_score=0.38,
        claim="Only sparse source evidence is available for this monitor.",
        quality=SourceQualityLevel.WEAK,
    )
    weak_trust = _trust_assessment(
        stale[1],
        stale[2],
        level=ListingTrustLevel.WEAK,
    )
    suspicious_trust = _trust_assessment(
        marketplace[1],
        marketplace[2],
        level=ListingTrustLevel.SUSPICIOUS,
    )
    return _scenario(
        "comparison/no-strong-buy",
        "Boundary comparison input where no candidate clears evidence and trust bars.",
        ComparisonDecisionAgentInput(
            run_id=new_id(),
            brief=brief,
            products=(marketplace[0], stale[0]),
            listings=(marketplace[1], stale[1]),
            category_analyses=(
                _comparison_analysis(*marketplace, fit_score=0.42),
                _comparison_analysis(*stale, fit_score=0.38),
            ),
            trust_assessments=(suspicious_trust, weak_trust),
            evidence=(marketplace[2], stale[2]),
        ),
        boundary=True,
    )


def _comparison_candidate(
    *,
    name: str,
    brand: str,
    model: str,
    price: str,
    fit_score: float,
    claim: str,
    quality: SourceQualityLevel = SourceQualityLevel.ADEQUATE,
) -> tuple[CanonicalProduct, ProductListing, SourceEvidence]:
    source_id = new_id()
    product = CanonicalProduct(
        name=name,
        brand=brand,
        model=model,
        category="monitor",
        source_ids=(source_id,),
    )
    listing = ProductListing(
        product_id=product.product_id,
        title=f"{name} - Workbench Store",
        url=f"https://example.com/monitors/{model.casefold()}",
        seller=SellerProfile(
            seller_name="Workbench Store",
            is_marketplace_seller=False,
            source_ids=(source_id,),
        ),
        price=Money(amount=price, currency="USD"),
        source_ids=(source_id,),
        source_quality=SourceQuality(level=quality, score=fit_score),
    )
    product = product.model_copy(update={"listing_ids": (listing.listing_id,)})
    evidence = SourceEvidence(
        source_id=source_id,
        target=EvidenceTarget(
            target_type=EvidenceTargetType.PRODUCT,
            product_id=product.product_id,
        ),
        evidence_type=EvidenceType.PRODUCT_SPEC,
        claim=claim,
        confidence=_confidence(fit_score),
        source_quality=SourceQuality(level=quality, score=fit_score),
    )
    return product, listing, evidence


def _comparison_analysis(
    product: CanonicalProduct,
    listing: ProductListing,
    evidence: SourceEvidence,
    *,
    fit_score: float,
) -> CategoryAnalysis:
    warnings = (
        ("Evidence is limited, so this should not be a confident pick.",)
        if fit_score < 0.5
        else ()
    )
    return CategoryAnalysis(
        product_id=product.product_id,
        listing_ids=(listing.listing_id,),
        category="monitor",
        fit_summary=f"{product.name} is assessed against the monitor brief.",
        strengths=("Source-backed monitor facts are available.",)
        if fit_score >= 0.5
        else (),
        weaknesses=("Practical tradeoffs remain around value, trust, or evidence depth.",),
        warnings=warnings,
        confidence=_confidence(fit_score),
        evidence_ids=(evidence.evidence_id,),
        source_ids=(evidence.source_id,),
    )


def _scenario_verifier_approved() -> AgentWorkbenchScenario:
    brief, product, listing, _, evidence = _seed_objects("monitor")
    analysis = _category_analysis(product, listing, evidence)
    trust = _trust_assessment(listing, evidence)
    bundle = _recommendation_bundle(product, listing, evidence)
    return _scenario(
        "verifier/approved-fixture",
        "Fixture verifier approves a source-backed recommendation bundle.",
        VerificationAgentInput(
            run_id=new_id(),
            brief=brief,
            recommendation_bundle=bundle,
            products=(product,),
            listings=(listing,),
            evidence=(evidence,),
            trust_assessments=(trust,),
            category_analyses=(analysis,),
        ),
    )


def _scenario_verifier_warning() -> AgentWorkbenchScenario:
    brief, product, listing, _, evidence = _seed_objects("monitor")
    bundle = _recommendation_bundle(product, listing, evidence).model_copy(
        update={"warnings": ("Synthetic warning for review.",)}
    )
    return _scenario(
        "verifier/warning-fixture",
        "Boundary verifier input containing a warning to inspect.",
        VerificationAgentInput(
            run_id=new_id(),
            brief=brief,
            recommendation_bundle=bundle,
            products=(product,),
            listings=(listing,),
            evidence=(evidence,),
        ),
        boundary=True,
    )


def _scenario_verifier_unsupported_claim_block() -> AgentWorkbenchScenario:
    brief, product, listing, _, evidence = _seed_objects("monitor")
    analysis = _category_analysis(product, listing, evidence)
    trust = _trust_assessment(listing, evidence)
    bundle = _recommendation_bundle(product, listing, evidence).model_copy(
        update={
            "final_rationale": (
                "The Fixture Monitor has a 240Hz OLED panel and a three-year "
                "burn-in warranty."
            ),
            "mode_results": (
                _recommendation_bundle(product, listing, evidence).mode_results[
                    0
                ].model_copy(
                    update={
                        "rationale": (
                            "Choose it for 240Hz OLED gaming performance and "
                            "warranty coverage."
                        )
                    }
                ),
            ),
        }
    )
    return _scenario(
        "verifier/unsupported-claim-block",
        "Boundary verifier input with uncited product claims that must block output.",
        VerificationAgentInput(
            run_id=new_id(),
            brief=brief,
            recommendation_bundle=bundle,
            products=(product,),
            listings=(listing,),
            evidence=(evidence,),
            trust_assessments=(trust,),
            category_analyses=(analysis,),
        ),
        boundary=True,
    )


def _scenario_verifier_suspicious_listing_warning() -> AgentWorkbenchScenario:
    brief, product, listing, _, evidence = _seed_objects("monitor")
    analysis = _category_analysis(product, listing, evidence)
    trust = _trust_assessment(
        listing,
        evidence,
        level=ListingTrustLevel.SUSPICIOUS,
    )
    bundle = _recommendation_bundle(product, listing, evidence)
    return _scenario(
        "verifier/suspicious-listing-warning",
        "Boundary verifier input where a suspicious final listing lacks a warning.",
        VerificationAgentInput(
            run_id=new_id(),
            brief=brief,
            recommendation_bundle=bundle,
            products=(product,),
            listings=(listing,),
            evidence=(evidence,),
            trust_assessments=(trust,),
            category_analyses=(analysis,),
        ),
        boundary=True,
    )
