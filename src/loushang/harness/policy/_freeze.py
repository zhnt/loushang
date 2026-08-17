"""Immutable mapping helpers for policy argument payloads."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType


def _freeze_mapping(values: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(values, Mapping):
        raise TypeError("arguments must be a mapping")
    return MappingProxyType(
        {
            _require_policy_mapping_key(key): _freeze_value(value)
            for key, value in values.items()
        }
    )


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                _require_policy_mapping_key(key): _freeze_value(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    if value is None or isinstance(value, str | bool | int | float):
        return value
    raise TypeError(
        "policy argument values must be JSON-compatible mappings, sequences, "
        "strings, numbers, booleans, or null"
    )


def _require_policy_mapping_key(key: object) -> str:
    if not isinstance(key, str):
        raise TypeError("policy argument mapping keys must be strings")
    return key
