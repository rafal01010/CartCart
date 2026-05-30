from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.schemas.products import CanonicalProduct, ProductListing, UserAddedProduct


def _dump_json(
    value: CanonicalProduct | ProductListing | UserAddedProduct,
) -> dict[str, Any]:
    return value.model_dump(mode="json")


class CanonicalProductRecord(Base):
    __tablename__ = "canonical_products"
    __table_args__ = (
        Index("ix_canonical_products_run_id", "run_id"),
        Index("ix_canonical_products_name", "name"),
        Index("ix_canonical_products_brand_model", "brand", "model"),
        Index("ix_canonical_products_model", "model"),
        Index("ix_canonical_products_category", "category"),
    )

    product_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(200), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    product: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        run_id: UUID,
        product: CanonicalProduct,
    ) -> "CanonicalProductRecord":
        return cls(
            product_id=str(product.product_id),
            run_id=str(run_id),
            name=product.name,
            brand=product.brand,
            model=product.model,
            category=product.category,
            product=_dump_json(product),
        )

    def to_schema(self) -> CanonicalProduct:
        return CanonicalProduct.model_validate(self.product)

    def add_listing_id(self, listing_id: UUID) -> None:
        product = self.to_schema()
        if listing_id in product.listing_ids:
            return
        self.product = _dump_json(
            product.model_copy(
                update={"listing_ids": (*product.listing_ids, listing_id)}
            )
        )


class ProductListingRecord(Base):
    __tablename__ = "product_listings"
    __table_args__ = (
        Index("ix_product_listings_run_id", "run_id"),
        Index("ix_product_listings_product_id", "product_id"),
        Index("ix_product_listings_url", "url"),
        Index("ix_product_listings_seller_name", "seller_name"),
    )

    listing_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    product_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("canonical_products.product_id"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    seller_name: Mapped[str] = mapped_column(String(200), nullable=False)
    seller_trust_signal: Mapped[str] = mapped_column(String(40), nullable=False)
    captured_at: Mapped[str] = mapped_column(String(35), nullable=False)
    listing: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        run_id: UUID,
        listing: ProductListing,
    ) -> "ProductListingRecord":
        return cls(
            listing_id=str(listing.listing_id),
            run_id=str(run_id),
            product_id=str(listing.product_id),
            title=listing.title,
            url=str(listing.url),
            seller_name=listing.seller.seller_name,
            seller_trust_signal=listing.seller.trust_signal.value,
            captured_at=listing.captured_at.isoformat(),
            listing=_dump_json(listing),
        )

    def to_schema(self) -> ProductListing:
        return ProductListing.model_validate(self.listing)


class CandidateShortlistMembershipRecord(Base):
    __tablename__ = "candidate_shortlist_memberships"
    __table_args__ = (
        Index("ix_candidate_shortlist_memberships_run_id", "run_id"),
        Index("ix_candidate_shortlist_memberships_product_id", "product_id"),
        Index("ix_candidate_shortlist_memberships_listing_id", "listing_id"),
        UniqueConstraint(
            "run_id",
            "candidate_id",
            name="uq_candidate_shortlist_memberships_run_id_candidate_id",
        ),
    )

    membership_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=False,
    )
    candidate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    product_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("canonical_products.product_id"),
        nullable=False,
    )
    listing_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("product_listings.listing_id"),
        nullable=True,
    )
    position: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[str] = mapped_column(String(35), nullable=False)


class UserAddedProductRecord(Base):
    __tablename__ = "user_added_products"
    __table_args__ = (
        Index("ix_user_added_products_session_id", "session_id"),
        Index("ix_user_added_products_run_id", "run_id"),
        Index("ix_user_added_products_product_id", "product_id"),
        Index("ix_user_added_products_listing_id", "listing_id"),
        Index("ix_user_added_products_url", "url"),
    )

    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shopping_sessions.session_id"),
        nullable=False,
    )
    run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("shopping_runs.run_id"),
        nullable=True,
    )
    product_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("canonical_products.product_id"),
        nullable=True,
    )
    listing_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("product_listings.listing_id"),
        nullable=True,
    )
    input_text: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[str] = mapped_column(String(35), nullable=False)
    user_added: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_schema(
        cls,
        *,
        session_id: UUID,
        user_added: UserAddedProduct,
        run_id: UUID | None = None,
    ) -> "UserAddedProductRecord":
        return cls(
            candidate_id=str(user_added.candidate_id),
            session_id=str(session_id),
            run_id=str(run_id) if run_id is not None else None,
            product_id=(
                str(user_added.product.product_id) if user_added.product else None
            ),
            listing_id=(
                str(user_added.listing.listing_id) if user_added.listing else None
            ),
            input_text=user_added.input_text,
            url=str(user_added.url) if user_added.url is not None else None,
            created_at=user_added.created_at.isoformat(),
            user_added=_dump_json(user_added),
        )

    def to_schema(self) -> UserAddedProduct:
        return UserAddedProduct.model_validate(self.user_added)
