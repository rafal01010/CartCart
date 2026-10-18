"""Model-running general shopping owner for live shopping runs and workbench."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Protocol

from agents import (
    Agent,
    AgentHooks,
    FunctionTool,
    Handoff,
    ModelSettings,
    RunConfig,
    Tool,
    handoff,
)
from agents.exceptions import UserError
from agents.items import HandoffOutputItem
from agents.tool_context import ToolContext
from pydantic import Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.token_policy import CompletionPurpose, OWNER_START_TOKENS, scaled_tokens
from app.agents.decision_sources import consultation_source_packets, merge_source_packets, select_decision_sources, source_packets
from app.agents.context_management import (
    BoundedRunner,
    ContextBudgetExceeded,
    completion_instructions,
    FinalOutputFailure,
    context_budget_failure,
    context_events,
    active_budget,
    managed_owner_context,
    funded_scope_limit,
)
from app.agents.contracts import (
    GeneralShoppingAgentInput,
    GeneralShoppingCandidate,
    GeneralShoppingDecisionDraft,
    GeneralShoppingEvidence,
    GeneralShoppingModeSelection,
    GeneralShoppingOutcome,
)
from app.schemas.analysis import RecommendationChoiceGroup
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
from app.agents.owner_research import (
    OwnerResearchContext,
    OwnerResearchState,
    assess_run_listings,
)
from app.agents.research_guidance import FINAL_OPTION_SET_GUIDANCE, SHOPPER_ADVICE_GUIDANCE
from app.agents.research_tools import (
    AgentResearchTools,
    PersistedHostedCitation,
    _safe_public_result_url,
)
from app.core.settings import Settings
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.providers.contracts import SourceAllowAvoidPolicy
from app.schemas.base import CartCartBaseModel
from app.schemas.ids import SourceId
from app.schemas.regions import RegionCode
from app.schemas.search_sources import SourceIntelligenceCapability
from app.services.shopping_intent import RESEARCH_QUERY_GUIDANCE, research_context


OWNER_DECISION_GUIDANCE = (
    "Recommend by default from available research and buyer preferences. "
    + FINAL_OPTION_SET_GUIDANCE
    + "Mark each candidate's choice_group as primary or runner_up. "
    "Use candidate rationale and tradeoff fields for shopper advice. Unknowns and warnings retain internal diagnostics only. A decisive winner and mode selections are optional. "
    "Use the overall rationale for the recommendation. Where product age matters, explain known released generation, age or support differences from available dates. A confirmed upcoming launch may inform a useful tradeoff. "
    "Keep this JSON compact. Omit unnecessary mode selections, warnings, unknowns and evidence-gap narratives; use empty optional collections when they add no useful decision information. "
    "Write advice as plain prose. Put optional source associations in their fields; source links are shown below the advice. "
    "Search snippets, fetched pages and saved specialist context can inform your judgment without recorded quotes. "
    "Citations and reviews are optional. Associate real supplied evidence_ids or source_ids when useful. "
    "Source quality, domain reputation, trust assessments and cautions are advisory. Weigh actual material "
    "adverse findings by scope and credibility. Missing reviews, warranty, seller details or price are unknowns, "
    "not reasons alone to exclude a product. An official store is acceptable seller context. "
    "Consider the requested budget, known price and currency. Slightly over-budget alternatives are allowed "
    "with a clear explanation. Unknown or incomparable prices cannot be labeled within budget. "
    "Do not invent facts, current prices, reviews, links or quotations. Distinguish snippets, page text and "
    "manufacturer claims. A paraphrase is not a verbatim quotation. Write clear shopper-facing advice and "
    "qualify a judgment when uncertainty affects a meaningful product difference. Discourage a specific purchase when strong adverse information warrants it and "
    "offer useful alternatives when possible. "
    + SHOPPER_ADVICE_GUIDANCE
)

SAVED_OWNER_OUTPUT_TOKENS = scaled_tokens(5000)


def _transport_owner_usage(
    events: tuple[dict[str, Any], ...], owners: set[str]
) -> dict[str, int | None] | None:
    calls = [
        item["output"] for item in events
        if item.get("input", {}).get("agent") in owners
        and item.get("output", {}).get("charged_tokens") is not None
    ]
    if not calls:
        return None
    return {
        key: sum(call["actual_" + key] for call in calls)
        if all(call.get("actual_" + key) is not None for call in calls)
        else None
        for key in ("input_tokens", "output_tokens", "total_tokens")
    }


class GeneralCandidateSelection(CartCartBaseModel):
    name: str = Field(min_length=1, max_length=200)
    choice_group: RecommendationChoiceGroup = Field(description="Select strong suitable options as primary first, then worthwhile secondary alternatives as runner_up. A preferred winner does not remove other primaries.")
    evidence_ids: tuple[SourceId, ...] = Field(default_factory=tuple, max_length=8)
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple, max_length=8)
    rationale: str | None = Field(default=None, max_length=1500, description="One concise benefit sentence in plain prose. No input narration, links or citation markers.")
    tradeoff: str | None = Field(default=None, max_length=1000, description="One useful comparative limitation in plain prose. No links, citation markers or generic missing-data warnings.")
    unknowns: tuple[str, ...] = Field(default_factory=tuple, max_length=8)


class GeneralModelOutput(CartCartBaseModel):
    rationale: str = Field(min_length=1, max_length=1500, description="Direct what-to-buy advice in two or three short plain sentences. Name the strongest useful choices and worthwhile secondary alternatives with their tradeoffs, without input echoes, links or citation markers.")
    category: str = Field(min_length=1, max_length=200)
    specialist_helpful: bool = False
    candidates: tuple[GeneralCandidateSelection, ...] = Field(default_factory=tuple, max_length=5, description="The useful selected option set with up to three strong primaries and two worthwhile runners. Select groups before an optional preferred winner. Do not fill places with weak matches.")
    mode_selections: tuple[GeneralShoppingModeSelection, ...] = Field(
        default_factory=tuple, max_length=4
    )
    selected_candidate_name: str | None = Field(default=None, description="Optional preferred winner among the selected primary choices. Null is valid. This preference does not discard other useful primaries or change their order.")
    evidence_gap: str | None = Field(default=None, max_length=500)
    warnings: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    hosted_lead_urls: tuple[str, ...] = Field(default_factory=tuple, max_length=8)

    @field_validator("rationale")
    @classmethod
    def _nonblank_rationale(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Primary rationale must not be blank.")
        return value

    @model_validator(mode="after")
    def _valid_choice_groups(self) -> "GeneralModelOutput":
        names = [candidate.name.casefold() for candidate in self.candidates]
        if len(set(names)) != len(names):
            raise ValueError("candidate names must be unique across choice groups.")
        primary = [candidate for candidate in self.candidates if candidate.choice_group == "primary"]
        runners = [candidate for candidate in self.candidates if candidate.choice_group == "runner_up"]
        if len(primary) > 3 or len(runners) > 2:
            raise ValueError("author at most three primary choices and two runners-up.")
        if self.candidates and not primary:
            raise ValueError("candidate output requires at least one primary choice.")
        if self.selected_candidate_name is not None and self.selected_candidate_name.casefold() not in {
            candidate.name.casefold() for candidate in primary
        }:
            raise ValueError("the selected candidate must be a primary choice.")
        return self


class OwnerHandoffContext(CartCartBaseModel):
    reason: str = Field(min_length=10, max_length=300)

    @field_validator("reason")
    @classmethod
    def _nonblank_reason(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 10:
            raise ValueError("Handoff reason must not be blank.")
        return stripped


def _rejected_handoff_diagnostic(
    source_agent: str,
    target_agent: str,
    category: str,
    requested_route: tuple[str, ...],
    buyer_route: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "source_agent": source_agent,
        "target_agent": target_agent,
        "requested_category": category,
        "requested_category_length": len(category),
        "requested_route": list(requested_route),
        "buyer_route": list(buyer_route),
    }


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
        return await BoundedRunner.run(
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
            by_name = {
                tool.name: tool
                for tool in agent.tools
                if isinstance(tool, FunctionTool)
            }

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
                rationale=(
                    "Oak walking cane was comfortable in the walking test and is a wooden walking aid."
                    if evidence_ids and candidate_name == "Oak walking cane"
                    else "There is not enough checked evidence to choose a product yet."
                ),
                category="garden seat"
                if "garden seat" in query.casefold()
                else "walking cane",
                candidates=(
                    GeneralCandidateSelection(
                        name=candidate_name, choice_group="primary", evidence_ids=tuple(evidence_ids)
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
                rationale="There is not enough checked evidence to choose a product yet.",
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

    @managed_owner_context
    async def resume_saved(
        self,
        input_data: GeneralShoppingAgentInput,
        *,
        owner_agent_name: str,
        activity: tuple[dict[str, Any], ...],
        source_retry: dict[str, Any] | None = None,
    ) -> GeneralShoppingDecisionDraft:
        """Finish saved advice, optionally resuming an explicitly requested source consultation."""
        budget = active_budget()
        context_start = len(budget.events) if budget else 0
        region_code = (
            input_data.brief.region.region.country_code
            if input_data.brief.region is not None
            else None
        )
        tools = (
            self.regional_research_tools_factory(input_data.run_id, region_code)
            if self.regional_research_tools_factory is not None
            else self.research_tools_factory(input_data.run_id)
            if self.research_tools_factory is not None
            else None
        )
        if tools is None or tools.required_region_code != region_code:
            raise ValueError(
                "Saved research requires matching run-scoped source access."
            )
        tools.set_brief(input_data.brief)
        quotes = await tools.restore_recorded_quotes(activity)
        self._activity = tuple(item for item in activity if item.get("tool_name") != "context_call")
        source_receipt = None
        source_activity: tuple[dict[str, Any], ...] = ()
        try:
            if source_retry is not None:
                if self.source_intelligence_manager is None:
                    raise ValueError("Focused source retry requires the configured source manager.")
                saved = self.source_intelligence_manager.load_retry_input(input_data.run_id, source_retry["reuse_key"])
                if saved.allowed_capabilities != (SourceIntelligenceCapability.VIDEO_REVIEW,):
                    raise ValueError("Focused durable retry supports video reviews only.")
                if saved.brief != input_data.brief:
                    raise ValueError("Source retry brief changed.")
                helpers = OwnerResearchContext(
                    agent_name=owner_agent_name, run_id=input_data.run_id,
                    brief=input_data.brief, region_code=region_code,
                    session_factory=self.session_factory, shared_session=self.shared_session,
                    source_manager=self.source_intelligence_manager,
                    source_policy=tools.source_policy,
                    allowed_quote_ids=lambda: frozenset(SourceId(q["evidence_id"]) for q in quotes),
                )
                source_receipt = await helpers.consult_source(
                    saved.allowed_capabilities[0], product_name=source_retry["candidate_name"],
                    product_id=source_retry.get("consult_product_id"),
                    evidence_id=source_retry.get("consult_evidence_id"),
                    expected_reuse_key=source_retry["reuse_key"],
                )
                source_activity = tuple(helpers.activity)
                self._activity += source_activity
            output, result = await self._decide_recorded(
                input_data, owner_agent_name, quotes, source_receipt=source_receipt
            )
        except Exception as exc:
            self._activity += (
                {
                    "tool_name": "general_owner_resume",
                    "status": "failed",
                    "input": {"agent": owner_agent_name, "research_enabled": False},
                    "output": {
                        "error_type": type(exc).__name__, "error_message": str(exc)[:2000],
                        "usage": _transport_owner_usage(context_events(context_start), {owner_agent_name}),
                    },
                },
            )
            raise RuntimeError("The saved shopping advice could not finish. Your gathered information is saved. Try again.") from exc
        draft = await self._validated_draft(input_data, output, tools, ())
        usage = getattr(getattr(result, "context_wrapper", None), "usage", None)
        self._activity = (
            *(item for item in activity if item.get("tool_name") != "context_call"),
            *source_activity,
            {
                "tool_name": "general_owner",
                "status": draft.outcome.value,
                "input": {"agent": owner_agent_name, "research_enabled": False},
                "output": {
                    "restored_quote_count": len(quotes),
                    "research_reused": True,
                    "max_output_tokens_per_turn": SAVED_OWNER_OUTPUT_TOKENS,
                    "selected_candidate_name": draft.selected_candidate_name,
                    "last_agent": owner_agent_name,
                    "last_agent_model": getattr(
                        getattr(result, "last_agent", None), "model", None
                    ),
                    "failure_type": None,
                    "usage": {
                        key: getattr(usage, key, None)
                        for key in ("input_tokens", "output_tokens", "total_tokens")
                    },
                },
            },
        )
        self._activity += tuple(item for item in context_events(context_start) if item.get("tool_name") == "decision_source_selection")
        return draft.model_copy(update={"owner_agent_name": owner_agent_name})

    async def _recorded_decision_input(
        self,
        input_data: GeneralShoppingAgentInput,
        *,
        consultation_bundles: tuple[dict[str, Any], ...] = (),
        candidate_names: dict[str, str] | None = None,
        prior_gaps: tuple[str, ...] = (),
        source_receipt: dict[str, Any] | None = None,
    ) -> str:
        async with self._validation_session() as session:
            snapshots = {
                str(item.source_id): item
                for item in await SearchSourceRepository(session).list_source_snapshots(
                    input_data.run_id
                )
            }
            repository = SearchSourceRepository(session)
            source_results = await repository.list_search_results(input_data.run_id)
            source_evidence = await repository.list_source_evidence(input_data.run_id)
            product_repo = ProductRepository(session)
            products = await product_repo.list_canonical_products_for_run(
                input_data.run_id
            )
            listings = await product_repo.list_product_listings_for_run(
                input_data.run_id
            )
            decision_sources = select_decision_sources(
                input_data.brief,
                merge_source_packets((
                    *source_packets(input_data.brief, source_results, tuple(snapshots.values()), source_evidence, products),
                    *consultation_source_packets(consultation_bundles, candidate_names or {}),
                )),
            )
            trust = assess_run_listings(
                products,
                listings,
                await ResultRepository(session).list_listing_trust_assessments(
                    input_data.run_id
                ),
            )
        listing_cautions = [
            {
                "listing_id": str(item.listing_id),
                "product_id": str(item.product_id),
                "source_ids": [str(identifier) for identifier in item.source_ids],
                "price": item.price.model_dump(mode="json") if item.price else None,
                "over_budget_amount": (
                    str(item.price.amount - input_data.brief.budget.amount.amount)
                    if item.price
                    and input_data.brief.budget
                    and item.price.currency == input_data.brief.budget.amount.currency
                    and item.price.amount > input_data.brief.budget.amount.amount
                    else None
                ),
                "trust_level": trust[item.listing_id].level.value,
                "summary": trust[item.listing_id].summary,
                "red_flags": list(trust[item.listing_id].red_flags),
            }
            for item in listings
        ]
        return json.dumps(
            {
                "brief": input_data.brief.model_dump(mode="json"),
                "user_added_products": [
                    item.model_dump(mode="json") for item in input_data.user_added_products
                ],
                "current_utc_date": datetime.now(timezone.utc).date().isoformat(),
                "decision_sources": decision_sources.model_dump(mode="json"),
                "saved_products": [item.model_dump(mode="json") for item in products],
                "listing_cautions": listing_cautions,
                "prior_evidence_gaps": prior_gaps,
                "source_consultation": source_receipt,
            }
        )

    async def _decide_recorded(
        self,
        input_data: GeneralShoppingAgentInput,
        owner_agent_name: str,
        quotes: tuple[dict[str, Any], ...],
        *,
        prior_gaps: tuple[str, ...] = (),
        source_receipt: dict[str, Any] | None = None,
    ) -> tuple[GeneralModelOutput, Any]:
        configuration = build_openai_agent_run_configuration(
            self.settings,
            agent_name=owner_agent_name,
            run_id=str(input_data.run_id),
        )
        agent = Agent(
            name=owner_agent_name,
            model=configuration.model,
            instructions=(
                "Resume the shopping decision from the supplied saved research and buyer preferences. "
                "Research is closed. " + OWNER_DECISION_GUIDANCE + " "
                "Sources, citations, reviews, purchase details and exact quotations are optional. "
                "Treat source reputation, trust assessments and caution previews as advisory context. "
                "Weigh strong actual adverse findings and their scope; missing information is not adverse evidence. "
                "Consider budget, known prices, currencies and over-budget amounts. A slightly over-budget option "
                "is allowed with a clear explanation. Unknown or incomparable prices are not within budget. "
                "Do not invent current facts, links, reviews, quotations or prices. Attribute manufacturer claims. "
                "Do not present a paraphrase as a quotation. "
                "Only use supplied IDs when associating optional sources. Use today's date for known product age."
            ),
            output_type=GeneralModelOutput,
            model_settings=ModelSettings(
                max_tokens=SAVED_OWNER_OUTPUT_TOKENS, include_usage=True
            ),
        )
        apply_openai_agent_run_profile(agent, configuration)
        result = await asyncio.wait_for(
            self.model_runner.run(
                agent,
                await self._recorded_decision_input(
                    input_data, prior_gaps=prior_gaps, source_receipt=source_receipt
                ),
                run_config=RunConfig(
                    tracing_disabled=not configuration.tracing_enabled,
                    trace_include_sensitive_data=configuration.trace_include_sensitive_data,
                    workflow_name=configuration.trace_workflow_name,
                    trace_metadata=configuration.trace_metadata,
                ),
                max_turns=configuration.max_turns,
            ),
            timeout=configuration.timeout_seconds,
        )
        output = GeneralModelOutput.model_validate(
            getattr(result, "final_output", result)
        )
        return output, result

    @managed_owner_context
    async def run(
        self, input_data: GeneralShoppingAgentInput
    ) -> GeneralShoppingDecisionDraft:
        configuration = build_openai_agent_run_configuration(
            self.settings,
            agent_name="GeneralShoppingAgent",
            run_id=str(input_data.run_id),
        )
        budget = active_budget()
        context_start = len(budget.events) if budget else 0
        spent_start = budget.spent if budget else 0
        model_input = json.dumps(
            {
                **input_data.model_dump(mode="json"),
                "research_context": research_context(input_data.brief),
            }
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
        if tools is not None:
            tools.set_brief(input_data.brief)
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
        if tools is not None and technology_tools is not None:
            tools.share_run_state(technology_tools)
        if technology_tools is not None:
            technology_tools.set_brief(input_data.brief)
        brief_text = " ".join(
            (input_data.brief.original_query, input_data.brief.category or "")
        )
        buyer_route = DEFAULT_AGENT_CATALOG.route_product_analysis(brief_text).agent_path
        known_categories = set(DEFAULT_AGENT_CATALOG.product_category_routes) | set(
            DEFAULT_AGENT_CATALOG.technology_category_keywords
        )
        brief_category = " ".join((input_data.brief.category or "").lower().split())
        trace_category = (
            brief_category if brief_category in known_categories
            else DEFAULT_AGENT_CATALOG.require(buyer_route[-1]).routing_categories[0]
        )
        owner_research_state = OwnerResearchState()
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
                    research_state=owner_research_state,
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
                region_code=region_code,
                source_policy=tools.source_policy,
            )
            if configuration.mode == OpenAIAgentRuntimeMode.LIVE and tools is not None
            else None
        )
        sdk_tools: list[Tool] = (
            list(tools.sdk_owner_tools()) if tools is not None else []
        )
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
        specialist_requests: list[tuple[str, OwnerHandoffContext]] = []
        observed_handoffs: list[tuple[str, str]] = []
        rejected_specialist: str | None = None
        rejected_handoff: dict[str, Any] | None = None
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
                    region_code=region_code,
                    source_policy=specialist_research.source_policy,
                )
                if configuration.mode == OpenAIAgentRuntimeMode.LIVE
                and specialist_research is not None
                else None
            )
            owner_hosted_tools[specialist_name] = specialist_hosted
            specialist_sdk_tools: list[Tool] = (
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
                    RESEARCH_QUERY_GUIDANCE
                    + OWNER_DECISION_GUIDANCE
                    + " You now own this product shopping request. Finish with GeneralModelOutput. "
                    + _SPECIALIST_INSTRUCTIONS[specialist_name]
                    + " The parent agents retain your decision. Do not request further handoffs."
                ),
                output_type=GeneralModelOutput,
                tools=specialist_sdk_tools,
                model_settings=ModelSettings(
                    max_tokens=scaled_tokens(1500),
                    include_usage=True,
                    tool_choice="auto",
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
            specialist_name: str, request: OwnerHandoffContext
        ) -> None:
            nonlocal rejected_specialist, rejected_handoff
            if specialist_requests or not handoff_requests:
                rejected_specialist = specialist_name
                raise UserError("Specialist handoff exceeds the declared hierarchy.")
            requested_route = (technology_agent.name, specialist_name)
            if buyer_route != requested_route:
                rejected_specialist = specialist_name
                rejected_handoff = _rejected_handoff_diagnostic(
                    technology_agent.name,
                    specialist_name,
                    trace_category,
                    requested_route,
                    buyer_route,
                )
                raise UserError(
                    "Specialist handoff does not match the buyer's category."
                )
            specialist_requests.append((specialist_name, request))

        def specialist_callback(
            name: str,
        ) -> Callable[[Any, OwnerHandoffContext], None]:
            def callback(
                _context: Any, request: OwnerHandoffContext
            ) -> None:
                on_specialist_handoff(name, request)

            return callback

        specialist_handoffs: list[Agent[Any] | Handoff[Any, Any]] = [
            handoff(
                specialist_agents[name],
                tool_description_override=(
                    f"Transfer a matching {', '.join(DEFAULT_AGENT_CATALOG.require(name).routing_categories)} "
                    "shopping request to its product specialist for final ownership. "
                    "Do not use for broad or other technology requests."
                ),
                input_type=OwnerHandoffContext,
                on_handoff=specialist_callback(name),
            )
            for name in approved_specialists
        ]
        technology_sdk_tools: list[Tool] = (
            list(technology_tools.sdk_owner_tools()) if technology_tools else []
        )
        if owner_research:
            technology_sdk_tools.extend(
                owner_research["TechnologyDomainAnalystAgent"].sdk_tools()
            )
        technology_agent = Agent(
            name="TechnologyDomainAnalystAgent",
            model=technology_configuration.model,
            instructions=(
                RESEARCH_QUERY_GUIDANCE
                + OWNER_DECISION_GUIDANCE
                + " You now own this whole technology shopping request. Finish broad technology "
                "categories yourself. Hand off early only to an attached specialist for this category. "
                "A phone request belongs to SmartphoneSpecialistAgent. Preserve the buyer's preferences "
                "and original question. Do not return control to General."
            ),
            output_type=GeneralModelOutput,
            tools=technology_sdk_tools,
            model_settings=ModelSettings(
                max_tokens=scaled_tokens(1800), include_usage=True, tool_choice="auto"
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
        handoff_requests: list[OwnerHandoffContext] = []

        def on_technology_handoff(
            _context: Any, request: OwnerHandoffContext
        ) -> None:
            nonlocal rejected_handoff
            permitted = DEFAULT_AGENT_CATALOG.require(
                "GeneralShoppingAgent"
            ).target_handoff_agent_names
            if technology_agent.name not in permitted or handoff_requests:
                raise UserError(
                    "Technology handoff is not allowed or exceeds depth one."
                )
            requested_route = (technology_agent.name,)
            if buyer_route[0] != technology_agent.name:
                rejected_handoff = _rejected_handoff_diagnostic(
                    agent.name,
                    technology_agent.name,
                    trace_category,
                    requested_route,
                    buyer_route,
                )
                raise UserError(
                    "Technology handoff does not match the shopper's request."
                )
            handoff_requests.append(request)

        agent = Agent(
            name="GeneralShoppingAgent",
            model=configuration.model,
            instructions=(
                RESEARCH_QUERY_GUIDANCE
                + OWNER_DECISION_GUIDANCE
                + " Own ordinary shopping categories, including those without specialists. "
                "Finish non-technology requests yourself. For technology, transfer early to "
                "TechnologyDomainAnalystAgent when deeper category expertise helps. The receiving "
                "owner may delegate to its attached product specialist and owns the final decision."
            ),
            output_type=GeneralModelOutput,
            tools=sdk_tools,
            model_settings=ModelSettings(
                max_tokens=scaled_tokens(2500), include_usage=True, tool_choice="auto"
            ),
            handoffs=[
                handoff(
                    technology_agent,
                    tool_description_override=(
                        "Transfer a technology shopping request for deeper technology "
                        "fit analysis and final ownership. Do not use for other categories."
                    ),
                    input_type=OwnerHandoffContext,
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
        failure_type: str | None = None
        failure_code: str | None = None
        failure_message: str | None = None
        failure_hosted_calls: tuple[dict[str, Any], ...] = ()
        raw_result: Any = None
        completion_stage = "owner_sdk"
        failed_run_usage: Any = None
        recovered_run_usage: Any = None
        owner_name = agent.name
        handoff_activity: tuple[dict[str, Any], ...] = ()
        handoff_confirmed = False
        owner_timeout = configuration.timeout_seconds
        started_at = asyncio.get_running_loop().time()

        def source_tokens() -> int:
            return sum(
                item.get("output", {}).get("total_tokens") or 0
                for state in owner_research.values()
                for item in state.activity
                if item.get("tool_name") == "consult_source_intelligence"
            )

        def owner_tokens(sdk_tokens: int) -> int:
            if budget is not None and context_events(context_start):
                return budget.spent - spent_start
            return sdk_tokens + source_tokens()

        def validated_handoffs(result: Any) -> tuple[str, tuple[dict[str, Any], ...]]:
            completed = tuple(
                item
                for item in getattr(result, "new_items", ())
                if isinstance(item, HandoffOutputItem)
            )
            requested: list[
                tuple[
                    str, str, OwnerHandoffContext
                ]
            ] = (
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
                            "technology_category" if depth == 1 else "product_category": trace_category,
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
                    model_input,
                    run_config=run_config,
                    max_turns=configuration.max_turns,
                ),
                timeout=owner_timeout,
            )
            completion_stage = "handoff_validation"
            owner_name, handoff_activity = validated_handoffs(raw_result)
            handoff_confirmed = bool(handoff_activity)
            sdk_usage = getattr(
                getattr(raw_result, "context_wrapper", None), "usage", None
            )
            if not context_events(context_start) and owner_tokens(
                getattr(sdk_usage, "total_tokens", 0) or 0
            ) > funded_scope_limit("owner", OWNER_START_TOKENS):
                raise ContextBudgetExceeded("Owner run exceeded its token budget.")
            completion_stage = "output_validation"
            model_output = GeneralModelOutput.model_validate(
                getattr(raw_result, "final_output", raw_result)
            )
            if hosted_tool is not None:
                completion_stage = "hosted_discovery_validation"
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
                    if isinstance(item, Handoff)
                }
                for response in raw_result.raw_responses:
                    response_groups[response_owner].append(response)
                    for item in getattr(response, "output", ()):
                        name = getattr(item, "name", None)
                        target = (
                            handoff_targets.get(name) if isinstance(name, str) else None
                        )
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
                if (
                    sum(call.action == "search" for _, call in all_calls) > 6
                    or len(all_calls) > 18
                ):
                    raise ValueError("Hosted-search call limit or completion failed.")
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
                completion_stage = "canonical_candidate_validation"
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
                draft = GeneralShoppingDecisionDraft(
                    category=model_output.category,
                    specialist_helpful=model_output.specialist_helpful,
                    outcome=(
                        GeneralShoppingOutcome.DRAFT
                        if model_output.candidates
                        else GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE
                    ),
                    candidates=tuple(
                        GeneralShoppingCandidate(
                            name=item.name,
                            choice_group=item.choice_group,
                            rationale=item.rationale,
                            tradeoff=item.tradeoff,
                            unknowns=item.unknowns,
                        )
                        for item in model_output.candidates
                    ),
                    mode_selections=model_output.mode_selections,
                    selected_candidate_name=model_output.selected_candidate_name,
                    rationale=model_output.rationale,
                    warnings=model_output.warnings,
                )
        except (Exception, asyncio.TimeoutError) as exc:
            budget_failure = context_budget_failure(exc)
            failure_type = type(budget_failure or exc).__name__
            failure_message = str(budget_failure or exc)[:2000]
            failure_code = (
                "context_budget_exceeded"
                if budget_failure is not None
                else {
                    "Specialist handoff exceeds the declared hierarchy.": "specialist_depth_exceeded",
                    "Specialist handoff does not match the buyer's category.": "specialist_category_mismatch",
                    "Technology handoff is not allowed or exceeds depth one.": "technology_depth_exceeded",
                    "Technology handoff does not match the shopper's request.": "technology_category_mismatch",
                }.get(str(exc), "unclassified_sdk_error")
                if isinstance(exc, UserError)
                else "context_budget_exceeded"
                if isinstance(exc, ContextBudgetExceeded)
                else None
            )
            gap = f"Shopping research could not finish ({type(exc).__name__})."
            error_data = getattr(exc, "run_data", None)
            failure_hosted_calls = tuple(
                {
                    "call_id": call.call_id,
                    "action": call.action,
                    "status": call.status,
                    "source_urls": list(call.source_urls),
                }
                for call in read_hosted_web_search_activity(error_data).calls
            )
            error_usage = getattr(
                getattr(error_data, "context_wrapper", None), "usage", None
            )
            failed_run_usage = error_usage
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
                    contexts: list[
                        OwnerHandoffContext
                    ] = [
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
                                "technology_category" if index == 0 else "product_category": trace_category,
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
                            "technology_category" if failed_source == agent.name else "product_category": trace_category,
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
                            "product_category": trace_category,
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
                and owner_tokens(getattr(failed_run_usage, "total_tokens", 0) or 0)
                < funded_scope_limit("owner", OWNER_START_TOKENS)
                and budget_failure is None
                and not isinstance(exc, FinalOutputFailure)
            ):
                recovery_agent = technology_agent.clone(
                    tools=[],
                    handoffs=[],
                    model_settings=replace(
                        technology_agent.model_settings, tool_choice="none"
                    ),
                    hooks=None,
                    instructions=completion_instructions(
                        str(technology_agent.instructions), CompletionPurpose.OWNER
                    ),
                )
                try:
                    async with asyncio.timeout(remaining_seconds):
                        recovery_input = await self._recorded_decision_input(
                            input_data,
                            prior_gaps=(gap,),
                            consultation_bundles=tuple(payload for _, _, payload in owner_research_state.bundles.values()),
                            candidate_names=owner_research_state.candidate_names_by_product_id,
                            source_receipt={
                                "outcomes": [
                                    {
                                        key: receipt[key]
                                        for key in ("status", "outcome", "capability", "consultation_id")
                                        if key in receipt
                                    }
                                    for receipt in owner_research_state.completed_consultations.values()
                                ],
                            },
                        )
                        recovery_result = await self.model_runner.run(
                            recovery_agent,
                            recovery_input,
                            run_config=run_config,
                            max_turns=2,
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
                    if not context_events(context_start) and (
                        owner_tokens(
                            (getattr(failed_run_usage, "total_tokens", 0) or 0)
                            + (getattr(recovery_usage, "total_tokens", 0) or 0)
                        )
                        > funded_scope_limit("owner", OWNER_START_TOKENS)
                    ):
                        raise ContextBudgetExceeded(
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
                    gap = None
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
                    recovery_budget_failure = context_budget_failure(recovery_exc)
                    if recovery_budget_failure is not None:
                        failure_type = type(recovery_budget_failure).__name__
                        failure_code = "context_budget_exceeded"
                        gap = "Shopping research could not safely complete within its token budget."
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
        combined_usage = _transport_owner_usage(
            context_events(context_start), {agent.name, technology_agent.name, *specialist_agents}
        ) or combined_usage
        nested_source_tokens = source_tokens()
        if not context_events(context_start) and owner_tokens(
            combined_usage["total_tokens"] or 0
        ) > funded_scope_limit("owner", OWNER_START_TOKENS):
            gap = "Shopping research exceeded its combined owner/source token budget."
            failure_type = "ContextBudgetExceeded"
            failure_code = "context_budget_exceeded"
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
                "status": "research_failed" if gap is not None else draft.outcome.value,
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
                    "failure_type": failure_type,
                    "failure_stage": completion_stage
                    if failure_type is not None
                    else None,
                    "failure_code": failure_code,
                    "error_message": failure_message,
                    "failed_hosted_calls": list(failure_hosted_calls),
                    "rejected_handoff": rejected_handoff,
                    "model": configuration.model,
                    "last_agent": draft.owner_agent_name,
                    "last_agent_model": (
                        specialist_configurations[draft.owner_agent_name].model
                        if draft.owner_agent_name in specialist_configurations
                        else technology_configuration.model
                        if draft.owner_agent_name == technology_agent.name
                        else configuration.model
                    ),
                    "max_turns": configuration.max_turns,
                    "max_output_tokens_per_turn": scaled_tokens(2500),
                    "active_owner_max_output_tokens": (
                        specialist_agents[
                            draft.owner_agent_name
                        ].model_settings.max_tokens
                        if draft.owner_agent_name in specialist_agents
                        else technology_agent.model_settings.max_tokens
                        if draft.owner_agent_name == technology_agent.name
                        else agent.model_settings.max_tokens
                    ),
                    "usage": {
                        **combined_usage,
                    },
                    "usage_complete": all(value is not None for value in combined_usage.values()),
                    "nested_source_tokens": nested_source_tokens,
                    "accounted_owner_tokens": owner_tokens(
                        combined_usage["total_tokens"] or 0
                    ),
                    "usage_accounting": "shared_transport"
                    if context_events(context_start)
                    else "sdk_owner_plus_source_aggregate",
                },
            },
        )
        self._activity += tuple(item for item in context_events(context_start) if item.get("tool_name") == "decision_source_selection")
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
        for choice in model.candidates:
            references: list[GeneralShoppingEvidence] = []
            for evidence_id in choice.evidence_ids:
                item = evidence.get(evidence_id)
                snapshot = snapshots.get(item.source_id) if item else None
                source = next(
                    (
                        sources[source_id]
                        for source_id, linked in snapshot_by_search_id.items()
                        if snapshot is not None
                        and linked is not None
                        and linked.source_id == snapshot.source_id
                    ),
                    None,
                )
                if item is not None and snapshot is not None and snapshot.video is not None and item.transcript_support and _safe_public_result_url(str(snapshot.url)):
                    references.append(GeneralShoppingEvidence(
                        source_id=snapshot.source_id, snapshot_id=snapshot.source_id,
                        evidence_id=item.evidence_id, url=snapshot.url,
                        source_type=snapshot.source_type, quote=item.claim,
                    ))
                    continue
                if (
                    item is None
                    or snapshot is None
                    or source is None
                    or not _safe_public_result_url(str(source.url))
                    or not _safe_public_result_url(str(snapshot.url))
                ):
                    continue
                references.append(
                    GeneralShoppingEvidence(
                        source_id=source.source_id,
                        snapshot_id=snapshot.source_id,
                        evidence_id=item.evidence_id,
                        url=source.url,
                        source_type=source.source_type,
                        quote=(
                            item.claim
                            if snapshot.extracted_content
                            and item.claim in snapshot.extracted_content.text
                            else ""
                        ),
                    )
                )
            for source_id in choice.source_ids:
                source = sources.get(source_id)
                video_snapshot = snapshots.get(source_id)
                if source is None and video_snapshot is not None and video_snapshot.video is not None and _safe_public_result_url(str(video_snapshot.url)):
                    if not any(reference.source_id == source_id for reference in references):
                        references.append(GeneralShoppingEvidence(
                            source_id=source_id, snapshot_id=source_id,
                            url=video_snapshot.url, source_type=video_snapshot.source_type,
                        ))
                    continue
                if (
                    source is None
                    or not _safe_public_result_url(str(source.url))
                    or any(reference.source_id == source_id for reference in references)
                ):
                    continue
                snapshot = snapshot_by_search_id.get(source_id)
                references.append(
                    GeneralShoppingEvidence(
                        source_id=source_id,
                        snapshot_id=snapshot.source_id if snapshot else None,
                        url=source.url,
                        source_type=source.source_type,
                    )
                )
            candidates.append(
                GeneralShoppingCandidate(
                    name=choice.name,
                    choice_group=choice.choice_group,
                    evidence=tuple(references),
                    rationale=choice.rationale,
                    tradeoff=choice.tradeoff,
                    unknowns=choice.unknowns,
                )
            )
        names = {candidate.name.casefold(): candidate for candidate in candidates}
        selected = names.get((model.selected_candidate_name or "").casefold())
        modes = []
        for mode in model.mode_selections:
            candidate = names.get(mode.candidate_name.casefold())
            if candidate is None:
                continue
            available = {item.evidence_id for item in candidate.evidence}
            modes.append(
                mode.model_copy(
                    update={
                        "candidate_name": candidate.name,
                        "evidence_ids": tuple(
                            identifier
                            for identifier in mode.evidence_ids
                            if identifier in available
                        ),
                    }
                )
            )
        return GeneralShoppingDecisionDraft(
            category=model.category,
            specialist_helpful=model.specialist_helpful,
            outcome=(
                GeneralShoppingOutcome.DRAFT
                if candidates
                else GeneralShoppingOutcome.INSUFFICIENT_EVIDENCE
            ),
            candidates=tuple(candidates),
            mode_selections=tuple(modes),
            selected_candidate_name=selected.name if selected else None,
            evidence_gaps=(model.evidence_gap,) if model.evidence_gap else (),
            hosted_lead_source_ids=tuple(c.source_id for c in citations),
            rationale=model.rationale,
            warnings=model.warnings,
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
