import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from pydantic import AnyHttpUrl, ValidationError

import app.db.models  # noqa: F401
from app.agents.catalog import ProductAnalysisRoute
from app.agents.contracts import ExtractionAgentOutput, VerificationAgentInput
from app.agents.live_comparison_decision import (
    LiveComparisonDecisionAgent,
    MockComparisonDecisionModelRunner,
)
from app.agents.live_generic_product_analyst import (
    LiveGenericProductAnalystAgent,
    MockGenericProductAnalystModelRunner,
)
from app.agents.live_seller_listing_trust import (
    LiveSellerListingTrustAgent,
    MockSellerListingTrustModelRunner,
)
from app.agents.live_verifier_critic import (
    LiveVerifierCriticAgent,
    MockVerifierCriticModelRunner,
)
from app.agents.model_input_projection import restore_evidence, restore_explanations
from app.core.settings import AgentWorkflowMode, Settings
from app.db.base import Base
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.repositories.source_intelligence import SourceIntelligenceRepository
from app.db.repositories.video_sources import VideoReviewRepository
from app.db.session import create_database_engine, create_session_factory
from app.orchestration.shopping_runs import (
    CandidateDeduplicationRunOutput,
    RepositoryShoppingRunPersistenceHooks,
    ShoppingRunContext,
    ShoppingRunOrchestrator,
    SourceIntelligenceRunOutput,
    _analysis_evidence,
    _analysis_evidence_gaps,
)
from app.schemas.ids import new_id
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.products import CanonicalProduct, ProductListing, SellerProfile
from app.schemas.search_sources import (
    AmazonEvidenceContext,
    CommunityDiscussionEvidenceBundle,
    CommunityEvidenceContext,
    EvidenceTarget,
    EvidenceTargetType,
    EvidenceType,
    IKEAEvidenceContext,
    ProviderMetadata,
    ReusableSourceIntelligenceRequest,
    SourceEvidence,
    SourceEvidenceGap,
    SourceIntelligenceCapability,
    SourceReference,
    SourceSnapshot,
    SourceType,
    VideoEvidenceContext,
)
from app.services.product_deduplication import (
    DeterministicDeduplicationResult,
    DeterministicProductGroup,
)
from app.services.reusable_source_evidence import project_reusable_source_bundle
from test_source_intelligence_repository import (
    make_amazon_fixture,
    make_confidence,
    make_ikea_fixture,
    make_quality,
    make_reddit_fixture,
    make_video_fixture,
)


@dataclass
class CaptureRunner:
    delegate: Any
    inputs: list[dict[str, Any]] = field(default_factory=list)

    async def run(self, agent, model_input, **kwargs):
        self.inputs.append(restore_explanations(json.loads(model_input)))
        return await self.delegate.run(agent, model_input, **kwargs)


class GenericRoute:
    async def run(self, input_data):
        return ProductAnalysisRoute(
            category="office chairs", agent_path=("GenericProductAnalystAgent",)
        )


def source_context():
    alpha_id = UUID("00000000-0000-0000-0000-000000000179")
    beta_id = UUID("00000000-0000-0000-0000-000000000180")
    ordinary = SourceSnapshot(
        url="https://shop.example.com/alpha",
        source_type=SourceType.RETAILER_LISTING,
        provider=ProviderMetadata(provider_name="offline-test"),
    )
    alpha = CanonicalProduct(
        product_id=alpha_id,
        name="Alpha chair",
        category="office chairs",
        source_ids=(ordinary.source_id,),
    )
    beta = CanonicalProduct(
        product_id=beta_id, name="Beta chair", category="office chairs"
    )
    listing = ProductListing(
        product_id=alpha_id,
        title="Alpha chair",
        url=ordinary.url,
        seller=SellerProfile(
            seller_name="Alpha seller", source_ids=(ordinary.source_id,)
        ),
        source_ids=(ordinary.source_id,),
    )
    alternate = listing.model_copy(
        deep=True,
        update={
            "listing_id": new_id(),
            "url": AnyHttpUrl("https://shop.example.com/alpha-other"),
        },
    )
    beta_listing = listing.model_copy(
        deep=True,
        update={
            "listing_id": new_id(),
            "product_id": beta_id,
            "title": "Beta chair",
            "url": AnyHttpUrl("https://shop.example.com/beta"),
        },
    )
    snapshots_bundles = (
        make_video_fixture(alpha_id),
        make_reddit_fixture(alpha_id),
        make_amazon_fixture(alpha_id, listing.listing_id),
        make_ikea_fixture(alpha_id),
    )
    video, reddit, amazon, ikea = (item[1] for item in snapshots_bundles)
    video = video.model_copy(
        update={"transcript_gap_notes": ("A second review has no approved captions.",)}
    )
    missing = SourceSnapshot(
        url="https://www.reddit.com/r/OfficeChairs/comments/missing/",
        source_type=SourceType.COMMUNITY_DISCUSSION,
        provider=ProviderMetadata(provider_name="offline-test"),
    )
    missing_gap = SourceEvidenceGap(
        capability=SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
        source_id=missing.source_id,
        summary="The assigned public discussion was unavailable; no claims were accepted.",
    )
    unavailable = CommunityDiscussionEvidenceBundle(
        source_references=(
            SourceReference(source_id=missing.source_id, url=missing.url),
        ),
        evidence_gaps=(missing_gap,),
    )
    ordinary_evidence = SourceEvidence(
        source_id=ordinary.source_id,
        target=EvidenceTarget(
            target_type=EvidenceTargetType.PRODUCT, product_id=alpha_id
        ),
        evidence_type=EvidenceType.PRODUCT_SPEC,
        claim="Alpha chair has an adjustable seat.",
        confidence=make_confidence(),
        source_quality=make_quality(),
    )
    other_listing_evidence = ordinary_evidence.model_copy(
        update={
            "evidence_id": new_id(),
            "target": EvidenceTarget(
                target_type=EvidenceTargetType.LISTING, listing_id=alternate.listing_id
            ),
            "claim": "Only the alternate Alpha offer has a seller concern.",
        }
    )
    beta_evidence = ordinary_evidence.model_copy(
        update={
            "evidence_id": new_id(),
            "target": EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT, product_id=beta_id
            ),
            "claim": "Beta chair has a fixed seat.",
        }
    )
    request = ReusableSourceIntelligenceRequest(
        brief=ShoppingBrief(original_query="Compare office chairs"),
        product_ids=(alpha_id, beta_id),
        listing_ids=(listing.listing_id, alternate.listing_id, beta_listing.listing_id),
        requested_capabilities=tuple(SourceIntelligenceCapability),
    )
    output = SourceIntelligenceRunOutput(
        request=request,
        video_bundles=(video,),
        community_bundles=(reddit, unavailable),
        amazon_bundles=(amazon,),
        ikea_bundles=(ikea,),
        notes=("Diagnostic source-stage note.",),
    )
    context = ShoppingRunContext(
        run_id=new_id(),
        session_id=new_id(),
        trace_id="task179-offline",
        active_brief=request.brief,
        owner_products=(alpha, beta),
        owner_listings=(listing, alternate, beta_listing),
        extraction_evidence=(ordinary_evidence, other_listing_evidence, beta_evidence),
        source_intelligence=output,
    )
    context.deduplication = CandidateDeduplicationRunOutput(
        result=DeterministicDeduplicationResult(
            groups=(
                DeterministicProductGroup(product=alpha, listings=(listing, alternate)),
                DeterministicProductGroup(product=beta, listings=(beta_listing,)),
            )
        ),
        pre_dedupe_count=3,
        post_dedupe_count=2,
    )
    snapshots = (ordinary, missing, *(item[0] for item in snapshots_bundles))
    return context, snapshots, missing_gap


def test_projection_preserves_original_records_and_keeps_backend_context_out_of_model_outputs():
    context, _, missing_gap = source_context()
    evidence = _analysis_evidence(context)
    assert len(evidence) == 13
    assert len({item.evidence_id for item in evidence}) == 13
    output = context.source_intelligence
    assert output is not None
    for bundle in (
        *output.video_bundles,
        *output.community_bundles,
        *output.amazon_bundles,
        *output.ikea_bundles,
    ):
        projection = project_reusable_source_bundle(bundle)
        for original, projected in zip(
            bundle.evidence, projection.evidence, strict=True
        ):
            assert projected.evidence_id == original.evidence_id
            assert projected.source_id == original.source_id
            assert projected.target == original.target
            assert projected.claim == original.claim
            assert projected.reusable_source_context.record == original
    video = next(
        item
        for item in evidence
        if isinstance(item.reusable_source_context, VideoEvidenceContext)
    )
    assert video.transcript_support[0].text == "The seat cushion held up after a year."
    assert video.transcript_support[0].start_seconds == 12.0
    assert video.timestamp_references[0].end_seconds == 18.0
    reddit = next(
        item
        for item in evidence
        if isinstance(item.reusable_source_context, CommunityEvidenceContext)
    )
    assert reddit.reusable_source_context.record.evidence_quality_warnings == (
        "Anecdotal community discussion.",
    )
    assert reddit.reusable_source_context.record.qualitative_signal is True
    amazon = next(
        item
        for item in evidence
        if isinstance(item.reusable_source_context, AmazonEvidenceContext)
    )
    assert (
        amazon.reusable_source_context.listing_contexts[0].marketplace_country_code
        == "US"
    )
    assert (
        amazon.reusable_source_context.listing_contexts[0].seller_name
        == "Third Party Seller"
    )
    ikea = next(
        item
        for item in evidence
        if isinstance(item.reusable_source_context, IKEAEvidenceContext)
    )
    assert ikea.reusable_source_context.store_contexts[0].country_code == "US"
    assert missing_gap in _analysis_evidence_gaps(context)
    assert _analysis_evidence_gaps(context) == _analysis_evidence_gaps(context)
    assert not any(
        gap.summary == "Diagnostic source-stage note."
        for gap in _analysis_evidence_gaps(context)
    )
    schema = ExtractionAgentOutput.model_json_schema()
    assert (
        "reusable_source_context" not in schema["$defs"]["SourceEvidence"]["properties"]
    )
    assert "VideoEvidenceContext" not in schema["$defs"]
    assert SourceEvidence.model_validate_json(video.model_dump_json()) == video
    with pytest.raises(ValidationError, match="exact evidence record"):
        SourceEvidence.model_validate(
            {**video.model_dump(), "claim": "A different unsupported claim."}
        )
    context.owner_evidence = (evidence[0],)
    assert len(_analysis_evidence(context)) == 13
    context.owner_evidence = (
        evidence[0].model_copy(update={"claim": "Conflicting saved claim."}),
    )
    with pytest.raises(ValueError, match="conflicting source records"):
        _analysis_evidence(context)


@pytest.mark.asyncio
async def test_actual_consumers_receive_scoped_source_records_and_unavailable_source_gaps(
    tmp_path: Path,
):
    context, snapshots, missing_gap = source_context()
    context.saved_source_snapshots = snapshots
    settings = Settings(_env_file=None, database_path=tmp_path / "unused.sqlite3")
    analyst = CaptureRunner(MockGenericProductAnalystModelRunner())
    trust = CaptureRunner(MockSellerListingTrustModelRunner())
    comparison = CaptureRunner(MockComparisonDecisionModelRunner())
    orchestrator = ShoppingRunOrchestrator(
        persistence_hooks=SimpleNamespace(),
        agent_workflow_mode=AgentWorkflowMode.LIVE,
        category_router_agent=GenericRoute(),
        generic_product_analyst_agent=LiveGenericProductAnalystAgent(settings, analyst),
        seller_listing_trust_agent=LiveSellerListingTrustAgent(
            settings=settings, model_runner=trust
        ),
        comparison_decision_agent=LiveComparisonDecisionAgent(settings, comparison),
    )
    await orchestrator._run_listing_trust(context)
    await orchestrator._run_category_analysis(context)
    await orchestrator._run_comparison_decision(context)
    assert len(trust.inputs) == 3
    assert len(analyst.inputs) == 2
    assert len(comparison.inputs) == 1
    alpha_rows = restore_evidence(analyst.inputs[0])
    beta_rows = restore_evidence(analyst.inputs[1])
    assert "Alpha chair has an adjustable seat." in {row["claim"] for row in alpha_rows}
    assert {row["claim"] for row in beta_rows} == {"Beta chair has a fixed seat."}
    expected_caps = {capability.value for capability in SourceIntelligenceCapability}
    assert {
        row["reusable_source_context"]["capability"]
        for row in alpha_rows
        if row.get("reusable_source_context")
    } == expected_caps
    assert "Only the alternate Alpha offer has a seller concern." not in {
        row["claim"] for row in trust.inputs[0]["evidence"]
    }
    assert "Only the alternate Alpha offer has a seller concern." in {
        row["claim"] for row in trust.inputs[1]["evidence"]
    }
    assert {row["claim"] for row in trust.inputs[2]["evidence"]} == {
        "Beta chair has a fixed seat."
    }
    product_video = next(
        row
        for row in trust.inputs[0]["evidence"]
        if row["evidence_type"] == "video_claim"
    )
    assert product_video["target"]["target_type"] == "product"
    assert product_video["target"]["listing_id"] is None
    for payload in (*trust.inputs, *analyst.inputs, *comparison.inputs):
        assert missing_gap.model_dump(mode="json") in payload["evidence_gaps"]
    packets = comparison.inputs[0]["decision_sources"]["sources"]
    compared_rows = [row for packet in packets for row in packet["evidence"]]
    assert {row["evidence_id"] for row in compared_rows} == {
        str(item.evidence_id) for item in _analysis_evidence(context)
    }
    assert all(packet["url"] for packet in packets)
    assert context.recommendation_bundle is not None
    verifier = CaptureRunner(MockVerifierCriticModelRunner())
    report = await LiveVerifierCriticAgent(settings, verifier).run(
        VerificationAgentInput(
            run_id=context.run_id,
            brief=context.active_brief,
            recommendation_bundle=context.recommendation_bundle,
            products=context.owner_products,
            listings=context.owner_listings,
            evidence=_analysis_evidence(context),
            evidence_gaps=_analysis_evidence_gaps(context),
        )
    )
    assert report.approved is True
    assert missing_gap.model_dump(mode="json") in verifier.inputs[0]["evidence_gaps"]
    assert {row["evidence_id"] for row in restore_evidence(verifier.inputs[0])} == {
        str(item.evidence_id) for item in _analysis_evidence(context)
    }


@pytest.mark.asyncio
async def test_saved_result_resolves_projected_citations_and_original_support_in_fresh_session(
    tmp_path: Path,
):
    from app.schemas.analysis import RecommendationBundle

    context, snapshots, missing_gap = source_context()
    settings = Settings(
        _env_file=None, database_path=tmp_path / "source-consumers.sqlite3"
    )
    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = create_session_factory(engine)
        async with session_factory() as db:
            shopping_session = await SessionRepository(db).create(
                original_input=CreateSessionRequest(query="Compare office chairs"),
                current_brief=context.active_brief,
            )
            run = await RunRepository(db).create(shopping_session.session_id)
            context.run_id = run.run_id
            context.session_id = shopping_session.session_id
            sources = SearchSourceRepository(db)
            products = ProductRepository(db)
            for snapshot in snapshots:
                await sources.add_source_snapshot(run.run_id, snapshot)
            for product in context.owner_products:
                await products.add_canonical_product(run.run_id, product)
            for listing in context.owner_listings:
                await products.add_product_listing(run.run_id, listing)
            for item in context.extraction_evidence:
                await sources.add_source_evidence(run.run_id, item)
            hooks = RepositoryShoppingRunPersistenceHooks(
                run_repository=RunRepository(db),
                result_repository=ResultRepository(db),
                search_source_repository=sources,
                product_repository=products,
                source_intelligence_repository=SourceIntelligenceRepository(db),
                video_review_repository=VideoReviewRepository(db),
            )
            assert context.source_intelligence is not None
            await hooks.persist_source_intelligence(
                context, context.source_intelligence
            )
            collected = _analysis_evidence(context)
            context.recommendation_bundle = RecommendationBundle(
                final_product_id=context.owner_products[0].product_id,
                final_listing_id=context.owner_listings[0].listing_id,
                primary_product_ids=(context.owner_products[0].product_id,),
                final_rationale="Consider the supplied chair evidence and its cautions.",
                evidence_ids=tuple(item.evidence_id for item in collected),
                source_ids=tuple(dict.fromkeys(item.source_id for item in collected)),
            )
            await hooks.persist_live_output(context)
            await db.commit()
        async with session_factory() as db:
            loaded = await ResultRepository(db).load_latest_result_bundle(
                context.run_id
            )
            assert loaded is not None and loaded.source_projection is not None
            projected = {
                item.evidence_id: item
                for item in loaded.source_projection.source_evidence
            }
            expected = {item.evidence_id: item for item in collected}
            assert projected == expected
            assert set(loaded.recommendation_bundle.evidence_ids) == set(projected)
            source_ids = {
                item.source_id for item in loaded.source_projection.source_snapshots
            }
            assert all(item.source_id in source_ids for item in projected.values())
            output = context.source_intelligence
            videos = VideoReviewRepository(db)
            reusable = SourceIntelligenceRepository(db)
            saved_bundles = (
                await videos.get_video_review_bundle(output.video_bundles[0].bundle_id),
                await reusable.get_community_discussion_bundle(
                    output.community_bundles[0].bundle_id
                ),
                await reusable.get_community_discussion_bundle(
                    output.community_bundles[1].bundle_id
                ),
                await reusable.get_amazon_product_bundle(
                    output.amazon_bundles[0].bundle_id
                ),
                await reusable.get_ikea_store_bundle(output.ikea_bundles[0].bundle_id),
            )
            for bundle in saved_bundles:
                assert bundle is not None
                for original in bundle.evidence:
                    assert (
                        projected[original.evidence_id].reusable_source_context.record
                        == original
                    )
            gaps = await reusable.list_reusable_source_evidence_gaps(context.run_id)
            assert missing_gap in gaps
            video = next(
                item
                for item in projected.values()
                if isinstance(item.reusable_source_context, VideoEvidenceContext)
            )
            segments = await videos.list_transcript_segments(context.run_id)
            assert video.transcript_support[0].segment_id in {
                segment.segment_id for segment in segments
            }
            assert (
                video.transcript_support[0].text
                == "The seat cushion held up after a year."
            )
    finally:
        await engine.dispose()


def test_source_eval_bridge_reuses_projection_and_keeps_legacy_context_association_explicit():
    from app.evals.source_intelligence import _analysis_evidence as eval_evidence

    context, _, _ = source_context()
    output = context.source_intelligence
    assert output is not None
    for bundle in (
        *output.video_bundles,
        *output.community_bundles,
        *output.ikea_bundles,
    ):
        assert eval_evidence(bundle) == project_reusable_source_bundle(bundle).evidence
    amazon = output.amazon_bundles[0]
    expected = project_reusable_source_bundle(amazon).evidence
    actual = eval_evidence(amazon)
    assert [item.evidence_id for item in actual] == [
        item.evidence_id for item in expected
    ]
    assert [item.claim for item in actual] == [item.claim for item in expected]
    assert all(
        item.target.listing_id is None
        for item in expected
        if item.target.target_type
        in {EvidenceTargetType.REVIEW, EvidenceTargetType.REGION}
    )
    assert all(
        item.target.listing_id == context.owner_listings[0].listing_id
        for item in actual
        if item.target.target_type
        in {EvidenceTargetType.REVIEW, EvidenceTargetType.REGION}
    )


@pytest.mark.parametrize("provenance", ("product", "listing", "seller", "region"))
def test_source_only_gaps_follow_known_product_provenance_without_requiring_claims(
    provenance,
):
    from dataclasses import replace
    from app.orchestration.shopping_runs import _evidence_gaps_for_scope
    from app.schemas.products import RegionAvailability

    context, _, shared_gap = source_context()
    alpha, beta = context.owner_products
    beta_source = new_id()
    if provenance == "product":
        beta.source_ids = (beta_source,)
    elif provenance == "listing":
        context.owner_listings[2].source_ids = (beta_source,)
    elif provenance == "seller":
        context.owner_listings[2].seller.source_ids = (beta_source,)
    else:
        context.owner_listings[2].region_availability = (
            RegionAvailability(region_code="PH", source_ids=(beta_source,)),
        )
    beta_gap = SourceEvidenceGap(
        capability=SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
        source_id=beta_source,
        summary="The Beta-only assigned source was unavailable.",
    )
    metadata_gap = SourceEvidenceGap(
        capability=SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
        target=EvidenceTarget(
            target_type=EvidenceTargetType.SOURCE_METADATA, source_id=beta_source
        ),
        summary="The Beta source metadata could not be read.",
    )
    output = context.source_intelligence
    assert output is not None
    unavailable = output.community_bundles[1]
    unavailable = CommunityDiscussionEvidenceBundle(
        source_references=(
            *unavailable.source_references,
            SourceReference(
                source_id=beta_source, url="https://community.example.com/beta"
            ),
        ),
        evidence_gaps=(*unavailable.evidence_gaps, beta_gap, metadata_gap),
    )
    context.source_intelligence = replace(
        output, community_bundles=(output.community_bundles[0], unavailable)
    )
    alpha_gaps = _evidence_gaps_for_scope(
        context, alpha.product_id, context.owner_listings[:2], ()
    )
    beta_gaps = _evidence_gaps_for_scope(
        context, beta.product_id, context.owner_listings[2:], ()
    )
    assert beta_gap not in alpha_gaps
    assert metadata_gap not in alpha_gaps
    assert beta_gap in beta_gaps
    assert metadata_gap in beta_gaps
    assert shared_gap in alpha_gaps and shared_gap in beta_gaps


@pytest.mark.asyncio
async def test_source_persistence_rejects_same_id_conflict_before_overwriting_existing_evidence(
    tmp_path: Path,
):
    context, snapshots, _ = source_context()
    settings = Settings(_env_file=None, database_path=tmp_path / "collision.sqlite3")
    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = create_session_factory(engine)
        async with session_factory() as db:
            shopping_session = await SessionRepository(db).create(
                original_input=CreateSessionRequest(query="Compare office chairs"),
                current_brief=context.active_brief,
            )
            run = await RunRepository(db).create(shopping_session.session_id)
            context.run_id = run.run_id
            context.session_id = shopping_session.session_id
            sources = SearchSourceRepository(db)
            for snapshot in snapshots:
                await sources.add_source_snapshot(run.run_id, snapshot)
            output = context.source_intelligence
            assert output is not None
            projected = project_reusable_source_bundle(
                output.video_bundles[0]
            ).evidence[0]
            existing = projected.model_copy(
                update={
                    "claim": "An existing unrelated saved claim.",
                    "reusable_source_context": None,
                }
            )
            await sources.add_source_evidence(run.run_id, existing)
            hooks = RepositoryShoppingRunPersistenceHooks(
                run_repository=RunRepository(db),
                result_repository=ResultRepository(db),
                search_source_repository=sources,
                source_intelligence_repository=SourceIntelligenceRepository(db),
                video_review_repository=VideoReviewRepository(db),
            )
            with pytest.raises(ValueError, match="conflicting source records"):
                await hooks.persist_source_intelligence(context, output)
            assert await sources.list_source_evidence(run.run_id) == (existing,)
            assert (
                await VideoReviewRepository(db).get_video_review_bundle(
                    output.video_bundles[0].bundle_id
                )
                is None
            )
            await db.commit()
        async with session_factory() as db:
            assert await SearchSourceRepository(db).list_source_evidence(
                context.run_id
            ) == (existing,)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("include_backend_context", (True, False))
async def test_public_extraction_rejects_model_authored_reusable_context_but_retains_ordinary_evidence(
    tmp_path: Path, include_backend_context: bool
):
    from app.agents.contracts import ExtractionAgentInput
    from app.agents.live_extraction import (
        LiveExtractionAgent,
        MockExtractionModelRunner,
    )
    from app.evals.discovery_extraction import FixtureSnapshotTools
    from app.schemas.search_sources import ExtractedPageContent

    context, snapshots, _ = source_context()
    projected = next(
        item
        for item in _analysis_evidence(context)
        if isinstance(item.reusable_source_context, CommunityEvidenceContext)
    )
    evidence = (
        projected
        if include_backend_context
        else projected.model_copy(update={"reusable_source_context": None})
    )
    snapshot = next(
        item for item in snapshots if item.source_id == evidence.source_id
    ).model_copy(
        update={
            "extracted_content": ExtractedPageContent(
                text=evidence.claim,
                extractor="task179-offline-fixture",
                word_count=len(evidence.claim.split()),
            )
        }
    )
    product = context.owner_products[0].model_copy(
        update={"source_ids": (evidence.source_id,)}
    )
    output = ExtractionAgentOutput(products=(product,), source_evidence=(evidence,))
    runner = MockExtractionModelRunner(output=output)
    agent = LiveExtractionAgent(
        settings=Settings(
            _env_file=None, database_path=tmp_path / "unused-extraction.sqlite3"
        ),
        snapshot_tools_factory=FixtureSnapshotTools,
        model_runner=runner,
    )
    result = await agent.run(
        ExtractionAgentInput(
            run_id=context.run_id,
            snapshot_ids=(snapshot.source_id,),
            workbench_snapshots=(snapshot,),
        )
    )
    assert runner.calls == 1
    if include_backend_context:
        assert result.products == ()
        assert result.source_evidence == ()
        assert len(result.evidence_gaps) == 1
        assert result.evidence_gaps[0].source_id == snapshot.source_id
        assert (
            result.evidence_gaps[0].summary
            == "Agent extraction was invalid or timed out."
        )
    else:
        assert result.products == (product,)
        assert result.source_evidence == (evidence,)
        assert result.evidence_gaps == ()
