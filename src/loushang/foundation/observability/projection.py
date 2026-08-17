from __future__ import annotations

import math
from collections.abc import Mapping

from ..json import JSONValue


def project_diagnostic_mapping(
    value: Mapping[str, object] | None,
    *,
    name: str = "details",
) -> dict[str, JSONValue]:
    if value is None:
        return {}

    result: dict[str, JSONValue] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(f"{name} must be JSON-safe: keys must be strings")
        result[key] = project_diagnostic_value(item, name=f"{name}.{key}")
    return result


def project_diagnostic_value(value: object, *, name: str = "value") -> JSONValue:
    if value is None or isinstance(value, str | bool | int):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError(f"{name} must be JSON-safe: non-finite float")
        return value

    if isinstance(value, list | tuple):
        return [project_diagnostic_value(item, name=f"{name}[]") for item in value]

    if isinstance(value, Mapping):
        return project_diagnostic_mapping(value, name=name)

    raise TypeError(f"{name} must be JSON-safe: got {type(value).__name__}")


__all__ = ["project_diagnostic_mapping", "project_diagnostic_value"]
