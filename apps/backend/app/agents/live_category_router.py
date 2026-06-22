import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from agents import Agent, ModelSettings, RunConfig, Runner
from pydantic import ValidationError

from app.agents.catalog import (
    AgentCatalog,
    ProductAnalysisRoute,
    build_default_agent_catalog,
)
from app.agents.contracts import CategoryRouterAgentInput
from app.agents.openai_config import build_openai_agent_run_configuration
from app.core.settings import Settings
from app.schemas.intake import ShoppingBrief
from app.schemas.products import CanonicalProduct, ProductListing


class CategoryRouterModelRunner(Protocol):
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        """Run the SDK category-router agent and return its raw run result."""


@dataclass
class OpenAIAgentsSDKCategoryRouterModelRunner:
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
class MockCategoryRouterModelRunner:
    output: ProductAnalysisRoute | dict[str, Any] | None = None
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
        output = self.output or _mock_route_from_model_input(model_input)
        return _MockRunResult(final_output=output)


@dataclass
class LiveCategoryRouterAgent:
    settings: Settings
    catalog: AgentCatalog = field(default_factory=build_default_agent_catalog)
    model_runner: CategoryRouterModelRunner = field(
        default_factory=OpenAIAgentsSDKCategoryRouterModelRunner,
    )
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
        repr=False,
    )

    async def run(self, input_data: CategoryRouterAgentInput) -> ProductAnalysisRoute:
        configuration = build_openai_agent_run_configuration(
            self.settings,
            agent_name="CategoryRouterAgent",
            run_id=str(input_data.run_id),
        )
        agent = _build_category_router_agent(configuration.model)
        run_config = RunConfig(
            model=configuration.model,
            model_settings=ModelSettings(
                temperature=0,
                max_tokens=500,
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
                    _model_input(input_data, self.catalog),
                    run_config=run_config,
                    max_turns=configuration.max_turns,
                ),
                timeout=configuration.timeout_seconds,
            )
            route = _coerce_router_result(
                getattr(raw_result, "final_output", raw_result),
                input_data,
                self.catalog,
            )
        except TimeoutError:
            route = _fallback_route(input_data, self.catalog)
            self._set_activity("timeout_fallback", input_data, route)
            return route
        except (ValidationError, ValueError, TypeError):
            route = _fallback_route(input_data, self.catalog)
            self._set_activity("schema_invalid_fallback", input_data, route)
            return route
        except Exception:
            route = _fallback_route(input_data, self.catalog)
            self._set_activity("error_fallback", input_data, route)
            return route

        self._set_activity("model_category_route_completed", input_data, route)
        return route

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return self._workbench_activity

    def _set_activity(
        self,
        status: str,
        input_data: CategoryRouterAgentInput,
        route: ProductAnalysisRoute,
    ) -> None:
        self._workbench_activity = (
            {
                "tool_name": "openai_agents_structured_output",
                "status": status,
                "input": {
                    "agent": "CategoryRouterAgent",
                    "allowed_tools": [],
                    "brief_category": input_data.brief.category,
                    "product_count": len(input_data.products),
                },
                "output": route.model_dump(mode="json"),
            },
        )


@dataclass
class _MockRunResult:
    final_output: Any


def _build_category_router_agent(model: str) -> Agent[Any]:
    return Agent(
        name="CartCartCategoryRouterAgent",
        model=model,
        model_settings=ModelSettings(
            temperature=0,
            max_tokens=500,
            include_usage=True,
        ),
        instructions=(
            "Return only a structured ProductAnalysisRoute for the shopper's "
            "brief and candidate products. Use only the supplied catalog route "
            "names. Technology products must enter TechnologyDomainAnalystAgent "
            "before any narrower MVP technology specialist. Ordinary consumer "
            "product categories without a specialist must route to "
            "GenericProductAnalystAgent rather than an unsupported-category "
            "error. Do not analyze products, recommend products, browse, call "
            "tools, or expose agents, providers, prompts, traces, policies, or "
            "schemas to shoppers."
        ),
        tools=[],
        output_type=ProductAnalysisRoute,
    )


def _model_input(input_data: CategoryRouterAgentInput, catalog: AgentCatalog) -> str:
    return json.dumps(
        {
            "run_id": str(input_data.run_id),
            "brief": input_data.brief.model_dump(mode="json"),
            "products": [
                _product_summary(product) for product in input_data.products
            ],
            "listings": [
                _listing_summary(listing) for listing in input_data.listings
            ],
            "allowed_routes": {
                "generic_fallback_agent_name": catalog.generic_fallback_agent_name,
                "technology_domain_agent_name": catalog.technology_domain_agent_name,
                "product_category_routes": catalog.product_category_routes,
                "technology_category_keywords": catalog.technology_category_keywords,
            },
        },
        sort_keys=True,
    )


def _product_summary(product: CanonicalProduct) -> dict[str, Any]:
    return {
        "product_id": str(product.product_id),
        "name": product.name,
        "brand": product.brand,
        "model": product.model,
        "category": product.category,
    }


def _listing_summary(listing: ProductListing) -> dict[str, Any]:
    return {
        "listing_id": str(listing.listing_id),
        "product_id": str(listing.product_id),
        "title": listing.title,
        "seller_name": listing.seller.seller_name if listing.seller else None,
    }


def _coerce_router_result(
    value: Any,
    input_data: CategoryRouterAgentInput,
    catalog: AgentCatalog,
) -> ProductAnalysisRoute:
    raw_route = (
        value
        if isinstance(value, ProductAnalysisRoute)
        else ProductAnalysisRoute.model_validate(value)
    )
    _validate_model_route_shape(raw_route, catalog)
    return catalog.route_product_analysis(_routing_category(input_data, raw_route.category))


def _validate_model_route_shape(
    route: ProductAnalysisRoute,
    catalog: AgentCatalog,
) -> None:
    if route.category and _contains_artificial_blocking(route.category):
        raise ValueError("category router output included artificial category blocking.")
    for agent_name in (*route.agent_path, *route.fallback_agent_names):
        if _contains_artificial_blocking(agent_name):
            raise ValueError("category router output included unsupported-agent text.")
        catalog.require(agent_name)


def _fallback_route(
    input_data: CategoryRouterAgentInput,
    catalog: AgentCatalog,
) -> ProductAnalysisRoute:
    return catalog.route_product_analysis(_routing_category(input_data, None))


def _routing_category(
    input_data: CategoryRouterAgentInput,
    model_category: str | None,
) -> str | None:
    if input_data.brief.category and not _contains_artificial_blocking(
        input_data.brief.category,
    ):
        return input_data.brief.category

    product_category = _single_product_category(input_data.products)
    if product_category is not None:
        return product_category

    if model_category and not _contains_artificial_blocking(model_category):
        return model_category

    query = " ".join(input_data.brief.original_query.strip().split())
    return query or None


def _single_product_category(
    products: tuple[CanonicalProduct, ...],
) -> str | None:
    categories = tuple(
        product.category.strip()
        for product in products
        if product.category and product.category.strip()
    )
    normalized_categories = {_normalize_category(category) for category in categories}
    if len(normalized_categories) != 1:
        return None
    return categories[0]


def _normalize_category(category: str) -> str:
    return " ".join(category.casefold().replace("/", " ").split())


def _contains_artificial_blocking(text: str) -> bool:
    normalized = text.casefold()
    patterns = (
        r"\bunsupported categor",
        r"\bunsupported product",
        r"\bnot supported\b",
        r"\bno specialist\b",
        r"\bspecialist-only\b",
        r"\bcannot (?:route|support|analyze)\b",
        r"\bcan't (?:route|support|analyze)\b",
        r"\bunsupportedcategoryagent\b",
    )
    return any(re.search(pattern, normalized) is not None for pattern in patterns)


def _mock_route_from_model_input(model_input: str) -> ProductAnalysisRoute:
    payload = json.loads(model_input)
    brief = ShoppingBrief.model_validate(payload["brief"])
    catalog = build_default_agent_catalog()
    return catalog.route_product_analysis(
        _routing_category_from_payload(brief, payload["products"])
    )


def _routing_category_from_payload(
    brief: ShoppingBrief,
    product_summaries: list[dict[str, Any]],
) -> str | None:
    if brief.category and not _contains_artificial_blocking(brief.category):
        return brief.category

    categories = tuple(
        category.strip()
        for product in product_summaries
        if isinstance(product.get("category"), str)
        if (category := product["category"]).strip()
    )
    normalized_categories = {_normalize_category(category) for category in categories}
    if len(normalized_categories) == 1:
        return categories[0]

    query = " ".join(brief.original_query.strip().split())
    return query or None
