"""Strict JSON value contracts shared across Loushang subsystems."""

from __future__ import annotations

import json as stdlib_json
import math
from collections.abc import Callable
from typing import TypeAlias, cast

JSONPrimitive: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONPrimitive | list["JSONValue"] | dict[str, "JSONValue"]

_MAX_ERROR_PATH_CHARS = 512
_MAX_ERROR_PATH_SEGMENT_CHARS = 80
_TRUNCATED_PATH_SUFFIX = "...[truncated]"


class JsonValueError(TypeError):
    def __init__(self, message: str, *, path: str, value_type: str) -> None:
        super().__init__(message)
        self.path = path
        self.value_type = value_type


def require_json_value(value: object, *, name: str = "value") -> JSONValue:
    """Validate and copy a value from the strict JSON algebra."""

    return _require_json_value(value, path=name, seen=set())


def require_json_mapping(
    value: object,
    *,
    name: str = "value",
) -> dict[str, JSONValue]:
    projected = require_json_value(value, name=name)
    if not isinstance(projected, dict):
        raise JsonValueError(
            f"{name} must be a JSON object, got {type(value).__name__}",
            path=name,
            value_type=type(value).__name__,
        )
    return projected


def dump_json_value(
    value: object,
    *,
    name: str = "value",
    ensure_ascii: bool = False,
    sort_keys: bool = False,
    separators: tuple[str, str] | None = (",", ":"),
) -> str:
    projected = require_json_value(value, name=name)
    return stdlib_json.dumps(
        projected,
        ensure_ascii=ensure_ascii,
        sort_keys=sort_keys,
        separators=separators,
        allow_nan=False,
    )


def _require_json_value(
    value: object,
    *,
    path: str,
    seen: set[int],
) -> JSONValue:
    if value is None:
        return None
    if type(value) is str:
        return _require_json_string(cast(str, value), path=path)
    if type(value) is bool:
        return cast(bool, value)
    if type(value) is int:
        return _require_json_integer(cast(int, value), path=path)
    if type(value) is float:
        value = cast(float, value)
        if not math.isfinite(value):
            raise JsonValueError(
                f"{path} must be JSON-safe: non-finite float",
                path=path,
                value_type="float",
            )
        return value
    if type(value) is list:
        list_value = cast(list[object], value)
        return cast(
            list[JSONValue],
            _project_container(
                list_value,
                path=path,
                seen=seen,
                project=lambda: [
                    _require_json_value(item, path=f"{path}[{index}]", seen=seen)
                    for index, item in enumerate(list_value)
                ],
            ),
        )
    if type(value) is dict:
        value = cast(dict[object, object], value)
        return cast(
            dict[str, JSONValue],
            _project_container(
                value,
                path=path,
                seen=seen,
                project=lambda: _project_mapping(value, path=path, seen=seen),
            ),
        )
    raise JsonValueError(
        f"{path} must be JSON-safe: got {type(value).__name__}",
        path=path,
        value_type=type(value).__name__,
    )


def _project_mapping(
    value: dict[object, object],
    *,
    path: str,
    seen: set[int],
) -> dict[str, JSONValue]:
    result: dict[str, JSONValue] = {}
    for key, item in value.items():
        if type(key) is not str:
            raise JsonValueError(
                f"{path} must be JSON-safe: keys must be strings",
                path=path,
                value_type=type(key).__name__,
            )
        key = _require_json_string(cast(str, key), path=path)
        child_path = _mapping_child_path(path, key)
        result[key] = _require_json_value(item, path=child_path, seen=seen)
    return result


def _mapping_child_path(path: str, key: str) -> str:
    display_key = key
    if len(display_key) > _MAX_ERROR_PATH_SEGMENT_CHARS:
        display_key = display_key[: _MAX_ERROR_PATH_SEGMENT_CHARS - 3] + "..."
    suffix = (
        f".{display_key}"
        if display_key and display_key.isidentifier()
        else f"[{stdlib_json.dumps(display_key, ensure_ascii=True)}]"
    )
    candidate = path + suffix
    if len(candidate) <= _MAX_ERROR_PATH_CHARS:
        return candidate
    return (
        candidate[: _MAX_ERROR_PATH_CHARS - len(_TRUNCATED_PATH_SUFFIX)]
        + _TRUNCATED_PATH_SUFFIX
    )


def _require_json_string(value: str, *, path: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise JsonValueError(
            f"{path} must be JSON-safe: string is not valid UTF-8",
            path=path,
            value_type="str",
        ) from exc
    return value


def _require_json_integer(value: int, *, path: str) -> int:
    try:
        str(value)
    except ValueError as exc:
        raise JsonValueError(
            f"{path} must be JSON-safe: integer exceeds the encoder limit",
            path=path,
            value_type="int",
        ) from exc
    return value


def _project_container(
    value: object,
    *,
    path: str,
    seen: set[int],
    project: Callable[[], object],
) -> object:
    object_id = id(value)
    if object_id in seen:
        raise JsonValueError(
            f"{path} must be JSON-safe: circular reference",
            path=path,
            value_type=type(value).__name__,
        )
    seen.add(object_id)
    try:
        return project()
    finally:
        seen.remove(object_id)


__all__ = [
    "JSONPrimitive",
    "JSONValue",
    "JsonValueError",
    "dump_json_value",
    "require_json_mapping",
    "require_json_value",
]
