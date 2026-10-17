"""Durable optional-source progress and honest consultation outcomes."""

from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal

from app.schemas.base import CartCartBaseModel


class SourceConsultationOutcome(CartCartBaseModel):
    status: Literal[
        "no_attempt",
        "interrupted",
        "technical_failure",
        "provider_gap",
        "partial",
        "succeeded",
    ] = "no_attempt"
    failure_type: str | None = None
    diagnostic: str | None = None
    diagnostics: tuple[dict[str, str], ...] = ()


def safe_failure(exc: BaseException, *, phase: str) -> dict[str, str]:
    """Keep the real exception class without persisting arbitrary provider text."""
    detail = "Execution failed; provider availability was not established."
    if isinstance(exc, TimeoutError):
        detail = "The configured execution time limit interrupted this work."
    elif isinstance(exc, (ValueError, TypeError)):
        detail = "Retrieved output did not satisfy the approved evidence contract."
    elif type(exc).__name__ == "CancelledError":
        detail = "Execution was cancelled before this operation completed."
    elif type(exc).__name__ == "MaxTurnsExceeded":
        detail = "The configured SDK turn limit was reached."
    return {"error_type": type(exc).__name__, "safe_detail": detail, "phase": phase}


class SourceConsultationCheckpoint:
    def __init__(
        self, root: Path, run_id: str, compatibility: dict[str, Any],
        *, namespace: str = "source-consultations",
    ) -> None:
        self.run_id = run_id
        self.fingerprint = sha256(
            json.dumps(compatibility, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.path = root / namespace / run_id / f"{self.fingerprint}.json"

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        value = json.loads(self.path.read_text())
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 1
            or value.get("run_id") != self.run_id
            or value.get("compatibility_sha256") != self.fingerprint
        ):
            raise ValueError("Saved source consultation does not match this request.")
        return value

    def save(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            **value,
            "schema_version": 1,
            "run_id": self.run_id,
            "compatibility_sha256": self.fingerprint,
        }
        temporary: str | None = None
        try:
            with NamedTemporaryFile(
                mode="w", dir=self.path.parent, delete=False
            ) as handle:
                temporary = handle.name
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None and Path(temporary).exists():
                Path(temporary).unlink()
