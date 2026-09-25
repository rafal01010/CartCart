from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pydantic import AnyHttpUrl

from app.providers.contracts import (
    ExtractionProviderOptions,
    SourceAllowAvoidPolicy,
    SourcePolicyRule,
)
from app.schemas.search_sources import (
    ExtractionStatus,
    ProviderMetadata,
    SourceSnapshot,
    SourceType,
)
from app.services.source_extraction import (
    DynamicExtractionPolicy,
    ExtractionDecisionReason,
    StaticPageExtractionError,
    StaticPageTextExtractor,
)
from app.services.source_fetch import (
    HostResolver,
    HttpSourceFetcher,
    SourceFetchError,
    SourceFetchUnsafeUrlError,
)


class HttpStaticExtractionProvider:
    """Fetch an HTML page, persist it, and run the static extractor."""

    provider_name = "http-static-extraction"

    def __init__(
        self,
        *,
        snapshot_dir: Path,
        timeout_seconds: float = 10.0,
        max_content_bytes: int = 2 * 1024 * 1024,
        user_agent: str = "CartCart/0.1 source-fetcher",
        client: httpx.AsyncClient | None = None,
        max_attempts: int = 2,
        retry_backoff_seconds: float = 0.25,
        max_redirects: int = 10,
        host_resolver: HostResolver | None = None,
        minimum_static_word_count: int = 50,
    ) -> None:
        self._fetcher = HttpSourceFetcher(
            snapshot_dir=snapshot_dir,
            timeout_seconds=timeout_seconds,
            max_content_bytes=max_content_bytes,
            user_agent=user_agent,
            client=client,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            max_redirects=max_redirects,
            host_resolver=host_resolver,
        )
        self._extractor = StaticPageTextExtractor(snapshot_dir=snapshot_dir)
        self._policy = DynamicExtractionPolicy(
            minimum_static_word_count=minimum_static_word_count
        )

    async def extract(
        self,
        url: AnyHttpUrl,
        options: ExtractionProviderOptions | None = None,
    ) -> SourceSnapshot:
        source_type = (
            options.source_type if options is not None else SourceType.PRODUCT_PAGE
        )
        source_policy = (
            options.source_policy if options is not None else SourceAllowAvoidPolicy()
        )
        policy_reason = _source_policy_exclusion_reason(
            url,
            source_type=source_type,
            policy=source_policy,
        )
        if policy_reason is not None:
            return _failed_snapshot(
                url,
                source_type=source_type,
                status=ExtractionStatus.EXCLUDED,
                failure_code="source_policy_excluded",
                failure_message=policy_reason,
                retryable=False,
            )

        try:
            snapshot = await self._fetcher.fetch(url, source_type=source_type)
        except SourceFetchError as exc:
            return _failed_snapshot(
                url,
                source_type=source_type,
                status=(
                    ExtractionStatus.EXCLUDED
                    if isinstance(exc, SourceFetchUnsafeUrlError)
                    else ExtractionStatus.FAILED
                ),
                failure_code=exc.failure_code,
                failure_message=str(exc),
                retryable=exc.retryable,
                http_status_code=exc.http_status_code,
            )

        fetch_provider = snapshot.provider.provider_name
        snapshot.provider = ProviderMetadata(
            provider_name=self.provider_name,
            raw={**snapshot.provider.raw, "fetch_provider": fetch_provider},
        )
        try:
            extracted = self._extractor.extract(snapshot)
        except StaticPageExtractionError as exc:
            extracted = snapshot.model_copy(deep=True)
            extracted.extraction_status = ExtractionStatus.FAILED
            extracted.provider.raw.update(
                {
                    "extraction_failure_code": "static_extraction_failed",
                    "extraction_failure_message": str(exc),
                    "extraction_failure_retryable": False,
                }
            )
            return extracted

        decision = self._policy.decide(extracted)
        extracted.provider.raw.update(
            {
                "extraction_decision": decision.action.value,
                "extraction_decision_reason": decision.reason.value,
            }
        )
        if decision.reason == ExtractionDecisionReason.STATIC_TOO_SPARSE:
            extracted.extraction_status = ExtractionStatus.PARTIAL
        return extracted


def _failed_snapshot(
    url: AnyHttpUrl,
    *,
    source_type: SourceType,
    status: ExtractionStatus,
    failure_code: str,
    failure_message: str,
    retryable: bool,
    http_status_code: int | None = None,
) -> SourceSnapshot:
    return SourceSnapshot(
        url=url,
        source_type=source_type,
        provider=ProviderMetadata(
            provider_name=HttpStaticExtractionProvider.provider_name,
            raw={
                "requested_url": str(url),
                "fetch_provider": HttpSourceFetcher.provider_name,
                "extraction_failure_code": failure_code,
                "extraction_failure_message": failure_message[:500],
                "extraction_failure_retryable": retryable,
            },
        ),
        extraction_status=status,
        http_status_code=http_status_code,
    )


def _source_policy_exclusion_reason(
    url: AnyHttpUrl,
    *,
    source_type: SourceType,
    policy: SourceAllowAvoidPolicy,
) -> str | None:
    hostname = (urlsplit(str(url)).hostname or "").casefold().removeprefix("www.")
    matching_avoid = next(
        (
            rule
            for rule in policy.avoid
            if _rule_matches(rule, hostname=hostname, source_type=source_type)
        ),
        None,
    )
    if matching_avoid is not None:
        return matching_avoid.reason
    if policy.allow and not any(
        _rule_matches(rule, hostname=hostname, source_type=source_type)
        for rule in policy.allow
    ):
        return "Source is outside the extraction allow policy."
    return None


def _rule_matches(
    rule: SourcePolicyRule,
    *,
    hostname: str,
    source_type: SourceType,
) -> bool:
    if rule.source_type is not None and rule.source_type != source_type:
        return False
    if rule.domain is None:
        return True
    domain = rule.domain.casefold().strip(".").removeprefix("www.")
    return hostname == domain or hostname.endswith(f".{domain}")
