"""Model-running YouTube review specialist; provider I/O stays in typed tools."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from agents import Agent, ModelSettings, RunConfig, Runner
from pydantic import Field

from app.agents.contracts import YouTubeReviewIntelligenceAgentInput
from app.agents.openai_config import (
    OpenAIAgentConfigurationError,
    apply_openai_agent_run_profile,
    build_openai_agent_run_configuration,
)
from app.agents.research_tools import HostedCitationStore
from app.agents.source_hosted_search import (
    process_source_specialist_output,
    source_hosted_tool,
    source_tool_activity,
)
from app.agents.youtube_review_tools import YouTubeReviewTools
from app.core.settings import Settings
from app.providers import (
    TranscriptProvider,
    VideoSearchProvider,
    build_transcript_provider,
    build_video_search_provider,
)
from app.schemas.base import CartCartBaseModel
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import ProductId, SourceId
from app.schemas.search_sources import (
    ChannelSignal,
    EvidenceTarget,
    EvidenceTargetType,
    SourceQuality,
    SourceQualityLevel,
    VideoReviewEvidenceBundle,
)
from app.services.video_evidence_creation import (
    TranscriptBackedVideoClaim,
    VideoEvidenceCreator,
)


class SelectedVideo(CartCartBaseModel):
    video_id: str
    source_id: SourceId
    relevance_reason: str = Field(min_length=1, max_length=500)
    sponsorship_disclosed: bool = False
    affiliate_links_disclosed: bool = False


class InterpretedVideoClaim(CartCartBaseModel):
    video_id: str
    source_id: SourceId
    product_id: ProductId | None = None
    transcript_segment_id: SourceId
    quote: str = Field(min_length=1, max_length=700)
    signal_kind: str = Field(pattern=r"^(pro|con|concern|other)$")
    interpretation: str = Field(min_length=1, max_length=500)


class YouTubeReviewModelOutput(CartCartBaseModel):
    selected_videos: tuple[SelectedVideo, ...] = Field(max_length=3)
    claims: tuple[InterpretedVideoClaim, ...] = Field(max_length=18)
    evidence_gaps: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    retained_web_urls: tuple[str, ...] = Field(default_factory=tuple, max_length=8)


class YouTubeReviewModelRunner(Protocol):
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
        tools: YouTubeReviewTools,
    ) -> Any: ...


@dataclass
class OpenAIAgentsSDKYouTubeReviewModelRunner:
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
        tools: YouTubeReviewTools,
    ) -> Any:
        del tools
        return await Runner.run(
            agent, model_input, run_config=run_config, max_turns=max_turns
        )


@dataclass
class MockYouTubeReviewModelRunner:
    """Offline test runner that exercises the same tool boundary without an API call."""

    output: YouTubeReviewModelOutput | dict[str, Any] | None = None
    error: BaseException | None = None
    calls: int = 0

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
        tools: YouTubeReviewTools,
    ) -> Any:
        del agent, run_config, max_turns
        self.calls += 1
        if self.error:
            raise self.error
        if self.output is not None:
            return _MockResult(final_output=self.output)
        payload = json.loads(model_input)
        if not tools.bundle:
            await tools.search(
                (
                    payload["video_queries"]
                    or [payload["brief"]["original_query"] + " review"]
                )[0]
            )
        bundle = tools.bundle
        selections: list[SelectedVideo] = []
        claims: list[InterpretedVideoClaim] = []
        for video in bundle.videos[:2] if bundle else ():
            meta = await tools.metadata(video.video_id)
            if meta["status"] != "ok":
                continue
            transcript = await tools.transcript(video.video_id)
            text = " ".join(
                (
                    video.description or "",
                    *(s["text"] or "" for s in transcript.get("segments", [])),
                )
            )
            selections.append(
                SelectedVideo(
                    video_id=video.video_id,
                    source_id=SourceId(meta["source_id"]),
                    relevance_reason="Fixture review-video candidate for the supplied shopping brief.",
                    sponsorship_disclosed=bool(
                        re.search(
                            r"\b(sponsored|paid promotion|provided by|#ad)\b",
                            text,
                            re.I,
                        )
                    ),
                    affiliate_links_disclosed=bool(
                        re.search(r"\b(affiliate|commission|links below)\b", text, re.I)
                    ),
                )
            )
            for segment in transcript.get("segments", [])[:3]:
                quote = segment.get("text")
                if not quote:
                    continue
                lowered = quote.lower()
                kind = (
                    "concern"
                    if "concern" in lowered
                    else "con"
                    if "con:" in lowered
                    else "pro"
                    if "pro:" in lowered
                    else "other"
                )
                claims.append(
                    InterpretedVideoClaim(
                        video_id=video.video_id,
                        source_id=SourceId(meta["source_id"]),
                        product_id=ProductId(payload["products"][0]["product_id"])
                        if payload["products"]
                        else None,
                        transcript_segment_id=SourceId(segment["segment_id"]),
                        quote=quote[:700],
                        signal_kind=kind,
                        interpretation=f"Reviewer-described {kind} for this product.",
                    )
                )
        return _MockResult(
            final_output=YouTubeReviewModelOutput(
                selected_videos=tuple(selections), claims=tuple(claims)
            )
        )


@dataclass
class _MockResult:
    final_output: Any


@dataclass
class YouTubeReviewIntelligenceAgent:
    settings: Settings
    video_search_provider: VideoSearchProvider | None = None
    transcript_provider: TranscriptProvider | None = None
    citation_store: HostedCitationStore | None = None
    model_runner: YouTubeReviewModelRunner = field(
        default_factory=OpenAIAgentsSDKYouTubeReviewModelRunner
    )
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(), init=False, repr=False
    )

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return self._workbench_activity

    def prepare_delegated_run(
        self, input_data: YouTubeReviewIntelligenceAgentInput
    ) -> tuple[Agent[Any], YouTubeReviewTools, Any]:
        config = build_openai_agent_run_configuration(
            self.settings,
            agent_name="YouTubeReviewIntelligenceAgent",
            run_id=str(input_data.run_id),
        )
        tools = YouTubeReviewTools(
            input_data=input_data,
            video_provider=self.video_search_provider
            or build_video_search_provider(self.settings),
            transcript_provider=self.transcript_provider
            or build_transcript_provider(self.settings),
        )
        hosted_tool = source_hosted_tool(
            config=config,
            input_data=input_data,
            agent_name="YouTubeReviewIntelligenceAgent",
            citation_store=self.citation_store,
        )
        agent = Agent(
            name="YouTubeReviewIntelligenceAgent",
            model=config.model,
            model_settings=ModelSettings(
                max_tokens=3000, include_usage=True, tool_choice="auto"
            ),
            instructions=(
                "You are the YouTube review-evidence specialist, not a purchase recommender. "
                "Choose at most three relevant review videos for the supplied products and buying brief. "
                "Use search_videos for bounded follow-up discovery when needed, read_video_metadata for selected candidates, "
                "and read_video_transcript before citing a quote. Interpret product-specific pros, cons, concerns, "
                "and visible sponsorship or affiliate disclosures. Return exact transcript excerpts with their segment IDs; "
                "never invent quotes, timestamps, product IDs, source IDs, prices, or disclosures. "
                "If captions are inaccessible, select useful metadata only and explain the gap. "
                "Use only supplied product IDs, and do not attribute a review to a product if identity is unclear. "
                "You may use web_search for YouTube review discovery, or skip it. Put useful exact cited URLs in retained_web_urls. "
                "A hosted snippet is only a lead; use video tools and transcript segments for review claims."
            ),
            tools=[*tools.sdk_tools(), *([hosted_tool] if hosted_tool else [])],
            output_type=YouTubeReviewModelOutput,
        )
        apply_openai_agent_run_profile(agent, config)
        return agent, tools, config

    async def run(
        self, input_data: YouTubeReviewIntelligenceAgentInput
    ) -> VideoReviewEvidenceBundle:
        agent, tools, config = self.prepare_delegated_run(input_data)
        hosted_activity: tuple[dict[str, Any], ...] = ()
        run_config = RunConfig(
            tracing_disabled=not config.tracing_enabled,
            trace_include_sensitive_data=config.trace_include_sensitive_data,
            workflow_name=config.trace_workflow_name,
            trace_metadata=config.trace_metadata,
        )
        try:
            raw = await asyncio.wait_for(
                self.model_runner.run(
                    agent,
                    _model_input(input_data, tools),
                    run_config=run_config,
                    max_turns=config.max_turns,
                    tools=tools,
                ),
                timeout=config.timeout_seconds,
            )
            decision = YouTubeReviewModelOutput.model_validate(
                getattr(raw, "final_output", raw)
            )
            decision, hosted_activity = await process_source_specialist_output(
                raw=raw,
                decision=decision,
                input_data=input_data,
                agent_name=agent.name,
                citation_store=self.citation_store,
                require_sdk_metadata=isinstance(
                    self.model_runner, OpenAIAgentsSDKYouTubeReviewModelRunner
                ),
            )
            output = _validated_bundle(input_data, tools, decision)
            status = "model_evidence_completed"
        except Exception as exc:
            if isinstance(exc, OpenAIAgentConfigurationError):
                hosted_activity = (
                    *hosted_activity,
                    {
                        "tool_name": "web_search",
                        "status": "metadata_or_persistence_failed",
                        "input": {"agent": agent.name},
                        "output": {"reason": str(exc)},
                    },
                )
            if tools.bundle is None:
                self._workbench_activity = (
                    *source_tool_activity(tools.workbench_activity, agent.name),
                    *hosted_activity,
                    {
                        "tool_name": "openai_agents_structured_output",
                        "status": "model_or_provider_failed_no_video",
                    },
                )
                return VideoReviewEvidenceBundle(
                    transcript_gap_notes=(
                        "Model or video provider failed; no review evidence was accepted.",
                    )
                )
            output = _metadata_only_bundle(
                tools.bundle,
                "Model interpretation failed; no transcript-backed claim was accepted.",
            )
            status = "model_or_validation_failure_metadata_only"
        self._workbench_activity = (
            *source_tool_activity(tools.workbench_activity, agent.name),
            *hosted_activity,
            {
                "tool_name": "openai_agents_structured_output",
                "status": status,
                "input": {
                    "agent": "YouTubeReviewIntelligenceAgent",
                    "allowed_tools": [t.name for t in agent.tools],
                    "model": config.model,
                },
                "output": {
                    "video_count": len(output.videos),
                    "evidence_count": len(output.evidence),
                },
            },
        )
        return output


def _model_input(
    input_data: YouTubeReviewIntelligenceAgentInput, tools: YouTubeReviewTools
) -> str:
    return json.dumps(
        {
            "brief": input_data.brief.model_dump(mode="json"),
            "products": [p.model_dump(mode="json") for p in input_data.products],
            "video_queries": input_data.video_queries,
            "target_region_code": input_data.target_region_code,
            "supplied_videos": tools._video_summaries(tools.bundle),
            "limits": {
                "searches": tools.max_searches,
                "transcripts": tools.max_transcripts,
                "selected_videos": 3,
            },
        },
        sort_keys=True,
    )


def _validated_bundle(
    input_data: YouTubeReviewIntelligenceAgentInput,
    tools: YouTubeReviewTools,
    decision: YouTubeReviewModelOutput,
) -> VideoReviewEvidenceBundle:
    available = tools.bundle
    if available is None or not decision.selected_videos:
        return VideoReviewEvidenceBundle(
            transcript_gap_notes=(
                *decision.evidence_gaps,
                "No validated review video was selected.",
            )
        )
    video_by_id = {v.video_id: v for v in available.videos}
    source_by_url = {str(r.url): r for r in available.source_references}
    product_ids = {p.product_id for p in input_data.products}
    products = {p.product_id: p for p in input_data.products}
    selected: dict[str, SelectedVideo] = {}
    for item in decision.selected_videos:
        video = video_by_id.get(item.video_id)
        if (
            video is None
            or item.video_id in selected
            or source_by_url.get(str(video.url), None) is None
        ):
            raise ValueError("Selected video is unknown or duplicated.")
        if source_by_url[str(video.url)].source_id != item.source_id:
            raise ValueError("Selected video source ID does not match its URL.")
        if item.video_id not in tools._metadata_read:
            raise ValueError(
                "Selected video metadata was not read through the approved tool."
            )
        text = " ".join(
            [
                video.description or "",
                *[
                    s.text or ""
                    for s in available.transcript_segments
                    if s.video_id == video.video_id
                ],
            ]
        )
        if item.sponsorship_disclosed and not re.search(
            r"\b(sponsored|paid promotion|provided by|#ad)\b", text, re.I
        ):
            raise ValueError(
                "Sponsorship disclosure is not visible in retrieved material."
            )
        if item.affiliate_links_disclosed and not re.search(
            r"\b(affiliate|commission|links below)\b", text, re.I
        ):
            raise ValueError(
                "Affiliate disclosure is not visible in retrieved material."
            )
        selected[item.video_id] = item
    segments = {s.segment_id: s for s in available.transcript_segments}
    claims: list[TranscriptBackedVideoClaim] = []
    for item in decision.claims:
        segment = segments.get(item.transcript_segment_id)
        if (
            item.video_id not in selected
            or segment is None
            or segment.video_id != item.video_id
            or item.source_id != selected[item.video_id].source_id
        ):
            raise ValueError(
                "Claim cites a video, source, or segment outside the selected evidence."
            )
        if item.video_id not in tools._transcripts_read:
            raise ValueError("Claim transcript was not read through the approved tool.")
        if item.product_id is not None and item.product_id not in product_ids:
            raise ValueError("Claim cites an unsupplied product.")
        if item.product_id is not None:
            product = products[item.product_id]
            video = video_by_id[item.video_id]
            context = " ".join(
                (
                    video.title or "",
                    video.description or "",
                    *(
                        s.text or ""
                        for s in available.transcript_segments
                        if s.video_id == item.video_id
                    ),
                )
            ).casefold()
            identities = (product.model, product.name)
            if not any(
                identity and identity.casefold() in context for identity in identities
            ):
                raise ValueError(
                    "Product identity is not visible in selected video material."
                )
        if item.quote.casefold() not in (segment.text or "").casefold():
            raise ValueError("Claim quote is not present in cited transcript segment.")
        target = (
            EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT, product_id=item.product_id
            )
            if item.product_id
            else EvidenceTarget(
                target_type=EvidenceTargetType.SOURCE_METADATA, source_id=item.source_id
            )
        )
        claims.append(
            TranscriptBackedVideoClaim(
                source_id=item.source_id,
                target=target,
                video_id=item.video_id,
                claim=item.quote,
                signal_kind=item.signal_kind,
                interpretation=item.interpretation,
                confidence=Confidence(
                    score=0.7,
                    level=ConfidenceLevel.MEDIUM,
                    rationale="Model-interpreted, transcript-backed review statement.",
                ),
                source_quality=SourceQuality(
                    level=SourceQualityLevel.ADEQUATE,
                    score=0.65,
                    rationale="Timestamped transcript evidence from a selected review video.",
                ),
                transcript_segment_ids=(item.transcript_segment_id,),
            )
        )
    videos = tuple(
        video_by_id[video_id].model_copy(
            update={
                "sponsorship_disclosed": selection.sponsorship_disclosed,
                "affiliate_links_disclosed": selection.affiliate_links_disclosed,
                "bias_notes": (
                    "Visible sponsorship or affiliate disclosure; consider potential review bias."
                    if selection.sponsorship_disclosed
                    or selection.affiliate_links_disclosed
                    else None
                ),
                "affiliate_bias_risk": Confidence(
                    score=0.6
                    if selection.sponsorship_disclosed
                    or selection.affiliate_links_disclosed
                    else 0.2,
                    level=ConfidenceLevel.MEDIUM
                    if selection.sponsorship_disclosed
                    or selection.affiliate_links_disclosed
                    else ConfidenceLevel.LOW,
                    rationale="Visible disclosure assessment from selected video material.",
                ),
                "channel_signals": tuple(
                    dict.fromkeys(
                        (
                            *video_by_id[video_id].channel_signals,
                            *(
                                (ChannelSignal.SPONSORSHIP_DISCLOSED,)
                                if selection.sponsorship_disclosed
                                else ()
                            ),
                            *(
                                (ChannelSignal.AFFILIATE_LINKS_DISCLOSED,)
                                if selection.affiliate_links_disclosed
                                else ()
                            ),
                        )
                    )
                ),
            }
        )
        for video_id, selection in selected.items()
    )
    references = tuple(source_by_url[str(v.url)] for v in videos)
    selected_ids = set(selected)
    bundle = VideoReviewEvidenceBundle(
        videos=videos,
        source_references=references,
        transcript_segments=tuple(
            s for s in available.transcript_segments if s.video_id in selected_ids
        ),
        transcript_gap_notes=tuple(
            dict.fromkeys((*available.transcript_gap_notes, *decision.evidence_gaps))
        ),
    )
    output = VideoEvidenceCreator().create(bundle, tuple(claims))
    evidence = tuple(
        e.model_copy(
            update={
                "sponsorship_disclosed": selected[e.video_id].sponsorship_disclosed,
                "affiliate_links_disclosed": selected[
                    e.video_id
                ].affiliate_links_disclosed,
                "affiliate_bias_risk": next(
                    v.affiliate_bias_risk for v in videos if v.video_id == e.video_id
                ),
                **(
                    {
                        "transcript_gap": "No permitted transcript-backed claim was available for this video."
                    }
                    if e.metadata_only
                    else {}
                ),
            }
        )
        for e in output.evidence
    )
    return VideoReviewEvidenceBundle.model_validate(
        output.model_copy(update={"evidence": evidence}).model_dump()
    )


def _metadata_only_bundle(
    bundle: VideoReviewEvidenceBundle, gap: str
) -> VideoReviewEvidenceBundle:
    clean = VideoReviewEvidenceBundle(
        videos=bundle.videos[:3],
        source_references=tuple(
            r
            for r in bundle.source_references
            if any(str(r.url) == str(v.url) for v in bundle.videos[:3])
        ),
        transcript_gap_notes=(*bundle.transcript_gap_notes, gap),
    )
    return VideoReviewEvidenceBundle.model_validate(
        VideoEvidenceCreator().create(clean).model_dump()
    )
