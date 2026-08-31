from __future__ import annotations

import inspect
from typing import Any


class DirectAsyncIterator:
    """Advance an async source directly when it already implements ``__anext__``."""

    def __init__(self, source: object) -> None:
        direct_next = getattr(source, "__anext__", None)
        if callable(direct_next):
            self._iterator = source
            self._owns_iterator = False
            return

        iterate = getattr(source, "__aiter__", None)
        if not callable(iterate):
            raise TypeError("async source must define __anext__ or __aiter__")
        self._iterator = iterate()
        self._owns_iterator = self._iterator is not source

    def __aiter__(self) -> DirectAsyncIterator:
        return self

    async def __anext__(self) -> Any:
        return await self._iterator.__anext__()  # type: ignore[attr-defined,no-any-return]

    async def aclose(self) -> None:
        if self._owns_iterator:
            await close_async_source(self._iterator)


async def close_async_source(source: object) -> None:
    """Close an async source without assuming which close spelling it exposes."""

    for name in ("aclose", "close"):
        close = getattr(source, name, None)
        if not callable(close):
            continue
        result = close()
        if inspect.isawaitable(result):
            await result
        return
