from pathlib import Path

import pytest

from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.products import ProductRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_database_engine, create_session_factory
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.money import Money
from app.schemas.products import (
    CanonicalProduct,
    ListingAvailabilityStatus,
    ProductListing,
    RegionAvailability,
    SellerProfile,
    SellerTrustSignal,
    UserAddedProduct,
)
from app.schemas.ids import new_id
from app.schemas.search_sources import SourceQuality, SourceQualityLevel


def make_seller(name: str, trust_signal: SellerTrustSignal) -> SellerProfile:
    return SellerProfile(
        seller_name=name,
        seller_url=f"https://example.com/sellers/{name.lower().replace(' ', '-')}",
        trust_signal=trust_signal,
        trust_confidence=Confidence(
            score=0.86 if trust_signal == SellerTrustSignal.STRONG else 0.22,
            level=(
                ConfidenceLevel.HIGH
                if trust_signal == SellerTrustSignal.STRONG
                else ConfidenceLevel.LOW
            ),
        ),
        source_ids=(new_id(),),
    )


def make_listing(
    product: CanonicalProduct,
    title: str,
    url: str,
    seller_name: str,
    trust_signal: SellerTrustSignal,
    price: str,
    source_quality_level: SourceQualityLevel = SourceQualityLevel.UNKNOWN,
) -> ProductListing:
    return ProductListing(
        product_id=product.product_id,
        title=title,
        url=url,
        seller=make_seller(seller_name, trust_signal),
        price=Money(amount=price, currency="USD"),
        region_availability=(
            RegionAvailability(
                region_code="US",
                status=ListingAvailabilityStatus.AVAILABLE,
                source_ids=(new_id(),),
            ),
        ),
        source_quality=SourceQuality(level=source_quality_level),
        source_ids=(new_id(),),
    )


async def create_session_and_run(session_factory) -> tuple:
    async with session_factory() as db_session:
        shopping_session = await SessionRepository(db_session).create(
            original_input=CreateSessionRequest(query="Need a travel laptop"),
            current_brief=ShoppingBrief(original_query="Need a travel laptop"),
        )
        run = await RunRepository(db_session).create(shopping_session.session_id)
        await db_session.commit()
    return shopping_session, run


@pytest.mark.asyncio
async def test_product_repository_groups_duplicate_listings_without_losing_identity(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "products.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        _shopping_session, run = await create_session_and_run(session_factory)
        product = CanonicalProduct(
            name="Acme Travel Laptop 13",
            brand="Acme",
            model="Travel 13",
            category="laptop",
            source_ids=(new_id(),),
        )
        official_listing = make_listing(
            product,
            "Acme Travel Laptop 13 - Official Store",
            "https://example.com/acme/travel-13",
            "Acme Official",
            SellerTrustSignal.STRONG,
            "999.00",
            SourceQualityLevel.STRONG,
        )
        risky_listing = make_listing(
            product,
            "Acme Travel Laptop 13 - Marketplace Deal",
            "https://example.com/market/acme-travel-13",
            "Too Cheap Deals",
            SellerTrustSignal.SUSPICIOUS,
            "499.00",
            SourceQualityLevel.WEAK,
        )

        async with session_factory() as db_session:
            repository = ProductRepository(db_session)
            await repository.add_canonical_product(run.run_id, product)
            stored_official = await repository.add_product_listing(
                run.run_id,
                official_listing,
            )
            stored_risky = await repository.add_product_listing(
                run.run_id,
                risky_listing,
            )
            await db_session.commit()

        async with session_factory() as db_session:
            repository = ProductRepository(db_session)
            loaded_product = await repository.get_canonical_product(product.product_id)
            loaded_listings = await repository.list_listings_for_product(
                product.product_id,
            )

        assert stored_official.listing_id != stored_risky.listing_id
        assert loaded_product is not None
        assert set(loaded_product.listing_ids) == {
            official_listing.listing_id,
            risky_listing.listing_id,
        }
        assert {listing.listing_id for listing in loaded_listings} == {
            official_listing.listing_id,
            risky_listing.listing_id,
        }
        seller_trust_by_listing = {
            listing.listing_id: listing.seller.trust_signal
            for listing in loaded_listings
        }
        assert seller_trust_by_listing[official_listing.listing_id] == (
            SellerTrustSignal.STRONG
        )
        assert seller_trust_by_listing[risky_listing.listing_id] == (
            SellerTrustSignal.SUSPICIOUS
        )
        source_quality_by_listing = {
            listing.listing_id: listing.source_quality.level
            for listing in loaded_listings
        }
        assert source_quality_by_listing[official_listing.listing_id] == (
            SourceQualityLevel.STRONG
        )
        assert source_quality_by_listing[risky_listing.listing_id] == (
            SourceQualityLevel.WEAK
        )

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_product_repository_stores_shortlist_and_user_added_products(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "products.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        shopping_session, run = await create_session_and_run(session_factory)
        product = CanonicalProduct(name="Acme Travel Laptop 13")
        listing = make_listing(
            product,
            "Acme Travel Laptop 13",
            "https://example.com/acme/travel-13",
            "Acme Official",
            SellerTrustSignal.REASONABLE,
            "899.00",
        )
        user_added = UserAddedProduct(
            input_text="This is the laptop I was considering.",
            product=product,
            listing=listing,
        )

        async with session_factory() as db_session:
            repository = ProductRepository(db_session)
            await repository.add_canonical_product(run.run_id, product)
            await repository.add_product_listing(run.run_id, listing)
            membership = await repository.add_shortlist_membership(
                run.run_id,
                product_id=product.product_id,
                listing_id=listing.listing_id,
                candidate_id=user_added.candidate_id,
                position=0,
            )
            stored_user_added = await repository.add_user_added_product(
                shopping_session.session_id,
                user_added,
                run_id=run.run_id,
            )
            await db_session.commit()

        async with session_factory() as db_session:
            repository = ProductRepository(db_session)
            memberships = await repository.list_shortlist_memberships(run.run_id)
            user_added_products = await repository.list_user_added_products(
                shopping_session.session_id,
            )

        assert membership.candidate_id == user_added.candidate_id
        assert membership.product_id == product.product_id
        assert membership.listing_id == listing.listing_id
        assert memberships[0].candidate_id == user_added.candidate_id
        assert stored_user_added.candidate_id == user_added.candidate_id
        assert user_added_products[0].product is not None
        assert user_added_products[0].listing is not None
        assert user_added_products[0].listing.listing_id == listing.listing_id

    finally:
        await engine.dispose()
