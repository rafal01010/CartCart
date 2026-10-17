"""Local SDK/tool controls. These fixtures are never public-caption evidence."""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from agents import Runner
from agents.tool_context import ToolContext

from app.agents.contracts import YouTubeReviewIntelligenceAgentInput
from app.agents.live_source_intelligence_manager import (
    SourceIntelligenceManagerAgent,
    SourceManagerDecision,
    SourceManagerInput,
)
from app.agents.live_youtube_review_intelligence import (
    InterpretedVideoClaim,
    SelectedVideo,
    YouTubeReviewModelOutput,
)
from app.agents.source_consultation import safe_failure
from app.agents.workbench import (
    _WorkbenchYouTubeTranscriptProvider,
    _scenario_youtube_monitor_review_transcript,
)
from app.core.settings import Settings
from app.providers import FakeVideoSearchProvider
from app.providers.contracts import ProviderRunStatus, TranscriptProviderResult
from app.schemas.search_sources import (
    SourceIntelligenceCapability,
    TranscriptAvailability,
)


async def invoke(tool, payload):
    arguments = json.dumps(payload)
    return json.loads(
        await tool.on_invoke_tool(
            ToolContext(
                context=None,
                tool_name=tool.name,
                tool_call_id="local-task223",
                tool_arguments=arguments,
            ),
            arguments,
        )
    )


def request():
    supplied = YouTubeReviewIntelligenceAgentInput.model_validate(
        _scenario_youtube_monitor_review_transcript().input
    )
    return SourceManagerInput(
        run_id=supplied.run_id,
        brief=supplied.brief,
        products=supplied.products,
        listings=supplied.listings,
        source_snapshots=supplied.source_snapshots,
        query_hints=supplied.video_queries,
        region_code="PH",
        allowed_capabilities=(SourceIntelligenceCapability.VIDEO_REVIEW,),
        reuse_key="local-task223-same-consultation",
    )


class Parent:
    calls = 0
    fail_after_tool = False

    async def run(self, agent, model_input, **kwargs):
        self.calls += 1
        await invoke(
            next(tool for tool in agent.tools if tool.name == "consult_video_review"),
            {"input": "Inspect this local review."},
        )
        if self.fail_after_tool:
            raise RuntimeError("Bearer secret-token must never be saved")
        return SimpleNamespace(
            final_output=SourceManagerDecision(summary="Local source control finished.")
        )


class Captions(_WorkbenchYouTubeTranscriptProvider):
    calls = 0
    gap = False

    async def fetch_transcript(self, video, options=None):
        self.calls += 1
        if self.gap:
            return TranscriptProviderResult(
                status=ProviderRunStatus.SUCCEEDED,
                capabilities=self.capabilities,
                video=video,
                availability=TranscriptAvailability.UNAVAILABLE,
                gap_notes=("Local fixture declares no permitted captions.",),
            )
        return await super().fetch_transcript(video, options)


def nested_script(*, fail=False, gap=False, cancel=False):
    async def run(*, starting_agent, input, **kwargs):
        context = json.loads(input)
        tools = {tool.name: tool for tool in starting_agent.tools}
        video_id = context["supplied_videos"][0]["video_id"]
        metadata = await invoke(tools["read_video_metadata"], {"video_id": video_id})
        transcript = await invoke(
            tools["read_video_transcript"], {"video_id": video_id}
        )
        if cancel:
            raise asyncio.CancelledError()
        if fail:
            raise RuntimeError("Bearer secret-token must never be saved")
        claims = (
            ()
            if gap
            else (
                InterpretedVideoClaim(
                    video_id=video_id,
                    source_id=metadata["source_id"],
                    product_id=context["products"][0]["product_id"],
                    transcript_segment_id=transcript["segments"][0]["segment_id"],
                    quote=transcript["segments"][0]["text"],
                    signal_kind="pro",
                    interpretation="Local fixture reviewer reports readable text.",
                ),
            )
        )
        return SimpleNamespace(
            final_output=YouTubeReviewModelOutput(
                selected_videos=(
                    SelectedVideo(
                        video_id=video_id,
                        source_id=metadata["source_id"],
                        relevance_reason="Local monitor identity matches.",
                    ),
                ),
                claims=claims,
            )
        )

    return run


def manager(tmp_path, parent, captions):
    return SourceIntelligenceManagerAgent(
        settings=Settings(_env_file=None, artifact_dir=tmp_path),
        model_runner=parent,
        video_provider=FakeVideoSearchProvider(),
        transcript_provider=captions,
    )


@pytest.mark.asyncio
async def test_local_failed_sdk_keeps_captions_and_resumes_without_fetch(
    monkeypatch, tmp_path
):
    parent, captions, data = Parent(), Captions(), request()
    monkeypatch.setattr(Runner, "run", nested_script(fail=True))
    failed = await manager(tmp_path, parent, captions).run(data)
    assert failed.outcome.status == "technical_failure"
    assert failed.outcome.failure_type == "RuntimeError"
    assert failed.video_bundles[0].transcript_segments[0].text.startswith("Pro:")
    assert not any(not item.metadata_only for item in failed.video_bundles[0].evidence)
    checkpoint = next(tmp_path.rglob("*.json"))
    assert "secret-token" not in checkpoint.read_text()
    saved = json.loads(checkpoint.read_text())
    assert saved["attempt_usage"][-1]["finalized"] is True
    assert saved["attempt_usage"][-1]["unknown_in_flight_possible"] is False
    state = saved["tool_states"]["video_review"]
    assert state["transcripts_read"]
    assert state["retrievals"][state["transcripts_read"][0]]["status"] == "completed"
    assert captions.calls == 1

    monkeypatch.setattr(Runner, "run", nested_script())
    restarted = manager(tmp_path, parent, captions)
    assert restarted.load_retry_input(data.run_id, data.reuse_key) == data
    assert restarted.pending_retry_input(data.run_id) == data
    service_manager = SourceIntelligenceManagerAgent(settings=restarted.settings)
    assert service_manager.pending_retry_input(data.run_id) == data
    incompatible = SourceIntelligenceManagerAgent(
        settings=restarted.settings.model_copy(
            update={"youtube_transcript_timeout_seconds": 29.0}
        )
    )
    with pytest.raises(ValueError, match="No compatible"):
        incompatible.load_retry_input(data.run_id, data.reuse_key)
    success = await restarted.run(data)
    assert success.outcome.status == "succeeded"
    assert success.video_bundles[0].evidence[0].transcript_segment_ids
    assert captions.calls == 1
    assert success.prior_usage and len(success.prior_usage) == 1
    replay = await manager(tmp_path, parent, captions).run(data)
    assert replay.outcome.status == "succeeded"
    assert parent.calls == 2
    assert replay.video_bundles == success.video_bundles
    assert (
        json.loads(checkpoint.read_text())["tool_states"]["video_review"]["span_reads"]
        == 2
    )


@pytest.mark.asyncio
async def test_local_partial_accepted_evidence_survives_parent_failure(
    monkeypatch, tmp_path
):
    parent, captions = Parent(), Captions()
    parent.fail_after_tool = True
    monkeypatch.setattr(Runner, "run", nested_script())
    data = request()
    result = await manager(tmp_path, parent, captions).run(data)
    assert result.outcome.status == "partial"
    assert result.outcome.failure_type == "RuntimeError"
    assert result.video_bundles[0].evidence[0].transcript_segment_ids
    assert "secret-token" not in next(tmp_path.rglob("*.json")).read_text()
    parent_calls = parent.calls
    resumed = manager(tmp_path, parent, captions)
    recovered = await resumed.run(data)
    assert recovered.outcome.status == "succeeded"
    assert recovered.video_bundles == result.video_bundles
    assert recovered.activity[0]["output"]["prior_attempt_diagnostics"][0]["error_type"] == "RuntimeError"
    assert json.loads(next(tmp_path.rglob("*.json")).read_text())["diagnostics"][0]["error_type"] == "RuntimeError"
    assert parent.calls == parent_calls
    assert captions.calls == 1
    with pytest.raises(ValueError, match="No compatible unfinished"):
        resumed.pending_retry_input(data.run_id)


@pytest.mark.asyncio
async def test_local_provider_gap_is_not_no_attempt_or_success(monkeypatch, tmp_path):
    captions = Captions()
    captions.gap = True
    data = request()
    monkeypatch.setattr(Runner, "run", nested_script(gap=True))
    result = await manager(tmp_path, Parent(), captions).run(data)
    assert result.outcome.status == "provider_gap"
    assert result.outcome.failure_type is None
    assert result.video_bundles[0].transcript_segments == ()
    assert all(item.metadata_only for item in result.video_bundles[0].evidence)
    resumed = await manager(tmp_path, Parent(), captions).run(data)
    assert resumed.outcome.status == "provider_gap"
    assert captions.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", tuple(SourceIntelligenceCapability))
async def test_local_empty_failure_never_becomes_success_and_keeps_diagnostic(
    tmp_path, capability
):
    class FailedParent:
        async def run(self, *args, **kwargs):
            raise ValueError("password=private-provider-value")

    data = replace(request(), allowed_capabilities=(capability,))
    result = await manager(tmp_path, FailedParent(), Captions()).run(data)
    assert result.outcome.status == "technical_failure"
    assert result.outcome.failure_type == "ValueError"
    assert not result.activity[0]["output"]["called_specialists"]
    if capability == SourceIntelligenceCapability.VIDEO_REVIEW:
        assert result.video_bundles[0].videos
        assert not result.video_bundles[0].transcript_segments
    assert "private-provider-value" not in next(tmp_path.rglob("*.json")).read_text()


@pytest.mark.asyncio
async def test_local_empty_completed_bundle_is_no_attempt(monkeypatch, tmp_path):
    async def no_retrieval(**kwargs):
        return SimpleNamespace(
            final_output=YouTubeReviewModelOutput(selected_videos=(), claims=())
        )

    monkeypatch.setattr(Runner, "run", no_retrieval)
    result = await manager(tmp_path, Parent(), Captions()).run(request())
    assert result.outcome.status == "no_attempt"
    assert result.video_bundles[0].videos == ()
    assert result.video_bundles[0].transcript_gap_notes


@pytest.mark.asyncio
async def test_local_search_failure_persists_type_then_successful_retry_is_clean(
    monkeypatch, tmp_path
):
    class FailedSearch(FakeVideoSearchProvider):
        async def search_videos(self, *args, **kwargs):
            raise OSError("secret-provider-url")

    async def search_then_empty(*, starting_agent, **kwargs):
        response = await invoke(
            next(tool for tool in starting_agent.tools if tool.name == "search_videos"),
            {"query": "local failing review search"},
        )
        assert response["status"] == "provider_error"
        return SimpleNamespace(
            final_output=YouTubeReviewModelOutput(selected_videos=(), claims=())
        )

    data, parent, captions = request(), Parent(), Captions()
    failed_manager = manager(tmp_path, parent, captions)
    failed_manager.video_provider = FailedSearch()
    monkeypatch.setattr(Runner, "run", search_then_empty)
    failed = await failed_manager.run(data)
    assert failed.outcome.status == "technical_failure"
    assert failed.outcome.failure_type == "OSError"
    saved_path = next(tmp_path.rglob("*.json"))
    saved = json.loads(saved_path.read_text())
    assert "secret-provider-url" not in saved_path.read_text()
    assert saved["tool_states"]["video_review"]["searched"] == 1
    assert failed_manager.pending_retry_input(data.run_id) == data

    monkeypatch.setattr(Runner, "run", nested_script())
    restarted = manager(tmp_path, parent, captions)
    success = await restarted.run(data)
    assert success.outcome.status == "succeeded"
    assert success.outcome.failure_type is None
    assert captions.calls == 1
    with pytest.raises(ValueError, match="No compatible unfinished"):
        restarted.pending_retry_input(data.run_id)


@pytest.mark.asyncio
async def test_local_unfinished_search_start_survives_restart_as_interrupted(
    monkeypatch, tmp_path
):
    in_flight = []

    class InterruptedSearch(FakeVideoSearchProvider):
        async def search_videos(self, *args, **kwargs):
            in_flight.append(json.loads(next(tmp_path.rglob("*.json")).read_text()))
            raise asyncio.CancelledError()

    async def search_then_empty(*, starting_agent, **kwargs):
        await invoke(
            next(tool for tool in starting_agent.tools if tool.name == "search_videos"),
            {"query": "local interrupted review search"},
        )
        return SimpleNamespace(
            final_output=YouTubeReviewModelOutput(selected_videos=(), claims=())
        )

    data = request()
    interrupted = manager(tmp_path, Parent(), Captions())
    interrupted.video_provider = InterruptedSearch()
    monkeypatch.setattr(Runner, "run", search_then_empty)
    with pytest.raises(asyncio.CancelledError):
        await interrupted.run(data)
    recorded = in_flight[0]["attempt_usage"][-1]
    assert recorded["finalized"] is False
    assert recorded["usage_complete"] is False
    assert recorded["unknown_in_flight_possible"] is True
    assert recorded["recorded_charge_is_lower_bound"] is True
    assert recorded["input_tokens"] is None and recorded["output_tokens"] is None
    path = next(tmp_path.rglob("*.json"))
    saved = json.loads(path.read_text())
    assert saved["outcome"]["status"] == "interrupted"
    assert saved["attempt_usage"][-1]["finalized"] is True
    assert saved["attempt_usage"][-1]["unknown_in_flight_possible"] is False
    events = saved["tool_states"]["video_review"]["activity"]
    assert [item["status"] for item in events] == ["started", "cancelled"]
    saved["tool_states"]["video_review"]["activity"] = events[:1]
    path.write_text(json.dumps(saved))

    async def empty(**kwargs):
        return SimpleNamespace(
            final_output=YouTubeReviewModelOutput(selected_videos=(), claims=())
        )

    monkeypatch.setattr(Runner, "run", empty)
    result = await manager(tmp_path, Parent(), Captions()).run(data)
    assert result.outcome.status == "interrupted"
    assert result.outcome.failure_type is None
    assert json.loads(path.read_text())["tool_states"]["video_review"]["searched"] == 1


@pytest.mark.asyncio
async def test_local_cancellation_checkpoint_is_durable(monkeypatch, tmp_path):
    monkeypatch.setattr(Runner, "run", nested_script(cancel=True))
    with pytest.raises(asyncio.CancelledError):
        await manager(tmp_path, Parent(), Captions()).run(request())
    saved = json.loads(next(tmp_path.rglob("*.json")).read_text())
    assert saved["outcome"]["status"] == "interrupted"
    assert saved["outcome"]["failure_type"] == "CancelledError"
    assert saved["tool_states"]["video_review"]["transcripts"]


def test_local_safe_failure_never_copies_arbitrary_exception_text():
    diagnostic = safe_failure(
        RuntimeError("api_key=do-not-store"), phase="caption_retrieval"
    )
    assert diagnostic == {
        "error_type": "RuntimeError",
        "phase": "caption_retrieval",
        "safe_detail": "Execution failed; provider availability was not established.",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("request_id", ["consult_product_id", "consult_evidence_id"])
async def test_local_id_bearing_owner_request_survives_checkpoint_restart(
    tmp_path, request_id
):
    class FailedParent:
        async def run(self, *args, **kwargs):
            raise RuntimeError("Local stopped source control")

    initial = request()
    owner_request = {
        "candidate_name": initial.products[0].name,
        "consult_product_id": None,
        "consult_evidence_id": None,
    }
    owner_request[request_id] = str(initial.products[0].product_id)
    data = replace(initial, owner_request=owner_request)
    await manager(tmp_path, FailedParent(), Captions()).run(data)
    restarted = manager(tmp_path, Parent(), Captions())
    restored = restarted.pending_retry_input(data.run_id)
    assert restored.owner_request == owner_request
    assert restored == data
