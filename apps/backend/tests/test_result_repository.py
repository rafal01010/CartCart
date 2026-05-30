from pathlib import Path

import pytest

from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_database_engine, create_session_factory
from app.schemas.analysis import (
    CategoryAnalysis,
    ComparisonCriterion,
    ComparisonMatrix,
    ComparisonRow,
    ListingTrustAssessment,
    ListingTrustLevel,
    RecommendationBundle,
    RecommendationMode,
    RecommendationModeResult,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import new_id
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.money import Money
from app.schemas.products import (
    CanonicalProduct,
    ProductListing,
    SellerProfile,
    SellerTrustSignal,
)
from app.schemas.runs import AgentRunRecord, RunStage, RunStatus


def make_confidence(score: float = 0.82) -> Confidence:
    return Confidence(
        score=score,
        level=ConfidenceLevel.HIGH if score >= 0.75 else ConfidenceLevel.MEDIUM,
        rationale="Fixture confidence.",
    )


async def create_run_with_product_and_listing(session_factory) -> tuple:
    async with session_factory() as db_session:
        shopping_session = await SessionRepository(db_session).create(
            original_input=CreateSessionRequest(query="Need a travel laptop"),
            current_brief=ShoppingBrief(original_query="Need a travel laptop"),
        )
        run = await RunRepository(db_session).create(shopping_session.session_id)
        product = CanonicalProduct(
            name="Acme Travel Laptop 13",
            brand="Acme",
            model="Travel 13",
            category="laptop",
            source_ids=(new_id(),),
        )
        listing = ProductListing(
            product_id=product.product_id,
            title="Acme Travel Laptop 13 - Official Store",
            url="https://example.com/acme/travel-13",
            seller=SellerProfile(
                seller_name="Acme Official",
                seller_url="https://example.com/acme",
                trust_signal=SellerTrustSignal.STRONG,
                trust_confidence=make_confidence(),
                source_ids=(new_id(),),
            ),
            price=Money(amount="999.00", currency="USD"),
            source_ids=(new_id(),),
        )
        product_repository = ProductRepository(db_session)
        await product_repository.add_canonical_product(run.run_id, product)
        await product_repository.add_product_listing(run.run_id, listing)
        await db_session.commit()
    return run, product, listing


@pytest.mark.asyncio
async def test_result_repository_saves_and_loads_full_fixture_bundle(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "results.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        run, product, listing = await create_run_with_product_and_listing(
            session_factory
        )
        trust_evidence_id = new_id()
        product_evidence_id = new_id()
        recommendation_evidence_id = new_id()
        trust = ListingTrustAssessment(
            listing_id=listing.listing_id,
            level=ListingTrustLevel.STRONG,
            confidence=make_confidence(),
            summary="Official seller with clear fulfillment.",
            positive_signals=("Official store.",),
            evidence_ids=(trust_evidence_id,),
            source_ids=(new_id(),),
        )
        category_analysis = CategoryAnalysis(
            product_id=product.product_id,
            listing_ids=(listing.listing_id,),
            category="laptop",
            fit_summary="Good fit for travel and daily work.",
            strengths=("Portable.", "Good value."),
            confidence=make_confidence(),
            evidence_ids=(product_evidence_id,),
            source_ids=(new_id(),),
        )
        agent_record = AgentRunRecord(
            run_id=run.run_id,
            stage=RunStage.CATEGORY_ANALYSIS,
            agent_name="GenericProductAnalystAgent",
            status=RunStatus.SUCCEEDED,
            started_at="2026-05-30T00:00:00Z",
            ended_at="2026-05-30T00:00:05Z",
            trace_id="trace-fixture",
            source_ids=(new_id(),),
        )
        comparison_matrix = ComparisonMatrix(
            criteria=(
                ComparisonCriterion(name="fit", weight=0.5),
                ComparisonCriterion(name="seller_trust", weight=0.5),
            ),
            rows=(
                ComparisonRow(
                    product_id=product.product_id,
                    listing_id=listing.listing_id,
                    scores={"fit": 0.88, "seller_trust": 0.95},
                    evidence_ids=(product_evidence_id, trust_evidence_id),
                    summary="Strong product fit from a trustworthy listing.",
                ),
            ),
        )
        recommendation = RecommendationBundle(
            final_product_id=product.product_id,
            final_listing_id=listing.listing_id,
            final_rationale="Best balance of fit, value, and seller trust.",
            mode_results=(
                RecommendationModeResult(
                    mode=RecommendationMode.BEST_OVERALL,
                    product_id=product.product_id,
                    listing_id=listing.listing_id,
                    title="Best overall",
                    rationale="Best overall based on the fixture result.",
                    confidence=make_confidence(),
                    evidence_ids=(recommendation_evidence_id,),
                    source_ids=(new_id(),),
                ),
            ),
            comparison_matrix=comparison_matrix,
            evidence_ids=(recommendation_evidence_id,),
            source_ids=(new_id(),),
        )

        async with session_factory() as db_session:
            saved = await ResultRepository(db_session).save_result_bundle(
                run.run_id,
                trust_assessments=(trust,),
                category_analyses=(category_analysis,),
                agent_records=(agent_record,),
                recommendation_bundle=recommendation,
            )
            await db_session.commit()

        async with session_factory() as db_session:
            loaded = await ResultRepository(db_session).load_latest_result_bundle(
                run.run_id
            )

        assert saved.result_version.version == 1
        assert loaded is not None
        assert loaded.result_version.version == 1
        assert loaded.trust_assessments[0].listing_id == listing.listing_id
        assert loaded.category_analyses[0].product_id == product.product_id
        assert loaded.agent_records[0].agent_name == "GenericProductAnalystAgent"
        assert loaded.comparison_matrix.rows[0].listing_id == listing.listing_id
        assert loaded.recommendation_bundle.bundle_id == recommendation.bundle_id
        assert loaded.recommendation_bundle.final_product_id == product.product_id
        assert loaded.recommendation_bundle.final_listing_id == listing.listing_id

    finally:
        await engine.dispose()
