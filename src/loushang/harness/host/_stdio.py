"""Shared stdio behavior for Product-facing hosts."""

from __future__ import annotations

import asyncio
import io
from typing import TextIO


def stream_supports_fileno(stream: TextIO) -> bool:
    """Whether reading ``stream`` must be offloaded from the event loop."""

    fileno = getattr(stream, "fileno", None)
    if not callable(fileno):
        return False
    try:
        fileno()
    except (io.UnsupportedOperation, OSError, ValueError):
        return False
    return True


async def read_line(stream: TextIO, *, use_thread: bool) -> str:
    """Read one line without blocking the event loop for real stdio streams."""

    if use_thread:
        return await asyncio.to_thread(stream.readline)
    return stream.readline()
