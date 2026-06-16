from typing import Any

import httpx
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError

from app.providers.contracts import SearchProviderOptions, SourcePolicyRule
from app.schemas.search_sources import (
    ProviderMetadata,
    SearchQuery,
    SearchResult,
    SourceQuality,
    SourceQualityLevel,
)


TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_MAX_RESULTS = 20


class TavilySearchError(RuntimeError):
    """Raised when Tavily cannot return a valid search response."""


class _TavilySearchResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1)
    url: AnyHttpUrl
    content: str | None = None
    score: float | None = None


class _TavilySearchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    request_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    results: list[_TavilySearchResult]
    response_time: float | str | None = None
    usage: dict[str, Any] | None = None


class TavilySearchProvider:
    provider_name = "tavily"

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Tavily API key must not be empty.")
        if timeout_seconds <= 0:
            raise ValueError("Tavily timeout must be greater than zero.")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._client = client

    async def search(
        self,
        query: SearchQuery,
        options: SearchProviderOptions | None = None,
    ) -> tuple[SearchResult, ...]:
        search_options = options or SearchProviderOptions()
        payload = self._build_payload(query, search_options)
        response = await self._post(payload)

        try:
            parsed = _TavilySearchResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise TavilySearchError(
                "Tavily returned an invalid search response."
            ) from exc

        target_region = search_options.region_code or query.region_code
        return tuple(
            SearchResult(
                query=query,
                url=result.url,
                title=_truncate(result.title, 300),
                snippet=_optional_truncate(result.content, 1000),
                provider=ProviderMetadata(
                    provider_name=self.provider_name,
                    provider_result_id=f"{parsed.request_id}:{index}",
                    query_id=parsed.request_id,
                    raw={
                        "rank": index,
                        "score": result.score,
                        "response_time_seconds": parsed.response_time,
                        "target_region_code": target_region,
                    },
                ),
                quality=SourceQuality(level=SourceQualityLevel.UNKNOWN),
            )
            for index, result in enumerate(parsed.results, start=1)
        )

    def _build_payload(
        self,
        query: SearchQuery,
        options: SearchProviderOptions,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query": query.query,
            "topic": "general",
            "search_depth": "basic",
            "max_results": min(options.max_results, TAVILY_MAX_RESULTS),
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_usage": True,
        }
        include_domains = _policy_domains(options.source_policy.allow)
        exclude_domains = _policy_domains(options.source_policy.avoid)
        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains
        return payload

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            if self._client is not None:
                response = await self._client.post(
                    TAVILY_SEARCH_URL,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(
                    timeout=self._timeout_seconds
                ) as client:
                    response = await client.post(
                        TAVILY_SEARCH_URL,
                        json=payload,
                        headers=headers,
                    )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise TavilySearchError(
                f"Tavily search failed with HTTP {exc.response.status_code}."
            ) from exc
        except httpx.RequestError as exc:
            raise TavilySearchError("Tavily search request failed.") from exc
        return response


def _policy_domains(rules: tuple[SourcePolicyRule, ...]) -> list[str]:
    return list(
        dict.fromkeys(
            rule.domain.strip().lower().removeprefix(".")
            for rule in rules
            if rule.domain is not None
        )
    )


def _truncate(value: str, max_length: int) -> str:
    return value.strip()[:max_length]


def _optional_truncate(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    truncated = _truncate(value, max_length)
    return truncated or None
