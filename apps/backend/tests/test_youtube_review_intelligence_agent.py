from dataclasses import dataclass
from typing import Any

import pytest
from agents import Agent

from app.agents.contracts import YouTubeReviewIntelligenceAgentInput
from app.agents.live_youtube_review_intelligence import (
    InterpretedVideoClaim,
    OpenAIAgentsSDKYouTubeReviewModelRunner,
    SelectedVideo,
    YouTubeReviewIntelligenceAgent,
    YouTubeReviewModelOutput,
)
from app.agents.workbench import (
    _WorkbenchYouTubeTranscriptProvider,
    _scenario_youtube_monitor_review_transcript,
)
from app.agents.youtube_review_tools import YouTubeReviewTools
from app.core.settings import Settings
from app.providers import FakeVideoSearchProvider
from app.schemas.ids import new_id


def _input() -> YouTubeReviewIntelligenceAgentInput:
    return YouTubeReviewIntelligenceAgentInput.model_validate(
        _scenario_youtube_monitor_review_transcript().input
    )


@dataclass
class _SelectingRunner:
    invented_quote: bool = False
    wrong_source_id: bool = False
    calls: int = 0

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: Any,
        max_turns: int,
        tools: YouTubeReviewTools,
    ) -> Any:
        del model_input, run_config, max_turns
        self.calls += 1
        assert agent.name == "YouTubeReviewIntelligenceAgent"
        assert {tool.name for tool in agent.tools} == {
            "search_videos",
            "read_video_metadata",
            "read_video_transcript",
        }
        video = tools.bundle.videos[0]
        metadata = await tools.metadata(video.video_id)
        transcript = await tools.transcript(video.video_id)
        segment = transcript["segments"][0]
        source_id = new_id() if self.wrong_source_id else metadata["source_id"]
        output = YouTubeReviewModelOutput(
            selected_videos=(
                SelectedVideo(
                    video_id=video.video_id,
                    source_id=source_id,
                    relevance_reason="Video reviews the supplied monitor.",
                    sponsorship_disclosed=True,
                    affiliate_links_disclosed=True,
                ),
            ),
            claims=(
                InterpretedVideoClaim(
                    video_id=video.video_id,
                    source_id=source_id,
                    product_id=tools.input_data.products[0].product_id,
                    transcript_segment_id=segment["segment_id"],
                    quote="Invented claim" if self.invented_quote else segment["text"],
                    signal_kind="pro",
                    interpretation="The reviewer reports sharp text for coding.",
                ),
            ),
        )
        return type("Result", (), {"final_output": output})()


@pytest.mark.asyncio
async def test_model_runner_selects_timestamped_product_evidence_through_approved_tools() -> (
    None
):
    runner = _SelectingRunner()
    agent = YouTubeReviewIntelligenceAgent(
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        video_search_provider=FakeVideoSearchProvider(),
        transcript_provider=_WorkbenchYouTubeTranscriptProvider(),
        model_runner=runner,
    )
    input_data = _input()
    bundle = await agent.run(input_data)
    assert runner.calls == 1
    assert bundle.evidence[0].signal_kind == "pro"
    assert (
        bundle.evidence[0].interpretation
        == "The reviewer reports sharp text for coding."
    )
    assert bundle.evidence[0].transcript_segment_ids
    assert bundle.evidence[0].timestamp_references[0].start_seconds == 15
    assert bundle.evidence[0].target.product_id == input_data.products[0].product_id
    assert {item["tool_name"] for item in agent.workbench_activity} >= {
        "read_video_metadata",
        "read_video_transcript",
        "openai_agents_structured_output",
    }


@pytest.mark.asyncio
async def test_invented_quote_degrades_to_metadata_only_without_fabrication() -> None:
    agent = YouTubeReviewIntelligenceAgent(
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        video_search_provider=FakeVideoSearchProvider(),
        transcript_provider=_WorkbenchYouTubeTranscriptProvider(),
        model_runner=_SelectingRunner(invented_quote=True),
    )
    bundle = await agent.run(_input())
    assert all(item.metadata_only for item in bundle.evidence)
    assert all("Invented claim" not in item.claim for item in bundle.evidence)
    assert "Model interpretation failed" in " ".join(bundle.transcript_gap_notes)


@pytest.mark.asyncio
async def test_wrong_source_id_cannot_enter_video_evidence_bundle() -> None:
    agent = YouTubeReviewIntelligenceAgent(
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        video_search_provider=FakeVideoSearchProvider(),
        transcript_provider=_WorkbenchYouTubeTranscriptProvider(),
        model_runner=_SelectingRunner(wrong_source_id=True),
    )
    bundle = await agent.run(_input())
    assert all(item.metadata_only for item in bundle.evidence)
    assert (
        agent.workbench_activity[-1]["status"]
        == "model_or_validation_failure_metadata_only"
    )


@pytest.mark.asyncio
async def test_video_tools_reject_unknown_ids_and_enforce_search_budget() -> None:
    tools = YouTubeReviewTools(
        input_data=_input(),
        video_provider=FakeVideoSearchProvider(),
        transcript_provider=_WorkbenchYouTubeTranscriptProvider(),
    )
    assert (await tools.metadata("not-in-input"))["status"] == "unknown_video"
    assert (await tools.transcript("not-in-input"))["status"] == "unknown_video"
    assert (await tools.search(""))["status"] == "invalid_query"
    assert (await tools.search("fixture monitor review"))["status"] == "succeeded"
    assert (await tools.search("fixture display review"))["status"] == "succeeded"
    assert (await tools.search("another review"))["status"] == "budget_exhausted"


@pytest.mark.asyncio
async def test_sdk_runner_invokes_openai_agents_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[int] = []

    async def fake_run(agent: Agent[Any], model_input: str, **kwargs: Any) -> object:
        assert agent.name == "YouTubeReviewIntelligenceAgent"
        assert model_input == "fixture"
        called.append(kwargs["max_turns"])
        return object()

    monkeypatch.setattr(
        "app.agents.live_youtube_review_intelligence.Runner.run", fake_run
    )
    tools = YouTubeReviewTools(
        _input(), FakeVideoSearchProvider(), _WorkbenchYouTubeTranscriptProvider()
    )
    result = await OpenAIAgentsSDKYouTubeReviewModelRunner().run(
        Agent(name="YouTubeReviewIntelligenceAgent", instructions="test"),
        "fixture",
        run_config=object(),
        max_turns=4,
        tools=tools,
    )
    assert result is not None
    assert called == [4]
