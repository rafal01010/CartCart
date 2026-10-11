from app.schemas.analysis import RecommendationBundle
from app.schemas.ids import ListingId


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
    choices = (
        *((f"primary choice {index}", product_id) for index, product_id in enumerate(bundle.primary_product_ids or (), start=1)),
        *((f"runner-up offer {index}", product_id) for index, product_id in enumerate(bundle.runner_up_product_ids, start=1)),
    )
    for label, product_id in choices:
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
                offers.append((label, listing_id))
    by_listing: dict[ListingId, str] = {}
    for label, listing_id in offers:
        by_listing.setdefault(listing_id, label)
    return tuple((label, listing_id) for listing_id, label in by_listing.items())
