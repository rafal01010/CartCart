import pytest

from app.agents.openai_config import (
    OPENAI_API_KEY_ENV_VAR,
    LIVE_AGENTS_ENABLED_ENV_VAR,
    OpenAIAgentConfigurationError,
    OpenAIAgentRuntimeMode,
    build_openai_agent_run_configuration,
    require_live_openai_agent_configuration,
)
from app.core.settings import DEFAULT_OPENAI_AGENT_MODEL, Settings


def test_fixture_agent_configuration_does_not_require_openai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CARTCART_OPENAI_API_KEY", raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    configuration = build_openai_agent_run_configuration(
        settings,
        agent_name="IntakeAgent",
        session_id="session_test",
        run_id="run_test",
    )

    assert configuration.mode == OpenAIAgentRuntimeMode.FIXTURE
    assert configuration.live_agents_enabled is False
    assert configuration.api_key_configured is False
    assert configuration.missing_env_var is None
    assert configuration.model == DEFAULT_OPENAI_AGENT_MODEL
    assert configuration.timeout_seconds == 45.0
    assert configuration.trace_metadata == {
        "app": "cartcart",
        "environment": "local",
        "agent_runtime_mode": "fixture",
        "model": DEFAULT_OPENAI_AGENT_MODEL,
        "agent_name": "IntakeAgent",
        "session_id": "session_test",
        "run_id": "run_test",
    }


def test_live_agent_configuration_requires_enabled_flag() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        live_agents_enabled=False,
        openai_api_key="test-openai-key",
    )

    with pytest.raises(OpenAIAgentConfigurationError) as exc_info:
        require_live_openai_agent_configuration(settings)

    assert LIVE_AGENTS_ENABLED_ENV_VAR in str(exc_info.value)
    assert OPENAI_API_KEY_ENV_VAR in str(exc_info.value)


def test_live_agent_configuration_requires_openai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CARTCART_OPENAI_API_KEY", raising=False)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        live_agents_enabled=True,
        openai_api_key=None,
    )

    configuration = build_openai_agent_run_configuration(settings)

    assert configuration.mode == OpenAIAgentRuntimeMode.FIXTURE
    assert configuration.live_agents_enabled is True
    assert configuration.missing_env_var == OPENAI_API_KEY_ENV_VAR
    with pytest.raises(OpenAIAgentConfigurationError) as exc_info:
        require_live_openai_agent_configuration(settings)

    assert OPENAI_API_KEY_ENV_VAR in str(exc_info.value)
    assert "Fixture and mocked agent modes can run without it." in str(
        exc_info.value
    )


def test_live_agent_configuration_serializes_no_secret() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        environment="live",
        live_agents_enabled=True,
        openai_api_key="test-openai-key",
        openai_model="gpt-5.5",
        openai_agent_timeout_seconds=60,
        openai_agent_max_turns=10,
        openai_agent_tracing_enabled=True,
        openai_agent_trace_include_sensitive_data=False,
        openai_agent_trace_workflow_name="cartcart-live-agents",
    )

    configuration = require_live_openai_agent_configuration(
        settings,
        agent_name="QueryPlannerAgent",
        run_id="run_live",
    )

    assert configuration.mode == OpenAIAgentRuntimeMode.LIVE
    assert configuration.api_key_configured is True
    assert configuration.model == "gpt-5.5"
    assert configuration.timeout_seconds == 60
    assert configuration.max_turns == 10
    assert configuration.tracing_enabled is True
    assert configuration.trace_include_sensitive_data is False
    assert configuration.trace_workflow_name == "cartcart-live-agents"
    assert configuration.trace_metadata["environment"] == "live"
    assert configuration.trace_metadata["agent_runtime_mode"] == "live"
    assert configuration.trace_metadata["agent_name"] == "QueryPlannerAgent"
    assert configuration.trace_metadata["run_id"] == "run_live"
    assert "test-openai-key" not in configuration.model_dump_json()
