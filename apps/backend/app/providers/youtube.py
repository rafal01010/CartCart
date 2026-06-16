from __future__ import annotations

import html
import re
from datetime import datetime

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.providers.contracts import (
    ProviderCapabilityFlags,
    ProviderRunStatus,
    VideoSearchProviderOptions,
    VideoSearchProviderResult,
)
from app.schemas.ids import new_id
from app.schemas.search_sources import (
    TranscriptAvailability,
    VideoReviewEvidenceBundle,
    VideoSource,
)
from app.schemas.source_references import SourceReference


YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
_YOUTUBE_DURATION_PATTERN = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+)S)?)?$"
)


class YouTubeVideoSearchError(RuntimeError):
    """Raised when YouTube cannot return valid video metadata."""


class _YouTubeSearchId(BaseModel):
    model_config = ConfigDict(extra="ignore")

    video_id: str = Field(alias="videoId", min_length=1)


class _YouTubeSnippet(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1)
    description: str = ""
    channel_id: str = Field(alias="channelId", min_length=1)
    channel_title: str = Field(alias="channelTitle", min_length=1)
    published_at: datetime = Field(alias="publishedAt")


class _YouTubeSearchItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: _YouTubeSearchId
    snippet: _YouTubeSnippet


class _YouTubeSearchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[_YouTubeSearchItem] = Field(default_factory=list)


class _YouTubeContentDetails(BaseModel):
    model_config = ConfigDict(extra="ignore")

    duration: str | None = None


class _YouTubeVideoItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    content_details: _YouTubeContentDetails = Field(alias="contentDetails")


class _YouTubeVideosResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[_YouTubeVideoItem] = Field(default_factory=list)


class YouTubeDataApiVideoSearchProvider:
    provider_name = "youtube-data-api"

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("YouTube Data API key must not be empty.")
        if timeout_seconds <= 0:
            raise ValueError("YouTube timeout must be greater than zero.")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._client = client

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name=self.provider_name,
            uses_official_api=True,
            supports_video_search=True,
            supports_transcripts=False,
            permits_transcript_text=False,
            compliance_notes=(
                "Uses official YouTube Data API metadata only.",
                "Transcript availability and transcript text are not checked.",
            ),
        )

    async def search_videos(
        self,
        query: str,
        options: VideoSearchProviderOptions | None = None,
    ) -> VideoSearchProviderResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("YouTube video search query must not be empty.")
        search_options = options or VideoSearchProviderOptions()

        search_response = await self._get(
            YOUTUBE_SEARCH_URL,
            params={
                "part": "snippet",
                "q": normalized_query,
                "type": "video",
                "order": "relevance",
                "safeSearch": "moderate",
                "maxResults": str(search_options.max_results),
                **(
                    {"regionCode": search_options.region_code}
                    if search_options.region_code is not None
                    else {}
                ),
            },
        )
        try:
            search = _YouTubeSearchResponse.model_validate(search_response.json())
        except (ValueError, ValidationError) as exc:
            raise YouTubeVideoSearchError(
                "YouTube search returned an invalid metadata response."
            ) from exc

        if not search.items:
            return VideoSearchProviderResult(
                status=ProviderRunStatus.UNAVAILABLE,
                capabilities=self.capabilities,
                notes=("YouTube returned no matching videos.",),
            )

        video_ids = tuple(dict.fromkeys(item.id.video_id for item in search.items))
        details_response = await self._get(
            YOUTUBE_VIDEOS_URL,
            params={"part": "contentDetails", "id": ",".join(video_ids)},
        )
        try:
            details = _YouTubeVideosResponse.model_validate(details_response.json())
        except (ValueError, ValidationError) as exc:
            raise YouTubeVideoSearchError(
                "YouTube video details returned an invalid metadata response."
            ) from exc

        duration_by_video_id = {
            item.id: _duration_seconds(item.content_details.duration)
            for item in details.items
        }
        videos = tuple(
            _to_video_source(item, duration_by_video_id.get(item.id.video_id))
            for item in search.items
        )
        source_references = tuple(
            SourceReference(source_id=new_id(), url=video.url, title=video.title)
            for video in videos
        )
        transcript_note = (
            "Transcript availability was not checked by the YouTube metadata adapter."
        )
        return VideoSearchProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            bundle=VideoReviewEvidenceBundle(
                videos=videos,
                source_references=source_references,
                transcript_gap_notes=(transcript_note,),
            ),
            notes=(transcript_note,),
        )

    async def _get(
        self,
        url: str,
        *,
        params: dict[str, str],
    ) -> httpx.Response:
        headers = {"X-Goog-Api-Key": self._api_key}
        try:
            if self._client is not None:
                response = await self._client.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self._timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(
                    timeout=self._timeout_seconds
                ) as client:
                    response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise YouTubeVideoSearchError(
                f"YouTube metadata request failed with HTTP {exc.response.status_code}."
            ) from exc
        except httpx.RequestError as exc:
            raise YouTubeVideoSearchError(
                "YouTube metadata request failed."
            ) from exc
        return response


def _to_video_source(
    item: _YouTubeSearchItem,
    duration_seconds: int | None,
) -> VideoSource:
    snippet = item.snippet
    description = _optional_text(snippet.description, 5000)
    return VideoSource(
        video_id=item.id.video_id,
        url=f"https://www.youtube.com/watch?v={item.id.video_id}",
        title=_required_text(snippet.title, 300),
        description=description,
        channel_id=snippet.channel_id,
        channel_name=_required_text(snippet.channel_title, 200),
        published_at=snippet.published_at,
        duration_seconds=duration_seconds,
        transcript_availability=TranscriptAvailability.NOT_CHECKED,
    )


def _required_text(value: str, max_length: int) -> str:
    return html.unescape(value).strip()[:max_length]


def _optional_text(value: str, max_length: int) -> str | None:
    normalized = _required_text(value, max_length)
    return normalized or None


def _duration_seconds(value: str | None) -> int | None:
    if value is None:
        return None
    match = _YOUTUBE_DURATION_PATTERN.fullmatch(value)
    if match is None:
        return None
    parts = {name: int(part or 0) for name, part in match.groupdict().items()}
    return (
        parts["days"] * 86_400
        + parts["hours"] * 3_600
        + parts["minutes"] * 60
        + parts["seconds"]
    )
