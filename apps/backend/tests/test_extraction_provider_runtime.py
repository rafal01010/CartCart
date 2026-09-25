from pathlib import Path

import httpx
import pytest
from pydantic import AnyHttpUrl

from app.core.settings import ExtractionProviderName, Settings
from app.providers import (
    ExtractionProviderOptions,
    FakeExtractionProvider,
    HttpStaticExtractionProvider,
    build_extraction_provider,
)
from app.providers.contracts import (
    SourceAllowAvoidPolicy,
    SourcePolicyAction,
    SourcePolicyRule,
)
from app.schemas.search_sources import ExtractionStatus, SourceType


def test_extraction_runtime_defaults_to_fixture_mode() -> None:
    provider = build_extraction_provider(Settings(_env_file=None))  # type: ignore[call-arg]

    assert isinstance(provider, FakeExtractionProvider)
    assert provider.disabled is False


def test_extraction_runtime_keeps_explicit_fixture_mode_when_enabled() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        extraction_provider=ExtractionProviderName.FIXTURE,
        extraction_provider_enabled=True,
    )

    provider = build_extraction_provider(settings)

    assert isinstance(provider, FakeExtractionProvider)
    assert provider.disabled is False


@pytest.mark.asyncio
async def test_extraction_runtime_supports_explicit_disabled_mode() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        extraction_provider=ExtractionProviderName.DISABLED,
        extraction_provider_enabled=True,
    )

    provider = build_extraction_provider(settings)
    snapshot = await provider.extract(AnyHttpUrl("https://example.com/product"))

    assert isinstance(provider, FakeExtractionProvider)
    assert provider.disabled is True
    assert snapshot.extraction_status == ExtractionStatus.EXCLUDED
    assert snapshot.provider.provider_name == "disabled-extraction"


def test_extraction_runtime_builds_configured_http_static_adapter(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        artifact_dir=tmp_path,
        extraction_provider=ExtractionProviderName.HTTP_STATIC,
        extraction_provider_enabled=True,
    )

    assert isinstance(build_extraction_provider(settings), HttpStaticExtractionProvider)


@pytest.mark.asyncio
async def test_http_static_adapter_fetches_and_extracts_through_one_boundary(
    tmp_path: Path,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            text=(
                "<html><head><title>Fixture Monitor</title></head><body><main>"
                "<p>Fixture product details with enough useful static page text for "
                "the extraction adapter to retain as normalized source evidence.</p>"
                "</main></body></html>"
            ),
            request=request,
        )

    snapshot_dir = tmp_path / "raw-sources"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = HttpStaticExtractionProvider(
            snapshot_dir=snapshot_dir,
            client=client,
        )
        snapshot = await provider.extract(
            AnyHttpUrl("https://example.com/product"),
            ExtractionProviderOptions(source_type=SourceType.RETAILER_LISTING),
        )

    assert snapshot.source_type == SourceType.RETAILER_LISTING
    assert snapshot.extraction_status == ExtractionStatus.PARTIAL
    assert snapshot.extracted_content is not None
    assert "Fixture product details" in snapshot.extracted_content.text
    assert snapshot.provider.provider_name == "http-static-extraction"
    assert snapshot.provider.raw["fetch_provider"] == "http-fetch"
    assert snapshot.provider.raw["extraction_decision_reason"] == "static_too_sparse"
    assert snapshot.raw_artifact is not None
    assert (snapshot_dir / snapshot.raw_artifact.path).is_file()


@pytest.mark.asyncio
async def test_http_static_adapter_returns_failed_snapshot_for_blocked_source(
    tmp_path: Path,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await HttpStaticExtractionProvider(
            snapshot_dir=tmp_path,
            client=client,
        ).extract(AnyHttpUrl("https://example.com/blocked"))

    assert snapshot.extraction_status == ExtractionStatus.FAILED
    assert snapshot.http_status_code == 403
    assert snapshot.provider.raw["extraction_failure_code"] == "blocked"
    assert snapshot.provider.raw["extraction_failure_retryable"] is False
    assert list(tmp_path.rglob("*")) == []


@pytest.mark.asyncio
async def test_http_static_adapter_enforces_extraction_source_policy(
    tmp_path: Path,
) -> None:
    policy = SourceAllowAvoidPolicy(
        avoid=(
            SourcePolicyRule(
                action=SourcePolicyAction.AVOID,
                domain="blocked.example",
                reason="Blocked by fixture policy.",
            ),
        )
    )
    snapshot = await HttpStaticExtractionProvider(snapshot_dir=tmp_path).extract(
        AnyHttpUrl("https://blocked.example/product"),
        ExtractionProviderOptions(source_policy=policy),
    )

    assert snapshot.extraction_status == ExtractionStatus.EXCLUDED
    assert snapshot.provider.raw["extraction_failure_code"] == (
        "source_policy_excluded"
    )
