"""Serialize clipboard requests without blocking the conversation input loop."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field

from loushang.tui.text_clipboard import TextClipboardWriter


@dataclass(slots=True)
class CopyCoordinator:
    writer: TextClipboardWriter | None
    present: Callable[[str], None]
    _pending: deque[tuple[int, str]] = field(default_factory=deque, init=False)
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _generation: int = field(default=0, init=False)
    _closed: bool = field(default=False, init=False)

    def submit(self, text: str) -> None:
        if self._closed:
            return
        if not text:
            self.present("No completed assistant answer to copy")
            return
        if self.writer is None:
            self.present("Clipboard is unavailable in this terminal")
            return
        self._generation += 1
        self._pending.append((self._generation, text))
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def close(self) -> None:
        self._closed = True
        self._pending.clear()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        while self._pending and not self._closed:
            generation, text = self._pending.popleft()
            assert self.writer is not None
            try:
                result = await self.writer.write(text)
            except Exception as exc:
                if generation == self._generation and not self._closed:
                    self.present(f"Copy failed: {exc}")
                continue
            if generation != self._generation or self._closed:
                continue
            message = {
                "confirmed": "Copied to clipboard",
                "sent": "Sent to terminal clipboard (unconfirmed)",
                "failed": f"Copy failed: {result.message}",
            }[result.outcome]
            self.present(message)


__all__ = ["CopyCoordinator"]
