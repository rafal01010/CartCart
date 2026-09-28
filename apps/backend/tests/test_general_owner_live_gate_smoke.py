"""Opt-in credentialed Task 89Y smokes; application providers stay in process."""

import json
import os

import pytest
from dotenv import dotenv_values
from sqlalchemy.ext.asyncio import create_async_engine

import app.db.models  # noqa: F401
from app.agents.contracts import DiscoveryAgentInput, GeneralShoppingAgentInput
from app.agents.live_discovery import LiveDiscoveryAgent
from app.agents.live_general_shopping import LiveGeneralShoppingAgent
from app.agents.openai_config import build_openai_agent_run_configuration
from app.agents.research_tools import AgentResearchTools
from app.agents.workbench import (
    _GeneralFixtureExtractionProvider,
    _general_fixture_search_provider,
)
from app.core.agent_run_profiles import AgentRunProfileName
from app.core.settings import BACKEND_ROOT, AgentWorkflowMode, Settings
from app.db.base import Base
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_session_factory
from app.schemas.ids import new_id
from app.schemas.intake import CreateSessionRequest, FieldSource, ShoppingBrief
from app.schemas.search_sources import SearchIntent, SearchPlan, SearchQuery


def _live_settings() -> Settings:
    """Fail before any call if effective non-secret settings drift from .env."""
    env_file = BACKEND_ROOT / ".env"
    assert env_file.is_file(), "apps/backend/.env is required for this smoke."
    local = dotenv_values(env_file)
    for key in (
        "CARTCART_OPENAI_MODEL",
        "CARTCART_OPENAI_AGENT_MAX_TURNS",
        "CARTCART_OPENAI_AGENT_TIMEOUT_SECONDS",
        "CARTCART_OPENAI_RUN_PROFILES",
        "CARTCART_AGENT_WORKFLOW_MODE",
        "CARTCART_LIVE_AGENTS_ENABLED",
    ):
        assert local.get(key), f"{key} must be set in apps/backend/.env."
        assert key not in os.environ, f"Unexpected process override of {key}."
    assert not os.environ.get("CARTCART_OPENAI_AGENT_OVERRIDES"), (
        "Unexpected process model override."
    )
    assert local["CARTCART_AGENT_WORKFLOW_MODE"] == "fixture"
    assert local["CARTCART_LIVE_AGENTS_ENABLED"] == "false"
    settings = Settings(
        _env_file=env_file,
        live_agents_enabled=True,
        agent_workflow_mode=AgentWorkflowMode.LIVE,
        openai_agent_tracing_enabled=False,
    )
    assert settings.openai_model == local["CARTCART_OPENAI_MODEL"]
    assert settings.openai_agent_max_turns == int(
        local["CARTCART_OPENAI_AGENT_MAX_TURNS"] or "0"
    )
    assert settings.openai_agent_timeout_seconds == float(
        local["CARTCART_OPENAI_AGENT_TIMEOUT_SECONDS"] or "0"
    )
    expected_profiles = json.loads(local["CARTCART_OPENAI_RUN_PROFILES"] or "{}")
    for profile in (AgentRunProfileName.FAST, AgentRunProfileName.STRONG):
        assert (
            settings.openai_run_profiles[profile].model_dump(exclude_none=True)
            == expected_profiles[profile.value]
        )
    expected_overrides = json.loads(
        local.get("CARTCART_OPENAI_AGENT_OVERRIDES") or "{}"
    )
    assert {
        name: profile.model_dump(exclude_none=True)
        for name, profile in settings.openai_agent_overrides.items()
    } == expected_overrides
    assert settings.openai_api_key is not None
    assert (
        os.environ.get("OPENAI_API_KEY") == settings.openai_api_key.get_secret_value()
    )
    assert settings.agent_workflow_mode == AgentWorkflowMode.LIVE
    for name in (
        "GeneralShoppingAgent",
        "TechnologyDomainAnalystAgent",
        "SmartphoneSpecialistAgent",
        "DiscoveryAgent",
    ):
        profile = build_openai_agent_run_configuration(settings, agent_name=name)
        assert profile.model == settings.openai_run_profiles[profile.run_profile].model
        assert (
            profile.max_turns
            == settings.openai_run_profiles[profile.run_profile].max_turns
        )
        assert (
            profile.timeout_seconds
            == settings.openai_run_profiles[profile.run_profile].timeout_seconds
        )
        print(
            f"89Y {name}: {profile.model}, {profile.max_turns} turns, "
            f"{profile.timeout_seconds}s, {profile.reasoning_effort}; "
            "fixture application providers"
        )
    return settings


async def _fixture_run(query: str):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    run_id = new_id()
    brief = ShoppingBrief(
        original_query=query,
        category="smartphone",
        category_source=FieldSource.INFERRED,
    )
    async with factory() as session:
        shopper = await SessionRepository(session).create(
            original_input=CreateSessionRequest(query=query), current_brief=brief
        )
        await RunRepository(session).create(shopper.session_id, run_id=run_id)
        await session.commit()
    return engine, factory, run_id, brief


def _research_tools(name, run_id, factory, region_code):
    return AgentResearchTools(
        agent_name=name,
        run_id=run_id,
        session_factory=factory,
        search_provider=_general_fixture_search_provider(),
        extraction_provider=_GeneralFixtureExtractionProvider(),
        required_region_code=region_code,
    )


@pytest.mark.live_model
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("CARTCART_RUN_89Y_LIVE_SMOKE") != "1",
    reason="Set CARTCART_RUN_89Y_LIVE_SMOKE=1 for this credentialed gate.",
)
async def test_live_general_to_technology_to_smartphone_handoff() -> None:
    settings = _live_settings()
    engine, factory, run_id, brief = await _fixture_run(
        "I need a smartphone with good battery and camera. Please use the "
        "technology analyst and phone specialist for a careful answer."
    )
    try:
        owner = LiveGeneralShoppingAgent(
            settings=settings,
            session_factory=factory,
            regional_research_tools_factory=lambda actual_run_id, region: (
                _research_tools("GeneralShoppingAgent", actual_run_id, factory, region)
            ),
            technology_research_tools_factory=lambda actual_run_id, region: (
                _research_tools(
                    "TechnologyDomainAnalystAgent", actual_run_id, factory, region
                )
            ),
        )
        draft = await owner.run(GeneralShoppingAgentInput(run_id=run_id, brief=brief))
        handoffs = [
            item
            for item in owner.workbench_activity
            if item["tool_name"] == "sdk_handoff" and item["status"] == "completed"
        ]
        print(
            "89Y handoff statuses:",
            [(item["output"]["target_agent"], item["status"]) for item in handoffs],
        )
        assert [item["output"]["target_agent"] for item in handoffs] == [
            "TechnologyDomainAnalystAgent",
            "SmartphoneSpecialistAgent",
        ]
        assert draft.owner_agent_name == "SmartphoneSpecialistAgent"
        assert handoffs[-1]["output"]["last_agent"] == draft.owner_agent_name
        assert draft.rationale or draft.evidence_gaps
    finally:
        await engine.dispose()


@pytest.mark.live_model
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("CARTCART_RUN_89Y_LIVE_SMOKE") != "1",
    reason="Set CARTCART_RUN_89Y_LIVE_SMOKE=1 for this credentialed gate.",
)
async def test_live_hosted_search_maps_citations_to_persisted_ids() -> None:
    settings = _live_settings()
    engine, factory, run_id, _ = await _fixture_run(
        "Find a current independent review of a smartphone with strong battery. "
        "Use hosted web search to find a review URL, then classify the cited lead."
    )
    try:
        agent = LiveDiscoveryAgent(
            settings=settings,
            research_tools_factory=lambda actual_run_id: _research_tools(
                "DiscoveryAgent", actual_run_id, factory, None
            ),
        )
        result = await agent.run(
            DiscoveryAgentInput(
                run_id=run_id,
                brief=ShoppingBrief(
                    original_query="Find a current independent smartphone battery review. "
                    "Use hosted web search and classify a cited review URL.",
                    category="smartphone",
                    category_source=FieldSource.INFERRED,
                ),
                search_plan=SearchPlan(
                    queries=(
                        SearchQuery(
                            query="independent smartphone battery review",
                            intent=SearchIntent.REVIEW,
                        ),
                    ),
                ),
            )
        )
        activity = agent.workbench_activity
        hosted = [item for item in activity if item["tool_name"] == "web_search"]
        mapped = [
            item for item in activity if item["tool_name"] == "web_search_citations"
        ]
        print(
            "89Y hosted statuses:",
            [(item["tool_name"], item["status"]) for item in activity],
        )
        assert any(item["status"] == "completed" for item in hosted)
        assert mapped and mapped[0]["status"] == "mapped"
        citations = mapped[0]["output"]["citations"]
        assert citations
        async with factory() as session:
            repository = SearchSourceRepository(session)
            sources = await repository.list_search_results(run_id)
            evidence = await repository.list_source_evidence(run_id)
        source_ids = {str(item.source_id) for item in sources}
        evidence_ids = {str(item.evidence_id) for item in evidence}
        assert all(item["source_id"] in source_ids for item in citations)
        assert all(item["evidence_id"] in evidence_ids for item in citations)
        assert {str(item.source_id) for item in result.source_decisions} >= {
            item["source_id"] for item in citations
        }
    finally:
        await engine.dispose()
