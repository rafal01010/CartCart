from enum import StrEnum

from pydantic import Field

from app.core.settings import Settings
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
    timeout_seconds: float = Field(gt=0, le=300)
    max_turns: int = Field(ge=1, le=50)
    tracing_enabled: bool
    trace_include_sensitive_data: bool
    trace_workflow_name: str = Field(min_length=1, max_length=120)
    trace_metadata: dict[str, str] = Field(default_factory=dict)
    api_key_configured: bool
    api_key_env_var: str = OPENAI_API_KEY_ENV_VAR
    missing_env_var: str | None = None


def build_openai_agent_run_configuration(
    settings: Settings,
    *,
    agent_name: str | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
) -> OpenAIAgentRunConfiguration:
    api_key_configured = settings.openai_api_key is not None
    live_ready = settings.live_agents_enabled and api_key_configured
    mode = (
        OpenAIAgentRuntimeMode.LIVE
        if live_ready
        else OpenAIAgentRuntimeMode.FIXTURE
    )
    missing_env_var = (
        OPENAI_API_KEY_ENV_VAR
        if settings.live_agents_enabled and not api_key_configured
        else None
    )

    return OpenAIAgentRunConfiguration(
        mode=mode,
        live_agents_enabled=settings.live_agents_enabled,
        model=settings.openai_model,
        timeout_seconds=settings.openai_agent_timeout_seconds,
        max_turns=settings.openai_agent_max_turns,
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
) -> dict[str, str]:
    metadata = {
        "app": "cartcart",
        "environment": settings.environment.value,
        "agent_runtime_mode": mode.value,
        "model": settings.openai_model,
    }
    if agent_name:
        metadata["agent_name"] = agent_name
    if session_id:
        metadata["session_id"] = session_id
    if run_id:
        metadata["run_id"] = run_id
    return metadata
