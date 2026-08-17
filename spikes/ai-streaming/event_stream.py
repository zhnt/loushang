from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass

from spike_types import AssistantMessage, AssistantMessageEvent


class AssistantMessageEventStream:
    def __init__(self) -> None:
        self._events: deque[AssistantMessageEvent | _Sentinel] = deque()
        self._waiters: list[asyncio.Future[AssistantMessageEvent | _Sentinel]] = []
        self._result: AssistantMessage | None = None
        self._result_waiters: list[asyncio.Future[AssistantMessage]] = []
        self._closed = False

    def _push(self, event: AssistantMessageEvent) -> None:
        if self._closed:
            return
        if self._waiters:
            future = self._waiters.pop(0)
            future.set_result(event)
        else:
            self._events.append(event)

    def _finish(self, message: AssistantMessage) -> None:
        if self._closed:
            return
        self._closed = True
        self._result = message
        self._events.append(_Sentinel())
        self._wake_waiters(_Sentinel())
        self._wake_result_waiters(message)

    def _fail(self, message: AssistantMessage) -> None:
        if self._closed:
            return
        self._closed = True
        self._result = message
        self._events.append(_Sentinel())
        self._wake_waiters(_Sentinel())
        self._wake_result_waiters(message)

    def _wake_waiters(self, value: AssistantMessageEvent | _Sentinel) -> None:
        while self._waiters:
            future = self._waiters.pop(0)
            if not future.done():
                future.set_result(value)

    def _wake_result_waiters(self, value: AssistantMessage) -> None:
        while self._result_waiters:
            future = self._result_waiters.pop(0)
            if not future.done():
                future.set_result(value)

    def __aiter__(self):
        return self

    async def __anext__(self) -> AssistantMessageEvent:
        item = await self._next_item()
        if isinstance(item, _Sentinel):
            raise StopAsyncIteration
        return item

    async def _next_item(self) -> AssistantMessageEvent | _Sentinel:
        if self._events:
            return self._events.popleft()

        if self._closed:
            return _Sentinel()

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._waiters.append(future)
        item = await future
        return item

    async def result(self) -> AssistantMessage:
        if self._result is not None:
            return self._result

        if self._closed:
            assert self._result is not None
            return self._result

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._result_waiters.append(future)
        return await future


@dataclass(slots=True)
class _Sentinel:
    pass


class _StreamWriter:
    def __init__(self, stream: AssistantMessageEventStream) -> None:
        self._stream = stream

    def push(self, event: AssistantMessageEvent) -> None:
        self._stream._push(event)

    def finish(self, message: AssistantMessage) -> None:
        self._stream._finish(message)

    def fail(self, message: AssistantMessage) -> None:
        self._stream._fail(message)


def create_assistant_message_event_stream() -> tuple[AssistantMessageEventStream, _StreamWriter]:
    stream = AssistantMessageEventStream()
    return stream, _StreamWriter(stream)
