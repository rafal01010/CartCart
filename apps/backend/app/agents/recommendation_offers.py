import re
from collections.abc import Sequence

from app.schemas.analysis import RecommendationBundle
from app.schemas.ids import ListingId
from app.schemas.products import ProductListing


def recommendation_listing_surfaces(
    bundle: RecommendationBundle,
) -> tuple[tuple[str, ListingId], ...]:
    offers: list[tuple[str, ListingId]] = []
    if bundle.final_listing_id is not None:
        offers.append(("final pick", bundle.final_listing_id))
    offers.extend(
        (result.mode.value, result.listing_id)
        for result in bundle.mode_results
        if result.listing_id is not None
    )
    mode_product_ids = {result.product_id for result in bundle.mode_results}
    for index, product_id in enumerate(bundle.runner_up_product_ids, start=1):
        if product_id in mode_product_ids:
            continue
        listing_ids = {
            row.listing_id
            for row in bundle.comparison_matrix.rows
            if row.product_id == product_id
        }
        if len(listing_ids) == 1:
            listing_id = listing_ids.pop()
            if listing_id is not None:
                offers.append((f"runner-up offer {index}", listing_id))
    by_listing: dict[ListingId, str] = {}
    for label, listing_id in offers:
        by_listing.setdefault(listing_id, label)
    return tuple((label, listing_id) for listing_id, label in by_listing.items())


_BLOCKING_FORMS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^(?:please )?(?:do not|don't|must not|should not) (?:buy|purchase|recommend)\b\s*(?P<target>.*)$",
        r"^(?:please )?avoid (?:buying (?:from )?|purchasing (?:from )?)?(?P<target>.*)$",
        r"^do not treat (?P<target>.+) as (?:a )?safe buy$",
        r"^(?P<target>.+?) (?:is|are) (?:not (?:a )?safe (?:buy|purchase)|unsafe to (?:buy|purchase)|blocked|excluded)$",
        r"^(?P<target>.+?) (?:should|must) be avoided$",
    )
)
_IMPLICIT_OFFER = re.compile(
    r"^(?:this|the) (?:suspicious |unsafe )?(?:listing|offer|seller)$",
    re.IGNORECASE,
)


def _warning_target_ids(
    target: str,
    listing_id: ListingId,
    aliases: dict[str, set[ListingId]],
    *,
    scoped: bool,
) -> set[ListingId]:
    target = re.split(
        r"\s+(?:because|until|since|given|due to)\b", target.casefold(), maxsplit=1
    )[0].strip()
    if target in aliases:
        return aliases[target]
    if not target or _IMPLICIT_OFFER.fullmatch(target):
        return {listing_id} if scoped else set()
    if target.startswith("from "):
        return aliases.get(target[5:], set())
    parts = re.split(r"\s+(?:from|at)\s+", target, maxsplit=1)
    if len(parts) != 2:
        return set()
    offer, seller = parts
    seller_ids = aliases.get(seller, set())
    if _IMPLICIT_OFFER.fullmatch(offer):
        return seller_ids & {listing_id} if scoped else seller_ids
    return aliases.get(offer, set()) & seller_ids


def has_blocking_listing_warning(
    bundle: RecommendationBundle,
    listing_id: ListingId,
    listings: Sequence[ProductListing],
) -> bool:
    aliases: dict[str, set[ListingId]] = {}
    for listing in listings:
        for alias in (
            str(listing.listing_id),
            str(listing.url),
            listing.title,
            listing.seller.seller_name,
        ):
            if alias:
                aliases.setdefault(alias.casefold(), set()).add(listing.listing_id)

    scoped_text = [
        result.rationale
        for result in bundle.mode_results
        if result.listing_id == listing_id
    ]
    if bundle.final_listing_id == listing_id and bundle.final_rationale:
        scoped_text.append(bundle.final_rationale)
    scoped_text.extend(
        row.summary
        for row in bundle.comparison_matrix.rows
        if row.listing_id == listing_id
        and row.product_id in bundle.runner_up_product_ids
        and row.summary
    )
    for text, scoped in (
        *((text, True) for text in scoped_text),
        *((text, False) for text in bundle.warnings),
    ):
        for clause in re.split(r"[;!?,]|\.(?=\s|$)|\s+but\s+", text):
            clause = clause.strip()
            for form in _BLOCKING_FORMS:
                match = form.fullmatch(clause)
                if match and _warning_target_ids(
                    match.group("target"), listing_id, aliases, scoped=scoped
                ) == {listing_id}:
                    return True
    return False
