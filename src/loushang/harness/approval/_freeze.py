"""Immutable payload helpers for approval requests."""


from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Never


class _FrozenDict(dict[str, Any]):
    """Immutable dict snapshot that remains compatible with serializers."""

    def _immutable(self, *args: object, **kwargs: object) -> Never:
        del args, kwargs
        raise TypeError("frozen mapping does not support mutation")

    def __setitem__(self, key: str, value: Any) -> Never:
        self._immutable(key, value)

    def __delitem__(self, key: str) -> Never:
        self._immutable(key)

    def clear(self) -> Never:
        self._immutable()

    def pop(self, key: str, default: Any = None) -> Never:
        self._immutable(key, default)

    def popitem(self) -> Never:
        self._immutable()

    def setdefault(self, key: str, default: Any = None) -> Never:
        self._immutable(key, default)

    def update(self, *args: Any, **kwargs: Any) -> Never:
        self._immutable(*args, **kwargs)

    def __ior__(self, other: object) -> Never:
        self._immutable(other)

    def __reduce__(self) -> tuple[type[_FrozenDict], tuple[dict[str, Any]]]:
        return type(self), (dict(self),)

    def __deepcopy__(self, memo: dict[int, Any]) -> _FrozenDict:
        copied = type(self)(
            {deepcopy(key, memo): deepcopy(value, memo) for key, value in self.items()}
        )
        memo[id(self)] = copied
        return copied

def _freeze_mapping(values: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(values, Mapping):
        raise TypeError("ApprovalRequest arguments must be a mapping")
    return _FrozenDict(
        {
            _require_string_key(key): _freeze_value(value)
            for key, value in values.items()
        }
    )

def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenDict(
            {
                _require_string_key(key): _freeze_value(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    if value is None or isinstance(value, str | bool | int | float):
        return value
    raise TypeError(
        "ApprovalRequest argument values must be JSON-compatible mappings, "
        "sequences, strings, numbers, booleans, or null"
    )

def _thaw_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_value(item) for item in value]
    return value

def _require_string_key(key: object) -> str:
    if not isinstance(key, str):
        raise TypeError("ApprovalRequest argument mapping keys must be strings")
    return key
