"""Offline SDK-result tests for the four scoped hosted source researchers."""

from dataclasses import dataclass
from typing import Any

import pytest
from agents import WebSearchTool
from sqlalchemy.ext.asyncio import create_async_engine

from app.agents.contracts import (
    AmazonProductIntelligenceAgentInput,
    IKEAStoreIntelligenceAgentInput,
    RedditCommunityIntelligenceAgentInput,
    YouTubeReviewIntelligenceAgentInput,
)
from app.agents.openai_config import OpenAIAgentConfigurationError
from app.agents.research_tools import HostedCitationStore
from app.agents.workbench import (
    _live_amazon_product_intelligence_agent,
    _live_ikea_store_intelligence_agent,
    _live_reddit_community_intelligence_agent,
    _live_youtube_review_intelligence_agent,
    _scenario_amazon_third_party_seller_region_gap,
    _scenario_ikea_available_regional_product,
    _scenario_reddit_headphones_recurring_complaint,
    _scenario_youtube_monitor_review_transcript,
)
from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_session_factory
from app.schemas.intake import CreateSessionRequest
import app.db.models  # noqa: F401


CASES = (
    (
        "YouTubeReviewIntelligenceAgent",
        YouTubeReviewIntelligenceAgentInput,
        _scenario_youtube_monitor_review_transcript,
        _live_youtube_review_intelligence_agent,
        "https://www.youtube.com/watch?v=review123",
        {"search_videos", "read_video_metadata", "read_video_transcript"},
    ),
    (
        "RedditCommunityIntelligenceAgent",
        RedditCommunityIntelligenceAgentInput,
        _scenario_reddit_headphones_recurring_complaint,
        _live_reddit_community_intelligence_agent,
        "https://www.reddit.com/r/headphones/comments/abc123/owners",
        {"search_community_discussions", "read_community_discussion"},
    ),
    (
        "AmazonProductIntelligenceAgent",
        AmazonProductIntelligenceAgentInput,
        _scenario_amazon_third_party_seller_region_gap,
        _live_amazon_product_intelligence_agent,
        "https://www.amazon.com/dp/B000000000",
        {"search_amazon_products", "read_amazon_product"},
    ),
    (
        "IKEAStoreIntelligenceAgent",
        IKEAStoreIntelligenceAgentInput,
        _scenario_ikea_available_regional_product,
        _live_ikea_store_intelligence_agent,
        "https://www.ikea.com/ph/en/p/micke-desk-90214308/",
        {"search_ikea_products", "read_ikea_product"},
    ),
)


@dataclass
class _Runner:
    output: dict[str, Any]
    raw_responses: list[Any]
    seen_agent: Any = None

    async def run(
        self,
        agent: Any,
        model_input: str,
        *,
        run_config: Any,
        max_turns: int,
        tools: Any,
    ) -> Any:
        del model_input, run_config, max_turns, tools
        self.seen_agent = agent
        return type(
            "Result",
            (),
            {"final_output": self.output, "raw_responses": self.raw_responses},
        )()


def _settings(model: str = "gpt-6-luna") -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        live_agents_enabled=True,
        openai_api_key="mock-only-no-call",
        openai_model=model,
    )


def _response(url: str) -> list[Any]:
    return [
        {
            "output": [
                {
                    "type": "web_search_call",
                    "id": "ws_1",
                    "status": "completed",
                    "action": {"type": "search", "sources": [{"url": url}]},
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "text": "Research lead",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": url,
                                    "title": "Research lead",
                                    "start_index": 0,
                                    "end_index": 13,
                                }
                            ],
                        }
                    ],
                },
            ]
        }
    ]


def _empty_output(name: str, **extra: Any) -> dict[str, Any]:
    selected = (
        {"selected_videos": [], "claims": []}
        if name == "YouTubeReviewIntelligenceAgent"
        else {"selected_discussions": [], "signals": []}
        if name == "RedditCommunityIntelligenceAgent"
        else {"selected_sources": []}
    )
    return {**selected, **extra}


@pytest.mark.asyncio
@pytest.mark.parametrize("name,input_type,scenario,factory,url,provider_tools", CASES)
async def test_four_specialists_attach_optional_hosted_tool_and_persist_scoped_citation(
    name: str,
    input_type: Any,
    scenario: Any,
    factory: Any,
    url: str,
    provider_tools: set[str],
) -> None:
    input_data = input_type.model_validate(scenario().input)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = create_session_factory(engine)
        async with sessions() as session:
            shopping_session = await SessionRepository(session).create(
                original_input=CreateSessionRequest(
                    query=input_data.brief.original_query
                ),
                current_brief=input_data.brief,
            )
            await RunRepository(session).create(
                shopping_session.session_id, run_id=input_data.run_id
            )
            await session.commit()

        agent = factory(_settings())
        agent.citation_store = HostedCitationStore(
            run_id=input_data.run_id, session_factory=sessions
        )
        runner = _Runner(
            _empty_output(
                name,
                retained_web_urls=[url],
                evidence_gaps=["Provider evidence absent."],
            ),
            _response(url),
        )
        agent.model_runner = runner
        await agent.run(input_data)
        sdk_agent = runner.seen_agent
        assert sdk_agent.name == name
        assert sdk_agent.model_settings.tool_choice == "auto"
        assert {tool.name for tool in sdk_agent.tools} == provider_tools | {
            "web_search"
        }
        assert sum(isinstance(tool, WebSearchTool) for tool in sdk_agent.tools) == 1
        web_tool = next(
            tool for tool in sdk_agent.tools if isinstance(tool, WebSearchTool)
        )
        assert web_tool.filters is not None
        assert any(
            item["tool_name"] == "web_search_citation"
            and item["status"] == "retained"
            and item["input"]["agent"] == name
            and item["input"]["url"] == url
            and item["output"]["evidence_id"]
            for item in agent.workbench_activity
        )
        async with sessions() as session:
            repository = SearchSourceRepository(session)
            assert len(await repository.list_search_results(input_data.run_id)) == 1
            evidence = await repository.list_source_evidence(input_data.run_id)
            assert len(evidence) == 1
            assert evidence[0].target.target_type.value == "source_metadata"

        agent.model_runner = _Runner(
            _empty_output(name, evidence_gaps=["No source found."]), []
        )
        await agent.run(input_data)
        assert not any(
            item["tool_name"] == "web_search" for item in agent.workbench_activity
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("name,input_type,scenario,factory,url,provider_tools", CASES)
async def test_specialist_rejects_wrong_site_or_region_without_site_evidence(
    name: str,
    input_type: Any,
    scenario: Any,
    factory: Any,
    url: str,
    provider_tools: set[str],
) -> None:
    del url, provider_tools
    input_data = input_type.model_validate(scenario().input)
    wrong_url = (
        "https://www.ikea.com/us/en/p/micke-desk-123/"
        if name == "IKEAStoreIntelligenceAgent"
        else "https://example.com/unrelated"
    )
    agent = factory(_settings())
    # A real live run requires persistence before it can attach hosted search.
    with pytest.raises(OpenAIAgentConfigurationError):
        agent.prepare_delegated_run(input_data)
    agent.citation_store = HostedCitationStore(
        run_id=input_data.run_id,
        session_factory=object(),  # type: ignore[arg-type]
    )
    runner = _Runner(
        _empty_output(name, retained_web_urls=[wrong_url]), _response(wrong_url)
    )
    agent.model_runner = runner
    await agent.run(input_data)
    assert any(
        item["tool_name"] == "web_search_citation" and item["status"] == "rejected"
        for item in agent.workbench_activity
    ), agent.workbench_activity


@pytest.mark.parametrize("name,input_type,scenario,factory,url,provider_tools", CASES)
def test_unsupported_model_fails_closed(
    name: str,
    input_type: Any,
    scenario: Any,
    factory: Any,
    url: str,
    provider_tools: set[str],
) -> None:
    del name, url, provider_tools
    input_data = input_type.model_validate(scenario().input)
    agent = factory(_settings("unknown-web-tool-model"))
    agent.citation_store = HostedCitationStore(
        run_id=input_data.run_id,
        session_factory=object(),  # type: ignore[arg-type]
    )
    with pytest.raises(OpenAIAgentConfigurationError, match="no verified hosted"):
        agent.prepare_delegated_run(input_data)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,input_type,scenario,factory,url,provider_tools", CASES)
@pytest.mark.parametrize("failure", ["failed_call", "missing_citation"])
async def test_hosted_failure_keeps_site_evidence_empty_and_reports_gap(
    name: str,
    input_type: Any,
    scenario: Any,
    factory: Any,
    url: str,
    provider_tools: set[str],
    failure: str,
) -> None:
    del provider_tools
    input_data = input_type.model_validate(scenario().input)
    agent = factory(_settings())
    agent.citation_store = HostedCitationStore(
        run_id=input_data.run_id,
        session_factory=object(),  # type: ignore[arg-type]
    )
    raw = _response(url)
    if failure == "failed_call":
        raw[0]["output"][0]["status"] = "failed"
    else:
        raw[0]["output"][1]["content"][0]["annotations"] = []
    agent.model_runner = _Runner(_empty_output(name, retained_web_urls=[url]), raw)
    bundle = await agent.run(input_data)
    assert not bundle.evidence
    assert any(
        item["tool_name"] == "web_search"
        and item["status"] == ("failed" if failure == "failed_call" else "completed")
        for item in agent.workbench_activity
    )
    assert getattr(bundle, "evidence_gaps", ()) or getattr(
        bundle, "transcript_gap_notes", ()
    )


@pytest.mark.asyncio
async def test_selected_hosted_url_must_be_exact_sdk_citation() -> None:
    name, input_type, scenario, factory, url, _ = CASES[0]
    input_data = input_type.model_validate(scenario().input)
    agent = factory(_settings())
    agent.citation_store = HostedCitationStore(
        run_id=input_data.run_id,
        session_factory=object(),  # type: ignore[arg-type]
    )
    agent.model_runner = _Runner(
        _empty_output(name, retained_web_urls=["https://www.youtube.com/watch"]),
        _response(url),
    )
    bundle = await agent.run(input_data)
    assert not bundle.evidence
    assert any(
        item["tool_name"] == "web_search_citation"
        and item["status"] == "rejected_invalid_selection"
        for item in agent.workbench_activity
    )
