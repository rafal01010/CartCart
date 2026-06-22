from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from app.agents import LiveRedditCommunityIntelligenceAgent
from app.agents.contracts import RedditCommunityIntelligenceAgentInput
from app.providers import (
    CommunityDiscussionProviderOptions,
    CommunityDiscussionProviderResult,
    ProviderCapabilityFlags,
    ProviderRunStatus,
)
from app.schemas.analysis import RecommendationBundle
from app.schemas.ids import new_id
from app.schemas.intake import FieldSource, ShoppingBrief
from app.schemas.products import CanonicalProduct, ProductListing, SellerProfile
from app.schemas.regions import Region
from app.schemas.search_sources import (
    CommunityDiscussionContext,
    CommunityDiscussionEvidenceBundle,
    EvidenceTargetType,
    SourceEvidenceGap,
    SourceIntelligenceCapability,
    SourceQuality,
    SourceQualityLevel,
)
from app.schemas.source_references import SourceReference


@pytest.mark.asyncio
async def test_reddit_agent_creates_recurring_qualitative_complaint_evidence() -> None:
    product, listing = _product_and_listing()
    provider = _FixtureCommunityProvider(bundle=_recurring_complaint_bundle())
    agent = LiveRedditCommunityIntelligenceAgent(
        community_provider=provider,
        now=lambda: datetime(2026, 6, 21, tzinfo=UTC),
    )

    output = await agent.run(
        RedditCommunityIntelligenceAgentInput(
            run_id=new_id(),
            brief=_brief(),
            products=(product,),
            listings=(listing,),
            community_queries=("fixture headphones owner complaints reddit",),
        )
    )

    assert not isinstance(output, RecommendationBundle)
    assert len(output.source_references) >= 2
    assert {"headphones", "HeadphoneAdvice"} <= {
        discussion.community_name for discussion in output.discussions
    }
    assert {"hp123", "hp456"} <= {
        discussion.thread_id for discussion in output.discussions
    }
    recurring = [
        item for item in output.evidence if item.claim == "ear pads split after months"
    ]
    assert len(recurring) == 1
    evidence = recurring[0]
    assert evidence.target.target_type == EvidenceTargetType.PRODUCT
    assert evidence.target.product_id == product.product_id
    assert evidence.recurring_signal is True
    assert evidence.qualitative_signal is True
    assert set(evidence.context_source_ids) == {
        output.discussions[0].source_id,
        output.discussions[1].source_id,
    }
    warning_text = " ".join(evidence.evidence_quality_warnings).casefold()
    assert "qualitative" in warning_text
    assert "authoritative product fact" in warning_text
    assert "brigaded" in warning_text
    assert "astroturfed" in warning_text
    assert [activity["tool_name"] for activity in agent.workbench_activity] == [
        "CommunityDiscussionProvider.search_discussions",
        "CommunityEvidenceCreator.create",
    ]


@pytest.mark.asyncio
async def test_reddit_agent_selects_relevant_discussions_before_summarizing() -> None:
    product, listing = _product_and_listing()
    provider = _FixtureCommunityProvider(bundle=_recurring_complaint_bundle())
    agent = LiveRedditCommunityIntelligenceAgent(
        community_provider=provider,
        max_discussions=2,
        now=lambda: datetime(2026, 6, 21, tzinfo=UTC),
    )

    output = await agent.run(
        RedditCommunityIntelligenceAgentInput(
            run_id=new_id(),
            brief=_brief(),
            products=(product,),
            listings=(listing,),
            community_queries=("fixture headphones owner complaints reddit",),
        )
    )

    assert len(output.discussions) == 2
    assert all(
        "coffee" not in discussion.thread_title.casefold()
        for discussion in output.discussions
        if discussion.thread_title is not None
    )
    assert all(
        "coffee" not in (reference.title or "").casefold()
        for reference in output.source_references
    )
    assert output.evidence
    assert all(
        set(item.context_source_ids).issubset(
            {discussion.source_id for discussion in output.discussions}
        )
        for item in output.evidence
    )


@pytest.mark.asyncio
async def test_reddit_agent_preserves_inaccessible_content_gap() -> None:
    product, listing = _product_and_listing()
    provider = _FixtureCommunityProvider(bundle=_inaccessible_bundle())
    agent = LiveRedditCommunityIntelligenceAgent(community_provider=provider)

    output = await agent.run(
        RedditCommunityIntelligenceAgentInput(
            run_id=new_id(),
            brief=_brief(),
            products=(product,),
            listings=(listing,),
            community_queries=("fixture headphones inaccessible reddit",),
        )
    )

    assert not isinstance(output, RecommendationBundle)
    assert output.evidence == ()
    assert output.evidence_gaps
    gap_text = " ".join(
        f"{gap.summary} {gap.reason or ''}" for gap in output.evidence_gaps
    ).casefold()
    assert "inaccessible" in gap_text
    assert "deleted" in gap_text or "removed" in gap_text
    assert output.evidence_gaps[0].capability == (
        SourceIntelligenceCapability.COMMUNITY_DISCUSSION
    )


@pytest.mark.asyncio
async def test_reddit_agent_returns_gap_when_provider_disabled() -> None:
    product, listing = _product_and_listing()
    provider = _FixtureCommunityProvider(disabled=True)
    agent = LiveRedditCommunityIntelligenceAgent(community_provider=provider)

    output = await agent.run(
        RedditCommunityIntelligenceAgentInput(
            run_id=new_id(),
            brief=_brief(),
            products=(product,),
            listings=(listing,),
            community_queries=("fixture headphones reddit",),
        )
    )

    assert output.source_references == ()
    assert output.discussions == ()
    assert output.evidence == ()
    assert output.evidence_gaps
    assert "disabled" in (output.evidence_gaps[0].reason or "").casefold()


def _brief() -> ShoppingBrief:
    return ShoppingBrief(
        original_query="I need comfortable headphones for commuting.",
        category="headphones",
        category_source=FieldSource.INFERRED,
        region={
            "region": Region(country_code="US", currency="USD"),
            "source": FieldSource.USER_PROVIDED,
        },
    )


def _product_and_listing() -> tuple[CanonicalProduct, ProductListing]:
    source_id = new_id()
    product = CanonicalProduct(
        name="Fixture Headphones",
        brand="Fixture",
        model="Headphones 1",
        category="headphones",
        source_ids=(source_id,),
    )
    listing = ProductListing(
        product_id=product.product_id,
        title="Fixture Headphones - Official Store",
        url="https://example.com/headphones/fixture-headphones",
        seller=SellerProfile(seller_name="Fixture Official"),
        source_ids=(source_id,),
    )
    product = product.model_copy(update={"listing_ids": (listing.listing_id,)})
    return product, listing


def _recurring_complaint_bundle() -> CommunityDiscussionEvidenceBundle:
    first_source_id = new_id()
    second_source_id = new_id()
    unrelated_source_id = new_id()
    first_url = "https://www.reddit.com/r/headphones/comments/hp123/ear_pads_split/"
    second_url = "https://www.reddit.com/r/HeadphoneAdvice/comments/hp456/owner_feedback/comment789/"
    unrelated_url = "https://www.reddit.com/r/Coffee/comments/cf123/grinder_burrs/"
    return CommunityDiscussionEvidenceBundle(
        source_references=(
            SourceReference(
                source_id=first_source_id,
                url=first_url,
                title="Fixture headphones long-term owner thread",
            ),
            SourceReference(
                source_id=second_source_id,
                url=second_url,
                title="Fixture Headphones owner feedback",
            ),
            SourceReference(
                source_id=unrelated_source_id,
                url=unrelated_url,
                title="Coffee grinder burr discussion",
            ),
        ),
        discussions=(
            CommunityDiscussionContext(
                source_id=first_source_id,
                url=first_url,
                community_name="headphones",
                thread_id="hp123",
                thread_title="Fixture headphones long-term owner thread",
                comment_count=44,
                extracted_public_summary=(
                    "Owners report ear pads split after months. Several also "
                    "mention clamp discomfort after long sessions."
                ),
            ),
            CommunityDiscussionContext(
                source_id=second_source_id,
                url=second_url,
                community_name="HeadphoneAdvice",
                thread_id="hp456",
                comment_id="comment789",
                thread_title="Fixture Headphones owner feedback",
                engagement_score=91,
                extracted_public_summary=(
                    "Users say ear pads split after months with daily use. One "
                    "comment says replacement pads helped comfort."
                ),
            ),
            CommunityDiscussionContext(
                source_id=unrelated_source_id,
                url=unrelated_url,
                community_name="Coffee",
                thread_id="cf123",
                thread_title="Coffee grinder burr discussion",
                comment_count=20,
                extracted_public_summary=(
                    "Owners report burr alignment issues on a coffee grinder."
                ),
            ),
        ),
    )


def _inaccessible_bundle() -> CommunityDiscussionEvidenceBundle:
    source_id = new_id()
    url = "https://www.reddit.com/r/headphones/comments/deleted123/removed_thread/"
    return CommunityDiscussionEvidenceBundle(
        source_references=(
            SourceReference(
                source_id=source_id,
                url=url,
                title="Removed Reddit thread",
            ),
        ),
        discussions=(
            CommunityDiscussionContext(
                source_id=source_id,
                url=url,
                community_name="headphones",
                thread_id="deleted123",
                thread_title="Removed Reddit thread",
                extracted_public_summary=None,
            ),
        ),
        evidence_gaps=(
            SourceEvidenceGap(
                capability=SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
                source_id=source_id,
                summary="Public Reddit content was inaccessible.",
                reason="The public thread appears deleted or removed.",
                source_quality=SourceQuality(level=SourceQualityLevel.WEAK, score=0.1),
            ),
        ),
    )


@dataclass(frozen=True)
class _FixtureCommunityProvider:
    bundle: CommunityDiscussionEvidenceBundle | None = None
    disabled: bool = False
    provider_name: str = "test-reddit-community"

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name=self.provider_name,
            enabled=not self.disabled,
            supports_domain_scoped_search=True,
            supports_public_page_extraction=True,
            supports_community_discussion_retrieval=True,
        )

    async def search_discussions(
        self,
        query: str,
        products: tuple[CanonicalProduct, ...] = (),
        options: CommunityDiscussionProviderOptions | None = None,
    ) -> CommunityDiscussionProviderResult:
        del query, products, options
        if self.disabled:
            return CommunityDiscussionProviderResult(
                status=ProviderRunStatus.DISABLED,
                capabilities=self.capabilities,
                notes=("Community provider is disabled for this test.",),
            )
        assert self.bundle is not None
        return CommunityDiscussionProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            bundle=self.bundle,
        )
