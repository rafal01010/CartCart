from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.products import (
    CandidateShortlistMembershipRecord,
    CanonicalProductRecord,
    ProductListingRecord,
    UserAddedProductRecord,
)
from app.schemas.ids import CandidateId, ListingId, ProductId, RunId, SessionId, new_id
from app.schemas.products import CanonicalProduct, ProductListing, UserAddedProduct
from app.schemas.timestamps import utc_now


@dataclass(frozen=True)
class CandidateShortlistMembership:
    membership_id: CandidateId
    run_id: RunId
    candidate_id: CandidateId
    product_id: ProductId
    listing_id: ListingId | None
    position: int | None


class ProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_canonical_product(
        self,
        run_id: RunId,
        product: CanonicalProduct,
    ) -> CanonicalProduct:
        record = CanonicalProductRecord.from_schema(run_id=run_id, product=product)
        self._session.add(record)
        await self._session.flush()
        return record.to_schema()

    async def get_canonical_product(
        self,
        product_id: ProductId,
    ) -> CanonicalProduct | None:
        record = await self._session.get(CanonicalProductRecord, str(product_id))
        if record is None:
            return None
        return record.to_schema()

    async def add_product_listing(
        self,
        run_id: RunId,
        listing: ProductListing,
    ) -> ProductListing:
        record = ProductListingRecord.from_schema(run_id=run_id, listing=listing)
        self._session.add(record)
        product_record = await self._session.get(
            CanonicalProductRecord,
            str(listing.product_id),
        )
        if product_record is not None:
            product_record.add_listing_id(listing.listing_id)
        await self._session.flush()
        return record.to_schema()

    async def get_product_listing(
        self,
        listing_id: ListingId,
    ) -> ProductListing | None:
        record = await self._session.get(ProductListingRecord, str(listing_id))
        if record is None:
            return None
        return record.to_schema()

    async def list_listings_for_product(
        self,
        product_id: ProductId,
    ) -> tuple[ProductListing, ...]:
        statement: Select[tuple[ProductListingRecord]] = (
            select(ProductListingRecord)
            .where(ProductListingRecord.product_id == str(product_id))
            .order_by(ProductListingRecord.seller_name, ProductListingRecord.url)
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)

    async def add_shortlist_membership(
        self,
        run_id: RunId,
        *,
        product_id: ProductId,
        listing_id: ListingId | None = None,
        candidate_id: CandidateId | None = None,
        position: int | None = None,
    ) -> CandidateShortlistMembership:
        record = CandidateShortlistMembershipRecord(
            membership_id=str(new_id()),
            run_id=str(run_id),
            candidate_id=str(candidate_id or new_id()),
            product_id=str(product_id),
            listing_id=str(listing_id) if listing_id is not None else None,
            position=position,
            created_at=utc_now().isoformat(),
        )
        self._session.add(record)
        await self._session.flush()
        return _to_shortlist_membership(record)

    async def list_shortlist_memberships(
        self,
        run_id: RunId,
    ) -> tuple[CandidateShortlistMembership, ...]:
        statement: Select[tuple[CandidateShortlistMembershipRecord]] = (
            select(CandidateShortlistMembershipRecord)
            .where(CandidateShortlistMembershipRecord.run_id == str(run_id))
            .order_by(
                CandidateShortlistMembershipRecord.position,
                CandidateShortlistMembershipRecord.created_at,
            )
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(_to_shortlist_membership(record) for record in records)

    async def add_user_added_product(
        self,
        session_id: SessionId,
        user_added: UserAddedProduct,
        *,
        run_id: RunId | None = None,
    ) -> UserAddedProduct:
        record = UserAddedProductRecord.from_schema(
            session_id=session_id,
            run_id=run_id,
            user_added=user_added,
        )
        self._session.add(record)
        await self._session.flush()
        return record.to_schema()

    async def update_user_added_product_for_run(
        self,
        session_id: SessionId,
        user_added: UserAddedProduct,
        *,
        run_id: RunId,
    ) -> UserAddedProduct | None:
        record = await self._session.get(
            UserAddedProductRecord,
            str(user_added.candidate_id),
        )
        if record is None or record.session_id != str(session_id):
            return None

        record.update_from_schema(user_added=user_added, run_id=run_id)
        await self._session.flush()
        return record.to_schema()

    async def list_user_added_products(
        self,
        session_id: SessionId,
    ) -> tuple[UserAddedProduct, ...]:
        statement: Select[tuple[UserAddedProductRecord]] = (
            select(UserAddedProductRecord)
            .where(UserAddedProductRecord.session_id == str(session_id))
            .order_by(UserAddedProductRecord.created_at)
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(record.to_schema() for record in records)


def _to_shortlist_membership(
    record: CandidateShortlistMembershipRecord,
) -> CandidateShortlistMembership:
    return CandidateShortlistMembership(
        membership_id=UUID(record.membership_id),
        run_id=UUID(record.run_id),
        candidate_id=UUID(record.candidate_id),
        product_id=UUID(record.product_id),
        listing_id=UUID(record.listing_id) if record.listing_id else None,
        position=record.position,
    )
