import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import SourceId
from app.schemas.money import Money
from app.schemas.products import (
    CanonicalProduct,
    ListingAvailabilityStatus,
    ListingExtractionMissingField,
    ProductListing,
    ProductListingExtraction,
    RegionAvailability,
    SellerProfile,
)
from app.schemas.search_sources import (
    ExtractionStatus,
    SearchResult,
    SourceSnapshot,
    SourceType,
)


_LISTING_PAGE_TYPES = frozenset(
    {
        SourceType.PRODUCT_PAGE,
        SourceType.RETAILER_LISTING,
        SourceType.OFFICIAL_BRAND_PAGE,
    }
)
_REGION_CURRENCIES = {
    "AU": "AUD",
    "CA": "CAD",
    "CN": "CNY",
    "DE": "EUR",
    "ES": "EUR",
    "FR": "EUR",
    "GB": "GBP",
    "IN": "INR",
    "IT": "EUR",
    "JP": "JPY",
    "KR": "KRW",
    "HK": "HKD",
    "MO": "MOP",
    "MX": "MXN",
    "NZ": "NZD",
    "PH": "PHP",
    "SG": "SGD",
    "TW": "TWD",
    "US": "USD",
}
_CURRENCY_SYMBOLS = {
    "A$": "AUD",
    "C$": "CAD",
    "HK$": "HKD",
    "MOP$": "MOP",
    "NT$": "TWD",
    "NZ$": "NZD",
    "S$": "SGD",
    "₱": "PHP",
    "£": "GBP",
    "€": "EUR",
    "₹": "INR",
    "₩": "KRW",
}
_KNOWN_CURRENCIES = frozenset({*_REGION_CURRENCIES.values(), "BRL"})
_PRICE_CODE_FIRST = re.compile(
    r"\b(?P<currency>[A-Z]{3})\s*(?P<amount>\d[\d,]*(?:\.\d{1,2})?)\b"
)
_PRICE_CODE_LAST = re.compile(
    r"\b(?P<amount>\d[\d,]*(?:\.\d{1,2})?)\s*(?P<currency>[A-Z]{3})\b"
)
_PRICE_SYMBOL = re.compile(
    r"(?P<symbol>HK\$|MOP\$|NT\$|NZ\$|A\$|C\$|S\$|[$₱£€¥₹₩])\s*"
    r"(?P<amount>\d[\d,]*(?:\.\d{1,2})?)"
)


class ProductListingExtractionError(ValueError):
    """Raised when a source cannot identify a product listing."""


@dataclass(frozen=True)
class _ExtractionFields:
    title: str
    brand: str | None
    price: Money | None
    seller_name: str
    seller_was_explicit: bool
    region_codes: tuple[str, ...]


class ProductListingExtractor:
    """Normalize deterministic listing fields without model or provider calls."""

    def extract_search_result(
        self,
        result: SearchResult,
    ) -> ProductListingExtraction:
        text = "\n".join(value for value in (result.title, result.snippet) if value)
        region_codes = _region_codes(
            text,
            result.query.region_code,
            result.provider.raw.get("target_region_code"),
        )
        fields = _extract_fields(
            title=result.title,
            text=text,
            url=str(result.url),
            site_name=None,
            region_codes=region_codes,
        )
        return _build_extraction(
            fields, source_id=result.source_id, url=str(result.url)
        )

    def extract_source_snapshot(
        self,
        snapshot: SourceSnapshot,
    ) -> ProductListingExtraction:
        if snapshot.source_type not in _LISTING_PAGE_TYPES:
            raise ProductListingExtractionError(
                "product listing extraction requires a product or retailer page."
            )
        if snapshot.extracted_content is None:
            raise ProductListingExtractionError(
                "product listing extraction requires extracted page content."
            )
        if snapshot.extraction_status not in {
            ExtractionStatus.SUCCEEDED,
            ExtractionStatus.PARTIAL,
        }:
            raise ProductListingExtractionError(
                "product listing extraction requires usable extracted page content."
            )
        title = snapshot.title
        if title is None:
            raise ProductListingExtractionError(
                "product listing extraction requires a page title."
            )
        content = snapshot.extracted_content
        text = "\n".join(
            value for value in (title, content.description, content.text) if value
        )
        region_codes = _region_codes(
            text,
            snapshot.provider.raw.get("target_region_code"),
        )
        fields = _extract_fields(
            title=title,
            text=text,
            url=str(snapshot.url),
            site_name=content.site_name,
            region_codes=region_codes,
        )
        return _build_extraction(
            fields,
            source_id=snapshot.source_id,
            url=str(snapshot.url),
        )


def _extract_fields(
    *,
    title: str,
    text: str,
    url: str,
    site_name: str | None,
    region_codes: tuple[str, ...],
) -> _ExtractionFields:
    seller_name = _labeled_value(text, ("sold by", "seller", "store", "retailer"))
    seller_was_explicit = seller_name is not None or site_name is not None
    return _ExtractionFields(
        title=title.strip(),
        brand=_labeled_value(text, ("brand", "manufacturer")),
        price=_price(text, region_codes),
        seller_name=seller_name or site_name or _hostname(url),
        seller_was_explicit=seller_was_explicit,
        region_codes=region_codes,
    )


def _build_extraction(
    fields: _ExtractionFields,
    *,
    source_id: SourceId,
    url: str,
) -> ProductListingExtraction:
    product = CanonicalProduct(
        name=fields.title,
        brand=fields.brand,
        source_ids=(source_id,),
    )
    listing = ProductListing(
        product_id=product.product_id,
        title=fields.title,
        url=url,
        seller=SellerProfile(
            seller_name=fields.seller_name,
            source_ids=(source_id,),
        ),
        price=fields.price,
        region_availability=tuple(
            RegionAvailability(
                region_code=region_code,
                status=ListingAvailabilityStatus.UNKNOWN,
                source_ids=(source_id,),
            )
            for region_code in fields.region_codes
        ),
        source_ids=(source_id,),
    )
    missing = _missing_fields(fields)
    return ProductListingExtraction(
        product=product,
        listing=listing,
        missing_data_flags=missing,
        confidence=_confidence(fields, missing),
    )


def _labeled_value(text: str, labels: tuple[str, ...]) -> str | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?i)(?:^|[\n.;])\s*(?:{label_pattern})\s*:\s*"
        r"(?P<value>[^\n|]{1,200}?)"
        r"(?=(?:[.;]\s*[A-Za-z][A-Za-z ]{0,20}\s*:)|\n|\||$)",
        text,
    )
    if match is None:
        return None
    value = " ".join(match.group("value").split()).strip(" -.;")
    return value or None


def _price(text: str, region_codes: tuple[str, ...]) -> Money | None:
    price_context = _labeled_value(text, ("price", "sale price", "current price"))
    candidates = (price_context,) if price_context is not None else (text,)
    for candidate in candidates:
        for pattern in (_PRICE_CODE_FIRST, _PRICE_CODE_LAST):
            match = pattern.search(candidate)
            if match is not None and match.group("currency") in _KNOWN_CURRENCIES:
                return _money(match.group("amount"), match.group("currency"))
        match = _PRICE_SYMBOL.search(candidate)
        if match is not None:
            currency = _symbol_currency(match.group("symbol"), region_codes)
            if currency is not None:
                return _money(match.group("amount"), currency)
    return None


def _money(amount: str, currency: str) -> Money | None:
    try:
        return Money(amount=Decimal(amount.replace(",", "")), currency=currency)
    except (InvalidOperation, ValueError):
        return None


def _symbol_currency(symbol: str, region_codes: tuple[str, ...]) -> str | None:
    if symbol in _CURRENCY_SYMBOLS:
        return _CURRENCY_SYMBOLS[symbol]
    if symbol not in {"$", "¥"}:
        return None
    currencies = {
        _REGION_CURRENCIES[region]
        for region in region_codes
        if region in _REGION_CURRENCIES
    }
    if symbol == "¥":
        currencies &= {"CNY", "JPY"}
    return currencies.pop() if len(currencies) == 1 else None


def _region_codes(text: str, *metadata_values: object) -> tuple[str, ...]:
    candidates: list[str] = []
    for value in metadata_values:
        if isinstance(value, str):
            candidates.append(value)
    region_value = _labeled_value(
        text,
        ("region", "available in", "ships to", "country"),
    )
    if region_value is not None:
        candidates.extend(re.findall(r"\b[A-Za-z]{2}\b", region_value))
    return tuple(
        dict.fromkeys(
            candidate.strip().upper()
            for candidate in candidates
            if re.fullmatch(r"[A-Za-z]{2}", candidate.strip())
        )
    )


def _hostname(url: str) -> str:
    hostname = urlparse(url).hostname
    if hostname is None:
        raise ProductListingExtractionError("product listing URL requires a hostname.")
    return hostname.removeprefix("www.")


def _missing_fields(
    fields: _ExtractionFields,
) -> tuple[ListingExtractionMissingField, ...]:
    missing: list[ListingExtractionMissingField] = []
    if fields.brand is None:
        missing.append(ListingExtractionMissingField.BRAND)
    if fields.price is None:
        missing.extend(
            (
                ListingExtractionMissingField.PRICE,
                ListingExtractionMissingField.CURRENCY,
            )
        )
    if not fields.seller_was_explicit:
        missing.append(ListingExtractionMissingField.SELLER_STORE)
    if not fields.region_codes:
        missing.append(ListingExtractionMissingField.REGION)
    return tuple(missing)


def _confidence(
    fields: _ExtractionFields,
    missing: tuple[ListingExtractionMissingField, ...],
) -> Confidence:
    score = 0.4
    score += 0.15 if fields.brand is not None else 0.0
    score += 0.2 if fields.price is not None else 0.0
    score += 0.15 if fields.seller_was_explicit else 0.0
    score += 0.1 if fields.region_codes else 0.0
    level = (
        ConfidenceLevel.HIGH
        if score >= 0.8
        else ConfidenceLevel.MEDIUM
        if score >= 0.55
        else ConfidenceLevel.LOW
    )
    missing_names = ", ".join(field.value for field in missing)
    rationale = (
        "Deterministic listing fields were found for title, brand, price, seller, "
        "and region."
        if not missing
        else f"Deterministic extraction is missing: {missing_names}."
    )
    return Confidence(score=round(score, 2), level=level, rationale=rationale)
