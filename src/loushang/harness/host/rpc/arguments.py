"""Strict argument readers shared by RPC command handlers."""

from __future__ import annotations

from math import isfinite
from typing import Any


def require_mode(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if value in {"all", "one-at-a-time"}:
        return value
    raise ValueError(f"{key} must be 'all' or 'one-at-a-time'")


def require_string(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    if not keys:
        raise ValueError("missing required string field")
    raise ValueError(f"missing required string field: {keys[0]}")


def optional_string(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            return value
        raise ValueError(f"{key} must be a string")
    return None


def optional_number(payload: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, int | float) and not isinstance(value, bool):
            try:
                normalized = float(value)
            except OverflowError as exc:
                raise ValueError(f"{key} must be a finite number") from exc
            if isfinite(normalized):
                return normalized
            raise ValueError(f"{key} must be a finite number")
        raise ValueError(f"{key} must be a number")
    return None


def optional_int(payload: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        raise ValueError(f"{key} must be an integer")
    return None


def optional_bool(payload: dict[str, Any], *keys: str) -> bool | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        raise ValueError(f"{key} must be a boolean")
    return None


def optional_env_pairs(value: object) -> list[list[str]] | None:
    if value is None:
        return None
    if isinstance(value, str) or not isinstance(value, list):
        raise ValueError("env must contain 2-item string pairs")
    normalized: list[list[str]] = []
    for pair in value:
        if (
            isinstance(pair, str)
            or not isinstance(pair, list | tuple)
            or len(pair) != 2
            or not all(isinstance(part, str) for part in pair)
        ):
            raise ValueError("env must contain 2-item string pairs")
        normalized.append([pair[0], pair[1]])
    return normalized


__all__ = [
    "optional_bool",
    "optional_env_pairs",
    "optional_int",
    "optional_number",
    "optional_string",
    "require_mode",
    "require_string",
]
