import asyncio
import json
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from agents import Agent, ModelSettings, RunConfig, Runner
from pydantic import Field, ValidationError

from app.agents.contracts import (
    DiscoveryAgentInput,
    DiscoveryAgentOutcome,
    DiscoveryAgentOutput,
    DiscoveryNextAction,
    DiscoverySourceDecision,
    DiscoverySourceKind,
)
from app.agents.research_tools import AgentResearchTools
from app.agents.openai_config import (
    apply_openai_agent_run_profile,
    build_openai_agent_run_configuration,
)
from app.core.settings import Settings
from app.schemas.base import CartCartBaseModel
from app.schemas.ids import SourceId
from app.schemas.search_sources import SearchResult


_EXCLUDED_RAW_FLAGS = frozenset(
    {
        "excluded",
        "source_policy_excluded",
        "excluded_by_source_policy",
    }
)


class DiscoveryModelRunner(Protocol):
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        """Run the SDK discovery agent and return its raw run result."""


class DiscoveryModelOutput(CartCartBaseModel):
    """Compact model response; persisted sources are reattached by backend code."""

    source_decisions: tuple[DiscoverySourceDecision, ...]
    selected_source_ids: tuple[SourceId, ...]
    outcome: DiscoveryAgentOutcome
    notes: tuple[str, ...] = Field(default_factory=tuple)


@dataclass
class OpenAIAgentsSDKDiscoveryModelRunner:
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        return await Runner.run(
            agent,
            model_input,
            run_config=run_config,
            max_turns=max_turns,
        )


@dataclass
class MockDiscoveryModelRunner:
    output: DiscoveryAgentOutput | dict[str, Any] | None = None
    error: BaseException | None = None
    calls: int = 0

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        del agent, run_config, max_turns
        self.calls += 1
        if self.error is not None:
            raise self.error
        output = (
            self.output
            if self.output is not None
            else _mock_discovery_from_model_input(model_input)
        )
        return _MockRunResult(final_output=output)


@dataclass
class LiveDiscoveryAgent:
    settings: Settings
    research_tools_factory: Callable[[Any], AgentResearchTools] | None = None
    model_runner: DiscoveryModelRunner = field(
        default_factory=OpenAIAgentsSDKDiscoveryModelRunner,
    )
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
        repr=False,
    )
    _research_tools: AgentResearchTools | None = field(
        default=None, init=False, repr=False
    )

    async def run(self, input_data: DiscoveryAgentInput) -> DiscoveryAgentOutput:
        configuration = build_openai_agent_run_configuration(
            self.settings,
            agent_name="DiscoveryAgent",
            run_id=str(input_data.run_id),
        )
        self._research_tools = (
            self.research_tools_factory(input_data.run_id)
            if self.research_tools_factory is not None
            else None
        )
        agent = _build_discovery_agent(configuration.model, self._research_tools)
        apply_openai_agent_run_profile(agent, configuration)
        run_config = RunConfig(
            model_settings=ModelSettings(
                max_tokens=4000,
                include_usage=True,
            ),
            tracing_disabled=not configuration.tracing_enabled,
            trace_include_sensitive_data=configuration.trace_include_sensitive_data,
            workflow_name=configuration.trace_workflow_name,
            trace_metadata=configuration.trace_metadata,
        )

        try:
            raw_result = await asyncio.wait_for(
                self.model_runner.run(
                    agent,
                    _model_input(input_data),
                    run_config=run_config,
                    max_turns=configuration.max_turns,
                ),
                timeout=configuration.timeout_seconds,
            )
            output = _coerce_discovery_result(
                getattr(raw_result, "final_output", raw_result),
                input_data,
                self._research_tools.search_results if self._research_tools else (),
            )
        except TimeoutError:
            output = _fallback_discovery_output(
                input_data,
                self._research_tools.search_results if self._research_tools else (),
            )
            self._set_activity("timeout_fallback", input_data, output)
            return output
        except (ValidationError, ValueError, TypeError):
            output = _fallback_discovery_output(
                input_data,
                self._research_tools.search_results if self._research_tools else (),
            )
            self._set_activity("schema_invalid_fallback", input_data, output)
            return output
        except Exception:
            output = _fallback_discovery_output(
                input_data,
                self._research_tools.search_results if self._research_tools else (),
            )
            self._set_activity("error_fallback", input_data, output)
            return output

        self._set_activity("model_discovery_completed", input_data, output)
        return output

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return self._workbench_activity

    def _set_activity(
        self,
        status: str,
        input_data: DiscoveryAgentInput,
        output: DiscoveryAgentOutput,
    ) -> None:
        self._workbench_activity = (
            *(self._research_tools.workbench_activity if self._research_tools else ()),
            {
                "tool_name": "openai_agents_structured_output",
                "status": status,
                "input": {
                    "agent": "DiscoveryAgent",
                    "allowed_tools": [
                        tool.name for tool in self._research_tools.sdk_tools()
                    ]
                    if self._research_tools is not None
                    else [],
                    "search_result_count": len(input_data.seed_results),
                    "inspected_source_count": len(output.source_decisions),
                },
                "output": {
                    "outcome": output.outcome.value,
                    "selected_source_ids": [
                        str(source_id) for source_id in output.selected_source_ids
                    ],
                    "notes": output.notes,
                },
            },
        )


@dataclass
class _MockRunResult:
    final_output: Any


def _build_discovery_agent(
    model: str, research_tools: AgentResearchTools | None
) -> Agent[Any]:
    return Agent(
        name="CartCartDiscoveryAgent",
        model=model,
        model_settings=ModelSettings(
            max_tokens=4000,
            include_usage=True,
        ),
        instructions=(
            "You own shopping-source research. Inspect the supplied seed results and "
            "use search_sources for bounded follow-up searches when reviews, broad "
            "collections, weak matches, or too few listings leave the research "
            "incomplete. Use the shopping brief's buying region for follow-up "
            "searches. Search for named models found in reviews when useful. "
            "When product_leads are supplied, choose the most promising named "
            "models for this shopper and search for official or retailer "
            "offers within the four-call tool budget, before choosing pages "
            "to inspect. Explain useful leads you could not research. A review "
            "lead is not "
            "itself an offer; explain ambiguous identity instead of guessing. "
            "A provider source_type or planned query intent is only a hint, never "
            "a semantic classification. For every source ID you inspect, return "
            "one source_decision with a classification, calibrated confidence, "
            "specific reasons, intended treatment, candidate/model hints, and "
            "next_action. Classify professional reviews, individual product "
            "pages, retailer listings, official brand pages, marketplace "
            "listings, category/collection pages, community sources, irrelevant "
            "and uncertain sources. Retain reviews as evidence; do not turn a "
            "review into a listing. Select source IDs needing page inspection "
            "in selected_source_ids (fetch or retain_as_evidence actions). "
            "Use fetch_source by ID to resolve ambiguity when needed. Excluded "
            "or unsafe sources must be ignored. If nothing useful remains, "
            "return insufficient_candidates with explicit reasons. Never invent "
            "IDs, prices, specs, sellers, or product facts."
        ),
        tools=list(research_tools.sdk_tools()) if research_tools else [],
        output_type=DiscoveryModelOutput,
    )


def _model_input(input_data: DiscoveryAgentInput) -> str:
    return json.dumps(
        {
            "run_id": str(input_data.run_id),
            "brief": input_data.brief.model_dump(mode="json"),
            "search_plan": input_data.search_plan.model_dump(mode="json"),
            "search_results": [
                _search_result_summary(result) for result in input_data.seed_results
            ],
            "product_leads": [
                lead.model_dump(mode="json") for lead in input_data.product_leads
            ],
        },
        sort_keys=True,
    )


def _search_result_summary(result: SearchResult) -> dict[str, Any]:
    return {
        "source_id": str(result.source_id),
        "query": result.query.model_dump(mode="json"),
        "url": _neutral_url(str(result.url)),
        "title": result.title,
        "snippet": result.snippet,
        "source_type": result.source_type.value,
        "quality": result.quality.model_dump(mode="json"),
        "provider": {
            "provider_name": result.provider.provider_name,
            "provider_result_id": result.provider.provider_result_id,
            "raw": _safe_provider_raw(result.provider.raw),
        },
    }


def _safe_provider_raw(raw: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "source_class",
        "requires_trust_assessment",
        "region_relevance",
        "region_relevance_score",
        "source_policy_version",
        *_EXCLUDED_RAW_FLAGS,
    }
    return {key: value for key, value in raw.items() if key in allowed_keys}


def _neutral_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _coerce_discovery_result(
    value: Any,
    input_data: DiscoveryAgentInput,
    tool_results: tuple[SearchResult, ...],
) -> DiscoveryAgentOutput:
    raw_output = (
        value
        if isinstance(value, (DiscoveryAgentOutput, DiscoveryModelOutput))
        else DiscoveryModelOutput.model_validate(value)
    )
    output = DiscoveryAgentOutput(
        search_results=(*input_data.seed_results, *tool_results),
        source_decisions=raw_output.source_decisions,
        selected_source_ids=raw_output.selected_source_ids,
        outcome=raw_output.outcome,
        notes=raw_output.notes,
    )
    _validate_discovery_policy(output)
    return output.model_copy(
        update={"selected_source_ids": _inspection_order(output.source_decisions)}
    )


def _inspection_order(
    decisions: tuple[DiscoverySourceDecision, ...],
) -> tuple[SourceId, ...]:
    fetch = tuple(
        item.source_id
        for item in decisions
        if item.next_action == DiscoveryNextAction.FETCH
    )
    evidence = tuple(
        item.source_id
        for item in decisions
        if item.next_action == DiscoveryNextAction.RETAIN_AS_EVIDENCE
    )
    # The current extraction stage inspects at most eight pages. Reserve room
    # for review evidence while ensuring shopping pages are not hidden behind it.
    return (*fetch[:6], *evidence[:2], *fetch[6:], *evidence[2:])


def _validate_discovery_policy(output: DiscoveryAgentOutput) -> None:
    result_by_id = {result.source_id: result for result in output.search_results}
    decisions = {decision.source_id: decision for decision in output.source_decisions}
    if set(decisions) != set(result_by_id):
        raise ValueError(
            "discovery must classify every observed source ID exactly once."
        )
    if any(
        decision.next_action != DiscoveryNextAction.IGNORE
        for decision in output.source_decisions
        if any(
            result_by_id[decision.source_id].provider.raw.get(flag)
            for flag in _EXCLUDED_RAW_FLAGS
        )
    ):
        raise ValueError("excluded sources cannot be selected for research.")
    selected = set(output.selected_source_ids)
    actionable = {
        decision.source_id
        for decision in output.source_decisions
        if decision.next_action
        in {
            DiscoveryNextAction.FETCH,
            DiscoveryNextAction.RETAIN_AS_EVIDENCE,
        }
    }
    if selected != actionable:
        raise ValueError("selected IDs must match fetch/evidence decisions.")
    if any(
        decisions[source_id].classification == DiscoverySourceKind.IRRELEVANT
        for source_id in selected
    ):
        raise ValueError("irrelevant sources cannot be selected.")


def _fallback_discovery_output(
    input_data: DiscoveryAgentInput,
    tool_results: tuple[SearchResult, ...] = (),
) -> DiscoveryAgentOutput:
    return DiscoveryAgentOutput(
        search_results=(*input_data.seed_results, *tool_results),
        outcome=DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES,
        notes=("Discovery model could not classify the available sources.",),
    )


def _mock_discovery_from_model_input(model_input: str) -> DiscoveryAgentOutput:
    payload = json.loads(model_input)
    input_data = DiscoveryAgentInput.model_validate(
        {
            "run_id": payload["run_id"],
            "brief": payload["brief"],
            "search_plan": payload["search_plan"],
            "seed_results": payload["search_results"],
        }
    )
    # Fixture-only model response; live decisions come from the OpenAI model.
    decisions: list[DiscoverySourceDecision] = []
    for result in input_data.seed_results:
        text = f"{result.title} {result.snippet or ''}".casefold()
        excluded = any(result.provider.raw.get(flag) for flag in _EXCLUDED_RAW_FLAGS)
        if excluded or "proxy" in text or "unrelated" in text:
            kind, action = DiscoverySourceKind.IRRELEVANT, DiscoveryNextAction.IGNORE
        elif "review" in text or "best tvs" in text:
            kind, action = (
                DiscoverySourceKind.PROFESSIONAL_REVIEW,
                DiscoveryNextAction.RETAIN_AS_EVIDENCE,
            )
        elif "retailer" in text or " at " in text:
            kind, action = (
                DiscoverySourceKind.RETAILER_LISTING,
                DiscoveryNextAction.FETCH,
            )
        elif "collection" in text or "televisions by" in text:
            kind, action = (
                DiscoverySourceKind.CATEGORY_COLLECTION,
                DiscoveryNextAction.FETCH,
            )
        else:
            kind, action = DiscoverySourceKind.UNCERTAIN, DiscoveryNextAction.IGNORE
        decisions.append(
            DiscoverySourceDecision(
                source_id=result.source_id,
                classification=kind,
                confidence=0.8 if kind != DiscoverySourceKind.UNCERTAIN else 0.3,
                reasons=("Fixture-scripted mock classification from title/snippet.",),
                intended_treatment="Inspect page"
                if action != DiscoveryNextAction.IGNORE
                else "Ignore",
                candidate_model_hints=("Aurora A55", "Northstar N65")
                if "Aurora A55 and Northstar N65" in result.title
                else (),
                next_action=action,
            )
        )
    selected = _inspection_order(tuple(decisions))
    return DiscoveryAgentOutput(
        source_decisions=tuple(decisions),
        selected_source_ids=selected,
        outcome=DiscoveryAgentOutcome.SELECTED
        if selected
        else DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES,
    )
