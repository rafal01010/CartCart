import json

import pytest

from app.agents.contracts import ExtractionAgentInput, ExtractionAgentOutput
from app.agents.extraction_tools import SnapshotReadResult
from app.agents.live_extraction import LiveExtractionAgent, _validate_extraction
from app.core.settings import Settings
from app.evals.discovery_extraction import FixtureSnapshotTools
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import new_id
from app.schemas.search_sources import (
    EvidenceTarget,
    EvidenceTargetType,
    EvidenceType,
    ExtractedPageContent,
    ExtractionStatus,
    ProviderMetadata,
    SourceEvidence,
    SourceQuality,
    SourceQualityLevel,
    SourceSnapshot,
    SourceType,
)


def _evidence(source_id, claim):
    return SourceEvidence(
        source_id=source_id,
        target=EvidenceTarget(
            target_type=EvidenceTargetType.SOURCE_METADATA, source_id=source_id
        ),
        evidence_type=EvidenceType.REVIEW_CLAIM,
        claim=claim,
        confidence=Confidence(
            score=0.8, level=ConfidenceLevel.HIGH, rationale="Exact support."
        ),
        source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE),
    )


def _snapshot(text):
    return SourceSnapshot(
        url="https://example.com/review",
        source_type=SourceType.SEARCH_RESULT,
        provider=ProviderMetadata(provider_name="offline"),
        extraction_status=ExtractionStatus.SUCCEEDED,
        extracted_content=ExtractedPageContent(
            text=text, extractor="offline", word_count=len(text.split())
        ),
    )


def test_extraction_rejects_fabricated_claim_with_real_source_id():
    source_id = new_id()
    input_data = ExtractionAgentInput(run_id=new_id(), snapshot_ids=(source_id,))
    readable = {
        source_id: SnapshotReadResult(
            status="succeeded", snapshot_id=source_id, text="The battery lasts one day."
        )
    }
    with pytest.raises(ValueError, match="exact"):
        _validate_extraction(
            ExtractionAgentOutput(
                source_evidence=(_evidence(source_id, "The battery lasts ten days."),)
            ),
            readable,
            input_data,
        )
    _validate_extraction(
        ExtractionAgentOutput(
            source_evidence=(_evidence(source_id, "The battery lasts one day."),)
        ),
        readable,
        input_data,
    )


@pytest.mark.asyncio
async def test_deferred_extraction_does_not_treat_hidden_prefetch_as_observed():
    snapshots = tuple(
        _snapshot("Unread specific support. " + "Page filler. " * 500) for _ in range(8)
    )
    request = ExtractionAgentInput(
        run_id=new_id(),
        snapshot_ids=tuple(s.source_id for s in snapshots),
        workbench_snapshots=snapshots,
    )
    tools = FixtureSnapshotTools(request)
    output = ExtractionAgentOutput(
        source_evidence=(
            _evidence(snapshots[-1].source_id, "Unread specific support."),
        )
    )

    class Runner:
        async def run(self, agent, model_input, **kwargs):
            self.prompt = json.loads(model_input)
            return output

    runner = Runner()
    result = await LiveExtractionAgent(
        settings=Settings(_env_file=None, environment="test"),
        snapshot_tools_factory=lambda _: tools,
        model_runner=runner,
    ).run(request)
    assert (
        result.evidence_gaps[0].summary == "Agent extraction was invalid or timed out."
    )
    assert len(tools.observed_text) == 1
    assert "Unread specific support." in runner.prompt["pages"][0]["text"]
    assert "text" not in runner.prompt["pages"][-1]


@pytest.mark.asyncio
async def test_extraction_reads_late_support_without_spending_initial_quota():
    snapshots = tuple(
        _snapshot("Page filler. " * 500 + "Late seller warning.") for _ in range(8)
    )
    request = ExtractionAgentInput(
        run_id=new_id(),
        snapshot_ids=tuple(s.source_id for s in snapshots),
        workbench_snapshots=snapshots,
    )
    tools = FixtureSnapshotTools(request)
    tools._remaining = 2

    class Runner:
        async def run(self, agent, model_input, **kwargs):
            page = await tools.read(
                str(snapshots[-1].source_id), focus="Late seller warning."
            )
            assert page.status == "succeeded"
            return ExtractionAgentOutput(
                source_evidence=(
                    _evidence(snapshots[-1].source_id, "Late seller warning."),
                )
            )

    result = await LiveExtractionAgent(
        settings=Settings(_env_file=None, environment="test"),
        snapshot_tools_factory=lambda _: tools,
        model_runner=Runner(),
    ).run(request)
    assert result.source_evidence[0].claim == "Late seller warning."
    assert not result.evidence_gaps


def test_extraction_rejects_claim_spliced_across_separate_reads():
    source_id = new_id()
    request = ExtractionAgentInput(run_id=new_id(), snapshot_ids=(source_id,))
    readable = {
        source_id: SnapshotReadResult(
            status="succeeded", snapshot_id=source_id, text="Battery lasts\none day."
        )
    }
    output = ExtractionAgentOutput(
        source_evidence=(_evidence(source_id, "Battery lasts\none day."),)
    )
    with pytest.raises(ValueError, match="exact"):
        _validate_extraction(
            output,
            readable,
            request,
            observed_text={source_id: ["Battery lasts", "one day."]},
        )


@pytest.mark.asyncio
async def test_verifier_reloads_late_canonical_support_and_blocks_fabrication():
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.agents.contracts import VerificationAgentInput
    from app.agents.extraction_tools import SnapshotInterpretationTools
    from app.agents.live_verifier_critic import (
        LiveVerifierCriticAgent,
        MockVerifierCriticModelRunner,
    )
    from app.db.base import Base
    from app.db.repositories.runs import RunRepository
    from app.db.repositories.search_sources import SearchSourceRepository
    from app.db.repositories.sessions import SessionRepository
    from app.db.session import create_session_factory
    from app.schemas.analysis import (
        ComparisonCriterion,
        ComparisonMatrix,
        ComparisonRow,
        RecommendationBundle,
    )
    from app.schemas.intake import CreateSessionRequest, ShoppingBrief
    from app.schemas.products import CanonicalProduct

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as session:
            brief = ShoppingBrief(original_query="Compare batteries.")
            shopping_session = await SessionRepository(session).create(
                original_input=CreateSessionRequest(query=brief.original_query),
                current_brief=brief,
            )
            run = await RunRepository(session).create(shopping_session.session_id)
            snapshot = _snapshot(
                "Unrelated navigation. " * 500 + "The battery lasts one day."
            )
            canonical = _evidence(snapshot.source_id, "The battery lasts one day.")
            repository = SearchSourceRepository(session)
            await repository.add_source_snapshot(run.run_id, snapshot)
            await repository.add_source_evidence(run.run_id, canonical)
            await session.commit()
            product = CanonicalProduct(
                name="Example Battery", source_ids=(snapshot.source_id,)
            )
            request = VerificationAgentInput(
                run_id=run.run_id,
                brief=brief,
                products=(product,),
                evidence=(canonical,),
                recommendation_bundle=RecommendationBundle(
                    comparison_matrix=ComparisonMatrix(
                        criteria=(ComparisonCriterion(name="Evidence"),),
                        rows=(
                            ComparisonRow(
                                product_id=product.product_id,
                                evidence_ids=(canonical.evidence_id,),
                                summary=canonical.claim,
                            ),
                        ),
                    ),
                    final_product_id=product.product_id,
                    final_rationale=canonical.claim,
                    evidence_ids=(canonical.evidence_id,),
                    source_ids=(snapshot.source_id,),
                ),
            )
            tools = SnapshotInterpretationTools(
                run_id=run.run_id,
                allowed_snapshot_ids=(snapshot.source_id,),
                shared_session=session,
                agent_name="VerifierCriticAgent",
            )

            class Runner(MockVerifierCriticModelRunner):
                async def run(self, agent, model_input, **kwargs):
                    self.prompt = json.loads(model_input)
                    support = self.prompt["canonical_support"][0]
                    assert support["status"] == "exact_page_support"
                    assert support["start_char"] == 11000
                    assert len(agent.tools) == 1
                    page = await tools.read(
                        str(snapshot.source_id), start_char=support["start_char"]
                    )
                    assert page.text == "The battery lasts one day."
                    return await super().run(agent, model_input, **kwargs)

            runner = Runner()
            agent = LiveVerifierCriticAgent(
                settings=Settings(_env_file=None, environment="test"),
                model_runner=runner,
                snapshot_tools_factory=lambda _: tools,
            )
            report = await agent.run(request)
            assert report.approved is True
            forged = canonical.model_copy(
                update={"claim": "The battery lasts ten days."}
            )
            forged_request = request.model_copy(update={"evidence": (forged,)})
            report = await agent.run(forged_request)
            assert report.approved is False
            assert report.blocking_issues == (
                "Original support is missing or does not match the cited evidence.",
            )
            assert runner.calls == 1
            await repository.save_source_snapshot(
                run.run_id, snapshot.model_copy(update={"extracted_content": None})
            )
            report = await agent.run(request)
            assert report.approved is False
            assert report.blocking_issues == (
                "Original support is missing or does not match the cited evidence.",
            )
            from app.db.repositories.video_sources import VideoReviewRepository
            from app.schemas.search_sources import (
                VideoSource,
                VideoTranscriptSegment,
                VideoReviewEvidence,
                VideoReviewEvidenceBundle,
            )
            from app.schemas.source_references import SourceReference

            video = VideoSource(
                video_id="offline-review",
                url=snapshot.url,
                description="Unrelated description. " * 200,
            )
            segment = VideoTranscriptSegment(
                video_id=video.video_id,
                start_seconds=100,
                end_seconds=120,
                text="Unrelated captions. " * 240 + "The battery lasts one day.",
            )
            typed = VideoReviewEvidence(
                evidence_id=canonical.evidence_id,
                source_id=snapshot.source_id,
                target=canonical.target,
                video_id=video.video_id,
                claim=canonical.claim,
                confidence=canonical.confidence,
                source_quality=canonical.source_quality,
                transcript_segment_ids=(segment.segment_id,),
            )
            await repository.save_source_snapshot(
                run.run_id,
                snapshot.model_copy(
                    update={
                        "source_type": SourceType.VIDEO,
                        "video": video,
                        "extracted_content": None,
                    }
                ),
            )
            await VideoReviewRepository(session).add_video_review_bundle(
                run.run_id,
                VideoReviewEvidenceBundle(
                    videos=(video,),
                    source_references=(
                        SourceReference(source_id=snapshot.source_id, url=snapshot.url),
                    ),
                    transcript_segments=(segment,),
                    evidence=(typed,),
                ),
            )

            class BoundedCaptionRunner(MockVerifierCriticModelRunner):
                async def run(self, agent, model_input, **kwargs):
                    assert "Unrelated captions." not in model_input
                    assert "Unrelated description." not in model_input
                    assert len(model_input) < 16000
                    support = json.loads(model_input)["canonical_support"][0]
                    assert support["status"] == "canonical_typed_support"
                    first = await tools.read(str(snapshot.source_id))
                    assert first.text_truncated is True
                    assert "The battery lasts one day." not in first.text
                    late = await tools.read(
                        str(snapshot.source_id), focus="The battery lasts one day."
                    )
                    assert "The battery lasts one day." in late.text
                    assert late.source_part_ids == (segment.segment_id,)
                    assert late.timestamp_references[0].start_seconds == 100
                    return await super().run(agent, model_input, **kwargs)

            typed_agent = LiveVerifierCriticAgent(
                settings=Settings(_env_file=None, environment="test"),
                model_runner=BoundedCaptionRunner(),
                snapshot_tools_factory=lambda _: tools,
            )
            report = await typed_agent.run(request)
            assert report.approved is True
            from app.db.models.video_sources import VideoReviewEvidenceRecord

            typed_record = await session.get(
                VideoReviewEvidenceRecord, str(typed.evidence_id)
            )
            typed_record.evidence = typed.model_copy(
                update={"claim": forged.claim}
            ).model_dump(mode="json")
            await repository.save_source_evidence(run.run_id, forged)
            report = await typed_agent.run(forged_request)
            assert report.approved is False
            assert report.blocking_issues == (
                "Original support is missing or does not match the cited evidence.",
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_live_run_factory_supplies_scoped_verifier_snapshot_access():
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from app.agents.contracts import VerificationAgentInput
    from app.core.settings import AgentWorkflowMode
    from app.db.repositories.runs import RunRepository
    from app.db.repositories.search_sources import SearchSourceRepository
    from app.db.repositories.sessions import SessionRepository
    from app.schemas.analysis import ComparisonMatrix, RecommendationBundle
    from app.schemas.intake import ShoppingBrief
    from app.services.runs import RunService

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with AsyncSession(engine) as session:
            service = RunService(
                SessionRepository(session),
                RunRepository(session),
                search_source_repository=SearchSourceRepository(session),
                settings=Settings(
                    _env_file=None,
                    environment="test",
                    agent_workflow_mode=AgentWorkflowMode.LIVE,
                    live_agents_enabled=True,
                    openai_api_key="offline-test-key",
                ),
            )
            agents = service._live_agent_kwargs()
            assert "general_shopping_agent" in agents
            verifier = agents["verifier_critic_agent"]
            source_id = new_id()
            request = VerificationAgentInput(
                run_id=new_id(),
                brief=ShoppingBrief(original_query="Compare batteries."),
                evidence=(_evidence(source_id, "One day of battery life."),),
                recommendation_bundle=RecommendationBundle(
                    no_strong_buy=True,
                    no_strong_buy_reason="There is not enough checked evidence to choose a product yet. Try a more specific request or check again later.",
                    comparison_matrix=ComparisonMatrix(),
                ),
            )
            tools = verifier.snapshot_tools_factory(request)
            assert tools.sdk_tools()[0].name == "read_source_snapshot"
            rejected = await tools.read(str(new_id()))
            assert rejected.status == "unknown_snapshot"
            assert rejected.gap == "Snapshot is not assigned to this extraction."
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_wrapped_verifier_budget_failure_remains_a_technical_failure():
    from app.agents.context_management import ContextBudgetExceeded
    from app.agents.live_verifier_critic import (
        LiveVerifierCriticAgent,
        MockVerifierCriticModelRunner,
    )
    from test_live_verifier_critic_agent import _verification_input

    error = ValueError("Wrapped failure")
    error.__cause__ = ContextBudgetExceeded("Budget exhausted")
    agent = LiveVerifierCriticAgent(
        settings=Settings(_env_file=None, environment="test"),
        model_runner=MockVerifierCriticModelRunner(error=error),
    )
    with pytest.raises(ContextBudgetExceeded, match="Budget exhausted"):
        await agent.run(_verification_input())
