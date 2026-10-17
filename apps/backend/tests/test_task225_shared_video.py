import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.context_management import ContextBudgetExceeded, _allowances
from app.agents.contracts import YouTubeReviewIntelligenceAgentInput
from app.agents.live_source_intelligence_manager import (
    SkippedSource, SourceIntelligenceManagerAgent, SourceManagerDecision, SourceManagerInput,
)
from app.agents.live_youtube_review_intelligence import (
    YouTubeReviewIntelligenceAgent, YouTubeReviewModelOutput, _validated_bundle,
)
from app.agents.owner_research import OwnerResearchState
from app.agents.source_consultation import SourceConsultationCheckpoint
from app.agents.source_spans import source_span
from app.agents.youtube_review_tools import YouTubeReviewTools
from app.core.settings import Settings
from app.schemas.ids import new_id
from app.schemas.intake import ShoppingBrief
from app.schemas.products import CanonicalProduct
from app.schemas.search_sources import (
    SourceIntelligenceCapability, VideoReviewEvidenceBundle, VideoSource, VideoTranscriptSegment,
)
from app.schemas.source_references import SourceReference


REAL_CHECKPOINT = Path(__file__).parent / "fixtures/providers/task225_saved_caption_checkpoint.json"
VIDEO = SourceIntelligenceCapability.VIDEO_REVIEW


class RejectProviders:
    async def search_videos(self, *args, **kwargs):
        pytest.fail("Saved discovery must not be fetched again")

    async def fetch_transcript(self, *args, **kwargs):
        pytest.fail("Saved captions must not be fetched again")


def supplied_from_saved(saved):
    value = saved["input"]
    return SourceManagerInput(
        run_id=value["run_id"], brief=ShoppingBrief.model_validate(value["brief"]),
        products=tuple(CanonicalProduct.model_validate(row) for row in value["products"]),
        listings=(), source_snapshots=(), query_hints=tuple(value["query_hints"]),
        region_code=value["region_code"], allowed_capabilities=(VIDEO,),
        reuse_key=value["reuse_key"], owner_request=value["owner_request"],
    )


@pytest.mark.asyncio
async def test_two_candidates_import_consumed_real_work_without_refetch_or_old_writes(tmp_path, monkeypatch):
    before = REAL_CHECKPOINT.read_bytes()
    saved = json.loads(before)
    assert [row["charged_tokens"] for row in saved["attempt_usage"]] == [67182, 26687, 59629, 85366]
    original = supplied_from_saved(saved)
    manager = SourceIntelligenceManagerAgent(
        Settings(_env_file=None).model_copy(update={
            "artifact_dir": tmp_path, "video_search_provider": "youtube", "video_search_provider_enabled": True,
            "transcript_provider": "yt_dlp", "transcript_provider_enabled": True,
            "search_provider": "tavily", "search_provider_enabled": True,
            "amazon_product_intelligence_provider": "serpapi", "amazon_product_intelligence_provider_enabled": True,
        }),
        video_provider=RejectProviders(), transcript_provider=RejectProviders(),
    )
    legacy = SourceConsultationCheckpoint(tmp_path, str(original.run_id), manager._compatibility(original))
    legacy.path.parent.mkdir(parents=True)
    legacy.path.write_bytes(before)
    tools_seen = []
    prepare = YouTubeReviewIntelligenceAgent.prepare_delegated_run

    def capture(self, supplied):
        result = prepare(self, supplied)
        tools_seen.append(result[1])
        return result

    monkeypatch.setattr(YouTubeReviewIntelligenceAgent, "prepare_delegated_run", capture)
    owner_state = OwnerResearchState()

    class ReadRetainedRunner:
        async def run(self, agent, model_input, **kwargs):
            tools = tools_seen[-1]
            assert tools._searched == 2
            assert tools._transcripts_read == {"Dk_FdSDiNeI", "WM9Vkls_8zI", "e9WGaciZgsc"}
            assert (await tools.search(next(iter(saved["tool_states"]["video_review"]["search_results"]))))["reused"]
            assert (await tools.search("unfunded new product search"))["status"] == "budget_exhausted"
            assert (await tools.metadata("Dk_FdSDiNeI"))["status"] == "ok"
            assert (await tools.transcript("Dk_FdSDiNeI", start_segment=308, focus="camera"))["status"] == "ok"
            allowance = _allowances.get()[-1]
            assert allowance is owner_state.source_allowance
            assert allowance.spent == 12000 * (len(tools_seen) - 1)
            reservation = allowance.reserve(12000, agent="offline-source-control")
            allowance.settle(reservation, 12000)
            return SimpleNamespace(final_output=SourceManagerDecision(
                summary="Saved speech remains available; no new product claim accepted.",
                skipped_sources=(SkippedSource(capability=VIDEO, reason="Retained material only."),),
            ))

    manager.model_runner = ReadRetainedRunner()
    results = []
    for name in ("Discovered alternative B", "Discovered alternative C"):
        results.append(await manager.run(replace(
            original, products=(CanonicalProduct(name=name, category="phone"),),
            query_hints=(name,), reuse_key=name, owner_request={"candidate_name": name},
            source_allowance=owner_state.source_allowance,
        )))
    assert [tools._span_reads for tools in tools_seen] == [11, 12]
    assert owner_state.source_allowance.spent == 24000
    with pytest.raises(ContextBudgetExceeded):
        owner_state.source_allowance.reserve(16001, agent="offline-source-control")
    for result in results:
        assert result.outcome.status == "partial"
        assert result.video_bundles[0].evidence == VideoReviewEvidenceBundle.model_validate(saved["validated_bundles"]["video_review"]).evidence
        assert result.prior_usage[:4] == tuple(saved["attempt_usage"])
    progress = json.loads(next((tmp_path / "source-progress" / str(original.run_id)).glob("*.json")).read_text())
    assert progress["tool_states"]["video_review"]["span_reads"] == 12
    assert progress["tool_states"]["video_review"]["transcripts"] == saved["tool_states"]["video_review"]["transcripts"]
    assert progress["attempt_usage"][:4] == saved["attempt_usage"]
    assert len(progress["attempt_usage"]) == 6
    assert legacy.path.read_bytes() == before
    assert REAL_CHECKPOINT.read_bytes() == before


def comparative_tools():
    products = (CanonicalProduct(name="Product A"), CanonicalProduct(name="Product B"))
    supplied = YouTubeReviewIntelligenceAgentInput(run_id=new_id(), brief=ShoppingBrief(original_query="Compare camera and battery"), products=products)
    tools = YouTubeReviewTools(supplied, RejectProviders(), RejectProviders())
    video_id = "comparison01"
    source = SourceReference(source_id=new_id(), url=f"https://www.youtube.com/watch?v={video_id}")
    texts = ["Product A lasts twelve hours.", "Product B lasts sixteen hours.", "The screen looks good."]
    segments = tuple(VideoTranscriptSegment(video_id=video_id, start_seconds=index * 10, end_seconds=index * 10 + 5, text=text) for index, text in enumerate(texts))
    bundle = VideoReviewEvidenceBundle(
        videos=(VideoSource(video_id=video_id, url=source.url, title="Product A versus Product B"),),
        source_references=(source,), transcript_segments=segments,
    )
    tools._bundles.append(bundle)
    tools._metadata_read.add(video_id)
    tools._transcripts_read.add(video_id)
    tools._transcripts[video_id] = bundle
    for segment in segments:
        tools.observed_spans[str(segment.segment_id)] = [source_span(segment.text)]
    decision = YouTubeReviewModelOutput.model_validate({
        "selected_videos": [{"video_id":video_id,"source_id":str(source.source_id),"relevance_reason":"Exact comparison."}],
        "claims": [{"video_id":video_id,"source_id":str(source.source_id),"product_id":str(product.product_id),"transcript_segment_id":str(segment.segment_id),"quote":segment.text,"signal_kind":"other","interpretation":"Measured reviewer battery result."} for product,segment in zip(products,segments)],
    })
    return tools, decision


def test_comparative_exact_claims_bind_two_products_to_one_source_and_caption_body():
    tools, decision = comparative_tools()
    result = _validated_bundle(tools.input_data, tools, decision)
    assert len(result.source_references) == len(result.videos) == 1
    assert len(result.transcript_segments) == 3
    assert [row.claim for row in result.evidence] == ["Product A lasts twelve hours.", "Product B lasts sixteen hours."]
    assert [row.target.product_id for row in result.evidence] == [product.product_id for product in tools.input_data.products]
    assert [row.timestamp_references[0].start_seconds for row in result.evidence] == [0, 10]


def test_title_only_comparative_identity_does_not_bind_unobserved_product():
    tools, decision = comparative_tools()
    first = decision.claims[0]
    segments = tools.bundle.transcript_segments
    tools.observed_spans = {str(segments[2].segment_id): [source_span(segments[2].text)]}
    claim = first.model_copy(update={"transcript_segment_id": segments[2].segment_id, "quote": segments[2].text})
    with pytest.raises(ValueError, match="Product identity"):
        _validated_bundle(tools.input_data, tools, decision.model_copy(update={"claims": (claim,)}))


@pytest.mark.asyncio
async def test_two_owner_contexts_admit_different_video_candidates_and_share_allowance(tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.agents.live_source_intelligence_manager import SourceManagerResult
    from app.agents.owner_research import OwnerResearchContext
    from app.agents.source_consultation import SourceConsultationOutcome
    from app.db.base import Base
    from app.db.repositories.sessions import SessionRepository
    from app.db.repositories.runs import RunRepository
    from app.schemas.intake import CreateSessionRequest

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db:
            brief = ShoppingBrief(original_query="Compare useful alternatives")
            session = await SessionRepository(db).create(original_input=CreateSessionRequest(query=brief.original_query), current_brief=brief)
            run = await RunRepository(db).create(session.session_id)
            await db.commit()
        state = OwnerResearchState()

        class Manager:
            requests = []

            async def run(self, supplied):
                self.requests.append(supplied)
                return SourceManagerResult(
                    outcome=SourceConsultationOutcome(status="partial"),
                    video_bundles=(VideoReviewEvidenceBundle(transcript_gap_notes=("No new accepted speech.",)),),
                )

        manager = Manager()
        owners = [OwnerResearchContext(
            agent_name="GeneralShoppingAgent", run_id=run.run_id,
            brief=brief, region_code="PH", session_factory=factory,
            source_manager=manager, research_state=state,
        ) for _ in range(2)]
        assert (await owners[0].consult_source(VIDEO, product_name="Discovered model A"))["status"] == "partial"
        assert (await owners[0].consult_source(VIDEO, product_name="Discovered model B"))["status"] == "partial"
        assert (await owners[1].consult_source(VIDEO, product_name="Discovered model C"))["status"] == "partial"
        repeated = await owners[1].consult_source(VIDEO, product_name="Discovered model A")
        assert repeated["status"] == "budget_exhausted"
        assert [supplied.products[0].name for supplied in manager.requests] == ["Discovered model A", "Discovered model B", "Discovered model C"]
        assert all(supplied.source_allowance is state.source_allowance for supplied in manager.requests)
    finally:
        await engine.dispose()


def test_comparative_quote_cannot_be_reassigned_to_adjacent_other_product():
    tools, decision = comparative_tools()
    wrong = decision.claims[0].model_copy(update={"product_id":tools.input_data.products[1].product_id})
    with pytest.raises(ValueError, match="unambiguously"):
        _validated_bundle(tools.input_data, tools, decision.model_copy(update={"claims":(wrong,)}))


def test_larger_legacy_counters_cannot_discard_accepted_speech_or_raw_work(tmp_path):
    saved = json.loads(REAL_CHECKPOINT.read_text())
    original = supplied_from_saved(saved)
    settings = Settings(_env_file=None).model_copy(update={
        "artifact_dir": tmp_path, "video_search_provider": "youtube", "video_search_provider_enabled": True,
        "transcript_provider": "yt_dlp", "transcript_provider_enabled": True,
        "search_provider": "tavily", "search_provider_enabled": True,
        "amazon_product_intelligence_provider": "serpapi", "amazon_product_intelligence_provider_enabled": True,
    })
    manager = SourceIntelligenceManagerAgent(settings)
    checkpoint = SourceConsultationCheckpoint(tmp_path, str(original.run_id), manager._compatibility(original))
    checkpoint.save(saved)
    newer = json.loads(REAL_CHECKPOINT.read_text())
    changed = replace(original, reuse_key="different-request", products=(CanonicalProduct(name="Product B"),))
    newer["input"] = manager._saved_input(changed)
    newer["tool_states"]["video_review"]["span_reads"] = 11
    newer["validated_bundles"]["video_review"]["evidence"] = []
    newer["attempt_usage"].append({"charged_tokens": 1000})
    other = SourceConsultationCheckpoint(tmp_path, str(original.run_id), manager._compatibility(changed))
    other.save(newer)
    with pytest.raises(ValueError, match="cannot be safely combined"):
        manager._legacy_video_progress(original)
    assert checkpoint.load()["validated_bundles"] == saved["validated_bundles"]


def test_overlapping_model_names_keep_max_quote_on_exact_variant():
    tools, decision = comparative_tools()
    first, second = tools.input_data.products
    second = second.model_copy(update={"name": "Product A Max"})
    tools.input_data = tools.input_data.model_copy(update={"products": (first, second)})
    bundle = tools.bundle
    segments = list(bundle.transcript_segments)
    segments[1] = segments[1].model_copy(update={"text":"Product A Max lasts sixteen hours."})
    updated = bundle.model_copy(update={"transcript_segments":tuple(segments)})
    tools._bundles = [updated]
    tools._transcripts[updated.videos[0].video_id] = updated
    tools.observed_spans[str(segments[1].segment_id)] = [source_span(segments[1].text)]
    claim = decision.claims[1].model_copy(update={"quote":segments[1].text})
    correct = decision.model_copy(update={"claims":(claim,)})
    accepted = _validated_bundle(tools.input_data, tools, correct)
    assert accepted.evidence[0].target.product_id == second.product_id
    wrong = correct.model_copy(update={"claims":(claim.model_copy(update={"product_id":first.product_id}),)})
    with pytest.raises(ValueError, match="unambiguously"):
        _validated_bundle(tools.input_data, tools, wrong)


def test_unmarked_video_cannot_bind_distant_observed_identity_to_generic_speech():
    tools, decision = comparative_tools()
    supplied = tools.input_data.model_copy(update={"products":(tools.input_data.products[0],)})
    bundle = tools.bundle
    video_id = bundle.videos[0].video_id
    texts = ["Product A has a camera."] + ["Unrelated setup detail."] * 5 + ["The battery lasts sixteen hours."]
    segments = tuple(VideoTranscriptSegment(video_id=video_id, start_seconds=index*10, text=text) for index,text in enumerate(texts))
    updated = bundle.model_copy(update={"videos":(bundle.videos[0].model_copy(update={"title":"Review impressions"}),), "transcript_segments":segments})
    tools._bundles = [updated]
    tools._transcripts[video_id] = updated
    tools.observed_spans = {str(row.segment_id):[source_span(row.text)] for row in segments}
    claim = decision.claims[0].model_copy(update={"quote":segments[-1].text,"transcript_segment_id":segments[-1].segment_id})
    with pytest.raises(ValueError, match="Product identity"):
        _validated_bundle(supplied, tools, decision.model_copy(update={"claims":(claim,)}))


def test_bounded_normal_bundle_keeps_late_alternative_with_whole_exact_support():
    from app.agents.context_management import source_bundle_context
    from app.agents.owner_research import _bounded_owner_bundle

    tools, decision = comparative_tools()
    bundle = _validated_bundle(tools.input_data, tools, decision)
    first, second = bundle.evidence
    disclosure = {
        "sponsorship_disclosed": True,
        "affiliate_links_disclosed": True,
        "affiliate_bias_risk": {"score": 0.7, "level": "medium", "rationale": "The reviewer discloses affiliate links."},
        "bias_notes": "Sponsored review with disclosed affiliate links.",
    }
    bundle = bundle.model_copy(update={"videos": (VideoSource.model_validate(bundle.videos[0].model_dump() | disclosure),)})
    repeated = tuple(first.model_copy(update={"evidence_id":new_id(), "interpretation":"An independent reviewer perspective. " * 18}) for _ in range(16))
    expanded = bundle.model_copy(update={"evidence":(*repeated,second)})
    payload = _bounded_owner_bundle(source_bundle_context(expanded), "retained-exact-bundle", max_chars=9000)
    assert len(json.dumps(payload, ensure_ascii=False)) <= 9000
    assert str(second.evidence_id) in {value["evidence_id"] for value in payload["evidence"]}
    assert payload["evidence"][1]["evidence_id"] == str(second.evidence_id)
    kept = {row["segment_id"]:row for row in payload["transcript_segments"]}
    segment = bundle.transcript_segments[1]
    assert kept[str(segment.segment_id)]["text"] == "Product B lasts sixteen hours."
    assert kept[str(segment.segment_id)]["start_seconds"] == 10
    assert kept[str(segment.segment_id)]["source_id"] == str(second.source_id)
    assert kept[str(segment.segment_id)]["url"] == str(bundle.videos[0].url)
    assert payload["deferred_evidence_ids"]
    assert {key: payload["videos"][0][key] for key in disclosure} == disclosure
