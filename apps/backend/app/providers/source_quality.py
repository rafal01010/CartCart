from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import AnyHttpUrl, Field

from app.core.ikea_regions import IKEA_REGION_PATHS
from app.schemas.base import CartCartBaseModel
from app.schemas.money import CurrencyCode
from app.schemas.regions import RegionCode
from app.schemas.search_sources import SourceQuality, SourceQualityLevel


SOURCE_POLICY_VERSION = "cartcart_source_quality_v1_2026-06-13"

MVP_TARGET_REGIONS = frozenset(
    {"PH", "US", "KR", "CA", "JP", "SG", "MO", "AU", "NZ", "HK", "TW"}
)

REGION_CURRENCIES: dict[str, str] = {
    "PH": "PHP",
    "US": "USD",
    "KR": "KRW",
    "CA": "CAD",
    "JP": "JPY",
    "SG": "SGD",
    "MO": "MOP",
    "AU": "AUD",
    "NZ": "NZD",
    "HK": "HKD",
    "TW": "TWD",
}


class SourceClass(StrEnum):
    OFFICIAL_MANUFACTURER = "official_manufacturer"
    OFFICIAL_STORE_REGIONAL = "official_store_regional"
    ESTABLISHED_RETAILER_FIRST_PARTY = "established_retailer_first_party"
    ESTABLISHED_RETAILER_MIXED = "established_retailer_mixed"
    OPEN_MARKETPLACE = "open_marketplace"
    RESELLER_IMPORT_PROXY = "reseller_import_proxy"
    REVIEW_TESTING = "review_testing"
    REVIEW_EDITORIAL = "review_editorial"
    COMMUNITY = "community"
    PRICE_COMPARISON = "price_comparison"
    UNKNOWN = "unknown"


class SourceEvidenceContext(StrEnum):
    GENERAL = "general"
    SPECIFICATIONS = "specifications"
    PRODUCT_IDENTITY = "product_identity"
    PURCHASE = "purchase"
    REVIEW = "review"
    COMMUNITY = "community"


class RegionRelevanceLevel(StrEnum):
    MATCH = "match"
    PARTIAL = "partial"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


class SourceQualityMetadata(CartCartBaseModel):
    target_region_code: RegionCode | None = None
    source_region_code: RegionCode | None = None
    currency: CurrencyCode | None = None
    ships_to_target_region: bool | None = None
    cross_border_allowed: bool = False
    evidence_context: SourceEvidenceContext = SourceEvidenceContext.GENERAL
    official_brand_match: bool | None = None
    official_store_verified: bool | None = None
    sold_by_domain_owner: bool | None = None
    third_party_seller: bool | None = None
    seller_identity_known: bool | None = None
    return_policy_present: bool | None = None
    local_warranty_present: bool | None = None
    contact_information_present: bool | None = None
    shipping_origin_known: bool | None = None
    product_identity_consistent: bool | None = None
    suspicious_price: bool = False
    off_platform_payment: bool = False
    recurring_community_signal: bool = False
    community_engagement_available: bool = False
    community_source_recent: bool = False


class SourceQualityAssessment(CartCartBaseModel):
    policy_version: str = SOURCE_POLICY_VERSION
    normalized_url: AnyHttpUrl
    normalized_domain: str = Field(min_length=1, max_length=253)
    source_class: SourceClass
    quality: SourceQuality
    excluded: bool = False
    requires_trust_assessment: bool = False
    region_relevance: RegionRelevanceLevel
    region_relevance_score: float = Field(ge=0.0, le=1.0)
    reasons: tuple[str, ...] = Field(min_length=1)


@dataclass(frozen=True)
class _DomainRule:
    source_class: SourceClass
    baseline_score: float
    rationale: str
    regions: frozenset[str] = frozenset()
    excluded: bool = False
    requires_trust_assessment: bool = False


def _rule(
    source_class: SourceClass,
    baseline_score: float,
    rationale: str,
    *,
    regions: tuple[str, ...] = (),
    excluded: bool = False,
    requires_trust_assessment: bool = False,
) -> _DomainRule:
    return _DomainRule(
        source_class=source_class,
        baseline_score=baseline_score,
        rationale=rationale,
        regions=frozenset(regions),
        excluded=excluded,
        requires_trust_assessment=requires_trust_assessment,
    )


_OFFICIAL_MANUFACTURER_DOMAINS = {
    "acer.com",
    "adidas.com",
    "apple.com",
    "asics.com",
    "asus.com",
    "bosch-home.com",
    "boschtools.com",
    "brother.com",
    "canon.com",
    "chiccousa.com",
    "coleman.com",
    "columbia.com",
    "cybex-online.com",
    "dell.com",
    "decathlon.com",
    "dewalt.com",
    "ecosa.com",
    "electrolux.com",
    "epson.com",
    "fujifilm-x.com",
    "garmin.com",
    "gracobaby.com",
    "haier.com",
    "hasbro.com",
    "hermanmiller.com",
    "hillspet.com",
    "hm.com",
    "hp.com",
    "kitchenaid.com",
    "koala.com",
    "kongcompany.com",
    "laroche-posay.com",
    "lego.com",
    "lenovo.com",
    "lg.com",
    "logitech.com",
    "lorealparisusa.com",
    "makitatools.com",
    "mattel.com",
    "maxi-cosi.com",
    "midea.com",
    "milwaukeetool.com",
    "muji.com",
    "newbalance.com",
    "nike.com",
    "nikon.com",
    "nintendo.com",
    "ninjakitchen.com",
    "nivea.com",
    "om-digitalsolutions.com",
    "panasonic.com",
    "patagonia.com",
    "philips.com",
    "pigeon.com",
    "playstation.com",
    "purina.com",
    "royalcanin.com",
    "ryobitools.com",
    "salomon.com",
    "samsung.com",
    "sephora.com",
    "skechers.com",
    "sony.com",
    "stanleytools.com",
    "steelcase.com",
    "tefal.com",
    "theordinary.com",
    "thenorthface.com",
    "tiger-corporation.com",
    "uniqlo.com",
    "watsons.com",
    "whirlpool.com",
    "xbox.com",
    "zara.com",
    "zojirushi.com",
    "zwilling.com",
}


_EXCLUDED_DOMAINS = {
    "aliexpress.com",
    "buyee.jp",
    "carousell.com.hk",
    "carousell.ph",
    "carousell.sg",
    "fromjapan.co.jp",
    "goat.com",
    "grailed.com",
    "jauce.com",
    "mercari.com",
    "neokyo.com",
    "sendico.com",
    "shein.com",
    "stockx.com",
    "temu.com",
    "zenmarket.jp",
}


_OPEN_MARKETPLACE_REGIONS: dict[str, tuple[str, ...]] = {
    "11st.co.kr": ("KR",),
    "auction.co.kr": ("KR",),
    "ebay.ca": ("CA",),
    "ebay.com": ("US",),
    "ebay.com.au": ("AU",),
    "etsy.com": ("US",),
    "gmarket.co.kr": ("KR",),
    "lazada.com.ph": ("PH",),
    "lazada.sg": ("SG",),
    "catch.com.au": ("AU",),
    "mydeal.com.au": ("AU",),
    "qoo10.sg": ("SG",),
    "rakuten.co.jp": ("JP",),
    "rakuten.com.tw": ("TW",),
    "ruten.com.tw": ("TW",),
    "shopee.ph": ("PH",),
    "shopee.sg": ("SG",),
    "shopee.tw": ("TW",),
    "shopping.yahoo.co.jp": ("JP",),
    "taobao.com": ("MO", "HK", "TW", "SG"),
    "themarket.com": ("NZ",),
    "tmall.com": ("MO", "HK", "TW", "SG"),
    "trademe.co.nz": ("NZ",),
}


_AMAZON_REGIONS: dict[str, tuple[str, ...]] = {
    "amazon.com": ("US",),
    "amazon.ca": ("CA",),
    "amazon.co.jp": ("JP",),
    "amazon.sg": ("SG",),
    "amazon.com.au": ("AU",),
}


_MIXED_RETAILER_REGIONS: dict[str, tuple[str, ...]] = {
    "bestbuy.ca": ("CA",),
    "bestbuy.com": ("US",),
    "bigw.com.au": ("AU",),
    "bunnings.com.au": ("AU",),
    "canadiantire.ca": ("CA",),
    "coupang.com": ("KR",),
    "hktvmall.com": ("HK", "MO"),
    "kmart.com.au": ("AU",),
    "lotteon.com": ("KR",),
    "mightyape.co.nz": ("NZ",),
    "momoshop.com.tw": ("TW",),
    "musinsa.com": ("KR",),
    "smstore.com": ("PH",),
    "ssg.com": ("KR",),
    "target.com": ("US",),
    "thebay.com": ("CA",),
    "thewarehouse.co.nz": ("NZ",),
    "walmart.ca": ("CA",),
    "walmart.com": ("US",),
    "wayfair.com": ("US", "CA"),
    "zalora.com.ph": ("PH",),
    "zozo.jp": ("JP",),
}


_FIRST_PARTY_RETAILER_REGIONS: dict[str, tuple[str, ...]] = {
    "abenson.com": ("PH",),
    "acehardware.ph": ("PH",),
    "aeonretail.com": ("JP",),
    "ansons.ph": ("PH",),
    "biccamera.com": ("JP",),
    "books.com.tw": ("TW",),
    "briscoes.co.nz": ("NZ",),
    "broadwaylifestyle.com": ("HK", "MO"),
    "challenger.sg": ("SG",),
    "chewy.com": ("US",),
    "costco.ca": ("CA",),
    "costco.com": ("US",),
    "courts.com.sg": ("SG",),
    "fairprice.com.sg": ("SG",),
    "farmers.co.nz": ("NZ",),
    "fortress.com.hk": ("HK", "MO"),
    "gaincity.com": ("SG",),
    "harveynorman.com.sg": ("SG",),
    "homedepot.ca": ("CA",),
    "homedepot.com": ("US",),
    "jbhifi.com.au": ("AU",),
    "londondrugs.com": ("CA",),
    "lowes.ca": ("CA",),
    "lowes.com": ("US",),
    "mannings.com.hk": ("HK", "MO"),
    "mitre10.co.nz": ("NZ",),
    "nitori-net.jp": ("JP",),
    "noelleeming.co.nz": ("NZ",),
    "officeworks.com.au": ("AU",),
    "officedepot.com": ("US",),
    "oliveyoung.co.kr": ("KR",),
    "pchome.com.tw": ("TW",),
    "petbarn.com.au": ("AU",),
    "petexpress.com.ph": ("PH",),
    "rustans.com": ("PH",),
    "senao.com.tw": ("TW",),
    "shoppersdrugmart.ca": ("CA",),
    "staples.com": ("US",),
    "thegoodguys.com.au": ("AU",),
    "tk3c.com": ("TW",),
    "ulta.com": ("US",),
    "watsons.com.hk": ("HK", "MO"),
    "watsons.com.sg": ("SG",),
    "watsons.com.tw": ("TW",),
    "wilcon.com.ph": ("PH",),
    "yodobashi.com": ("JP",),
}


_REVIEW_TESTING_DOMAINS = {
    "babygearlab.com",
    "cameralabs.com",
    "choice.com.au",
    "consumerreports.org",
    "dpreview.com",
    "outdoorgearlab.com",
    "reviewed.usatoday.com",
    "rtings.com",
    "which.co.uk",
}


_REVIEW_EDITORIAL_DOMAINS = {
    "cnet.com",
    "goodhousekeeping.com",
    "nytimes.com",
    "techgearlab.com",
    "tomsguide.com",
}


_REVIEW_REFERENCE_DOMAINS = {"incidecoder.com", "makeupalley.com"}


_COMMUNITY_DOMAINS = {
    "cheapies.nz",
    "clien.net",
    "dcard.tw",
    "dcinside.com",
    "forums.redflagdeals.com",
    "hardwarezone.com.sg",
    "mobile01.com",
    "ozbargain.com.au",
    "pinoydvd.com",
    "ptt.cc",
    "reddit.com",
}


_PRICE_COMPARISON_DOMAINS = {"kakaku.com", "price.com.hk"}


_TRACKING_QUERY_KEYS = {
    "aff",
    "affiliate",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_",
    "tag",
}


def normalize_source_url(url: str) -> tuple[str, str]:
    candidate = url.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("source URL must be an HTTP URL with a hostname.")

    domain = parsed.hostname.rstrip(".").lower()
    if domain.startswith("www."):
        domain = domain[4:]
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("source URL contains an invalid hostname.") from exc

    port = parsed.port
    netloc = domain
    if port is not None and not (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        netloc = f"{domain}:{port}"

    neutral_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not _is_tracking_query_key(key)
    ]
    normalized = urlunsplit(
        (
            parsed.scheme.lower(),
            netloc,
            parsed.path or "/",
            urlencode(neutral_query, doseq=True),
            "",
        )
    )
    return normalized, domain


def score_source_quality(
    url: str,
    metadata: SourceQualityMetadata | None = None,
) -> SourceQualityAssessment:
    details = metadata or SourceQualityMetadata()
    normalized_url, domain = normalize_source_url(url)
    parsed = urlsplit(normalized_url)
    rule = _classify_domain(domain, parsed.path)
    reasons = [rule.rationale]
    score = rule.baseline_score
    excluded = rule.excluded
    requires_trust = rule.requires_trust_assessment

    region_score, region_level, region_reasons = _score_region_relevance(
        domain,
        parsed.path,
        rule,
        details,
    )
    reasons.extend(region_reasons)

    if rule.source_class == SourceClass.OFFICIAL_MANUFACTURER:
        if details.official_brand_match is False:
            score -= 0.35
            reasons.append("The official domain does not match the product brand.")
        if details.evidence_context == SourceEvidenceContext.PURCHASE:
            score -= (1.0 - region_score) * 0.35
            reasons.append(
                "Official purchase details are only strong when the regional store matches."
            )

    if rule.source_class == SourceClass.COMMUNITY:
        if details.recurring_community_signal:
            score += 0.05
            reasons.append("The same community signal recurs across the available evidence.")
        if details.community_engagement_available:
            score += 0.03
            reasons.append("Community engagement context is available.")
        if details.community_source_recent:
            score += 0.02
            reasons.append("The community evidence is recent.")
        reasons.append(
            "Community evidence is qualitative and cannot establish official facts."
        )

    if _is_amazon_domain(domain):
        requires_trust = True
        if details.evidence_context == SourceEvidenceContext.REVIEW:
            score -= 0.05
            reasons.append(
                "Amazon reviews require variant-mixing and manipulation checks."
            )
        else:
            reasons.append(
                "Amazon evidence must preserve listing, seller, and fulfillment context."
            )

    score, heuristic_reasons = _apply_metadata_heuristics(score, rule, details)
    reasons.extend(heuristic_reasons)

    if details.target_region_code is not None and rule.source_class not in {
        SourceClass.OFFICIAL_MANUFACTURER,
        SourceClass.REVIEW_TESTING,
        SourceClass.REVIEW_EDITORIAL,
        SourceClass.COMMUNITY,
    }:
        score -= (1.0 - region_score) * 0.2

    score = round(min(1.0, max(0.0, score)), 2)
    level = _quality_level(score, rule.source_class, heuristic_reasons)
    rationale = " ".join(dict.fromkeys(reasons))[:500]

    return SourceQualityAssessment(
        normalized_url=normalized_url,
        normalized_domain=domain,
        source_class=rule.source_class,
        quality=SourceQuality(level=level, score=score, rationale=rationale),
        excluded=excluded,
        requires_trust_assessment=requires_trust,
        region_relevance=region_level,
        region_relevance_score=region_score,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _classify_domain(domain: str, path: str) -> _DomainRule:
    if _matches_any(domain, {"ikea.com", "ikea.com.hk", "ikea.com.tw"}):
        return _rule(
            SourceClass.OFFICIAL_STORE_REGIONAL,
            0.9,
            "IKEA is an official source whose purchase facts are region-specific.",
        )
    if domain == "nytimes.com" and not path.startswith("/wirecutter"):
        return _unknown_rule()
    if _domain_matches(domain, "facebook.com") and path.startswith("/marketplace"):
        return _rule(
            SourceClass.RESELLER_IMPORT_PROXY,
            0.2,
            "Facebook Marketplace is excluded as normal purchase evidence.",
            excluded=True,
            requires_trust_assessment=True,
        )
    if _matches_any(domain, _EXCLUDED_DOMAINS):
        return _rule(
            SourceClass.RESELLER_IMPORT_PROXY,
            0.2,
            "The platform is excluded as normal purchase evidence by the MVP seed.",
            excluded=True,
            requires_trust_assessment=True,
        )
    for candidate, regions in _AMAZON_REGIONS.items():
        if _domain_matches(domain, candidate):
            return _rule(
                SourceClass.OPEN_MARKETPLACE,
                0.45,
                "Amazon is a mixed marketplace and must be assessed per listing.",
                regions=regions,
                requires_trust_assessment=True,
            )
    for candidate, regions in _OPEN_MARKETPLACE_REGIONS.items():
        if _domain_matches(domain, candidate):
            return _rule(
                SourceClass.OPEN_MARKETPLACE,
                0.45,
                "The domain is an open marketplace requiring seller and listing checks.",
                regions=regions,
                requires_trust_assessment=True,
            )
    for candidate, regions in _MIXED_RETAILER_REGIONS.items():
        if _domain_matches(domain, candidate):
            return _rule(
                SourceClass.ESTABLISHED_RETAILER_MIXED,
                0.65,
                "The established retailer also carries offers that require listing checks.",
                regions=regions,
                requires_trust_assessment=True,
            )
    for candidate, regions in _FIRST_PARTY_RETAILER_REGIONS.items():
        if _domain_matches(domain, candidate):
            return _rule(
                SourceClass.ESTABLISHED_RETAILER_FIRST_PARTY,
                0.8,
                "The domain is a seeded established first-party retailer.",
                regions=regions,
            )
    if _matches_any(domain, _REVIEW_TESTING_DOMAINS):
        return _rule(
            SourceClass.REVIEW_TESTING,
            0.75,
            "The source is seeded for independent or specialist product testing.",
        )
    if _matches_any(domain, _REVIEW_EDITORIAL_DOMAINS):
        return _rule(
            SourceClass.REVIEW_EDITORIAL,
            0.65,
            "The source is a seeded editorial review or buying-guide publication.",
        )
    if _matches_any(domain, _REVIEW_REFERENCE_DOMAINS):
        return _rule(
            SourceClass.REVIEW_EDITORIAL,
            0.45,
            "The source provides user-review or ingredient-reference context only.",
        )
    if _matches_any(domain, _COMMUNITY_DOMAINS):
        return _rule(
            SourceClass.COMMUNITY,
            0.3,
            "The source is a community signal, not an authoritative product source.",
        )
    if _matches_any(domain, _PRICE_COMPARISON_DOMAINS):
        return _rule(
            SourceClass.PRICE_COMPARISON,
            0.35,
            "The source may discover shops or prices but is not the seller of record.",
            requires_trust_assessment=True,
        )
    if _matches_any(domain, _OFFICIAL_MANUFACTURER_DOMAINS):
        return _rule(
            SourceClass.OFFICIAL_MANUFACTURER,
            0.95,
            "The domain is a seeded official manufacturer source for its own products.",
        )
    return _unknown_rule()


def _unknown_rule() -> _DomainRule:
    return _rule(
        SourceClass.UNKNOWN,
        0.25,
        "The source is not in the MVP seed and remains weak or unknown pending verification.",
    )


def _score_region_relevance(
    domain: str,
    path: str,
    rule: _DomainRule,
    metadata: SourceQualityMetadata,
) -> tuple[float, RegionRelevanceLevel, list[str]]:
    target = metadata.target_region_code
    if target is None:
        return 0.5, RegionRelevanceLevel.UNKNOWN, [
            "No target region was supplied, so regional relevance is unknown."
        ]

    reasons: list[str] = []
    if _matches_any(domain, {"ikea.com", "ikea.com.hk", "ikea.com.tw"}):
        expected_domain, expected_path = IKEA_REGION_PATHS.get(target, ("", ""))
        if expected_domain and _domain_matches(domain, expected_domain) and path.startswith(
            expected_path
        ):
            region_score = 1.0
            reasons.append("The IKEA country or region path matches the shopper region.")
        else:
            region_score = 0.35
            reasons.append(
                "The IKEA country or region path does not match the shopper region."
            )
    elif metadata.source_region_code is not None:
        if metadata.source_region_code == target:
            region_score = 1.0
            reasons.append("The declared source region matches the shopper region.")
        else:
            region_score = 0.35
            reasons.append("The declared source region differs from the shopper region.")
    elif rule.regions:
        if target in rule.regions:
            region_score = 1.0
            reasons.append("The seeded retailer or marketplace region matches.")
        else:
            region_score = 0.35
            reasons.append("The seeded retailer or marketplace region does not match.")
    else:
        region_score = 0.7
        reasons.append(
            "The source is broadly useful, but local price and availability still need confirmation."
        )

    expected_currency = REGION_CURRENCIES.get(target)
    if metadata.currency is not None and expected_currency is not None:
        if metadata.currency == expected_currency:
            region_score += 0.05
            reasons.append("The listing currency matches the shopper region.")
        elif not metadata.cross_border_allowed:
            region_score -= 0.25
            reasons.append("The listing currency does not match the shopper region.")

    if metadata.ships_to_target_region is True:
        region_score += 0.05
        reasons.append("Shipping to the target region is confirmed.")
    elif metadata.ships_to_target_region is False:
        region_score -= 0.4
        reasons.append("The source does not ship to the target region.")

    region_score = round(min(1.0, max(0.0, region_score)), 2)
    if region_score >= 0.8:
        level = RegionRelevanceLevel.MATCH
    elif region_score >= 0.45:
        level = RegionRelevanceLevel.PARTIAL
    else:
        level = RegionRelevanceLevel.MISMATCH
    return region_score, level, reasons


def _apply_metadata_heuristics(
    score: float,
    rule: _DomainRule,
    metadata: SourceQualityMetadata,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    if metadata.sold_by_domain_owner is True:
        score += 0.15
        reasons.append("The domain owner is the seller of record.")
    if metadata.official_store_verified is True:
        score += 0.1
        reasons.append("The listing has a verified official-store signal.")
    if metadata.third_party_seller is True:
        score -= 0.05
        reasons.append("A third-party seller controls the offer.")
    if metadata.seller_identity_known is False:
        score -= 0.12
        reasons.append("The seller identity is missing or unclear.")
    if metadata.return_policy_present is False:
        score -= 0.08
        reasons.append("A usable return policy was not found.")
    if metadata.local_warranty_present is False:
        score -= 0.1
        reasons.append("Local warranty coverage was not confirmed.")
    if metadata.contact_information_present is False:
        score -= 0.08
        reasons.append("Store contact information was not found.")
    if metadata.shipping_origin_known is False:
        score -= 0.07
        reasons.append("The shipping origin is unclear.")
    if metadata.product_identity_consistent is False:
        score -= 0.18
        reasons.append("Product identity or model details are inconsistent.")
    if metadata.suspicious_price:
        score -= 0.2
        reasons.append("The price is suspiciously low or otherwise implausible.")
    if metadata.off_platform_payment:
        score -= 0.3
        reasons.append("The seller attempts to move payment off-platform.")
    if metadata.currency is not None and metadata.target_region_code is not None:
        expected_currency = REGION_CURRENCIES.get(metadata.target_region_code)
        if expected_currency and metadata.currency != expected_currency:
            score -= 0.08
    if metadata.ships_to_target_region is False:
        score -= 0.12

    if rule.source_class == SourceClass.UNKNOWN and reasons:
        reasons.append("Unknown stores with suspicious metadata require manual review.")
    return score, reasons


def _quality_level(
    score: float,
    source_class: SourceClass,
    heuristic_reasons: list[str],
) -> SourceQualityLevel:
    if source_class == SourceClass.UNKNOWN and not heuristic_reasons:
        return SourceQualityLevel.UNKNOWN
    if score >= 0.85:
        return SourceQualityLevel.STRONG
    if score >= 0.65:
        return SourceQualityLevel.ADEQUATE
    if score >= 0.4:
        return SourceQualityLevel.MIXED
    return SourceQualityLevel.WEAK


def _is_tracking_query_key(key: str) -> bool:
    normalized = key.lower()
    return normalized.startswith("utm_") or normalized in _TRACKING_QUERY_KEYS


def _is_amazon_domain(domain: str) -> bool:
    return any(_domain_matches(domain, candidate) for candidate in _AMAZON_REGIONS)


def _matches_any(domain: str, candidates: set[str]) -> bool:
    return any(_domain_matches(domain, candidate) for candidate in candidates)


def _domain_matches(domain: str, candidate: str) -> bool:
    return domain == candidate or domain.endswith(f".{candidate}")
