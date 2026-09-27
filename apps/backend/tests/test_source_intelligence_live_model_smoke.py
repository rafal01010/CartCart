"""Opt-in Task 89P SDK delegation smoke; source data is fixture-only."""

import json
import os

import pytest
from dotenv import dotenv_values

from app.agents.contracts import IKEAStoreIntelligenceAgentInput
from app.agents.live_source_intelligence_manager import (
    SourceIntelligenceManagerAgent,
    SourceManagerInput,
)
from app.agents.openai_config import build_openai_agent_run_configuration
from app.agents.workbench import (
    _WorkbenchIKEAStoreIntelligenceProvider,
    _scenario_ikea_available_regional_product,
)
from app.core.agent_run_profiles import AgentRunProfileName
from app.core.settings import BACKEND_ROOT, AgentWorkflowMode, Settings
from app.schemas.search_sources import SourceIntelligenceCapability


@pytest.mark.live_model
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("CARTCART_RUN_89P_LIVE_SMOKE") != "1",
    reason="Set CARTCART_RUN_89P_LIVE_SMOKE=1 for the credentialed SDK smoke.",
)
async def test_live_parent_delegates_to_ikea_agent_over_fixture_data() -> None:
    """The real SDK must run both parent and nested specialist, without source HTTP."""
    assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY is required."
    local_env = BACKEND_ROOT / ".env"
    assert local_env.is_file(), "The local apps/backend/.env is required."
    local_values = dotenv_values(local_env)
    payload = IKEAStoreIntelligenceAgentInput.model_validate(
        _scenario_ikea_available_regional_product().input
    )
    settings = Settings(  # type: ignore[call-arg]
        _env_file=local_env,
        live_agents_enabled=True,
        agent_workflow_mode=AgentWorkflowMode.LIVE,
        openai_agent_tracing_enabled=False,
    )
    assert {
        AgentRunProfileName.FAST,
        AgentRunProfileName.STRONG,
    } <= set(settings.openai_run_profiles), (
        "The local fast/strong model profiles were not loaded from apps/backend/.env."
    )
    assert settings.openai_model == local_values["CARTCART_OPENAI_MODEL"]
    assert settings.openai_agent_max_turns == int(
        local_values["CARTCART_OPENAI_AGENT_MAX_TURNS"] or "0"
    )
    assert settings.openai_agent_timeout_seconds == float(
        local_values["CARTCART_OPENAI_AGENT_TIMEOUT_SECONDS"] or "0"
    )
    expected_profiles = json.loads(
        local_values["CARTCART_OPENAI_RUN_PROFILES"] or "{}"
    )
    for profile_name in (AgentRunProfileName.FAST, AgentRunProfileName.STRONG):
        assert settings.openai_run_profiles[profile_name].model_dump(
            exclude_none=True
        ) == expected_profiles[profile_name.value], (
            f"Process environment overrides local {profile_name.value} profile."
        )
    parent_config = build_openai_agent_run_configuration(
        settings, agent_name="SourceIntelligenceManagerAgent"
    )
    specialist_config = build_openai_agent_run_configuration(
        settings, agent_name="IKEAStoreIntelligenceAgent"
    )
    assert parent_config.max_turns == 15
    assert specialist_config.max_turns == 9
    assert settings.agent_workflow_mode == AgentWorkflowMode.LIVE
    print(
        "89P live configuration: "
        f"parent={parent_config.model}/{parent_config.max_turns} turns/"
        f"{parent_config.timeout_seconds}s, "
        f"specialist={specialist_config.model}/{specialist_config.max_turns} "
        f"turns/{specialist_config.timeout_seconds}s; "
        "source_provider=in-process IKEA fixture"
    )
    manager = SourceIntelligenceManagerAgent(
        settings=settings,
        ikea_provider=_WorkbenchIKEAStoreIntelligenceProvider(),
    )
    result = await manager.run(
        SourceManagerInput(
            run_id=payload.run_id,
            brief=payload.brief,
            products=payload.products,
            listings=payload.listings,
            source_snapshots=(),
            query_hints=payload.product_queries,
            region_code="PH",
            allowed_capabilities=(
                SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
            ),
        )
    )
    delegated = [
        item for item in result.activity if item["tool_name"] == "agent_as_tool"
    ]
    activity_summary = [
        (item["tool_name"], item["status"]) for item in result.activity
    ]
    assert result.activity[0]["status"] == "completed", (
        result.notes,
        activity_summary,
    )
    assert len(delegated) == 1, (result.notes, activity_summary)
    assert delegated[0]["input"]["agent"] == "IKEAStoreIntelligenceAgent"
    assert result.model_name == parent_config.model
    assert delegated[0]["input"]["model"] == specialist_config.model
    assert delegated[0]["status"] == "validated", (
        result.notes,
        activity_summary,
    )
    assert result.ikea_bundles and result.ikea_bundles[0].evidence
    bundle = result.ikea_bundles[0]
    source_ids = {item.source_id for item in bundle.source_references}
    assert source_ids
    assert all(item.source_id in source_ids for item in bundle.evidence)
    assert any(
        item["tool_name"] == "search_ikea_products"
        for item in result.activity
    )
    assert any(
        item["tool_name"] == "read_ikea_product"
        for item in result.activity
    )
