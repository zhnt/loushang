"""Strict codec for content-free attempt usage observations."""

from __future__ import annotations

from collections.abc import Mapping

from loushang.foundation.json import JSONValue, require_json_mapping
from loushang.harness.transcript.model_usage_types import ModelCallAttemptUsage

_FIELDS = {
    "schemaVersion",
    "invocationId",
    "attempt",
    "modelInputSnapshotId",
    "input",
    "output",
    "cacheRead",
    "cacheWrite",
    "totalTokens",
    "terminal",
}


def encode_model_call_attempt_usage(payload: object) -> JSONValue:
    if not isinstance(payload, ModelCallAttemptUsage):
        raise TypeError("payload must be ModelCallAttemptUsage")
    return {
        "schemaVersion": payload.schema_version,
        "invocationId": payload.invocation_id,
        "attempt": payload.attempt,
        "modelInputSnapshotId": payload.model_input_snapshot_id,
        "input": payload.input,
        "output": payload.output,
        "cacheRead": payload.cache_read,
        "cacheWrite": payload.cache_write,
        "totalTokens": payload.total_tokens,
        "terminal": payload.terminal,
    }


def decode_model_call_attempt_usage(value: JSONValue) -> ModelCallAttemptUsage:
    payload = require_json_mapping(value, name="model call attempt usage")
    unexpected = set(payload).difference(_FIELDS)
    missing = _FIELDS.difference(payload)
    if unexpected:
        raise ValueError(
            "model call attempt usage contains unknown fields: "
            + ", ".join(sorted(unexpected))
        )
    if missing:
        raise ValueError(
            "model call attempt usage is missing fields: "
            + ", ".join(sorted(missing))
        )
    terminal = payload["terminal"]
    if not isinstance(terminal, bool):
        raise TypeError("model call attempt usage terminal must be boolean")
    return ModelCallAttemptUsage(
        schema_version=_required_int(payload, "schemaVersion"),
        invocation_id=_required_text(payload, "invocationId"),
        attempt=_required_int(payload, "attempt"),
        model_input_snapshot_id=_required_text(payload, "modelInputSnapshotId"),
        input=_optional_int(payload, "input"),
        output=_optional_int(payload, "output"),
        cache_read=_optional_int(payload, "cacheRead"),
        cache_write=_optional_int(payload, "cacheWrite"),
        total_tokens=_optional_int(payload, "totalTokens"),
        terminal=terminal,
    )


def _required_text(value: Mapping[str, JSONValue], key: str) -> str:
    field = value[key]
    if not isinstance(field, str) or not field.strip():
        raise TypeError(f"model call attempt usage {key} must be non-empty text")
    return field


def _required_int(value: Mapping[str, JSONValue], key: str) -> int:
    field = value[key]
    if isinstance(field, bool) or not isinstance(field, int):
        raise TypeError(f"model call attempt usage {key} must be an integer")
    return field


def _optional_int(value: Mapping[str, JSONValue], key: str) -> int | None:
    field = value[key]
    if field is None:
        return None
    if isinstance(field, bool) or not isinstance(field, int):
        raise TypeError(f"model call attempt usage {key} must be an integer or null")
    return field


__all__ = [
    "decode_model_call_attempt_usage",
    "encode_model_call_attempt_usage",
]
