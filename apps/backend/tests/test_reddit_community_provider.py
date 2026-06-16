from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.providers import (
    CommunityDiscussionProviderOptions,
    FakeSearchProvider,
    ProviderRunStatus,
    RedditCommunityDiscoveryProvider,
    TavilySearchProvider,
    build_community_discussion_provider,
)
from app.core.settings import Settings
from app.providers.fixtures import load_provider_fixture, provider_fixture_transport
from app.schemas.products import CanonicalProduct
from app.schemas.search_sources import (
    EvidenceTargetType,
    ProviderMetadata,
    SearchIntent,
    SearchQuery,
    SearchResult,
    SourceQualityLevel,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "providers"


def test_reddit_runtime_uses_the_configured_general_search_path() -> None:
    provider = build_community_discussion_provider(Settings(_env_file=None))  # type: ignore[call-arg]

    assert isinstance(provider, RedditCommunityDiscoveryProvider)


@pytest.mark.asyncio
async def test_reddit_fixture_replay_returns_thread_and_comment_context() -> None:
    fixture = load_provider_fixture(FIXTURE_DIR / "reddit_search.json")
    transport = provider_fixture_transport(fixture)
    product = CanonicalProduct(name="Portable Monitor")

    async with httpx.AsyncClient(transport=transport) as client:
        provider = RedditCommunityDiscoveryProvider(
            search_provider=TavilySearchProvider(
                api_key="recorded-test-key",
                client=client,
            ),
            now=lambda: datetime(2026, 6, 13, tzinfo=UTC),
        )
        result = await provider.search_discussions(
            "portable monitor owner experiences",
            products=(product,),
            options=CommunityDiscussionProviderOptions(
                region_code="PH",
                max_results=5,
            ),
        )

    assert result.status == ProviderRunStatus.SUCCEEDED
    assert result.capabilities.supports_domain_scoped_search is True
    assert result.capabilities.supports_public_page_extraction is False
    assert result.bundle is not None
    assert len(result.bundle.source_references) == 2
    assert len(result.bundle.discussions) == 2
    assert result.bundle.discussions[0].community_name == "Monitors"
    assert result.bundle.discussions[0].thread_id == "thread123"
    assert result.bundle.discussions[0].comment_id is None
    assert result.bundle.discussions[1].community_name == "UsbCHardware"
    assert result.bundle.discussions[1].comment_id == "comment789"
    assert result.bundle.evidence[0].target.target_type == EvidenceTargetType.PRODUCT
    assert result.bundle.evidence[0].target.product_id == product.product_id
    assert result.bundle.evidence[0].source_quality.level == SourceQualityLevel.WEAK
    assert result.bundle.evidence[0].qualitative_signal is True
    assert any(
        "anecdotal" in warning
        for warning in result.bundle.evidence[0].evidence_quality_warnings
    )
    assert any(
        "Full public Reddit content was not extracted" in gap.summary
        for gap in result.bundle.evidence_gaps
    )


@pytest.mark.asyncio
async def test_reddit_adapter_preserves_available_public_metadata() -> None:
    query = SearchQuery(query="fixture", intent=SearchIntent.REVIEW)
    search_result = SearchResult(
        query=query,
        url=(
            "https://www.reddit.com/r/OfficeChairs/comments/chair123/"
            "long_term_review/comment456/"
        ),
        title="Fixture Chair long-term review",
        snippet="Search excerpt that should be replaced by permitted extracted text.",
        provider=ProviderMetadata(
            provider_name="fixture-search",
            raw={
                "posted_at": "2026-05-20T08:30:00Z",
                "engagement_score": 142,
                "comment_count": 38,
                "recurring_signal": True,
                "extracted_public_text": (
                    "Fixture Chair owners repeatedly mention durable controls and "
                    "limited seat-depth adjustment."
                ),
            },
        ),
    )
    product = CanonicalProduct(name="Fixture Chair")
    provider = RedditCommunityDiscoveryProvider(
        search_provider=FakeSearchProvider(results=(search_result,)),
        now=lambda: datetime(2026, 6, 13, tzinfo=UTC),
    )

    result = await provider.search_discussions("fixture chair owner reports", (product,))

    assert result.bundle is not None
    discussion = result.bundle.discussions[0]
    evidence = result.bundle.evidence[0]
    assert discussion.posted_at == datetime(2026, 5, 20, 8, 30, tzinfo=UTC)
    assert discussion.engagement_score == 142
    assert discussion.comment_count == 38
    assert discussion.extracted_public_summary is not None
    assert discussion.extracted_public_summary.startswith("Fixture Chair owners")
    assert evidence.recurring_signal is True
    assert not any(
        "Full public Reddit content was not extracted" in gap.summary
        for gap in result.bundle.evidence_gaps
    )


@pytest.mark.asyncio
async def test_reddit_adapter_returns_explicit_gap_for_removed_content() -> None:
    search_result = SearchResult(
        query=SearchQuery(query="fixture", intent=SearchIntent.REVIEW),
        url="https://www.reddit.com/r/Monitors/comments/removed123/example/",
        title="[removed]",
        snippet="[deleted]",
        provider=ProviderMetadata(provider_name="fixture-search"),
    )
    provider = RedditCommunityDiscoveryProvider(
        search_provider=FakeSearchProvider(results=(search_result,))
    )

    result = await provider.search_discussions("removed fixture")

    assert result.bundle is not None
    assert result.bundle.evidence == ()
    assert len(result.bundle.evidence_gaps) == 1
    assert "inaccessible or too weak" in result.bundle.evidence_gaps[0].summary
    assert "deleted or removed" in (result.bundle.evidence_gaps[0].reason or "")


@pytest.mark.asyncio
async def test_reddit_adapter_warns_for_stale_low_context_discussion() -> None:
    search_result = SearchResult(
        query=SearchQuery(query="fixture", intent=SearchIntent.REVIEW),
        url="https://www.reddit.com/r/Monitors/comments/old123/old_review/",
        title="Fixture Monitor old owner report",
        snippet="Fixture Monitor owners mention intermittent cable issues.",
        provider=ProviderMetadata(
            provider_name="fixture-search",
            raw={"posted_at": "2023-01-10T08:30:00Z"},
        ),
    )
    product = CanonicalProduct(name="Fixture Monitor")
    provider = RedditCommunityDiscoveryProvider(
        search_provider=FakeSearchProvider(results=(search_result,)),
        now=lambda: datetime(2026, 6, 14, tzinfo=UTC),
    )

    result = await provider.search_discussions("fixture monitor issues", (product,))

    assert result.bundle is not None
    warnings = result.bundle.evidence[0].evidence_quality_warnings
    assert "Only a search-result excerpt was available." in warnings
    assert "At least one cited discussion is older than one year." in warnings
    assert "Discussion engagement metadata was unavailable." in warnings


@pytest.mark.asyncio
async def test_reddit_adapter_returns_gap_when_search_has_no_reddit_results() -> None:
    search_result = SearchResult(
        query=SearchQuery(query="fixture", intent=SearchIntent.REVIEW),
        url="https://example.com/not-reddit",
        title="Not Reddit",
        snippet="This result must be ignored by the Reddit adapter.",
        provider=ProviderMetadata(provider_name="fixture-search"),
    )
    provider = RedditCommunityDiscoveryProvider(
        search_provider=FakeSearchProvider(results=(search_result,))
    )

    result = await provider.search_discussions("fixture")

    assert result.bundle is not None
    assert result.bundle.source_references == ()
    assert result.bundle.discussions == ()
    assert result.bundle.evidence == ()
    assert result.bundle.evidence_gaps[0].source_id is None
    assert "No accessible public Reddit discussions" in (
        result.bundle.evidence_gaps[0].summary
    )
