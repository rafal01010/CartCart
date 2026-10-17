import copy
import json
from hashlib import sha256
from pathlib import Path

import pytest

from app.agents.context_management import source_bundle_context
from app.agents.contracts import YouTubeReviewIntelligenceAgentInput
from app.agents.live_youtube_review_intelligence import (
    YouTubeReviewModelOutput,
    _validated_bundle,
)
from app.agents.owner_research import _bounded_owner_bundle
from app.agents.youtube_review_tools import YouTubeReviewTools


CHECKPOINT = Path(__file__).parent / "fixtures/providers/task224_saved_caption_checkpoint.json"
CAUTION = "Saved reviewer speech does not verify current product facts, prices or listings."


class NoProviderCalls:
    async def search_videos(self, *args, **kwargs):
        pytest.fail("Completed video discovery must not run again.")

    async def fetch_transcript(self, *args, **kwargs):
        pytest.fail("Completed captions must not be fetched again.")


def saved_caption_tools():
    saved = json.loads(CHECKPOINT.read_text())
    original = saved["input"]
    supplied = YouTubeReviewIntelligenceAgentInput(
        run_id=original["run_id"], brief=original["brief"],
        products=original["products"], listings=original["listings"],
        source_snapshots=original["source_snapshots"],
        video_queries=original["query_hints"],
    )
    tools = YouTubeReviewTools(supplied, NoProviderCalls(), NoProviderCalls())
    tools.restore_state(copy.deepcopy(saved["tool_states"]["video_review"]))
    return tools, saved


async def accepted_saved_speech_bundle():
    tools, saved = saved_caption_tools()
    video_id = "e9WGaciZgsc"
    metadata = await tools.metadata(video_id)
    segments = []
    for offset, keyword in ((36, "battery"), (59, "camera")):
        page = await tools.transcript(video_id, start_segment=offset, focus=keyword)
        assert page["status"] == "ok"
        segments.append(page["segments"][0])
    decision = YouTubeReviewModelOutput.model_validate({
        "selected_videos": [{
            "video_id": video_id, "source_id": metadata["source_id"],
            "relevance_reason": "Retained camera and battery review speech.",
        }],
        "claims": [{
            "video_id": video_id, "source_id": metadata["source_id"],
            "product_id": saved["input"]["products"][0]["product_id"],
            "transcript_segment_id": segment["segment_id"],
            "quote": segment["text"], "signal_kind": "other",
            "interpretation": "Retained exact reviewer speech for owner assessment.",
        } for segment in segments],
        "evidence_gaps": [CAUTION],
    })
    bundle = _validated_bundle(tools.input_data, tools, decision)
    return bundle, segments


@pytest.mark.asyncio
async def test_saved_literal_miss_preserves_captions_exact_request_and_consumed_counters():
    before = CHECKPOINT.read_bytes()
    tools, saved = saved_caption_tools()
    state = saved["tool_states"]["video_review"]
    assert state["span_reads"] == 6 and state["searched"] == 2
    assert len(state["transcripts_read"]) == 3
    assert len(state["transcripts"]["e9WGaciZgsc"]["transcript_segments"]) == 95
    assert len(state["transcripts"]["Dk_FdSDiNeI"]["transcript_segments"]) == 443
    result = await tools.transcript("e9WGaciZgsc", focus="camera battery")
    assert result["status"] == "focus_miss"
    assert result["availability"] == "available" and result["total_segments"] == 95
    assert result["next_segment"] == 0 and result["next_start_char"] == 0
    event = tools.workbench_activity[-1]
    assert event["input"] == {
        "video_id": "e9WGaciZgsc", "start_segment": 0,
        "start_char": 0, "focus": "camera battery",
    }
    assert event["status"] == "focus_miss" and event["output"]["segment_count"] == 0
    assert event["output"]["availability"] == "available"
    assert event["output"]["source_id"] == "ee69aaf2-48c2-4dd9-8b9d-275ee330c473"
    assert event["output"]["video_id"] == "e9WGaciZgsc"
    battery = await tools.transcript("e9WGaciZgsc", start_segment=36, focus="battery")
    camera = await tools.transcript("Dk_FdSDiNeI", start_segment=308, focus="camera")
    unfiltered = await tools.transcript("e9WGaciZgsc", start_segment=59)
    assert battery["status"] == camera["status"] == unfiltered["status"] == "ok"
    assert "battery" in battery["segments"][0]["text"]
    assert "camera" in camera["segments"][0]["text"]
    for page in (battery, camera, unfiltered):
        for segment in page["segments"]:
            assert segment["content_sha256"] == sha256(segment["text"].encode()).hexdigest()
    after = tools.dump_state()
    assert after["span_reads"] == 10
    for key in ("searched", "transcripts_read", "transcripts", "bundles", "retrievals"):
        assert after[key] == state[key]
    assert after["activity"][:len(state["activity"])] == state["activity"]
    assert CHECKPOINT.read_bytes() == before


@pytest.mark.asyncio
async def test_early_gap_is_technical_failure_with_read_activity_not_literal_miss():
    tools, _ = saved_caption_tools()
    response = await tools.transcript("WM9Vkls_8zI", focus="camera battery")
    assert response["status"] == "technical_failure"
    assert response["availability"] == "not_checked"
    assert response["diagnostic"]["provider_status"] == "unavailable"
    assert response["diagnostic"]["failure_code"] == "rate_limited"
    assert tools.workbench_activity[-1]["status"] == "technical_failure"
    assert tools.workbench_activity[-1]["input"]["focus"] == "camera battery"
    assert tools._span_reads == 7


@pytest.mark.asyncio
async def test_focus_cursor_keeps_original_request_in_success_and_all_early_outcomes():
    tools, _ = saved_caption_tools()
    response = await tools.transcript("e9WGaciZgsc", start_segment=30, focus="battery")
    assert response["start_segment"] == 33
    assert tools.workbench_activity[-1]["input"]["start_segment"] == 30
    assert tools.workbench_activity[-1]["input"]["focus"] == "battery"
    assert tools.workbench_activity[-1]["output"]["start_segment"] == 33
    for arguments, expected in (({"start_segment": -1}, "invalid_request"),
                                 ({"start_segment": 999}, "invalid_request")):
        result = await tools.transcript("e9WGaciZgsc", **arguments)
        assert result["status"] == expected
        assert tools.workbench_activity[-1]["status"] == expected
    tools._span_reads = 12
    assert (await tools.transcript("e9WGaciZgsc"))["status"] == "budget_exhausted"
    assert tools.workbench_activity[-1]["status"] == "budget_exhausted"
    assert tools._span_reads == 12


@pytest.mark.asyncio
async def test_saved_speech_validates_and_owner_context_retains_whole_units_and_cautions():
    bundle, exact = await accepted_saved_speech_bundle()
    projected = _bounded_owner_bundle(source_bundle_context(bundle), "offline-fixture", max_chars=9000)
    assert len([item for item in bundle.evidence if not item.metadata_only]) == 2
    assert CAUTION in json.dumps(projected)
    for expected in exact:
        received = next(s for s in projected["transcript_segments"]
                        if s["segment_id"] == expected["segment_id"])
        for key in ("text", "video_id", "source_id", "start_seconds", "end_seconds", "url", "content_sha256"):
            assert received[key] == expected[key]
        assert received["content_sha256"] == sha256(received["text"].encode()).hexdigest()


@pytest.mark.asyncio
async def test_oversized_invalid_focus_diagnostic_is_bounded_with_exact_fingerprint():
    tools, _ = saved_caption_tools()
    focus = "oversized literal " * 1000
    response = await tools.transcript("e9WGaciZgsc", focus=focus)
    assert response["status"] == "invalid_request"
    request = tools.workbench_activity[-1]["input"]
    assert request["focus"] == focus[:200]
    assert request["focus_characters"] == len(focus)
    assert request["focus_sha256"] == sha256(focus.encode()).hexdigest()
    assert request["focus_truncated"] is True
    assert tools._span_reads == 6


@pytest.mark.asyncio
async def test_raw_saved_captions_without_observed_speech_still_fail_claim_validation():
    bundle, segments = await accepted_saved_speech_bundle()
    tools, saved = saved_caption_tools()
    segment = segments[0]
    decision = YouTubeReviewModelOutput.model_validate({
        "selected_videos": [{
            "video_id": segment["video_id"], "source_id": segment["source_id"],
            "relevance_reason": "Local negative control.",
        }],
        "claims": [{
            "video_id": segment["video_id"], "source_id": segment["source_id"],
            "product_id": saved["input"]["products"][0]["product_id"],
            "transcript_segment_id": segment["segment_id"],
            "quote": segment["text"], "signal_kind": "other",
            "interpretation": "Local negative control.",
        }],
    })
    assert bundle.evidence and not tools.observed_spans
    with pytest.raises(ValueError, match="Claim quote is not present"):
        _validated_bundle(tools.input_data, tools, decision)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["provider_gap", "technical_failure", "cancelled"])
async def test_local_provider_boundaries_keep_gap_failure_and_cancelled_read_activity(outcome):
    import asyncio

    from test_task223_source_lifecycle import Captions

    class LocalProvider(Captions):
        async def fetch_transcript(self, video, options=None):
            if outcome == "technical_failure":
                raise RuntimeError("Local provider failure control")
            if outcome == "cancelled":
                raise asyncio.CancelledError()
            self.gap = True
            return await super().fetch_transcript(video, options)

    saved_tools, _ = saved_caption_tools()
    tools = YouTubeReviewTools(saved_tools.input_data, NoProviderCalls(), LocalProvider())
    tools._bundles = list(saved_tools._bundles)
    if outcome == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await tools.transcript("e9WGaciZgsc", focus="camera battery")
    else:
        response = await tools.transcript("e9WGaciZgsc", focus="camera battery")
        assert response["status"] == outcome
        if outcome == "provider_gap":
            assert response["availability"] == "unavailable"
            assert response["segments"] == []
        else:
            assert response["diagnostic"]["error_type"] == "RuntimeError"
    event = tools.workbench_activity[-1]
    assert event["tool_name"] == "read_video_transcript"
    assert event["status"] == outcome
    assert event["input"]["focus"] == "camera battery"
    assert event["output"]["source_id"] == "ee69aaf2-48c2-4dd9-8b9d-275ee330c473"
    assert tools._span_reads == 1 and tools._transcripts_read == {"e9WGaciZgsc"}
