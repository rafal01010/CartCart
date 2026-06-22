import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from agents import Agent, ModelSettings, RunConfig, Runner
from pydantic import ValidationError

from app.agents.contracts import (
    DiscoveryAgentInput,
    DiscoveryAgentOutcome,
    DiscoveryAgentOutput,
)
from app.agents.openai_config import build_openai_agent_run_configuration
from app.core.settings import Settings
from app.schemas.search_sources import (
    SearchResult,
    SourceQualityLevel,
    SourceType,
)


_EXTRACTABLE_SOURCE_TYPES = frozenset(
    {
        SourceType.PRODUCT_PAGE,
        SourceType.RETAILER_LISTING,
        SourceType.OFFICIAL_BRAND_PAGE,
        SourceType.PROFESSIONAL_REVIEW,
        SourceType.COMMUNITY_DISCUSSION,
    }
)
_EXCLUDED_SOURCE_CLASSES = frozenset(
    {
        "reseller_import_proxy",
        "price_comparison",
    }
)
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
    model_runner: DiscoveryModelRunner = field(
        default_factory=OpenAIAgentsSDKDiscoveryModelRunner,
    )
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
        repr=False,
    )

    async def run(self, input_data: DiscoveryAgentInput) -> DiscoveryAgentOutput:
        configuration = build_openai_agent_run_configuration(
            self.settings,
            agent_name="DiscoveryAgent",
            run_id=str(input_data.run_id),
        )
        agent = _build_discovery_agent(configuration.model)
        run_config = RunConfig(
            model=configuration.model,
            model_settings=ModelSettings(
                temperature=0,
                max_tokens=900,
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
            )
        except TimeoutError:
            output = _fallback_discovery_output(input_data)
            self._set_activity("timeout_fallback", input_data, output)
            return output
        except (ValidationError, ValueError, TypeError):
            output = _fallback_discovery_output(input_data)
            self._set_activity("schema_invalid_fallback", input_data, output)
            return output
        except Exception:
            output = _fallback_discovery_output(input_data)
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
            {
                "tool_name": "openai_agents_structured_output",
                "status": status,
                "input": {
                    "agent": "DiscoveryAgent",
                    "allowed_tools": [],
                    "search_result_count": len(input_data.seed_results),
                    "eligible_source_count": len(
                        _eligible_search_results(input_data.seed_results)
                    ),
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


def _build_discovery_agent(model: str) -> Agent[Any]:
    return Agent(
        name="CartCartDiscoveryAgent",
        model=model,
        model_settings=ModelSettings(
            temperature=0,
            max_tokens=900,
            include_usage=True,
        ),
        instructions=(
            "Review supplied SearchResult records and return only a structured "
            "DiscoveryAgentOutput. Select candidate source IDs for extraction "
            "from the supplied search_results only. Choose product pages, "
            "retailer listings, official brand/store pages, professional "
            "reviews, or community discussions when the source quality is not "
            "weak and the source is not a proxy, reseller-import, or price "
            "comparison result. Do not select generic search-result pages, "
            "video results, other/unknown page types, weak sources, excluded "
            "source-policy classes, or IDs not present in the input. If no "
            "credible candidates exist, return outcome insufficient_candidates "
            "with no selected_source_ids and a brief note. Do not invent product "
            "names, listings, prices, specs, seller facts, source IDs, URLs, or "
            "claims. Do not browse, call tools, recommend products, or expose "
            "agents, providers, prompts, traces, policies, or schemas."
        ),
        tools=[],
        output_type=DiscoveryAgentOutput,
    )


def _model_input(input_data: DiscoveryAgentInput) -> str:
    return json.dumps(
        {
            "run_id": str(input_data.run_id),
            "brief": input_data.brief.model_dump(mode="json"),
            "search_plan": input_data.search_plan.model_dump(mode="json"),
            "search_results": [
                _search_result_summary(result)
                for result in input_data.seed_results
            ],
        },
        sort_keys=True,
    )


def _search_result_summary(result: SearchResult) -> dict[str, Any]:
    return {
        "source_id": str(result.source_id),
        "query": result.query.model_dump(mode="json"),
        "url": str(result.url),
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


def _coerce_discovery_result(
    value: Any,
    input_data: DiscoveryAgentInput,
) -> DiscoveryAgentOutput:
    raw_output = (
        value
        if isinstance(value, DiscoveryAgentOutput)
        else DiscoveryAgentOutput.model_validate(value)
    )
    output = DiscoveryAgentOutput(
        search_results=input_data.seed_results,
        selected_source_ids=raw_output.selected_source_ids,
        outcome=raw_output.outcome,
        notes=raw_output.notes,
    )
    _validate_discovery_policy(output)
    return output


def _validate_discovery_policy(output: DiscoveryAgentOutput) -> None:
    result_by_id = {result.source_id: result for result in output.search_results}
    selected_results = tuple(result_by_id[source_id] for source_id in output.selected_source_ids)
    invalid_source_ids = tuple(
        result.source_id
        for result in selected_results
        if not _is_eligible_search_result(result)
    )
    if invalid_source_ids:
        raise ValueError("discovery output selected ineligible source IDs.")

    eligible_source_ids = {
        result.source_id for result in _eligible_search_results(output.search_results)
    }
    if eligible_source_ids and output.outcome == DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES:
        raise ValueError("discovery output ignored eligible source candidates.")


def _fallback_discovery_output(input_data: DiscoveryAgentInput) -> DiscoveryAgentOutput:
    eligible_results = _eligible_search_results(input_data.seed_results)
    if not eligible_results:
        return DiscoveryAgentOutput(
            search_results=input_data.seed_results,
            outcome=DiscoveryAgentOutcome.INSUFFICIENT_CANDIDATES,
            notes=("No eligible source results were available for extraction.",),
        )
    return DiscoveryAgentOutput(
        search_results=input_data.seed_results,
        selected_source_ids=tuple(result.source_id for result in eligible_results),
        outcome=DiscoveryAgentOutcome.SELECTED,
        notes=(
            "Deterministic fallback selected eligible source IDs from supplied search results.",
        ),
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
    return _fallback_discovery_output(input_data)


def _eligible_search_results(
    results: tuple[SearchResult, ...],
) -> tuple[SearchResult, ...]:
    return tuple(result for result in results if _is_eligible_search_result(result))


def _is_eligible_search_result(result: SearchResult) -> bool:
    if result.source_type not in _EXTRACTABLE_SOURCE_TYPES:
        return False
    if result.quality.level == SourceQualityLevel.WEAK:
        return False

    raw = result.provider.raw
    if any(bool(raw.get(flag)) for flag in _EXCLUDED_RAW_FLAGS):
        return False

    source_class = raw.get("source_class")
    if isinstance(source_class, str) and source_class in _EXCLUDED_SOURCE_CLASSES:
        return False

    return True
