from enum import StrEnum

from pydantic import Field, model_validator

from app.schemas.base import CartCartBaseModel, VersionedSchema


class AgentStatus(StrEnum):
    REQUIRED_MVP = "required-mvp"
    CANDIDATE_MVP = "candidate-mvp"
    PROPOSED_LATER = "proposed-later"
    IMPLEMENTED = "implemented"


class AgentKind(StrEnum):
    ORCHESTRATOR = "orchestrator"
    WORKFLOW_STEP = "workflow_step"
    ROUTER = "router"
    DOMAIN_ANALYST = "domain_analyst"
    SPECIALIST_ANALYST = "specialist_analyst"
    TRUST_ANALYST = "trust_analyst"
    SOURCE_INTELLIGENCE = "source_intelligence"
    DECISION = "decision"
    VERIFIER = "verifier"


class InvocationMode(StrEnum):
    APPLICATION_CODE = "application_code"
    TYPED_STEP = "typed_step"
    TOOL_SUBRUN = "tool_subrun"
    DOMAIN_TOOL_SUBRUN = "domain_tool_subrun"
    SPECIALIST_TOOL_SUBRUN = "specialist_tool_subrun"
    REUSABLE_SOURCE_TOOL = "reusable_source_tool"
    FINAL_TYPED_STEP = "final_typed_step"
    NOT_IMPLEMENTED = "not_implemented"


class AgentCatalogEntry(VersionedSchema):
    agent_name: str = Field(min_length=1, max_length=200)
    status: AgentStatus
    kind: AgentKind
    invocation_mode: InvocationMode
    contract_name: str | None = Field(default=None, min_length=1, max_length=200)
    parent_agent_name: str | None = Field(default=None, min_length=1, max_length=200)
    routing_categories: tuple[str, ...] = Field(default_factory=tuple)
    fallback_agent_names: tuple[str, ...] = Field(default_factory=tuple)
    provider_requirements: tuple[str, ...] = Field(default_factory=tuple)
    output_schema: str | None = Field(default=None, min_length=1, max_length=200)
    is_reusable_source_agent: bool = False

    @model_validator(mode="after")
    def _source_agents_require_source_kind(self) -> "AgentCatalogEntry":
        if self.is_reusable_source_agent and self.kind != AgentKind.SOURCE_INTELLIGENCE:
            raise ValueError("reusable source agents require source_intelligence kind.")
        return self


class ProductAnalysisRoute(CartCartBaseModel):
    category: str | None = None
    agent_path: tuple[str, ...] = Field(min_length=1)
    fallback_agent_names: tuple[str, ...] = Field(default_factory=tuple)


class AgentCatalog(VersionedSchema):
    entries: dict[str, AgentCatalogEntry] = Field(min_length=1)
    product_category_routes: dict[str, str] = Field(default_factory=dict)
    technology_category_keywords: tuple[str, ...] = Field(default_factory=tuple)
    reusable_source_agent_names: tuple[str, ...] = Field(default_factory=tuple)
    generic_fallback_agent_name: str = "GenericProductAnalystAgent"
    technology_domain_agent_name: str = "TechnologyDomainAnalystAgent"

    @model_validator(mode="after")
    def _validate_catalog_references(self) -> "AgentCatalog":
        for key, entry in self.entries.items():
            if key != entry.agent_name:
                raise ValueError("catalog entry keys must match agent_name.")
            self._require_known_agent(entry.parent_agent_name, "parent")
            for fallback_name in entry.fallback_agent_names:
                self._require_known_agent(fallback_name, "fallback")

        self._require_known_agent(self.generic_fallback_agent_name, "generic fallback")
        self._require_known_agent(self.technology_domain_agent_name, "technology domain")

        for route_target in self.product_category_routes.values():
            self._require_known_agent(route_target, "category route")
            if self.entries[route_target].kind != AgentKind.SPECIALIST_ANALYST:
                raise ValueError("product category routes must target specialists.")

        for source_agent_name in self.reusable_source_agent_names:
            self._require_known_agent(source_agent_name, "source agent")
            if not self.entries[source_agent_name].is_reusable_source_agent:
                raise ValueError("reusable source agent names must target source agents.")
        return self

    def get(self, agent_name: str) -> AgentCatalogEntry | None:
        return self.entries.get(agent_name)

    def require(self, agent_name: str) -> AgentCatalogEntry:
        entry = self.get(agent_name)
        if entry is None:
            raise KeyError(agent_name)
        return entry

    def route_product_analysis(self, category: str | None) -> ProductAnalysisRoute:
        normalized_category = _normalize_category(category)
        if normalized_category is None:
            return self._generic_route(category)

        specialist_name = self._specialist_for_category(normalized_category)
        if specialist_name is not None:
            specialist = self.require(specialist_name)
            return ProductAnalysisRoute(
                category=category,
                agent_path=(self.technology_domain_agent_name, specialist.agent_name),
                fallback_agent_names=specialist.fallback_agent_names,
            )

        if self._is_technology_category(normalized_category):
            technology_domain = self.require(self.technology_domain_agent_name)
            return ProductAnalysisRoute(
                category=category,
                agent_path=(technology_domain.agent_name,),
                fallback_agent_names=technology_domain.fallback_agent_names,
            )

        return self._generic_route(category)

    def reusable_source_agents(self) -> tuple[AgentCatalogEntry, ...]:
        return tuple(self.require(name) for name in self.reusable_source_agent_names)

    def _generic_route(self, category: str | None) -> ProductAnalysisRoute:
        generic = self.require(self.generic_fallback_agent_name)
        return ProductAnalysisRoute(
            category=category,
            agent_path=(generic.agent_name,),
            fallback_agent_names=generic.fallback_agent_names,
        )

    def _is_technology_category(self, normalized_category: str) -> bool:
        for keyword in self.technology_category_keywords:
            normalized_keyword = _normalize_category(keyword)
            if normalized_keyword is not None and _category_matches(
                normalized_category,
                normalized_keyword,
            ):
                return True
        return False

    def _specialist_for_category(self, normalized_category: str) -> str | None:
        for route_category, specialist_name in self.product_category_routes.items():
            normalized_route_category = _normalize_category(route_category)
            if normalized_route_category is None:
                continue
            if _category_matches(normalized_category, normalized_route_category):
                return specialist_name
        return None

    def _require_known_agent(self, agent_name: str | None, label: str) -> None:
        if agent_name is not None and agent_name not in self.entries:
            raise ValueError(f"unknown {label} agent: {agent_name}")


def build_default_agent_catalog() -> AgentCatalog:
    return AgentCatalog(
        entries=_DEFAULT_AGENT_ENTRIES,
        product_category_routes=_DEFAULT_PRODUCT_CATEGORY_ROUTES,
        technology_category_keywords=_DEFAULT_TECHNOLOGY_CATEGORY_KEYWORDS,
        reusable_source_agent_names=(
            "YouTubeReviewIntelligenceAgent",
            "RedditCommunityIntelligenceAgent",
            "AmazonProductIntelligenceAgent",
            "IKEAStoreIntelligenceAgent",
        ),
    )


def _entry(
    agent_name: str,
    *,
    status: AgentStatus,
    kind: AgentKind,
    invocation_mode: InvocationMode,
    contract_name: str | None = None,
    parent_agent_name: str | None = None,
    routing_categories: tuple[str, ...] = (),
    fallback_agent_names: tuple[str, ...] = (),
    provider_requirements: tuple[str, ...] = (),
    output_schema: str | None = None,
    is_reusable_source_agent: bool = False,
) -> AgentCatalogEntry:
    return AgentCatalogEntry(
        agent_name=agent_name,
        status=status,
        kind=kind,
        invocation_mode=invocation_mode,
        contract_name=contract_name,
        parent_agent_name=parent_agent_name,
        routing_categories=routing_categories,
        fallback_agent_names=fallback_agent_names,
        provider_requirements=provider_requirements,
        output_schema=output_schema,
        is_reusable_source_agent=is_reusable_source_agent,
    )


def _normalize_category(category: str | None) -> str | None:
    if category is None:
        return None
    normalized = " ".join(category.strip().lower().replace("/", " ").split())
    return normalized or None


def _category_matches(normalized_category: str, normalized_route_category: str) -> bool:
    if normalized_category == normalized_route_category:
        return True
    if " " in normalized_route_category:
        return normalized_route_category in normalized_category
    return normalized_route_category in set(normalized_category.split())


_DEFAULT_TECHNOLOGY_CATEGORY_KEYWORDS = (
    "technology",
    "tech",
    "electronics",
    "computer",
    "gaming",
    "monitor",
    "display",
    "smartphone",
    "phone",
    "mobile phone",
    "laptop",
    "notebook",
    "earphones",
    "headphones",
    "earbuds",
    "headset",
    "tv",
    "television",
    "smartwatch",
    "smart watch",
    "wearable",
    "mouse",
    "keyboard",
    "router",
)


_DEFAULT_PRODUCT_CATEGORY_ROUTES = {
    "monitor": "MonitorSpecialistAgent",
    "display": "MonitorSpecialistAgent",
    "smartphone": "SmartphoneSpecialistAgent",
    "phone": "SmartphoneSpecialistAgent",
    "mobile phone": "SmartphoneSpecialistAgent",
    "laptop": "LaptopSpecialistAgent",
    "notebook": "LaptopSpecialistAgent",
    "earphones": "EarphonesHeadphonesSpecialistAgent",
    "headphones": "EarphonesHeadphonesSpecialistAgent",
    "earbuds": "EarphonesHeadphonesSpecialistAgent",
    "headset": "EarphonesHeadphonesSpecialistAgent",
    "tv": "TVSpecialistAgent",
    "television": "TVSpecialistAgent",
    "smartwatch": "SmartwatchSpecialistAgent",
    "smart watch": "SmartwatchSpecialistAgent",
}


_DEFAULT_AGENT_ENTRIES = {
    "ShoppingRunOrchestrator": _entry(
        "ShoppingRunOrchestrator",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.ORCHESTRATOR,
        invocation_mode=InvocationMode.APPLICATION_CODE,
        contract_name="ShoppingRunOrchestrator",
        output_schema="Persisted workflow state",
    ),
    "IntakeAgent": _entry(
        "IntakeAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.WORKFLOW_STEP,
        invocation_mode=InvocationMode.TYPED_STEP,
        contract_name="IntakeAgent",
        output_schema="ShoppingBrief",
    ),
    "QueryPlannerAgent": _entry(
        "QueryPlannerAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.WORKFLOW_STEP,
        invocation_mode=InvocationMode.TYPED_STEP,
        contract_name="QueryPlannerAgent",
        output_schema="SearchPlan",
    ),
    "DiscoveryAgent": _entry(
        "DiscoveryAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.WORKFLOW_STEP,
        invocation_mode=InvocationMode.TYPED_STEP,
        contract_name="DiscoveryAgent",
        output_schema="DiscoveryAgentOutput",
    ),
    "ExtractionReviewAgent": _entry(
        "ExtractionReviewAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.WORKFLOW_STEP,
        invocation_mode=InvocationMode.TOOL_SUBRUN,
        contract_name="ExtractionReviewAgent",
        output_schema="ExtractionReviewAgentOutput",
    ),
    "DeduplicationReviewAgent": _entry(
        "DeduplicationReviewAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.WORKFLOW_STEP,
        invocation_mode=InvocationMode.TOOL_SUBRUN,
        contract_name="DeduplicationReviewAgent",
        output_schema="DeduplicationDecision",
    ),
    "CategoryRouterAgent": _entry(
        "CategoryRouterAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.ROUTER,
        invocation_mode=InvocationMode.APPLICATION_CODE,
        contract_name="AgentCatalog.route_product_analysis",
        output_schema="ProductAnalysisRoute",
    ),
    "GenericProductAnalystAgent": _entry(
        "GenericProductAnalystAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.SPECIALIST_ANALYST,
        invocation_mode=InvocationMode.SPECIALIST_TOOL_SUBRUN,
        contract_name="GenericProductAnalystAgent",
        routing_categories=("generic", "*"),
        output_schema="CategoryAnalysis",
    ),
    "TechnologyDomainAnalystAgent": _entry(
        "TechnologyDomainAnalystAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.DOMAIN_ANALYST,
        invocation_mode=InvocationMode.DOMAIN_TOOL_SUBRUN,
        contract_name="TechnologyDomainAnalystAgent",
        routing_categories=_DEFAULT_TECHNOLOGY_CATEGORY_KEYWORDS,
        fallback_agent_names=("GenericProductAnalystAgent",),
        output_schema="CategoryAnalysis",
    ),
    "MonitorSpecialistAgent": _entry(
        "MonitorSpecialistAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.SPECIALIST_ANALYST,
        invocation_mode=InvocationMode.SPECIALIST_TOOL_SUBRUN,
        contract_name="MonitorSpecialistAgent",
        parent_agent_name="TechnologyDomainAnalystAgent",
        routing_categories=("monitor", "display"),
        fallback_agent_names=(
            "TechnologyDomainAnalystAgent",
            "GenericProductAnalystAgent",
        ),
        output_schema="CategoryAnalysis",
    ),
    "SmartphoneSpecialistAgent": _entry(
        "SmartphoneSpecialistAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.SPECIALIST_ANALYST,
        invocation_mode=InvocationMode.SPECIALIST_TOOL_SUBRUN,
        contract_name="SmartphoneSpecialistAgent",
        parent_agent_name="TechnologyDomainAnalystAgent",
        routing_categories=("smartphone", "phone", "mobile phone"),
        fallback_agent_names=(
            "TechnologyDomainAnalystAgent",
            "GenericProductAnalystAgent",
        ),
        output_schema="CategoryAnalysis",
    ),
    "LaptopSpecialistAgent": _entry(
        "LaptopSpecialistAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.SPECIALIST_ANALYST,
        invocation_mode=InvocationMode.SPECIALIST_TOOL_SUBRUN,
        contract_name="LaptopSpecialistAgent",
        parent_agent_name="TechnologyDomainAnalystAgent",
        routing_categories=("laptop", "notebook"),
        fallback_agent_names=(
            "TechnologyDomainAnalystAgent",
            "GenericProductAnalystAgent",
        ),
        output_schema="CategoryAnalysis",
    ),
    "EarphonesHeadphonesSpecialistAgent": _entry(
        "EarphonesHeadphonesSpecialistAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.SPECIALIST_ANALYST,
        invocation_mode=InvocationMode.SPECIALIST_TOOL_SUBRUN,
        contract_name="EarphonesHeadphonesSpecialistAgent",
        parent_agent_name="TechnologyDomainAnalystAgent",
        routing_categories=("earphones", "headphones", "earbuds", "headset"),
        fallback_agent_names=(
            "TechnologyDomainAnalystAgent",
            "GenericProductAnalystAgent",
        ),
        output_schema="CategoryAnalysis",
    ),
    "TVSpecialistAgent": _entry(
        "TVSpecialistAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.SPECIALIST_ANALYST,
        invocation_mode=InvocationMode.SPECIALIST_TOOL_SUBRUN,
        contract_name="TVSpecialistAgent",
        parent_agent_name="TechnologyDomainAnalystAgent",
        routing_categories=("tv", "television"),
        fallback_agent_names=(
            "TechnologyDomainAnalystAgent",
            "GenericProductAnalystAgent",
        ),
        output_schema="CategoryAnalysis",
    ),
    "SmartwatchSpecialistAgent": _entry(
        "SmartwatchSpecialistAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.SPECIALIST_ANALYST,
        invocation_mode=InvocationMode.SPECIALIST_TOOL_SUBRUN,
        contract_name="SmartwatchSpecialistAgent",
        parent_agent_name="TechnologyDomainAnalystAgent",
        routing_categories=("smartwatch", "smart watch"),
        fallback_agent_names=(
            "TechnologyDomainAnalystAgent",
            "GenericProductAnalystAgent",
        ),
        output_schema="CategoryAnalysis",
    ),
    "SellerListingTrustAgent": _entry(
        "SellerListingTrustAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.TRUST_ANALYST,
        invocation_mode=InvocationMode.TYPED_STEP,
        contract_name="SellerListingTrustAgent",
        output_schema="ListingTrustAssessment",
    ),
    "YouTubeReviewIntelligenceAgent": _entry(
        "YouTubeReviewIntelligenceAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.SOURCE_INTELLIGENCE,
        invocation_mode=InvocationMode.REUSABLE_SOURCE_TOOL,
        contract_name="YouTubeReviewIntelligenceAgent",
        provider_requirements=(
            "youtube_video_metadata_provider_optional",
            "authorized_caption_or_approved_transcript_provider_optional",
        ),
        output_schema="VideoReviewEvidenceBundle",
        is_reusable_source_agent=True,
    ),
    "RedditCommunityIntelligenceAgent": _entry(
        "RedditCommunityIntelligenceAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.SOURCE_INTELLIGENCE,
        invocation_mode=InvocationMode.REUSABLE_SOURCE_TOOL,
        contract_name="RedditCommunityIntelligenceAgent",
        provider_requirements=(
            "reddit_community_discussion_provider_optional",
            "domain_scoped_reddit_search_provider_optional",
            "permitted_public_page_extraction_optional",
        ),
        output_schema="CommunityDiscussionEvidenceBundle",
        is_reusable_source_agent=True,
    ),
    "AmazonProductIntelligenceAgent": _entry(
        "AmazonProductIntelligenceAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.SOURCE_INTELLIGENCE,
        invocation_mode=InvocationMode.REUSABLE_SOURCE_TOOL,
        contract_name="AmazonProductIntelligenceAgent",
        provider_requirements=(
            "amazon_product_intelligence_provider_optional",
            "amazon_listing_identity_provider_optional",
            "amazon_review_signal_provider_optional",
            "regional_ship_to_evidence_provider_optional",
        ),
        output_schema="AmazonProductEvidenceBundle",
        is_reusable_source_agent=True,
    ),
    "IKEAStoreIntelligenceAgent": _entry(
        "IKEAStoreIntelligenceAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.SOURCE_INTELLIGENCE,
        invocation_mode=InvocationMode.REUSABLE_SOURCE_TOOL,
        contract_name="IKEAStoreIntelligenceAgent",
        provider_requirements=(
            "ikea_regional_official_store_provider_optional",
            "ikea_product_page_provider_optional",
            "ikea_store_delivery_evidence_provider_optional",
        ),
        output_schema="IKEAStoreEvidenceBundle",
        is_reusable_source_agent=True,
    ),
    "ComparisonDecisionAgent": _entry(
        "ComparisonDecisionAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.DECISION,
        invocation_mode=InvocationMode.TYPED_STEP,
        contract_name="ComparisonDecisionAgent",
        output_schema="RecommendationBundle",
    ),
    "VerifierCriticAgent": _entry(
        "VerifierCriticAgent",
        status=AgentStatus.REQUIRED_MVP,
        kind=AgentKind.VERIFIER,
        invocation_mode=InvocationMode.FINAL_TYPED_STEP,
        contract_name="VerifierCriticAgent",
        output_schema="VerificationReport",
    ),
}


DEFAULT_AGENT_CATALOG = build_default_agent_catalog()
