"""Stable view adapters for product-prepared conversation runtime sources."""

from __future__ import annotations

from collections.abc import Callable

StringQueueReader = Callable[[], tuple[str, ...]]
StringQueueSource = Callable[[], object]


def stable_string_queue_reader(
    source: StringQueueSource | None,
) -> StringQueueReader:
    """Adapt an explicit, possibly fallible source to a stable string queue."""

    def read() -> tuple[str, ...]:
        if source is None:
            return ()
        try:
            values = source()
        except Exception:
            return ()
        if not isinstance(values, list | tuple):
            return ()
        return tuple(value for value in values if isinstance(value, str))

    return read


__all__ = [
    "StringQueueReader",
    "StringQueueSource",
    "stable_string_queue_reader",
]
