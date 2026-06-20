import pytest
from fastapi.testclient import TestClient

from app.agents.workbench import (
    AgentWorkbenchError,
    AgentWorkbenchRunRequest,
    AgentWorkbenchRunner,
)
from app.core.settings import Settings
from app.main import create_app


def make_test_client(**settings_overrides: object) -> TestClient:
    values = {
        "environment": "test",
        "frontend_origins": ("http://frontend.test",),
        **settings_overrides,
    }
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        **values,
    )
    return TestClient(create_app(settings))


def test_workbench_route_is_disabled_by_default() -> None:
    client = make_test_client()

    response = client.get("/internal/agent-workbench")

    assert response.status_code == 404


def test_workbench_route_is_unavailable_outside_allowed_environments() -> None:
    client = make_test_client(
        agent_workbench_enabled=True,
        environment="production",
    )

    response = client.get("/internal/agent-workbench")

    assert response.status_code == 404


def test_workbench_route_is_excluded_from_openapi() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/internal/agent-workbench" not in paths
    assert "/internal/agent-workbench/runs" not in paths


def test_workbench_catalog_lists_allowlisted_fake_agent_scenarios() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.get("/internal/agent-workbench")

    assert response.status_code == 200
    body = response.json()
    agent_names = {agent["agent_name"] for agent in body["agents"]}
    assert "ShoppingScopeGuardrail" in agent_names
    assert "SellerListingTrustAgent" in agent_names
    guardrail = next(
        agent
        for agent in body["agents"]
        if agent["agent_name"] == "ShoppingScopeGuardrail"
    )
    assert {scenario["name"] for scenario in guardrail["scenarios"]} >= {
        "guardrail/allowed-monitor",
        "guardrail/blocked-off-topic",
        "guardrail/allowed-coffee-grinder",
        "guardrail/blocked-dangerous-product",
    }
    assert guardrail["modes"] == ["fixture", "mock", "live"]
    guide = next(
        agent
        for agent in body["agents"]
        if agent["agent_name"] == "ShoppingGuideAgent"
    )
    assert {scenario["name"] for scenario in guide["scenarios"]} >= {
        "guide/headphones-missing-budget",
        "guide/ready-monitor-brief",
    }
    assert guide["modes"] == ["fixture", "mock", "live"]
    intake = next(
        agent
        for agent in body["agents"]
        if agent["agent_name"] == "IntakeAgent"
    )
    assert {scenario["name"] for scenario in intake["scenarios"]} >= {
        "intake/monitor-ph-budget",
        "intake/ambiguous-category",
    }
    assert intake["modes"] == ["fixture", "mock", "live"]


def test_workbench_runs_allowlisted_fake_agent_from_internal_endpoint() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "ShoppingScopeGuardrail",
            "scenario_name": "guardrail/allowed-monitor",
            "mode": "fixture",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["agent_name"] == "ShoppingScopeGuardrail"
    assert body["input_schema"] == "ShoppingScopeGuardrailInput"
    assert body["output_schema"] == "ShoppingGuardrailResult"
    assert body["output"]["decision"] == "allowed"
    assert body["allowed_tool_activity"] == []
    assert body["fallback"]["used"] is False
    assert body["usage"] is None
    assert body["trace_id"].startswith("agent_workbench_")
    assert body["elapsed_ms"] >= 0


def test_workbench_mock_guardrail_accepts_required_coffee_grinder_scenario() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "ShoppingScopeGuardrail",
            "scenario_name": "guardrail/allowed-coffee-grinder",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["decision"] == "allowed"
    assert body["allowed_tool_activity"][0]["status"] == "model_guardrail_completed"


def test_workbench_mock_guardrail_blocks_dangerous_product_before_model() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "ShoppingScopeGuardrail",
            "scenario_name": "guardrail/blocked-dangerous-product",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["decision"] == "blocked"
    assert body["output"]["reason"] == "unsafe_product"
    assert body["allowed_tool_activity"][0]["status"] == (
        "not_started_deterministic_block"
    )


def test_workbench_mock_intake_infers_monitor_ph_budget_scenario() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "IntakeAgent",
            "scenario_name": "intake/monitor-ph-budget",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["category"] == "monitor"
    assert body["output"]["category_source"] == "inferred"
    assert body["output"]["region"]["region"]["country_code"] == "PH"
    assert body["output"]["budget"]["amount"]["currency"] == "PHP"
    assert body["output"]["budget"]["amount"]["amount"] == "18000"
    assert {item["text"] for item in body["output"]["constraints"]} >= {
        "27-inch size",
        "1440p resolution",
    }
    assert {item["text"] for item in body["output"]["preferences"]} >= {
        "Good for coding",
        "Good for movies",
    }
    assert body["allowed_tool_activity"][0]["status"] == "model_intake_completed"
    assert body["allowed_tool_activity"][0]["input"]["allowed_tools"] == []


def test_workbench_mock_intake_preserves_ambiguous_category() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "IntakeAgent",
            "scenario_name": "intake/ambiguous-category",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["category"] is None
    assert body["output"]["category_source"] is None
    assert body["allowed_tool_activity"][0]["status"] == "model_intake_completed"


def test_workbench_mock_guide_asks_missing_budget_without_recommendation() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "ShoppingGuideAgent",
            "scenario_name": "guide/headphones-missing-budget",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["status"] == "collecting"
    assert body["output"]["current_question"]["purpose"] in {"budget", "use_case"}
    question_text = body["output"]["current_question"]["text"].lower()
    assert "recommend" not in question_text
    assert "link" not in question_text
    assert body["allowed_tool_activity"][0]["status"] == "model_guide_completed"
    assert body["allowed_tool_activity"][0]["input"]["allowed_tools"] == []


def test_workbench_mock_guide_readies_complete_monitor_brief() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "ShoppingGuideAgent",
            "scenario_name": "guide/ready-monitor-brief",
            "mode": "mock",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output"]["status"] == "ready_for_analysis"
    assert body["output"]["current_question"] is None
    assert body["output"]["ready_brief"]["category"] == "monitor"
    assert body["output"]["ready_brief"]["region"]["region"]["country_code"] == "PH"
    assert body["output"]["ready_brief"]["budget"]["amount"]["currency"] == "PHP"
    assert body["allowed_tool_activity"][0]["status"] == "model_guide_completed"


def test_workbench_rejects_unregistered_agents() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "ArbitraryAgent",
            "scenario_name": "anything",
            "mode": "fixture",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "agent_workbench_agent_not_allowed"


def test_workbench_rejects_invalid_input_override() -> None:
    client = make_test_client(agent_workbench_enabled=True)

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "ShoppingScopeGuardrail",
            "scenario_name": "guardrail/allowed-monitor",
            "mode": "fixture",
            "input": {"user_input": ""},
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "agent_workbench_invalid_input"


def test_workbench_live_mode_requires_live_agent_configuration() -> None:
    client = make_test_client(
        agent_workbench_enabled=True,
        live_agents_enabled=False,
        openai_api_key=None,
    )

    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "ShoppingScopeGuardrail",
            "scenario_name": "guardrail/allowed-monitor",
            "mode": "live",
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "agent_workbench_live_mode_unavailable"
    assert "CARTCART_LIVE_AGENTS_ENABLED=true" in body["error"]["message"]


@pytest.mark.asyncio
async def test_workbench_direct_runner_requires_opt_in_flag() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    runner = AgentWorkbenchRunner(settings)

    with pytest.raises(AgentWorkbenchError) as exc_info:
        await runner.run(
            AgentWorkbenchRunRequest(
                agent_name="ShoppingScopeGuardrail",
                scenario_name="guardrail/allowed-monitor",
            )
        )

    assert exc_info.value.code == "agent_workbench_disabled"
