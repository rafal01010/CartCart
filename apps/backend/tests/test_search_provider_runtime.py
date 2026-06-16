import pytest

from app.core.settings import SearchProviderName, Settings
from app.providers import (
    FakeSearchProvider,
    SearchProviderConfigurationError,
    TavilySearchProvider,
    build_search_provider,
)


def test_search_provider_runtime_defaults_to_fixture_mode() -> None:
    provider = build_search_provider(Settings(_env_file=None))  # type: ignore[call-arg]

    assert isinstance(provider, FakeSearchProvider)


def test_search_provider_runtime_builds_enabled_tavily_adapter() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        search_provider=SearchProviderName.TAVILY,
        search_provider_enabled=True,
        tavily_api_key="fixture-key",
    )

    assert isinstance(build_search_provider(settings), TavilySearchProvider)


def test_search_provider_runtime_falls_back_when_live_key_is_missing() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        search_provider=SearchProviderName.TAVILY,
        search_provider_enabled=True,
    )

    assert isinstance(build_search_provider(settings), FakeSearchProvider)


def test_search_provider_runtime_rejects_unimplemented_live_adapter() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        search_provider=SearchProviderName.BRAVE,
        search_provider_enabled=True,
        brave_search_api_key="fixture-key",
    )

    with pytest.raises(SearchProviderConfigurationError):
        build_search_provider(settings)
