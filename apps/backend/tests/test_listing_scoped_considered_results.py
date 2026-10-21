import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.models  # noqa: F401
from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.session import (
    create_database_engine,
    create_session_factory,
    get_db_session,
)
from app.main import create_app
from app.schemas.analysis import (
    ComparisonMatrix,
    ComparisonRow,
    ListingTrustAssessment,
    RecommendationBundle,
    RejectedItem,
)
from app.schemas.ids import new_id
from app.schemas.products import (
    CanonicalProduct,
    ProductListing,
    SellerProfile,
    UserAddedProduct,
)
from app.schemas.runs import RunStage, RunStatus


def test_saved_considered_results_keep_seller_exclusions_separate(
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None, database_path=tmp_path / "listing-outcomes.sqlite3"
    )  # type: ignore[call-arg]
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    app = create_app(settings)

    async def setup() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def db_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = db_session
    asyncio.run(setup())
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/sessions", json={"query": "Compare these kettles"}
            )
            assert response.status_code == 201
            session_id = UUID(response.json()["session_id"])
            shared = CanonicalProduct(name="Shared kettle")
            unrelated = CanonicalProduct(name="Other kettle")
            product_wide = CanonicalProduct(name="Unsuitable kettle")
            offers = tuple(
                ProductListing(
                    product_id=product.product_id,
                    title=f"{product.name} at {seller}",
                    url=f"https://shop.example/{index}",
                    seller=SellerProfile(seller_name=seller),
                    source_ids=(new_id(),),
                )
                for index, (product, seller) in enumerate(
                    (
                        (shared, "Unverified shop"),
                        (shared, "Authorized shop"),
                        (unrelated, "Other shop"),
                        (product_wide, "Shop A"),
                        (product_wide, "Shop B"),
                    )
                )
            )
            candidates = tuple(
                UserAddedProduct(
                    input_text=offer.title,
                    product=product,
                    listing=offer,
                    research_attempted=True,
                )
                for product, offer in zip(
                    (shared, shared, unrelated, product_wide, product_wide),
                    offers,
                    strict=True,
                )
            ) + (
                UserAddedProduct(
                    input_text="Ambiguous kettle",
                    possible_product_ids=(shared.product_id, unrelated.product_id),
                ),
                UserAddedProduct(input_text="Unresolved kettle"),
                UserAddedProduct(
                    input_text="Manual kettle",
                    product=shared,
                    manual_fallback_reason="retrieval_insufficient",
                ),
            )
            matrix = ComparisonMatrix(
                rows=tuple(
                    ComparisonRow(
                        product_id=offer.product_id,
                        listing_id=offer.listing_id,
                        summary=offer.title,
                    )
                    for offer in offers
                )
            )
            bundle = RecommendationBundle(
                no_strong_buy=True,
                no_strong_buy_reason="Compare the supported offers.",
                comparison_matrix=matrix,
                rejected_items=(
                    RejectedItem(
                        product_id=shared.product_id,
                        listing_id=offers[0].listing_id,
                        reason_code="suspicious_listing",
                        reason="Unverified shop has no verifiable seller identity.",
                        severity="high",
                    ),
                    RejectedItem(
                        product_id=product_wide.product_id,
                        reason_code="poor_fit",
                        reason="This model does not fit the request.",
                        severity="high",
                    ),
                    RejectedItem(
                        product_id=unrelated.product_id,
                        reason_code="poor_fit",
                        reason="A minor preference caveat.",
                        severity="low",
                    ),
                ),
            )
            trust = tuple(
                ListingTrustAssessment(
                    listing_id=offer.listing_id,
                    level=level,
                    confidence={"level": "high", "score": 0.9},
                    summary=summary,
                )
                for offer, level, summary in (
                    (offers[0], "suspicious", "Unverified seller identity."),
                    (
                        offers[1],
                        "reasonable",
                        "Authorized shop has documented warranty support.",
                    ),
                )
            )

            async def save() -> tuple[UUID, UUID]:
                async with factory() as session:
                    runs = RunRepository(session)
                    run = await runs.create(session_id)
                    products = ProductRepository(session)
                    for product in (shared, unrelated, product_wide):
                        await products.add_canonical_product(run.run_id, product)
                    for offer in offers:
                        await products.add_product_listing(run.run_id, offer)
                    for candidate in candidates:
                        await products.add_user_added_product(
                            session_id, candidate, run_id=run.run_id
                        )
                    await products.add_shortlist_membership(
                        run.run_id,
                        candidate_id=candidates[1].candidate_id,
                        product_id=shared.product_id,
                        listing_id=offers[1].listing_id,
                        position=1,
                    )
                    result = await ResultRepository(session).save_result_bundle(
                        run.run_id,
                        trust_assessments=trust,
                        category_analyses=(),
                        agent_records=(),
                        recommendation_bundle=bundle,
                    )
                    await runs.append_event(
                        run.run_id,
                        stage=RunStage.COMPLETE,
                        status=RunStatus.SUCCEEDED,
                        message="Saved fixture result.",
                    )
                    await session.commit()
                    return run.run_id, result.result_version.result_version_id

            run_id, version_id = asyncio.run(save())
            result_response = client.get(f"/api/sessions/{session_id}/results")
            assert result_response.status_code == 200
            body = result_response.json()
            by_candidate = {
                item["candidate"]["candidate_id"]: item
                for item in body["considered_products"]
            }
            assert [
                (
                    by_candidate[str(candidate.candidate_id)]["status"],
                    by_candidate[str(candidate.candidate_id)]["exclusion_reason"],
                )
                for candidate in candidates
            ] == [
                ("excluded", "Unverified shop has no verifiable seller identity."),
                ("confirmed", None),
                ("confirmed", None),
                ("excluded", "This model does not fit the request."),
                ("excluded", "This model does not fit the request."),
                ("possible", None),
                ("unresolved", None),
                ("manual", None),
            ]
            confirmed = by_candidate[str(candidates[1].candidate_id)]["candidate"]
            assert confirmed["listing"]["seller"]["seller_name"] == "Authorized shop"
            assert {
                item["listing_id"]: (item["level"], item["summary"])
                for item in body["trust_assessments"]
            } == {
                str(offers[0].listing_id): (
                    "suspicious",
                    "Unverified seller identity.",
                ),
                str(offers[1].listing_id): (
                    "reasonable",
                    "Authorized shop has documented warranty support.",
                ),
            }
            assert body["comparison_matrix"] == matrix.model_dump(mode="json")
            assert body["shortlist"] == [
                {
                    "candidate_id": str(candidates[1].candidate_id),
                    "product_id": str(shared.product_id),
                    "listing_id": str(offers[1].listing_id),
                    "position": 1,
                }
            ]

            async def change_saved_candidate() -> None:
                async with factory() as session:
                    await ProductRepository(session).update_user_added_product_for_run(
                        session_id,
                        candidates[1].model_copy(
                            update={
                                "input_text": "Later correction",
                                "listing": offers[0],
                            }
                        ),
                        run_id=run_id,
                    )
                    await session.commit()

            asyncio.run(change_saved_candidate())
            historical = client.get(f"/api/sessions/{session_id}/results/{version_id}")
            assert historical.status_code == 200
            assert historical.json() == body
    finally:
        asyncio.run(engine.dispose())
