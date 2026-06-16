from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import AnyHttpUrl, Field, ValidationError

from app.schemas.base import CartCartBaseModel, VersionedSchema


MAX_FIXTURE_RESULTS = 20
MAX_FIXTURE_STRING_LENGTH = 1_000
_OMITTED_KEYS = {
    "access_token",
    "answer",
    "api_key",
    "apikey",
    "authorization",
    "client_secret",
    "images",
    "raw_content",
    "refresh_token",
    "secret",
    "token",
    "x-api-key",
}


class ProviderFixtureError(RuntimeError):
    """Raised when a provider fixture cannot be loaded, recorded, or replayed."""


class ProviderFixtureRequest(CartCartBaseModel):
    method: Literal["GET", "POST"]
    url: AnyHttpUrl
    params: dict[str, str] = Field(default_factory=dict)
    json_body: dict[str, Any] | None = Field(
        default=None,
        alias="json",
        serialization_alias="json",
    )


class ProviderFixtureResponse(CartCartBaseModel):
    status_code: int = Field(ge=100, le=599)
    json_body: dict[str, Any] = Field(alias="json", serialization_alias="json")


class ProviderHttpFixture(VersionedSchema):
    provider_name: str = Field(min_length=1, max_length=120)
    request: ProviderFixtureRequest
    response: ProviderFixtureResponse


def load_provider_fixture(path: Path) -> ProviderHttpFixture:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ProviderHttpFixture.model_validate(payload)
    except (OSError, ValueError, ValidationError) as exc:
        raise ProviderFixtureError(f"Invalid provider fixture: {path}") from exc


def write_provider_fixture(
    path: Path,
    *,
    provider_name: str,
    request_method: str,
    request_url: str,
    request_json: Mapping[str, Any] | None,
    request_params: Mapping[str, str] | None = None,
    response_status_code: int,
    response_json: Mapping[str, Any],
    secret_values: Iterable[str] = (),
) -> ProviderHttpFixture:
    normalized_method = request_method.upper()
    if normalized_method not in {"GET", "POST"}:
        raise ProviderFixtureError("Provider fixtures support GET and POST only.")

    fixture = ProviderHttpFixture(
        provider_name=provider_name,
        request=ProviderFixtureRequest(
            method=normalized_method,
            url=request_url,
            params=dict(request_params or {}),
            json=(
                _sanitize_json(request_json)
                if request_json is not None
                else None
            ),
        ),
        response=ProviderFixtureResponse(
            status_code=response_status_code,
            json=_sanitize_json(response_json),
        ),
    )
    serialized = json.dumps(
        fixture.model_dump(mode="json", by_alias=True),
        indent=2,
        sort_keys=True,
    ) + "\n"
    for secret in secret_values:
        if secret and secret in serialized:
            raise ProviderFixtureError("Refusing to write a fixture containing a secret.")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized, encoding="utf-8")
    return fixture


def provider_fixture_transport(
    fixtures: ProviderHttpFixture | Sequence[ProviderHttpFixture],
) -> httpx.MockTransport:
    fixture_sequence = (
        (fixtures,)
        if isinstance(fixtures, ProviderHttpFixture)
        else tuple(fixtures)
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        request_url = str(request.url.copy_with(query=None))
        request_params = {
            key: value
            for key, value in request.url.params.items()
            if key.casefold() not in _OMITTED_KEYS
        }
        request_json = _request_json(request)

        for fixture in fixture_sequence:
            expected = fixture.request
            if (
                request.method == expected.method
                and request_url == str(expected.url)
                and request_params == expected.params
                and request_json == expected.json_body
            ):
                return httpx.Response(
                    fixture.response.status_code,
                    json=fixture.response.json_body,
                    request=request,
                )

        raise ProviderFixtureError(
            "Provider replay request method, URL, parameters, or JSON did not match "
            "a fixture."
        )

    return httpx.MockTransport(handler)


def _request_json(request: httpx.Request) -> dict[str, Any] | None:
    if not request.content:
        return None
    try:
        value = json.loads(request.content)
    except ValueError as exc:
        raise ProviderFixtureError("Provider replay request is not valid JSON.") from exc
    if not isinstance(value, dict):
        raise ProviderFixtureError("Provider replay request JSON must be an object.")
    return value


def _sanitize_json(value: Mapping[str, Any]) -> dict[str, Any]:
    sanitized = _sanitize_value(value)
    if not isinstance(sanitized, dict):
        raise ProviderFixtureError("Provider fixture payload must be a JSON object.")
    return sanitized


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_value(item)
            for key, item in value.items()
            if str(key).lower() not in _OMITTED_KEYS
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_sanitize_value(item) for item in value[:MAX_FIXTURE_RESULTS]]
    if isinstance(value, str):
        return value[:MAX_FIXTURE_STRING_LENGTH]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise ProviderFixtureError(
        f"Provider fixture payload contains unsupported type: {type(value).__name__}."
    )
