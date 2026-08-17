"""Strict JSON codec for terminal logical model-call outcomes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from loushang.ai.json_codec import deserialize_usage, serialize_usage
from loushang.ai.types import StopReason
from loushang.foundation.json import JSONValue, require_json_mapping, require_json_value
from loushang.harness.transcript.model_call_types import (
    ModelCallDisposition,
    ModelCallFailureInfo,
    ModelCallOutcome,
)


def encode_model_call_outcome(payload: object) -> JSONValue:
    if not isinstance(payload, ModelCallOutcome):
        raise TypeError("payload must be ModelCallOutcome")
    return {
        "schemaVersion": payload.schema_version,
        "invocationId": payload.invocation_id,
        "modelInputSnapshotIds": list(payload.model_input_snapshot_ids),
        "disposition": payload.disposition,
        "stopReason": payload.stop_reason,
        "usage": require_json_value(serialize_usage(payload.usage)),
        "failure": (
            _encode_failure(payload.failure) if payload.failure is not None else None
        ),
    }


def decode_model_call_outcome(value: JSONValue) -> ModelCallOutcome:
    payload = _object(
        value,
        name="model call outcome",
        fields={
            "schemaVersion",
            "invocationId",
            "modelInputSnapshotIds",
            "disposition",
            "stopReason",
            "usage",
            "failure",
        },
    )
    disposition = _text(payload, "disposition")
    stop_reason = _text(payload, "stopReason")
    if disposition not in {"completed", "failed", "cancelled"}:
        raise ValueError("model call outcome disposition is invalid")
    if stop_reason not in {"stop", "length", "toolUse", "error", "aborted"}:
        raise ValueError("model call outcome stop reason is invalid")
    raw_snapshot_ids = _field(payload, "modelInputSnapshotIds")
    if not isinstance(raw_snapshot_ids, list):
        raise TypeError("model call outcome snapshot ids must be an array")
    usage = require_json_mapping(_field(payload, "usage"), name="model call usage")
    raw_failure = _field(payload, "failure")
    return ModelCallOutcome(
        schema_version=_positive_int(payload, "schemaVersion"),
        invocation_id=_text(payload, "invocationId"),
        model_input_snapshot_ids=tuple(_string_item(item) for item in raw_snapshot_ids),
        disposition=cast(ModelCallDisposition, disposition),
        stop_reason=cast(StopReason, stop_reason),
        usage=deserialize_usage(dict(usage)),
        failure=(None if raw_failure is None else _decode_failure(raw_failure)),
    )


def _encode_failure(value: ModelCallFailureInfo) -> dict[str, JSONValue]:
    return {
        "code": value.code,
        "source": value.source,
        "retryable": value.retryable,
        "statusCode": value.status_code,
        "requestId": value.request_id,
        "details": dict(value.details),
    }


def _decode_failure(value: object) -> ModelCallFailureInfo:
    payload = _object(
        value,
        name="model call failure",
        fields={
            "code",
            "source",
            "retryable",
            "statusCode",
            "requestId",
            "details",
        },
    )
    retryable = _field(payload, "retryable")
    if not isinstance(retryable, bool):
        raise TypeError("model call failure retryable must be boolean")
    status_code = _field(payload, "statusCode")
    if status_code is not None and (
        isinstance(status_code, bool) or not isinstance(status_code, int)
    ):
        raise TypeError("model call failure status code must be integer or null")
    request_id = _field(payload, "requestId")
    if request_id is not None and not isinstance(request_id, str):
        raise TypeError("model call failure request id must be text or null")
    details = require_json_mapping(
        _field(payload, "details"),
        name="model call failure details",
    )
    return ModelCallFailureInfo(
        code=_text(payload, "code"),
        source=_text(payload, "source"),
        retryable=retryable,
        status_code=status_code,
        request_id=request_id,
        details=details,
    )


def _object(
    value: object,
    *,
    name: str,
    fields: set[str],
) -> dict[str, JSONValue]:
    payload = require_json_mapping(value, name=name)
    unexpected = set(payload).difference(fields)
    if unexpected:
        raise ValueError(f"{name} contains unknown fields: {', '.join(sorted(unexpected))}")
    missing = fields.difference(payload)
    if missing:
        raise ValueError(f"{name} is missing fields: {', '.join(sorted(missing))}")
    return payload


def _field(value: Mapping[str, JSONValue], key: str) -> JSONValue:
    try:
        return value[key]
    except KeyError as exc:
        raise ValueError(f"model call payload is missing {key!r}") from exc


def _text(value: Mapping[str, JSONValue], key: str) -> str:
    field = _field(value, key)
    if not isinstance(field, str) or not field.strip():
        raise TypeError(f"model call field {key!r} must be non-empty text")
    return field


def _string_item(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError("model call snapshot id must be non-empty text")
    return value


def _positive_int(value: Mapping[str, JSONValue], key: str) -> int:
    field = _field(value, key)
    if isinstance(field, bool) or not isinstance(field, int) or field < 1:
        raise TypeError(f"model call field {key!r} must be a positive integer")
    return field


__all__ = ["decode_model_call_outcome", "encode_model_call_outcome"]
