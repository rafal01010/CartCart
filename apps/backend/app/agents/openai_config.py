from dataclasses import replace
from enum import StrEnum
from typing import Any

from agents import Agent
from pydantic import Field
from openai.types.shared import Reasoning

from app.agents.catalog import ApprovedSDKTool, DEFAULT_AGENT_CATALOG
from app.agents.research_guidance import agent_research_guidance
from app.core.agent_run_profiles import (
    AgentRunProfileName,
    AgentRunProfileOptions,
    ReasoningEffort,
)
from app.core.settings import Settings, UNCONFIGURED_OPENAI_AGENT_MODEL
from app.schemas.base import CartCartBaseModel


OPENAI_API_KEY_ENV_VAR = "OPENAI_API_KEY"
LIVE_AGENTS_ENABLED_ENV_VAR = "CARTCART_LIVE_AGENTS_ENABLED"


class OpenAIAgentRuntimeMode(StrEnum):
    FIXTURE = "fixture"
    LIVE = "live"


class OpenAIAgentConfigurationError(RuntimeError):
    """Raised when a caller requests live OpenAI agents before they are ready."""


class OpenAIAgentRunConfiguration(CartCartBaseModel):
    mode: OpenAIAgentRuntimeMode
    live_agents_enabled: bool
    model: str = Field(min_length=1, max_length=200)
    run_profile: AgentRunProfileName
    timeout_seconds: float = Field(gt=0, le=300)
    max_turns: int = Field(ge=1, le=50)
    reasoning_effort: ReasoningEffort | None = None
    tracing_enabled: bool
    trace_include_sensitive_data: bool
    trace_workflow_name: str = Field(min_length=1, max_length=120)
    trace_metadata: dict[str, str] = Field(default_factory=dict)
    api_key_configured: bool
    api_key_env_var: str = OPENAI_API_KEY_ENV_VAR
    missing_env_var: str | None = None

    @property
    def reasoning(self) -> Reasoning | None:
        if self.reasoning_effort is None:
            return None
        if self.reasoning_effort == "max":
            raise OpenAIAgentConfigurationError(
                "Reasoning effort 'max' is unsupported by the installed SDK. "
                "Select 'xhigh' or another supported effort."
            )
        return Reasoning(effort=self.reasoning_effort)


def apply_openai_agent_run_profile(
    agent: Agent[Any], configuration: OpenAIAgentRunConfiguration
) -> None:
    """Keep model-specific settings on the agent, not the whole SDK run."""
    reasoning = configuration.reasoning
    if reasoning is not None:
        agent.model_settings = replace(agent.model_settings, reasoning=reasoning)
    agent_name = configuration.trace_metadata.get("agent_name")
    entry = DEFAULT_AGENT_CATALOG.get(agent_name) if agent_name else None
    if entry and ApprovedSDKTool.HOSTED_WEB_SEARCH in entry.approved_sdk_tools:
        agent.model_settings = replace(
            agent.model_settings,
            response_include=list(
                dict.fromkeys(
                    (
                        *(agent.model_settings.response_include or ()),
                        "web_search_call.action.sources",
                    )
                )
            ),
        )
    if isinstance(agent.instructions, str):
        agent.instructions += "\n\n" + agent_research_guidance(agent_name)


def build_openai_agent_run_configuration(
    settings: Settings,
    *,
    agent_name: str | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
) -> OpenAIAgentRunConfiguration:
    entry = DEFAULT_AGENT_CATALOG.get(agent_name) if agent_name else None
    if agent_name is not None and entry is None:
        raise OpenAIAgentConfigurationError(
            f"Unknown registered agent for OpenAI run configuration: {agent_name}"
        )
    profile_name = (
        entry.run_profile if entry is not None else AgentRunProfileName.DEFAULT
    )
    default_profile = settings.openai_run_profiles.get(
        AgentRunProfileName.DEFAULT, AgentRunProfileOptions()
    )
    profile = settings.openai_run_profiles.get(profile_name, AgentRunProfileOptions())
    override = settings.openai_agent_overrides.get(
        agent_name or "", AgentRunProfileOptions()
    )
    model = (
        override.model
        or profile.model
        or default_profile.model
        or settings.openai_model
    )
    timeout_seconds = (
        override.timeout_seconds
        or profile.timeout_seconds
        or default_profile.timeout_seconds
        or settings.openai_agent_timeout_seconds
    )
    max_turns = (
        override.max_turns
        or profile.max_turns
        or default_profile.max_turns
        or settings.openai_agent_max_turns
    )
    reasoning_effort = (
        override.reasoning_effort
        or profile.reasoning_effort
        or default_profile.reasoning_effort
    )
    api_key_configured = settings.openai_api_key is not None
    live_ready = settings.live_agents_enabled and api_key_configured
    if live_ready and model == UNCONFIGURED_OPENAI_AGENT_MODEL:
        raise OpenAIAgentConfigurationError(
            "Live OpenAI agents require CARTCART_OPENAI_MODEL in the process "
            "environment or apps/backend/.env, or a model in the selected "
            "agent run profile."
        )
    mode = OpenAIAgentRuntimeMode.LIVE if live_ready else OpenAIAgentRuntimeMode.FIXTURE
    missing_env_var = (
        OPENAI_API_KEY_ENV_VAR
        if settings.live_agents_enabled and not api_key_configured
        else None
    )

    return OpenAIAgentRunConfiguration(
        mode=mode,
        live_agents_enabled=settings.live_agents_enabled,
        model=model,
        run_profile=profile_name,
        timeout_seconds=timeout_seconds,
        max_turns=max_turns,
        reasoning_effort=reasoning_effort,
        tracing_enabled=settings.openai_agent_tracing_enabled,
        trace_include_sensitive_data=(
            settings.openai_agent_trace_include_sensitive_data
        ),
        trace_workflow_name=settings.openai_agent_trace_workflow_name,
        trace_metadata=_trace_metadata(
            settings,
            agent_name=agent_name,
            session_id=session_id,
            run_id=run_id,
            mode=mode,
            model=model,
            run_profile=profile_name,
            reasoning_effort=reasoning_effort,
        ),
        api_key_configured=api_key_configured,
        missing_env_var=missing_env_var,
    )


def require_live_openai_agent_configuration(
    settings: Settings,
    *,
    agent_name: str | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
) -> OpenAIAgentRunConfiguration:
    configuration = build_openai_agent_run_configuration(
        settings,
        agent_name=agent_name,
        session_id=session_id,
        run_id=run_id,
    )
    if not settings.live_agents_enabled:
        raise OpenAIAgentConfigurationError(
            "Live OpenAI agents are disabled. Set "
            f"{LIVE_AGENTS_ENABLED_ENV_VAR}=true and configure "
            f"{OPENAI_API_KEY_ENV_VAR} before requesting live-agent mode."
        )
    if settings.openai_api_key is None:
        raise OpenAIAgentConfigurationError(
            f"Live OpenAI agents require {OPENAI_API_KEY_ENV_VAR}. "
            "Fixture and mocked agent modes can run without it."
        )
    return configuration


def _trace_metadata(
    settings: Settings,
    *,
    agent_name: str | None,
    session_id: str | None,
    run_id: str | None,
    mode: OpenAIAgentRuntimeMode,
    model: str,
    run_profile: AgentRunProfileName,
    reasoning_effort: ReasoningEffort | None,
) -> dict[str, str]:
    metadata = {
        "app": "cartcart",
        "environment": settings.environment.value,
        "agent_runtime_mode": mode.value,
        "model": model,
        "run_profile": run_profile.value,
    }
    if agent_name:
        metadata["agent_name"] = agent_name
    if reasoning_effort:
        metadata["reasoning_effort"] = reasoning_effort
    if session_id:
        metadata["session_id"] = session_id
    if run_id:
        metadata["run_id"] = run_id
    return metadata
