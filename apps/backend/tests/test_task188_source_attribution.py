from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents.contracts import (
    RedditCommunityIntelligenceAgentInput,
    YouTubeReviewIntelligenceAgentInput,
)
from app.agents.live_reddit_community_intelligence import (
    InterpretedCommunitySignal,
    RedditCommunityIntelligenceAgent,
    RedditCommunityModelOutput,
    SelectedDiscussion,
)
from app.agents.live_youtube_review_intelligence import (
    InterpretedVideoClaim,
    SelectedVideo,
    YouTubeReviewIntelligenceAgent,
    YouTubeReviewModelOutput,
)
from app.agents.youtube_review_intelligence_service import (
    YouTubeReviewIntelligenceService,
)
from app.core.settings import Settings
from app.main import create_app
from app.providers import (
    FakeCommunityDiscussionProvider,
    FakeTranscriptProvider,
    FakeVideoSearchProvider,
    ProviderRunStatus,
    TranscriptProviderResult,
)
from app.schemas.ids import ProductId, new_id
from app.schemas.intake import ShoppingBrief
from app.schemas.products import CanonicalProduct
from app.schemas.search_sources import (
    CommunityDiscussionContext,
    CommunityDiscussionEvidenceBundle,
    CommunitySupportingQuote,
    EvidenceTargetType,
    ProviderMetadata,
    SourceSnapshot,
    SourceType,
    TranscriptAvailability,
    VideoSource,
    VideoTranscriptSegment,
)
from app.schemas.source_references import SourceReference


_CASES = json.loads(
    (Path(__file__).parent / "fixtures/task188_source_attribution.json").read_text()
)
_WARNING = "Public excerpts may omit owner context."
_BRIEF = ShoppingBrief(original_query="Compare Alpha Monitor and Beta Monitor.")


def _products(reverse: bool = False) -> tuple[CanonicalProduct, ...]:
    products = tuple(
        CanonicalProduct(name=name, model=name, category="monitor")
        for name in ("Alpha Monitor", "Beta Monitor")
    )
    return tuple(reversed(products)) if reverse else products


@dataclass
class _CommunityRunner:
    quote: str
    product_id: ProductId | None

    async def run(self, *args: Any, tools: Any, **kwargs: Any) -> Any:
        await tools.search("monitor owner notes")
        source = tools.bundle.discussions[0].source_id
        await tools.read(str(source))
        return SimpleNamespace(
            final_output=RedditCommunityModelOutput(
                selected_discussions=(
                    SelectedDiscussion(
                        source_id=source, relevance_reason="Observed owner discussion."
                    ),
                ),
                signals=(
                    InterpretedCommunitySignal(
                        source_id=source,
                        product_id=self.product_id,
                        claim=self.quote,
                        supporting_quotes=(
                            CommunitySupportingQuote(
                                source_id=source, quote=self.quote
                            ),
                        ),
                        evidence_quality_warnings=(_WARNING,),
                    ),
                ),
            )
        )


@dataclass
class _TranscriptProvider:
    texts: tuple[str, ...]

    @property
    def capabilities(self) -> Any:
        return FakeTranscriptProvider().capabilities

    async def fetch_transcript(
        self, video: VideoSource, options: Any = None
    ) -> TranscriptProviderResult:
        return TranscriptProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            video=video.model_copy(
                update={"transcript_availability": TranscriptAvailability.AVAILABLE}
            ),
            availability=TranscriptAvailability.AVAILABLE,
            segments=tuple(
                VideoTranscriptSegment(
                    video_id=video.video_id,
                    start_seconds=index * 10.0,
                    end_seconds=index * 10.0 + 8.0,
                    text=text,
                )
                for index, text in enumerate(self.texts)
            ),
        )


@dataclass
class _VideoRunner:
    quote: str
    product_id: ProductId | None

    async def run(self, *args: Any, tools: Any, **kwargs: Any) -> Any:
        video = tools.bundle.videos[0]
        metadata = await tools.metadata(video.video_id)
        captions = await tools.transcript(video.video_id)
        segment = next(
            item for item in captions["segments"] if self.quote in item["text"]
        )
        source = metadata["source_id"]
        return SimpleNamespace(
            final_output=YouTubeReviewModelOutput(
                selected_videos=(
                    SelectedVideo(
                        video_id=video.video_id,
                        source_id=source,
                        relevance_reason="Observed comparison review.",
                    ),
                ),
                claims=(
                    InterpretedVideoClaim(
                        video_id=video.video_id,
                        source_id=source,
                        product_id=self.product_id,
                        transcript_segment_id=segment["segment_id"],
                        quote=self.quote,
                        signal_kind="con",
                        interpretation="Qualitative reviewer observation.",
                    ),
                ),
            )
        )


async def _run(
    surface: str,
    case_name: str,
    products: tuple[CanonicalProduct, ...],
    target_name: str | None = "Beta Monitor",
) -> Any:
    case = _CASES[case_name]
    target = next(
        (item.product_id for item in products if item.name == target_name), None
    )
    if surface == "reddit":
        source = new_id()
        url = "https://www.reddit.com/r/Monitors/comments/task188/owner_notes/"
        bundle = CommunityDiscussionEvidenceBundle(
            source_references=(SourceReference(source_id=source, url=url),),
            discussions=(
                CommunityDiscussionContext(
                    source_id=source,
                    url=url,
                    thread_id="task188",
                    extracted_public_summary=" ".join(case["context"]),
                ),
            ),
        )
        agent = RedditCommunityIntelligenceAgent(
            settings=Settings(_env_file=None),
            community_provider=FakeCommunityDiscussionProvider(bundle=bundle),
            model_runner=_CommunityRunner(case["quote"], target),
        )
        return await agent.run(
            RedditCommunityIntelligenceAgentInput(
                run_id=new_id(),
                brief=_BRIEF,
                products=products,
            )
        )
    source = new_id()
    video = VideoSource(
        video_id="task188vid1",
        url="https://www.youtube.com/watch?v=task188vid1",
        title="Alpha Monitor and Beta Monitor comparison",
        description="Sponsored review with affiliate links.",
    )
    snapshot = SourceSnapshot(
        source_id=source,
        url=video.url,
        source_type=SourceType.VIDEO,
        provider=ProviderMetadata(provider_name="task188-offline"),
        video=video,
    )
    supplied = YouTubeReviewIntelligenceAgentInput(
        run_id=new_id(),
        brief=_BRIEF,
        products=products,
        source_snapshots=(snapshot,),
    )
    provider = _TranscriptProvider(tuple(case["context"]))
    if surface == "youtube_service":
        return await YouTubeReviewIntelligenceService(transcript_provider=provider).run(
            supplied
        )
    return await YouTubeReviewIntelligenceAgent(
        settings=Settings(_env_file=None),
        video_search_provider=FakeVideoSearchProvider(),
        transcript_provider=provider,
        model_runner=_VideoRunner(case["quote"], target),
    ).run(supplied)


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["reddit", "youtube_agent", "youtube_service"])
@pytest.mark.parametrize("reverse", [False, True])
async def test_named_beta_quote_keeps_beta_target_in_either_product_order(
    surface: str, reverse: bool
) -> None:
    products = _products(reverse)
    output = await _run(surface, "named_beta", products)
    evidence = next(
        item for item in output.evidence if item.claim == _CASES["named_beta"]["quote"]
    )
    assert evidence.target.product_id == next(
        item.product_id for item in products if item.name == "Beta Monitor"
    )
    assert evidence.target.target_type == EvidenceTargetType.PRODUCT
    if surface == "reddit":
        assert evidence.supporting_quotes == (
            CommunitySupportingQuote(
                source_id=evidence.source_id,
                quote="Con: Beta Monitor has poor brightness.",
            ),
        )
        assert _WARNING in evidence.evidence_quality_warnings
        assert (
            "Do not use Reddit alone for specifications, warranty, price, or availability."
            in evidence.evidence_quality_warnings
        )
    else:
        assert evidence.timestamp_references[0].start_seconds == 10.0
        assert evidence.transcript_segment_ids == (
            output.transcript_segments[1].segment_id,
        )
        assert evidence.source_id == output.source_references[0].source_id
        assert evidence.sponsorship_disclosed is True
        assert evidence.affiliate_links_disclosed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["reddit", "youtube_agent"])
async def test_beta_quote_cannot_become_alpha_evidence(surface: str) -> None:
    products = _products()
    rejected = await _run(surface, "named_beta", products, "Alpha Monitor")
    accepted = await _run(surface, "named_beta", products)
    assert accepted.evidence[0].claim == "Con: Beta Monitor has poor brightness."
    if surface == "reddit":
        assert rejected.evidence == ()
        assert (
            rejected.evidence_gaps[0].reason
            == "Model interpretation failed; no community claim was accepted."
        )
    else:
        assert [item.metadata_only for item in rejected.evidence] == [True]
        assert (
            "Model interpretation failed; no transcript-backed claim was accepted."
            in rejected.transcript_gap_notes
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["reddit", "youtube_agent", "youtube_service"])
async def test_comparison_keeps_its_exact_source_support(surface: str) -> None:
    products = _products()
    output = await _run(surface, "comparison", products, "Alpha Monitor")
    evidence = output.evidence[0]
    assert evidence.claim == "Pro: Alpha Monitor has sharper text than Beta Monitor."
    if surface == "youtube_service":
        assert evidence.target.target_type == EvidenceTargetType.SOURCE_METADATA
        assert evidence.target.source_id == evidence.source_id
        assert evidence.metadata_only is False
        assert evidence.timestamp_references[0].start_seconds == 0.0
    else:
        assert evidence.target.product_id == products[0].product_id


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["reddit", "youtube_agent", "youtube_service"])
async def test_unnamed_quote_uses_unambiguous_observed_context(surface: str) -> None:
    products = _products()
    output = await _run(surface, "unnamed_beta", products)
    evidence = next(
        item for item in output.evidence if item.claim == "Con: it has poor brightness."
    )
    assert evidence.target.product_id == products[1].product_id


@pytest.mark.asyncio
async def test_community_unnamed_quote_uses_local_subject_after_a_topic_switch() -> (
    None
):
    products = _products()
    output = await _run("reddit", "local_beta", products)
    assert output.evidence[0].claim == "Con: it has poor brightness."
    assert output.evidence[0].target.product_id == products[1].product_id


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["reddit", "youtube_agent", "youtube_service"])
async def test_ambiguous_quote_keeps_context_or_a_gap(surface: str) -> None:
    products = _products()
    output = await _run(surface, "ambiguous", products, "Alpha Monitor")
    accepted = await _run(surface, "unnamed_beta", products)
    assert accepted.evidence[0].claim == "Con: it has poor brightness."
    if surface == "reddit":
        assert output.evidence == ()
        assert (
            output.evidence_gaps[0].reason
            == "Model interpretation failed; no community claim was accepted."
        )
    elif surface == "youtube_agent":
        assert [item.metadata_only for item in output.evidence] == [True]
        assert (
            "Model interpretation failed; no transcript-backed claim was accepted."
            in output.transcript_gap_notes
        )
    else:
        evidence = next(
            item
            for item in output.evidence
            if item.claim == "Con: it has poor brightness."
        )
        assert evidence.target.target_type == EvidenceTargetType.SOURCE_METADATA
        assert evidence.target.source_id == evidence.source_id
        assert evidence.timestamp_references[0].start_seconds == 10.0


@pytest.mark.parametrize("mode", ["fixture", "mock"])
@pytest.mark.parametrize("reverse", [False, True])
def test_named_workbench_statement_attribution(mode: str, reverse: bool) -> None:
    client = TestClient(
        create_app(
            Settings(
                _env_file=None,
                environment="test",
                agent_workbench_enabled=True,
            )
        )
    )
    catalog = client.get("/internal/agent-workbench")
    assert catalog.status_code == 200
    agent = next(
        item
        for item in catalog.json()["agents"]
        if item["agent_name"] == "YouTubeReviewIntelligenceAgent"
    )
    scenario = next(
        item
        for item in agent["scenarios"]
        if item["name"] == "youtube/alpha-beta-statement-attribution"
    )
    supplied = scenario["input"]
    if reverse:
        supplied["products"].reverse()
    beta = next(item for item in supplied["products"] if item["name"] == "Beta Monitor")
    response = client.post(
        "/internal/agent-workbench/runs",
        json={
            "agent_name": "YouTubeReviewIntelligenceAgent",
            "scenario_name": scenario["name"],
            "mode": mode,
            "input": supplied,
        },
    )
    assert response.status_code == 200
    result = response.json()
    quote = next(
        item
        for item in result["output"]["evidence"]
        if item["claim"] == "Con: Beta Monitor has poor brightness."
    )
    assert quote["target"]["product_id"] == beta["product_id"]
    assert quote["target"]["target_type"] == "product"
    assert quote["source_id"] == supplied["source_snapshots"][0]["source_id"]
    assert quote["timestamp_references"][0]["start_seconds"] == 10.0
    assert result["execution_kind"] == (
        "provider_service" if mode == "fixture" else "mock_sdk_agent"
    )
    if mode == "mock":
        activity = next(
            item
            for item in result["allowed_tool_activity"]
            if item["tool_name"] == "read_video_transcript"
        )
        assert activity["status"] == "ok"
        assert activity["input"]["video_id"] == "ccAttribution188"
        assert (
            activity["output"]["source_id"]
            == supplied["source_snapshots"][0]["source_id"]
        )
        assert activity["output"]["segment_count"] == 2
        assert set(activity) == {"tool_name", "status", "input", "output"}
