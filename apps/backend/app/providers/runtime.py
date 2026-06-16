from app.core.settings import (
    AmazonProductIntelligenceProviderName,
    ExtractionProviderName,
    IKEAStoreIntelligenceProviderName,
    SearchProviderName,
    Settings,
    TranscriptProviderName,
    VideoSearchProviderName,
)
from app.providers.amazon import SerpApiAmazonProductIntelligenceProvider
from app.providers.contracts import (
    AmazonProductIntelligenceProvider,
    CommunityDiscussionProvider,
    ExtractionProvider,
    IKEAStoreIntelligenceProvider,
    SearchProvider,
    TranscriptProvider,
    VideoSearchProvider,
)
from app.providers.fakes import (
    FakeAmazonProductIntelligenceProvider,
    FakeExtractionProvider,
    FakeIKEAStoreIntelligenceProvider,
    FakeSearchProvider,
    FakeTranscriptProvider,
    FakeVideoSearchProvider,
)
from app.providers.extraction import HttpStaticExtractionProvider
from app.providers.ikea import IKEARegionalStoreDiscoveryProvider
from app.providers.reddit import RedditCommunityDiscoveryProvider
from app.providers.tavily import TavilySearchProvider
from app.providers.youtube import YouTubeDataApiVideoSearchProvider
from app.providers.youtube_transcript import YtDlpTranscriptProvider


class SearchProviderConfigurationError(RuntimeError):
    """Raised when live search is enabled for an unsupported configuration."""


def build_search_provider(settings: Settings) -> SearchProvider:
    if (
        not settings.search_provider_enabled
        or settings.search_provider == SearchProviderName.FIXTURE
    ):
        return FakeSearchProvider()

    if settings.search_provider == SearchProviderName.TAVILY:
        if settings.tavily_api_key is None:
            return FakeSearchProvider()
        return TavilySearchProvider(
            api_key=settings.tavily_api_key.get_secret_value(),
            timeout_seconds=settings.provider_timeout_seconds,
        )

    raise SearchProviderConfigurationError(
        f"Search provider '{settings.search_provider.value}' has no runtime adapter."
    )


def build_extraction_provider(settings: Settings) -> ExtractionProvider:
    provider_name = settings.extraction_provider
    if provider_name == ExtractionProviderName.DISABLED:
        return FakeExtractionProvider(disabled=True)

    if (
        not settings.extraction_provider_enabled
        or provider_name == ExtractionProviderName.FIXTURE
    ):
        return FakeExtractionProvider()

    if provider_name == ExtractionProviderName.HTTP_STATIC:
        return HttpStaticExtractionProvider(
            snapshot_dir=settings.resolved_raw_source_snapshot_dir,
            timeout_seconds=settings.provider_timeout_seconds,
            max_content_bytes=settings.source_fetch_max_content_bytes,
            user_agent=settings.source_fetch_user_agent,
        )

    raise AssertionError(f"Unhandled extraction provider: {provider_name.value}")


def build_community_discussion_provider(
    settings: Settings,
) -> CommunityDiscussionProvider:
    return RedditCommunityDiscoveryProvider(
        search_provider=build_search_provider(settings),
    )


class AmazonProductIntelligenceProviderConfigurationError(RuntimeError):
    """Raised when Amazon intelligence is enabled for an unsupported provider."""


def build_amazon_product_intelligence_provider(
    settings: Settings,
) -> AmazonProductIntelligenceProvider:
    provider_name = settings.amazon_product_intelligence_provider
    if provider_name == AmazonProductIntelligenceProviderName.DISABLED:
        return FakeAmazonProductIntelligenceProvider(disabled=True)

    if (
        not settings.amazon_product_intelligence_provider_enabled
        or provider_name == AmazonProductIntelligenceProviderName.FIXTURE
    ):
        return FakeAmazonProductIntelligenceProvider()

    if provider_name == AmazonProductIntelligenceProviderName.SERPAPI:
        if settings.serpapi_api_key is None:
            return FakeAmazonProductIntelligenceProvider()
        return SerpApiAmazonProductIntelligenceProvider(
            api_key=settings.serpapi_api_key.get_secret_value(),
            timeout_seconds=settings.provider_timeout_seconds,
        )

    raise AmazonProductIntelligenceProviderConfigurationError(
        "Amazon product intelligence provider "
        f"'{provider_name.value}' has no runtime adapter."
    )


class IKEAStoreIntelligenceProviderConfigurationError(RuntimeError):
    """Raised when IKEA intelligence is enabled for an unsupported provider."""


def build_ikea_store_intelligence_provider(
    settings: Settings,
) -> IKEAStoreIntelligenceProvider:
    provider_name = settings.ikea_store_intelligence_provider
    if provider_name == IKEAStoreIntelligenceProviderName.DISABLED:
        return FakeIKEAStoreIntelligenceProvider(disabled=True)

    if (
        not settings.ikea_store_intelligence_provider_enabled
        or provider_name == IKEAStoreIntelligenceProviderName.FIXTURE
    ):
        return FakeIKEAStoreIntelligenceProvider()

    if provider_name == IKEAStoreIntelligenceProviderName.SEARCH:
        if (
            not settings.search_provider_enabled
            or settings.search_provider == SearchProviderName.FIXTURE
        ):
            return FakeIKEAStoreIntelligenceProvider()
        if (
            settings.search_provider == SearchProviderName.TAVILY
            and settings.tavily_api_key is None
        ):
            return FakeIKEAStoreIntelligenceProvider()
        return IKEARegionalStoreDiscoveryProvider(
            search_provider=build_search_provider(settings),
        )

    raise IKEAStoreIntelligenceProviderConfigurationError(
        "IKEA store intelligence provider "
        f"'{provider_name.value}' has no runtime adapter."
    )


class VideoSearchProviderConfigurationError(RuntimeError):
    """Raised when video search is enabled for an unsupported configuration."""


def build_video_search_provider(settings: Settings) -> VideoSearchProvider:
    if settings.video_search_provider == VideoSearchProviderName.DISABLED:
        return FakeVideoSearchProvider(disabled=True)

    if (
        not settings.video_search_provider_enabled
        or settings.video_search_provider == VideoSearchProviderName.FIXTURE
    ):
        return FakeVideoSearchProvider()

    if settings.video_search_provider == VideoSearchProviderName.YOUTUBE:
        if settings.youtube_data_api_key is None:
            return FakeVideoSearchProvider()
        return YouTubeDataApiVideoSearchProvider(
            api_key=settings.youtube_data_api_key.get_secret_value(),
            timeout_seconds=settings.provider_timeout_seconds,
        )

    raise VideoSearchProviderConfigurationError(
        "Video search provider "
        f"'{settings.video_search_provider.value}' has no runtime adapter."
    )


def build_transcript_provider(settings: Settings) -> TranscriptProvider:
    if settings.transcript_provider == TranscriptProviderName.DISABLED:
        return FakeTranscriptProvider(disabled=True)

    if (
        not settings.transcript_provider_enabled
        or settings.transcript_provider == TranscriptProviderName.FIXTURE
    ):
        return FakeTranscriptProvider()

    if settings.transcript_provider == TranscriptProviderName.YT_DLP:
        return YtDlpTranscriptProvider(
            deno_executable=settings.youtube_transcript_deno_executable,
            languages=settings.youtube_transcript_languages,
            timeout_seconds=settings.youtube_transcript_timeout_seconds,
            output_limit_bytes=settings.youtube_transcript_output_limit_bytes,
            temp_storage_limit_bytes=(
                settings.youtube_transcript_temp_storage_limit_bytes
            ),
            max_segments=settings.youtube_transcript_max_segments,
        )

    raise AssertionError(
        f"Unhandled transcript provider: {settings.transcript_provider.value}"
    )
