"""Local source lifecycle/routing contracts, not live caption evidence."""

import json
from pathlib import Path

import pytest

from app.agents.catalog import DEFAULT_AGENT_CATALOG, ApprovedSDKTool
from app.agents.live_source_intelligence_manager import SourceIntelligenceManagerAgent
from app.agents.youtube_review_tools import YouTubeReviewTools
from app.providers import FakeVideoSearchProvider
from app.providers.contracts import ProviderRunStatus, TranscriptProviderResult
from app.schemas.search_sources import SourceIntelligenceCapability
from test_task222_source_sdk import _input
from test_task223_source_lifecycle import Captions


CASES = json.loads(
    (
        Path(__file__).parent / "fixtures/providers/task223_caption_outcomes.json"
    ).read_text()
)["cases"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES)
async def test_local_caption_provider_outcomes_keep_failure_distinct(case):
    class Provider(Captions):
        async def fetch_transcript(self, video, options=None):
            return TranscriptProviderResult(
                status=ProviderRunStatus.UNAVAILABLE,
                capabilities=self.capabilities,
                video=video,
                availability=case["availability"],
                failure_type=case.get("failure_type"),
                gap_notes=("Local provider outcome control.",),
            )

    tools = YouTubeReviewTools(_input(), FakeVideoSearchProvider(), Provider())
    result = await tools.transcript("ccMonitor01")
    assert result["status"] == case["expected_retrieval"]
    outcome = SourceIntelligenceManagerAgent._outcome(
        {},
        {SourceIntelligenceCapability.VIDEO_REVIEW},
        [],
        {SourceIntelligenceCapability.VIDEO_REVIEW: tools},
    )
    assert outcome.status == case["expected_consultation"]
    assert outcome.failure_type == case.get("failure_type")
    assert not tools.bundle.transcript_segments


def test_local_catalog_declares_shared_outcomes_and_only_video_durable_reuse():
    names = (
        "SourceIntelligenceManagerAgent",
        "YouTubeReviewIntelligenceAgent",
        "RedditCommunityIntelligenceAgent",
        "AmazonProductIntelligenceAgent",
        "IKEAStoreIntelligenceAgent",
    )
    for name in names:
        entry = DEFAULT_AGENT_CATALOG.require(name)
        assert entry.source_lifecycle_contract == "SourceConsultationOutcome"
        assert entry.durable_video_progress == (name in names[:2])
    assert (
        ApprovedSDKTool.READ_VIDEO_TRANSCRIPT
        in DEFAULT_AGENT_CATALOG.require(
            "YouTubeReviewIntelligenceAgent"
        ).approved_sdk_tools
    )
    assert (
        DEFAULT_AGENT_CATALOG.require("SmartphoneSpecialistAgent").parent_agent_name
        == "TechnologyDomainAnalystAgent"
    )
    assert (
        DEFAULT_AGENT_CATALOG.require("GenericProductAnalystAgent").agent_name
        == "GenericProductAnalystAgent"
    )


def test_local_lifecycle_eval_references_exist():
    path = (
        Path(__file__).parents[1] / "app/evals/fixtures/task223_source_lifecycle.json"
    )
    for case in json.loads(path.read_text())["cases"]:
        name, function = case["control"].split("::")
        assert f"def {function}(" in (Path(__file__).parent / name).read_text()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "YtDlpCommandTimeout",
        "YtDlpCommandOutputLimit",
        "YtDlpCommandStorageLimit",
        "OSError",
    ],
)
async def test_local_ytdlp_failure_class_survives_provider_without_raw_stderr(failure):
    import sys
    import app.providers.youtube_transcript as transcripts
    from test_youtube_transcript_provider import _video

    error_class = OSError if failure == "OSError" else getattr(transcripts, failure)

    class Runner:
        async def run(self, *args, **kwargs):
            raise error_class("secret stderr must not be persisted")

    provider = transcripts.YtDlpTranscriptProvider(
        runner=Runner(),
        check_runtime_dependencies=False,
        deno_executable=sys.executable,
    )
    result = await provider.fetch_transcript(_video())
    assert result.failure_type == failure
    assert result.availability.value == "not_checked"
    assert not result.segments
    assert "secret stderr" not in result.model_dump_json()
