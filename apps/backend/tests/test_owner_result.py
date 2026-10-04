"""Focused offline owner-result persistence and API projection checks."""

from pathlib import Path
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import AnyHttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.models  # noqa: F401
from app.agents.contracts import (
    GeneralShoppingCandidate,
    GeneralShoppingDecisionDraft,
    GeneralShoppingEvidence,
    GeneralShoppingAgentInput,
    GeneralShoppingModeSelection,
    GeneralShoppingOutcome,
    VerificationAgentInput,
    VerificationReport,
)
from app.api.routes.results import SessionResultsResponse
from app.agents.live_general_shopping import (
    GeneralCandidateSelection,
    GeneralModelOutput,
    LiveGeneralShoppingAgent,
)
from app.agents.research_tools import AgentResearchTools
from app.core.settings import AgentWorkflowMode, Settings
from app.db.base import Base
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import (
    create_database_engine,
    create_session_factory,
    get_db_session,
)
from app.main import create_app
from app.providers import FakeExtractionProvider, FakeSearchProvider
from app.orchestration.shopping_runs import (
    RepositoryShoppingRunPersistenceHooks,
    ShoppingRunContext,
    ShoppingRunOrchestrator,
)
from app.schemas.analysis import (
    ListingTrustAssessment,
    ListingTrustLevel,
    RecommendationMode,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.money import Money
from app.schemas.products import CanonicalProduct, ProductListing, SellerProfile
from app.schemas.runs import RunStage, RunStatus
from app.schemas.search_sources import (
    EvidenceTarget,
    EvidenceTargetType,
    EvidenceType,
    ExtractedPageContent,
    ExtractionStatus,
    ProviderMetadata,
    SearchIntent,
    SearchQuery,
    SearchResult,
    SourceEvidence,
    SourceQuality,
    SourceQualityLevel,
    SourceSnapshot,
    SourceType,
)


class _Owner:
    def __init__(self, name: str) -> None:
        self.workbench_activity = (
            (
                {
                    "tool_name": "sdk_handoff",
                    "status": "completed",
                    "input": {"source_agent": "GeneralShoppingAgent"},
                    "output": {"target_agent": "TechnologyDomainAnalystAgent"},
                },
                {
                    "tool_name": "sdk_handoff",
                    "status": "completed",
                    "input": {"source_agent": "TechnologyDomainAnalystAgent"},
                    "output": {"target_agent": name},
                },
            )
            if name == "SmartphoneSpecialistAgent"
            else ()
        )


class _Verifier:
    workbench_activity = ()

    def __init__(self, mode: str = "approve") -> None:
        self.mode = mode

    async def run(self, input_data: VerificationAgentInput) -> VerificationReport:
        if self.mode == "block":
            return VerificationReport(
                approved=False,
                recommendation_bundle=input_data.recommendation_bundle,
                blocking_issues=("Independent review found insufficient support.",),
            )
        bundle = input_data.recommendation_bundle
        if self.mode == "revise":
            bundle = bundle.model_copy(
                update={
                    "final_rationale": f"{input_data.products[0].name} was described on this product page."
                }
            )
        return VerificationReport(
            approved=True,
            recommendation_bundle=bundle,
            notes=(
                "Evidence check revised the rationale."
                if self.mode == "revise"
                else "Evidence check approved.",
            ),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "owner", "tampered", "verifier_mode", "with_mode"),
    [
        ("Oak walking cane", "GeneralShoppingAgent", False, "approve", False),
        ("Northstar Phone", "SmartphoneSpecialistAgent", False, "approve", False),
        ("Weak page cane", "GeneralShoppingAgent", True, "approve", False),
        ("Revised cane", "GeneralShoppingAgent", False, "revise", False),
        ("Blocked cane", "GeneralShoppingAgent", False, "block", False),
        ("Unchecked cane", "GeneralShoppingAgent", False, "skip", False),
        ("Mode cane", "GeneralShoppingAgent", False, "approve", True),
        ("Price mismatch cane", "GeneralShoppingAgent", False, "bad_price", True),
    ],
)
async def test_active_owner_result_is_verified_persisted_and_returned(
    tmp_path: Path,
    name: str,
    owner: str,
    tampered: bool,
    verifier_mode: str,
    with_mode: bool,
) -> None:
    settings = Settings(_env_file=None, database_path=tmp_path / "owner.sqlite3")  # type: ignore[call-arg]
    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as session:
            brief = ShoppingBrief(original_query=f"Should I buy {name}?")
            shopping_session = await SessionRepository(session).create(
                original_input=CreateSessionRequest(query=brief.original_query),
                current_brief=brief,
            )
            run = await RunRepository(session).create(shopping_session.session_id)
            sources = SearchSourceRepository(session)
            references = []
            for index, source_type in enumerate(
                (SourceType.PRODUCT_PAGE, SourceType.PROFESSIONAL_REVIEW)
            ):
                url = AnyHttpUrl(
                    f"https://source{index}.example.org/{name.replace(' ', '-').lower()}"
                )
                search = SearchResult(
                    query=SearchQuery(query=name, intent=SearchIntent.DISCOVERY),
                    url=url,
                    title=name,
                    source_type=source_type,
                    provider=ProviderMetadata(provider_name="offline-test"),
                )
                snapshot = SourceSnapshot(
                    url=url,
                    source_type=source_type,
                    title=name,
                    provider=search.provider,
                    extraction_status=ExtractionStatus.SUCCEEDED,
                    extracted_content=ExtractedPageContent(
                        text=(
                            f"Our review describes {name} as a promising option."
                            if index
                            else f"{name} was described on this product page."
                        ),
                        extractor="offline-test",
                        word_count=10,
                    ),
                    quality=SourceQuality(level=SourceQualityLevel.STRONG),
                )
                quote = SourceEvidence(
                    source_id=snapshot.source_id,
                    target=EvidenceTarget(
                        target_type=EvidenceTargetType.SOURCE_METADATA,
                        source_id=snapshot.source_id,
                    ),
                    evidence_type=EvidenceType.REVIEW_CLAIM
                    if index
                    else EvidenceType.PRODUCT_SPEC,
                    claim=(
                        f"Our review describes {name} as a promising option."
                        if index
                        else f"{name} was described on this product page."
                    ),
                    confidence=Confidence(score=0.8, level=ConfidenceLevel.HIGH),
                    source_quality=snapshot.quality,
                )
                await sources.add_search_result(run.run_id, search)
                await sources.add_source_snapshot(
                    run.run_id, snapshot, search_result_id=search.source_id
                )
                await sources.add_source_evidence(run.run_id, quote)
                references.append(
                    GeneralShoppingEvidence(
                        source_id=search.source_id,
                        snapshot_id=snapshot.source_id,
                        evidence_id=quote.evidence_id,
                        url=url,
                        source_type=source_type,
                        quote=quote.claim,
                    )
                )
            if tampered:
                references[0] = references[0].model_copy(
                    update={"quote": "An unrecorded claim."}
                )
            mode_candidates = ()
            mode_selections = ()
            if with_mode:
                alternate_name = "Maple walking cane"
                alternate_references = []
                for index, source_type in enumerate(
                    (SourceType.RETAILER_LISTING, SourceType.PROFESSIONAL_REVIEW)
                ):
                    url = AnyHttpUrl(
                        f"https://alternate{index}.example.net/maple-walking-cane"
                    )
                    quote_text = (
                        (
                            "Maple walking cane costs $49.00 at this shop."
                            if verifier_mode == "bad_price"
                            else "Maple walking cane costs $39.00 at this shop."
                        )
                        if index == 0
                        else "Our review describes Maple walking cane as a useful alternative."
                    )
                    search = SearchResult(
                        query=SearchQuery(
                            query=alternate_name, intent=SearchIntent.DISCOVERY
                        ),
                        url=url,
                        title=alternate_name,
                        source_type=source_type,
                        provider=ProviderMetadata(provider_name="offline-test"),
                    )
                    snapshot = SourceSnapshot(
                        url=url,
                        source_type=source_type,
                        title=alternate_name,
                        provider=search.provider,
                        extraction_status=ExtractionStatus.SUCCEEDED,
                        extracted_content=ExtractedPageContent(
                            text=quote_text, extractor="offline-test", word_count=10
                        ),
                        quality=SourceQuality(level=SourceQualityLevel.STRONG),
                    )
                    quote = SourceEvidence(
                        source_id=snapshot.source_id,
                        target=EvidenceTarget(
                            target_type=EvidenceTargetType.SOURCE_METADATA,
                            source_id=snapshot.source_id,
                        ),
                        evidence_type=EvidenceType.REVIEW_CLAIM
                        if index
                        else EvidenceType.PRICE,
                        claim=quote_text,
                        confidence=Confidence(score=0.8, level=ConfidenceLevel.HIGH),
                        source_quality=snapshot.quality,
                    )
                    await sources.add_search_result(run.run_id, search)
                    await sources.add_source_snapshot(
                        run.run_id, snapshot, search_result_id=search.source_id
                    )
                    await sources.add_source_evidence(run.run_id, quote)
                    alternate_references.append(
                        GeneralShoppingEvidence(
                            source_id=search.source_id,
                            snapshot_id=snapshot.source_id,
                            evidence_id=quote.evidence_id,
                            url=url,
                            source_type=source_type,
                            quote=quote_text,
                        )
                    )
                alternate_product = await ProductRepository(
                    session
                ).add_canonical_product(
                    run.run_id,
                    CanonicalProduct(
                        name=alternate_name,
                        category="walking cane",
                        source_ids=tuple(
                            item.snapshot_id for item in alternate_references
                        ),
                    ),
                )
                alternate_listing = await ProductRepository(
                    session
                ).add_product_listing(
                    run.run_id,
                    ProductListing(
                        product_id=alternate_product.product_id,
                        title=alternate_name,
                        url=alternate_references[0].url,
                        seller=SellerProfile(seller_name="Example Shop"),
                        price=Money(amount="39.00", currency="USD"),
                        source_ids=(
                            alternate_references[0].source_id,
                            alternate_references[0].snapshot_id,
                        ),
                    ),
                )
                mode_candidates = (
                    GeneralShoppingCandidate(
                        name=alternate_name, evidence=tuple(alternate_references)
                    ),
                )
                mode_selections = (
                    GeneralShoppingModeSelection(
                        mode=RecommendationMode.BEST_VALUE,
                        candidate_name=alternate_name,
                        listing_id=alternate_listing.listing_id,
                        rationale="Maple walking cane costs $39.00 at this shop.",
                        evidence_ids=(alternate_references[0].evidence_id,),
                    ),
                )
            draft = GeneralShoppingDecisionDraft(
                owner_agent_name=owner,
                category="smartphone" if "Phone" in name else "walking cane",
                outcome=GeneralShoppingOutcome.DRAFT,
                candidates=(
                    GeneralShoppingCandidate(name=name, evidence=tuple(references)),
                    *mode_candidates,
                ),
                mode_selections=mode_selections,
                selected_candidate_name=name,
                rationale=f"{name} looks promising based on the product page and review.",
            )
            if with_mode:
                research = AgentResearchTools(
                    agent_name="GeneralShoppingAgent",
                    run_id=run.run_id,
                    session_factory=None,
                    shared_session=session,
                    search_provider=FakeSearchProvider(),
                    extraction_provider=FakeExtractionProvider(),
                )
                research._recorded_quote_ids.update(
                    item.evidence_id
                    for candidate in draft.candidates
                    for item in candidate.evidence
                )
                model_output = GeneralModelOutput(
                    rationale=draft.rationale,
                    category="walking cane",
                    candidates=tuple(
                        GeneralCandidateSelection(
                            name=candidate.name,
                            evidence_ids=tuple(
                                item.evidence_id for item in candidate.evidence
                            ),
                        )
                        for candidate in draft.candidates
                    ),
                    selected_candidate_name=name,
                    mode_selections=mode_selections,
                )
                draft = await LiveGeneralShoppingAgent(
                    settings=settings, shared_session=session
                )._validated_draft(
                    GeneralShoppingAgentInput(run_id=run.run_id, brief=brief),
                    model_output,
                    research,
                    (),
                )
                assert draft.outcome == GeneralShoppingOutcome.DRAFT
                assert draft.mode_selections == mode_selections
            hooks = RepositoryShoppingRunPersistenceHooks(
                run_repository=RunRepository(session),
                result_repository=ResultRepository(session),
                search_source_repository=sources,
                product_repository=ProductRepository(session),
            )
            orchestrator = ShoppingRunOrchestrator(
                hooks,
                agent_workflow_mode=AgentWorkflowMode.LIVE,
                general_shopping_agent=_Owner(owner),  # type: ignore[arg-type]
                verifier_critic_agent=_Verifier(verifier_mode),  # type: ignore[arg-type]
            )
            context = ShoppingRunContext(
                run_id=run.run_id,
                session_id=shopping_session.session_id,
                trace_id="offline-owner-result",
                active_brief=brief,
                general_owner_draft=draft,
            )
            if with_mode:
                context.trust_assessments = (
                    ListingTrustAssessment(
                        listing_id=alternate_listing.listing_id,
                        level=ListingTrustLevel.REASONABLE,
                        confidence=Confidence(score=0.8, level=ConfidenceLevel.HIGH),
                        summary="The listing details were checked.",
                        evidence_ids=(alternate_references[0].evidence_id,),
                        source_ids=(alternate_references[0].snapshot_id,),
                    ),
                )
            await orchestrator._run_comparison_decision(context)
            if verifier_mode != "skip":
                await orchestrator._run_verification(context)
            await hooks.persist_live_output(context)
            await RunRepository(session).append_event(
                run.run_id,
                stage=RunStage.COMPLETE,
                status=RunStatus.SUCCEEDED,
                message="Offline owner-result analysis completed.",
            )
            await session.commit()
            app = create_app(settings)

            async def override_db_session() -> AsyncIterator[AsyncSession]:
                async with factory() as api_session:
                    yield api_session

            app.dependency_overrides[get_db_session] = override_db_session
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                api_response = await client.get(
                    f"/api/sessions/{shopping_session.session_id}/results"
                )
            assert api_response.status_code == 200
            response = SessionResultsResponse.model_validate(api_response.json())
            assert response.result_version.version == 1
            assert response.result_version.run_id == run.run_id
            assert response.recommendation_bundle.result_author == owner
            expected_action = (
                "blocked"
                if tampered or verifier_mode in {"block", "skip"}
                else "revised"
                if verifier_mode == "revise"
                else "approved"
            )
            assert response.recommendation_bundle.verification_action == expected_action
            assert response.recommendation_bundle.no_strong_buy is (
                tampered or verifier_mode in {"block", "skip"}
            )
            if tampered or verifier_mode in {"block", "skip"}:
                assert response.recommendation_bundle.final_product_id is None
                if tampered:
                    assert response.products == ()
            else:
                selected_product = next(
                    item for item in response.products if item.name == name
                )
                assert (
                    response.recommendation_bundle.final_product_id
                    == selected_product.product_id
                )
                assert response.recommendation_bundle.final_listing_id is None
                assert len(response.recommendation_bundle.evidence_ids) == 2
            if with_mode:
                if verifier_mode == "bad_price":
                    assert [
                        item.mode
                        for item in response.recommendation_bundle.mode_results
                    ] == [RecommendationMode.BEST_OVERALL]
                else:
                    assert {
                        item.mode
                        for item in response.recommendation_bundle.mode_results
                    } == {
                        RecommendationMode.BEST_OVERALL,
                        RecommendationMode.BEST_VALUE,
                    }
                    value_mode = next(
                        item
                        for item in response.recommendation_bundle.mode_results
                        if item.mode == RecommendationMode.BEST_VALUE
                    )
                    assert value_mode.listing_id == alternate_listing.listing_id
                    assert value_mode.evidence_ids == (
                        alternate_references[0].evidence_id,
                    )
            if verifier_mode == "revise":
                assert (
                    "final_rationale"
                    in response.recommendation_bundle.verification_changes
                )
                assert (
                    "Evidence check revised the rationale."
                    in response.recommendation_bundle.verification_changes
                )
            if verifier_mode == "block":
                assert (
                    "Independent review found insufficient support."
                    in response.recommendation_bundle.verification_changes
                )
            if tampered:
                assert (
                    "Selected product citations failed same-run validation."
                    in response.recommendation_bundle.verification_changes
                )
            assert len(response.source_snapshots) == (4 if with_mode else 2)
            assert len(response.source_evidence) == (4 if with_mode else 2)
            assert len(response.recommendation_bundle.handoff_chain) == (
                2 if owner != "GeneralShoppingAgent" else 0
            )
    finally:
        await engine.dispose()
