from enum import StrEnum

from pydantic import Field

from app.agents.catalog import (
    DEFAULT_AGENT_CATALOG,
    AgentCatalog,
)
from app.schemas.base import VersionedSchema


GENERIC_FALLBACK_AGENT_NAME = "GenericProductAnalystAgent"
TECHNOLOGY_DOMAIN_AGENT_NAME = "TechnologyDomainAnalystAgent"
SPECIALIST_FALLBACK_CHAIN = (
    TECHNOLOGY_DOMAIN_AGENT_NAME,
    GENERIC_FALLBACK_AGENT_NAME,
)


class ProductAnalysisRoutingEvalKind(StrEnum):
    GENERIC_FALLBACK = "generic_fallback"
    TECHNOLOGY_DOMAIN = "technology_domain"
    MVP_SPECIALIST = "mvp_specialist"


class ProductAnalysisRoutingEvalCase(VersionedSchema):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    kind: ProductAnalysisRoutingEvalKind
    category: str = Field(min_length=1, max_length=120)
    shopper_query: str = Field(min_length=1, max_length=500)
    expected_agent_path: tuple[str, ...] = Field(min_length=1)
    expected_fallback_agent_names: tuple[str, ...] = Field(default_factory=tuple)


class ProductAnalysisRoutingEvalResult(VersionedSchema):
    case_name: str = Field(min_length=1, max_length=120)
    passed: bool
    actual_agent_path: tuple[str, ...] = Field(default_factory=tuple)
    actual_fallback_agent_names: tuple[str, ...] = Field(default_factory=tuple)
    expected_agent_path: tuple[str, ...] = Field(default_factory=tuple)
    expected_fallback_agent_names: tuple[str, ...] = Field(default_factory=tuple)
    failure_reason: str | None = Field(default=None, min_length=1, max_length=500)


class ProductAnalysisFallbackEvalCase(VersionedSchema):
    name: str = Field(min_length=1, max_length=120)
    specialist_agent_name: str = Field(min_length=1, max_length=120)
    own_category: str = Field(min_length=1, max_length=120)
    non_specialist_technology_category: str = Field(min_length=1, max_length=120)
    non_technology_category: str = Field(min_length=1, max_length=120)
    expected_specialist_agent_path: tuple[str, ...] = Field(min_length=2)
    expected_specialist_fallback_agent_names: tuple[str, ...] = Field(min_length=2)
    expected_technology_fallback_status: str = Field(min_length=1, max_length=120)
    expected_technology_fallback_agent_path: tuple[str, ...] = Field(
        default=(TECHNOLOGY_DOMAIN_AGENT_NAME,),
        min_length=1,
    )
    expected_technology_fallback_agent_names: tuple[str, ...] = Field(
        default=(GENERIC_FALLBACK_AGENT_NAME,),
    )
    expected_generic_fallback_status: str = Field(min_length=1, max_length=120)
    expected_generic_fallback_agent_path: tuple[str, ...] = Field(
        default=(GENERIC_FALLBACK_AGENT_NAME,),
        min_length=1,
    )
    expected_generic_fallback_agent_names: tuple[str, ...] = Field(default=())


def product_analysis_routing_eval_cases() -> tuple[
    ProductAnalysisRoutingEvalCase,
    ...,
]:
    return (
        ProductAnalysisRoutingEvalCase(
            name="routing/generic-office-chair",
            description="Broad non-technology categories use generic analysis.",
            kind=ProductAnalysisRoutingEvalKind.GENERIC_FALLBACK,
            category="office chair",
            shopper_query="Help me choose an ergonomic office chair.",
            expected_agent_path=(GENERIC_FALLBACK_AGENT_NAME,),
        ),
        ProductAnalysisRoutingEvalCase(
            name="routing/technology-keyboard-domain",
            description="Technology categories without MVP specialists use the domain layer.",
            kind=ProductAnalysisRoutingEvalKind.TECHNOLOGY_DOMAIN,
            category="gaming keyboard",
            shopper_query="Help me choose a quiet gaming keyboard.",
            expected_agent_path=(TECHNOLOGY_DOMAIN_AGENT_NAME,),
            expected_fallback_agent_names=(GENERIC_FALLBACK_AGENT_NAME,),
        ),
        *_mvp_specialist_routing_cases(),
    )


def product_analysis_fallback_eval_cases() -> tuple[
    ProductAnalysisFallbackEvalCase,
    ...,
]:
    return tuple(
        ProductAnalysisFallbackEvalCase(
            name=f"fallback/{slug}",
            specialist_agent_name=specialist_agent_name,
            own_category=category,
            non_specialist_technology_category="gaming keyboard",
            non_technology_category="office chair",
            expected_specialist_agent_path=(
                TECHNOLOGY_DOMAIN_AGENT_NAME,
                specialist_agent_name,
            ),
            expected_specialist_fallback_agent_names=SPECIALIST_FALLBACK_CHAIN,
            expected_technology_fallback_status=technology_fallback_status,
            expected_generic_fallback_status=generic_fallback_status,
        )
        for slug, category, specialist_agent_name, technology_fallback_status, generic_fallback_status in (
            (
                "monitor-to-domain-to-generic",
                "monitor",
                "MonitorSpecialistAgent",
                "technology_domain_fallback_non_monitor",
                "generic_fallback_non_monitor",
            ),
            (
                "smartphone-to-domain-to-generic",
                "smartphone",
                "SmartphoneSpecialistAgent",
                "technology_domain_fallback_non_phone",
                "generic_fallback_non_phone",
            ),
            (
                "laptop-to-domain-to-generic",
                "laptop",
                "LaptopSpecialistAgent",
                "technology_domain_fallback_non_laptop",
                "generic_fallback_non_laptop",
            ),
            (
                "headphones-to-domain-to-generic",
                "headphones",
                "EarphonesHeadphonesSpecialistAgent",
                "technology_domain_fallback_non_audio",
                "generic_fallback_non_audio",
            ),
            (
                "tv-to-domain-to-generic",
                "tv",
                "TVSpecialistAgent",
                "technology_domain_fallback_non_tv",
                "generic_fallback_non_tv",
            ),
            (
                "smartwatch-to-domain-to-generic",
                "smartwatch",
                "SmartwatchSpecialistAgent",
                "technology_domain_fallback_non_smartwatch",
                "generic_fallback_non_smartwatch",
            ),
        )
    )


def evaluate_product_analysis_routing_case(
    eval_case: ProductAnalysisRoutingEvalCase,
    *,
    catalog: AgentCatalog = DEFAULT_AGENT_CATALOG,
) -> ProductAnalysisRoutingEvalResult:
    route = catalog.route_product_analysis(eval_case.category)
    passed = (
        route.agent_path == eval_case.expected_agent_path
        and route.fallback_agent_names == eval_case.expected_fallback_agent_names
    )
    failure_reason = None
    if not passed:
        failure_reason = (
            f"Expected {eval_case.expected_agent_path} with fallbacks "
            f"{eval_case.expected_fallback_agent_names}, got {route.agent_path} "
            f"with fallbacks {route.fallback_agent_names}."
        )
    return ProductAnalysisRoutingEvalResult(
        case_name=eval_case.name,
        passed=passed,
        actual_agent_path=route.agent_path,
        actual_fallback_agent_names=route.fallback_agent_names,
        expected_agent_path=eval_case.expected_agent_path,
        expected_fallback_agent_names=eval_case.expected_fallback_agent_names,
        failure_reason=failure_reason,
    )


def _mvp_specialist_routing_cases() -> tuple[
    ProductAnalysisRoutingEvalCase,
    ...,
]:
    return tuple(
        ProductAnalysisRoutingEvalCase(
            name=f"routing/{slug}-specialist",
            description=(
                "MVP technology specialist categories enter the technology "
                "domain before the specialist."
            ),
            kind=ProductAnalysisRoutingEvalKind.MVP_SPECIALIST,
            category=category,
            shopper_query=shopper_query,
            expected_agent_path=(TECHNOLOGY_DOMAIN_AGENT_NAME, specialist_agent_name),
            expected_fallback_agent_names=SPECIALIST_FALLBACK_CHAIN,
        )
        for slug, category, specialist_agent_name, shopper_query in (
            (
                "monitor",
                "monitor",
                "MonitorSpecialistAgent",
                "Help me choose a 27-inch monitor for coding and movies.",
            ),
            (
                "smartphone",
                "smartphone",
                "SmartphoneSpecialistAgent",
                "Help me choose a midrange phone with good camera and battery.",
            ),
            (
                "laptop",
                "laptop",
                "LaptopSpecialistAgent",
                "Help me choose a portable laptop for school.",
            ),
            (
                "headphones",
                "headphones",
                "EarphonesHeadphonesSpecialistAgent",
                "Help me choose noise-cancelling headphones for commuting.",
            ),
            (
                "tv",
                "tv",
                "TVSpecialistAgent",
                "Help me choose a 55-inch TV for movies and gaming.",
            ),
            (
                "smartwatch",
                "smartwatch",
                "SmartwatchSpecialistAgent",
                "Help me choose a smartwatch for fitness with Android.",
            ),
        )
    )
