"""Role-scoped OpenAI hosted search and SDK citation extraction."""

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from agents import WebSearchTool
from openai.types.responses.web_search_tool import Filters

from app.agents.catalog import ApprovedSDKTool, DEFAULT_AGENT_CATALOG
from app.agents.openai_config import OpenAIAgentConfigurationError
from app.core.ikea_regions import IKEA_REGION_PATHS
from app.providers.amazon import _marketplace_for_region
from app.providers.contracts import (
    SourceAllowAvoidPolicy,
    SourcePolicyAction,
    SourcePolicyRule,
)
from app.schemas.regions import RegionCode


@dataclass(frozen=True)
class HostedWebSearchCall:
    call_id: str | None
    action: str
    status: str
    source_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class HostedWebCitation:
    url: str
    title: str
    cited_text: str
    call_id: str | None


@dataclass(frozen=True)
class HostedWebSearchActivity:
    calls: tuple[HostedWebSearchCall, ...]
    citations: tuple[HostedWebCitation, ...]


def build_hosted_web_search_tool(
    *,
    agent_name: str,
    region_code: RegionCode | None,
    source_policy: SourceAllowAvoidPolicy,
) -> WebSearchTool:
    entry = DEFAULT_AGENT_CATALOG.require(agent_name)
    if ApprovedSDKTool.HOSTED_WEB_SEARCH not in entry.approved_sdk_tools:
        raise OpenAIAgentConfigurationError(
            f"{agent_name} is not approved for hosted web search."
        )
    domains = tuple(
        dict.fromkeys(
            rule.domain.rstrip(".").removeprefix("www.").lower()
            for rule in source_policy.allow
            if rule.domain
        )
    )
    if len(domains) > 100:
        raise OpenAIAgentConfigurationError(
            "Hosted web search supports at most 100 allowed domains."
        )
    return WebSearchTool(
        user_location={"type": "approximate", "country": region_code}
        if region_code
        else None,
        filters=Filters(allowed_domains=list(domains)) if domains else None,
        search_context_size="medium",
    )


def read_hosted_web_search_activity(raw_result: Any) -> HostedWebSearchActivity:
    """Read actual Responses items, never infer a hosted call from provider tools."""
    calls: list[HostedWebSearchCall] = []
    citations: list[HostedWebCitation] = []
    last_call_id: str | None = None
    for response in getattr(raw_result, "raw_responses", ()) or ():
        for item in _value(response, "output", ()) or ():
            if _value(item, "type") == "web_search_call":
                call_id = _value(item, "id")
                last_call_id = call_id if isinstance(call_id, str) else None
                action_data = _value(item, "action")
                action = _value(action_data, "type", "unknown")
                status = _value(item, "status", "unknown")
                source_urls = tuple(
                    url
                    for source in (_value(action_data, "sources", ()) or ())
                    if isinstance((url := _value(source, "url")), str)
                )
                calls.append(
                    HostedWebSearchCall(
                        call_id=last_call_id,
                        action=str(action),
                        status=str(status),
                        source_urls=source_urls,
                    )
                )
            if _value(item, "type") != "message":
                continue
            for content in _value(item, "content", ()) or ():
                message_text = _value(content, "text", "")
                if not isinstance(message_text, str):
                    message_text = ""
                for annotation in _value(content, "annotations", ()) or ():
                    if _value(annotation, "type") != "url_citation":
                        continue
                    url = _value(annotation, "url")
                    if not isinstance(url, str):
                        continue
                    title = _value(annotation, "title")
                    start = _value(annotation, "start_index")
                    end = _value(annotation, "end_index")
                    cited_text = (
                        message_text[start:end].strip()
                        if isinstance(start, int)
                        and isinstance(end, int)
                        and 0 <= start < end <= len(message_text)
                        else ""
                    )
                    citations.append(
                        HostedWebCitation(
                            url=url,
                            title=title if isinstance(title, str) else "",
                            cited_text=cited_text,
                            call_id=last_call_id,
                        )
                    )
    return HostedWebSearchActivity(tuple(calls), tuple(citations))


def _value(item: Any, name: str, default: Any = None) -> Any:
    return (
        item.get(name, default)
        if isinstance(item, dict)
        else getattr(item, name, default)
    )


def source_specialist_search_policy(
    agent_name: str, region_code: RegionCode | None
) -> SourceAllowAvoidPolicy:
    """Use a site and marketplace scope independent of model instructions."""
    domains = {
        "YouTubeReviewIntelligenceAgent": ("youtube.com", "youtu.be"),
        "RedditCommunityIntelligenceAgent": ("reddit.com",),
        "AmazonProductIntelligenceAgent": (_marketplace_for_region(region_code),),
        "IKEAStoreIntelligenceAgent": (
            IKEA_REGION_PATHS.get(region_code or "", ("ikea.com", ""))[0],
        ),
    }.get(agent_name)
    if domains is None:
        raise OpenAIAgentConfigurationError("Unknown hosted source specialist.")
    return SourceAllowAvoidPolicy(
        allow=tuple(
            SourcePolicyRule(
                action=SourcePolicyAction.ALLOW,
                domain=domain,
                reason=f"{agent_name} is restricted to its source site.",
            )
            for domain in domains
        )
    )


def source_specialist_citation_url_allowed(
    agent_name: str, url: str, region_code: RegionCode | None
) -> bool:
    if agent_name != "IKEAStoreIntelligenceAgent":
        return True
    configured = IKEA_REGION_PATHS.get(region_code or "")
    if configured is None:
        return False
    domain, prefix = configured
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    path = parsed.path.casefold()
    expected = prefix.casefold().rstrip("/")
    return host in {domain, f"www.{domain}"} and (
        not expected or path.startswith(expected + "/")
    )
