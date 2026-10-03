import json
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any

import pytest
from agents import Agent, RunConfig, Runner, WebSearchTool
from agents.exceptions import UserError
from agents.items import ModelResponse
from agents.models.interface import Model
from agents.tool_context import ToolContext
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)
from sqlalchemy.ext.asyncio import create_async_engine

from app.agents.contracts import GeneralShoppingAgentInput, GeneralShoppingOutcome
from app.agents.context_management import (
    BoundedRunner,
    ContextBudget,
    ContextBudgetExceeded,
    context_scope,
)
from app.agents.live_general_shopping import (
    GeneralModelOutput,
    GeneralCandidateSelection,
    LiveGeneralShoppingAgent,
    MockGeneralShoppingModelRunner,
    ProductSpecialistHandoffContext,
    TechnologyHandoffContext,
)
from app.agents.openai_config import OpenAIAgentConfigurationError
from app.agents.live_source_intelligence_manager import (
    SourceIntelligenceManagerAgent,
    SourceManagerDecision,
    SourceManagerResult,
)
from app.agents.live_youtube_review_intelligence import YouTubeReviewModelOutput
from app.agents.owner_research import OwnerResearchContext, assess_run_listings
from app.agents.research_tools import (
    AgentResearchTools,
    FetchSourceRequest,
    ResearchToolStatus,
    SearchSourcesRequest,
)
from app.agents.workbench import (
    AgentWorkbenchRunRequest,
    AgentWorkbenchRunner,
    _GeneralFixtureExtractionProvider,
    _general_fixture_search_provider,
)
from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.products import ProductRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_session_factory
from app.providers.fakes import FakeSearchProvider
from app.schemas.ids import new_id
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.intake import FieldSource, RegionPreference
from app.schemas.regions import Region
from app.schemas.products import CanonicalProduct, ProductListing, SellerProfile
from app.schemas.money import Money
from app.schemas.analysis import ListingTrustLevel
from app.schemas.search_sources import (
    SourceIntelligenceCapability,
    VideoReviewEvidenceBundle,
)
from app.schemas.search_sources import (
    ExtractedPageContent,
    ExtractionStatus,
    ProviderMetadata,
    SearchIntent,
    SearchQuery,
    SearchResult,
    SourceQuality,
    SourceQualityLevel,
    SourceType,
    SourceSnapshot,
)


def _settings(**values: Any) -> Settings:
    return Settings(_env_file=None, environment="test", **values)


def test_technology_handoff_requires_meaningful_context() -> None:
    with pytest.raises(ValueError):
        TechnologyHandoffContext(technology_category="keyboard", reason="            ")
    with pytest.raises(ValueError):
        ProductSpecialistHandoffContext(product_category="phone", reason=" ")


def test_owner_helpers_keep_implausible_listing_price_blocked() -> None:
    product = CanonicalProduct(name="Test Phone", category="smartphone")
    listings = tuple(
        ProductListing(
            product_id=product.product_id,
            title="Test Phone",
            url=f"https://example.com/phone-{index}",
            seller=SellerProfile(seller_name=f"Store {index}"),
            price=Money(amount=amount, currency="USD"),
            source_ids=(new_id(),),
        )
        for index, amount in enumerate(("199.00", "209.00", "219.00", "42.00"))
    )
    assessments = assess_run_listings((product,), listings)
    assert assessments[listings[-1].listing_id].level == ListingTrustLevel.SUSPICIOUS


class _ScriptedOwnerModel(Model):
    def __init__(
        self,
        *,
        transfer: bool,
        target: bool = False,
        specialist: bool = False,
        transfer_to_specialist: bool = False,
        invalid_specialist: bool = False,
        recovery: bool = False,
        invalid: bool = False,
        fail: bool = False,
    ):
        self.transfer = transfer
        self.target = target
        self.specialist = specialist
        self.transfer_to_specialist = transfer_to_specialist
        self.invalid_specialist = invalid_specialist
        self.recovery = recovery
        self.invalid = invalid
        self.fail = fail
        self.calls = 0
        self.instructions: list[str] = []
        self.tools: list[str] = []

    async def get_response(
        self,
        system_instructions,
        input,
        model_settings,
        tools,
        output_schema,
        handoffs,
        tracing,
        *,
        previous_response_id,
        conversation_id,
        prompt,
    ) -> ModelResponse:
        del (
            input,
            model_settings,
            output_schema,
            tracing,
            previous_response_id,
            conversation_id,
            prompt,
        )
        self.calls += 1
        if self.fail:
            raise RuntimeError("Scripted technology model failed")
        self.instructions.append(system_instructions or "")
        self.tools.extend(
            "web_search" if isinstance(tool, WebSearchTool) else tool.name
            for tool in tools
        )
        if self.transfer and not self.target and not self.specialist:
            assert len(handoffs) == 1
            output = ResponseFunctionToolCall(
                type="function_call",
                call_id="transfer-1",
                name=handoffs[0].tool_name,
                arguments=TechnologyHandoffContext(
                    technology_category="smartphone"
                    if self.transfer_to_specialist
                    else "keyboard"
                    if not self.invalid
                    else "smartphone",
                    reason="A deeper technology fit check would help this buyer.",
                ).model_dump_json(),
            )
        elif self.target and self.transfer_to_specialist:
            assert len(handoffs) == 6
            phone_handoff = next(
                item
                for item in handoffs
                if item.agent_name == "SmartphoneSpecialistAgent"
            )
            output = ResponseFunctionToolCall(
                type="function_call",
                call_id="transfer-2",
                name=phone_handoff.tool_name,
                arguments=ProductSpecialistHandoffContext(
                    product_category="keyboard" if self.invalid_specialist else "phone",
                    reason="A phone-specific camera and software support check is needed.",
                ).model_dump_json(),
            )
        else:
            assert len(handoffs) == (
                0 if self.specialist or self.recovery else 6 if self.target else 1
            )
            output = ResponseOutputMessage(
                id=f"message-{self.calls}",
                type="message",
                role="assistant",
                status="completed",
                content=[
                    ResponseOutputText(
                        type="output_text",
                        annotations=[],
                        text=GeneralModelOutput(
                            category="smartphone"
                            if self.specialist or self.recovery
                            else "keyboard"
                            if self.target
                            else "walking cane",
                            evidence_gap="No verified product and review pair was found.",
                        ).model_dump_json(),
                    )
                ],
            )
        return ModelResponse(
            output=[output],
            usage=Usage(requests=1, input_tokens=20, output_tokens=30, total_tokens=50),
            response_id=None,
        )

    async def stream_response(self, *args, **kwargs):
        raise AssertionError("Streaming is not used in this test")
        yield


@dataclass
class _SDKOwnerRunner:
    transfer: bool
    invalid: bool = False
    target_fails: bool = False
    specialist_transfer: bool = False
    invalid_specialist: bool = False
    specialist_fails: bool = False
    missing_activity: bool = False
    general: _ScriptedOwnerModel | None = None
    technology: _ScriptedOwnerModel | None = None
    specialist: _ScriptedOwnerModel | None = None
    resolved_models: tuple[str, str] | None = None

    async def run(self, agent, model_input, *, run_config, max_turns):
        if agent.name == "TechnologyDomainAnalystAgent":
            assert agent.handoffs == []
            agent.model = _ScriptedOwnerModel(
                transfer=False, target=True, recovery=True
            )
            return await Runner.run(
                agent, model_input, run_config=run_config, max_turns=max_turns
            )
        target = agent.handoffs[0]._agent_ref()
        assert target is not None
        self.resolved_models = (agent.model, target.model)
        self.general = _ScriptedOwnerModel(
            transfer=self.transfer,
            invalid=self.invalid,
            transfer_to_specialist=self.specialist_transfer,
        )
        self.technology = _ScriptedOwnerModel(
            transfer=False,
            target=True,
            fail=self.target_fails,
            transfer_to_specialist=self.specialist_transfer,
            invalid_specialist=self.invalid_specialist,
        )
        agent.model = self.general
        target.model = self.technology
        phone = next(
            item._agent_ref()
            for item in target.handoffs
            if item.agent_name == "SmartphoneSpecialistAgent"
        )
        self.specialist = _ScriptedOwnerModel(
            transfer=False, specialist=True, fail=self.specialist_fails
        )
        phone.model = self.specialist
        result = await Runner.run(
            agent, model_input, run_config=run_config, max_turns=max_turns
        )
        if self.missing_activity:
            return SimpleNamespace(
                final_output=result.final_output,
                new_items=result.new_items,
                last_agent=result.last_agent,
                context_wrapper=result.context_wrapper,
            )
        return result


class _SourceCallingPhoneModel(Model):
    def __init__(
        self,
        product_id: str,
        quote_sources: tuple[str, str] | None = None,
        hosted_url: str | None = None,
    ) -> None:
        self.product_id = product_id
        self.quote_sources = quote_sources
        self.hosted_url = hosted_url
        self.calls = 0
        self.tool_result_seen = False

    async def get_response(
        self,
        system_instructions,
        input,
        model_settings,
        tools,
        output_schema,
        handoffs,
        tracing,
        *,
        previous_response_id,
        conversation_id,
        prompt,
    ) -> ModelResponse:
        del (
            system_instructions,
            model_settings,
            output_schema,
            tracing,
            previous_response_id,
            conversation_id,
            prompt,
        )
        assert not handoffs
        assert any(tool.name == "consult_source_intelligence" for tool in tools)
        self.calls += 1
        if self.quote_sources and self.calls in {1, 3}:
            output = ResponseFunctionToolCall(
                type="function_call",
                call_id=f"phone-read-{self.calls}",
                name="fetch_source",
                arguments=json.dumps(
                    {"source_id": self.quote_sources[(self.calls - 1) // 2]}
                ),
            )
        elif self.quote_sources and self.calls in {2, 4}:
            source_id = self.quote_sources[(self.calls - 2) // 2]
            output = ResponseFunctionToolCall(
                type="function_call",
                call_id=f"phone-quote-{self.calls}",
                name="record_source_quote",
                arguments=json.dumps(
                    {
                        "source_id": source_id,
                        "quote": (
                            "Test Phone has a 5000 mAh battery."
                            if self.calls == 2
                            else "Test Phone lasted all day in the review test."
                        ),
                    }
                ),
            )
        elif self.calls == (5 if self.quote_sources else 1):
            output = ResponseFunctionToolCall(
                type="function_call",
                call_id="phone-source-1",
                name="consult_source_intelligence",
                arguments=json.dumps(
                    {"product_id": self.product_id, "capability": "video_review"}
                ),
            )
        else:
            self.tool_result_seen = "Source specialist failed" in str(input)
            quote_ids = tuple(
                item["evidence_id"]
                for event in input
                if event.get("type") == "function_call_output"
                for item in [json.loads(event["output"])]
                if item.get("evidence_id")
            )
            output = ResponseOutputMessage(
                id="phone-result",
                type="message",
                role="assistant",
                status="completed",
                content=[
                    ResponseOutputText(
                        type="output_text",
                        annotations=[],
                        text=GeneralModelOutput(
                            category="smartphone",
                            candidates=(
                                GeneralCandidateSelection(
                                    name="Test Phone", evidence_ids=quote_ids
                                ),
                            )
                            if quote_ids
                            else (),
                            selected_candidate_name="Test Phone" if quote_ids else None,
                            evidence_gap="Source video evidence is unavailable; no checked pick."
                            if not quote_ids
                            else None,
                            hosted_lead_urls=(self.hosted_url,)
                            if self.hosted_url
                            else (),
                        ).model_dump_json(),
                    )
                ],
            )
        return ModelResponse(
            output=[output],
            usage=Usage(requests=1, input_tokens=20, output_tokens=30, total_tokens=50),
            response_id=None,
        )

    async def stream_response(self, *args, **kwargs):
        raise AssertionError("Streaming is not used in this test")
        yield


@dataclass
class _SourceCallingOwnerRunner:
    product_id: str
    quote_sources: tuple[str, str] | None = None
    hosted_url: str | None = None
    phone: _SourceCallingPhoneModel | None = None

    async def run(self, agent, model_input, *, run_config, max_turns):
        technology = agent.handoffs[0]._agent_ref()
        agent.model = _ScriptedOwnerModel(transfer=True, transfer_to_specialist=True)
        technology.model = _ScriptedOwnerModel(
            transfer=False, target=True, transfer_to_specialist=True
        )
        phone = next(
            item._agent_ref()
            for item in technology.handoffs
            if item.agent_name == "SmartphoneSpecialistAgent"
        )
        self.phone = _SourceCallingPhoneModel(
            self.product_id, self.quote_sources, self.hosted_url
        )
        phone.model = self.phone
        result = await Runner.run(
            agent, model_input, run_config=run_config, max_turns=max_turns
        )
        if self.hosted_url is None:
            return result
        hosted_response = SimpleNamespace(
            output=[
                {
                    "type": "web_search_call",
                    "id": "phone-web-1",
                    "status": "completed",
                    "action": {
                        "type": "search",
                        "sources": [{"url": self.hosted_url}],
                    },
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "text": "Test Phone review",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": self.hosted_url,
                                    "title": "Test Phone review",
                                    "start_index": 0,
                                    "end_index": 17,
                                }
                            ],
                        }
                    ],
                },
            ]
        )
        return SimpleNamespace(
            final_output=result.final_output,
            new_items=result.new_items,
            last_agent=result.last_agent,
            context_wrapper=result.context_wrapper,
            raw_responses=(*result.raw_responses, hosted_response),
        )


@dataclass
class _SourceManagerStub:
    fails: bool = False
    total_tokens: int = 30
    calls: int = 0

    async def run(self, input_data):
        self.calls += 1
        assert input_data.allowed_capabilities == (
            SourceIntelligenceCapability.VIDEO_REVIEW,
        )
        assert len(input_data.products) == 1
        if self.fails:
            raise RuntimeError("Fixture source specialist unavailable")
        return SourceManagerResult(
            video_bundles=(
                VideoReviewEvidenceBundle(
                    transcript_gap_notes=("No transcript is available.",)
                ),
            ),
            model_name="gpt-6-sol",
            total_tokens=self.total_tokens,
        )


@dataclass
class _RecordingRunner:
    raw_responses: tuple[Any, ...] = ()
    output: Any = None
    error: Exception | None = None
    seen_agent: Agent[Any] | None = None
    max_turns: int = 0

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        del model_input, run_config
        self.seen_agent = agent
        self.max_turns = max_turns
        if self.error is not None:
            raise self.error
        return type(
            "Result",
            (),
            {
                "final_output": self.output
                or GeneralModelOutput(category="walking cane"),
                "raw_responses": self.raw_responses,
            },
        )()


async def _isolated_agent(
    runner: Any,
    *,
    search_provider: Any = None,
    extraction_provider: Any = None,
    model: str = "gpt-6-sol",
    technology_model: str | None = None,
    smartphone_model: str | None = None,
) -> tuple[LiveGeneralShoppingAgent, GeneralShoppingAgentInput, Any, Any]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    run_id = new_id()
    brief = ShoppingBrief(original_query="Find a wooden cane")
    async with factory() as session:
        shopping_session = await SessionRepository(session).create(
            original_input=CreateSessionRequest(query=brief.original_query),
            current_brief=brief,
        )
        await RunRepository(session).create(shopping_session.session_id, run_id=run_id)
        await session.commit()
    agent = LiveGeneralShoppingAgent(
        settings=_settings(
            live_agents_enabled=True,
            openai_api_key="fixture-only-key",
            openai_model=model,
            openai_agent_overrides={
                **(
                    {"TechnologyDomainAnalystAgent": {"model": technology_model}}
                    if technology_model
                    else {}
                ),
                **(
                    {"SmartphoneSpecialistAgent": {"model": smartphone_model}}
                    if smartphone_model
                    else {}
                ),
            },
        ),
        model_runner=runner,
        session_factory=factory,
        research_tools_factory=lambda actual_run_id: AgentResearchTools(
            agent_name="GeneralShoppingAgent",
            run_id=actual_run_id,
            session_factory=factory,
            search_provider=search_provider or _general_fixture_search_provider(),
            extraction_provider=extraction_provider
            or _GeneralFixtureExtractionProvider(),
        ),
        technology_research_tools_factory=lambda actual_run_id, region_code: (
            AgentResearchTools(
                agent_name="TechnologyDomainAnalystAgent",
                run_id=actual_run_id,
                session_factory=factory,
                search_provider=search_provider or _general_fixture_search_provider(),
                extraction_provider=extraction_provider
                or _GeneralFixtureExtractionProvider(),
                required_region_code=region_code,
            )
        ),
    )
    return agent, GeneralShoppingAgentInput(run_id=run_id, brief=brief), factory, engine


@pytest.mark.asyncio
async def test_sdk_general_finishes_cane_without_handoff() -> None:
    runner = _SDKOwnerRunner(transfer=False)
    owner, input_data, _, engine = await _isolated_agent(runner)
    try:
        draft = await owner.run(input_data)
        assert draft.owner_agent_name == "GeneralShoppingAgent"
        assert runner.general.calls == 1
        assert runner.technology.calls == 0
        assert not any(
            item["tool_name"] == "sdk_handoff" for item in owner.workbench_activity
        )
        assert "web_search" in runner.general.tools
        assert runner.technology.tools == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sdk_handoff_lets_technology_finish_unsupported_category() -> None:
    runner = _SDKOwnerRunner(transfer=True)
    owner, input_data, _, engine = await _isolated_agent(
        runner, technology_model="gpt-6-astra"
    )
    input_data = input_data.model_copy(
        update={"brief": ShoppingBrief(original_query="Find a keyboard")}
    )
    try:
        draft = await owner.run(input_data)
        assert draft.owner_agent_name == "TechnologyDomainAnalystAgent"
        assert draft.category == "keyboard"
        assert runner.general.calls == runner.technology.calls == 1
        assert runner.resolved_models == ("gpt-6-sol", "gpt-6-astra")
        assert "whole technology shopping request" in runner.technology.instructions[0]
        assert "search_sources" in runner.technology.tools
        assert "web_search" in runner.technology.tools
        assert "read_run_evidence" in runner.technology.tools
        handoffs = [
            item
            for item in owner.workbench_activity
            if item["tool_name"] == "sdk_handoff"
        ]
        assert len(handoffs) == 1
        assert handoffs[0]["status"] == "completed"
        assert handoffs[0]["input"]["reason"]
        assert handoffs[0]["output"]["last_agent"] == "TechnologyDomainAnalystAgent"
        assert handoffs[0]["output"]["target_model"] == "gpt-6-astra"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sdk_phone_path_has_two_transfers_and_specialist_draft() -> None:
    runner = _SDKOwnerRunner(transfer=True, specialist_transfer=True)
    owner, input_data, _, engine = await _isolated_agent(
        runner, technology_model="gpt-6-astra", smartphone_model="gpt-6-luna"
    )
    input_data = input_data.model_copy(
        update={"brief": ShoppingBrief(original_query="Find a smartphone")}
    )
    try:
        draft = await owner.run(input_data)
        assert draft.owner_agent_name == "SmartphoneSpecialistAgent"
        assert draft.category == "smartphone"
        assert (
            runner.general.calls
            == runner.technology.calls
            == runner.specialist.calls
            == 1
        )
        assert "phone camera" in runner.specialist.instructions[0]
        assert "past 365 days" in runner.specialist.instructions[0]
        assert "about 60 days" in runner.specialist.instructions[0]
        assert "Current UTC date:" in runner.specialist.instructions[0]
        assert "web_search" in runner.specialist.tools
        assert "search_sources" in runner.specialist.tools
        assert "consult_source_intelligence" in runner.specialist.tools
        handoffs = [
            item
            for item in owner.workbench_activity
            if item["tool_name"] == "sdk_handoff"
        ]
        assert [item["status"] for item in handoffs] == ["completed", "completed"]
        assert [item["output"]["target_agent"] for item in handoffs] == [
            "TechnologyDomainAnalystAgent",
            "SmartphoneSpecialistAgent",
        ]
        assert [item["output"]["depth"] for item in handoffs] == [1, 2]
        assert [item["input"]["source_model"] for item in handoffs] == [
            "gpt-6-sol",
            "gpt-6-astra",
        ]
        assert handoffs[1]["output"]["target_model"] == "gpt-6-luna"
        assert (
            next(
                item
                for item in owner.workbench_activity
                if item["tool_name"] == "general_owner"
            )["output"]["last_agent"]
            == "SmartphoneSpecialistAgent"
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_fails", "source_tokens"),
    [(False, 30), (True, 30), (False, 95000)],
)
async def test_delegated_phone_can_consult_bounded_source_agent_and_keep_gap(
    source_fails: bool,
    source_tokens: int,
) -> None:
    product = CanonicalProduct(name="Test Phone", category="smartphone")
    runner = _SourceCallingOwnerRunner(str(product.product_id))
    manager = _SourceManagerStub(fails=source_fails, total_tokens=source_tokens)
    owner, input_data, factory, engine = await _isolated_agent(runner)
    owner.source_intelligence_manager = manager
    owner.regional_research_tools_factory = lambda run_id, region_code: (
        AgentResearchTools(
            agent_name="GeneralShoppingAgent",
            run_id=run_id,
            session_factory=factory,
            search_provider=_general_fixture_search_provider(),
            extraction_provider=_GeneralFixtureExtractionProvider(),
            required_region_code=region_code,
        )
    )
    input_data = input_data.model_copy(
        update={
            "brief": ShoppingBrief(
                original_query="Find a smartphone",
                region=RegionPreference(
                    region=Region(country_code="US"),
                    source=FieldSource.USER_PROVIDED,
                ),
            )
        }
    )
    async with factory() as session:
        await ProductRepository(session).add_canonical_product(
            input_data.run_id, product
        )
        await session.commit()
    try:
        draft = await owner.run(input_data)
        assert draft.owner_agent_name == "SmartphoneSpecialistAgent"
        assert draft.outcome == GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE
        assert manager.calls == 1
        assert runner.phone.calls == 2
        assert runner.phone.tool_result_seen is source_fails
        assert next(
            item
            for item in owner.workbench_activity
            if item["tool_name"] == "general_owner"
        )["output"]["nested_source_tokens"] == (0 if source_fails else source_tokens)
        if source_tokens > 90000:
            assert "combined owner/source token budget" in draft.evidence_gaps[0]
        assert any(
            item["tool_name"] == "consult_source_intelligence"
            and item["input"]["agent"] == "SmartphoneSpecialistAgent"
            and item["status"] == ("failed" if source_fails else "succeeded")
            for item in owner.workbench_activity
        )
        assert [
            item["output"]["target_agent"]
            for item in owner.workbench_activity
            if item["tool_name"] == "sdk_handoff" and item["status"] == "completed"
        ] == ["TechnologyDomainAnalystAgent", "SmartphoneSpecialistAgent"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_phone_finishes_from_its_quotes_and_retains_hosted_lead() -> None:
    query = SearchQuery(query="Test Phone", intent=SearchIntent.DISCOVERY)
    product_page = SearchResult(
        query=query,
        url="https://example.com/phones/test-phone",
        title="Test Phone product page",
        source_type=SourceType.PRODUCT_PAGE,
        provider=ProviderMetadata(provider_name="fixture"),
        quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.7),
    )
    review_page = SearchResult(
        query=query,
        url="https://reviews.example.org/test-phone",
        title="Test Phone independent review",
        source_type=SourceType.PROFESSIONAL_REVIEW,
        provider=ProviderMetadata(provider_name="fixture"),
        quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.7),
    )
    product = CanonicalProduct(
        name="Test Phone",
        category="smartphone",
        source_ids=(product_page.source_id, review_page.source_id),
    )
    lead_url = "https://www.rtings.com/smartphone/reviews/test-phone"
    runner = _SourceCallingOwnerRunner(
        str(product.product_id),
        (str(product_page.source_id), str(review_page.source_id)),
        lead_url,
    )
    manager = _SourceManagerStub()
    owner, input_data, factory, engine = await _isolated_agent(runner)
    owner.source_intelligence_manager = manager
    owner.regional_research_tools_factory = lambda run_id, region_code: (
        AgentResearchTools(
            agent_name="GeneralShoppingAgent",
            run_id=run_id,
            session_factory=factory,
            search_provider=_general_fixture_search_provider(),
            extraction_provider=_GeneralFixtureExtractionProvider(),
            required_region_code=region_code,
        )
    )
    input_data = input_data.model_copy(
        update={
            "brief": ShoppingBrief(
                original_query="Find a smartphone",
                region=RegionPreference(
                    region=Region(country_code="US"),
                    source=FieldSource.USER_PROVIDED,
                ),
            )
        }
    )
    async with factory() as session:
        await ProductRepository(session).add_canonical_product(
            input_data.run_id, product
        )
        repo = SearchSourceRepository(session)
        for source, quote in (
            (product_page, "Test Phone has a 5000 mAh battery."),
            (review_page, "Test Phone lasted all day in the review test."),
        ):
            await repo.add_search_result(input_data.run_id, source)
            await repo.add_source_snapshot(
                input_data.run_id,
                SourceSnapshot(
                    url=source.url,
                    title=source.title,
                    source_type=source.source_type,
                    provider=source.provider,
                    extraction_status=ExtractionStatus.SUCCEEDED,
                    extracted_content=ExtractedPageContent(
                        text=quote,
                        extractor="fixture",
                        word_count=len(quote.split()),
                    ),
                    quality=source.quality,
                ),
                search_result_id=source.source_id,
            )
        await session.commit()
    try:
        draft = await owner.run(input_data)
        assert draft.owner_agent_name == "SmartphoneSpecialistAgent"
        assert draft.outcome == GeneralShoppingOutcome.DRAFT, owner.workbench_activity[
            -1
        ]
        assert draft.selected_candidate_name == "Test Phone"
        assert len(draft.candidates[0].evidence) == 2
        assert len(draft.hosted_lead_source_ids) == 1
        assert manager.calls == 1
        assert runner.phone.calls == 6
        assert [
            item["input"]["agent"]
            for item in owner.workbench_activity
            if item["tool_name"] == "record_source_quote"
        ] == ["SmartphoneSpecialistAgent", "SmartphoneSpecialistAgent"]
        assert any(
            item["tool_name"] == "web_search_citations"
            and item["input"]["agent"] == "SmartphoneSpecialistAgent"
            and item["status"] == "mapped"
            for item in owner.workbench_activity
        )
        assert (
            len(
                [
                    item
                    for item in owner.workbench_activity
                    if item["tool_name"] == "sdk_handoff"
                    and item["status"] == "completed"
                ]
            )
            == 2
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_source_agent_can_consult_quote_backed_candidate_before_product_persistence() -> (
    None
):
    owner, input_data, factory, engine = await _isolated_agent(
        MockGeneralShoppingModelRunner()
    )
    del owner
    query = SearchQuery(query="Test Phone", intent=SearchIntent.DISCOVERY)
    source = SearchResult(
        query=query,
        url="https://example.com/phones/test-phone",
        title="Test Phone product page",
        source_type=SourceType.PRODUCT_PAGE,
        provider=ProviderMetadata(provider_name="fixture"),
        quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.7),
    )
    quote_text = "Test Phone has a 5000 mAh battery."
    async with factory() as session:
        repo = SearchSourceRepository(session)
        await repo.add_search_result(input_data.run_id, source)
        await repo.add_source_snapshot(
            input_data.run_id,
            SourceSnapshot(
                url=source.url,
                title=source.title,
                source_type=source.source_type,
                provider=source.provider,
                extraction_status=ExtractionStatus.SUCCEEDED,
                extracted_content=ExtractedPageContent(
                    text=quote_text,
                    extractor="fixture",
                    word_count=len(quote_text.split()),
                ),
                quality=source.quality,
            ),
            search_result_id=source.source_id,
        )
        await session.commit()
    research = AgentResearchTools(
        agent_name="SmartphoneSpecialistAgent",
        run_id=input_data.run_id,
        session_factory=factory,
        search_provider=_general_fixture_search_provider(),
        extraction_provider=_GeneralFixtureExtractionProvider(),
        required_region_code="US",
    )
    await research.fetch(FetchSourceRequest(source_id=source.source_id))
    recorded = await research.record_quote(source.source_id, quote_text)
    assert recorded.evidence_id is not None
    manager = _SourceManagerStub()
    context = OwnerResearchContext(
        agent_name="SmartphoneSpecialistAgent",
        run_id=input_data.run_id,
        brief=ShoppingBrief(original_query="Find a smartphone"),
        region_code="US",
        session_factory=factory,
        source_manager=manager,
        allowed_quote_ids=lambda: research.recorded_quote_ids,
    )
    try:
        assert (await context.read_source(str(source.source_id)))["status"] == "gap"
        context.allowed_source_ids = lambda: research.recorded_source_ids
        assert (await context.read_source(str(source.source_id)))[
            "status"
        ] == "succeeded"
        denied = await context.consult_source(
            SourceIntelligenceCapability.VIDEO_REVIEW,
            product_name="Unrelated Product",
            evidence_id=str(recorded.evidence_id),
        )
        assert denied["status"] == "gap"
        assert manager.calls == 0
        accepted = await context.consult_source(
            SourceIntelligenceCapability.VIDEO_REVIEW,
            product_name="Test Phone",
            evidence_id=str(recorded.evidence_id),
        )
        assert accepted["status"] == "succeeded"
        assert manager.calls == 1
        assert accepted["bundles"][0]["transcript_gap_notes"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_phone_owner_comparison_excludes_other_product_categories() -> None:
    _, input_data, factory, engine = await _isolated_agent(
        MockGeneralShoppingModelRunner()
    )
    phones = (
        CanonicalProduct(name="Test Phone A", category="smartphone"),
        CanonicalProduct(name="Test Phone B", category="smartphone"),
    )
    laptop = CanonicalProduct(name="Test Laptop", category="laptop")
    async with factory() as session:
        repo = ProductRepository(session)
        for product in (*phones, laptop):
            await repo.add_canonical_product(input_data.run_id, product)
        await session.commit()
    context = OwnerResearchContext(
        agent_name="SmartphoneSpecialistAgent",
        run_id=input_data.run_id,
        brief=ShoppingBrief(original_query="Find a smartphone"),
        region_code=None,
        session_factory=factory,
    )
    try:
        assert (
            await context.compare_candidates(
                [str(phones[0].product_id), str(laptop.product_id)]
            )
        )["status"] == "unknown_product"
        comparison = await context.compare_candidates(
            [str(item.product_id) for item in phones]
        )
        assert comparison["status"] == "succeeded"
        assert [row["name"] for row in comparison["products"]] == [
            "Test Phone A",
            "Test Phone B",
        ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_owner_source_consultation_uses_nested_sdk_agent_tool(
    monkeypatch,
) -> None:
    _, input_data, factory, engine = await _isolated_agent(
        MockGeneralShoppingModelRunner()
    )
    product = CanonicalProduct(name="Test Phone", category="smartphone")
    async with factory() as session:
        await ProductRepository(session).add_canonical_product(
            input_data.run_id, product
        )
        await session.commit()
    nested_names = []

    async def nested_runner(*, starting_agent, input, **kwargs):
        del input, kwargs
        nested_names.append(starting_agent.name)
        return SimpleNamespace(
            final_output=YouTubeReviewModelOutput(
                selected_videos=(),
                claims=(),
                evidence_gaps=("No verified video was available.",),
            ),
            raw_responses=(),
        )

    monkeypatch.setattr(Runner, "run", nested_runner)

    class ParentRunner:
        async def run(self, agent, model_input, *, run_config, max_turns):
            del model_input, run_config, max_turns
            tool = next(
                item for item in agent.tools if item.name == "consult_video_review"
            )
            payload = json.dumps({"input": "Check review video evidence"})
            await tool.on_invoke_tool(
                ToolContext(
                    context=None,
                    tool_name=tool.name,
                    tool_call_id="source-tool-1",
                    tool_arguments=payload,
                ),
                payload,
            )
            return SimpleNamespace(
                final_output=SourceManagerDecision(
                    skipped_sources=(),
                    summary="Video evidence checked with an explicit gap.",
                )
            )

    manager = SourceIntelligenceManagerAgent(
        settings=_settings(live_agents_enabled=False),
        model_runner=ParentRunner(),
    )
    context = OwnerResearchContext(
        agent_name="SmartphoneSpecialistAgent",
        run_id=input_data.run_id,
        brief=ShoppingBrief(original_query="Find a smartphone"),
        region_code="US",
        session_factory=factory,
        source_manager=manager,
    )
    try:
        result = await context.consult_source(
            SourceIntelligenceCapability.VIDEO_REVIEW,
            product_id=str(product.product_id),
        )
        assert result["status"] == "succeeded"
        assert nested_names == ["YouTubeReviewIntelligenceAgent"]
        assert result["bundles"][0]["transcript_gap_notes"]
        assert any(
            item["tool_name"] == "agent_as_tool"
            and item["input"]["agent"] == "YouTubeReviewIntelligenceAgent"
            for item in context.activity
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_phone_hosted_citation_is_persisted_under_receiving_owner() -> None:
    url = "https://www.rtings.com/smartphone/reviews/test-phone"

    class HostedPhoneRunner(_SDKOwnerRunner):
        async def run(self, agent, model_input, *, run_config, max_turns):
            result = await super().run(
                agent, model_input, run_config=run_config, max_turns=max_turns
            )
            hosted_response = SimpleNamespace(
                output=[
                    {
                        "type": "web_search_call",
                        "id": "phone-web-1",
                        "status": "completed",
                        "action": {"type": "search", "sources": [{"url": url}]},
                    },
                    {
                        "type": "message",
                        "content": [
                            {
                                "text": "Test Phone review",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "url": url,
                                        "title": "Test Phone review",
                                        "start_index": 0,
                                        "end_index": 17,
                                    }
                                ],
                            }
                        ],
                    },
                ]
            )
            return SimpleNamespace(
                final_output=GeneralModelOutput(
                    category="smartphone",
                    evidence_gap="A cited review lead needs page verification.",
                    hosted_lead_urls=(url,),
                ),
                new_items=result.new_items,
                last_agent=result.last_agent,
                context_wrapper=result.context_wrapper,
                raw_responses=(*result.raw_responses, hosted_response),
            )

    runner = HostedPhoneRunner(transfer=True, specialist_transfer=True)
    owner, input_data, factory, engine = await _isolated_agent(runner)
    input_data = input_data.model_copy(
        update={"brief": ShoppingBrief(original_query="Find a smartphone")}
    )
    try:
        draft = await owner.run(input_data)
        assert draft.owner_agent_name == "SmartphoneSpecialistAgent"
        assert len(draft.hosted_lead_source_ids) == 1
        assert runner.specialist is not None
        assert "web_search" in runner.specialist.tools
        assert any(
            item["tool_name"] == "web_search"
            and item["input"]["agent"] == "SmartphoneSpecialistAgent"
            for item in owner.workbench_activity
        )
        assert any(
            item["tool_name"] == "web_search_citations"
            and item["status"] == "mapped"
            and item["input"]["agent"] == "SmartphoneSpecialistAgent"
            for item in owner.workbench_activity
        )
        async with factory() as session:
            saved = await SearchSourceRepository(session).list_search_results(
                input_data.run_id
            )
            assert draft.hosted_lead_source_ids[0] in {item.source_id for item in saved}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_invalid_specialist_transfer_stays_at_technology_with_gap() -> None:
    runner = _SDKOwnerRunner(
        transfer=True, specialist_transfer=True, invalid_specialist=True
    )
    owner, input_data, _, engine = await _isolated_agent(runner)
    input_data = input_data.model_copy(
        update={"brief": ShoppingBrief(original_query="Find a smartphone")}
    )
    try:
        draft = await owner.run(input_data)
        assert draft.owner_agent_name == "TechnologyDomainAnalystAgent"
        assert draft.outcome == GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE
        assert runner.specialist.calls == 0
        handoffs = [
            item
            for item in owner.workbench_activity
            if item["tool_name"] == "sdk_handoff"
        ]
        assert [item["status"] for item in handoffs] == ["completed", "failed"]
        assert handoffs[1]["input"]["target_agent"] == "SmartphoneSpecialistAgent"
        assert any(
            item["tool_name"] == "owner_recovery" and item["status"] == "completed"
            for item in owner.workbench_activity
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_non_technology_handoff_is_rejected_with_honest_fallback() -> None:
    runner = _SDKOwnerRunner(transfer=True, invalid=True)
    owner, input_data, _, engine = await _isolated_agent(runner)
    try:
        draft = await owner.run(input_data)
        assert draft.owner_agent_name == "GeneralShoppingAgent"
        assert draft.outcome == GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE
        assert runner.technology.calls == 0
        owner_activity = next(
            item
            for item in owner.workbench_activity
            if item["tool_name"] == "general_owner"
        )
        assert owner_activity["output"]["failure_type"] == "UserError"
        assert (
            owner_activity["output"]["failure_code"] == "technology_category_mismatch"
        )
        assert not any(
            item["tool_name"] == "sdk_handoff" and item["status"] == "completed"
            for item in owner.workbench_activity
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_technology_model_failure_after_sdk_handoff_has_safe_gap() -> None:
    runner = _SDKOwnerRunner(transfer=True, target_fails=True)
    owner, input_data, _, engine = await _isolated_agent(runner)
    input_data = input_data.model_copy(
        update={"brief": ShoppingBrief(original_query="Find a keyboard")}
    )
    try:
        draft = await owner.run(input_data)
        assert draft.owner_agent_name == "TechnologyDomainAnalystAgent"
        assert draft.outcome == GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE
        assert runner.technology.calls == 1
        assert any(
            item["tool_name"] == "sdk_handoff" and item["status"] == "completed"
            for item in owner.workbench_activity
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_specialist_recovers_with_technology_owner() -> None:
    runner = _SDKOwnerRunner(
        transfer=True, specialist_transfer=True, specialist_fails=True
    )
    owner, input_data, _, engine = await _isolated_agent(runner)
    input_data = input_data.model_copy(
        update={"brief": ShoppingBrief(original_query="Find a smartphone")}
    )
    try:
        draft = await owner.run(input_data)
        assert draft.owner_agent_name == "TechnologyDomainAnalystAgent"
        assert draft.outcome == GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE
        assert runner.specialist.calls == 1
        assert any(
            item["tool_name"] == "owner_recovery" and item["status"] == "completed"
            for item in owner.workbench_activity
        )
        assert [
            item["output"]["target_agent"]
            for item in owner.workbench_activity
            if item["tool_name"] == "sdk_handoff" and item["status"] == "completed"
        ] == ["TechnologyDomainAnalystAgent", "SmartphoneSpecialistAgent"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_source_completion_usage_does_not_count_shared_child_usage_again() -> (
    None
):
    class SharedUsageManager(_SourceManagerStub):
        async def run(self, input_data):
            result = await super().run(input_data)
            return SourceManagerResult(
                video_bundles=result.video_bundles,
                total_tokens=20000,
                activity=(
                    {
                        "tool_name": "agent_as_tool",
                        "status": "validated",
                        "input": {"agent": "YouTubeReviewIntelligenceAgent"},
                        "output": {"total_tokens": 70000},
                    },
                ),
            )

    product = CanonicalProduct(name="Test Phone", category="smartphone")
    runner = _SourceCallingOwnerRunner(str(product.product_id))
    owner, input_data, factory, engine = await _isolated_agent(runner)
    owner.source_intelligence_manager = SharedUsageManager()
    input_data = input_data.model_copy(
        update={
            "brief": ShoppingBrief(
                original_query="Find a smartphone",
                region=RegionPreference(
                    region=Region(country_code="US"), source=FieldSource.USER_PROVIDED
                ),
            )
        }
    )
    owner.regional_research_tools_factory = lambda run_id, region_code: (
        AgentResearchTools(
            agent_name="GeneralShoppingAgent",
            run_id=run_id,
            session_factory=factory,
            search_provider=_general_fixture_search_provider(),
            extraction_provider=_GeneralFixtureExtractionProvider(),
            required_region_code=region_code,
        )
    )
    async with factory() as session:
        await ProductRepository(session).add_canonical_product(
            input_data.run_id, product
        )
        await session.commit()
    try:
        await owner.run(input_data)
        event = next(
            item
            for item in owner.workbench_activity
            if item["tool_name"] == "general_owner"
        )
        assert event["status"] == "insufficient_evidence"
        assert event["output"]["nested_source_tokens"] == 20000
        assert event["output"]["gap"] is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_owner_completion_uses_settled_transport_instead_of_sdk_aggregate() -> (
    None
):
    class OfflineProvider:
        def get_model(self, model_name):
            return _ScriptedOwnerModel(transfer=False)

    class LedgerRunner:
        async def run(self, agent, model_input, *, run_config, max_turns):
            result = await BoundedRunner.run(
                agent,
                model_input,
                run_config=replace(run_config, model_provider=OfflineProvider()),
                max_turns=max_turns,
            )
            result.context_wrapper.usage.total_tokens = 95000
            return result

    owner, input_data, _, engine = await _isolated_agent(LedgerRunner())
    try:
        await owner.run(input_data)
        event = next(
            item
            for item in owner.workbench_activity
            if item["tool_name"] == "general_owner"
        )
        assert event["status"] == "insufficient_evidence"
        assert event["output"]["usage"]["total_tokens"] == 95000
        assert event["output"]["accounted_owner_tokens"] == 50
        assert event["output"]["usage_accounting"] == "shared_transport"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("wrapped_failure", [False, True])
async def test_nested_source_budget_failure_stops_owner_without_recovery(
    wrapped_failure: bool,
) -> None:
    class ExhaustedManager(_SourceManagerStub):
        async def run(self, input_data):
            try:
                raise ContextBudgetExceeded("Source budget cannot safely continue.")
            except ContextBudgetExceeded as exc:
                if wrapped_failure:
                    raise UserError("SDK source tool failed.") from exc
                raise

    product = CanonicalProduct(name="Test Phone", category="smartphone")
    runner = _SourceCallingOwnerRunner(str(product.product_id))
    owner, input_data, factory, engine = await _isolated_agent(runner)
    owner.source_intelligence_manager = ExhaustedManager()
    input_data = input_data.model_copy(
        update={
            "brief": ShoppingBrief(
                original_query="Find a smartphone",
                region=RegionPreference(
                    region=Region(country_code="US"), source=FieldSource.USER_PROVIDED
                ),
            )
        }
    )
    owner.regional_research_tools_factory = lambda run_id, region_code: (
        AgentResearchTools(
            agent_name="GeneralShoppingAgent",
            run_id=run_id,
            session_factory=factory,
            search_provider=_general_fixture_search_provider(),
            extraction_provider=_GeneralFixtureExtractionProvider(),
            required_region_code=region_code,
        )
    )
    async with factory() as session:
        await ProductRepository(session).add_canonical_product(
            input_data.run_id, product
        )
        await session.commit()
    try:
        await owner.run(input_data)
        event = next(
            item
            for item in owner.workbench_activity
            if item["tool_name"] == "general_owner"
        )
        assert event["status"] == "research_failed"
        assert event["output"]["failure_code"] == "context_budget_exceeded"
        assert runner.phone.calls == 1
        assert not any(
            item["tool_name"] == "owner_recovery" for item in owner.workbench_activity
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "budget_status"),
    [
        ("I need to buy a phone, budget is not a problem", "unlimited"),
        ("I need to buy a phone", "missing"),
    ],
)
async def test_owner_hierarchy_receives_query_context_without_rewriting_original(
    query, budget_status
) -> None:
    from datetime import date

    class ContextRunner(_RecordingRunner):
        async def run(self, agent, model_input, *, run_config, max_turns):
            payload = json.loads(model_input)
            assert payload["brief"]["original_query"] == query
            assert payload["research_context"]["budget_status"] == budget_status
            assert date.fromisoformat(payload["research_context"]["current_date"])
            technology = agent.handoffs[0]._agent_ref()
            phone = next(
                item._agent_ref()
                for item in technology.handoffs
                if item.agent_name == "SmartphoneSpecialistAgent"
            )
            for owner_agent in (agent, technology, phone):
                assert "specific research purpose" in owner_agent.instructions
                assert "unresolved evidence gaps" in owner_agent.instructions
                assert (
                    "Do not invent preferences, product generations"
                    in owner_agent.instructions
                )
            return await super().run(
                agent, model_input, run_config=run_config, max_turns=max_turns
            )

    owner, input_data, _, engine = await _isolated_agent(ContextRunner())
    input_data = input_data.model_copy(
        update={"brief": ShoppingBrief(original_query=query)}
    )
    try:
        await owner.run(input_data)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_recovery_forced_finalization_without_candidate_stays_technical_failure() -> (
    None
):
    class BoundedRecoveryRunner(_SDKOwnerRunner):
        async def run(self, agent, model_input, *, run_config, max_turns):
            if agent.name == "TechnologyDomainAnalystAgent":

                class OfflineProvider:
                    def get_model(self, model_name):
                        return _ScriptedOwnerModel(
                            transfer=False, target=True, recovery=True
                        )

                agent.model = "offline-recovery"
                return await BoundedRunner.run(
                    agent,
                    model_input,
                    run_config=replace(run_config, model_provider=OfflineProvider()),
                    max_turns=max_turns,
                )
            return await super().run(
                agent, model_input, run_config=run_config, max_turns=max_turns
            )

    runner = BoundedRecoveryRunner(
        transfer=True, specialist_transfer=True, specialist_fails=True
    )
    owner, input_data, _, engine = await _isolated_agent(runner)
    input_data = input_data.model_copy(
        update={"brief": ShoppingBrief(original_query="Find a smartphone")}
    )
    budget = ContextBudget()
    budget.spent = (
        budget.limits.total_tokens
        - budget.limits.decision_reserve
        - budget.limits.verification_reserve
        - 6000
    )
    try:
        with context_scope(budget):
            await owner.run(input_data)
        assert any(item["output"].get("finalizing") for item in budget.events), (
            budget.events,
            owner.workbench_activity,
        )
        event = next(
            item
            for item in owner.workbench_activity
            if item["tool_name"] == "general_owner"
        )
        assert event["status"] == "research_failed"
        assert event["output"]["failure_code"] == "context_budget_exceeded"
        assert any(
            item["tool_name"] == "owner_recovery" and item["status"] == "failed"
            for item in owner.workbench_activity
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_completed_handoff_keeps_last_owner_on_post_run_validation_failure() -> (
    None
):
    runner = _SDKOwnerRunner(transfer=True, missing_activity=True)
    owner, input_data, _, engine = await _isolated_agent(runner)
    input_data = input_data.model_copy(
        update={"brief": ShoppingBrief(original_query="Find a keyboard")}
    )
    try:
        draft = await owner.run(input_data)
        assert draft.owner_agent_name == "TechnologyDomainAnalystAgent"
        assert draft.outcome == GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE
        assert any(
            item["tool_name"] == "sdk_handoff" and item["status"] == "completed"
            for item in owner.workbench_activity
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_general_owner_uses_live_run_shared_session_with_mocked_sdk() -> None:
    isolated, input_data, factory, engine = await _isolated_agent(
        MockGeneralShoppingModelRunner()
    )
    try:
        async with factory() as session:
            owner = LiveGeneralShoppingAgent(
                settings=isolated.settings,
                model_runner=MockGeneralShoppingModelRunner(exercise_tools=True),
                shared_session=session,
                regional_research_tools_factory=lambda run_id, region_code: (
                    AgentResearchTools(
                        agent_name="GeneralShoppingAgent",
                        run_id=run_id,
                        session_factory=None,
                        shared_session=session,
                        search_provider=_general_fixture_search_provider(),
                        extraction_provider=_GeneralFixtureExtractionProvider(),
                        required_region_code=region_code,
                    )
                ),
                technology_research_tools_factory=lambda run_id, region_code: (
                    AgentResearchTools(
                        agent_name="TechnologyDomainAnalystAgent",
                        run_id=run_id,
                        session_factory=None,
                        shared_session=session,
                        search_provider=_general_fixture_search_provider(),
                        extraction_provider=_GeneralFixtureExtractionProvider(),
                        required_region_code=region_code,
                    )
                ),
            )
            draft = await owner.run(input_data)
            assert draft.outcome == GeneralShoppingOutcome.DRAFT
            assert draft.selected_candidate_name == "Oak walking cane"
            assert len(draft.candidates[0].evidence) == 2
            assert (
                len(
                    await SearchSourceRepository(session).list_source_evidence(
                        input_data.run_id
                    )
                )
                == 2
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_mock_workbench_cane_research_creates_cited_draft_and_weak_cases() -> (
    None
):
    workbench = AgentWorkbenchRunner(
        _settings(agent_workbench_enabled=True, live_agents_enabled=True)
    )
    cane = await workbench.run(
        AgentWorkbenchRunRequest(
            agent_name="GeneralShoppingAgent", scenario_name="wooden_cane", mode="mock"
        )
    )
    assert cane.output["outcome"] == GeneralShoppingOutcome.DRAFT
    assert cane.output["selected_candidate_name"] == "Oak walking cane"
    evidence = cane.output["candidates"][0]["evidence"]
    assert len(evidence) == 2
    assert all(
        item["source_id"] and item["snapshot_id"] and item["evidence_id"]
        for item in evidence
    )
    assert {item["source_type"] for item in evidence} == {
        "product_page",
        "professional_review",
    }
    assert [activity.tool_name for activity in cane.allowed_tool_activity].count(
        "record_source_quote"
    ) == 2
    for scenario in ("ambiguous_product", "weak_search_results"):
        result = await workbench.run(
            AgentWorkbenchRunRequest(
                agent_name="GeneralShoppingAgent", scenario_name=scenario, mode="mock"
            )
        )
        assert result.output["outcome"] == GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE
        assert result.output["selected_candidate_name"] is None
        assert result.output["evidence_gaps"]
        if scenario == "weak_search_results":
            assert any(
                item.tool_name == "record_source_quote"
                for item in result.allowed_tool_activity
            )
            assert not result.output["candidates"]


@pytest.mark.asyncio
async def test_mock_workbench_records_actual_domain_and_phone_sdk_handoffs() -> None:
    workbench = AgentWorkbenchRunner(
        _settings(agent_workbench_enabled=True, live_agents_enabled=True)
    )
    for scenario, expected_owner, expected_chain in (
        (
            "keyboard_domain",
            "TechnologyDomainAnalystAgent",
            ("TechnologyDomainAnalystAgent",),
        ),
        (
            "smartphone_two_hop",
            "SmartphoneSpecialistAgent",
            ("TechnologyDomainAnalystAgent", "SmartphoneSpecialistAgent"),
        ),
    ):
        result = await workbench.run(
            AgentWorkbenchRunRequest(
                agent_name="GeneralShoppingAgent", scenario_name=scenario, mode="mock"
            )
        )
        assert result.output["owner_agent_name"] == expected_owner
        assert (
            tuple(
                item.output["target_agent"]
                for item in result.allowed_tool_activity
                if item.tool_name == "sdk_handoff" and item.status == "completed"
            )
            == expected_chain
        )


@pytest.mark.asyncio
async def test_model_cannot_select_uncited_or_unpersisted_evidence() -> None:
    runner = _RecordingRunner(
        output=GeneralModelOutput(
            category="walking cane",
            candidates=(
                GeneralCandidateSelection(
                    name="Invented cane", evidence_ids=(new_id(),)
                ),
            ),
            selected_candidate_name="Invented cane",
        )
    )
    agent, input_data, _, engine = await _isolated_agent(runner)
    try:
        result = await agent.run(input_data)
        assert result.outcome == GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE
        assert result.candidates == ()
        assert result.selected_candidate_name is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_owner_quote_tool_requires_same_run_fetched_exact_text_and_region() -> (
    None
):
    agent, input_data, factory, engine = await _isolated_agent(_RecordingRunner())
    del agent
    tools = AgentResearchTools(
        agent_name="GeneralShoppingAgent",
        run_id=input_data.run_id,
        session_factory=factory,
        search_provider=_general_fixture_search_provider(),
        extraction_provider=_GeneralFixtureExtractionProvider(),
        required_region_code="PH",
    )
    try:
        wrong_region = await tools.search(
            SearchSourcesRequest(query="wooden cane", region_code="US")
        )
        assert wrong_region.status == ResearchToolStatus.INVALID_REQUEST
        search = await tools.search(SearchSourcesRequest(query="wooden cane"))
        assert search.status == ResearchToolStatus.SUCCEEDED
        source_id = search.sources[0].source_id
        before_fetch = await tools.record_quote(source_id, "Oak walking cane")
        assert before_fetch.status == ResearchToolStatus.GAP
        fetched = await tools.fetch(FetchSourceRequest(source_id=source_id))
        assert fetched.status == ResearchToolStatus.SUCCEEDED
        assert (
            await tools.record_quote(source_id, "invented feature")
        ).status == ResearchToolStatus.GAP
        recorded = await tools.record_quote(source_id, fetched.text or "")
        assert recorded.status == ResearchToolStatus.SUCCEEDED
        assert recorded.evidence_id in tools.recorded_quote_ids
        async with factory() as session:
            evidence = await SearchSourceRepository(session).list_source_evidence(
                input_data.run_id
            )
            assert [item.evidence_id for item in evidence] == [recorded.evidence_id]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_live_configuration_attaches_optional_hosted_and_provider_tools() -> None:
    runner = _RecordingRunner()
    agent, input_data, _, engine = await _isolated_agent(runner)
    try:
        result = await agent.run(input_data)
        assert result.outcome == GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE
        assert runner.seen_agent is not None
        assert {
            tool.name for tool in runner.seen_agent.tools if hasattr(tool, "name")
        } >= {"search_sources", "fetch_source", "record_source_quote"}
        assert any(isinstance(tool, WebSearchTool) for tool in runner.seen_agent.tools)
        assert len(runner.seen_agent.handoffs) == 1
        assert (
            runner.seen_agent.handoffs[0].agent_name == "TechnologyDomainAnalystAgent"
        )
        technology = runner.seen_agent.handoffs[0]._agent_ref()
        assert technology is not None
        assert {item.agent_name for item in technology.handoffs} == {
            "MonitorSpecialistAgent",
            "SmartphoneSpecialistAgent",
            "LaptopSpecialistAgent",
            "EarphonesHeadphonesSpecialistAgent",
            "TVSpecialistAgent",
            "SmartwatchSpecialistAgent",
        }
        assert all(item._agent_ref().handoffs == [] for item in technology.handoffs)
        assert runner.max_turns == agent.settings.openai_agent_max_turns
        assert not any(
            item["tool_name"] == "web_search" for item in agent.workbench_activity
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_hosted_call_persists_only_cited_weak_lead() -> None:
    runner = _RecordingRunner(
        output=GeneralModelOutput(
            category="walking cane",
            hosted_lead_urls=("https://example.com/cane",),
        ),
        raw_responses=(
            {
                "output": [
                    {
                        "type": "web_search_call",
                        "id": "ws-1",
                        "status": "completed",
                        "action": {
                            "type": "search",
                            "sources": [{"url": "https://example.com/cane"}],
                        },
                    },
                    {
                        "type": "message",
                        "content": [
                            {
                                "text": "A cane page was found.",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "url": "https://example.com/cane",
                                        "title": "Cane page",
                                        "start_index": 0,
                                        "end_index": 10,
                                    }
                                ],
                            }
                        ],
                    },
                ]
            },
        ),
    )
    agent, input_data, factory, engine = await _isolated_agent(runner)
    try:
        result = await agent.run(input_data)
        assert result.outcome == GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE
        assert len(result.hosted_lead_source_ids) == 1
        async with factory() as session:
            repo = SearchSourceRepository(session)
            evidence = await repo.list_source_evidence(input_data.run_id)
            assert len(evidence) == 1
            assert evidence[0].source_quality.level == "weak"
        assert any(
            item["tool_name"] == "web_search_citations"
            for item in agent.workbench_activity
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_search_open_and_find_do_not_discard_valid_hosted_leads() -> None:
    url = "https://example.com/phone"
    runner = _RecordingRunner(
        output=GeneralModelOutput(category="smartphone", hosted_lead_urls=(url,)),
        raw_responses=(
            SimpleNamespace(
                output=[
                    {
                        "type": "web_search_call",
                        "id": str(index),
                        "status": "completed",
                        "action": {"type": action},
                    }
                    for index, action in enumerate(
                        ("search", "open_page", "find_in_page")
                    )
                ]
                + [
                    {
                        "type": "message",
                        "content": [
                            {
                                "text": "Phone source",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "url": url,
                                        "title": "Phone source",
                                        "start_index": 0,
                                        "end_index": 12,
                                    }
                                ],
                            }
                        ],
                    }
                ]
            ),
        ),
    )
    owner, input_data, _, engine = await _isolated_agent(runner)
    try:
        draft = await owner.run(input_data)
        assert len(draft.hosted_lead_source_ids) == 1
        assert not any(
            item["status"] == "research_failed" for item in owner.workbench_activity
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_model_failure_is_reported_as_research_failure() -> None:
    runner = _RecordingRunner(error=RuntimeError("Private provider credential"))
    owner, input_data, _, engine = await _isolated_agent(runner)
    try:
        await owner.run(input_data)
        assert any(
            item["tool_name"] == "general_owner" and item["status"] == "research_failed"
            for item in owner.workbench_activity
        )
        assert "Private provider credential" not in json.dumps(owner.workbench_activity)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_model_selected_uncited_hosted_url_is_rejected() -> None:
    runner = _RecordingRunner(
        output=GeneralModelOutput(
            category="walking cane",
            hosted_lead_urls=("https://invented.example/cane",),
        ),
        raw_responses=(
            {
                "output": [
                    {
                        "type": "web_search_call",
                        "id": "ws-2",
                        "status": "completed",
                        "action": {"type": "search"},
                    },
                    {
                        "type": "message",
                        "content": [
                            {
                                "text": "Cane source",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "url": "https://example.com/cane",
                                        "title": "Cane",
                                        "start_index": 0,
                                        "end_index": 4,
                                    }
                                ],
                            }
                        ],
                    },
                ]
            },
        ),
    )
    agent, input_data, factory, engine = await _isolated_agent(runner)
    try:
        result = await agent.run(input_data)
        assert result.hosted_lead_source_ids == ()
        assert any(
            item["status"] == "uncited_rejected" for item in agent.workbench_activity
        )
        async with factory() as session:
            assert (
                await SearchSourceRepository(session).list_search_results(
                    input_data.run_id
                )
                == ()
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_hosted_call_and_runner_error_fall_back_honestly() -> None:
    for runner in (
        _RecordingRunner(
            raw_responses=(
                {
                    "output": [
                        {
                            "type": "web_search_call",
                            "id": "w",
                            "status": "failed",
                            "action": {"type": "search"},
                        }
                    ]
                },
            )
        ),
        _RecordingRunner(error=RuntimeError("offline model failure")),
    ):
        agent, input_data, _, engine = await _isolated_agent(runner)
        try:
            result = await agent.run(input_data)
            assert result.outcome == GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE
            assert result.evidence_gaps
            assert result.selected_candidate_name is None
        finally:
            await engine.dispose()


@pytest.mark.asyncio
async def test_incompatible_hosted_model_fails_before_mocked_runner() -> None:
    runner = _RecordingRunner()
    agent, input_data, _, engine = await _isolated_agent(
        runner, model="unverified-model"
    )
    try:
        with pytest.raises(OpenAIAgentConfigurationError):
            await agent.run(input_data)
        assert runner.seen_agent is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_fixture_mode_has_no_model_or_provider_call() -> None:
    workbench = AgentWorkbenchRunner(_settings(agent_workbench_enabled=True))
    fixture = await workbench.run(
        AgentWorkbenchRunRequest(
            agent_name="GeneralShoppingAgent",
            scenario_name="wooden_cane",
            mode="fixture",
        )
    )
    assert fixture.output["outcome"] == GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE
    assert fixture.allowed_tool_activity == ()


@pytest.mark.asyncio
async def test_generic_provider_hits_can_be_classified_after_fetch() -> None:
    query = SearchQuery(query="wooden cane", intent=SearchIntent.DISCOVERY)
    provider = FakeSearchProvider(
        results=tuple(
            SearchResult(
                query=query,
                url=url,
                title="Oak walking cane",
                source_type=SourceType.SEARCH_RESULT,
                provider=ProviderMetadata(provider_name="fixture-search"),
                quality=SourceQuality(level=SourceQualityLevel.UNKNOWN),
            )
            for url in (
                "https://www.homedepot.com/p/oak-walking-cane",
                "https://www.goodhousekeeping.com/reviews/oak-walking-cane",
            )
        )
    )
    agent, input_data, _, engine = await _isolated_agent(
        MockGeneralShoppingModelRunner(exercise_tools=True),
        search_provider=provider,
    )
    try:
        result = await agent.run(input_data)
        assert result.outcome == GeneralShoppingOutcome.DRAFT
        assert {item.source_type for item in result.candidates[0].evidence} == {
            SourceType.RETAILER_LISTING,
            SourceType.PROFESSIONAL_REVIEW,
        }
    finally:
        await engine.dispose()
