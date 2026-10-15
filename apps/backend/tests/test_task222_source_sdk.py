from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
from typing import Any

import pytest
from agents import Agent, ModelSettings, RunConfig, handoff
from agents.items import HandoffOutputItem, ModelResponse
from agents.models.interface import Model, ModelProvider
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

from app.agents.context_management import (
    BoundedRunner,
    ContextBudget,
    ContextBudgetExceeded,
    context_scope,
    managed_owner_context,
)
import app.agents.context_management as context_management
from app.agents.contracts import YouTubeReviewIntelligenceAgentInput
from app.agents.live_source_intelligence_manager import (
    SourceIntelligenceManagerAgent,
    SourceManagerInput,
)
from app.agents.live_youtube_review_intelligence import (
    YouTubeReviewIntelligenceAgent,
)
from app.agents.live_general_shopping import GeneralModelOutput
from app.agents.workbench import (
    _WorkbenchYouTubeTranscriptProvider,
    _scenario_youtube_monitor_review_transcript,
)
from app.agents.youtube_review_intelligence_service import _bundle_from_video_snapshots
from app.agents.research_history import ResearchHistory
from app.core.settings import Settings
from app.providers import FakeTranscriptProvider, FakeVideoSearchProvider
from app.schemas.search_sources import TranscriptAvailability
from app.schemas.search_sources import SourceIntelligenceCapability


def _message(value: dict[str, Any]) -> list[ResponseOutputMessage]:
    return [
        ResponseOutputMessage(
            id="local-task222-answer",
            type="message",
            role="assistant",
            status="completed",
            content=[
                ResponseOutputText(
                    type="output_text", annotations=[], text=json.dumps(value)
                )
            ],
        )
    ]


def _call(name: str, arguments: dict[str, Any]) -> list[ResponseFunctionToolCall]:
    return [
        ResponseFunctionToolCall(
            type="function_call",
            call_id=f"local-{name}",
            name=name,
            arguments=json.dumps(arguments),
        )
    ]


def _results(items: list[Any]) -> list[dict[str, Any]]:
    return [
        json.loads(item["output"])
        for item in items
        if item.get("type") == "function_call_output"
    ]


class _LocalModel(Model):
    def __init__(self, steps: list[Any], charges: list[int] | None = None):
        self.steps = list(steps)
        self.charges = list(charges or [1000] * len(steps))
        self.calls: list[dict[str, Any]] = []

    async def get_response(
        self,
        system_instructions,
        input,
        model_settings,
        tools,
        output_schema,
        handoffs,
        tracing,
        **kwargs,
    ):
        self.calls.append(
            {
                "instructions": system_instructions,
                "input": input,
                "tools": [tool.name for tool in tools],
                "output_tokens": model_settings.max_tokens,
            }
        )
        assert self.steps, "The offline script forbids additional model calls."
        step = self.steps.pop(0)
        output = step(input) if callable(step) else step
        charge = self.charges.pop(0)
        return ModelResponse(
            output=output,
            response_id=None,
            usage=Usage(
                requests=1,
                input_tokens=charge - 100,
                output_tokens=100,
                total_tokens=charge,
            ),
        )

    async def stream_response(self, *args, **kwargs):
        raise AssertionError("The offline control forbids streaming.")
        yield


class _LocalProvider(ModelProvider):
    def __init__(self, manager: _LocalModel, source: _LocalModel):
        self.models = {"gpt-6.1-sol": manager, "gpt-6-luna": source}

    def get_model(self, model_name):
        return self.models[model_name]


class _BoundedLocalRunner:
    def __init__(self, provider: _LocalProvider):
        self.provider = provider

    async def run(self, agent, model_input, *, run_config, max_turns, **kwargs):
        return await BoundedRunner.run(
            agent,
            model_input,
            run_config=replace(
                run_config,
                model_provider=self.provider,
                tracing_disabled=True,
            ),
            max_turns=max_turns,
        )


@dataclass
class _LocalVideoProvider:
    provider: FakeVideoSearchProvider
    calls: list[str] = field(default_factory=list)

    @property
    def capabilities(self):
        return self.provider.capabilities

    async def search_videos(self, query, options=None):
        self.calls.append(query)
        return await self.provider.search_videos(query, options)


@dataclass
class _LocalTranscriptProvider:
    unavailable: bool = False
    calls: list[str] = field(default_factory=list)

    @property
    def capabilities(self):
        return _WorkbenchYouTubeTranscriptProvider().capabilities

    async def fetch_transcript(self, video, options=None):
        self.calls.append(video.video_id)
        provider = (
            FakeTranscriptProvider(availability=TranscriptAvailability.UNAVAILABLE)
            if self.unavailable
            else _WorkbenchYouTubeTranscriptProvider()
        )
        return await provider.fetch_transcript(video, options)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        openai_agent_tracing_enabled=False,
        openai_run_profiles={
            "fast": {"model": "gpt-6-luna", "max_turns": 9},
            "strong": {"model": "gpt-6.1-sol", "max_turns": 15},
        },
    )


def _input() -> YouTubeReviewIntelligenceAgentInput:
    return YouTubeReviewIntelligenceAgentInput.model_validate(
        _scenario_youtube_monitor_review_transcript().input
    )


def _manager_input(payload) -> SourceManagerInput:
    return SourceManagerInput(
        run_id=payload.run_id,
        brief=payload.brief,
        products=payload.products,
        listings=payload.listings,
        source_snapshots=payload.source_snapshots,
        query_hints=payload.video_queries,
        region_code="PH",
        allowed_capabilities=(SourceIntelligenceCapability.VIDEO_REVIEW,),
    )


def _save_control(name: str, report: dict[str, Any]) -> None:
    directory = os.getenv("CARTCART_TASK222_ARTIFACT_DIR")
    if directory:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{name}.json").write_text(
            json.dumps(
                {"control": "explicitly local SDK/source providers", **report}, indent=2
            ),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", [False, True])
async def test_nested_source_sdk_keeps_native_reads_and_validates_local_speech(
    unavailable: bool,
) -> None:
    payload = _input()
    video_provider = _LocalVideoProvider(
        FakeVideoSearchProvider(
            bundle=_bundle_from_video_snapshots(payload.source_snapshots),
        )
    )
    transcripts = _LocalTranscriptProvider(unavailable=unavailable)

    def source_output(items):
        metadata = next(result for result in _results(items) if "video" in result)
        transcript = next(result for result in _results(items) if "segments" in result)
        video = metadata["video"]
        claims = []
        if not unavailable:
            segment = transcript["segments"][0]
            assert segment["text"] == (
                "Pro: the Fixture Monitor has sharp text and strong brightness for coding."
            )
            assert segment["start_seconds"] == 15.0
            assert segment["end_seconds"] == 26.0
            claims = [
                {
                    "video_id": video["video_id"],
                    "source_id": metadata["source_id"],
                    "product_id": str(payload.products[0].product_id),
                    "transcript_segment_id": segment["segment_id"],
                    "quote": segment["text"],
                    "signal_kind": "pro",
                    "interpretation": "The local reviewer describes sharp text for coding.",
                }
            ]
        else:
            assert transcript["status"] == "unavailable"
            assert transcript["availability"] == "unavailable"
        return _message(
            {
                "selected_videos": [
                    {
                        "video_id": video["video_id"],
                        "source_id": metadata["source_id"],
                        "relevance_reason": "This labeled local video reviews the supplied monitor.",
                        "sponsorship_disclosed": True,
                        "affiliate_links_disclosed": True,
                    }
                ],
                "claims": claims,
                "evidence_gaps": ["Local provider reports captions unavailable."]
                if unavailable
                else [],
                "retained_web_urls": [],
            }
        )

    def manager_output(items):
        returned = next(result for result in _results(items) if "bundle" in result)
        bundle = returned["bundle"]
        assert bundle["videos"][0]["video_id"] == "ccMonitor01"
        assert bundle["source_references"][0]["source_id"]
        if not unavailable:
            assert "sharp text" in json.dumps(bundle)
            assert (
                bundle["evidence"][0]["timestamp_references"][0]["start_seconds"]
                == 15.0
            )
        return _message(
            {
                "summary": "Validated explicitly local review evidence.",
                "skipped_sources": [],
            }
        )

    manager_model = _LocalModel(
        [
            _call(
                "consult_video_review", {"input": "Interpret the local monitor review."}
            ),
            manager_output,
        ],
        [1082, 1000],
    )
    source_model = _LocalModel(
        [
            _call("search_videos", {"query": "local monitor review"}),
            _call("read_video_metadata", {"video_id": "ccMonitor01"}),
            _call("read_video_transcript", {"video_id": "ccMonitor01"}),
            source_output,
        ],
        [16577, 1000, 1000, 1000],
    )
    budget = ContextBudget()
    manager = SourceIntelligenceManagerAgent(
        settings=_settings(),
        video_provider=video_provider,
        transcript_provider=transcripts,
        model_runner=_BoundedLocalRunner(_LocalProvider(manager_model, source_model)),
    )
    with context_scope(budget):
        result = await manager.run(_manager_input(payload))
    assert not manager_model.steps and not source_model.steps
    assert video_provider.calls == ["local monitor review"]
    assert transcripts.calls == ["ccMonitor01"]
    assert "read_video_metadata" in source_model.calls[1]["tools"]
    assert "read_video_transcript" in source_model.calls[2]["tools"]
    assert source_model.calls[0]["output_tokens"] == 4000
    assert manager_model.calls[0]["output_tokens"] == 2000
    assert budget.spent == 21659
    assert budget.reserved == 0
    source_events = [
        event
        for event in budget.events
        if event["input"]["agent"] == "YouTubeReviewIntelligenceAgent"
    ]
    metadata_event = source_events[1]["output"]
    source_scope = next(
        scope for scope in metadata_event["scopes"] if scope["scope"] == "source"
    )
    assert source_scope["spent_tokens"] == 17659
    assert source_scope["remaining_tokens"] >= 22341
    assert metadata_event["phase"] == "research"
    assert metadata_event["completion_purpose"] == "source"
    delegated = [
        item for item in result.activity if item["tool_name"] == "agent_as_tool"
    ]
    assert len(delegated) == 1
    assert delegated[0]["status"] == "validated"
    assert delegated[0]["input"]["agent"] == "YouTubeReviewIntelligenceAgent"
    bundle = result.video_bundles[0]
    checkpoint = None
    if unavailable:
        assert bundle.transcript_segments == ()
        assert (
            bundle.videos[0].transcript_availability
            == TranscriptAvailability.UNAVAILABLE
        )
        assert "unavailable" in " ".join(bundle.transcript_gap_notes).lower()
        assert all(item.metadata_only for item in bundle.evidence)
    else:
        assert bundle.transcript_segments[0].text == (
            "Pro: the Fixture Monitor has sharp text and strong brightness for coding."
        )
        evidence = bundle.evidence[0]
        assert evidence.transcript_segment_ids == (
            bundle.transcript_segments[0].segment_id,
        )
        assert evidence.timestamp_references[0].start_seconds == 15.0
        assert evidence.timestamp_references[0].end_seconds == 26.0
        assert evidence.target.product_id == payload.products[0].product_id
        assert evidence.source_id in {ref.source_id for ref in bundle.source_references}
        history = ResearchHistory()
        handle = history.archive(
            "task222_local_source_checkpoint",
            {
                "bundle": bundle.model_dump(mode="json"),
                "execution_metadata": "Repeated local diagnostics. " * 10000,
                "repeated_source_views": [bundle.videos[0].model_dump(mode="json")]
                * 30,
            },
        )
        checkpoint = history.checkpoint(handle, characters=3200)
        speech = next(
            record
            for record in checkpoint["source_records"]
            if record["segment_id"] == str(bundle.transcript_segments[0].segment_id)
        )
        assert speech["video_id"] == "ccMonitor01"
        assert speech["text"] == (
            "Pro: the Fixture Monitor has sharp text and strong brightness for coding."
        )
        assert speech["start_seconds"] == 15.0 and speech["end_seconds"] == 26.0
        reference = next(
            row
            for row in checkpoint["references"]
            if row.get("video_id") == "ccMonitor01" and row.get("source_id")
        )
        assert reference["source_id"] == str(evidence.source_id)
        assert any(
            row.get("source_id") == reference["source_id"]
            and row.get("url") == "https://www.youtube.com/watch?v=ccMonitor01"
            for row in checkpoint["references"]
        )
        assert len(json.dumps(checkpoint, ensure_ascii=False)) <= 3200
        assert checkpoint["omitted_material_unreviewed"] is True
    _save_control(
        "source-provider-unavailable" if unavailable else "source-sdk-speech",
        {
            "video_bundle": bundle.model_dump(mode="json"),
            "manager_transport": manager_model.calls,
            "source_transport": source_model.calls,
            "budget_events": budget.events,
            "spent_tokens": budget.spent,
            "reserved_tokens": budget.reserved,
            "checkpoint": checkpoint,
            "source_provider_calls": transcripts.calls,
            "manager_activity": result.activity,
        },
    )


@pytest.mark.asyncio
async def test_true_source_funding_exhaustion_never_attempts_caption_provider() -> None:
    payload = _input()
    video_provider = _LocalVideoProvider(FakeVideoSearchProvider())
    transcripts = _LocalTranscriptProvider()
    manager_model, source_model = _LocalModel([]), _LocalModel([])
    manager = SourceIntelligenceManagerAgent(
        settings=_settings(),
        video_provider=video_provider,
        transcript_provider=transcripts,
        model_runner=_BoundedLocalRunner(_LocalProvider(manager_model, source_model)),
    )
    budget = ContextBudget(spent=200_000)
    with context_scope(budget), pytest.raises(ContextBudgetExceeded):
        await manager.run(_manager_input(payload))
    assert manager_model.calls == [] and source_model.calls == []
    assert video_provider.calls == [] and transcripts.calls == []
    assert budget.spent == 200_000 and budget.reserved == 0
    _save_control(
        "source-technical-no-attempt",
        {
            "budget_events": budget.events,
            "spent_tokens": budget.spent,
            "reserved_tokens": budget.reserved,
            "source_provider_calls": transcripts.calls,
            "manager_transport": manager_model.calls,
            "source_transport": source_model.calls,
            "outcome": "retryable ContextBudgetExceeded",
        },
    )


@pytest.mark.asyncio
async def test_source_completion_under_pressure_gets_source_gap_guidance() -> None:
    payload = _input()
    transcripts = _LocalTranscriptProvider()
    video_provider = _LocalVideoProvider(FakeVideoSearchProvider())
    source_model = _LocalModel(
        [
            _message(
                {
                    "selected_videos": [],
                    "claims": [],
                    "retained_web_urls": [],
                    "evidence_gaps": [
                        "Caption retrieval was not attempted due to technical funding."
                    ],
                }
            )
        ]
    )
    specialist = YouTubeReviewIntelligenceAgent(
        settings=_settings(),
        video_search_provider=video_provider,
        transcript_provider=transcripts,
        model_runner=_BoundedLocalRunner(_LocalProvider(_LocalModel([]), source_model)),
    )
    budget = ContextBudget(spent=188_000)
    with context_scope(budget):
        bundle = await specialist.run(payload)
    assert len(source_model.calls) == 1
    call = source_model.calls[0]
    assert call["tools"] == []
    assert "Recommend by default" not in call["instructions"]
    assert "Further research is closed" in call["instructions"]
    assert "source" in call["instructions"].lower()
    assert transcripts.calls == [] and video_provider.calls == []
    assert any("not attempted" in note for note in bundle.transcript_gap_notes)
    assert bundle.evidence == ()
    assert budget.spent == 189_000 and budget.reserved == 0
    _save_control(
        "source-funded-completion",
        {
            "video_bundle": bundle.model_dump(mode="json"),
            "source_transport": source_model.calls,
            "budget_events": budget.events,
            "spent_tokens": budget.spent,
            "reserved_tokens": budget.reserved,
            "source_provider_calls": transcripts.calls,
        },
    )


@pytest.mark.asyncio
async def test_owner_handoffs_share_one_funded_scope_through_actual_sdk() -> None:
    captured = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "data/artifacts/task221/phone3-inspection.json"
        ).read_text()
    )
    brief = captured["brief"]
    local_facts = [
        {
            "name": "Local iPhone candidate",
            "source_id": "11111111-1111-4111-8111-111111111111",
            "benefit": "The local iPhone candidate has clear daylight photos and lasts a full day in the local review.",
            "tradeoff": "Its zoom detail trails the local Android candidate.",
        },
        {
            "name": "Local Android candidate",
            "source_id": "22222222-2222-4222-8222-222222222222",
            "benefit": "The local Android candidate has sharper zoom detail in the local review.",
            "tradeoff": "Its battery lasted less than a full day in the local review.",
        },
    ]
    observed_scopes = []

    def observe_scope():
        scopes = context_management._allowances.get()
        assert len(scopes) == 1
        observed_scopes.append(scopes[0])

    def authored_advice(items):
        observe_scope()
        supplied = json.loads(
            next(item["content"] for item in items if item.get("role") == "user")
        )
        assert supplied["brief"] == brief
        assert supplied["brief"]["region"]["region"]["country_code"] == "PH"
        assert (
            supplied["brief"]["preferences"][1]["text"] == "Budget is not a constraint."
        )
        primary, alternative = supplied["local_supplied_facts"]
        return _message(
            {
                "category": "smartphone",
                "candidates": [
                    {
                        "name": primary["name"],
                        "choice_group": "primary",
                        "source_ids": [primary["source_id"]],
                        "rationale": primary["benefit"],
                        "tradeoff": primary["tradeoff"],
                    },
                    {
                        "name": alternative["name"],
                        "choice_group": "runner_up",
                        "source_ids": [alternative["source_id"]],
                        "rationale": alternative["benefit"],
                        "tradeoff": alternative["tradeoff"],
                    },
                ],
                "selected_candidate_name": primary["name"],
                "rationale": primary["benefit"]
                + " "
                + primary["tradeoff"]
                + " Choose the local Android candidate if zoom matters more than battery life.",
            }
        )

    smartphone = Agent(
        name="SmartphoneSpecialistAgent",
        model="gpt-6-luna",
        instructions="Author useful phone advice from the supplied local review facts and buyer preferences. Preserve the source associations.",
        model_settings=ModelSettings(max_tokens=2000),
        output_type=GeneralModelOutput,
    )
    specialist_handoff = handoff(smartphone)
    technology = Agent(
        name="TechnologyDomainAnalystAgent",
        model="gpt-6.1-sol",
        instructions="Delegate this supplied smartphone brief to the smartphone owner.",
        model_settings=ModelSettings(max_tokens=2400),
        handoffs=[specialist_handoff],
        output_type=GeneralModelOutput,
    )
    technology_handoff = handoff(technology)
    general = Agent(
        name="GeneralShoppingAgent",
        model="gpt-6.1-sol",
        instructions="Delegate this supplied technology brief to its technology owner.",
        model_settings=ModelSettings(max_tokens=3334),
        handoffs=[technology_handoff],
        output_type=GeneralModelOutput,
    )

    def transfer(tool_name):
        def invoke(items):
            observe_scope()
            return _call(tool_name, {})

        return invoke

    strong = _LocalModel(
        [
            transfer(technology_handoff.tool_name),
            transfer(specialist_handoff.tool_name),
        ]
    )
    fast = _LocalModel([authored_advice])
    provider = _LocalProvider(strong, fast)
    root = ContextBudget()

    @managed_owner_context
    async def run_owner():
        return await BoundedRunner.run(
            general,
            json.dumps({"brief": brief, "local_supplied_facts": local_facts}),
            run_config=RunConfig(model_provider=provider, tracing_disabled=True),
            max_turns=3,
        )

    with context_scope(root):
        result = await run_owner()
    output = result.final_output
    assert isinstance(output, GeneralModelOutput)
    assert output.selected_candidate_name == "Local iPhone candidate"
    assert output.rationale == (
        "The local iPhone candidate has clear daylight photos and lasts a full day in the local review. "
        "Its zoom detail trails the local Android candidate. "
        "Choose the local Android candidate if zoom matters more than battery life."
    )
    assert output.candidates[0].rationale == local_facts[0]["benefit"]
    assert output.candidates[1].tradeoff == local_facts[1]["tradeoff"]
    assert result.last_agent.name == "SmartphoneSpecialistAgent"
    edges = [
        [item.source_agent.name, item.target_agent.name]
        for item in result.new_items
        if isinstance(item, HandoffOutputItem)
    ]
    assert edges == [
        ["GeneralShoppingAgent", "TechnologyDomainAnalystAgent"],
        ["TechnologyDomainAnalystAgent", "SmartphoneSpecialistAgent"],
    ]
    assert [event["input"]["agent"] for event in root.events] == [
        "GeneralShoppingAgent",
        "TechnologyDomainAnalystAgent",
        "SmartphoneSpecialistAgent",
    ]
    owner_snapshots = [
        next(scope for scope in event["output"]["scopes"] if scope["scope"] == "owner")
        for event in root.events
    ]
    assert [scope["spent_tokens"] for scope in owner_snapshots] == [0, 1000, 2000]
    assert [scope["funded_tokens"] for scope in owner_snapshots] == [
        120000,
        120000,
        120000,
    ]
    assert [event["output"]["active_output_limit"] for event in root.events] == [
        3334,
        2400,
        2000,
    ]
    assert len(observed_scopes) == 3
    assert all(scope is observed_scopes[0] for scope in observed_scopes)
    assert observed_scopes[0].spent == 3000 and observed_scopes[0].reserved == 0
    assert observed_scopes[0].completion_plans == {}
    assert root.spent == 3000 and root.reserved == 0
    assert not strong.steps and not fast.steps
    _save_control(
        "owner-handoff-sdk",
        {
            "captured_buyer_brief": brief,
            "local_supplied_facts": local_facts,
            "authored_advice": output.model_dump(mode="json"),
            "sdk_handoff_edges": edges,
            "strong_transport": strong.calls,
            "fast_transport": fast.calls,
            "budget_events": root.events,
            "spent_tokens": root.spent,
            "reserved_tokens": root.reserved,
            "owner_scope_spent_tokens": observed_scopes[0].spent,
            "owner_scope_reserved_tokens": observed_scopes[0].reserved,
            "same_owner_scope_across_all_calls": True,
        },
    )
