"""Transport AppClient over an admitted message stream and closed wire profile."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import TypeVar, cast

from .framing import (
    AppConnectionClosedError,
    AppFramedStreamV1,
    AppMessageStreamV1,
    require_timeout,
)
from .protocol import (
    AckV1,
    AppErrorCodeV1,
    AppFailureV1,
    AppOperationV1,
    AppRequestPayloadV1,
    AppRequestV1,
    AppResultPayloadV1,
    AppServiceError,
    AttachmentEventsV1,
    AttachmentEventV1,
    AttachmentReadEventsV1,
    InteractionRespondV1,
    InvalidAppMessageError,
    MuxAttachmentV1,
    MuxAttachV1,
    MuxCloseV1,
    MuxCreateV1,
    MuxDetachV1,
    MuxListResultV1,
    MuxListV1,
    MuxMemberCloseV1,
    MuxMemberOpenV1,
    MuxReadV1,
    MuxSpaceV1,
    SessionSnapshotRequestV1,
    SessionSnapshotV1,
    TurnInterruptV1,
    TurnTextV1,
    decode_response,
    encode_request,
)
from .protocol.connection_profile import AppConnectionProfileV1, connection_hello
from .protocol.stdio_profile import (
    CONTROL_OPERATIONS,
    MAX_CONTROL_REQUESTS,
    MAX_ORDINARY_REQUESTS,
)

_Result = TypeVar("_Result", bound=AppResultPayloadV1)


@dataclass(frozen=True, slots=True)
class _Pending:
    future: asyncio.Future[AppResultPayloadV1]
    result_type: type[object]
    control: bool


class RemoteAppClientV1:
    """Own one connection, never a process; publish before calling start()."""

    def __init__(
        self, stream: AppMessageStreamV1, *, profile: AppConnectionProfileV1,
        phase_timeout: float = 10.0,
    ) -> None:
        require_timeout(phase_timeout)
        self._hello = connection_hello(profile)
        self._stream = stream
        self._timeout = phase_timeout
        self._reader: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._stream_close_task: asyncio.Task[None] | None = None
        self._pending: dict[str, _Pending] = {}
        self._counts = {False: 0, True: 0}
        self._send_lock = asyncio.Lock()
        self._next_id = 0
        self._started = False
        self._ready = False
        self._closed = False

    async def start(self) -> None:
        if self._started or self._closed:
            raise AppConnectionClosedError()
        self._started = True
        try:
            async with asyncio.timeout(self._timeout):
                if await self._stream.receive() != self._hello:
                    raise InvalidAppMessageError()
                await self._stream.send(self._hello)
            self._ready = True
            self._reader = asyncio.create_task(self._receive_responses())
        except BaseException:
            await self.close()
            raise

    async def _call(
        self,
        operation: AppOperationV1,
        payload: AppRequestPayloadV1,
        result_type: type[_Result],
    ) -> _Result:
        if not self._ready or self._closed:
            raise AppConnectionClosedError()
        control = operation in CONTROL_OPERATIONS
        maximum = MAX_CONTROL_REQUESTS if control else MAX_ORDINARY_REQUESTS
        if self._counts[control] >= maximum:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        self._counts[control] += 1
        registered = False
        try:
            async with asyncio.timeout(self._timeout):
                async with self._send_lock:
                    if self._closed:
                        raise AppConnectionClosedError()
                    self._next_id += 1
                    if self._next_id > (1 << 63) - 1:
                        raise AppConnectionClosedError()
                    request_id = str(self._next_id)
                    encoded = encode_request(
                        AppRequestV1(request_id, operation, payload)
                    )
                    future: asyncio.Future[AppResultPayloadV1] = (
                        asyncio.get_running_loop().create_future()
                    )
                    # A cancelled local caller still owns a bounded remote slot.
                    future.add_done_callback(_observe_future)
                    self._pending[request_id] = _Pending(future, result_type, control)
                    registered = True
                    try:
                        await self._stream.send(encoded)
                    except BaseException:
                        await self.close()
                        raise
        except BaseException:
            if not registered:
                self._counts[control] -= 1
            raise
        result = await asyncio.shield(future)
        return cast(_Result, result)

    async def _receive_responses(self) -> None:
        try:
            while not self._closed:
                response = decode_response(await self._stream.receive())
                pending = self._pending.get(response.request_id)
                if pending is None:
                    raise InvalidAppMessageError()
                result = response.result
                if (
                    type(result) is not AppFailureV1
                    and type(result) is not pending.result_type
                ):
                    raise InvalidAppMessageError()
                del self._pending[response.request_id]
                self._counts[pending.control] -= 1
                if type(result) is AppFailureV1:
                    pending.future.set_exception(AppServiceError(result.code))
                else:
                    pending.future.set_result(result)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._fail_pending()
        finally:
            self._fail_pending()
            # Explicit close retains the stream and can retry settlement.
            with suppress(AppServiceError):
                await self._close_stream()

    def _fail_pending(self) -> None:
        self._closed = True
        for pending in self._pending.values():
            self._counts[pending.control] -= 1
            if not pending.future.done():
                pending.future.set_exception(AppConnectionClosedError())
        self._pending.clear()

    async def close(self) -> None:
        self._fail_pending()
        task = self._close_task
        if task is None or _failed(task):
            task = asyncio.create_task(self._close_once())
            task.add_done_callback(_observe_task)
            self._close_task = task
        done, _ = await asyncio.wait({task}, timeout=self._timeout)
        if not done:
            # Keep the exact cleanup task even if an IO adapter ignores cancel.
            raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)
        await asyncio.shield(task)

    async def _close_once(self) -> None:
        reader = self._reader
        if (
            reader is not None
            and reader is not asyncio.current_task()
            and not reader.done()
        ):
            reader.cancel()
        await self._close_stream()
        if reader is not None and reader is not asyncio.current_task():
            await asyncio.gather(reader, return_exceptions=True)

    async def _close_stream(self) -> None:
        task = self._stream_close_task
        if task is None or _failed(task):
            task = asyncio.create_task(self._stream.close())
            task.add_done_callback(_observe_task)
            self._stream_close_task = task
        await asyncio.shield(task)

    async def create_mux(self, request: MuxCreateV1) -> MuxSpaceV1:
        return await self._call(AppOperationV1.MUX_CREATE, request, MuxSpaceV1)

    async def list_muxes(self) -> MuxListResultV1:
        return await self._call(AppOperationV1.MUX_LIST, MuxListV1(), MuxListResultV1)

    async def read_mux(self, request: MuxReadV1) -> MuxSpaceV1:
        return await self._call(AppOperationV1.MUX_READ, request, MuxSpaceV1)

    async def attach_mux(self, request: MuxAttachV1) -> MuxAttachmentV1:
        return await self._call(AppOperationV1.MUX_ATTACH, request, MuxAttachmentV1)

    async def detach_mux(self, request: MuxDetachV1) -> AckV1:
        return await self._call(AppOperationV1.MUX_DETACH, request, AckV1)

    async def close_mux(self, request: MuxCloseV1) -> AckV1:
        return await self._call(AppOperationV1.MUX_CLOSE, request, AckV1)

    async def open_member(self, request: MuxMemberOpenV1) -> MuxSpaceV1:
        return await self._call(AppOperationV1.MEMBER_OPEN, request, MuxSpaceV1)

    async def close_member(self, request: MuxMemberCloseV1) -> MuxSpaceV1:
        return await self._call(AppOperationV1.MEMBER_CLOSE, request, MuxSpaceV1)

    async def snapshot_session(
        self, request: SessionSnapshotRequestV1
    ) -> SessionSnapshotV1:
        return await self._call(
            AppOperationV1.SESSION_SNAPSHOT, request, SessionSnapshotV1
        )

    async def start_turn(self, request: TurnTextV1) -> AckV1:
        return await self._call(AppOperationV1.TURN_START, request, AckV1)

    async def steer_turn(self, request: TurnTextV1) -> AckV1:
        return await self._call(AppOperationV1.TURN_STEER, request, AckV1)

    async def follow_up_turn(self, request: TurnTextV1) -> AckV1:
        return await self._call(AppOperationV1.TURN_FOLLOW_UP, request, AckV1)

    async def interrupt_turn(self, request: TurnInterruptV1) -> AckV1:
        return await self._call(AppOperationV1.TURN_INTERRUPT, request, AckV1)

    async def respond_interaction(self, request: InteractionRespondV1) -> AckV1:
        return await self._call(AppOperationV1.INTERACTION_RESPOND, request, AckV1)

    async def read_events(
        self,
        *,
        attachment_id: str,
        controller_generation: int,
        limit: int = 64,
    ) -> tuple[AttachmentEventV1, ...]:
        result = await self._call(
            AppOperationV1.ATTACHMENT_READ_EVENTS,
            AttachmentReadEventsV1(attachment_id, controller_generation, limit),
            AttachmentEventsV1,
        )
        return result.events


class StdioAppClientV1(RemoteAppClientV1):
    """G14 client: fixed foreground profile and unchanged construction."""

    def __init__(self, stream: AppFramedStreamV1, *, phase_timeout: float = 10.0) -> None:
        super().__init__(stream, profile=AppConnectionProfileV1.STDIO, phase_timeout=phase_timeout)


def _observe_future(future: asyncio.Future[AppResultPayloadV1]) -> None:
    if not future.cancelled():
        future.exception()


def _failed(task: asyncio.Task[None]) -> bool:
    return task.done() and (task.cancelled() or task.exception() is not None)


def _observe_task(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


__all__ = ["RemoteAppClientV1", "StdioAppClientV1"]
