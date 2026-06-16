import json
import os
from pathlib import Path

import httpx
import pytest

from app.core.settings import Settings
from app.providers import (
    SearchProvider,
    SearchProviderOptions,
    SourceAllowAvoidPolicy,
    SourcePolicyAction,
    SourcePolicyRule,
    TavilySearchError,
    TavilySearchProvider,
)
from app.providers.fixtures import (
    ProviderFixtureError,
    load_provider_fixture,
    provider_fixture_transport,
    write_provider_fixture,
)
from app.tools.record_tavily_search_fixture import record_tavily_search_fixture
from app.schemas.search_sources import SearchIntent, SearchQuery, SourceQualityLevel


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "providers" / "tavily_search.json"
)


@pytest.mark.asyncio
async def test_tavily_search_maps_recorded_response_through_provider_contract() -> None:
    fixture = load_provider_fixture(FIXTURE_PATH)

    async with httpx.AsyncClient(
        transport=provider_fixture_transport(fixture)
    ) as client:
        provider: SearchProvider = TavilySearchProvider(
            api_key="recorded-test-key",
            timeout_seconds=3,
            client=client,
        )
        query = SearchQuery(
            query="best monitor reviews",
            intent=SearchIntent.REVIEW,
            region_code="ph",
        )
        results = await provider.search(
            query,
            SearchProviderOptions(
                max_results=50,
                source_policy=SourceAllowAvoidPolicy(
                    allow=(
                        SourcePolicyRule(
                            action=SourcePolicyAction.ALLOW,
                            domain="reviews.example.com",
                            reason="Recorded approved review source.",
                        ),
                    ),
                    avoid=(
                        SourcePolicyRule(
                            action=SourcePolicyAction.AVOID,
                            domain="reseller.example",
                            reason="Recorded excluded reseller.",
                        ),
                    ),
                ),
            ),
        )

    assert fixture.request.json_body == {
        "query": "best monitor reviews",
        "topic": "general",
        "search_depth": "basic",
        "max_results": 20,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
        "include_usage": True,
        "include_domains": ["reviews.example.com"],
        "exclude_domains": ["reseller.example"],
    }
    assert len(results) == 2
    assert results[0].query == query
    assert results[0].provider.provider_name == "tavily"
    assert results[0].provider.query_id == "recorded-tavily-request-1"
    assert results[0].provider.provider_result_id == "recorded-tavily-request-1:1"
    assert results[0].provider.raw == {
        "rank": 1,
        "score": 0.91,
        "response_time_seconds": 0.42,
        "target_region_code": "PH",
    }
    assert results[0].quality.level == SourceQualityLevel.UNKNOWN
    assert "recorded-test-key" not in json.dumps(
        [result.model_dump(mode="json") for result in results]
    )


@pytest.mark.asyncio
async def test_tavily_search_fixture_replays_deterministically() -> None:
    fixture = load_provider_fixture(FIXTURE_PATH)

    async def replay() -> list[dict[str, object]]:
        async with httpx.AsyncClient(
            transport=provider_fixture_transport(fixture)
        ) as client:
            provider = TavilySearchProvider(api_key="replay-key", client=client)
            results = await provider.search(
                SearchQuery(
                    query="best monitor reviews",
                    intent=SearchIntent.REVIEW,
                    region_code="ph",
                ),
                SearchProviderOptions(
                    max_results=50,
                    source_policy=SourceAllowAvoidPolicy(
                        allow=(
                            SourcePolicyRule(
                                action=SourcePolicyAction.ALLOW,
                                domain="reviews.example.com",
                                reason="Recorded approved review source.",
                            ),
                        ),
                        avoid=(
                            SourcePolicyRule(
                                action=SourcePolicyAction.AVOID,
                                domain="reseller.example",
                                reason="Recorded excluded reseller.",
                            ),
                        ),
                    ),
                ),
            )
        return [
            result.model_dump(mode="json", exclude={"source_id"})
            for result in results
        ]

    assert await replay() == await replay()


def test_provider_fixture_recording_sanitizes_and_serializes_stably(
    tmp_path: Path,
) -> None:
    fixture_path = tmp_path / "recording.json"
    long_content = "x" * 1_500

    write_provider_fixture(
        fixture_path,
        provider_name="tavily",
        request_method="POST",
        request_url="https://api.tavily.com/search",
        request_json={
            "query": "synthetic fixture query",
            "api_key": "secret-key",
        },
        response_status_code=200,
        response_json={
            "answer": "unneeded generated answer",
            "raw_content": "unneeded raw page body",
            "results": [
                {
                    "title": "Fixture result",
                    "url": "https://example.com/result",
                    "content": long_content,
                }
            ],
        },
        secret_values=("secret-key",),
    )
    first_write = fixture_path.read_text(encoding="utf-8")
    recorded = load_provider_fixture(fixture_path)
    write_provider_fixture(
        fixture_path,
        provider_name=recorded.provider_name,
        request_method=recorded.request.method,
        request_url=str(recorded.request.url),
        request_json=recorded.request.json_body,
        response_status_code=recorded.response.status_code,
        response_json=recorded.response.json_body,
    )

    assert fixture_path.read_text(encoding="utf-8") == first_write
    assert "secret-key" not in first_write
    assert "raw_content" not in first_write
    assert "unneeded generated answer" not in first_write
    result = recorded.response.json_body["results"][0]
    assert len(result["content"]) == 1_000


@pytest.mark.asyncio
async def test_provider_fixture_replay_rejects_unrecorded_request() -> None:
    fixture = load_provider_fixture(FIXTURE_PATH)

    async with httpx.AsyncClient(
        transport=provider_fixture_transport(fixture)
    ) as client:
        with pytest.raises(ProviderFixtureError, match="did not match"):
            await client.post(
                "https://api.tavily.com/search",
                json={"query": "different query"},
            )


@pytest.mark.asyncio
async def test_tavily_fixture_recording_requires_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("CARTCART_RECORD_PROVIDER_FIXTURES", raising=False)

    with pytest.raises(RuntimeError, match="CARTCART_RECORD_PROVIDER_FIXTURES=1"):
        await record_tavily_search_fixture(
            output_path=tmp_path / "tavily.json",
            query_text="synthetic fixture query",
            region_code="US",
            max_results=1,
        )


@pytest.mark.asyncio
async def test_tavily_search_raises_sanitized_error_for_http_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "invalid secret test-key"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = TavilySearchProvider(api_key="test-key", client=client)

        with pytest.raises(TavilySearchError, match="HTTP 401") as exc_info:
            await provider.search(
                SearchQuery(query="monitor", intent=SearchIntent.DISCOVERY)
            )

    assert "test-key" not in str(exc_info.value)
    assert "invalid secret" not in str(exc_info.value)


@pytest.mark.live_provider
@pytest.mark.asyncio
async def test_tavily_search_live_opt_in() -> None:
    if os.getenv("CARTCART_RUN_LIVE_PROVIDER_TESTS") != "1":
        pytest.skip("Set CARTCART_RUN_LIVE_PROVIDER_TESTS=1 to allow live calls.")

    settings = Settings()
    if settings.tavily_api_key is None:
        pytest.skip("CARTCART_TAVILY_API_KEY is not configured.")

    provider = TavilySearchProvider(
        api_key=settings.tavily_api_key.get_secret_value(),
        timeout_seconds=settings.provider_timeout_seconds,
    )
    results = await provider.search(
        SearchQuery(
            query="official laptop buying guide",
            intent=SearchIntent.DISCOVERY,
            region_code=settings.default_region_code,
        ),
        SearchProviderOptions(max_results=1),
    )

    assert results
    assert results[0].provider.provider_name == "tavily"
