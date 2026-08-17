from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from loushang.foundation.json import JSONValue, require_json_mapping


@dataclass(frozen=True)
class ContextUsageEstimate:
    tokens: int
    usage_tokens: int
    trailing_tokens: int
    last_usage_index: int | None


def serialize_context_usage_payload(value: object | None) -> dict[str, Any] | None:
    """Serialize context usage into a strict, transport-neutral mapping."""

    if value is None:
        return None
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    raw = require_json_mapping(value, name="context_usage")
    serialized = _camelize(raw)
    if not isinstance(serialized, dict):
        raise TypeError("context usage serialization must produce a mapping")
    return serialized


def _camelize(value: JSONValue) -> JSONValue:
    if isinstance(value, dict):
        return {_snake_to_camel(key): _camelize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_camelize(item) for item in value]
    return value


def _snake_to_camel(value: str) -> str:
    parts = value.split("_")
    if len(parts) == 1:
        return value
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


__all__ = ["ContextUsageEstimate", "serialize_context_usage_payload"]
