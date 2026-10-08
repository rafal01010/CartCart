"""Shared hosted-search boundary for the four source-intelligence specialists."""

from __future__ import annotations

from typing import Any

from app.agents.hosted_web_search import (
    build_hosted_web_search_tool,
    read_hosted_web_search_activity,
    source_specialist_citation_url_allowed,
    source_specialist_search_policy,
)
from app.agents.openai_config import (
    OpenAIAgentConfigurationError,
    OpenAIAgentRuntimeMode,
    OpenAIAgentRunConfiguration,
)
from app.agents.research_tools import (
    HostedCitationStore,
    _neutral_url,
    _safe_public_result_url,
    _source_policy_allows,
)
from app.schemas.ids import RunId
from app.schemas.regions import RegionCode
from app.schemas.search_sources import SourceType


def source_region_code(input_data: Any) -> RegionCode | None:
    return getattr(input_data, "target_region_code", None) or (
        input_data.brief.region.region.country_code
        if input_data.brief.region is not None
        else None
    )


def source_tool_activity(
    items: tuple[dict[str, Any], ...], agent_name: str
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            **item,
            "input": {**item.get("input", {}), "agent": agent_name},
        }
        for item in items
    )


def source_hosted_tool(
    *,
    config: OpenAIAgentRunConfiguration,
    input_data: Any,
    agent_name: str,
    citation_store: HostedCitationStore | None,
) -> Any | None:
    if config.mode != OpenAIAgentRuntimeMode.LIVE:
        return None
    if citation_store is None or citation_store.run_id != input_data.run_id:
        raise OpenAIAgentConfigurationError(
            f"Live {agent_name} requires a run-scoped hosted citation store."
        )
    return build_hosted_web_search_tool(
        agent_name=agent_name,
        region_code=source_region_code(input_data),
        source_policy=source_specialist_search_policy(
            agent_name, source_region_code(input_data)
        ),
    )


async def process_source_specialist_output(
    *,
    raw: Any,
    decision: Any,
    input_data: Any,
    agent_name: str,
    citation_store: HostedCitationStore | None,
    require_sdk_metadata: bool,
) -> tuple[Any, tuple[dict[str, Any], ...]]:
    activity, gap = await process_source_hosted_search(
        raw=raw,
        agent_name=agent_name,
        run_id=input_data.run_id,
        region_code=source_region_code(input_data),
        query=input_data.brief.original_query,
        retained_urls=decision.retained_web_urls,
        citation_store=citation_store,
        require_sdk_metadata=require_sdk_metadata,
    )
    if gap and len(decision.evidence_gaps) < 5:
        decision = decision.model_copy(
            update={"evidence_gaps": (*decision.evidence_gaps, gap)}
        )
    return decision, activity


async def process_source_hosted_search(
    *,
    raw: Any,
    agent_name: str,
    run_id: RunId,
    region_code: RegionCode | None,
    query: str,
    retained_urls: tuple[str, ...],
    citation_store: HostedCitationStore | None,
    require_sdk_metadata: bool,
) -> tuple[tuple[dict[str, Any], ...], str | None]:
    if citation_store is None:
        return (), None
    if require_sdk_metadata and not hasattr(raw, "raw_responses"):
        raise OpenAIAgentConfigurationError(
            f"{agent_name} SDK result omitted hosted-search activity metadata."
        )
    search = read_hosted_web_search_activity(raw)
    activity: list[dict[str, Any]] = [
        {
            "tool_name": "web_search",
            "status": call.status,
            "input": {"agent": agent_name, "run_id": str(run_id)},
            "output": {
                "call_id": call.call_id,
                "action": call.action,
                "returned_urls": list(call.source_urls),
            },
        }
        for call in search.calls
    ]
    if any(call.status != "completed" for call in search.calls):
        activity.extend(
            {
                "tool_name": "web_search_source",
                "status": "rejected_failed_call",
                "input": {"agent": agent_name, "url": url},
                "output": {},
            }
            for call in search.calls
            for url in call.source_urls
        )
        return tuple(activity), "Hosted search failed; its results were not accepted."
    if search.calls and not search.citations:
        activity.extend(
            {
                "tool_name": "web_search_source",
                "status": "rejected_uncited",
                "input": {"agent": agent_name, "url": url},
                "output": {},
            }
            for call in search.calls
            for url in call.source_urls
        )
        return tuple(activity), "Hosted search returned no URL citations."
    if not search.calls:
        return tuple(activity), None
    cited_by_url = {}
    for citation in search.citations:
        try:
            normalized = _neutral_url(citation.url)
            if normalized in cited_by_url:
                activity.append(
                    {
                        "tool_name": "web_search_citation",
                        "status": "duplicate_rejected",
                        "input": {"agent": agent_name, "url": citation.url},
                        "output": {},
                    }
                )
                continue
            cited_by_url[normalized] = citation
        except ValueError:
            activity.append(
                {
                    "tool_name": "web_search_citation",
                    "status": "rejected_invalid_url",
                    "input": {"agent": agent_name, "url": citation.url},
                    "output": {},
                }
            )
    selected: set[str] = set()
    exact_citation_urls = {citation.url for citation in search.citations}
    for url in retained_urls:
        try:
            normalized = _neutral_url(url)
        except ValueError:
            normalized = ""
        if (
            url not in exact_citation_urls
            or normalized not in cited_by_url
            or normalized in selected
        ):
            activity.extend(
                {
                    "tool_name": "web_search_citation",
                    "status": "rejected_invalid_selection",
                    "input": {"agent": agent_name, "url": citation.url},
                    "output": {},
                }
                for citation in search.citations
            )
            return (
                tuple(activity),
                "A retained hosted URL lacked a unique exact SDK citation.",
            )
        selected.add(normalized)
    policy = source_specialist_search_policy(agent_name, region_code)
    eligible = tuple(
        citation
        for normalized, citation in cited_by_url.items()
        if normalized in selected
        and _safe_public_result_url(normalized)
        and _source_policy_allows(normalized, SourceType.SEARCH_RESULT, policy)
        and source_specialist_citation_url_allowed(agent_name, normalized, region_code)
    )
    try:
        persisted, decisions = await citation_store.persist(
            agent_name=agent_name,
            citations=eligible,
            query=query,
            region_code=region_code,
            source_policy=policy,
        )
    except Exception as exc:
        raise OpenAIAgentConfigurationError(
            f"{agent_name} hosted citations could not be persisted."
        ) from exc
    retained = {item.url: item for item in persisted}
    rejected = {url: reason for url, reason in decisions if reason != "retained"}
    for normalized, citation in cited_by_url.items():
        saved = retained.get(normalized)
        activity.append(
            {
                "tool_name": "web_search_citation",
                "status": "retained" if saved else rejected.get(normalized, "rejected"),
                "input": {"agent": agent_name, "url": citation.url},
                "output": (
                    {
                        "source_id": str(saved.source_id),
                        "snapshot_id": str(saved.snapshot_id),
                        "evidence_id": str(saved.evidence_id),
                    }
                    if saved
                    else {}
                ),
            }
        )
    for call in search.calls:
        for url in call.source_urls:
            try:
                source_url = _neutral_url(url)
            except ValueError:
                source_url = url
            if source_url not in cited_by_url:
                activity.append(
                    {
                        "tool_name": "web_search_source",
                        "status": "rejected_uncited",
                        "input": {"agent": agent_name, "url": url},
                        "output": {},
                    }
                )
    return tuple(activity), (
        "Hosted results remained unverified source leads; no site evidence was inferred."
        if search.citations and not persisted
        else None
    )
