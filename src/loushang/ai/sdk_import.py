"""Keep first-use SDK imports off the caller's event loop."""

from __future__ import annotations

import asyncio
from importlib import import_module
from threading import Lock
from typing import Any

_PACKAGES = {
    "anthropic-messages": "anthropic",
    "openai-completions": "openai",
    "openai-responses": "openai",
}
_inflight: dict[tuple[asyncio.AbstractEventLoop, str], asyncio.Task[Any]] = {}
_lock = Lock()


def sdk_package_for_api(api: str) -> str | None:
    """Return only the SDK used by a built-in API adapter."""

    return _PACKAGES.get(api)


async def load_sdk_symbols(api: str) -> tuple[Any, Any] | None:
    """Share an in-flight import without letting caller cancellation stop it."""

    package = sdk_package_for_api(api)
    if package is None:
        return None
    loop = asyncio.get_running_loop()
    key = (loop, package)
    with _lock:
        task = _inflight.get(key)
        if task is None:
            task = loop.create_task(asyncio.to_thread(import_module, package))
            _inflight[key] = task
            task.add_done_callback(lambda finished: _forget(key, finished))
    module = await asyncio.shield(task)
    constructor = (
        module.AsyncAnthropic if package == "anthropic" else module.AsyncOpenAI
    )
    return constructor, module.Omit


def _forget(
    key: tuple[asyncio.AbstractEventLoop, str], task: asyncio.Task[Any]
) -> None:
    # A cancelled prewarm may be the last waiter for a failing import.
    if not task.cancelled():
        task.exception()
    with _lock:
        if _inflight.get(key) is task:
            del _inflight[key]


__all__ = ["load_sdk_symbols", "sdk_package_for_api"]
