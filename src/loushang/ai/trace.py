from __future__ import annotations

import math
from collections.abc import Mapping
from contextlib import suppress
from typing import Any, cast

from loushang.foundation.json import JSONValue
from loushang.foundation.observability import get_log

_log = get_log(__name__).bind(component="AITrace")
TRACE_SCHEMA = "loushang.ai.trace.v1"
_DROP = object()
_SAFE_SCALAR_KEYS = frozenset(
    {
        "api",
        "provider",
        "endpoint",
        "model",
        "upstreamModel",
        "requestId",
        "request_id",
        "response_id",
        "callId",
        "tool_call_id",
        "id",
        "tool_name",
        "name",
        "statusCode",
        "status_code",
        "code",
        "level",
        "field",
        "reason",
        "retryable",
        "attempt",
        "maxAttempts",
        "delayMs",
        "before",
        "after",
        "remaining",
        "event_type",
        "exceptionType",
        "providerResponseSummary",
        "args_source",
        "valid_json",
        "repair_valid",
        "kind",
        "mode",
        "present",
        "empty",
        "error_position",
    }
)
_SAFE_KEY_LIST_KEYS = frozenset(
    {
        "keys",
        "parameter_keys",
        "argument_keys",
        "repaired_keys",
    }
)


TraceEvent = dict[str, JSONValue]


def emit_trace(options: Any | None, event: Mapping[str, object]) -> None:
    normalized = normalize_trace_event(event)
    _emit_options_trace(options, normalized)
    _emit_observability_trace(normalized)


def normalize_trace_event(event: Mapping[str, object]) -> TraceEvent:
    event_type = _trace_type(event)
    source, name = _trace_source_name(event_type)
    data: dict[str, JSONValue] = {}
    for raw_key, value in event.items():
        key = str(raw_key)
        if key == "type":
            continue
        normalized = _safe_trace_value(key, value)
        if normalized is not _DROP:
            data[key] = cast(JSONValue, normalized)
    return {
        "schema": TRACE_SCHEMA,
        "type": event_type,
        "source": source,
        "name": name,
        "data": data,
    }


def _emit_options_trace(options: Any | None, event: TraceEvent) -> None:
    if options is None:
        return
    handler = getattr(options, "trace", None)
    if callable(handler):
        with suppress(Exception):
            handler(event)


def _emit_observability_trace(event: TraceEvent) -> None:
    with suppress(Exception):
        _log.debug_event(
            "provider",
            _event_name(event),
            event=event,
        )


def _event_name(event: Mapping[str, object]) -> str:
    raw_type = event.get("type")
    if isinstance(raw_type, str) and raw_type:
        return raw_type.replace(":", ".")
    return "event"


def _trace_type(event: Mapping[str, object]) -> str:
    raw_type = event.get("type")
    if isinstance(raw_type, str) and raw_type:
        return raw_type
    return "event"


def _trace_source_name(event_type: str) -> tuple[str, str]:
    if ":" in event_type:
        source, name = event_type.split(":", 1)
        return source or "event", name or "event"
    return "event", event_type


def _safe_trace_value(key: str, value: object) -> JSONValue | object:
    if key == "args" and isinstance(value, Mapping):
        return _summarize_tool_args(value)
    if key in _SAFE_KEY_LIST_KEYS:
        if isinstance(value, (list, tuple)) and all(
            isinstance(item, str) for item in value
        ):
            return list(value)
        return _DROP
    if key in _SAFE_SCALAR_KEYS:
        return _safe_scalar(value)
    if key.endswith(("_tokens", "Tokens", "_chars", "Chars", "_count", "Count")):
        return _safe_number(value)
    if isinstance(value, BaseException):
        return {"exceptionType": type(value).__name__}
    return _DROP


def _safe_scalar(value: object) -> JSONValue | object:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _DROP
    return _DROP


def _safe_number(value: object) -> JSONValue | object:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return _DROP
    return value if not isinstance(value, float) or math.isfinite(value) else _DROP


def _summarize_tool_args(args: Mapping[str, object]) -> dict[str, JSONValue]:
    keys: list[JSONValue] = [str(key) for key in sorted(args, key=str)]
    summary: dict[str, JSONValue] = {
        "kind": "object",
        "keys": keys,
    }
    content = args.get("content")
    if isinstance(content, str):
        summary["content_chars"] = len(content)
    command = args.get("command")
    if isinstance(command, str):
        summary["command_chars"] = len(command)
    return summary


__all__ = ["TRACE_SCHEMA", "TraceEvent", "emit_trace", "normalize_trace_event"]
