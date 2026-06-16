from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.providers.contracts import (
    AmazonProductIntelligenceProviderOptions,
    AmazonProductIntelligenceProviderResult,
    ProviderCapabilityFlags,
    ProviderRunStatus,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import new_id
from app.schemas.products import CanonicalProduct, ProductListing
from app.schemas.search_sources import (
    AmazonListingContext,
    AmazonProductEvidence,
    AmazonProductEvidenceBundle,
    EvidenceTarget,
    EvidenceTargetType,
    SourceEvidenceGap,
    SourceIntelligenceCapability,
    SourceQuality,
    SourceQualityLevel,
)
from app.schemas.source_references import SourceReference
from app.schemas.timestamps import utc_now
from app.services.amazon_evidence_creation import (
    AmazonProductEvidenceCreator,
    AmazonProductEvidenceInput,
)


SERPAPI_SEARCH_URL = "https://serpapi.com/search.json"
MAX_AMAZON_LISTINGS = 5
_ASIN_PATTERN = re.compile(r"^[A-Z0-9]{10}$")
_ASIN_PATH_PATTERN = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", re.I)
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_MATCH_STOP_WORDS = {
    "a",
    "an",
    "and",
    "for",
    "new",
    "of",
    "the",
    "with",
}
_MARKETPLACE_REGIONS = {
    "amazon.com": "US",
    "amazon.ca": "CA",
    "amazon.co.jp": "JP",
    "amazon.sg": "SG",
    "amazon.com.au": "AU",
    "amazon.co.uk": "GB",
    "amazon.de": "DE",
    "amazon.fr": "FR",
    "amazon.it": "IT",
    "amazon.es": "ES",
    "amazon.in": "IN",
    "amazon.com.mx": "MX",
    "amazon.com.br": "BR",
}
_REGION_MARKETPLACES = {
    region_code: domain for domain, region_code in _MARKETPLACE_REGIONS.items()
}


class AmazonProductIntelligenceError(RuntimeError):
    """Raised when SerpApi cannot return valid Amazon product data."""


class _SearchMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    status: str | None = None


class _AmazonSearchResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    asin: str | None = None
    title: str = Field(min_length=1)


class _AmazonSearchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    search_metadata: _SearchMetadata = Field(default_factory=_SearchMetadata)
    organic_results: list[_AmazonSearchResult] = Field(default_factory=list)


class _AmazonProductResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    search_metadata: _SearchMetadata = Field(default_factory=_SearchMetadata)
    search_parameters: dict[str, Any] = Field(default_factory=dict)
    product_results: dict[str, Any] = Field(default_factory=dict)
    reviews_information: dict[str, Any] = Field(default_factory=dict)
    purchase_options: list[dict[str, Any]] = Field(default_factory=list)
    other_sellers: list[dict[str, Any]] = Field(default_factory=list)


class SerpApiAmazonProductIntelligenceProvider:
    provider_name = "serpapi-amazon"

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        if not api_key.strip():
            raise ValueError("SerpApi API key must not be empty.")
        if timeout_seconds <= 0:
            raise ValueError("SerpApi Amazon timeout must be greater than zero.")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._client = client
        self._now = now

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name=self.provider_name,
            supports_amazon_product_intelligence=True,
            supports_amazon_listing_identity=True,
            supports_amazon_review_signals=True,
            supports_regional_ship_to_evidence=True,
            compliance_notes=(
                "Uses SerpApi's documented Amazon Search and Product APIs.",
                "Live calls require explicit local configuration and provider credentials.",
                "Returned links are neutral Amazon product URLs without affiliate tags.",
                "Review signals remain marketplace-provided and are not independently verified.",
            ),
        )

    async def fetch_product_evidence(
        self,
        product: CanonicalProduct,
        listings: tuple[ProductListing, ...] = (),
        options: AmazonProductIntelligenceProviderOptions | None = None,
    ) -> AmazonProductIntelligenceProviderResult:
        provider_options = options or AmazonProductIntelligenceProviderOptions()
        target_region = provider_options.region_code
        targets = _listing_targets(listings)

        if not targets:
            marketplace_domain = _marketplace_for_region(target_region)
            discovered_asin = await self._discover_asin(
                product,
                marketplace_domain=marketplace_domain,
                target_region=target_region,
            )
            if discovered_asin is None:
                return self._gap_result(
                    product,
                    summary="No sufficiently matching Amazon product was discovered.",
                    reason=(
                        "SerpApi returned no Amazon search result with a usable ASIN "
                        "and conservative product-name match."
                    ),
                )
            targets = ((discovered_asin, None, marketplace_domain),)

        bundles: list[AmazonProductEvidenceBundle] = []
        for asin, listing, marketplace_domain in targets[:MAX_AMAZON_LISTINGS]:
            response = await self._fetch_product(
                asin=asin,
                marketplace_domain=marketplace_domain,
                target_region=target_region,
            )
            bundles.append(
                _to_evidence_bundle(
                    response=response,
                    product=product,
                    listing=listing,
                    requested_asin=asin,
                    requested_marketplace_domain=marketplace_domain,
                    target_region=target_region,
                    accessed_at=self._now(),
                )
            )

        return AmazonProductIntelligenceProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            bundle=_merge_bundles(bundles),
        )

    async def _discover_asin(
        self,
        product: CanonicalProduct,
        *,
        marketplace_domain: str,
        target_region: str | None,
    ) -> str | None:
        response = await self._get(
            {
                "engine": "amazon",
                "k": _product_query(product),
                "amazon_domain": marketplace_domain,
                "output": "json",
                **(
                    {"shipping_location": target_region}
                    if target_region is not None
                    else {}
                ),
            }
        )
        try:
            parsed = _AmazonSearchResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise AmazonProductIntelligenceError(
                "SerpApi returned an invalid Amazon search response."
            ) from exc

        for result in parsed.organic_results:
            asin = _normalize_asin(result.asin)
            if asin is not None and _matches_product(product, result.title):
                return asin
        return None

    async def _fetch_product(
        self,
        *,
        asin: str,
        marketplace_domain: str,
        target_region: str | None,
    ) -> _AmazonProductResponse:
        response = await self._get(
            {
                "engine": "amazon_product",
                "asin": asin,
                "amazon_domain": marketplace_domain,
                "other_sellers": "true",
                "output": "json",
                **(
                    {"shipping_location": target_region}
                    if target_region is not None
                    else {}
                ),
            }
        )
        try:
            parsed = _AmazonProductResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise AmazonProductIntelligenceError(
                "SerpApi returned an invalid Amazon product response."
            ) from exc
        if not parsed.product_results:
            raise AmazonProductIntelligenceError(
                "SerpApi Amazon product response did not include product results."
            )
        return parsed

    async def _get(self, params: dict[str, str]) -> httpx.Response:
        request_params = {**params, "api_key": self._api_key}
        try:
            if self._client is not None:
                response = await self._client.get(
                    SERPAPI_SEARCH_URL,
                    params=request_params,
                    timeout=self._timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(
                    timeout=self._timeout_seconds
                ) as client:
                    response = await client.get(
                        SERPAPI_SEARCH_URL,
                        params=request_params,
                    )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise AmazonProductIntelligenceError(
                f"SerpApi Amazon request failed with HTTP {exc.response.status_code}."
            ) from exc
        except httpx.RequestError as exc:
            raise AmazonProductIntelligenceError(
                "SerpApi Amazon request failed."
            ) from exc
        return response

    def _gap_result(
        self,
        product: CanonicalProduct,
        *,
        summary: str,
        reason: str,
    ) -> AmazonProductIntelligenceProviderResult:
        return AmazonProductIntelligenceProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            bundle=AmazonProductEvidenceBundle(
                evidence_gaps=(
                    SourceEvidenceGap(
                        capability=(
                            SourceIntelligenceCapability.AMAZON_PRODUCT_LISTING_REVIEW
                        ),
                        target=EvidenceTarget(
                            target_type=EvidenceTargetType.PRODUCT,
                            product_id=product.product_id,
                        ),
                        summary=summary,
                        reason=reason,
                        source_quality=SourceQuality(
                            level=SourceQualityLevel.UNKNOWN
                        ),
                        confidence=_confidence(0.9, ConfidenceLevel.HIGH, reason),
                    ),
                )
            ),
        )


def _to_evidence_bundle(
    *,
    response: _AmazonProductResponse,
    product: CanonicalProduct,
    listing: ProductListing | None,
    requested_asin: str,
    requested_marketplace_domain: str,
    target_region: str | None,
    accessed_at: datetime,
) -> AmazonProductEvidenceBundle:
    data = response.product_results
    asin = _normalize_asin(data.get("asin")) or requested_asin
    marketplace_domain = _amazon_domain(
        _text(response.search_parameters.get("amazon_domain"))
    )
    marketplace_domain = marketplace_domain or requested_marketplace_domain
    listing_url = f"https://www.{marketplace_domain}/dp/{asin}"
    source_id = new_id()
    listing_id = listing.listing_id if listing is not None else new_id()
    title = _text(data.get("title")) or product.name
    seller, ship_from, delivery = _seller_context(response)
    fulfillment = _fulfillment_label(ship_from)
    review_count = _integer(data.get("reviews")) or _integer(
        _mapping(data.get("product_details")).get("review")
    )
    rating = _number(data.get("rating")) or _number(
        _mapping(data.get("product_details")).get("rating")
    )
    ships_to_region = _ships_to_region(data, delivery, target_region)
    variant_label, variant_warning = _variant_context(data.get("variants"), asin)
    quality = SourceQuality(
        level=SourceQualityLevel.ADEQUATE,
        score=0.76,
        rationale=(
            "Structured Amazon marketplace data returned by SerpApi; seller and "
            "review trust still require separate assessment."
        ),
    )
    source_reference = SourceReference(
        source_id=source_id,
        url=listing_url,
        title=title[:300],
        accessed_at=accessed_at,
    )
    listing_context = AmazonListingContext(
        source_id=source_id,
        marketplace_name="Amazon",
        marketplace_domain=marketplace_domain,
        marketplace_country_code=_MARKETPLACE_REGIONS.get(marketplace_domain),
        listing_url=listing_url,
        asin=asin,
        external_listing_id=asin,
        product_title=title[:300],
        variant_label=variant_label,
        seller_name=seller,
        fulfillment=fulfillment,
        ships_to_region_code=target_region,
        ships_to_region=ships_to_region,
        review_count=review_count,
        average_rating=rating,
    )

    return AmazonProductEvidenceCreator().create(
        (
            AmazonProductEvidenceInput(
                product_id=product.product_id,
                listing_id=listing_id,
                source_reference=source_reference,
                listing_context=listing_context,
                source_quality=quality,
                product_page_claim=_product_fact_summary(data),
                price_claim=_price_summary(data),
                review_summary_claim=_review_summary(
                    response,
                    rating,
                    review_count,
                ),
                review_quality_warnings=(
                    (variant_warning,) if variant_warning is not None else ()
                ),
            ),
        )
    )


def _merge_bundles(
    bundles: Iterable[AmazonProductEvidenceBundle],
) -> AmazonProductEvidenceBundle:
    source_references: list[SourceReference] = []
    listing_contexts: list[AmazonListingContext] = []
    evidence: list[AmazonProductEvidence] = []
    evidence_gaps: list[SourceEvidenceGap] = []
    for bundle in bundles:
        source_references.extend(bundle.source_references)
        listing_contexts.extend(bundle.listing_contexts)
        evidence.extend(bundle.evidence)
        evidence_gaps.extend(bundle.evidence_gaps)
    return AmazonProductEvidenceBundle(
        source_references=tuple(source_references),
        listing_contexts=tuple(listing_contexts),
        evidence=tuple(evidence),
        evidence_gaps=tuple(evidence_gaps),
    )


def _listing_targets(
    listings: tuple[ProductListing, ...],
) -> tuple[tuple[str, ProductListing, str], ...]:
    targets: list[tuple[str, ProductListing, str]] = []
    seen: set[tuple[str, str]] = set()
    for listing in listings:
        parsed = urlparse(str(listing.url))
        marketplace_domain = _amazon_domain(parsed.hostname)
        asin = _asin_from_url(str(listing.url))
        if marketplace_domain is None or asin is None:
            continue
        key = (marketplace_domain, asin)
        if key in seen:
            continue
        seen.add(key)
        targets.append((asin, listing, marketplace_domain))
    return tuple(targets)


def _amazon_domain(hostname: str | None) -> str | None:
    if hostname is None:
        return None
    normalized = hostname.casefold().removeprefix("www.")
    return normalized if normalized in _MARKETPLACE_REGIONS else None


def _asin_from_url(url: str) -> str | None:
    match = _ASIN_PATH_PATTERN.search(url)
    return _normalize_asin(match.group(1)) if match is not None else None


def _normalize_asin(value: Any) -> str | None:
    normalized = _text(value)
    if normalized is None:
        return None
    normalized = normalized.upper()
    return normalized if _ASIN_PATTERN.fullmatch(normalized) else None


def _marketplace_for_region(region_code: str | None) -> str:
    if region_code is None:
        return "amazon.com"
    return _REGION_MARKETPLACES.get(region_code, "amazon.com")


def _product_query(product: CanonicalProduct) -> str:
    return " ".join(
        dict.fromkeys(
            value.strip()
            for value in (product.brand, product.model, product.name)
            if value is not None and value.strip()
        )
    )


def _matches_product(product: CanonicalProduct, result_title: str) -> bool:
    normalized_title = result_title.casefold()
    if product.model is not None and product.model.casefold() not in normalized_title:
        return False
    desired_tokens = {
        token
        for token in _TOKEN_PATTERN.findall(_product_query(product).casefold())
        if token not in _MATCH_STOP_WORDS and len(token) > 1
    }
    if not desired_tokens:
        return True
    title_tokens = set(_TOKEN_PATTERN.findall(normalized_title))
    required_matches = min(2, len(desired_tokens))
    return len(desired_tokens & title_tokens) >= required_matches


def _seller_context(
    response: _AmazonProductResponse,
) -> tuple[str | None, str | None, tuple[str, ...]]:
    data = response.product_results
    offers = response.purchase_options or response.other_sellers
    offer = offers[0] if offers else {}
    seller = _text(data.get("sold_by")) or _text(offer.get("sold_by"))
    ship_from = _text(data.get("ships_from")) or _text(data.get("ship_from"))
    ship_from = ship_from or _text(offer.get("ship_from"))
    delivery = _text_values(data.get("delivery")) or _text_values(
        offer.get("delivery")
    )
    return seller, ship_from, delivery


def _fulfillment_label(ship_from: str | None) -> str | None:
    if ship_from is None:
        return None
    if "amazon" in ship_from.casefold():
        return f"Fulfilled or shipped by {ship_from}"
    return f"Ships from {ship_from}"


def _ships_to_region(
    data: Mapping[str, Any],
    delivery: tuple[str, ...],
    target_region: str | None,
) -> bool | None:
    if target_region is None:
        return None
    status_text = " ".join(
        value
        for value in (
            _text(data.get("availability")),
            *delivery,
        )
        if value is not None
    ).casefold()
    if not status_text:
        return None
    if any(
        marker in status_text
        for marker in (
            "cannot be shipped",
            "does not ship",
            "not deliverable",
            "unavailable for delivery",
            "currently unavailable",
        )
    ):
        return False
    if delivery or any(
        marker in status_text
        for marker in ("delivery", "deliver", "ships to", "in stock")
    ):
        return True
    return None


def _variant_context(value: Any, asin: str) -> tuple[str | None, str | None]:
    labels: list[str] = []
    variant_asins: set[str] = set()
    if isinstance(value, list):
        for group in value:
            if not isinstance(group, Mapping):
                continue
            title = _text(group.get("title"))
            items = group.get("items")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                item_asin = _normalize_asin(item.get("asin"))
                if item_asin is not None:
                    variant_asins.add(item_asin)
                if item_asin == asin or item.get("selected") is True:
                    name = _text(item.get("name"))
                    if name is not None:
                        labels.append(f"{title}: {name}" if title else name)
    warning = None
    if len(variant_asins) > 1:
        warning = (
            "Review totals or summaries may combine multiple Amazon variants; "
            "the selected ASIN must be checked before applying review claims."
        )
    return ("; ".join(labels)[:200] or None), warning


def _product_fact_summary(data: Mapping[str, Any]) -> str | None:
    parts: list[str] = []
    description = _text(data.get("description"))
    if description is not None:
        parts.append(description)
    about = _text_values(data.get("about_this_item")) or _text_values(
        data.get("feature_bullets")
    )
    parts.extend(about[:3])
    details = _mapping(data.get("product_details"))
    detail_parts = [
        f"{str(key).replace('_', ' ').title()}: {value}"
        for key, value in details.items()
        if key not in {"asin", "rating", "review"}
        and isinstance(value, (str, int, float))
    ]
    parts.extend(detail_parts[:5])
    if not parts:
        return None
    return "Amazon product page states: " + " ".join(parts)[:1965]


def _price_summary(data: Mapping[str, Any]) -> str | None:
    displayed = _text(data.get("price"))
    extracted = _number(data.get("extracted_price"))
    if displayed is not None:
        return f"Amazon displayed price: {displayed}."
    if extracted is not None:
        return f"Amazon displayed a numeric price of {extracted:g}; currency was not provided."
    return None


def _review_summary(
    response: _AmazonProductResponse,
    rating: float | None,
    review_count: int | None,
) -> str | None:
    parts: list[str] = []
    if rating is not None:
        rating_text = f"Average rating {rating:g} out of 5"
        if review_count is not None:
            rating_text += f" from {review_count:,} reviews"
        parts.append(rating_text + ".")
    elif review_count is not None:
        parts.append(f"Amazon reported {review_count:,} reviews.")

    review_info = response.reviews_information
    for key in ("reviews_summary", "customers_say", "review_aspects"):
        value = review_info.get(key)
        summaries = _summary_values(value)
        if summaries:
            parts.append(" ".join(summaries[:3]))
            break
    if not parts:
        return None
    return " ".join(parts)[:2000]


def _summary_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        normalized = value.strip()
        return (normalized,) if normalized else ()
    if isinstance(value, Mapping):
        summary = _text(value.get("summary"))
        return (summary,) if summary is not None else ()
    if not isinstance(value, list):
        return ()
    summaries: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            summaries.append(item.strip())
        elif isinstance(item, Mapping):
            title = _text(item.get("title"))
            summary = _text(item.get("summary"))
            sentiment = _text(item.get("sentiment"))
            if summary is not None:
                prefix = f"{title} ({sentiment}): " if title and sentiment else ""
                summaries.append(prefix + summary)
    return tuple(summaries)


def _confidence(
    score: float,
    level: ConfidenceLevel,
    rationale: str,
) -> Confidence:
    return Confidence(score=score, level=level, rationale=rationale)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _text_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        normalized = value.strip()
        return (normalized,) if normalized else ()
    if not isinstance(value, list):
        return ()
    return tuple(
        normalized
        for item in value
        if isinstance(item, str) and (normalized := item.strip())
    )


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        normalized = re.sub(r"[^0-9]", "", value)
        return int(normalized) if normalized else None
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"\d+(?:\.\d+)?", value.replace(",", ""))
        return float(match.group()) if match is not None else None
    return None
