"""Acquire an immutable command snapshot from a sync or async product port."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable

CommandItemsSource = Callable[[], object]


async def materialize_command_items(
    source: CommandItemsSource | None,
) -> tuple[object, ...]:
    if source is None:
        return ()
    raw_items = source()
    if inspect.isawaitable(raw_items):
        raw_items = await raw_items
    if not isinstance(raw_items, Iterable):
        return ()
    return tuple(raw_items)


__all__ = ["CommandItemsSource", "materialize_command_items"]
