from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from enum import StrEnum

from pydantic import Field

from app.providers.source_quality import SourceClass, score_source_quality
from app.schemas.analysis import (
    ListingTrustAssessment,
    ListingTrustLevel,
    ListingTrustSignal,
    ListingTrustSignalKind,
    ListingTrustSignalPolarity,
)
from app.schemas.base import CartCartBaseModel
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import ListingId, SourceId
from app.schemas.products import ProductListing, SellerTrustSignal
from app.schemas.search_sources import SourceQualityLevel


class PriceComparisonBasis(StrEnum):
    CANONICAL_GROUP = "canonical_group"
    CATEGORY = "category"


class PricePlausibilityFinding(CartCartBaseModel):
    listing_id: ListingId
    suspicious: bool
    basis: PriceComparisonBasis
    price: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    reference_median: Decimal = Field(gt=0)
    price_to_median_ratio: Decimal = Field(ge=0)
    comparable_listing_count: int = Field(ge=2)
    summary: str = Field(min_length=1, max_length=1000)
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)


class ListingTrustRuleContext(CartCartBaseModel):
    review_count: int | None = Field(default=None, ge=0)
    return_policy_present: bool | None = None
    warranty_present: bool | None = None
    suspicious_price: bool = False
    suspicious_price_reasons: tuple[str, ...] = Field(default_factory=tuple)
    missing_metadata: tuple[str, ...] = Field(default_factory=tuple)
    contradictory_listing_data: tuple[str, ...] = Field(default_factory=tuple)
    evidence_ids: tuple[SourceId, ...] = Field(default_factory=tuple)
    source_ids: tuple[SourceId, ...] = Field(default_factory=tuple)


def assess_listing_trust(
    listing: ProductListing,
    context: ListingTrustRuleContext | None = None,
) -> ListingTrustAssessment:
    details = context or ListingTrustRuleContext()
    evidence_ids = details.evidence_ids or listing.source_ids
    source_ids = tuple(dict.fromkeys((*details.source_ids, *listing.source_ids)))
    source_class = score_source_quality(str(listing.url)).source_class

    signals: list[ListingTrustSignal] = []
    positives: list[str] = []
    red_flags: list[str] = []
    score = 0.45

    seller_score, seller_positive, seller_flag = _seller_signal(
        listing, signals, evidence_ids, source_ids
    )
    score += seller_score
    positives.extend(seller_positive)
    red_flags.extend(seller_flag)

    source_score, source_positive, source_flag = _source_type_signal(
        source_class, signals, evidence_ids, source_ids
    )
    score += source_score
    positives.extend(source_positive)
    red_flags.extend(source_flag)

    review_score, review_positive, review_flag = _review_count_signal(
        details.review_count, signals, evidence_ids, source_ids
    )
    score += review_score
    positives.extend(review_positive)
    red_flags.extend(review_flag)

    policy_score, policy_positive, policy_flag = _policy_signal(
        details.return_policy_present,
        details.warranty_present,
        signals,
        evidence_ids,
        source_ids,
    )
    score += policy_score
    positives.extend(policy_positive)
    red_flags.extend(policy_flag)

    missing = _missing_metadata(listing, details)
    if missing:
        score -= min(0.24, 0.06 * len(missing))
        summary = "Missing listing metadata: " + ", ".join(missing) + "."
        signals.append(
            _signal(
                ListingTrustSignalKind.MISSING_METADATA,
                ListingTrustSignalPolarity.NEGATIVE,
                0.64,
                summary,
                evidence_ids,
                source_ids,
            )
        )
        red_flags.append(summary)

    suspicious = False
    if details.suspicious_price:
        suspicious = True
        score -= 0.45
        summary = (
            " ".join(details.suspicious_price_reasons)
            if details.suspicious_price_reasons
            else "The listing price is marked as suspicious."
        )
        signals.append(
            _signal(
                ListingTrustSignalKind.SUSPICIOUS_PRICE,
                ListingTrustSignalPolarity.NEGATIVE,
                0.95,
                summary,
                evidence_ids,
                source_ids,
            )
        )
        red_flags.append(summary)

    if details.contradictory_listing_data:
        suspicious = True
        score -= 0.35
        summary = "Contradictory listing data: "
        summary += "; ".join(details.contradictory_listing_data) + "."
        signals.append(
            _signal(
                ListingTrustSignalKind.CONTRADICTORY_LISTING_DATA,
                ListingTrustSignalPolarity.NEGATIVE,
                0.9,
                summary,
                evidence_ids,
                source_ids,
            )
        )
        red_flags.append(summary)

    if _is_unknown_assessment(listing, details, source_class, signals):
        level = ListingTrustLevel.UNKNOWN
        confidence = _confidence(0.34, "There is not enough listing evidence.")
        summary = "There is not enough seller or listing evidence to judge trust."
    else:
        suspicious = suspicious or _has_suspicious_signal(signals)
        level = _level_from_score(score, suspicious, positives, red_flags)
        confidence = _confidence_for_level(level, score)
        summary = _summary_for_level(level)

    return ListingTrustAssessment(
        listing_id=listing.listing_id,
        level=level,
        confidence=confidence,
        summary=summary,
        trust_signals=tuple(signals),
        red_flags=tuple(dict.fromkeys(red_flags)),
        positive_signals=tuple(dict.fromkeys(positives)),
        evidence_ids=evidence_ids,
        source_ids=source_ids,
    )


def compare_price_plausibility(
    listing_groups: Sequence[Sequence[ProductListing]],
) -> tuple[PricePlausibilityFinding, ...]:
    """Find implausibly cheap listings using same-product prices before category prices."""

    non_empty_groups = tuple(tuple(group) for group in listing_groups if group)
    category_prices = _prices_by_currency(
        listing for group in non_empty_groups for listing in group
    )
    findings: list[PricePlausibilityFinding] = []
    for group in non_empty_groups:
        group_prices = _prices_by_currency(group)
        for listing in group:
            finding = _price_plausibility_finding(
                listing,
                group_prices.get(listing.price.currency, ()) if listing.price else (),
                PriceComparisonBasis.CANONICAL_GROUP,
            )
            if finding is None:
                finding = _price_plausibility_finding(
                    listing,
                    category_prices.get(listing.price.currency, ()) if listing.price else (),
                    PriceComparisonBasis.CATEGORY,
                )
            if finding is not None:
                findings.append(finding)
    return tuple(findings)


def price_plausibility_contexts(
    listing_groups: Sequence[Sequence[ProductListing]],
    existing_contexts: Mapping[ListingId, ListingTrustRuleContext] | None = None,
) -> dict[ListingId, ListingTrustRuleContext]:
    contexts = dict(existing_contexts or {})
    for finding in compare_price_plausibility(listing_groups):
        if not finding.suspicious:
            continue
        current = contexts.get(finding.listing_id, ListingTrustRuleContext())
        contexts[finding.listing_id] = current.model_copy(
            update={
                "suspicious_price": True,
                "suspicious_price_reasons": tuple(
                    dict.fromkeys((*current.suspicious_price_reasons, finding.summary))
                ),
                "evidence_ids": tuple(
                    dict.fromkeys((*current.evidence_ids, *finding.source_ids))
                ),
                "source_ids": tuple(
                    dict.fromkeys((*current.source_ids, *finding.source_ids))
                ),
            }
        )
    return contexts


def _prices_by_currency(
    listings: Iterable[ProductListing],
) -> dict[str, tuple[tuple[ProductListing, Decimal], ...]]:
    prices: dict[str, list[tuple[ProductListing, Decimal]]] = {}
    for listing in listings:
        if listing.price is None:
            continue
        currency = listing.price.currency
        amount = listing.price.amount
        prices.setdefault(currency, []).append((listing, amount))
    return {currency: tuple(items) for currency, items in prices.items()}


def _price_plausibility_finding(
    listing: ProductListing,
    comparison_prices: Sequence[tuple[ProductListing, Decimal]],
    basis: PriceComparisonBasis,
) -> PricePlausibilityFinding | None:
    if listing.price is None:
        return None
    peer_prices = tuple(
        (peer, amount)
        for peer, amount in comparison_prices
        if peer.listing_id != listing.listing_id and amount > 0
    )
    minimum_peers = (
        2 if basis == PriceComparisonBasis.CANONICAL_GROUP else 4
    )
    if len(peer_prices) < minimum_peers:
        return None

    median = _median(tuple(amount for _peer, amount in peer_prices))
    if median <= 0:
        return None

    price = listing.price.amount
    ratio = price / median
    suspicious = _is_implausibly_low_price(listing, ratio, median, median - price, basis)
    if not suspicious:
        return None

    source_ids = tuple(
        dict.fromkeys(
            source_id
            for peer, _amount in ((listing, price), *peer_prices)
            for source_id in peer.source_ids
        )
    )
    return PricePlausibilityFinding(
        listing_id=listing.listing_id,
        suspicious=True,
        basis=basis,
        price=price,
        currency=listing.price.currency,
        reference_median=median,
        price_to_median_ratio=ratio,
        comparable_listing_count=len(peer_prices),
        summary=_price_plausibility_summary(listing, ratio, median, basis),
        source_ids=source_ids,
    )


def _is_implausibly_low_price(
    listing: ProductListing,
    ratio: Decimal,
    median: Decimal,
    discount_amount: Decimal,
    basis: PriceComparisonBasis,
) -> bool:
    if discount_amount <= 0:
        return False

    if basis == PriceComparisonBasis.CANONICAL_GROUP:
        ratio_threshold = Decimal("0.50")
        required_discount_share = Decimal("0.25")
    else:
        ratio_threshold = Decimal("0.30")
        required_discount_share = Decimal("0.50")

    if _has_trusted_discount_context(listing):
        ratio_threshold *= Decimal("0.70")

    required_discount = max(Decimal("10.00"), median * required_discount_share)
    return ratio <= ratio_threshold and discount_amount >= required_discount


def _has_trusted_discount_context(listing: ProductListing) -> bool:
    source_class = score_source_quality(str(listing.url)).source_class
    return (
        listing.seller.trust_signal
        in {SellerTrustSignal.STRONG, SellerTrustSignal.REASONABLE}
        and listing.source_quality.level
        in {SourceQualityLevel.STRONG, SourceQualityLevel.ADEQUATE}
        and source_class
        in {
            SourceClass.OFFICIAL_MANUFACTURER,
            SourceClass.OFFICIAL_STORE_REGIONAL,
            SourceClass.ESTABLISHED_RETAILER_FIRST_PARTY,
        }
    )


def _median(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def _price_plausibility_summary(
    listing: ProductListing,
    ratio: Decimal,
    median: Decimal,
    basis: PriceComparisonBasis,
) -> str:
    percentage = int((ratio * Decimal("100")).quantize(Decimal("1")))
    scope = (
        "same-product listings"
        if basis == PriceComparisonBasis.CANONICAL_GROUP
        else "category listings"
    )
    return (
        f"The listing price is only about {percentage}% of the comparable "
        f"{scope} median ({listing.price.currency} {median:.2f}), which is "
        "too low to treat as a normal discount without stronger seller evidence."
    )


def _seller_signal(
    listing: ProductListing,
    signals: list[ListingTrustSignal],
    evidence_ids: tuple[SourceId, ...],
    source_ids: tuple[SourceId, ...],
) -> tuple[float, list[str], list[str]]:
    seller_name = listing.seller.seller_name
    known = _seller_identity_known(seller_name)
    trust_signal = listing.seller.trust_signal
    positives: list[str] = []
    red_flags: list[str] = []
    score = 0.0

    if trust_signal == SellerTrustSignal.SUSPICIOUS:
        score -= 0.55
        summary = "Seller identity or prior seller signal is suspicious."
        red_flags.append(summary)
        polarity = ListingTrustSignalPolarity.NEGATIVE
        strength = 0.95
    elif trust_signal == SellerTrustSignal.WEAK:
        score -= 0.2
        summary = "Seller identity is weak."
        red_flags.append(summary)
        polarity = ListingTrustSignalPolarity.NEGATIVE
        strength = 0.72
    elif not known and trust_signal != SellerTrustSignal.UNKNOWN:
        score -= 0.18
        summary = "Seller identity is missing or generic."
        red_flags.append(summary)
        polarity = ListingTrustSignalPolarity.NEGATIVE
        strength = 0.68
    elif trust_signal == SellerTrustSignal.STRONG:
        score += 0.2
        summary = "Seller identity is clear and has a strong extracted signal."
        positives.append(summary)
        polarity = ListingTrustSignalPolarity.POSITIVE
        strength = 0.88
    elif trust_signal == SellerTrustSignal.REASONABLE:
        score += 0.12
        summary = "Seller identity is clear and has a reasonable extracted signal."
        positives.append(summary)
        polarity = ListingTrustSignalPolarity.POSITIVE
        strength = 0.76
    elif trust_signal == SellerTrustSignal.MIXED:
        score -= 0.08
        summary = "Seller identity is present, but the extracted signal is mixed."
        red_flags.append(summary)
        polarity = ListingTrustSignalPolarity.NEGATIVE
        strength = 0.58
    else:
        summary = "Seller identity is present but not independently verified."
        polarity = ListingTrustSignalPolarity.UNKNOWN
        strength = 0.4

    signals.append(
        _signal(
            ListingTrustSignalKind.SELLER_IDENTITY,
            polarity,
            strength,
            summary,
            evidence_ids,
            source_ids,
        )
    )
    return score, positives, red_flags


def _source_type_signal(
    source_class: SourceClass,
    signals: list[ListingTrustSignal],
    evidence_ids: tuple[SourceId, ...],
    source_ids: tuple[SourceId, ...],
) -> tuple[float, list[str], list[str]]:
    positives: list[str] = []
    red_flags: list[str] = []
    score = 0.0

    if source_class in {
        SourceClass.OFFICIAL_MANUFACTURER,
        SourceClass.OFFICIAL_STORE_REGIONAL,
        SourceClass.ESTABLISHED_RETAILER_FIRST_PARTY,
    }:
        score = 0.22
        summary = "Source is an official or established first-party purchase source."
        positives.append(summary)
        polarity = ListingTrustSignalPolarity.POSITIVE
        strength = 0.9
    elif source_class == SourceClass.ESTABLISHED_RETAILER_MIXED:
        score = 0.1
        summary = "Source is an established retailer with listing-specific checks."
        positives.append(summary)
        polarity = ListingTrustSignalPolarity.POSITIVE
        strength = 0.7
    elif source_class == SourceClass.OPEN_MARKETPLACE:
        summary = "Source is an open marketplace, so seller details matter."
        polarity = ListingTrustSignalPolarity.NEUTRAL
        strength = 0.55
    elif source_class == SourceClass.RESELLER_IMPORT_PROXY:
        score = -0.35
        summary = "Source is excluded or reseller-like for normal purchase evidence."
        red_flags.append(summary)
        polarity = ListingTrustSignalPolarity.NEGATIVE
        strength = 0.9
    elif source_class in {
        SourceClass.REVIEW_TESTING,
        SourceClass.REVIEW_EDITORIAL,
        SourceClass.COMMUNITY,
        SourceClass.PRICE_COMPARISON,
    }:
        score = -0.12
        summary = "Source is not the seller of record for this listing."
        red_flags.append(summary)
        polarity = ListingTrustSignalPolarity.NEGATIVE
        strength = 0.64
    else:
        summary = "Source type is not recognized as an established retailer."
        polarity = ListingTrustSignalPolarity.UNKNOWN
        strength = 0.4

    signals.append(
        _signal(
            ListingTrustSignalKind.ESTABLISHED_RETAILER_SOURCE_TYPE,
            polarity,
            strength,
            summary,
            evidence_ids,
            source_ids,
        )
    )
    return score, positives, red_flags


def _review_count_signal(
    review_count: int | None,
    signals: list[ListingTrustSignal],
    evidence_ids: tuple[SourceId, ...],
    source_ids: tuple[SourceId, ...],
) -> tuple[float, list[str], list[str]]:
    positives: list[str] = []
    red_flags: list[str] = []
    score = 0.0

    if review_count is None:
        summary = "Listing review count is unavailable."
        polarity = ListingTrustSignalPolarity.UNKNOWN
        strength = 0.35
    elif review_count >= 50:
        score = 0.08
        summary = f"Listing has a substantial review count ({review_count})."
        positives.append(summary)
        polarity = ListingTrustSignalPolarity.POSITIVE
        strength = 0.72
    elif review_count >= 10:
        score = 0.04
        summary = f"Listing has some review history ({review_count} reviews)."
        positives.append(summary)
        polarity = ListingTrustSignalPolarity.POSITIVE
        strength = 0.58
    elif review_count == 0:
        score = -0.1
        summary = "Listing has no visible review history."
        red_flags.append(summary)
        polarity = ListingTrustSignalPolarity.NEGATIVE
        strength = 0.62
    else:
        score = -0.06
        summary = f"Listing has very little review history ({review_count} reviews)."
        red_flags.append(summary)
        polarity = ListingTrustSignalPolarity.NEGATIVE
        strength = 0.54

    signals.append(
        _signal(
            ListingTrustSignalKind.REVIEW_COUNT,
            polarity,
            strength,
            summary,
            evidence_ids,
            source_ids,
        )
    )
    return score, positives, red_flags


def _policy_signal(
    return_policy_present: bool | None,
    warranty_present: bool | None,
    signals: list[ListingTrustSignal],
    evidence_ids: tuple[SourceId, ...],
    source_ids: tuple[SourceId, ...],
) -> tuple[float, list[str], list[str]]:
    positives: list[str] = []
    red_flags: list[str] = []

    if return_policy_present is True and warranty_present is True:
        score = 0.12
        summary = "Return and warranty details are clear."
        positives.append(summary)
        polarity = ListingTrustSignalPolarity.POSITIVE
        strength = 0.8
    elif return_policy_present is True or warranty_present is True:
        score = 0.06
        summary = "At least one of return or warranty details is clear."
        positives.append(summary)
        polarity = ListingTrustSignalPolarity.POSITIVE
        strength = 0.62
    elif return_policy_present is False and warranty_present is False:
        score = -0.12
        summary = "Return and warranty details are both unclear or missing."
        red_flags.append(summary)
        polarity = ListingTrustSignalPolarity.NEGATIVE
        strength = 0.72
    elif return_policy_present is False or warranty_present is False:
        score = -0.06
        summary = "Return or warranty clarity is missing."
        red_flags.append(summary)
        polarity = ListingTrustSignalPolarity.NEGATIVE
        strength = 0.58
    else:
        score = 0.0
        summary = "Return and warranty clarity is unavailable."
        polarity = ListingTrustSignalPolarity.UNKNOWN
        strength = 0.35

    signals.append(
        _signal(
            ListingTrustSignalKind.RETURN_WARRANTY_CLARITY,
            polarity,
            strength,
            summary,
            evidence_ids,
            source_ids,
        )
    )
    return score, positives, red_flags


def _missing_metadata(
    listing: ProductListing,
    context: ListingTrustRuleContext,
) -> tuple[str, ...]:
    missing = list(context.missing_metadata)
    if listing.price is None:
        missing.append("price")
    if not listing.region_availability:
        missing.append("regional availability")
    if listing.source_quality.level == SourceQualityLevel.UNKNOWN:
        missing.append("source quality")
    if not any((listing.retailer_id, listing.sku, listing.upc, listing.ean)):
        missing.append("retailer or product identifier")
    return tuple(dict.fromkeys(item.strip() for item in missing if item.strip()))


def _is_unknown_assessment(
    listing: ProductListing,
    context: ListingTrustRuleContext,
    source_class: SourceClass,
    signals: Sequence[ListingTrustSignal],
) -> bool:
    if context.suspicious_price or context.contradictory_listing_data:
        return False
    if context.review_count is not None:
        return False
    if context.return_policy_present is not None or context.warranty_present is not None:
        return False
    if context.missing_metadata:
        return False
    if listing.seller.trust_signal != SellerTrustSignal.UNKNOWN:
        return False
    if source_class != SourceClass.UNKNOWN:
        return False
    known_polarities = {
        ListingTrustSignalPolarity.POSITIVE,
        ListingTrustSignalPolarity.NEGATIVE,
    }
    meaningful_signals = (
        signal
        for signal in signals
        if signal.kind != ListingTrustSignalKind.MISSING_METADATA
    )
    return not any(signal.polarity in known_polarities for signal in meaningful_signals)


def _has_suspicious_signal(signals: Sequence[ListingTrustSignal]) -> bool:
    suspicious_kinds = {
        ListingTrustSignalKind.SUSPICIOUS_PRICE,
        ListingTrustSignalKind.CONTRADICTORY_LISTING_DATA,
    }
    return any(
        signal.kind in suspicious_kinds
        or (
            signal.kind == ListingTrustSignalKind.SELLER_IDENTITY
            and signal.polarity == ListingTrustSignalPolarity.NEGATIVE
            and signal.strength >= 0.9
        )
        or (
            signal.kind == ListingTrustSignalKind.ESTABLISHED_RETAILER_SOURCE_TYPE
            and signal.polarity == ListingTrustSignalPolarity.NEGATIVE
            and signal.strength >= 0.9
        )
        for signal in signals
    )


def _level_from_score(
    raw_score: float,
    suspicious: bool,
    positives: Sequence[str],
    red_flags: Sequence[str],
) -> ListingTrustLevel:
    if suspicious:
        return ListingTrustLevel.SUSPICIOUS
    score = min(1.0, max(0.0, raw_score))
    if score >= 0.82 and not red_flags:
        return ListingTrustLevel.STRONG
    if score >= 0.65 and len(red_flags) <= 1:
        return ListingTrustLevel.REASONABLE
    if positives and red_flags and score >= 0.35:
        return ListingTrustLevel.MIXED
    if score >= 0.48:
        return ListingTrustLevel.MIXED
    return ListingTrustLevel.WEAK


def _confidence_for_level(level: ListingTrustLevel, raw_score: float) -> Confidence:
    clamped = min(1.0, max(0.0, raw_score))
    if level == ListingTrustLevel.SUSPICIOUS:
        return _confidence(0.86, "Deterministic red flags require blocking caution.")
    if level == ListingTrustLevel.STRONG:
        return _confidence(max(0.82, clamped), "Strong deterministic trust signals.")
    if level == ListingTrustLevel.REASONABLE:
        return _confidence(max(0.68, clamped), "Mostly positive deterministic signals.")
    if level == ListingTrustLevel.MIXED:
        return _confidence(0.62, "Positive and negative trust signals are mixed.")
    return _confidence(0.7, "Deterministic rules found weak trust signals.")


def _summary_for_level(level: ListingTrustLevel) -> str:
    summaries = {
        ListingTrustLevel.STRONG: "The listing has strong seller and source trust signals.",
        ListingTrustLevel.REASONABLE: "The listing has reasonable buyer-safety signals.",
        ListingTrustLevel.MIXED: "The listing has both useful and concerning trust signals.",
        ListingTrustLevel.WEAK: "The listing has weak seller or listing trust signals.",
        ListingTrustLevel.SUSPICIOUS: (
            "The listing has suspicious trust signals and should not be treated "
            "as a safe buy."
        ),
        ListingTrustLevel.UNKNOWN: (
            "There is not enough seller or listing evidence to judge trust."
        ),
    }
    return summaries[level]


def _confidence(score: float, rationale: str) -> Confidence:
    if score >= 0.75:
        level = ConfidenceLevel.HIGH
    elif score >= 0.5:
        level = ConfidenceLevel.MEDIUM
    else:
        level = ConfidenceLevel.LOW
    return Confidence(score=score, level=level, rationale=rationale)


def _signal(
    kind: ListingTrustSignalKind,
    polarity: ListingTrustSignalPolarity,
    strength: float,
    summary: str,
    evidence_ids: tuple[SourceId, ...],
    source_ids: tuple[SourceId, ...],
) -> ListingTrustSignal:
    return ListingTrustSignal(
        kind=kind,
        polarity=polarity,
        strength=strength,
        summary=summary,
        evidence_ids=evidence_ids,
        source_ids=source_ids,
    )


def _seller_identity_known(seller_name: str) -> bool:
    normalized = " ".join(seller_name.lower().split())
    unknown_names = {
        "3rd party seller",
        "marketplace seller",
        "seller",
        "third party",
        "third-party seller",
        "unknown",
        "unknown seller",
    }
    return normalized not in unknown_names
