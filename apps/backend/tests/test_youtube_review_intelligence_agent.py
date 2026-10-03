from dataclasses import dataclass
from hashlib import sha256
from typing import Any

import pytest
from agents import Agent, RunConfig

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
from app.schemas.confidence import Confidence
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
                    quote="Invented claim" if self.invented_quote else segment["text"][:700],
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
        "app.agents.context_management.Runner.run", fake_run
    )
    tools = YouTubeReviewTools(
        _input(), FakeVideoSearchProvider(), _WorkbenchYouTubeTranscriptProvider()
    )
    result = await OpenAIAgentsSDKYouTubeReviewModelRunner().run(
        Agent(name="YouTubeReviewIntelligenceAgent", instructions="test"),
        "fixture",
        run_config=RunConfig(tracing_disabled=True),
        max_turns=4,
        tools=tools,
    )
    assert result is not None
    assert called == [4]


class _SingleLongTranscriptProvider(_WorkbenchYouTubeTranscriptProvider):
    async def fetch_transcript(self, video, options=None):
        result = await super().fetch_transcript(video, options)
        segment = result.segments[0].model_copy(update={
            "text": "Monitor setup. " * 150
            + "Concern: the Fixture Monitor stand wobbles. This is sponsored with affiliate links.",
        })
        return result.model_copy(update={"segments": (segment,)})


@pytest.mark.asyncio
async def test_single_caption_segment_pages_to_its_exact_late_caveat():
    tools = YouTubeReviewTools(
        _input(), FakeVideoSearchProvider(), _SingleLongTranscriptProvider()
    )
    video_id = tools.bundle.videos[0].video_id
    first = await tools.transcript(video_id)
    assert first["text_truncated"] is True
    assert first["next_segment"] == 0
    assert first["next_start_char"] == 1000
    pages = [first]
    while pages[-1]["next_segment"] is not None:
        previous = pages[-1]
        pages.append(await tools.transcript(
            video_id,
            start_segment=previous["next_segment"],
            start_char=previous["next_start_char"],
        ))
    canonical = tools.bundle.transcript_segments[0]
    assert "".join(page["segments"][0]["text"] for page in pages) == canonical.text
    assert "Concern: the Fixture Monitor stand wobbles." in pages[-1]["segments"][0]["text"]
    for page in pages:
        segment = page["segments"][0]
        assert segment["segment_id"] == str(canonical.segment_id)
        assert segment["start_seconds"] == 15
        assert segment["end_seconds"] == 26
        assert segment["text"] == canonical.text[segment["start_char"]:segment["end_char"]]
        assert segment["total_characters"] == len(canonical.text)
        assert segment["content_sha256"] == sha256(canonical.text.encode()).hexdigest()
    assert pages[-1]["next_start_char"] is None


@pytest.mark.asyncio
async def test_caption_focus_can_advance_past_repeated_terms():
    tools = YouTubeReviewTools(
        _input(), FakeVideoSearchProvider(), _SingleLongTranscriptProvider()
    )
    video_id = tools.bundle.videos[0].video_id
    first = await tools.transcript(video_id, focus="Monitor")
    later = await tools.transcript(video_id, focus="Monitor", start_char=2200)
    assert first["segments"][0]["start_char"] == 0
    assert later["status"] == "ok"
    assert later["segments"][0]["start_char"] >= 2200
    assert "stand wobbles" in later["segments"][0]["text"]


@pytest.mark.asyncio
async def test_canonical_caption_disclosures_survive_model_false_flags():
    class FalseDisclosureRunner(_SelectingRunner):
        async def run(self, *args, **kwargs):
            result = await super().run(*args, **kwargs)
            result.final_output.selected_videos = tuple(
                selected.model_copy(update={
                    "sponsorship_disclosed": False,
                    "affiliate_links_disclosed": False,
                }) for selected in result.final_output.selected_videos
            )
            return result

    agent = YouTubeReviewIntelligenceAgent(
        settings=Settings(_env_file=None),
        video_search_provider=FakeVideoSearchProvider(),
        transcript_provider=_SingleLongTranscriptProvider(),
        model_runner=FalseDisclosureRunner(),
    )
    input_data = _input()
    snapshot = input_data.source_snapshots[0]
    input_data = input_data.model_copy(update={"source_snapshots": (
        snapshot.model_copy(update={"video": snapshot.video.model_copy(update={
            "description": "Fixture Monitor review.",
            "affiliate_bias_risk": Confidence(
                score=0.91, level="high", rationale="Strong pre-existing bias caution."
            ),
            "bias_notes": "Strong pre-existing bias caution.",
        })}),
    )})
    bundle = await agent.run(input_data)
    assert bundle.evidence[0].metadata_only is False
    assert bundle.videos[0].sponsorship_disclosed is True
    assert bundle.videos[0].affiliate_links_disclosed is True
    assert bundle.evidence[0].sponsorship_disclosed is True
    assert bundle.evidence[0].affiliate_links_disclosed is True
    assert bundle.evidence[0].affiliate_bias_risk.score == 0.91
    assert bundle.videos[0].bias_notes == "Strong pre-existing bias caution."


@pytest.mark.asyncio
async def test_observed_late_caption_quote_is_accepted_with_original_timestamp():
    class PagingRunner(_SelectingRunner):
        async def run(self, *args, **kwargs):
            result = await super().run(*args, **kwargs)
            tools = kwargs["tools"]
            video_id = result.final_output.selected_videos[0].video_id
            page = await tools.transcript(video_id)
            while page["next_segment"] is not None:
                page = await tools.transcript(
                    video_id, start_segment=page["next_segment"],
                    start_char=page["next_start_char"],
                )
            text = page["segments"][0]["text"]
            quote = text[text.index("Concern:"):]
            result.final_output.claims = (
                result.final_output.claims[0].model_copy(update={
                    "quote": quote, "signal_kind": "concern",
                }),
            )
            return result

    agent = YouTubeReviewIntelligenceAgent(
        settings=Settings(_env_file=None),
        video_search_provider=FakeVideoSearchProvider(),
        transcript_provider=_SingleLongTranscriptProvider(),
        model_runner=PagingRunner(),
    )
    bundle = await agent.run(_input())
    assert bundle.evidence[0].metadata_only is False
    assert bundle.evidence[0].claim == (
        "Concern: the Fixture Monitor stand wobbles. This is sponsored with affiliate links."
    )
    assert bundle.evidence[0].timestamp_references[0].start_seconds == 15
    assert bundle.evidence[0].timestamp_references[0].end_seconds == 26


@pytest.mark.asyncio
async def test_character_paging_keeps_span_read_quota_and_rejects_invalid_offsets():
    tools = YouTubeReviewTools(
        _input(), FakeVideoSearchProvider(), _SingleLongTranscriptProvider()
    )
    video_id = tools.bundle.videos[0].video_id
    assert (await tools.transcript(video_id, start_char=-1))["status"] == "invalid_request"
    assert (await tools.transcript(video_id, start_char=5001))["status"] == "invalid_request"
    page = await tools.transcript(video_id, start_char=1000)
    assert page["segments"][0]["start_char"] == 1000
    for _ in range(10):
        assert (await tools.transcript(video_id))["status"] == "ok"
    assert (await tools.transcript(video_id, start_char=2000))["status"] == "budget_exhausted"

@pytest.mark.asyncio
async def test_exact_late_caption_quote_requires_an_observed_span():
    class LongTranscriptProvider(_WorkbenchYouTubeTranscriptProvider):
        async def fetch_transcript(self, video, options=None):
            result = await super().fetch_transcript(video, options)
            return result.model_copy(update={"segments": tuple(segment.model_copy(update={
                "text": "Unrelated setup. " * 130 + segment.text,
            }) for segment in result.segments)})

    class UnreadQuoteRunner(_SelectingRunner):
        async def run(self, *args, **kwargs):
            result = await super().run(*args, **kwargs)
            original = kwargs["tools"].bundle.transcript_segments[0]
            quote = original.text.split("Unrelated setup. " * 130)[-1]
            result.final_output.claims = (result.final_output.claims[0].model_copy(update={"quote": quote}),)
            return result

    agent = YouTubeReviewIntelligenceAgent(settings=Settings(_env_file=None),
        video_search_provider=FakeVideoSearchProvider(), transcript_provider=LongTranscriptProvider(),
        model_runner=UnreadQuoteRunner())
    result = await agent.run(_input())
    assert all(item.metadata_only for item in result.evidence)
    assert "Model interpretation failed" in " ".join(result.transcript_gap_notes)
