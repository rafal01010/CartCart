from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from typing import Any

from fastapi.encoders import jsonable_encoder
from pydantic import Field, ValidationError

from app.agents.catalog import DEFAULT_AGENT_CATALOG, AgentCatalog, AgentCatalogEntry
from app.agents.contracts import (
    AmazonProductIntelligenceAgentInput,
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
    FakeAmazonProductIntelligenceAgent,
    FakeComparisonDecisionAgent,
    FakeDeduplicationReviewAgent,
    FakeDiscoveryAgent,
    FakeEarphonesHeadphonesSpecialistAgent,
    FakeExtractionReviewAgent,
    FakeGenericProductAnalystAgent,
    FakeIKEAStoreIntelligenceAgent,
    FakeIntakeAgent,
    FakeLaptopSpecialistAgent,
    FakeMonitorSpecialistAgent,
    FakeQueryPlannerAgent,
    FakeRedditCommunityIntelligenceAgent,
    FakeSellerListingTrustAgent,
    FakeShoppingGuideAgent,
    FakeShoppingScopeGuardrail,
    FakeSmartphoneSpecialistAgent,
    FakeSmartwatchSpecialistAgent,
    FakeTVSpecialistAgent,
    FakeTechnologyDomainAnalystAgent,
    FakeVerifierCriticAgent,
    FakeYouTubeReviewIntelligenceAgent,
)
from app.agents.live_guardrails import (
    LiveShoppingScopeGuardrail,
    MockShoppingGuardrailModelRunner,
)
from app.agents.live_guide import LiveShoppingGuideAgent, MockShoppingGuideModelRunner
from app.agents.live_intake import LiveIntakeAgent, MockIntakeModelRunner
from app.agents.openai_config import (
    OpenAIAgentConfigurationError,
    build_openai_agent_run_configuration,
    require_live_openai_agent_configuration,
)
from app.core.settings import EnvironmentMode, Settings
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
from app.schemas.products import CanonicalProduct, ProductListing, SellerProfile
from app.schemas.regions import Region
from app.schemas.search_sources import (
    EvidenceTarget,
    EvidenceTargetType,
    EvidenceType,
    ExtractionStatus,
    ProviderMetadata,
    SearchIntent,
    SearchPlan,
    SearchQuery,
    SearchResult,
    SourceEvidence,
    SourceQuality,
    SourceQualityLevel,
    SourceSnapshot,
    SourceType,
)


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
            (_scenario_query_planner_monitor, _scenario_query_planner_generic),
        ),
        "DiscoveryAgent": _definition(
            catalog,
            "DiscoveryAgent",
            DiscoveryAgentInput,
            "DiscoveryAgentOutput",
            FakeDiscoveryAgent,
            (_scenario_discovery_with_seed, _scenario_discovery_empty_seed),
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
        ),
        "TechnologyDomainAnalystAgent": _definition(
            catalog,
            "TechnologyDomainAnalystAgent",
            ProductAnalysisAgentInput,
            "CategoryAnalysis",
            FakeTechnologyDomainAnalystAgent,
            (_scenario_technology_analysis, _scenario_technology_non_specialist),
        ),
        "MonitorSpecialistAgent": _definition(
            catalog,
            "MonitorSpecialistAgent",
            ProductAnalysisAgentInput,
            "CategoryAnalysis",
            FakeMonitorSpecialistAgent,
            (_scenario_monitor_analysis, _scenario_monitor_non_monitor),
        ),
        "SmartphoneSpecialistAgent": _definition(
            catalog,
            "SmartphoneSpecialistAgent",
            ProductAnalysisAgentInput,
            "CategoryAnalysis",
            FakeSmartphoneSpecialistAgent,
            (_scenario_smartphone_analysis, _scenario_smartphone_non_phone),
        ),
        "LaptopSpecialistAgent": _definition(
            catalog,
            "LaptopSpecialistAgent",
            ProductAnalysisAgentInput,
            "CategoryAnalysis",
            FakeLaptopSpecialistAgent,
            (_scenario_laptop_analysis, _scenario_laptop_non_laptop),
        ),
        "EarphonesHeadphonesSpecialistAgent": _definition(
            catalog,
            "EarphonesHeadphonesSpecialistAgent",
            ProductAnalysisAgentInput,
            "CategoryAnalysis",
            FakeEarphonesHeadphonesSpecialistAgent,
            (_scenario_headphones_analysis, _scenario_headphones_non_audio),
        ),
        "TVSpecialistAgent": _definition(
            catalog,
            "TVSpecialistAgent",
            ProductAnalysisAgentInput,
            "CategoryAnalysis",
            FakeTVSpecialistAgent,
            (_scenario_tv_analysis, _scenario_tv_non_tv),
        ),
        "SmartwatchSpecialistAgent": _definition(
            catalog,
            "SmartwatchSpecialistAgent",
            ProductAnalysisAgentInput,
            "CategoryAnalysis",
            FakeSmartwatchSpecialistAgent,
            (_scenario_smartwatch_analysis, _scenario_smartwatch_non_watch),
        ),
        "SellerListingTrustAgent": _definition(
            catalog,
            "SellerListingTrustAgent",
            SellerListingTrustAgentInput,
            "ListingTrustAssessment",
            FakeSellerListingTrustAgent,
            (_scenario_trust_established, _scenario_trust_unknown_seller),
        ),
        "YouTubeReviewIntelligenceAgent": _definition(
            catalog,
            "YouTubeReviewIntelligenceAgent",
            YouTubeReviewIntelligenceAgentInput,
            "VideoReviewEvidenceBundle",
            FakeYouTubeReviewIntelligenceAgent,
            (_scenario_youtube_review, _scenario_youtube_no_query),
        ),
        "RedditCommunityIntelligenceAgent": _definition(
            catalog,
            "RedditCommunityIntelligenceAgent",
            RedditCommunityIntelligenceAgentInput,
            "CommunityDiscussionEvidenceBundle",
            FakeRedditCommunityIntelligenceAgent,
            (_scenario_reddit_discussion, _scenario_reddit_no_products),
        ),
        "AmazonProductIntelligenceAgent": _definition(
            catalog,
            "AmazonProductIntelligenceAgent",
            AmazonProductIntelligenceAgentInput,
            "AmazonProductEvidenceBundle",
            FakeAmazonProductIntelligenceAgent,
            (_scenario_amazon_listing, _scenario_amazon_region_gap),
        ),
        "IKEAStoreIntelligenceAgent": _definition(
            catalog,
            "IKEAStoreIntelligenceAgent",
            IKEAStoreIntelligenceAgentInput,
            "IKEAStoreEvidenceBundle",
            FakeIKEAStoreIntelligenceAgent,
            (_scenario_ikea_store, _scenario_ikea_region_gap),
        ),
        "ComparisonDecisionAgent": _definition(
            catalog,
            "ComparisonDecisionAgent",
            ComparisonDecisionAgentInput,
            "RecommendationBundle",
            FakeComparisonDecisionAgent,
            (_scenario_comparison_shortlist, _scenario_comparison_sparse),
        ),
        "VerifierCriticAgent": _definition(
            catalog,
            "VerifierCriticAgent",
            VerificationAgentInput,
            "VerificationReport",
            FakeVerifierCriticAgent,
            (_scenario_verifier_approved, _scenario_verifier_warning),
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


def _seed_objects(category: str = "monitor") -> tuple[
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
        red_flags=("Unknown seller details.",) if level == ListingTrustLevel.WEAK else (),
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


def _scenario_query_planner_monitor() -> AgentWorkbenchScenario:
    return _scenario(
        "query-planner/monitor-us",
        "Fixture query planner creates a review query.",
        QueryPlannerAgentInput(run_id=new_id(), brief=_brief("monitor")),
    )


def _scenario_query_planner_generic() -> AgentWorkbenchScenario:
    return _scenario(
        "query-planner/generic-category",
        "Boundary query plan for a non-specialist category.",
        QueryPlannerAgentInput(run_id=new_id(), brief=_brief("office chair")),
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


def _analysis_scenario(category: str, scenario_name: str, description: str) -> AgentWorkbenchScenario:
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


def _analysis_boundary_scenario(category: str, scenario_name: str, description: str) -> AgentWorkbenchScenario:
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
    return _analysis_scenario(
        "office chair",
        "generic/office-chair-basic",
        "Generic analysis handles a normal non-tech product.",
    )


def _scenario_generic_weak_evidence() -> AgentWorkbenchScenario:
    return _analysis_boundary_scenario(
        "lamp",
        "generic/weak-evidence",
        "Boundary generic analysis with intentionally sparse synthetic evidence.",
    )


def _scenario_technology_analysis() -> AgentWorkbenchScenario:
    return _analysis_scenario(
        "monitor",
        "technology/monitor-basic",
        "Technology domain analysis handles a technology product.",
    )


def _scenario_technology_non_specialist() -> AgentWorkbenchScenario:
    return _analysis_boundary_scenario(
        "keyboard",
        "technology/non-specialist-tech",
        "Boundary technology analysis for tech without an MVP specialist.",
    )


def _scenario_monitor_analysis() -> AgentWorkbenchScenario:
    return _analysis_scenario(
        "monitor",
        "monitor/coding-basic",
        "Monitor specialist fixture input.",
    )


def _scenario_monitor_non_monitor() -> AgentWorkbenchScenario:
    return _analysis_boundary_scenario(
        "office chair",
        "monitor/non-monitor",
        "Boundary monitor specialist input that should be routed away later.",
    )


def _scenario_smartphone_analysis() -> AgentWorkbenchScenario:
    return _analysis_scenario(
        "smartphone",
        "smartphone/midrange-basic",
        "Smartphone specialist fixture input.",
    )


def _scenario_smartphone_non_phone() -> AgentWorkbenchScenario:
    return _analysis_boundary_scenario(
        "monitor",
        "smartphone/non-phone",
        "Boundary smartphone specialist input that should be routed away later.",
    )


def _scenario_laptop_analysis() -> AgentWorkbenchScenario:
    return _analysis_scenario(
        "laptop",
        "laptop/student-basic",
        "Laptop specialist fixture input.",
    )


def _scenario_laptop_non_laptop() -> AgentWorkbenchScenario:
    return _analysis_boundary_scenario(
        "smartwatch",
        "laptop/non-laptop",
        "Boundary laptop specialist input that should be routed away later.",
    )


def _scenario_headphones_analysis() -> AgentWorkbenchScenario:
    return _analysis_scenario(
        "headphones",
        "headphones/commute-basic",
        "Earphones/headphones specialist fixture input.",
    )


def _scenario_headphones_non_audio() -> AgentWorkbenchScenario:
    return _analysis_boundary_scenario(
        "tv",
        "headphones/non-audio",
        "Boundary audio specialist input that should be routed away later.",
    )


def _scenario_tv_analysis() -> AgentWorkbenchScenario:
    return _analysis_scenario("tv", "tv/movie-basic", "TV specialist fixture input.")


def _scenario_tv_non_tv() -> AgentWorkbenchScenario:
    return _analysis_boundary_scenario(
        "laptop",
        "tv/non-tv",
        "Boundary TV specialist input that should be routed away later.",
    )


def _scenario_smartwatch_analysis() -> AgentWorkbenchScenario:
    return _analysis_scenario(
        "smartwatch",
        "smartwatch/fitness-basic",
        "Smartwatch specialist fixture input.",
    )


def _scenario_smartwatch_non_watch() -> AgentWorkbenchScenario:
    return _analysis_boundary_scenario(
        "phone",
        "smartwatch/non-watch",
        "Boundary smartwatch specialist input that should be routed away later.",
    )


def _scenario_trust_established() -> AgentWorkbenchScenario:
    _, _, listing, _, evidence = _seed_objects("monitor")
    return _scenario(
        "trust/established-retailer",
        "Fixture trust run for a listing with a named seller.",
        SellerListingTrustAgentInput(
            run_id=new_id(),
            listing=listing,
            evidence=(evidence,),
        ),
    )


def _scenario_trust_unknown_seller() -> AgentWorkbenchScenario:
    _, product, listing, _, evidence = _seed_objects("monitor")
    weak_listing = listing.model_copy(
        update={
            "product_id": product.product_id,
            "seller": SellerProfile(
                seller_name="Unknown Outlet",
                is_marketplace_seller=True,
            ),
        }
    )
    return _scenario(
        "trust/unknown-marketplace",
        "Boundary trust run for an unknown marketplace seller.",
        SellerListingTrustAgentInput(
            run_id=new_id(),
            listing=weak_listing,
            evidence=(evidence,),
        ),
        boundary=True,
    )


def _scenario_youtube_review() -> AgentWorkbenchScenario:
    brief, product, listing, snapshot, _ = _seed_objects("monitor")
    return _scenario(
        "youtube/monitor-review",
        "Fixture YouTube source-intelligence run.",
        YouTubeReviewIntelligenceAgentInput(
            run_id=new_id(),
            brief=brief,
            products=(product,),
            listings=(listing,),
            source_snapshots=(snapshot,),
            video_queries=("fixture monitor review",),
        ),
    )


def _scenario_youtube_no_query() -> AgentWorkbenchScenario:
    brief, product, listing, _, _ = _seed_objects("monitor")
    return _scenario(
        "youtube/no-query-gap",
        "Boundary YouTube run with no explicit video query.",
        YouTubeReviewIntelligenceAgentInput(
            run_id=new_id(),
            brief=brief,
            products=(product,),
            listings=(listing,),
        ),
        boundary=True,
    )


def _scenario_reddit_discussion() -> AgentWorkbenchScenario:
    brief, product, listing, _, _ = _seed_objects("headphones")
    return _scenario(
        "reddit/headphones-discussion",
        "Fixture Reddit/community source-intelligence run.",
        RedditCommunityIntelligenceAgentInput(
            run_id=new_id(),
            brief=brief,
            products=(product,),
            listings=(listing,),
            community_queries=("fixture headphones reddit",),
        ),
    )


def _scenario_reddit_no_products() -> AgentWorkbenchScenario:
    return _scenario(
        "reddit/no-products-gap",
        "Boundary Reddit/community input without candidate products.",
        RedditCommunityIntelligenceAgentInput(
            run_id=new_id(),
            brief=_brief("headphones"),
            community_queries=("fixture headphones reddit",),
        ),
        boundary=True,
    )


def _scenario_amazon_listing() -> AgentWorkbenchScenario:
    brief, product, listing, _, _ = _seed_objects("monitor")
    return _scenario(
        "amazon/listing-context",
        "Fixture Amazon source-intelligence run with region context.",
        AmazonProductIntelligenceAgentInput(
            run_id=new_id(),
            brief=brief,
            products=(product,),
            listings=(listing,),
            product_queries=("fixture monitor amazon",),
            target_region_code="US",
        ),
    )


def _scenario_amazon_region_gap() -> AgentWorkbenchScenario:
    brief, product, listing, _, _ = _seed_objects("monitor")
    return _scenario(
        "amazon/region-gap",
        "Boundary Amazon source-intelligence run with alternate region context.",
        AmazonProductIntelligenceAgentInput(
            run_id=new_id(),
            brief=brief,
            products=(product,),
            listings=(listing,),
            product_queries=("fixture monitor amazon",),
            target_region_code="PH",
        ),
        boundary=True,
    )


def _scenario_ikea_store() -> AgentWorkbenchScenario:
    brief, product, listing, _, _ = _seed_objects("desk")
    return _scenario(
        "ikea/official-store-context",
        "Fixture IKEA source-intelligence run with region context.",
        IKEAStoreIntelligenceAgentInput(
            run_id=new_id(),
            brief=brief,
            products=(product,),
            listings=(listing,),
            product_queries=("fixture desk ikea",),
            target_region_code="US",
        ),
    )


def _scenario_ikea_region_gap() -> AgentWorkbenchScenario:
    brief, product, listing, _, _ = _seed_objects("desk")
    return _scenario(
        "ikea/region-gap",
        "Boundary IKEA source-intelligence run with alternate region context.",
        IKEAStoreIntelligenceAgentInput(
            run_id=new_id(),
            brief=brief,
            products=(product,),
            listings=(listing,),
            product_queries=("fixture desk ikea",),
            target_region_code="PH",
        ),
        boundary=True,
    )


def _scenario_comparison_shortlist() -> AgentWorkbenchScenario:
    brief, product, listing, _, evidence = _seed_objects("monitor")
    analysis = _category_analysis(product, listing, evidence)
    trust = _trust_assessment(listing, evidence)
    dedupe = DeduplicationDecision(
        candidate_ids=(new_id(), new_id()),
        outcome=DeduplicationOutcome.UNCERTAIN,
        canonical_product_id=product.product_id,
        confidence=_confidence(0.6),
        rationale="Workbench fixture dedupe note.",
        evidence_ids=(evidence.evidence_id,),
        source_ids=(evidence.source_id,),
    )
    return _scenario(
        "comparison/monitor-shortlist",
        "Fixture comparison decision with one assessed shortlist item.",
        ComparisonDecisionAgentInput(
            run_id=new_id(),
            brief=brief,
            products=(product,),
            listings=(listing,),
            category_analyses=(analysis,),
            trust_assessments=(trust,),
            deduplication_decisions=(dedupe,),
            evidence=(evidence,),
        ),
    )


def _scenario_comparison_sparse() -> AgentWorkbenchScenario:
    brief, product, listing, _, evidence = _seed_objects("monitor")
    return _scenario(
        "comparison/sparse-shortlist",
        "Boundary comparison input with no analysis or trust items yet.",
        ComparisonDecisionAgentInput(
            run_id=new_id(),
            brief=brief,
            products=(product,),
            listings=(listing,),
            evidence=(evidence,),
        ),
        boundary=True,
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
            evidence=(evidence,),
            trust_assessments=(trust,),
            category_analyses=(analysis,),
        ),
    )


def _scenario_verifier_warning() -> AgentWorkbenchScenario:
    brief, product, listing, _, evidence = _seed_objects("monitor")
    bundle = _recommendation_bundle(product, listing, evidence).model_copy(
        update={"warnings": ("Synthetic warning for verifier inspection.",)}
    )
    return _scenario(
        "verifier/warning-fixture",
        "Boundary verifier input containing a warning to inspect.",
        VerificationAgentInput(
            run_id=new_id(),
            brief=brief,
            recommendation_bundle=bundle,
            evidence=(evidence,),
        ),
        boundary=True,
    )
