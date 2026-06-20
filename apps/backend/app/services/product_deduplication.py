import re
from difflib import SequenceMatcher
from dataclasses import dataclass, field
from enum import StrEnum
from collections.abc import Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit

from app.providers.source_quality import normalize_source_url
from app.schemas.products import CanonicalProduct, ProductListing, ProductListingExtraction


class DeterministicMatchKind(StrEnum):
    CANONICAL_URL = "canonical_url"
    RETAILER_ID = "retailer_id"
    SKU = "sku"
    UPC = "upc"
    EAN = "ean"
    BRAND_MODEL = "brand_model"
    FUZZY_TITLE_SPECS = "fuzzy_title_specs"


class FuzzyProductMatchOutcome(StrEnum):
    SAME_PRODUCT = "same_product"
    SAME_FAMILY = "same_family"
    UNCERTAIN = "uncertain"
    DIFFERENT_PRODUCT = "different_product"


@dataclass(frozen=True)
class DeterministicMatchEvidence:
    kind: DeterministicMatchKind
    value: str
    rationale: str


@dataclass(frozen=True)
class FuzzyProductMatchDecision:
    left_product_id: object
    right_product_id: object
    outcome: FuzzyProductMatchOutcome
    confidence: float
    title_similarity: float
    spec_similarity: float | None
    shared_spec_tokens: tuple[str, ...] = ()
    conflicting_spec_tokens: tuple[str, ...] = ()
    rationale: str = ""


@dataclass(frozen=True)
class DeterministicProductGroup:
    product: CanonicalProduct
    listings: tuple[ProductListing, ...]
    match_evidence: tuple[DeterministicMatchEvidence, ...] = ()


@dataclass(frozen=True)
class DeterministicDeduplicationResult:
    groups: tuple[DeterministicProductGroup, ...]
    fuzzy_decisions: tuple[FuzzyProductMatchDecision, ...] = ()

    @property
    def listings(self) -> tuple[ProductListing, ...]:
        return tuple(listing for group in self.groups for listing in group.listings)

    @property
    def collapsed_count(self) -> int:
        return len(self.listings) - len(self.groups)


@dataclass
class _MutableProductGroup:
    product: CanonicalProduct
    listings: list[ProductListing] = field(default_factory=list)
    match_evidence: list[DeterministicMatchEvidence] = field(default_factory=list)


_ASIN_PATH_PATTERN = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", re.I)
_IKEA_PRODUCT_CODE_PATTERN = re.compile(r"-(\d{8})(?:[/?]|$)")
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_SPEC_UNIT_PATTERN = re.compile(
    r"\b(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>"
    r"inches|inch|in|cm|mm|hz|khz|w|kw|gb|tb|mah|mp"
    r")\b",
    re.I,
)
_RESOLUTION_PATTERN = re.compile(r"\b(?:\d{3,4}p|[48]k)\b", re.I)
_PATH_ID_MARKERS = frozenset({"dp", "gp", "product", "products", "item", "items", "p"})
_QUERY_ID_KEYS = frozenset(
    {
        "asin",
        "ean",
        "gtin",
        "id",
        "item",
        "itemid",
        "model",
        "pid",
        "product",
        "productid",
        "sku",
        "skuid",
        "upc",
    }
)
_TITLE_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "by",
        "for",
        "from",
        "in",
        "inch",
        "inches",
        "new",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
    }
)
_COLOR_SPEC_WORDS = frozenset(
    {
        "black",
        "blue",
        "gold",
        "gray",
        "green",
        "grey",
        "pink",
        "purple",
        "red",
        "silver",
        "white",
        "yellow",
    }
)
_SAME_PRODUCT_MIN_CONFIDENCE = 0.9
_SAME_FAMILY_MIN_TITLE_SIMILARITY = 0.52
_UNCERTAIN_MIN_TITLE_SIMILARITY = 0.68


class DeterministicProductDeduplicator:
    """Collapse only high-confidence product/listing matches with auditable evidence."""

    def group(
        self,
        extractions: Sequence[ProductListingExtraction],
    ) -> DeterministicDeduplicationResult:
        groups: list[_MutableProductGroup] = []
        fuzzy_decisions: list[FuzzyProductMatchDecision] = []
        for extraction in extractions:
            listing = _listing_with_canonical_identity(extraction.listing)
            matched = False
            for group in groups:
                evidence = _match_evidence(extraction.product, listing, group)
                if evidence is None:
                    continue
                grouped_listing = _copy_listing(
                    listing,
                    product_id=group.product.product_id,
                )
                group.listings.append(grouped_listing)
                group.match_evidence.append(evidence)
                group.product = _merge_product_identity(
                    group.product,
                    extraction.product,
                    tuple(item.listing_id for item in group.listings),
                )
                matched = True
                break
            if not matched:
                fuzzy_match: (
                    tuple[_MutableProductGroup, FuzzyProductMatchDecision] | None
                ) = None
                for group in groups:
                    decision = _fuzzy_product_match_decision(
                        extraction.product,
                        listing,
                        group.product,
                        group.listings[0],
                    )
                    fuzzy_decisions.append(decision)
                    if decision.outcome != FuzzyProductMatchOutcome.SAME_PRODUCT:
                        continue
                    if (
                        fuzzy_match is None
                        or decision.confidence > fuzzy_match[1].confidence
                    ):
                        fuzzy_match = (group, decision)
                if fuzzy_match is not None:
                    group, decision = fuzzy_match
                    grouped_listing = _copy_listing(
                        listing,
                        product_id=group.product.product_id,
                    )
                    group.listings.append(grouped_listing)
                    group.match_evidence.append(
                        DeterministicMatchEvidence(
                            kind=DeterministicMatchKind.FUZZY_TITLE_SPECS,
                            value=f"{decision.confidence:.3f}",
                            rationale=decision.rationale,
                        )
                    )
                    group.product = _merge_product_identity(
                        group.product,
                        extraction.product,
                        tuple(item.listing_id for item in group.listings),
                    )
                    matched = True
            if not matched:
                product = _merge_product_identity(
                    extraction.product,
                    extraction.product,
                    (listing.listing_id,),
                )
                groups.append(_MutableProductGroup(product=product, listings=[listing]))
        return DeterministicDeduplicationResult(
            groups=tuple(
                DeterministicProductGroup(
                    product=group.product,
                    listings=tuple(group.listings),
                    match_evidence=tuple(group.match_evidence),
                )
                for group in groups
            ),
            fuzzy_decisions=tuple(fuzzy_decisions),
        )


def canonical_listing_url(url: str) -> str:
    normalized, _domain = normalize_source_url(url)
    parsed = urlsplit(normalized)
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return parsed._replace(path=path, query=query).geturl()


def _listing_with_canonical_identity(listing: ProductListing) -> ProductListing:
    updates: dict[str, object] = {}
    if listing.canonical_url is None:
        updates["canonical_url"] = canonical_listing_url(str(listing.url))
    if listing.retailer_id is None:
        retailer_id = _retailer_id(str(listing.url))
        if retailer_id is not None:
            updates["retailer_id"] = retailer_id
    return _copy_listing(listing, **updates) if updates else listing


def _match_evidence(
    incoming_product: CanonicalProduct,
    incoming_listing: ProductListing,
    group: _MutableProductGroup,
) -> DeterministicMatchEvidence | None:
    incoming_url = _normalized_url_value(incoming_listing)
    if incoming_url is not None:
        for listing in group.listings:
            if incoming_url == _normalized_url_value(listing):
                return DeterministicMatchEvidence(
                    kind=DeterministicMatchKind.CANONICAL_URL,
                    value=incoming_url,
                    rationale="Listings have the same canonical URL after removing tracking parameters.",
                )

    incoming_retailer = _retailer_key(incoming_listing)
    if incoming_retailer is not None:
        for listing in group.listings:
            if incoming_retailer == _retailer_key(listing):
                return DeterministicMatchEvidence(
                    kind=DeterministicMatchKind.RETAILER_ID,
                    value=":".join(incoming_retailer),
                    rationale="Listings share the same retailer domain and retailer product identifier.",
                )

    for kind in (DeterministicMatchKind.UPC, DeterministicMatchKind.EAN):
        incoming_identifiers = _identifier_values(kind, incoming_product, incoming_listing)
        if not incoming_identifiers:
            continue
        for listing in group.listings:
            group_identifiers = _identifier_values(kind, group.product, listing)
            match = incoming_identifiers & group_identifiers
            if match:
                value = sorted(match)[0]
                return DeterministicMatchEvidence(
                    kind=kind,
                    value=value,
                    rationale=f"Products share the same exact {kind.value.upper()} identifier.",
                )

    incoming_sku = _identifier_values(
        DeterministicMatchKind.SKU,
        incoming_product,
        incoming_listing,
    )
    if incoming_sku:
        for listing in group.listings:
            group_sku = _identifier_values(
                DeterministicMatchKind.SKU,
                group.product,
                listing,
            )
            match = incoming_sku & group_sku
            if match and (
                _same_retailer_domain(incoming_listing, listing)
                or _same_exact_brand(incoming_product, group.product)
            ):
                value = sorted(match)[0]
                return DeterministicMatchEvidence(
                    kind=DeterministicMatchKind.SKU,
                    value=value,
                    rationale="Products share an exact SKU with the same retailer domain or exact brand.",
                )

    incoming_brand_model = _brand_model_key(incoming_product)
    group_brand_model = _brand_model_key(group.product)
    if incoming_brand_model is not None and incoming_brand_model == group_brand_model:
        return DeterministicMatchEvidence(
            kind=DeterministicMatchKind.BRAND_MODEL,
            value=":".join(incoming_brand_model),
            rationale="Products have the same exact normalized brand and model.",
        )
    return None


def _identifier_values(
    kind: DeterministicMatchKind,
    product: CanonicalProduct,
    listing: ProductListing,
) -> set[str]:
    if kind == DeterministicMatchKind.SKU:
        return _normalized_values(product.sku, listing.sku)
    if kind == DeterministicMatchKind.UPC:
        return _normalized_gtins(product.upc, listing.upc)
    if kind == DeterministicMatchKind.EAN:
        return _normalized_gtins(product.ean, listing.ean)
    return set()


def _normalized_values(*values: str | None) -> set[str]:
    return {
        normalized
        for value in values
        if value is not None
        if (normalized := _normalize_identifier(value)) is not None
    }


def _normalized_gtins(*values: str | None) -> set[str]:
    return {
        normalized
        for value in values
        if value is not None
        if (normalized := _normalize_gtin(value)) is not None
    }


def _normalize_identifier(value: str) -> str | None:
    normalized = re.sub(r"[^A-Z0-9]+", "", value.upper())
    return normalized or None


def _normalize_gtin(value: str) -> str | None:
    digits = re.sub(r"\D+", "", value)
    return digits if digits else None


def _same_exact_brand(left: CanonicalProduct, right: CanonicalProduct) -> bool:
    left_brand = _normalize_text(left.brand)
    right_brand = _normalize_text(right.brand)
    return left_brand is not None and left_brand == right_brand


def _brand_model_key(product: CanonicalProduct) -> tuple[str, str] | None:
    brand = _normalize_text(product.brand)
    model = _normalize_text(product.model)
    if brand is None or model is None:
        return None
    return brand, model


def _fuzzy_product_match_decision(
    incoming_product: CanonicalProduct,
    incoming_listing: ProductListing,
    group_product: CanonicalProduct,
    group_listing: ProductListing,
) -> FuzzyProductMatchDecision:
    incoming_title = _normalized_match_text(incoming_product, incoming_listing)
    group_title = _normalized_match_text(group_product, group_listing)
    incoming_tokens = _title_tokens(incoming_title)
    group_tokens = _title_tokens(group_title)
    title_similarity = _title_similarity(
        incoming_title,
        group_title,
        incoming_tokens,
        group_tokens,
    )
    incoming_specs = _spec_tokens(incoming_title)
    group_specs = _spec_tokens(group_title)
    shared_specs = tuple(sorted(set(incoming_specs) & set(group_specs)))
    conflicting_specs = _conflicting_spec_tokens(incoming_specs, group_specs)
    spec_similarity = _spec_similarity(incoming_specs, group_specs)

    brand_conflict = _known_brand_conflict(incoming_product, group_product)
    same_known_brand = _same_exact_brand(incoming_product, group_product)
    model_conflict = _known_model_conflict(incoming_product, group_product)
    has_spec_gap = bool(incoming_specs) != bool(group_specs)
    has_specs = bool(incoming_specs and group_specs)
    has_conflict = bool(conflicting_specs or brand_conflict or model_conflict)

    if brand_conflict:
        return _fuzzy_decision(
            incoming_product,
            group_product,
            FuzzyProductMatchOutcome.DIFFERENT_PRODUCT,
            min(title_similarity, 0.25),
            title_similarity,
            spec_similarity,
            shared_specs,
            conflicting_specs,
            "Known brands differ, so fuzzy title similarity is not enough to group these products.",
        )

    if (
        not has_conflict
        and title_similarity >= 0.88
        and (
            (has_specs and spec_similarity is not None and spec_similarity >= 0.8)
            or (not has_specs and same_known_brand and title_similarity >= 0.95)
        )
    ):
        confidence = min(
            0.99,
            0.55 * title_similarity
            + 0.35 * (spec_similarity if spec_similarity is not None else 1.0)
            + (0.1 if same_known_brand else 0.0),
        )
        if confidence >= _SAME_PRODUCT_MIN_CONFIDENCE:
            return _fuzzy_decision(
                incoming_product,
                group_product,
                FuzzyProductMatchOutcome.SAME_PRODUCT,
                confidence,
                title_similarity,
                spec_similarity,
                shared_specs,
                conflicting_specs,
                "Normalized titles and extracted specs are highly similar with no conflicting brand, model, or spec evidence.",
            )

    if (
        (conflicting_specs or model_conflict)
        and not brand_conflict
        and title_similarity >= _SAME_FAMILY_MIN_TITLE_SIMILARITY
    ):
        return _fuzzy_decision(
            incoming_product,
            group_product,
            FuzzyProductMatchOutcome.SAME_FAMILY,
            min(0.84, max(title_similarity, spec_similarity or 0.0)),
            title_similarity,
            spec_similarity,
            shared_specs,
            conflicting_specs,
            "Titles look related, but model or spec differences make this a family-level match rather than the same product.",
        )

    if (
        not has_conflict
        and (has_spec_gap or title_similarity >= _UNCERTAIN_MIN_TITLE_SIMILARITY)
        and title_similarity >= _SAME_FAMILY_MIN_TITLE_SIMILARITY
    ):
        return _fuzzy_decision(
            incoming_product,
            group_product,
            FuzzyProductMatchOutcome.UNCERTAIN,
            min(0.79, title_similarity),
            title_similarity,
            spec_similarity,
            shared_specs,
            conflicting_specs,
            "Titles overlap, but the evidence is incomplete or below the confidence needed to collapse candidates.",
        )

    return _fuzzy_decision(
        incoming_product,
        group_product,
        FuzzyProductMatchOutcome.DIFFERENT_PRODUCT,
        max(0.0, min(0.5, title_similarity)),
        title_similarity,
        spec_similarity,
        shared_specs,
        conflicting_specs,
        "Normalized title and spec similarity is too weak to treat these as the same product.",
    )


def _fuzzy_decision(
    incoming_product: CanonicalProduct,
    group_product: CanonicalProduct,
    outcome: FuzzyProductMatchOutcome,
    confidence: float,
    title_similarity: float,
    spec_similarity: float | None,
    shared_spec_tokens: tuple[str, ...],
    conflicting_spec_tokens: tuple[str, ...],
    rationale: str,
) -> FuzzyProductMatchDecision:
    return FuzzyProductMatchDecision(
        left_product_id=incoming_product.product_id,
        right_product_id=group_product.product_id,
        outcome=outcome,
        confidence=round(confidence, 3),
        title_similarity=round(title_similarity, 3),
        spec_similarity=round(spec_similarity, 3)
        if spec_similarity is not None
        else None,
        shared_spec_tokens=shared_spec_tokens,
        conflicting_spec_tokens=conflicting_spec_tokens,
        rationale=rationale,
    )


def _normalized_match_text(
    product: CanonicalProduct,
    listing: ProductListing,
) -> str:
    return " ".join(
        part
        for part in (product.brand, product.model, product.name, listing.title)
        if part
    )


def _title_tokens(text: str) -> set[str]:
    return {
        token
        for token in _TOKEN_PATTERN.findall(text.casefold().replace("-", " "))
        if token not in _TITLE_STOPWORDS
    }


def _title_similarity(
    left_text: str,
    right_text: str,
    left_tokens: set[str],
    right_tokens: set[str],
) -> float:
    if not left_tokens or not right_tokens:
        return 0.0
    token_similarity = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    sequence_similarity = SequenceMatcher(
        None,
        " ".join(sorted(left_tokens)),
        " ".join(sorted(right_tokens)),
    ).ratio()
    return max(token_similarity, sequence_similarity * 0.95)


def _spec_tokens(text: str) -> tuple[str, ...]:
    casefolded = text.casefold().replace('"', " in ")
    specs: set[str] = set()
    for match in _SPEC_UNIT_PATTERN.finditer(casefolded):
        number = _normalize_number(match.group("number"))
        unit = _normalize_spec_unit(match.group("unit"))
        if unit == "size_in":
            specs.add(f"number:{number}")
        else:
            specs.add(f"{unit}:{number}")
    for match in _RESOLUTION_PATTERN.finditer(casefolded):
        specs.add(f"resolution:{match.group(0).casefold()}")
    for token in _TOKEN_PATTERN.findall(casefolded.replace("-", " ")):
        if token in _COLOR_SPEC_WORDS:
            specs.add(f"color:{token}")
        elif token.isdigit() and len(token) >= 2:
            specs.add(f"number:{int(token)}")
        elif re.fullmatch(r"\d+(?:gb|tb|hz|mah|mp|w)", token):
            specs.add(_compact_spec_token(token))
    return tuple(sorted(specs))


def _compact_spec_token(token: str) -> str:
    match = re.fullmatch(r"(?P<number>\d+)(?P<unit>gb|tb|hz|mah|mp|w)", token)
    if match is None:
        return f"spec:{token}"
    return f"{_normalize_spec_unit(match.group('unit'))}:{match.group('number')}"


def _normalize_number(value: str) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _normalize_spec_unit(value: str) -> str:
    unit = value.casefold()
    if unit in {"inches", "inch", "in"}:
        return "size_in"
    return unit


def _spec_similarity(
    left_specs: tuple[str, ...],
    right_specs: tuple[str, ...],
) -> float | None:
    if not left_specs and not right_specs:
        return None
    if not left_specs or not right_specs:
        return 0.0
    left = set(left_specs)
    right = set(right_specs)
    return len(left & right) / len(left | right)


def _conflicting_spec_tokens(
    left_specs: tuple[str, ...],
    right_specs: tuple[str, ...],
) -> tuple[str, ...]:
    left_by_kind = _specs_by_kind(left_specs)
    right_by_kind = _specs_by_kind(right_specs)
    conflicts: list[str] = []
    for kind in sorted(left_by_kind.keys() & right_by_kind.keys()):
        if left_by_kind[kind] != right_by_kind[kind]:
            conflicts.append(
                f"{kind}:{'/'.join(sorted(left_by_kind[kind]))}!={ '/'.join(sorted(right_by_kind[kind]))}"
            )
    return tuple(conflicts)


def _specs_by_kind(specs: tuple[str, ...]) -> dict[str, set[str]]:
    by_kind: dict[str, set[str]] = {}
    for spec in specs:
        kind, _separator, value = spec.partition(":")
        by_kind.setdefault(kind, set()).add(value)
    return by_kind


def _known_brand_conflict(left: CanonicalProduct, right: CanonicalProduct) -> bool:
    left_brand = _normalize_text(left.brand)
    right_brand = _normalize_text(right.brand)
    return left_brand is not None and right_brand is not None and left_brand != right_brand


def _known_model_conflict(left: CanonicalProduct, right: CanonicalProduct) -> bool:
    left_model = _normalize_text(left.model)
    right_model = _normalize_text(right.model)
    return left_model is not None and right_model is not None and left_model != right_model


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", value).strip().casefold()
    return normalized or None


def _normalized_url_value(listing: ProductListing) -> str | None:
    if listing.canonical_url is not None:
        return canonical_listing_url(str(listing.canonical_url))
    return canonical_listing_url(str(listing.url))


def _retailer_key(listing: ProductListing) -> tuple[str, str] | None:
    retailer_id = _normalize_identifier(listing.retailer_id or "")
    if retailer_id is None:
        return None
    return _domain(str(listing.url)), retailer_id


def _same_retailer_domain(left: ProductListing, right: ProductListing) -> bool:
    return _domain(str(left.url)) == _domain(str(right.url))


def _domain(url: str) -> str:
    _normalized_url, domain = normalize_source_url(url)
    return domain


def _retailer_id(url: str) -> str | None:
    normalized_url, _domain = normalize_source_url(url)
    parsed = urlsplit(normalized_url)

    amazon_match = _ASIN_PATH_PATTERN.search(parsed.path)
    if amazon_match is not None:
        return amazon_match.group(1)

    ikea_match = _IKEA_PRODUCT_CODE_PATTERN.search(parsed.path)
    if ikea_match is not None:
        return ikea_match.group(1)

    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        if key.replace("_", "").replace("-", "").lower() in _QUERY_ID_KEYS:
            normalized = _normalize_identifier(value)
            if normalized is not None:
                return normalized

    path_parts = [part for part in parsed.path.split("/") if part]
    for index, part in enumerate(path_parts[:-1]):
        marker = part.casefold()
        if marker in _PATH_ID_MARKERS:
            if marker == "gp" and path_parts[index + 1].casefold() == "product":
                continue
            normalized = _normalize_identifier(path_parts[index + 1])
            if normalized is not None:
                return normalized
    return None


def _merge_product_identity(
    primary: CanonicalProduct,
    incoming: CanonicalProduct,
    listing_ids: tuple[object, ...],
) -> CanonicalProduct:
    updates = {
        "brand": primary.brand or incoming.brand,
        "model": primary.model or incoming.model,
        "sku": primary.sku or incoming.sku,
        "upc": primary.upc or incoming.upc,
        "ean": primary.ean or incoming.ean,
        "category": primary.category or incoming.category,
        "source_ids": tuple(dict.fromkeys((*primary.source_ids, *incoming.source_ids))),
        "listing_ids": tuple(dict.fromkeys(listing_ids)),
    }
    return _copy_product(primary, **updates)


def _copy_product(product: CanonicalProduct, **updates: object) -> CanonicalProduct:
    data = product.model_dump(mode="json")
    data.update(updates)
    return CanonicalProduct.model_validate(data)


def _copy_listing(listing: ProductListing, **updates: object) -> ProductListing:
    data = listing.model_dump(mode="json")
    data.update(updates)
    return ProductListing.model_validate(data)
