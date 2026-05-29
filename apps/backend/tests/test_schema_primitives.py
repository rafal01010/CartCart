from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import BaseModel, ValidationError

from app.schemas import (
    Confidence,
    ConfidenceLevel,
    Money,
    Region,
    SessionId,
    SourceReference,
    Timestamp,
    VersionedSchema,
    new_id,
)


class IdPayload(BaseModel):
    session_id: SessionId


class TimestampPayload(BaseModel):
    captured_at: Timestamp


def test_id_primitives_accept_uuid_values_and_strings() -> None:
    generated_id = new_id()

    from_uuid = IdPayload(session_id=generated_id)
    from_string = IdPayload(session_id=str(generated_id))

    assert from_uuid.session_id == generated_id
    assert from_string.session_id == generated_id
    assert isinstance(from_string.session_id, UUID)


def test_id_primitives_reject_non_uuid_values() -> None:
    with pytest.raises(ValidationError):
        IdPayload(session_id="session-123")


def test_timestamp_accepts_timezone_aware_values_and_normalizes_to_utc() -> None:
    payload = TimestampPayload(captured_at="2026-05-29T08:30:00+08:00")

    assert payload.captured_at == datetime(2026, 5, 29, 0, 30, tzinfo=UTC)


def test_timestamp_rejects_naive_values() -> None:
    with pytest.raises(ValidationError):
        TimestampPayload(captured_at=datetime(2026, 5, 29, 8, 30))


def test_money_accepts_non_negative_decimal_amount_and_currency_code() -> None:
    price = Money(amount="1299.99", currency="usd")

    assert price.amount == Decimal("1299.99")
    assert price.currency == "USD"


@pytest.mark.parametrize(
    ("amount", "currency"),
    [
        ("-1.00", "USD"),
        ("10.999", "USD"),
        ("10.00", "US"),
        ("10.00", "US1"),
    ],
)
def test_money_rejects_invalid_amounts_and_currency_codes(
    amount: str, currency: str
) -> None:
    with pytest.raises(ValidationError):
        Money(amount=amount, currency=currency)


def test_region_accepts_country_code_currency_and_locale() -> None:
    region = Region(country_code="ph", currency="php", locale="en-PH")

    assert region.country_code == "PH"
    assert region.currency == "PHP"
    assert region.locale == "en-PH"


@pytest.mark.parametrize(
    "country_code",
    ["USA", "U", "1S"],
)
def test_region_rejects_invalid_country_codes(country_code: str) -> None:
    with pytest.raises(ValidationError):
        Region(country_code=country_code)


def test_confidence_accepts_score_level_and_rationale() -> None:
    confidence = Confidence(
        score=0.82,
        level=ConfidenceLevel.HIGH,
        rationale="Several source-backed signals agree.",
    )

    assert confidence.score == 0.82
    assert confidence.level == ConfidenceLevel.HIGH


@pytest.mark.parametrize("score", [-0.1, 1.1])
def test_confidence_rejects_scores_outside_unit_interval(score: float) -> None:
    with pytest.raises(ValidationError):
        Confidence(score=score, level="medium")


def test_source_reference_accepts_http_url_source_id_and_access_time() -> None:
    source_id = new_id()
    reference = SourceReference(
        source_id=source_id,
        url="https://example.com/review",
        title="Long-term review",
        accessed_at="2026-05-29T00:30:00Z",
    )

    assert reference.source_id == source_id
    assert str(reference.url) == "https://example.com/review"
    assert reference.accessed_at == datetime(2026, 5, 29, 0, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    "payload",
    [
        {"source_id": "source-123", "url": "https://example.com"},
        {"source_id": str(new_id()), "url": "ftp://example.com"},
        {"source_id": str(new_id()), "url": "https://example.com", "title": ""},
        {
            "source_id": str(new_id()),
            "url": "https://example.com",
            "accessed_at": "2026-05-29T00:30:00",
        },
    ],
)
def test_source_reference_rejects_invalid_examples(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        SourceReference(**payload)


def test_versioned_schema_defaults_to_version_one_and_forbids_extra_fields() -> None:
    schema = VersionedSchema()

    assert schema.schema_version == 1

    with pytest.raises(ValidationError):
        VersionedSchema(schema_version=0)

    with pytest.raises(ValidationError):
        VersionedSchema(unexpected=True)
