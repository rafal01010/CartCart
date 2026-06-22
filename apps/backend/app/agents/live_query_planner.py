import asyncio
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from agents import Agent, ModelSettings, RunConfig, Runner
from pydantic import ValidationError

from app.agents.contracts import QueryPlannerAgentInput
from app.agents.openai_config import build_openai_agent_run_configuration
from app.core.settings import Settings
from app.schemas.intake import BudgetMode, PreferenceMode, ShoppingBrief
from app.schemas.regions import RegionCode
from app.schemas.search_sources import (
    SearchIntent,
    SearchPlan,
    SearchQuery,
    SourceType,
)

_MAX_SEARCH_QUERY_LENGTH = 500


class QueryPlannerModelRunner(Protocol):
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        """Run the SDK query-planner agent and return its raw run result."""


@dataclass
class OpenAIAgentsSDKQueryPlannerModelRunner:
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
class MockQueryPlannerModelRunner:
    output: SearchPlan | dict[str, Any] | None = None
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
        output = self.output or _mock_plan_from_model_input(model_input)
        return _MockRunResult(final_output=output)


@dataclass
class LiveQueryPlannerAgent:
    settings: Settings
    model_runner: QueryPlannerModelRunner = field(
        default_factory=OpenAIAgentsSDKQueryPlannerModelRunner,
    )
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
        repr=False,
    )

    async def run(self, input_data: QueryPlannerAgentInput) -> SearchPlan:
        configuration = build_openai_agent_run_configuration(
            self.settings,
            agent_name="QueryPlannerAgent",
            run_id=str(input_data.run_id),
        )
        agent = _build_query_planner_agent(configuration.model)
        run_config = RunConfig(
            model=configuration.model,
            model_settings=ModelSettings(
                temperature=0,
                max_tokens=1100,
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
            plan = _coerce_query_plan_result(
                getattr(raw_result, "final_output", raw_result),
                input_data.brief,
            )
        except TimeoutError:
            plan = _fallback_search_plan(input_data.brief)
            self._set_activity("timeout_fallback", input_data, plan)
            return plan
        except (ValidationError, ValueError, TypeError):
            plan = _fallback_search_plan(input_data.brief)
            self._set_activity("schema_invalid_fallback", input_data, plan)
            return plan
        except Exception:
            plan = _fallback_search_plan(input_data.brief)
            self._set_activity("error_fallback", input_data, plan)
            return plan

        self._set_activity("model_query_plan_completed", input_data, plan)
        return plan

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return self._workbench_activity

    def _set_activity(
        self,
        status: str,
        input_data: QueryPlannerAgentInput,
        plan: SearchPlan,
    ) -> None:
        region_code = _region_code_from_brief(input_data.brief)
        self._workbench_activity = (
            {
                "tool_name": "openai_agents_structured_output",
                "status": status,
                "input": {
                    "agent": "QueryPlannerAgent",
                    "allowed_tools": [],
                    "category": input_data.brief.category,
                    "region_code": region_code,
                    "query_count": len(plan.queries),
                },
                "output": plan.model_dump(mode="json"),
            },
        )


@dataclass
class _MockRunResult:
    final_output: Any


def _build_query_planner_agent(model: str) -> Agent[Any]:
    return Agent(
        name="CartCartQueryPlannerAgent",
        model=model,
        model_settings=ModelSettings(
            temperature=0,
            max_tokens=1100,
            include_usage=True,
        ),
        instructions=(
            "Create a SearchPlan from the shopper's ShoppingBrief. Return only "
            "the structured SearchPlan. Include a small source strategy with "
            "shopping/listing, price or availability, official-source, and "
            "review queries when useful. Include video-review search when a "
            "normal shopper would benefit from demos, comparisons, durability, "
            "or setup evidence. Every ordinary consumer product category must "
            "receive a generic shopping plan; never refuse or block only "
            "because no category specialist exists. Use the brief's region code "
            "on every query when present, and do not invent a region when the "
            "brief has none. Do not recommend products, browse, call tools, "
            "mention internal process, or expose agents, providers, prompts, "
            "traces, policies, or schemas."
        ),
        tools=[],
        output_type=SearchPlan,
    )


def _model_input(input_data: QueryPlannerAgentInput) -> str:
    return json.dumps(
        {
            "run_id": str(input_data.run_id),
            "brief": input_data.brief.model_dump(mode="json"),
        },
        sort_keys=True,
    )


def _coerce_query_plan_result(value: Any, brief: ShoppingBrief) -> SearchPlan:
    plan = value if isinstance(value, SearchPlan) else SearchPlan.model_validate(value)
    plan = _normalize_query_plan(plan, brief)
    _validate_query_plan_policy(plan)
    return plan


def _normalize_query_plan(plan: SearchPlan, brief: ShoppingBrief) -> SearchPlan:
    region_code = _region_code_from_brief(brief)
    queries = tuple(
        _normalize_query(query, region_code=region_code)
        for query in plan.queries
    )
    return SearchPlan(
        queries=_dedupe_queries(queries),
        rationale=plan.rationale,
    )


def _normalize_query(
    query: SearchQuery,
    *,
    region_code: RegionCode | None,
) -> SearchQuery:
    required_source_types = (
        query.required_source_types or _default_source_types(query.intent)
    )
    return query.model_copy(
        update={
            "query": _clean_query(query.query),
            "region_code": region_code,
            "required_source_types": required_source_types,
        }
    )


def _dedupe_queries(queries: tuple[SearchQuery, ...]) -> tuple[SearchQuery, ...]:
    deduped: list[SearchQuery] = []
    seen: set[tuple[str, str]] = set()
    for query in queries:
        key = (query.intent.value, query.query.casefold())
        if key in seen:
            continue
        deduped.append(query)
        seen.add(key)
    return tuple(deduped)


def _validate_query_plan_policy(plan: SearchPlan) -> None:
    texts = [query.query for query in plan.queries]
    if plan.rationale:
        texts.append(plan.rationale)
    for text in texts:
        if _contains_artificial_blocking(text):
            raise ValueError("query planner output included artificial category blocking.")

    if len(plan.queries) < 2:
        raise ValueError("query planner output must include shopping and review queries.")
    if not any(_is_shopping_query(query) for query in plan.queries):
        raise ValueError("query planner output must include a shopping query.")
    if not any(_is_review_query(query) for query in plan.queries):
        raise ValueError("query planner output must include a review query.")
    if any(not query.required_source_types for query in plan.queries):
        raise ValueError("query planner output must include source strategy.")


def _contains_artificial_blocking(text: str) -> bool:
    normalized = text.casefold()
    patterns = (
        r"\bunsupported categor",
        r"\bunsupported product",
        r"\bnot supported\b",
        r"\bno specialist\b",
        r"\bspecialist-only\b",
        r"\bcannot (?:plan|support|search)\b",
        r"\bcan't (?:plan|support|search)\b",
        r"\bno search plan\b",
    )
    return any(re.search(pattern, normalized) is not None for pattern in patterns)


def _is_shopping_query(query: SearchQuery) -> bool:
    return query.intent in {
        SearchIntent.DISCOVERY,
        SearchIntent.PRICE_CHECK,
        SearchIntent.OFFICIAL_SOURCE,
        SearchIntent.TRUST_CHECK,
    } or bool(
        set(query.required_source_types)
        & {
            SourceType.PRODUCT_PAGE,
            SourceType.RETAILER_LISTING,
            SourceType.OFFICIAL_BRAND_PAGE,
        }
    )


def _is_review_query(query: SearchQuery) -> bool:
    return query.intent in {
        SearchIntent.REVIEW,
        SearchIntent.VIDEO_REVIEW,
    } or bool(
        set(query.required_source_types)
        & {
            SourceType.PROFESSIONAL_REVIEW,
            SourceType.VIDEO,
            SourceType.COMMUNITY_DISCUSSION,
        }
    )


def _default_source_types(intent: SearchIntent) -> tuple[SourceType, ...]:
    defaults = {
        SearchIntent.DISCOVERY: (
            SourceType.RETAILER_LISTING,
            SourceType.PRODUCT_PAGE,
            SourceType.OFFICIAL_BRAND_PAGE,
        ),
        SearchIntent.PRICE_CHECK: (
            SourceType.RETAILER_LISTING,
            SourceType.PRODUCT_PAGE,
        ),
        SearchIntent.REVIEW: (SourceType.PROFESSIONAL_REVIEW,),
        SearchIntent.OFFICIAL_SOURCE: (
            SourceType.OFFICIAL_BRAND_PAGE,
            SourceType.PRODUCT_PAGE,
        ),
        SearchIntent.VIDEO_REVIEW: (SourceType.VIDEO,),
        SearchIntent.TRUST_CHECK: (
            SourceType.RETAILER_LISTING,
            SourceType.COMMUNITY_DISCUSSION,
            SourceType.PROFESSIONAL_REVIEW,
        ),
    }
    return defaults[intent]


def _fallback_search_plan(brief: ShoppingBrief) -> SearchPlan:
    descriptor = _query_descriptor(brief)
    region_code = _region_code_from_brief(brief)
    region_phrase = _region_phrase(region_code)
    budget_phrase = _budget_phrase(brief)
    context_phrase = _context_phrase(brief)

    queries = (
        SearchQuery(
            query=_clean_query(
                f"{descriptor} {budget_phrase} {region_phrase} retailers buying options"
            ),
            intent=SearchIntent.DISCOVERY,
            region_code=region_code,
            required_source_types=_default_source_types(SearchIntent.DISCOVERY),
        ),
        SearchQuery(
            query=_clean_query(
                f"{descriptor} {budget_phrase} {region_phrase} reviews comparison"
            ),
            intent=SearchIntent.REVIEW,
            region_code=region_code,
            required_source_types=_default_source_types(SearchIntent.REVIEW),
        ),
        SearchQuery(
            query=_clean_query(
                f"{descriptor} {region_phrase} official store warranty availability"
            ),
            intent=SearchIntent.OFFICIAL_SOURCE,
            region_code=region_code,
            required_source_types=_default_source_types(SearchIntent.OFFICIAL_SOURCE),
        ),
        SearchQuery(
            query=_clean_query(
                f"{descriptor} {region_phrase} price seller return policy"
            ),
            intent=SearchIntent.PRICE_CHECK,
            region_code=region_code,
            required_source_types=_default_source_types(SearchIntent.PRICE_CHECK),
        ),
        SearchQuery(
            query=_clean_query(
                f"{descriptor} {context_phrase} video review long term comparison"
            ),
            intent=SearchIntent.VIDEO_REVIEW,
            region_code=region_code,
            required_source_types=_default_source_types(SearchIntent.VIDEO_REVIEW),
        ),
    )
    return SearchPlan(
        queries=_dedupe_queries(queries),
        rationale=(
            "Generic region-aware shopping plan covering retailers, reviews, "
            "official sources, prices, and video evidence where useful."
        ),
    )


def _mock_plan_from_model_input(model_input: str) -> SearchPlan:
    payload = json.loads(model_input)
    brief = ShoppingBrief.model_validate(payload["brief"])
    return _fallback_search_plan(brief)


def _query_descriptor(brief: ShoppingBrief) -> str:
    category = _clean_query(brief.category or "")
    if category:
        return category
    return _clean_query(brief.original_query)


def _region_code_from_brief(brief: ShoppingBrief) -> RegionCode | None:
    if brief.region is None:
        return None
    return brief.region.region.country_code


def _region_phrase(region_code: RegionCode | None) -> str:
    return f"in {region_code}" if region_code is not None else ""


def _budget_phrase(brief: ShoppingBrief) -> str:
    if brief.budget is None:
        return ""
    amount = _format_amount(brief.budget.amount.amount)
    currency = brief.budget.amount.currency
    prefix = "under" if brief.budget.mode == BudgetMode.HARD_CAP else "around"
    return f"{prefix} {amount} {currency}"


def _context_phrase(brief: ShoppingBrief) -> str:
    texts = [
        item.text
        for item in (*brief.constraints, *brief.preferences)
        if item.mode in {PreferenceMode.HARD, PreferenceMode.SOFT}
    ]
    return " ".join(texts[:2])


def _format_amount(amount: Decimal) -> str:
    normalized = amount.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f")


def _clean_query(value: str) -> str:
    query = " ".join(value.strip().split())
    if len(query) <= _MAX_SEARCH_QUERY_LENGTH:
        return query
    truncated = query[:_MAX_SEARCH_QUERY_LENGTH].rsplit(" ", 1)[0].strip()
    return truncated or query[:_MAX_SEARCH_QUERY_LENGTH]
