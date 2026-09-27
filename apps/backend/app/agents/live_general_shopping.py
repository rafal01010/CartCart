"""Model-running general shopping owner for live shopping runs and workbench."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Protocol
from urllib.parse import urlsplit

from agents import Agent, AgentHooks, ModelSettings, RunConfig, Runner, handoff
from agents.exceptions import UserError
from agents.items import HandoffOutputItem
from agents.tool_context import ToolContext
from pydantic import Field, ValidationInfo, field_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.contracts import (
    GeneralShoppingAgentInput,
    GeneralShoppingCandidate,
    GeneralShoppingDecisionDraft,
    GeneralShoppingEvidence,
    GeneralShoppingModeSelection,
    GeneralShoppingOutcome,
)
from app.agents.catalog import DEFAULT_AGENT_CATALOG
from app.agents.hosted_web_search import (
    build_hosted_web_search_tool,
    read_hosted_web_search_activity,
)
from app.agents.openai_config import (
    OpenAIAgentConfigurationError,
    OpenAIAgentRuntimeMode,
    apply_openai_agent_run_profile,
    build_openai_agent_run_configuration,
)
from app.agents.live_source_intelligence_manager import SourceIntelligenceManagerAgent
from app.agents.owner_research import OwnerResearchContext, assess_run_listings
from app.agents.research_tools import AgentResearchTools, PersistedHostedCitation
from app.core.settings import Settings
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.schemas.analysis import ListingTrustLevel, RecommendationMode
from app.providers.source_quality import (
    SourceClass,
    SourceEvidenceContext,
    SourceQualityMetadata,
    score_source_quality,
)
from app.providers.contracts import SourceAllowAvoidPolicy
from app.schemas.base import CartCartBaseModel
from app.schemas.ids import SourceId
from app.schemas.regions import RegionCode
from app.schemas.search_sources import SourceQualityLevel, SourceType


class GeneralCandidateSelection(CartCartBaseModel):
    name: str = Field(min_length=1, max_length=200)
    evidence_ids: tuple[SourceId, ...] = Field(min_length=1, max_length=8)


class GeneralModelOutput(CartCartBaseModel):
    category: str = Field(min_length=1, max_length=200)
    specialist_helpful: bool = False
    candidates: tuple[GeneralCandidateSelection, ...] = Field(default_factory=tuple)
    mode_selections: tuple[GeneralShoppingModeSelection, ...] = Field(
        default_factory=tuple, max_length=4
    )
    selected_candidate_name: str | None = None
    evidence_gap: str | None = Field(default=None, max_length=500)
    hosted_lead_urls: tuple[str, ...] = Field(default_factory=tuple, max_length=8)


class TechnologyHandoffContext(CartCartBaseModel):
    technology_category: str = Field(min_length=2, max_length=120)
    reason: str = Field(min_length=10, max_length=300)

    @field_validator("technology_category", "reason")
    @classmethod
    def _nonblank_handoff_context(cls, value: str, info: ValidationInfo) -> str:
        stripped = value.strip()
        if len(stripped) < (10 if info.field_name == "reason" else 2):
            raise ValueError("Handoff context must not be blank.")
        return stripped


class ProductSpecialistHandoffContext(CartCartBaseModel):
    product_category: str = Field(min_length=2, max_length=120)
    reason: str = Field(min_length=10, max_length=300)

    @field_validator("product_category", "reason")
    @classmethod
    def _nonblank_context(cls, value: str, info: ValidationInfo) -> str:
        stripped = value.strip()
        if len(stripped) < (10 if info.field_name == "reason" else 2):
            raise ValueError("Specialist handoff context must not be blank.")
        return stripped


_SPECIALIST_INSTRUCTIONS = {
    "MonitorSpecialistAgent": "Evaluate monitor size, resolution, panel, refresh, ports, ergonomics, and use-case fit.",
    "SmartphoneSpecialistAgent": "Evaluate phone camera, battery, updates, performance, compatibility, and regional variants.",
    "LaptopSpecialistAgent": "Evaluate laptop performance, memory, storage, battery, portability, ports, and repairability.",
    "EarphonesHeadphonesSpecialistAgent": "Evaluate audio fit, comfort, isolation, ANC, microphones, battery, and codecs.",
    "TVSpecialistAgent": "Evaluate TV panel, HDR, motion, viewing distance, gaming inputs, and software support.",
    "SmartwatchSpecialistAgent": "Evaluate watch phone compatibility, health features, battery, sensors, and support.",
}


class _OwnerHandoffHooks(AgentHooks):
    def __init__(self, observed: list[tuple[str, str]]) -> None:
        self.observed = observed

    async def on_handoff(
        self, _context: Any, agent: Agent[Any], source: Agent[Any]
    ) -> None:
        self.observed.append((source.name, agent.name))


class GeneralShoppingModelRunner(Protocol):
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any: ...


@dataclass
class OpenAIAgentsSDKGeneralShoppingModelRunner:
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        return await Runner.run(
            agent, model_input, run_config=run_config, max_turns=max_turns
        )


@dataclass
class MockGeneralShoppingModelRunner:
    """Offline workbench response; scripted tool-using tests inject a runner."""

    output: GeneralModelOutput | dict[str, Any] | None = None
    exercise_tools: bool = False
    calls: int = 0

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        del run_config, max_turns
        self.calls += 1
        query = json.loads(model_input)["brief"]["original_query"]
        if self.exercise_tools and (
            "cane" in query.casefold() or "garden seat" in query.casefold()
        ):
            by_name = {tool.name: tool for tool in agent.tools}

            async def invoke(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
                result = await by_name[name].on_invoke_tool(
                    ToolContext(
                        context=None,
                        tool_name=name,
                        tool_call_id=f"mock-{name}-{self.calls}",
                        tool_arguments="{}",
                    ),
                    json.dumps(arguments),
                )
                return json.loads(result)

            search = await invoke("search_sources", {"query": query, "max_results": 2})
            evidence_ids: list[SourceId] = []
            for source in search.get("sources", ()):  # Fixture provider only.
                fetched = await invoke(
                    "fetch_source", {"source_id": source["source_id"]}
                )
                if fetched.get("status") != "succeeded":
                    continue
                recorded = await invoke(
                    "record_source_quote",
                    {"source_id": source["source_id"], "quote": fetched["text"][:400]},
                )
                if recorded.get("evidence_id"):
                    evidence_ids.append(SourceId(recorded["evidence_id"]))
            candidate_name = (
                "Folding garden seat"
                if "garden seat" in query.casefold()
                else "Oak walking cane"
            )
            output = GeneralModelOutput(
                category="garden seat"
                if "garden seat" in query.casefold()
                else "walking cane",
                candidates=(
                    GeneralCandidateSelection(
                        name=candidate_name, evidence_ids=tuple(evidence_ids)
                    ),
                )
                if evidence_ids
                else (),
                selected_candidate_name=candidate_name if evidence_ids else None,
                evidence_gap="The sources did not support a checked cane choice."
                if not evidence_ids
                else None,
            )
            return _MockResult(final_output=output)
        return _MockResult(
            final_output=self.output
            or GeneralModelOutput(
                category=query[:200],
                evidence_gap="No verified page evidence was supplied by this offline mock.",
            ),
            raw_responses=(),
        )


@dataclass(frozen=True)
class _MockResult:
    final_output: Any
    raw_responses: tuple[Any, ...] = ()


@dataclass
class LiveGeneralShoppingAgent:
    settings: Settings
    research_tools_factory: Callable[[Any], AgentResearchTools] | None = None
    regional_research_tools_factory: (
        Callable[[Any, RegionCode | None], AgentResearchTools] | None
    ) = None
    technology_research_tools_factory: (
        Callable[[Any, RegionCode | None], AgentResearchTools] | None
    ) = None
    source_intelligence_manager: SourceIntelligenceManagerAgent | None = None
    session_factory: async_sessionmaker[AsyncSession] | None = None
    shared_session: AsyncSession | None = None
    model_runner: GeneralShoppingModelRunner = field(
        default_factory=OpenAIAgentsSDKGeneralShoppingModelRunner
    )
    _activity: tuple[dict[str, Any], ...] = field(default=(), init=False)

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return self._activity

    async def run(
        self, input_data: GeneralShoppingAgentInput
    ) -> GeneralShoppingDecisionDraft:
        configuration = build_openai_agent_run_configuration(
            self.settings,
            agent_name="GeneralShoppingAgent",
            run_id=str(input_data.run_id),
        )
        self._activity = ()
        region_code = (
            input_data.brief.region.region.country_code
            if input_data.brief.region is not None
            else None
        )
        if self.regional_research_tools_factory is not None:
            tools = self.regional_research_tools_factory(input_data.run_id, region_code)
        elif self.research_tools_factory is not None:
            tools = self.research_tools_factory(input_data.run_id)
        else:
            tools = None
        if tools is not None and tools.required_region_code != region_code:
            raise OpenAIAgentConfigurationError(
                "GeneralShoppingAgent research region must match the buyer's region."
            )
        if configuration.mode == OpenAIAgentRuntimeMode.LIVE and (
            tools is None
            or (self.session_factory is None and self.shared_session is None)
        ):
            raise OpenAIAgentConfigurationError(
                "Live GeneralShoppingAgent requires run-scoped research and evidence persistence."
            )
        technology_configuration = build_openai_agent_run_configuration(
            self.settings,
            agent_name="TechnologyDomainAnalystAgent",
            run_id=str(input_data.run_id),
        )
        technology_tools = (
            self.technology_research_tools_factory(input_data.run_id, region_code)
            if self.technology_research_tools_factory is not None
            else None
        )
        if (
            technology_tools is not None
            and technology_tools.required_region_code != region_code
        ):
            raise OpenAIAgentConfigurationError(
                "TechnologyDomainAnalystAgent research region must match the buyer's region."
            )
        if (
            configuration.mode == OpenAIAgentRuntimeMode.LIVE
            and technology_tools is None
        ):
            raise OpenAIAgentConfigurationError(
                "Live TechnologyDomainAnalystAgent handoff requires run-scoped research."
            )
        owner_research = (
            {
                name: OwnerResearchContext(
                    agent_name=name,
                    run_id=input_data.run_id,
                    brief=input_data.brief,
                    region_code=region_code,
                    session_factory=self.session_factory,
                    shared_session=self.shared_session,
                    source_manager=self.source_intelligence_manager,
                    source_policy=(
                        technology_tools.source_policy
                        if name != "GeneralShoppingAgent"
                        and technology_tools is not None
                        else tools.source_policy
                        if tools is not None
                        else SourceAllowAvoidPolicy()
                    ),
                )
                for name in (
                    "GeneralShoppingAgent",
                    "TechnologyDomainAnalystAgent",
                    *_SPECIALIST_INSTRUCTIONS,
                )
            }
            if configuration.mode == OpenAIAgentRuntimeMode.LIVE
            else {}
        )
        hosted_tool = (
            build_hosted_web_search_tool(
                agent_name="GeneralShoppingAgent",
                model=configuration.model,
                region_code=region_code,
                source_policy=tools.source_policy,
            )
            if configuration.mode == OpenAIAgentRuntimeMode.LIVE and tools is not None
            else None
        )
        sdk_tools = list(tools.sdk_owner_tools()) if tools is not None else []
        if owner_research:
            sdk_tools.extend(owner_research["GeneralShoppingAgent"].sdk_tools())
        if hosted_tool is not None:
            sdk_tools.append(hosted_tool)
        approved_specialists = DEFAULT_AGENT_CATALOG.require(
            "TechnologyDomainAnalystAgent"
        ).target_handoff_agent_names
        if set(approved_specialists) != set(_SPECIALIST_INSTRUCTIONS):
            raise OpenAIAgentConfigurationError(
                "Technology handoff targets must match implemented product specialists."
            )
        specialist_configurations = {}
        specialist_agents = {}
        specialist_tools: dict[str, AgentResearchTools] = {}
        owner_hosted_tools = {"GeneralShoppingAgent": hosted_tool}
        specialist_requests: list[tuple[str, ProductSpecialistHandoffContext]] = []
        observed_handoffs: list[tuple[str, str]] = []
        rejected_specialist: str | None = None
        for specialist_name in approved_specialists:
            entry = DEFAULT_AGENT_CATALOG.require(specialist_name)
            if (
                entry.parent_agent_name != "TechnologyDomainAnalystAgent"
                or not entry.target_can_finish_shopper_request
                or entry.target_handoff_agent_names
                or entry.sdk_implementation_pending
            ):
                raise OpenAIAgentConfigurationError(
                    f"{specialist_name} is not an approved terminal owner."
                )
            specialist_configuration = build_openai_agent_run_configuration(
                self.settings,
                agent_name=specialist_name,
                run_id=str(input_data.run_id),
            )
            specialist_configurations[specialist_name] = specialist_configuration
            specialist_research = (
                technology_tools.for_agent(specialist_name)
                if technology_tools is not None
                else None
            )
            if specialist_research is not None:
                specialist_tools[specialist_name] = specialist_research
            specialist_hosted = (
                build_hosted_web_search_tool(
                    agent_name=specialist_name,
                    model=specialist_configuration.model,
                    region_code=region_code,
                    source_policy=specialist_research.source_policy,
                )
                if configuration.mode == OpenAIAgentRuntimeMode.LIVE
                and specialist_research is not None
                else None
            )
            owner_hosted_tools[specialist_name] = specialist_hosted
            specialist_sdk_tools = (
                list(specialist_research.sdk_owner_tools())
                if specialist_research is not None
                else []
            )
            if owner_research:
                specialist_sdk_tools.extend(owner_research[specialist_name].sdk_tools())
            if specialist_hosted is not None:
                specialist_sdk_tools.append(specialist_hosted)
            specialist_agent = Agent(
                name=specialist_name,
                model=specialist_configuration.model,
                instructions=(
                    "You now own this product shopping request. Finish with "
                    "GeneralModelOutput, not CategoryAnalysis. The parent agents must "
                    "not rewrite your draft. "
                    + _SPECIALIST_INSTRUCTIONS[specialist_name]
                    + " You may search, fetch, inspect persisted run evidence, compare it, "
                    "check listing risk, or consult one scoped source specialist as needed. "
                    "Hosted citations are leads until a page is fetched and quoted. "
                    "Use only fetched and recorded page quote evidence IDs for candidates. "
                    "Optional comparison modes need a named cited candidate; price modes also need a checked listing and quote. "
                    "If those sources do not support a product/listing "
                    "and an independent review, leave the selection empty and explain "
                    "the evidence gap. Never invent a price, availability, seller trust, "
                    "specification, source ID, or further handoff."
                ),
                output_type=GeneralModelOutput,
                tools=specialist_sdk_tools,
                model_settings=ModelSettings(
                    max_tokens=1500, include_usage=True, tool_choice="auto"
                ),
                handoffs=[],
                hooks=_OwnerHandoffHooks(observed_handoffs),
            )
            apply_openai_agent_run_profile(specialist_agent, specialist_configuration)
            specialist_agents[specialist_name] = specialist_agent

        for owner_context in owner_research.values():
            owner_context.allowed_quote_ids = lambda: frozenset().union(
                *(
                    state.recorded_quote_ids
                    for state in (tools, technology_tools, *specialist_tools.values())
                    if state is not None
                )
            )
            owner_context.allowed_source_ids = lambda: frozenset(
                source.source_id
                for state in (tools, technology_tools, *specialist_tools.values())
                if state is not None
                for source in state.search_results
            ).union(
                *(
                    state.recorded_source_ids
                    for state in (tools, technology_tools, *specialist_tools.values())
                    if state is not None
                )
            )

        def on_specialist_handoff(
            specialist_name: str, request: ProductSpecialistHandoffContext
        ) -> None:
            nonlocal rejected_specialist
            if specialist_requests or not handoff_requests:
                rejected_specialist = specialist_name
                raise UserError("Specialist handoff exceeds the declared hierarchy.")
            brief_text = " ".join(
                (input_data.brief.original_query, input_data.brief.category or "")
            )
            requested_route = DEFAULT_AGENT_CATALOG.route_product_analysis(
                request.product_category
            ).agent_path
            buyer_route = DEFAULT_AGENT_CATALOG.route_product_analysis(
                brief_text
            ).agent_path
            if (
                requested_route != ("TechnologyDomainAnalystAgent", specialist_name)
                or buyer_route != requested_route
            ):
                rejected_specialist = specialist_name
                raise UserError(
                    "Specialist handoff does not match the buyer's category."
                )
            specialist_requests.append((specialist_name, request))

        def specialist_callback(
            name: str,
        ) -> Callable[[Any, ProductSpecialistHandoffContext], None]:
            def callback(
                _context: Any, request: ProductSpecialistHandoffContext
            ) -> None:
                on_specialist_handoff(name, request)

            return callback

        specialist_handoffs = [
            handoff(
                specialist_agents[name],
                tool_description_override=(
                    f"Transfer a matching {', '.join(DEFAULT_AGENT_CATALOG.require(name).routing_categories)} "
                    "shopping request to its product specialist for final ownership. "
                    "Do not use for broad or other technology requests."
                ),
                input_type=ProductSpecialistHandoffContext,
                on_handoff=specialist_callback(name),
            )
            for name in approved_specialists
        ]
        technology_agent = Agent(
            name="TechnologyDomainAnalystAgent",
            model=technology_configuration.model,
            instructions=(
                "You now own this whole technology shopping request. Interpret the original "
                "brief and the handoff reason, then finish with GeneralModelOutput. You may "
                "finish broad or unsupported technology categories yourself; do not invent "
                "a product specialist or return control to General. Hand off only when "
                "one of the declared product specialists fits the buyer's exact category; "
                "that specialist owns the final draft. Check compatibility, "
                "regional model differences, durability, software support, warranty, and "
                "other category-specific tradeoffs when evidence supports them. Use only "
                "record_source_quote evidence IDs for candidates. Search, fetch, inspect "
                "persisted evidence, compare, check listing trust, or consult a relevant "
                "source specialist when useful. Hosted citations are leads until fetched. "
                "Optional comparison modes need a named cited candidate; price modes also need a checked listing and quote. "
                "Search and fetch within "
                "the buyer's region when useful. If product/listing and independent review "
                "evidence are insufficient, leave the selection empty and explain the gap. "
                "Never infer prices, availability, seller trust, or specifications from snippets."
            ),
            output_type=GeneralModelOutput,
            tools=(list(technology_tools.sdk_owner_tools()) if technology_tools else [])
            + (
                list(owner_research["TechnologyDomainAnalystAgent"].sdk_tools())
                if owner_research
                else []
            ),
            model_settings=ModelSettings(
                max_tokens=1800, include_usage=True, tool_choice="auto"
            ),
            handoffs=specialist_handoffs
            if configuration.mode == OpenAIAgentRuntimeMode.LIVE
            else [],
            hooks=_OwnerHandoffHooks(observed_handoffs),
        )
        apply_openai_agent_run_profile(technology_agent, technology_configuration)
        technology_hosted = (
            build_hosted_web_search_tool(
                agent_name=technology_agent.name,
                model=technology_configuration.model,
                region_code=region_code,
                source_policy=technology_tools.source_policy,
            )
            if configuration.mode == OpenAIAgentRuntimeMode.LIVE
            and technology_tools is not None
            else None
        )
        owner_hosted_tools[technology_agent.name] = technology_hosted
        if technology_hosted is not None:
            technology_agent.tools.append(technology_hosted)
        handoff_requests: list[TechnologyHandoffContext] = []

        def on_technology_handoff(
            _context: Any, request: TechnologyHandoffContext
        ) -> None:
            permitted = DEFAULT_AGENT_CATALOG.require(
                "GeneralShoppingAgent"
            ).target_handoff_agent_names
            if technology_agent.name not in permitted or handoff_requests:
                raise UserError(
                    "Technology handoff is not allowed or exceeds depth one."
                )
            brief_text = " ".join(
                (input_data.brief.original_query, input_data.brief.category or "")
            )
            if (
                DEFAULT_AGENT_CATALOG.route_product_analysis(
                    request.technology_category
                ).agent_path[0]
                != technology_agent.name
                or DEFAULT_AGENT_CATALOG.route_product_analysis(brief_text).agent_path[
                    0
                ]
                != technology_agent.name
            ):
                raise UserError(
                    "Technology handoff does not match the shopper's request."
                )
            handoff_requests.append(request)

        agent = Agent(
            name="GeneralShoppingAgent",
            model=configuration.model,
            instructions=(
                "Own this ordinary shopping request, including categories without a specialist. "
                "Interpret the buyer's need, category, region and constraints. Treat any "
                "saved user-added products as leads, never as verified facts. Use approved "
                "research tools and run-scoped evidence, trust, comparison, or source "
                "intelligence helpers when useful; fetch before recording exact quotes. "
                "Hosted web search is optional and its citations are only leads until fetched. "
                "Organize candidates using only evidence IDs returned by record_source_quote. "
                "Seek independent product/listing and review evidence before choosing a candidate. "
                "Optionally name distinct best-value, within-budget, stretch, or runner-up modes only when cited evidence supports them; price modes also need a checked listing and quote. "
                "If that evidence is missing, leave selected_candidate_name empty and state a gap. "
                "Never infer current price, regional availability, seller trust, or product facts "
                "from snippets, ratings, or a cited URL alone. Finish broad or non-technology "
                "requests yourself. Only hand off to TechnologyDomainAnalystAgent when the "
                "shopper's request is about technology and deeper technology ownership helps. "
                "A handoff transfers the rest of this model decision; do not draft again."
            ),
            output_type=GeneralModelOutput,
            tools=sdk_tools,
            model_settings=ModelSettings(
                max_tokens=2500, include_usage=True, tool_choice="auto"
            ),
            handoffs=[
                handoff(
                    technology_agent,
                    tool_description_override=(
                        "Transfer a technology shopping request for deeper technology "
                        "fit analysis and final ownership. Do not use for other categories."
                    ),
                    input_type=TechnologyHandoffContext,
                    on_handoff=on_technology_handoff,
                )
            ]
            if configuration.mode == OpenAIAgentRuntimeMode.LIVE
            else [],
            hooks=_OwnerHandoffHooks(observed_handoffs),
        )
        apply_openai_agent_run_profile(agent, configuration)
        run_config = RunConfig(
            tracing_disabled=not configuration.tracing_enabled,
            trace_include_sensitive_data=configuration.trace_include_sensitive_data,
            workflow_name=configuration.trace_workflow_name,
            trace_metadata=configuration.trace_metadata,
        )
        citations: tuple[PersistedHostedCitation, ...] = ()
        gap: str | None = None
        raw_result: Any = None
        failed_run_usage: Any = None
        recovered_run_usage: Any = None
        owner_name = agent.name
        handoff_activity: tuple[dict[str, Any], ...] = ()
        handoff_confirmed = False
        owner_timeout = min(
            configuration.timeout_seconds,
            technology_configuration.timeout_seconds,
            *(item.timeout_seconds for item in specialist_configurations.values()),
        )
        started_at = asyncio.get_running_loop().time()

        def validated_handoffs(result: Any) -> tuple[str, tuple[dict[str, Any], ...]]:
            completed = tuple(
                item
                for item in getattr(result, "new_items", ())
                if isinstance(item, HandoffOutputItem)
            )
            requested = (
                [(agent.name, technology_agent.name, handoff_requests[0])]
                if handoff_requests
                else []
            )
            requested.extend(
                (technology_agent.name, name, request)
                for name, request in specialist_requests
            )
            if len(completed) != len(requested) or len(completed) > 2:
                raise ValueError(
                    "SDK handoff chain did not match validated handoff context."
                )
            expected_owner = agent.name
            if observed_handoffs and observed_handoffs != [
                (source, target) for source, target, _ in requested
            ]:
                raise ValueError("SDK handoff hooks did not match result items.")
            events: list[dict[str, Any]] = []
            for depth, (item, (source, target, request)) in enumerate(
                zip(completed, requested, strict=True), start=1
            ):
                if item.source_agent.name != source or item.target_agent.name != target:
                    raise ValueError("SDK handoff target or order was not approved.")
                expected_owner = target
                target_configuration = (
                    technology_configuration
                    if depth == 1
                    else specialist_configurations[target]
                )
                events.append(
                    {
                        "tool_name": "sdk_handoff",
                        "status": "completed",
                        "input": {
                            "source_agent": source,
                            "source_model": (
                                configuration.model
                                if depth == 1
                                else technology_configuration.model
                            ),
                            "technology_category"
                            if depth == 1
                            else "product_category": (
                                request.technology_category
                                if depth == 1
                                else request.product_category
                            ),
                            "reason": request.reason,
                        },
                        "output": {
                            "target_agent": target,
                            "target_model": target_configuration.model,
                            "last_agent": target,
                            "depth": depth,
                        },
                    }
                )
            last_name = getattr(getattr(result, "last_agent", None), "name", agent.name)
            if last_name != expected_owner:
                raise ValueError("SDK last agent did not match the handoff chain.")
            return expected_owner, tuple(events)

        try:
            raw_result = await asyncio.wait_for(
                self.model_runner.run(
                    agent,
                    json.dumps(input_data.model_dump(mode="json")),
                    run_config=run_config,
                    max_turns=min(
                        configuration.max_turns,
                        technology_configuration.max_turns,
                        *(
                            item.max_turns
                            for item in specialist_configurations.values()
                        ),
                        10,
                    ),
                ),
                timeout=owner_timeout,
            )
            owner_name, handoff_activity = validated_handoffs(raw_result)
            handoff_confirmed = bool(handoff_activity)
            sdk_usage = getattr(
                getattr(raw_result, "context_wrapper", None), "usage", None
            )
            nested_tokens = sum(
                item.get("output", {}).get("total_tokens") or 0
                for state in owner_research.values()
                for item in state.activity
                if item.get("tool_name")
                in {"agent_as_tool", "consult_source_intelligence"}
            )
            if (getattr(sdk_usage, "total_tokens", 0) or 0) + nested_tokens > 90000:
                raise ValueError("Owner run exceeded its token budget.")
            model_output = GeneralModelOutput.model_validate(
                getattr(raw_result, "final_output", raw_result)
            )
            if hosted_tool is not None:
                if not hasattr(raw_result, "raw_responses"):
                    raise ValueError(
                        "SDK result omitted hosted-search activity metadata."
                    )
                response_groups: dict[str, list[Any]] = {
                    name: [] for name in owner_hosted_tools
                }
                response_owner = agent.name
                handoff_targets = {
                    item.tool_name: item.agent_name
                    for item in (*agent.handoffs, *technology_agent.handoffs)
                }
                for response in raw_result.raw_responses:
                    response_groups[response_owner].append(response)
                    for item in getattr(response, "output", ()):
                        target = handoff_targets.get(getattr(item, "name", None))
                        if target is not None:
                            response_owner = target
                hosted_activity = {
                    name: read_hosted_web_search_activity(
                        SimpleNamespace(raw_responses=tuple(responses))
                    )
                    for name, responses in response_groups.items()
                }
                all_calls = [
                    (name, call)
                    for name, activity in hosted_activity.items()
                    for call in activity.calls
                ]
                self._activity = tuple(
                    {
                        "tool_name": "web_search",
                        "status": call.status,
                        "input": {"agent": name},
                        "output": {
                            "call_id": call.call_id,
                            "source_urls": list(call.source_urls),
                        },
                    }
                    for name, call in all_calls
                )
                if len(all_calls) > 2 or any(
                    call.status != "completed" for _, call in all_calls
                ):
                    raise ValueError("Hosted-search call limit or completion failed.")
                if all_calls and not any(
                    item.citations for item in hosted_activity.values()
                ):
                    raise ValueError("Hosted search returned no URL citations.")
                selected_urls = set(model_output.hosted_lead_urls)
                cited_urls = {
                    citation.url
                    for item in hosted_activity.values()
                    for citation in item.citations
                }
                for url in sorted(selected_urls - cited_urls):
                    self._activity += (
                        {
                            "tool_name": "web_search_citations",
                            "status": "uncited_rejected",
                            "input": {"agent": owner_name},
                            "output": {"url": url},
                        },
                    )
                research_by_owner = {
                    agent.name: tools,
                    technology_agent.name: technology_tools,
                    **specialist_tools,
                }
                for name, activity in hosted_activity.items():
                    selected_citations = tuple(
                        citation
                        for citation in activity.citations
                        if citation.url in selected_urls
                    )
                    owner_tools = research_by_owner[name]
                    mapped = (
                        await owner_tools.persist_hosted_citations(
                            selected_citations,
                            query=input_data.brief.original_query,
                            region_code=region_code,
                        )
                        if activity.calls
                        and owner_tools is not None
                        and selected_citations
                        else ()
                    )
                    citations += mapped
                    if activity.calls:
                        self._activity += (
                            {
                                "tool_name": "web_search_citations",
                                "status": "mapped" if mapped else "none_retained",
                                "input": {"agent": name},
                                "output": {
                                    "source_ids": [str(c.source_id) for c in mapped],
                                    "evidence_ids": [
                                        str(c.evidence_id) for c in mapped
                                    ],
                                    "rejected_count": len(activity.citations)
                                    - len(mapped),
                                },
                            },
                        )
            if tools is not None and (
                self.session_factory is not None or self.shared_session is not None
            ):
                draft = await self._validated_draft(
                    input_data,
                    model_output,
                    tools,
                    citations,
                    technology_tools if handoff_confirmed else None,
                    specialist_tools,
                )
                draft = draft.model_copy(update={"owner_agent_name": owner_name})
            else:
                draft = self._insufficient(
                    input_data,
                    model_output.category,
                    model_output.specialist_helpful,
                    "No persisted research was available in this fixture run.",
                )
        except (Exception, asyncio.TimeoutError) as exc:
            gap = f"Shopping research could not be verified ({type(exc).__name__})."
            error_data = getattr(exc, "run_data", None)
            failed_run_usage = getattr(
                getattr(error_data, "context_wrapper", None), "usage", None
            )
            error_handoffs = tuple(
                item
                for item in getattr(error_data, "new_items", ())
                if isinstance(item, HandoffOutputItem)
            )
            if not handoff_confirmed and (error_handoffs or observed_handoffs):
                expected = (
                    [(agent.name, technology_agent.name)] if handoff_requests else []
                ) + [(technology_agent.name, name) for name, _ in specialist_requests]
                recorded_edges = (
                    [
                        (item.source_agent.name, item.target_agent.name)
                        for item in error_handoffs
                    ]
                    if error_handoffs
                    else observed_handoffs
                )
                if len(recorded_edges) <= len(expected) and all(
                    edge == expected[index] for index, edge in enumerate(recorded_edges)
                ):
                    owner_name = recorded_edges[-1][1]
                    handoff_confirmed = True
                    contexts = [
                        handoff_requests[0],
                        *(r for _, r in specialist_requests),
                    ]
                    handoff_activity = tuple(
                        {
                            "tool_name": "sdk_handoff",
                            "status": "completed",
                            "input": {
                                "source_agent": source,
                                "source_model": (
                                    configuration.model
                                    if index == 0
                                    else technology_configuration.model
                                ),
                                "reason": contexts[index].reason,
                            },
                            "output": {
                                "target_agent": target,
                                "target_model": (
                                    technology_configuration.model
                                    if index == 0
                                    else specialist_configurations[target].model
                                ),
                                "last_agent": target,
                                "depth": index + 1,
                                "evidence": (
                                    "sdk_result_item"
                                    if error_handoffs
                                    else "sdk_handoff_hook"
                                ),
                            },
                        }
                        for index, (source, target) in enumerate(recorded_edges)
                    )
            if len(handoff_activity) < len(handoff_requests) + len(specialist_requests):
                failed_source = (
                    technology_agent.name if handoff_activity else agent.name
                )
                failed_target = (
                    specialist_requests[0][0]
                    if handoff_activity and specialist_requests
                    else technology_agent.name
                )
                handoff_activity += (
                    {
                        "tool_name": "sdk_handoff",
                        "status": "failed",
                        "input": {
                            "source_agent": failed_source,
                            "target_agent": failed_target,
                        },
                        "output": {
                            "last_agent": owner_name,
                            "error_type": type(exc).__name__,
                        },
                    },
                )
            elif rejected_specialist is not None:
                handoff_activity += (
                    {
                        "tool_name": "sdk_handoff",
                        "status": "failed",
                        "input": {
                            "source_agent": technology_agent.name,
                            "target_agent": rejected_specialist,
                        },
                        "output": {
                            "last_agent": owner_name,
                            "error_type": type(exc).__name__,
                        },
                    },
                )
            draft = self._insufficient(
                input_data, input_data.brief.category or "general shopping", False, gap
            )
            if handoff_confirmed:
                draft = draft.model_copy(update={"owner_agent_name": owner_name})
            failed_specialist = (
                specialist_requests[-1][0]
                if specialist_requests and owner_name == specialist_requests[-1][0]
                else rejected_specialist
                if owner_name == technology_agent.name
                else None
            )
            remaining_seconds = owner_timeout - (
                asyncio.get_running_loop().time() - started_at
            )
            if (
                failed_specialist is not None
                and raw_result is None
                and remaining_seconds > 0
                and getattr(failed_run_usage, "total_tokens", 0) < 90000
            ):
                recovery_agent = technology_agent.clone(
                    handoffs=[],
                    hooks=None,
                    instructions=(
                        str(technology_agent.instructions)
                        + " The product specialist failed. Finish this request yourself "
                        "from verified evidence or state a precise evidence gap."
                    ),
                )
                try:
                    recovery_result = await asyncio.wait_for(
                        self.model_runner.run(
                            recovery_agent,
                            json.dumps(input_data.model_dump(mode="json")),
                            run_config=run_config,
                            max_turns=2,
                        ),
                        timeout=remaining_seconds,
                    )
                    if getattr(
                        getattr(recovery_result, "last_agent", None), "name", None
                    ) != technology_agent.name or any(
                        isinstance(item, HandoffOutputItem)
                        for item in getattr(recovery_result, "new_items", ())
                    ):
                        raise ValueError(
                            "Technology recovery did not retain ownership."
                        )
                    recovery_output = GeneralModelOutput.model_validate(
                        getattr(recovery_result, "final_output", recovery_result)
                    )
                    recovery_usage = getattr(
                        getattr(recovery_result, "context_wrapper", None), "usage", None
                    )
                    if (
                        getattr(failed_run_usage, "total_tokens", 0)
                        + getattr(recovery_usage, "total_tokens", 0)
                        > 90000
                    ):
                        raise ValueError(
                            "Technology recovery exceeded its token budget."
                        )
                    recovered_run_usage = recovery_usage
                    assert tools is not None and technology_tools is not None
                    draft = await self._validated_draft(
                        input_data,
                        recovery_output,
                        tools,
                        (),
                        technology_tools,
                        specialist_tools,
                    )
                    owner_name = technology_agent.name
                    draft = draft.model_copy(update={"owner_agent_name": owner_name})
                    handoff_activity += (
                        {
                            "tool_name": "owner_recovery",
                            "status": "completed",
                            "input": {"failed_specialist": failed_specialist},
                            "output": {
                                "last_agent": owner_name,
                                "model": technology_configuration.model,
                                "sdk_handoff": False,
                                "total_tokens": getattr(
                                    recovery_usage, "total_tokens", None
                                ),
                            },
                        },
                    )
                except Exception as recovery_exc:
                    handoff_activity += (
                        {
                            "tool_name": "owner_recovery",
                            "status": "failed",
                            "input": {"failed_specialist": failed_specialist},
                            "output": {"error_type": type(recovery_exc).__name__},
                        },
                    )
        sdk_usage = getattr(getattr(raw_result, "context_wrapper", None), "usage", None)
        if sdk_usage is None:
            sdk_usage = failed_run_usage
        combined_usage = {
            field: (getattr(sdk_usage, field, 0) or 0)
            + (getattr(recovered_run_usage, field, 0) or 0)
            if sdk_usage is not None or recovered_run_usage is not None
            else None
            for field in ("input_tokens", "output_tokens", "total_tokens")
        }
        nested_source_tokens = sum(
            item.get("output", {}).get("total_tokens") or 0
            for state in owner_research.values()
            for item in state.activity
            if item.get("tool_name") in {"agent_as_tool", "consult_source_intelligence"}
        )
        if (combined_usage["total_tokens"] or 0) + nested_source_tokens > 90000:
            gap = "Shopping research exceeded its combined owner/source token budget."
            draft = self._insufficient(
                input_data, draft.category, False, gap
            ).model_copy(update={"owner_agent_name": owner_name})
        self._activity = (
            *((tools.workbench_activity) if tools is not None else ()),
            *(
                (technology_tools.workbench_activity)
                if technology_tools is not None
                else ()
            ),
            *(
                item
                for state in specialist_tools.values()
                for item in state.workbench_activity
            ),
            *(item for state in owner_research.values() for item in state.activity),
            *self._activity,
            *handoff_activity,
            {
                "tool_name": "general_owner",
                "status": draft.outcome.value,
                "input": {
                    "agent": "GeneralShoppingAgent",
                    "run_id": str(input_data.run_id),
                },
                "output": {
                    "selected_candidate_name": draft.selected_candidate_name,
                    "mode_selections": [
                        item.mode.value for item in draft.mode_selections
                    ],
                    "evidence_ids": [
                        str(e.evidence_id) for c in draft.candidates for e in c.evidence
                    ],
                    "gap": gap,
                    "model": configuration.model,
                    "last_agent": draft.owner_agent_name,
                    "last_agent_model": (
                        specialist_configurations[draft.owner_agent_name].model
                        if draft.owner_agent_name in specialist_configurations
                        else technology_configuration.model
                        if draft.owner_agent_name == technology_agent.name
                        else configuration.model
                    ),
                    "max_turns": min(configuration.max_turns, 10),
                    "max_output_tokens_per_turn": 2500,
                    "usage": {
                        **combined_usage,
                    },
                    "nested_source_tokens": nested_source_tokens,
                },
            },
        )
        return draft

    async def _validated_draft(
        self,
        input_data: GeneralShoppingAgentInput,
        model: GeneralModelOutput,
        tools: AgentResearchTools,
        citations: tuple[PersistedHostedCitation, ...],
        technology_tools: AgentResearchTools | None = None,
        specialist_tools: dict[str, AgentResearchTools] | None = None,
    ) -> GeneralShoppingDecisionDraft:
        async with self._validation_session() as session:
            repository = SearchSourceRepository(session)
            product_repo = ProductRepository(session)
            run_products = await product_repo.list_canonical_products_for_run(
                input_data.run_id
            )
            run_listings = await product_repo.list_product_listings_for_run(
                input_data.run_id
            )
            persisted_trust = await ResultRepository(
                session
            ).list_listing_trust_assessments(input_data.run_id)
            sources = {
                s.source_id: s
                for s in await repository.list_search_results(input_data.run_id)
            }
            snapshots = {
                s.source_id: s
                for s in await repository.list_source_snapshots(input_data.run_id)
            }
            snapshot_by_search_id = {
                source_id: await repository.get_snapshot_for_search_result(
                    input_data.run_id, source_id
                )
                for source_id in sources
            }
            evidence = {
                e.evidence_id: e
                for e in await repository.list_source_evidence(input_data.run_id)
            }
        candidates: list[GeneralShoppingCandidate] = []
        for choice in model.candidates[:8]:
            references: list[GeneralShoppingEvidence] = []
            for evidence_id in choice.evidence_ids:
                item = evidence.get(evidence_id)
                recorded_quote_ids = tools.recorded_quote_ids | (
                    technology_tools.recorded_quote_ids
                    if technology_tools
                    else frozenset()
                )
                recorded_quote_ids |= frozenset(
                    quote_id
                    for specialist in (specialist_tools or {}).values()
                    for quote_id in specialist.recorded_quote_ids
                )
                if item is None or evidence_id not in recorded_quote_ids:
                    continue
                snapshot = snapshots.get(item.source_id)
                if snapshot is None:
                    continue
                source = next(
                    (
                        sources[source_id]
                        for source_id, linked in snapshot_by_search_id.items()
                        if linked is not None and linked.source_id == snapshot.source_id
                    ),
                    None,
                )
                if source is None or snapshot.quality.level == SourceQualityLevel.WEAK:
                    continue
                source_type = source.source_type
                assessment = score_source_quality(
                    str(source.url),
                    SourceQualityMetadata(
                        target_region_code=(
                            input_data.brief.region.region.country_code
                            if input_data.brief.region is not None
                            else None
                        ),
                        evidence_context=SourceEvidenceContext.GENERAL,
                    ),
                )
                if assessment.excluded:
                    continue
                if (
                    source_type == SourceType.SEARCH_RESULT
                    or snapshot.quality.level == SourceQualityLevel.UNKNOWN
                ):
                    if assessment.quality.level in {
                        SourceQualityLevel.WEAK,
                        SourceQualityLevel.UNKNOWN,
                    }:
                        continue
                    if source_type == SourceType.SEARCH_RESULT:
                        source_type = {
                            SourceClass.REVIEW_TESTING: SourceType.PROFESSIONAL_REVIEW,
                            SourceClass.REVIEW_EDITORIAL: SourceType.PROFESSIONAL_REVIEW,
                            SourceClass.OFFICIAL_MANUFACTURER: SourceType.OFFICIAL_BRAND_PAGE,
                            SourceClass.OFFICIAL_STORE_REGIONAL: SourceType.OFFICIAL_BRAND_PAGE,
                            SourceClass.ESTABLISHED_RETAILER_FIRST_PARTY: SourceType.RETAILER_LISTING,
                            SourceClass.ESTABLISHED_RETAILER_MIXED: SourceType.RETAILER_LISTING,
                            SourceClass.OPEN_MARKETPLACE: SourceType.RETAILER_LISTING,
                        }.get(assessment.source_class, source_type)
                if (
                    choice.name.casefold()
                    not in (item.claim + " " + (snapshot.title or "")).casefold()
                ):
                    continue
                references.append(
                    GeneralShoppingEvidence(
                        source_id=source.source_id,
                        snapshot_id=snapshot.source_id,
                        evidence_id=item.evidence_id,
                        url=source.url,
                        source_type=source_type,
                        quote=item.claim,
                    )
                )
            if references:
                candidates.append(
                    GeneralShoppingCandidate(
                        name=choice.name, evidence=tuple(references)
                    )
                )
        selected = next(
            (c for c in candidates if c.name == model.selected_candidate_name), None
        )
        enough = False
        if selected is not None:
            listing_trust = assess_run_listings(
                run_products, run_listings, persisted_trust
            )
            selected_source_ids = {
                source_id
                for item in selected.evidence
                for source_id in (item.source_id, item.snapshot_id)
            }
            if any(
                listing_trust[listing.listing_id].level == ListingTrustLevel.SUSPICIOUS
                for listing in run_listings
                if selected_source_ids.intersection(listing.source_ids)
            ):
                return GeneralShoppingDecisionDraft(
                    category=model.category,
                    specialist_helpful=model.specialist_helpful,
                    outcome=GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE,
                    candidates=tuple(candidates),
                    evidence_gaps=(
                        "A cited listing has suspicious seller or listing signals.",
                    ),
                    hosted_lead_source_ids=tuple(c.source_id for c in citations),
                    rationale="There is not a safe, checked listing to recommend yet.",
                )
            domains = {urlsplit(str(e.url)).hostname for e in selected.evidence}
            types = {e.source_type for e in selected.evidence}
            enough = (
                len(domains) >= 2
                and SourceType.PROFESSIONAL_REVIEW in types
                and bool(
                    types
                    & {
                        SourceType.PRODUCT_PAGE,
                        SourceType.RETAILER_LISTING,
                        SourceType.OFFICIAL_BRAND_PAGE,
                    }
                )
            )
        if enough and selected is not None:
            candidates_by_name = {item.name: item for item in candidates}
            validated_modes = []
            seen_modes = set()
            for mode in model.mode_selections:
                candidate = candidates_by_name.get(mode.candidate_name)
                if (
                    candidate is None
                    or mode.mode in seen_modes
                    or mode.mode == RecommendationMode.BEST_OVERALL
                    or not set(mode.evidence_ids).issubset(
                        {item.evidence_id for item in candidate.evidence}
                    )
                ):
                    continue
                seen_modes.add(mode.mode)
                validated_modes.append(mode)
            return GeneralShoppingDecisionDraft(
                category=model.category,
                specialist_helpful=model.specialist_helpful,
                outcome=GeneralShoppingOutcome.DRAFT,
                candidates=tuple(candidates),
                mode_selections=tuple(validated_modes),
                selected_candidate_name=selected.name,
                hosted_lead_source_ids=tuple(c.source_id for c in citations),
                rationale=(
                    f"{selected.name} has cited product/listing and independent review "
                    "page excerpts. Price, regional availability, and seller trust still need checks."
                ),
            )
        return GeneralShoppingDecisionDraft(
            category=model.category,
            specialist_helpful=model.specialist_helpful,
            outcome=GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE,
            candidates=tuple(candidates),
            evidence_gaps=(
                model.evidence_gap
                or "A fetched product/listing page and independent review were not both verified.",
            ),
            hosted_lead_source_ids=tuple(c.source_id for c in citations),
            rationale="There is not enough checked evidence to choose a product yet.",
        )

    @asynccontextmanager
    async def _validation_session(self) -> AsyncIterator[AsyncSession]:
        if self.shared_session is not None:
            yield self.shared_session
        else:
            assert self.session_factory is not None
            async with self.session_factory() as session:
                yield session

    @staticmethod
    def _insufficient(
        input_data: GeneralShoppingAgentInput,
        category: str,
        specialist_helpful: bool,
        gap: str,
    ) -> GeneralShoppingDecisionDraft:
        del input_data
        return GeneralShoppingDecisionDraft(
            category=category,
            specialist_helpful=specialist_helpful,
            outcome=GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE,
            evidence_gaps=(gap,),
            rationale="There is not enough checked evidence to choose a product yet.",
        )
