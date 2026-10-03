from pathlib import Path

import pytest
from agents import Agent
from pydantic import ValidationError

from app.agents.openai_config import (
    OPENAI_API_KEY_ENV_VAR,
    LIVE_AGENTS_ENABLED_ENV_VAR,
    OpenAIAgentConfigurationError,
    OpenAIAgentRuntimeMode,
    build_openai_agent_run_configuration,
    require_live_openai_agent_configuration,
    apply_openai_agent_run_profile,
)
from app.core import settings as settings_module
from app.core.settings import Settings, UNCONFIGURED_OPENAI_AGENT_MODEL
from app.core.agent_run_profiles import AgentRunProfileName


@pytest.mark.parametrize(
    "name",
    (
        "GeneralShoppingAgent",
        "TechnologyDomainAnalystAgent",
        "SmartphoneSpecialistAgent",
        "DiscoveryAgent",
        "SellerListingTrustAgent",
        "YouTubeReviewIntelligenceAgent",
        "RedditCommunityIntelligenceAgent",
        "AmazonProductIntelligenceAgent",
        "IKEAStoreIntelligenceAgent",
    ),
)
def test_research_agents_receive_current_regional_tool_guidance(name: str) -> None:
    configuration = build_openai_agent_run_configuration(
        Settings(_env_file=None), agent_name=name
    )
    agent = Agent(name=name, instructions="Existing role instructions.")
    apply_openai_agent_run_profile(agent, configuration)
    assert isinstance(agent.instructions, str)
    assert agent.instructions.startswith("Existing role instructions.")
    assert "Current UTC date:" in agent.instructions
    assert "buyer's country" in agent.instructions
    assert "try another" in agent.instructions
    assert "web_search_call.action.sources" in (
        agent.model_settings.response_include or ()
    )


def test_example_gives_the_owner_chain_a_separate_research_budget() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=Path(__file__).parents[1] / ".env.example",
    )
    owner = build_openai_agent_run_configuration(
        settings, agent_name="GeneralShoppingAgent"
    )
    phone = build_openai_agent_run_configuration(
        settings, agent_name="SmartphoneSpecialistAgent"
    )
    assert (owner.timeout_seconds, owner.max_turns) == (180, 25)
    assert (phone.timeout_seconds, phone.max_turns) == (60, 15)


def test_unsupported_sdk_reasoning_effort_is_an_explicit_configuration_error() -> None:
    configuration = build_openai_agent_run_configuration(
        Settings(
            _env_file=None, openai_run_profiles={"default": {"reasoning_effort": "max"}}
        ),
    )
    with pytest.raises(
        OpenAIAgentConfigurationError, match="unsupported by the installed SDK"
    ):
        apply_openai_agent_run_profile(Agent(name="test"), configuration)


def test_fixture_agent_configuration_does_not_require_openai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CARTCART_OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("CARTCART_OPENAI_MODEL", "fixture-test-model")
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
    assert configuration.model == "fixture-test-model"
    assert configuration.run_profile == AgentRunProfileName.FAST
    assert configuration.timeout_seconds == 45.0
    assert configuration.trace_metadata == {
        "app": "cartcart",
        "environment": "local",
        "agent_runtime_mode": "fixture",
        "model": "fixture-test-model",
        "run_profile": "fast",
        "agent_name": "IntakeAgent",
        "session_id": "session_test",
        "run_id": "run_test",
    }


def test_live_configuration_without_any_model_fails_before_sdk_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CARTCART_OPENAI_MODEL", raising=False)
    monkeypatch.setattr(settings_module, "BACKEND_ROOT", tmp_path)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        live_agents_enabled=True,
        openai_api_key="test-openai-key",
    )

    assert settings.openai_model == UNCONFIGURED_OPENAI_AGENT_MODEL
    with pytest.raises(OpenAIAgentConfigurationError, match="CARTCART_OPENAI_MODEL"):
        build_openai_agent_run_configuration(settings, agent_name="IntakeAgent")


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
    assert "Fixture and mocked agent modes can run without it." in str(exc_info.value)


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


def test_catalog_profiles_resolve_different_models_in_one_fixture_run() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        openai_model="fallback-model",
        openai_run_profiles={
            "fast": {
                "model": "small-model",
                "reasoning_effort": "none",
                "timeout_seconds": 20,
                "max_turns": 4,
            },
            "strong": {
                "model": "large-model",
                "reasoning_effort": "medium",
                "timeout_seconds": 70,
            },
        },
    )

    extraction = build_openai_agent_run_configuration(
        settings, agent_name="ExtractionAgent", run_id="same-shopping-run"
    )
    decision = build_openai_agent_run_configuration(
        settings, agent_name="ComparisonDecisionAgent", run_id="same-shopping-run"
    )
    source_agent = build_openai_agent_run_configuration(
        settings, agent_name="YouTubeReviewIntelligenceAgent"
    )

    assert extraction.mode == decision.mode == OpenAIAgentRuntimeMode.FIXTURE
    assert (extraction.model, decision.model, source_agent.model) == (
        "small-model",
        "large-model",
        "small-model",
    )
    assert (extraction.timeout_seconds, extraction.max_turns) == (20, 4)
    assert (decision.timeout_seconds, decision.max_turns) == (70, 12)
    assert extraction.reasoning is not None
    assert extraction.reasoning.effort == "none"
    assert decision.reasoning is not None
    assert decision.reasoning.effort == "medium"
    assert decision.trace_metadata["model"] == "large-model"


def test_exact_agent_override_wins_over_catalog_profile() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        openai_model="fallback-model",
        openai_run_profiles={"strong": {"model": "strong-model", "max_turns": 10}},
        openai_agent_overrides={
            "VerifierCriticAgent": {
                "model": "critic-model",
                "max_turns": 12,
                "reasoning_effort": "high",
            }
        },
    )

    critic = build_openai_agent_run_configuration(
        settings, agent_name="VerifierCriticAgent"
    )
    decision = build_openai_agent_run_configuration(
        settings, agent_name="ComparisonDecisionAgent"
    )

    assert (critic.model, critic.max_turns) == ("critic-model", 12)
    assert critic.reasoning_effort == "high"
    assert (decision.model, decision.max_turns) == ("strong-model", 10)


def test_json_environment_profiles_and_default_profile_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CARTCART_OPENAI_RUN_PROFILES",
        '{"default":{"model":"default-model","timeout_seconds":55},'
        '"fast":{"max_turns":3}}',
    )
    monkeypatch.setenv(
        "CARTCART_OPENAI_AGENT_OVERRIDES",
        '{"IntakeAgent":{"model":"intake-model"}}',
    )
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    intake = build_openai_agent_run_configuration(settings, agent_name="IntakeAgent")
    guide = build_openai_agent_run_configuration(
        settings, agent_name="ShoppingGuideAgent"
    )

    assert (intake.model, intake.timeout_seconds, intake.max_turns) == (
        "intake-model",
        55,
        3,
    )
    assert (guide.model, guide.timeout_seconds, guide.max_turns) == (
        "default-model",
        55,
        3,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("openai_run_profiles", {"unknown": {"model": "test-model"}}),
        ("openai_run_profiles", {"fast": {"model": "   "}}),
        ("openai_run_profiles", {"fast": {"max_turns": 0}}),
        ("openai_run_profiles", {"strong": {"reasoning_effort": "ultra"}}),
        ("openai_agent_overrides", {"UnknownAgent": {"model": "test-model"}}),
    ),
)
def test_invalid_profile_configuration_is_rejected(
    field: str, value: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})  # type: ignore[call-arg]
