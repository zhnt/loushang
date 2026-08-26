from __future__ import annotations

import inspect


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
