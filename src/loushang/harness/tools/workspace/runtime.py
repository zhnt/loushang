from __future__ import annotations

import inspect
from collections.abc import Awaitable
from typing import Any, TypeAlias, TypeVar

from loushang.agent.types import AgentToolResult

from .truncate import TruncationResult

T = TypeVar("T")
MaybeAwaitable: TypeAlias = T | Awaitable[T]
_MISSING = object()


async def resolve_maybe_awaitable(value: MaybeAwaitable[T]) -> T:
    if inspect.isawaitable(value):
        return await value
    return value


def is_tool_aborted(signal: object | None) -> bool:
    return bool(signal is not None and getattr(signal, "aborted", False))


def raise_if_tool_aborted(signal: object | None) -> None:
    if is_tool_aborted(signal):
        raise RuntimeError("Operation aborted")


def coerce_int_parameter(
    value: object | None, *, field_name: str, minimum: int | None = None
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field_name} must be an integer")
    if isinstance(value, float) and not value.is_integer():
        raise TypeError(f"{field_name} must be an integer")
    resolved = int(value)
    if minimum is not None and resolved < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}")
    return resolved


async def emit_tool_update(
    on_update: object | None, result: AgentToolResult[Any]
) -> None:
    if on_update is None:
        return
    forwarded = on_update(result)  # type: ignore[operator]
    if inspect.isawaitable(forwarded):
        await forwarded


def pi_truncation_details(result: TruncationResult) -> dict[str, object]:
    return {
        "content": result.content,
        "truncated": result.truncated,
        "truncatedBy": result.truncated_by,
        "totalLines": result.total_lines,
        "totalBytes": result.total_bytes,
        "outputLines": result.output_lines,
        "outputBytes": result.output_bytes,
        "lastLinePartial": result.last_line_partial,
        "firstLineExceedsLimit": result.first_line_exceeds_limit,
        "maxLines": result.max_lines,
        "maxBytes": result.max_bytes,
    }


def resolve_tool_argument_alias(
    arguments: dict[str, Any],
    *,
    canonical: str,
    aliases: tuple[str, ...],
    default: object = _MISSING,
) -> Any:
    resolved: object = _MISSING
    resolved_key: str | None = None
    for key in (canonical, *aliases):
        if key not in arguments:
            continue
        value = arguments[key]
        if resolved is not _MISSING and value != resolved:
            raise ValueError(f"conflicting tool arguments: {resolved_key} and {key}")
        resolved = value
        resolved_key = key
    if resolved is _MISSING:
        return None if default is _MISSING else default
    return resolved


def prepare_tool_arguments(
    value: object, *, aliases: tuple[tuple[str, str], ...]
) -> dict[str, Any]:
    if not isinstance(value, dict):
        return value  # type: ignore[return-value]

    prepared = dict(value)
    for source, target in aliases:
        if source in prepared and target not in prepared:
            prepared[target] = prepared[source]
        elif source in prepared:
            prepared[target] = resolve_tool_argument_alias(
                prepared,
                canonical=target,
                aliases=(source,),
            )
        prepared.pop(source, None)
    return prepared
