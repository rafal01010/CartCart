import pytest

from app.providers.source_quality import (
    MVP_TARGET_REGIONS,
    RegionRelevanceLevel,
    SourceClass,
    SourceEvidenceContext,
    SourceQualityMetadata,
    normalize_source_url,
    score_source_quality,
)
from app.schemas.search_sources import SourceQualityLevel


def test_normalizes_domains_and_removes_tracking_parameters() -> None:
    normalized_url, domain = normalize_source_url(
        "HTTPS://WWW.Amazon.COM/dp/example?tag=affiliate&utm_source=test&color=black#reviews"
    )

    assert domain == "amazon.com"
    assert normalized_url == "https://amazon.com/dp/example?color=black"


@pytest.mark.parametrize(
    ("url", "region", "expected_class"),
    [
        ("https://www.apple.com/ph/iphone/", "PH", SourceClass.OFFICIAL_MANUFACTURER),
        (
            "https://abenson.com/product",
            "PH",
            SourceClass.ESTABLISHED_RETAILER_FIRST_PARTY,
        ),
        (
            "https://petexpress.com.ph/item",
            "PH",
            SourceClass.ESTABLISHED_RETAILER_FIRST_PARTY,
        ),
        ("https://choice.com.au/product", "AU", SourceClass.REVIEW_TESTING),
        (
            "https://target.com/p/example",
            "US",
            SourceClass.ESTABLISHED_RETAILER_MIXED,
        ),
        (
            "https://nytimes.com/wirecutter/reviews/example",
            "US",
            SourceClass.REVIEW_EDITORIAL,
        ),
    ],
)
def test_scores_representative_source_classes(
    url: str,
    region: str,
    expected_class: SourceClass,
) -> None:
    assessment = score_source_quality(
        url,
        SourceQualityMetadata(target_region_code=region),
    )

    assert assessment.source_class == expected_class
    assert assessment.excluded is False
    assert assessment.quality.level in {
        SourceQualityLevel.MIXED,
        SourceQualityLevel.ADEQUATE,
        SourceQualityLevel.STRONG,
    }


def test_excludes_proxy_and_resale_platforms_as_purchase_evidence() -> None:
    assessment = score_source_quality(
        "https://buyee.jp/item/example",
        SourceQualityMetadata(
            target_region_code="JP",
            evidence_context=SourceEvidenceContext.PURCHASE,
        ),
    )

    assert assessment.source_class == SourceClass.RESELLER_IMPORT_PROXY
    assert assessment.excluded is True
    assert assessment.requires_trust_assessment is True
    assert assessment.quality.level == SourceQualityLevel.WEAK


def test_marketplace_requires_listing_trust_even_with_matching_region() -> None:
    assessment = score_source_quality(
        "https://shopee.ph/example",
        SourceQualityMetadata(target_region_code="PH", currency="PHP"),
    )

    assert assessment.source_class == SourceClass.OPEN_MARKETPLACE
    assert assessment.requires_trust_assessment is True
    assert assessment.region_relevance == RegionRelevanceLevel.MATCH
    assert assessment.quality.level == SourceQualityLevel.MIXED


def test_suspicious_unknown_store_is_weak_but_not_automatically_excluded() -> None:
    assessment = score_source_quality(
        "https://cheap-perfect-products.example/deal",
        SourceQualityMetadata(
            target_region_code="CA",
            currency="USD",
            seller_identity_known=False,
            return_policy_present=False,
            contact_information_present=False,
            shipping_origin_known=False,
            product_identity_consistent=False,
            suspicious_price=True,
            off_platform_payment=True,
        ),
    )

    assert assessment.source_class == SourceClass.UNKNOWN
    assert assessment.excluded is False
    assert assessment.quality.level == SourceQualityLevel.WEAK
    assert assessment.quality.score == 0.0
    assert any("manual review" in reason for reason in assessment.reasons)


def test_unknown_source_defaults_to_unknown_without_exclusion() -> None:
    assessment = score_source_quality("https://new-store.example/product")

    assert assessment.source_class == SourceClass.UNKNOWN
    assert assessment.excluded is False
    assert assessment.quality.level == SourceQualityLevel.UNKNOWN
    assert assessment.quality.score == 0.25


def test_price_comparison_source_requires_actual_shop_assessment() -> None:
    assessment = score_source_quality(
        "https://kakaku.com/item/example",
        SourceQualityMetadata(target_region_code="JP"),
    )

    assert assessment.source_class == SourceClass.PRICE_COMPARISON
    assert assessment.requires_trust_assessment is True
    assert assessment.quality.level == SourceQualityLevel.WEAK


def test_only_facebook_marketplace_is_excluded() -> None:
    marketplace = score_source_quality(
        "https://facebook.com/marketplace/item/example"
    )
    ordinary_page = score_source_quality("https://facebook.com/example-brand")

    assert marketplace.excluded is True
    assert ordinary_page.source_class == SourceClass.UNKNOWN
    assert ordinary_page.excluded is False


def test_reddit_remains_qualitative_even_with_good_signal_metadata() -> None:
    assessment = score_source_quality(
        "https://www.reddit.com/r/BuyItForLife/comments/example",
        SourceQualityMetadata(
            target_region_code="US",
            evidence_context=SourceEvidenceContext.COMMUNITY,
            recurring_community_signal=True,
            community_engagement_available=True,
            community_source_recent=True,
        ),
    )

    assert assessment.source_class == SourceClass.COMMUNITY
    assert assessment.quality.level == SourceQualityLevel.MIXED
    assert assessment.quality.score == 0.4
    assert any("qualitative" in reason for reason in assessment.reasons)


def test_amazon_listing_and_review_context_remain_marketplace_specific() -> None:
    listing = score_source_quality(
        "https://amazon.ca/dp/example",
        SourceQualityMetadata(
            target_region_code="CA",
            evidence_context=SourceEvidenceContext.PURCHASE,
            sold_by_domain_owner=True,
            third_party_seller=False,
            currency="CAD",
        ),
    )
    review = score_source_quality(
        "https://amazon.ca/product-reviews/example",
        SourceQualityMetadata(
            target_region_code="CA",
            evidence_context=SourceEvidenceContext.REVIEW,
            currency="CAD",
        ),
    )

    assert listing.requires_trust_assessment is True
    assert listing.quality.score > review.quality.score
    assert any("listing, seller" in reason for reason in listing.reasons)
    assert any("variant-mixing" in reason for reason in review.reasons)


def test_ikea_quality_is_region_specific() -> None:
    matching = score_source_quality(
        "https://www.ikea.com/sg/en/p/example/",
        SourceQualityMetadata(target_region_code="SG", currency="SGD"),
    )
    mismatched = score_source_quality(
        "https://www.ikea.com/us/en/p/example/",
        SourceQualityMetadata(target_region_code="SG", currency="USD"),
    )

    assert matching.source_class == SourceClass.OFFICIAL_STORE_REGIONAL
    assert matching.region_relevance == RegionRelevanceLevel.MATCH
    assert matching.quality.level == SourceQualityLevel.STRONG
    assert mismatched.region_relevance == RegionRelevanceLevel.MISMATCH
    assert mismatched.quality.score < matching.quality.score


def test_region_scoring_penalizes_currency_and_shipping_mismatch_predictably() -> None:
    matching = score_source_quality(
        "https://www.jbhifi.com.au/products/example",
        SourceQualityMetadata(
            target_region_code="AU",
            currency="AUD",
            ships_to_target_region=True,
        ),
    )
    mismatched = score_source_quality(
        "https://www.jbhifi.com.au/products/example",
        SourceQualityMetadata(
            target_region_code="NZ",
            currency="AUD",
            ships_to_target_region=False,
        ),
    )

    assert matching.region_relevance_score == 1.0
    assert mismatched.region_relevance_score == 0.0
    assert mismatched.quality.score < matching.quality.score


def test_seed_covers_all_owner_approved_mvp_regions() -> None:
    assert MVP_TARGET_REGIONS == {
        "PH",
        "US",
        "KR",
        "CA",
        "JP",
        "SG",
        "MO",
        "AU",
        "NZ",
        "HK",
        "TW",
    }
