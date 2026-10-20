import asyncio
from dataclasses import dataclass
import os
from typing import Any

import pytest

from agents import Agent, RunConfig

from app.agents import (
    CategoryRouterAgentInput,
    LiveCategoryRouterAgent,
    MockCategoryRouterModelRunner,
    ProductAnalysisRoute,
)
from app.core.settings import Settings
from app.schemas.ids import new_id
from app.schemas.intake import FieldSource, ShoppingBrief
from app.schemas.products import CanonicalProduct


@dataclass
class RecordingCategoryRouterRunner:
    output: ProductAnalysisRoute | dict[str, Any] | None = None
    error: BaseException | None = None
    delay_seconds: float = 0
    calls: int = 0

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        del agent, model_input, run_config, max_turns
        self.calls += 1
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.error is not None:
            raise self.error
        return _RunResult(final_output=self.output or _valid_monitor_route())


@dataclass
class _RunResult:
    final_output: Any


def _settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        **overrides,
    )


def _input(category: str | None, query: str | None = None) -> CategoryRouterAgentInput:
    product = (
        CanonicalProduct(
            name=f"Fixture {category}",
            category=category,
        )
        if category is not None
        else None
    )
    return CategoryRouterAgentInput(
        run_id=new_id(),
        brief=ShoppingBrief(
            original_query=query or f"Help me choose a {category or 'product'}.",
            category=category,
            category_source=FieldSource.INFERRED if category is not None else None,
        ),
        products=(product,) if product is not None else (),
    )


def _valid_monitor_route() -> ProductAnalysisRoute:
    return ProductAnalysisRoute(
        category="monitor",
        agent_path=("TechnologyDomainAnalystAgent", "MonitorSpecialistAgent"),
        fallback_agent_names=(
            "TechnologyDomainAnalystAgent",
            "GenericProductAnalystAgent",
        ),
    )


@pytest.mark.asyncio
async def test_live_category_router_accepts_valid_monitor_route() -> None:
    runner = RecordingCategoryRouterRunner()
    agent = LiveCategoryRouterAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_input("monitor"))

    assert runner.calls == 1
    assert result.agent_path == (
        "TechnologyDomainAnalystAgent",
        "MonitorSpecialistAgent",
    )
    assert result.fallback_agent_names == (
        "TechnologyDomainAnalystAgent",
        "GenericProductAnalystAgent",
    )
    assert agent.workbench_activity[0]["status"] == "model_category_route_completed"
    assert agent.workbench_activity[0]["input"]["allowed_tools"] == []


@pytest.mark.asyncio
async def test_live_category_router_keeps_office_chair_on_generic_fallback() -> None:
    runner = MockCategoryRouterModelRunner()
    agent = LiveCategoryRouterAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_input("office chair"))

    assert runner.calls == 1
    assert result.agent_path == ("GenericProductAnalystAgent",)
    assert result.fallback_agent_names == ()
    combined_text = " ".join((*result.agent_path, *(result.fallback_agent_names)))
    assert "unsupported" not in combined_text.casefold()
    assert "no specialist" not in combined_text.casefold()
    assert agent.workbench_activity[0]["status"] == "model_category_route_completed"


@pytest.mark.asyncio
async def test_live_category_router_sends_non_specialist_tech_to_domain() -> None:
    runner = MockCategoryRouterModelRunner()
    agent = LiveCategoryRouterAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_input("gaming keyboard"))

    assert runner.calls == 1
    assert result.agent_path == ("TechnologyDomainAnalystAgent",)
    assert result.fallback_agent_names == ("GenericProductAnalystAgent",)


@pytest.mark.asyncio
@pytest.mark.parametrize("category", ("paper notebook", "gaming chair"))
@pytest.mark.parametrize("category_source", ("brief", "product", "model", "query"))
async def test_live_category_router_preserves_generic_model_decisions(
    category: str,
    category_source: str,
) -> None:
    model_route = ProductAnalysisRoute(
        category=category if category_source == "model" else None,
        agent_path=("GenericProductAnalystAgent",),
    )
    input_data = _input(category)
    if category_source == "product":
        input_data = input_data.model_copy(update={"brief": _input(None).brief})
    elif category_source == "model":
        input_data = _input(None)
    elif category_source == "query":
        input_data = _input(None, query=f"Help me choose a {category} please.")
    runner = RecordingCategoryRouterRunner(output=model_route)
    agent = LiveCategoryRouterAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert result.agent_path == ("GenericProductAnalystAgent",)
    assert result.fallback_agent_names == ()
    assert agent.workbench_activity[0]["status"] == "model_category_route_completed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("category", "expected_path", "expected_fallbacks"),
    (
        ("paper notebook", ("GenericProductAnalystAgent",), ()),
        ("gaming chair", ("GenericProductAnalystAgent",), ()),
        ("notebook", ("GenericProductAnalystAgent",), ()),
        ("gaming", ("GenericProductAnalystAgent",), ()),
        ("unknown product", ("GenericProductAnalystAgent",), ()),
        (
            "notebook computers",
            ("TechnologyDomainAnalystAgent", "LaptopSpecialistAgent"),
            ("TechnologyDomainAnalystAgent", "GenericProductAnalystAgent"),
        ),
        (
            "gaming monitor",
            ("TechnologyDomainAnalystAgent", "MonitorSpecialistAgent"),
            ("TechnologyDomainAnalystAgent", "GenericProductAnalystAgent"),
        ),
        (
            "gaming keyboard",
            ("TechnologyDomainAnalystAgent",),
            ("GenericProductAnalystAgent",),
        ),
        (
            "electronics",
            ("TechnologyDomainAnalystAgent",),
            ("GenericProductAnalystAgent",),
        ),
        (
            "gaming pc",
            ("TechnologyDomainAnalystAgent",),
            ("GenericProductAnalystAgent",),
        ),
        (
            "gaming console",
            ("TechnologyDomainAnalystAgent",),
            ("GenericProductAnalystAgent",),
        ),
        (
            "smart watches",
            ("TechnologyDomainAnalystAgent", "SmartwatchSpecialistAgent"),
            ("TechnologyDomainAnalystAgent", "GenericProductAnalystAgent"),
        ),
    ),
)
@pytest.mark.parametrize("failure", ("timeout", "error", "schema", "unknown_agent"))
async def test_live_category_router_keeps_semantic_routes_on_model_failure(
    category: str,
    expected_path: tuple[str, ...],
    expected_fallbacks: tuple[str, ...],
    failure: str,
) -> None:
    if failure == "timeout":
        runner = RecordingCategoryRouterRunner(error=TimeoutError())
        expected_status = "timeout_fallback"
    elif failure == "error":
        runner = RecordingCategoryRouterRunner(error=RuntimeError("mock model failed"))
        expected_status = "error_fallback"
    elif failure == "schema":
        runner = RecordingCategoryRouterRunner(output={"agent_path": []})
        expected_status = "schema_invalid_fallback"
    else:
        runner = RecordingCategoryRouterRunner(
            output={"agent_path": ["UnknownCategoryAgent"]},
        )
        expected_status = "error_fallback"
    agent = LiveCategoryRouterAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_input(category))

    assert runner.calls == 1
    assert result.agent_path == expected_path
    assert result.fallback_agent_names == expected_fallbacks
    assert agent.workbench_activity[0]["status"] == expected_status


@pytest.mark.asyncio
async def test_live_category_router_falls_back_on_unsupported_model_output() -> None:
    runner = RecordingCategoryRouterRunner(
        output={
            "category": "unsupported category no specialist",
            "agent_path": ("UnsupportedCategoryAgent",),
        }
    )
    agent = LiveCategoryRouterAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_input("office chair"))

    assert runner.calls == 1
    assert result.agent_path == ("GenericProductAnalystAgent",)
    assert agent.workbench_activity[0]["status"] == "schema_invalid_fallback"


@pytest.mark.asyncio
async def test_live_category_router_falls_back_on_timeout() -> None:
    runner = RecordingCategoryRouterRunner(delay_seconds=0.02)
    agent = LiveCategoryRouterAgent(
        settings=_settings(openai_agent_timeout_seconds=0.001),
        model_runner=runner,
    )

    result = await agent.run(_input("monitor"))

    assert runner.calls == 1
    assert result.agent_path == (
        "TechnologyDomainAnalystAgent",
        "MonitorSpecialistAgent",
    )
    assert agent.workbench_activity[0]["status"] == "timeout_fallback"


@pytest.mark.asyncio
async def test_live_category_router_falls_back_on_model_error() -> None:
    runner = RecordingCategoryRouterRunner(error=RuntimeError("mock model failed"))
    agent = LiveCategoryRouterAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_input("monitor"))

    assert runner.calls == 1
    assert result.agent_path == (
        "TechnologyDomainAnalystAgent",
        "MonitorSpecialistAgent",
    )
    assert agent.workbench_activity[0]["status"] == "error_fallback"


@pytest.mark.live_provider
@pytest.mark.asyncio
async def test_live_category_router_agent_live_opt_in() -> None:
    if os.getenv("CARTCART_RUN_LIVE_PROVIDER_TESTS") != "1":
        pytest.skip("Set CARTCART_RUN_LIVE_PROVIDER_TESTS=1 to allow live calls.")

    settings = Settings(_env_file=None, live_agents_enabled=True)  # type: ignore[call-arg]
    if settings.openai_api_key is None:
        pytest.skip("OPENAI_API_KEY is not configured.")

    result = await LiveCategoryRouterAgent(settings=settings).run(_input("monitor"))

    assert result.agent_path
