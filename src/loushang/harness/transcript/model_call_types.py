"""Durable, content-free terminal outcomes for logical model invocations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import Literal, TypeAlias, cast

from loushang.ai.json_codec import deserialize_usage, serialize_usage
from loushang.ai.prepared_request import PreparedModelCallOutcome
from loushang.ai.types import StopReason, Usage
from loushang.foundation.json import JSONValue

MODEL_CALL_OUTCOME_SCHEMA_VERSION = 1
ModelCallDisposition: TypeAlias = Literal["completed", "failed", "cancelled"]

_SAFE_FAILURE_STRING_DETAILS = frozenset(
    {
        "exceptionType",
        "rawCode",
        "providerErrorType",
        "providerErrorCode",
        "capacityMetric",
        "capacityLimit",
    }
)
_SAFE_FAILURE_NUMERIC_DETAILS = frozenset(
    {
        "maxParts",
        "maxBytes",
        "partCount",
        "estimatedBytes",
        "canonicalBytes",
        "estimatedWireBytes",
        "messageBytes",
        "messageCount",
        "imageBytes",
        "toolSchemaBytes",
        "estimatedInputTokens",
        "limitBytes",
        "limitMessages",
        "capacityValue",
        "capacityMaximum",
    }
)


@dataclass(frozen=True)
class ModelCallFailureInfo:
    code: str
    source: str
    retryable: bool
    status_code: int | None = None
    request_id: str | None = None
    details: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_bounded_text(
            self.code,
            name="model call failure code",
            max_characters=128,
        )
        _require_bounded_text(
            self.source,
            name="model call failure source",
            max_characters=256,
        )
        if not isinstance(self.retryable, bool):
            raise TypeError("model call failure retryable must be boolean")
        if self.status_code is not None and (
            isinstance(self.status_code, bool)
            or not isinstance(self.status_code, int)
            or self.status_code < 100
            or self.status_code > 599
        ):
            raise ValueError("model call failure status code is invalid")
        if self.request_id is not None:
            _require_bounded_text(
                self.request_id,
                name="model call failure request id",
                max_characters=512,
            )
        object.__setattr__(
            self,
            "details",
            MappingProxyType(_safe_failure_details(self.details)),
        )


@dataclass(frozen=True)
class ModelCallOutcome:
    invocation_id: str
    model_input_snapshot_ids: tuple[str, ...]
    disposition: ModelCallDisposition
    stop_reason: StopReason
    usage: Usage
    failure: ModelCallFailureInfo | None = None
    schema_version: int = MODEL_CALL_OUTCOME_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MODEL_CALL_OUTCOME_SCHEMA_VERSION:
            raise ValueError(
                "unsupported model call outcome schema version: "
                f"{self.schema_version}"
            )
        _require_bounded_text(
            self.invocation_id,
            name="model call invocation id",
            max_characters=256,
        )
        snapshot_ids = _require_text_sequence(
            self.model_input_snapshot_ids,
            name="model call Model Input snapshot ids",
        )
        if len(snapshot_ids) != len(set(snapshot_ids)):
            raise ValueError("model call Model Input snapshot ids must be unique")
        if not snapshot_ids and self.disposition == "completed":
            raise ValueError(
                "a completed model call requires a Model Input snapshot"
            )
        expected_disposition: ModelCallDisposition
        if self.stop_reason == "error":
            expected_disposition = "failed"
        elif self.stop_reason == "aborted":
            expected_disposition = "cancelled"
        elif self.stop_reason in {"stop", "length", "toolUse"}:
            expected_disposition = "completed"
        else:
            raise ValueError(f"unsupported model call stop reason: {self.stop_reason}")
        if self.disposition != expected_disposition:
            raise ValueError("model call disposition does not match stop reason")
        if not isinstance(self.usage, Usage):
            raise TypeError("model call outcome usage must be Usage")
        object.__setattr__(self, "usage", _canonical_usage(self.usage))
        if self.disposition == "failed":
            if not isinstance(self.failure, ModelCallFailureInfo):
                raise ValueError("failed model call outcome requires failure info")
        elif self.failure is not None:
            raise ValueError("non-failed model call outcome cannot contain failure info")
        object.__setattr__(self, "model_input_snapshot_ids", snapshot_ids)

    @classmethod
    def from_prepared_outcome(
        cls,
        outcome: PreparedModelCallOutcome,
        *,
        model_input_snapshot_ids: Sequence[str],
    ) -> ModelCallOutcome:
        if not isinstance(outcome, PreparedModelCallOutcome):
            raise TypeError("model call outcome requires PreparedModelCallOutcome")
        return cls(
            invocation_id=outcome.invocation_id,
            model_input_snapshot_ids=tuple(model_input_snapshot_ids),
            disposition=outcome.disposition,
            stop_reason=outcome.stop_reason,
            usage=outcome.usage,
            failure=(
                _failure_from_error_info(outcome.error_info)
                if outcome.disposition == "failed"
                else None
            ),
        )


def _failure_from_error_info(
    value: Mapping[str, object] | None,
) -> ModelCallFailureInfo:
    if not isinstance(value, Mapping):
        raise ValueError("failed model call outcome has no typed error info")
    code = value.get("code")
    source = value.get("source")
    retryable = value.get("retryable")
    if not isinstance(code, str) or not isinstance(source, str):
        raise ValueError("failed model call outcome error identity is invalid")
    if not isinstance(retryable, bool):
        raise ValueError("failed model call outcome retryability is invalid")
    status_code = value.get("statusCode")
    request_id = value.get("requestId")
    details = value.get("details")
    return ModelCallFailureInfo(
        code=code,
        source=source,
        retryable=retryable,
        status_code=(status_code if isinstance(status_code, int) else None),
        request_id=(request_id if isinstance(request_id, str) else None),
        details=(details if isinstance(details, Mapping) else {}),
    )


def _safe_failure_details(value: object) -> dict[str, JSONValue]:
    if not isinstance(value, Mapping):
        raise TypeError("model call failure details must be a mapping")
    safe: dict[str, JSONValue] = {}
    for key in sorted(_SAFE_FAILURE_STRING_DETAILS):
        item = value.get(key)
        if isinstance(item, str) and item:
            safe[key] = item[:256]
    for key in sorted(_SAFE_FAILURE_NUMERIC_DETAILS):
        item = value.get(key)
        if (
            isinstance(item, int | float)
            and not isinstance(item, bool)
            and isfinite(item)
            and 0 <= item <= 2**63 - 1
        ):
            safe[key] = item
    return safe


def _canonical_usage(usage: Usage) -> Usage:
    for name in ("input", "output", "cache_read", "cache_write", "total_tokens"):
        value = getattr(usage, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"model call usage {name} must be non-negative")
    canonical = deserialize_usage(serialize_usage(usage))
    if canonical != usage:
        raise ValueError("model call usage cost must be finite and non-negative")
    return canonical


def _require_text_sequence(value: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple | list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise TypeError(f"{name} must be a sequence of non-empty strings")
    items = tuple(cast(Sequence[str], value))
    if len(items) > 4_096:
        raise ValueError(f"{name} exceeds 4096 entries")
    if any(len(item) > 256 for item in items):
        raise ValueError(f"{name} contains an oversized identifier")
    return items


def _require_text(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def _require_bounded_text(
    value: object,
    *,
    name: str,
    max_characters: int,
) -> str:
    text = _require_text(value, name=name)
    if len(text) > max_characters:
        raise ValueError(f"{name} exceeds {max_characters} characters")
    return text


__all__ = [
    "MODEL_CALL_OUTCOME_SCHEMA_VERSION",
    "ModelCallDisposition",
    "ModelCallFailureInfo",
    "ModelCallOutcome",
]
