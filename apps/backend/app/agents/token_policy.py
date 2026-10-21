from enum import StrEnum


def scaled_tokens(baseline: int) -> int:
    return (baseline * 4 + 2) // 3


OWNER_START_TOKENS = scaled_tokens(90_000)
SOURCE_START_TOKENS = scaled_tokens(30_000)


class CompletionPurpose(StrEnum):
    OWNER = "owner"
    SOURCE_MANAGER = "source_manager"
    SOURCE = "source"
    STRUCTURED = "structured"


SOURCE_AGENTS = frozenset(
    {
        "YouTubeReviewIntelligenceAgent",
        "RedditCommunityIntelligenceAgent",
        "AmazonProductIntelligenceAgent",
        "IKEAStoreIntelligenceAgent",
    }
)
STRUCTURED_AGENTS = frozenset(
    {
        "IntakeAgent",
        "ShoppingGuideAgent",
        "ShoppingScopeGuardrailClassifier",
        "QueryPlannerAgent",
        "DiscoveryAgent",
        "ExtractionAgent",
        "CategoryRouterAgent",
        "SellerListingTrustAgent",
        "VerifierCriticAgent",
    }
)


def completion_purpose(agent: str, contract: str | None = None) -> CompletionPurpose:
    if contract in {
        "CategoryAnalysis",
        "ShoppingBrief",
        "ShoppingGuideDecision",
        "ShoppingGuardrailResult",
        "SearchPlan",
        "DiscoveryModelOutput",
        "ExtractionAgentOutput",
        "ProductAnalysisRoute",
        "SellerListingTrustModelOutput",
        "_VerifierModelDecision",
    }:
        return CompletionPurpose.STRUCTURED
    name = agent.removeprefix("CartCart")
    if name in SOURCE_AGENTS:
        return CompletionPurpose.SOURCE
    if name == "SourceIntelligenceManagerAgent":
        return CompletionPurpose.SOURCE_MANAGER
    if name in STRUCTURED_AGENTS:
        return CompletionPurpose.STRUCTURED
    return CompletionPurpose.OWNER
