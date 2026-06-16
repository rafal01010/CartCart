import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.core.settings import Settings, VideoSearchProviderName
from app.providers import (
    FakeVideoSearchProvider,
    ProviderRunStatus,
    VideoSearchProvider,
    VideoSearchProviderOptions,
    YouTubeDataApiVideoSearchProvider,
    YouTubeVideoSearchError,
    build_video_search_provider,
)
from app.providers.fixtures import load_provider_fixture, provider_fixture_transport
from app.schemas.search_sources import TranscriptAvailability


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "providers"


@pytest.mark.asyncio
async def test_youtube_metadata_search_maps_recorded_fixture() -> None:
    fixtures = (
        load_provider_fixture(FIXTURE_DIR / "youtube_search.json"),
        load_provider_fixture(FIXTURE_DIR / "youtube_videos.json"),
    )

    async with httpx.AsyncClient(
        transport=provider_fixture_transport(fixtures)
    ) as client:
        provider: VideoSearchProvider = YouTubeDataApiVideoSearchProvider(
            api_key="recorded-test-key",
            timeout_seconds=3,
            client=client,
        )
        result = await provider.search_videos(
            "portable monitor review",
            VideoSearchProviderOptions(region_code="PH", max_results=2),
        )

    assert result.status == ProviderRunStatus.SUCCEEDED
    assert result.capabilities.provider_name == "youtube-data-api"
    assert result.capabilities.uses_official_api is True
    assert result.capabilities.supports_video_search is True
    assert result.capabilities.supports_transcripts is False
    assert result.bundle is not None
    assert result.bundle.transcript_segments == ()
    assert result.bundle.transcript_gap_notes

    first, second = result.bundle.videos
    assert first.video_id == "monitor-review-1"
    assert first.title == "Portable Monitor Review & Long-Term Test"
    assert first.channel_id == "channel-fixture-1"
    assert first.channel_name == "Fixture Reviews"
    assert first.description == "A synthetic review description with real-world notes."
    assert first.published_at == datetime(2026, 5, 10, 8, 30, tzinfo=UTC)
    assert first.duration_seconds == 872
    assert str(first.url) == (
        "https://www.youtube.com/watch?v=monitor-review-1"
    )
    assert first.transcript_availability == TranscriptAvailability.NOT_CHECKED
    assert second.duration_seconds == 3723
    assert all(
        video.transcript_availability == TranscriptAvailability.NOT_CHECKED
        for video in result.bundle.videos
    )
    assert "recorded-test-key" not in json.dumps(
        [fixture.model_dump(mode="json") for fixture in fixtures]
    )


def test_video_search_runtime_selects_fixture_disabled_and_youtube_modes() -> None:
    default_provider = build_video_search_provider(Settings(_env_file=None))  # type: ignore[call-arg]
    disabled_provider = build_video_search_provider(  # type: ignore[call-arg]
        Settings(
            _env_file=None,
            video_search_provider=VideoSearchProviderName.DISABLED,
        )
    )
    live_provider = build_video_search_provider(  # type: ignore[call-arg]
        Settings(
            _env_file=None,
            video_search_provider=VideoSearchProviderName.YOUTUBE,
            video_search_provider_enabled=True,
            youtube_data_api_key="fixture-key",
        )
    )
    missing_key_provider = build_video_search_provider(  # type: ignore[call-arg]
        Settings(
            _env_file=None,
            video_search_provider=VideoSearchProviderName.YOUTUBE,
            video_search_provider_enabled=True,
        )
    )

    assert isinstance(default_provider, FakeVideoSearchProvider)
    assert isinstance(disabled_provider, FakeVideoSearchProvider)
    assert disabled_provider.disabled is True
    assert isinstance(live_provider, YouTubeDataApiVideoSearchProvider)
    assert isinstance(missing_key_provider, FakeVideoSearchProvider)


@pytest.mark.asyncio
async def test_youtube_metadata_search_returns_unavailable_for_no_matches() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": []}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = YouTubeDataApiVideoSearchProvider(
            api_key="test-key",
            client=client,
        )
        result = await provider.search_videos("no matching fixture")

    assert result.status == ProviderRunStatus.UNAVAILABLE
    assert result.bundle is None
    assert result.notes == ("YouTube returned no matching videos.",)


@pytest.mark.asyncio
async def test_youtube_metadata_search_raises_sanitized_http_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"error": {"message": "invalid secret test-key"}},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = YouTubeDataApiVideoSearchProvider(
            api_key="test-key",
            client=client,
        )
        with pytest.raises(YouTubeVideoSearchError, match="HTTP 403") as exc_info:
            await provider.search_videos("portable monitor review")

    assert "test-key" not in str(exc_info.value)
    assert "invalid secret" not in str(exc_info.value)
