from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from app.core.ikea_regions import IKEA_REGION_PATHS
from app.providers.contracts import (
    IKEAStoreIntelligenceProviderOptions,
    IKEAStoreIntelligenceProviderResult,
    ProviderCapabilityFlags,
    ProviderRunStatus,
    SearchProvider,
    SearchProviderOptions,
    SourceAllowAvoidPolicy,
    SourcePolicyAction,
    SourcePolicyRule,
)
from app.providers.source_quality import (
    REGION_CURRENCIES,
    SourceEvidenceContext,
    SourceQualityMetadata,
    normalize_source_url,
    score_source_quality,
)
from app.schemas.money import Money
from app.schemas.products import CanonicalProduct
from app.schemas.search_sources import (
    EvidenceTarget,
    EvidenceTargetType,
    IKEAStoreContext,
    IKEAStoreEvidenceBundle,
    RegionalStoreAvailability,
    SearchIntent,
    SearchQuery,
    SearchResult,
    SourceEvidenceGap,
    SourceIntelligenceCapability,
    SourceQuality,
    SourceQualityLevel,
    SourceType,
)
from app.schemas.source_references import SourceReference
from app.services.ikea_evidence_creation import (
    IKEAStoreEvidenceCreator,
    IKEAStoreEvidenceInput,
)


MAX_IKEA_RESULTS = 5
_PRODUCT_CODE_PATTERN = re.compile(r"(?<!\d)(\d{8})(?!\d)")
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_PRICE_PATTERN = re.compile(
    r"\b(?P<currency>[A-Z]{3})\s*(?P<amount>\d[\d,]*(?:\.\d{1,2})?)\b"
)
_MATCH_STOP_WORDS = {"a", "and", "for", "ikea", "of", "the", "with"}


@dataclass(frozen=True)
class _RegionalIKEAStore:
    country_code: str
    domain: str
    path_prefix: str


class IKEARegionalStoreDiscoveryProvider:
    provider_name = "ikea-regional-store-search"

    def __init__(self, *, search_provider: SearchProvider) -> None:
        self._search_provider = search_provider

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name=self.provider_name,
            supports_domain_scoped_search=True,
            supports_official_store_lookup=True,
            supports_ikea_regional_store_lookup=True,
            supports_ikea_product_pages=True,
            supports_ikea_store_delivery_context=True,
            compliance_notes=(
                "Uses the configured general search provider with official IKEA scope.",
                "Only official URLs matching the requested country or region are accepted.",
                "Search metadata is used without directly scraping IKEA pages.",
                "Availability and delivery evidence never imply global shipping.",
            ),
        )

    async def fetch_store_evidence(
        self,
        product: CanonicalProduct,
        options: IKEAStoreIntelligenceProviderOptions | None = None,
    ) -> IKEAStoreIntelligenceProviderResult:
        provider_options = options or IKEAStoreIntelligenceProviderOptions()
        target_region = provider_options.region_code
        store = _regional_store(target_region)
        if store is None:
            return self._region_gap_result(product, target_region)

        search_query = SearchQuery(
            query=_ikea_scoped_query(product, store),
            intent=SearchIntent.OFFICIAL_SOURCE,
            region_code=store.country_code,
            required_source_types=(SourceType.OFFICIAL_BRAND_PAGE,),
        )
        results = await self._search_provider.search(
            search_query,
            SearchProviderOptions(
                region_code=store.country_code,
                max_results=MAX_IKEA_RESULTS,
                source_policy=_ikea_source_policy(
                    provider_options.source_policy,
                    store.domain,
                ),
            ),
        )
        bundle = _to_evidence_bundle(
            product=product,
            store=store,
            results=results,
        )
        return IKEAStoreIntelligenceProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            bundle=bundle,
            notes=(
                "IKEA price, stock, pickup, and delivery evidence is region-specific.",
            ),
        )

    def _region_gap_result(
        self,
        product: CanonicalProduct,
        target_region: str | None,
    ) -> IKEAStoreIntelligenceProviderResult:
        if target_region is None:
            target = EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            )
            summary = "IKEA regional relevance could not be checked without a region."
            reason = "No target country or region was supplied."
        else:
            target = EvidenceTarget(
                target_type=EvidenceTargetType.REGION,
                region_code=target_region,
            )
            summary = f"No supported IKEA regional presence is configured for {target_region}."
            reason = (
                "The IKEA regional source catalog has no official country or region "
                "path for this target."
            )
        return IKEAStoreIntelligenceProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            bundle=IKEAStoreEvidenceCreator().create(
                (),
                evidence_gaps=(
                    SourceEvidenceGap(
                        capability=(
                            SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE
                        ),
                        target=target,
                        summary=summary,
                        reason=reason,
                        source_quality=SourceQuality(
                            level=SourceQualityLevel.UNKNOWN
                        ),
                    ),
                ),
            ),
        )


def _regional_store(region_code: str | None) -> _RegionalIKEAStore | None:
    if region_code is None:
        return None
    regional_path = IKEA_REGION_PATHS.get(region_code)
    if regional_path is None:
        return None
    return _RegionalIKEAStore(
        country_code=region_code,
        domain=regional_path[0],
        path_prefix=regional_path[1],
    )


def _ikea_scoped_query(
    product: CanonicalProduct,
    store: _RegionalIKEAStore,
) -> str:
    query_parts: list[str] = []
    for value in (product.name, product.model, product.brand):
        if value is None or not value.strip():
            continue
        candidate = value.strip()
        if candidate.casefold() not in " ".join(query_parts).casefold():
            query_parts.append(candidate)
    if "ikea" not in {token.casefold() for token in query_parts}:
        query_parts.append("IKEA")
    product_query = " ".join(query_parts)
    scope = f"site:{store.domain}{store.path_prefix}"
    return f"{product_query} {scope}"[:500]


def _ikea_source_policy(
    policy: SourceAllowAvoidPolicy,
    domain: str,
) -> SourceAllowAvoidPolicy:
    return SourceAllowAvoidPolicy(
        allow=(
            SourcePolicyRule(
                action=SourcePolicyAction.ALLOW,
                domain=domain,
                reason="IKEA discovery is restricted to the official regional domain.",
            ),
        ),
        avoid=policy.avoid,
    )


def _to_evidence_bundle(
    *,
    product: CanonicalProduct,
    store: _RegionalIKEAStore,
    results: tuple[SearchResult, ...],
) -> IKEAStoreEvidenceBundle:
    inputs: list[IKEAStoreEvidenceInput] = []
    gaps: list[SourceEvidenceGap] = []

    for result in results:
        normalized_url, domain = normalize_source_url(str(result.url))
        if not _matches_regional_store(normalized_url, domain, store):
            continue
        searchable = ". ".join(filter(None, (result.title, result.snippet)))
        if not _matches_product(product, searchable):
            continue

        price = _extract_price(searchable, store.country_code)
        availability = _availability_from_text(searchable)
        delivery_area = _delivery_context(searchable)
        product_code = _product_code(normalized_url, searchable)
        quality = score_source_quality(
            normalized_url,
            SourceQualityMetadata(
                target_region_code=store.country_code,
                source_region_code=store.country_code,
                currency=price.currency if price is not None else None,
                ships_to_target_region=(
                    True
                    if availability == RegionalStoreAvailability.AVAILABLE
                    else False
                    if availability
                    in {
                        RegionalStoreAvailability.DELIVERY_UNAVAILABLE,
                        RegionalStoreAvailability.PICKUP_ONLY,
                    }
                    else None
                ),
                evidence_context=SourceEvidenceContext.PURCHASE,
                official_store_verified=True,
                sold_by_domain_owner=True,
                product_identity_consistent=True,
            ),
        ).quality
        source_reference = SourceReference(
            source_id=result.source_id,
            url=normalized_url,
            title=result.title,
        )
        store_context = IKEAStoreContext(
            source_id=result.source_id,
            country_code=store.country_code,
            official_url=normalized_url,
            product_code=product_code,
            product_name=_product_title(result.title),
            store_name=_store_name(searchable),
            delivery_area=delivery_area,
            price=price,
            availability=availability,
        )
        inputs.append(
            IKEAStoreEvidenceInput(
                product_id=product.product_id,
                source_reference=source_reference,
                store_context=store_context,
                source_quality=quality,
                product_page_claim=_product_fact_claim(result, product_code),
            )
        )

    if not inputs:
        gaps.append(
            SourceEvidenceGap(
                capability=SourceIntelligenceCapability.IKEA_REGIONAL_OFFICIAL_STORE,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.REGION,
                    region_code=store.country_code,
                ),
                summary="No matching official IKEA product was found for the region.",
                reason=(
                    "Regional official-store search returned no product result with a "
                    "matching IKEA domain, country path, and product identity."
                ),
            )
        )

    return IKEAStoreEvidenceCreator().create(
        tuple(inputs),
        evidence_gaps=tuple(gaps),
    )


def _matches_regional_store(
    normalized_url: str,
    domain: str,
    store: _RegionalIKEAStore,
) -> bool:
    path = urlsplit(normalized_url).path.casefold().rstrip("/")
    expected_path = store.path_prefix.casefold().rstrip("/")
    return (
        (domain == store.domain or domain.endswith(f".{store.domain}"))
        and (not expected_path or path.startswith(expected_path))
        and "/p/" in path
    )


def _matches_product(product: CanonicalProduct, text: str) -> bool:
    searchable_tokens = set(_TOKEN_PATTERN.findall(text.casefold()))
    requested_tokens = {
        token
        for token in _TOKEN_PATTERN.findall(
            " ".join(filter(None, (product.model, product.name))).casefold()
        )
        if token not in _MATCH_STOP_WORDS
    }
    return bool(requested_tokens) and requested_tokens.issubset(searchable_tokens)


def _extract_price(text: str, region_code: str) -> Money | None:
    expected_currency = REGION_CURRENCIES.get(region_code)
    for match in _PRICE_PATTERN.finditer(text.upper()):
        currency = match.group("currency")
        if expected_currency is not None and currency != expected_currency:
            continue
        try:
            amount = Decimal(match.group("amount").replace(",", ""))
        except InvalidOperation:
            continue
        return Money(amount=amount, currency=currency)
    return None


def _availability_from_text(text: str) -> RegionalStoreAvailability:
    normalized = " ".join(text.casefold().split())
    if any(marker in normalized for marker in ("out of stock", "currently unavailable")):
        return RegionalStoreAvailability.OUT_OF_STOCK
    if "pickup only" in normalized or "collection only" in normalized:
        return RegionalStoreAvailability.PICKUP_ONLY
    if any(
        marker in normalized
        for marker in ("delivery unavailable", "not available for delivery")
    ):
        return RegionalStoreAvailability.DELIVERY_UNAVAILABLE
    if any(
        marker in normalized
        for marker in ("available for delivery", "available online", "in stock")
    ):
        return RegionalStoreAvailability.AVAILABLE
    return RegionalStoreAvailability.UNKNOWN


def _delivery_context(text: str) -> str | None:
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        if any(
            marker in sentence.casefold()
            for marker in ("delivery", "pickup", "pick-up", "collection", "store")
        ):
            return sentence.strip()[:200]
    return None


def _store_name(text: str) -> str | None:
    match = re.search(r"\b(IKEA\s+[A-Z][A-Za-z -]{1,60})\s+store\b", text)
    if match is None:
        return None
    return match.group(1).strip()


def _product_code(url: str, text: str) -> str | None:
    match = _PRODUCT_CODE_PATTERN.search(f"{url} {text}")
    if match is None:
        return None
    digits = match.group(1)
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:]}"


def _product_title(title: str) -> str:
    return re.sub(r"\s*[-|]\s*IKEA.*$", "", title, flags=re.IGNORECASE).strip()


def _product_fact_claim(result: SearchResult, product_code: str | None) -> str:
    code = f" Product number: {product_code}." if product_code is not None else ""
    return f"Official IKEA product page: {result.title}.{code}"[:2000]
