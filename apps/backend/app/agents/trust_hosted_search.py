"""Bound hosted trust research to one listing, seller, and buying region."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from app.agents.hosted_web_search import read_hosted_web_search_activity
from app.agents.openai_config import OpenAIAgentConfigurationError
from app.agents.research_tools import (
    HostedCitationStore,
    PersistedHostedCitation,
    _neutral_url,
    _safe_public_result_url,
    _source_policy_allows,
)
from app.providers.contracts import (
    SourceAllowAvoidPolicy,
    SourcePolicyAction,
    SourcePolicyRule,
)
from app.schemas.products import ProductListing
from app.schemas.regions import RegionCode
from app.schemas.search_sources import SourceType


def trust_search_policy(listing: ProductListing) -> SourceAllowAvoidPolicy:
    urls = (str(listing.url), str(listing.seller.seller_url or ""))
    domains = tuple(
        dict.fromkeys(
            (urlsplit(url).hostname or "").lower().removeprefix("www.")
            for url in urls
            if _safe_public_result_url(url)
        )
    )
    if not domains:
        raise OpenAIAgentConfigurationError(
            "Seller/listing hosted search needs a public listing or seller URL."
        )
    return SourceAllowAvoidPolicy(
        allow=tuple(
            SourcePolicyRule(
                action=SourcePolicyAction.ALLOW,
                domain=domain,
                reason="Trust research is restricted to this listing or seller site.",
            )
            for domain in domains
        )
    )


def trust_citation_matches_target(
    url: str, listing: ProductListing, region_code: RegionCode
) -> bool:
    """A marketplace domain alone does not identify its particular seller."""
    normalized = _neutral_url(url)
    listing_url = _neutral_url(str(listing.url))
    seller_url = (
        _neutral_url(str(listing.seller.seller_url))
        if listing.seller.seller_url
        else None
    )
    parsed = urlsplit(normalized)
    listing_parsed = urlsplit(listing_url)
    listing_path_region = listing_parsed.path.strip("/").split("/", 1)[0].lower()
    if listing_path_region == region_code.lower():
        citation_path_region = parsed.path.strip("/").split("/", 1)[0].lower()
        if citation_path_region != listing_path_region:
            return False
    if (
        parsed.hostname == listing_parsed.hostname
        and parsed.path == listing_parsed.path
    ):
        return True
    if (
        listing.seller.is_marketplace_seller is False
        and parsed.hostname == listing_parsed.hostname
    ):
        return True
    if seller_url:
        seller_parsed = urlsplit(seller_url)
        seller_path = seller_parsed.path.rstrip("/")
        if parsed.hostname == seller_parsed.hostname and (
            parsed.path == seller_path
            or (seller_path and parsed.path.startswith(f"{seller_path}/"))
        ):
            return True
    return False


async def persist_trust_search_leads(
    *,
    raw: Any,
    selected_urls: tuple[str, ...],
    listing: ProductListing,
    run_id: Any,
    region_code: RegionCode,
    citation_store: HostedCitationStore,
    source_policy: SourceAllowAvoidPolicy,
    require_sdk_metadata: bool,
) -> tuple[dict[str, PersistedHostedCitation], tuple[dict[str, Any], ...], str | None]:
    if require_sdk_metadata and not hasattr(raw, "raw_responses"):
        raise OpenAIAgentConfigurationError(
            "SellerListingTrustAgent SDK result omitted hosted-search activity metadata."
        )
    search = read_hosted_web_search_activity(raw)
    activity: list[dict[str, Any]] = [
        {
            "tool_name": "web_search",
            "status": call.status,
            "input": {"agent": "SellerListingTrustAgent", "run_id": str(run_id)},
            "output": {
                "call_id": call.call_id,
                "action": call.action,
                "returned_urls": list(call.source_urls),
            },
        }
        for call in search.calls
    ]
    if not search.calls:
        if selected_urls:
            raise ValueError("Trust research selected a URL without a hosted call.")
        return {}, tuple(activity), None
    if any(call.status != "completed" for call in search.calls):
        activity.extend(
            {
                "tool_name": "web_search_citation",
                "status": "rejected_failed_call",
                "input": {"agent": "SellerListingTrustAgent", "url": url},
                "output": {},
            }
            for call in search.calls
            for url in call.source_urls
        )
        return (
            {},
            tuple(activity),
            "Hosted trust search failed; no new trust evidence was accepted.",
        )
    if not search.citations:
        activity.extend(
            {
                "tool_name": "web_search_citation",
                "status": "rejected_uncited",
                "input": {"agent": "SellerListingTrustAgent", "url": url},
                "output": {},
            }
            for call in search.calls
            for url in call.source_urls
        )
        return {}, tuple(activity), "Hosted trust search returned no URL citations."

    citations = {citation.url: citation for citation in search.citations}
    if len(selected_urls) != len(
        set(_neutral_url(url) for url in selected_urls)
    ) or any(url not in citations for url in selected_urls):
        raise ValueError("Trust research selected an uncited or duplicate URL.")
    eligible = tuple(
        citations[url]
        for url in selected_urls
        if _safe_public_result_url(url)
        and _source_policy_allows(url, SourceType.SEARCH_RESULT, source_policy)
        and trust_citation_matches_target(url, listing, region_code)
    )
    try:
        persisted, decisions = await citation_store.persist(
            agent_name="SellerListingTrustAgent",
            citations=eligible,
            query=f"{listing.seller.seller_name} {listing.title} trust {region_code}"[
                :500
            ],
            region_code=region_code,
            source_policy=source_policy,
        )
    except Exception as exc:
        raise OpenAIAgentConfigurationError(
            "SellerListingTrustAgent hosted citations could not be persisted."
        ) from exc
    retained = {citation.url: citation for citation in persisted}
    decision_by_url = dict(decisions)
    for citation in search.citations:
        normalized = _neutral_url(citation.url)
        item = retained.get(normalized)
        status = (
            "retained"
            if item is not None
            else decision_by_url.get(normalized, "rejected_scope_or_not_selected")
        )
        activity.append(
            {
                "tool_name": "web_search_citation",
                "status": status,
                "input": {"agent": "SellerListingTrustAgent", "url": citation.url},
                "output": {
                    "source_id": str(item.source_id) if item else None,
                    "evidence_id": str(item.evidence_id) if item else None,
                },
            }
        )
    return (
        {
            url: retained[_neutral_url(url)]
            for url in selected_urls
            if _neutral_url(url) in retained
        },
        tuple(activity),
        None
        if len(retained) == len(selected_urls)
        else "Some hosted trust sources were outside this seller/listing scope.",
    )
