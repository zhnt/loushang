from __future__ import annotations

import re
from collections.abc import Mapping

_FIRST_CAP_RE = re.compile(r"(.)([A-Z][a-z]+)")
_ALL_CAP_RE = re.compile(r"([a-z0-9])([A-Z])")


def _snake_case_key(key: object) -> str:
    text = str(key)
    text = _FIRST_CAP_RE.sub(r"\1_\2", text)
    return _ALL_CAP_RE.sub(r"\1_\2", text).lower()


def snake_case_json_keys(value: object) -> object:
    """Normalize event payload keys without changing enum/string values."""

    if isinstance(value, Mapping):
        return {
            _snake_case_key(key): snake_case_json_keys(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [snake_case_json_keys(item) for item in value]
    if isinstance(value, tuple):
        return [snake_case_json_keys(item) for item in value]
    return value


__all__ = ["snake_case_json_keys"]
