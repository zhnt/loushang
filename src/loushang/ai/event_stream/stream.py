from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import suppress
from typing import Generic, TypeVar, cast

from loushang.ai.errors import (
    AICancelledError,
    AIError,
    AIStreamError,
    ai_error_from_info,
    ai_error_info_from_mapping,
)
from loushang.ai.types import (
    AssistantMessage,
    AssistantMessageEvent,
    DoneEvent,
    ErrorEvent,
)

TEvent = TypeVar("TEvent")
TResult = TypeVar("TResult")

DEFAULT_EVENT_STREAM_QUEUE_SIZE = 256


class EventStream(Generic[TEvent, TResult]):
    def __init__(
        self,
        *,
        is_terminal: Callable[[TEvent], bool],
        extract_result: Callable[[TEvent], TResult],
        max_queue_size: int = DEFAULT_EVENT_STREAM_QUEUE_SIZE,
    ) -> None:
        self._queue: asyncio.Queue[TEvent | None] = asyncio.Queue(
            maxsize=max(1, max_queue_size)
        )
        self._final_result: TResult | None = None
        self._terminal_event: TEvent | None = None
        self._producer_error: BaseException | None = None
        self._ended: bool = False
        self._producer_task: asyncio.Task[object] | None = None
        self._is_terminal = is_terminal
        self._extract_result = extract_result

    def push(self, event: TEvent) -> None:
        if self._ended:
            return
        if self._is_terminal(event):
            self._put_nowait_force(event)
            self._record_terminal(event)
            return
        self._queue.put_nowait(event)

    async def emit(self, event: TEvent) -> None:
        if self._ended:
            return
        await self._queue.put(event)
        if self._is_terminal(event):
            self._record_terminal(event)

    def __aiter__(self) -> AsyncIterator[TEvent]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[TEvent]:
        try:
            while True:
                item = await self._queue.get()
                if item is None:
                    break
                is_terminal = self._is_terminal(item)
                if is_terminal:
                    self._record_terminal(item)
                yield item
                if is_terminal:
                    break
        finally:
            if not self._ended:
                await self.aclose()

    def attach_task(self, task: asyncio.Task[object]) -> None:
        self._producer_task = task
        task.add_done_callback(self._finish_from_task)

    async def aclose(self) -> None:
        if self._ended:
            return
        self._ended = True
        task = self._producer_task
        if task is not None and not task.done():
            task.cancel()
            if task is not asyncio.current_task():
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    self._producer_error = exc
        self._put_nowait_force(None)

    cancel = aclose

    def end(self, result: TResult | None = None) -> None:
        if self._ended:
            return
        self._ended = True
        if result is not None:
            self._final_result = result
        self._put_nowait_force(None)

    async def result(self) -> TResult:
        if self._final_result is not None:
            await self._await_producer_completion()
            return self._final_result

        async for _ in self:
            if self._final_result is not None:
                await self._await_producer_completion()
                return self._final_result

        await self._await_producer_completion()
        if self._final_result is None:
            if self._producer_error is not None:
                raise RuntimeError(
                    "Event stream producer failed"
                ) from self._producer_error
            raise RuntimeError("Event stream finished without a final result")
        return self._final_result

    async def _await_producer_completion(self) -> None:
        task = self._producer_task
        if task is None or task is asyncio.current_task():
            return
        try:
            await task
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self._producer_error = exc

    def _finish_from_task(self, task: asyncio.Task[object]) -> None:
        if self._ended:
            return
        if task.cancelled():
            self.end()
            return
        try:
            self._producer_error = task.exception()
        except asyncio.CancelledError:
            self.end()
            return
        self.end()

    def _record_terminal(self, event: TEvent) -> None:
        if self._terminal_event is None:
            self._terminal_event = event
            self._final_result = self._extract_result(event)
        self._ended = True

    def _put_nowait_force(self, item: TEvent | None) -> None:
        try:
            self._queue.put_nowait(item)
            return
        except asyncio.QueueFull:
            pass
        with suppress(asyncio.QueueEmpty):
            self._queue.get_nowait()
        self._queue.put_nowait(item)


class AssistantMessageEventStream(EventStream[AssistantMessageEvent, AssistantMessage]):
    def __init__(
        self, *, max_queue_size: int = DEFAULT_EVENT_STREAM_QUEUE_SIZE
    ) -> None:
        super().__init__(
            is_terminal=lambda event: event["type"] in {"done", "error"},
            extract_result=_extract_assistant_message_result,
            max_queue_size=max_queue_size,
        )

    def push(self, event: AssistantMessageEvent) -> None:
        self._validate_event(event)
        super().push(event)

    async def emit(self, event: AssistantMessageEvent) -> None:
        self._validate_event(event)
        await super().emit(event)

    async def result(self) -> AssistantMessage:
        message = await self.final_message()
        terminal_event = self._terminal_event
        if terminal_event is not None and terminal_event["type"] == "error":
            raise _error_from_terminal_event(cast(ErrorEvent, terminal_event))
        if message.stop_reason == "aborted":
            raise AICancelledError(
                message.error_message or "Stream aborted",
                source=message.api,
                provider=message.provider,
                endpoint=message.endpoint,
                model=message.model,
                details=_response_details(message),
            )
        if message.stop_reason == "error":
            raise AIStreamError(
                message.error_message or "Stream failed",
                source=message.api,
                provider=message.provider,
                endpoint=message.endpoint,
                model=message.model,
                details=_response_details(message),
            )
        return message

    async def final_message(self) -> AssistantMessage:
        return await super().result()

    def _validate_event(self, event: AssistantMessageEvent) -> None:
        event_type = event["type"]
        if event_type not in {
            "start",
            "text_start",
            "text_delta",
            "text_end",
            "thinking_start",
            "thinking_delta",
            "thinking_end",
            "toolcall_start",
            "toolcall_delta",
            "toolcall_end",
            "image_start",
            "image_end",
            "done",
            "error",
        }:
            raise ValueError(f"Unsupported event type: {event_type}")

    def end(self, message: AssistantMessage | None = None) -> None:
        if self._ended:
            return
        if message is not None:
            done_event: DoneEvent = {
                "type": "done",
                "reason": "stop",
                "message": message,
            }
            self._put_nowait_force(done_event)
            self._record_terminal(done_event)
            return
        self._ended = True
        self._put_nowait_force(None)


def _extract_assistant_message_result(event: AssistantMessageEvent) -> AssistantMessage:
    if event["type"] == "done":
        return event["message"]
    return cast(ErrorEvent, event)["error"]


def _error_from_terminal_event(event: ErrorEvent) -> AIError:
    message = event["error"]
    if event["reason"] == "aborted":
        return AICancelledError(
            message.error_message or "Stream aborted",
            source=message.api,
            provider=message.provider,
            endpoint=message.endpoint,
            model=message.model,
            details=_response_details(message),
        )
    raw_info = event.get("error_info")
    if isinstance(raw_info, Mapping):
        try:
            return ai_error_from_info(ai_error_info_from_mapping(raw_info))
        except ValueError:
            pass
    return AIStreamError(
        message.error_message or "Stream failed",
        source=message.api,
        provider=message.provider,
        endpoint=message.endpoint,
        model=message.model,
        details=_response_details(message),
    )


def _response_details(message: AssistantMessage) -> dict[str, str]:
    if message.response_id is None:
        return {}
    return {"responseId": message.response_id}
