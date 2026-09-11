"""Transport AppClient over an admitted message stream and closed wire profile."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import TypeVar, cast

from .client import SessionDiscoveryClientV1
from .execution.codec import (
    decode_execution_hello,
    encode_call,
    is_execution_frame,
)
from .execution.codec import decode_response as decode_execution_response
from .execution.model import (
    ExecutionCallV1,
    ExecutionFailureV1,
    ExecutionServiceErrorV1,
)
from .execution.remote import RemoteExecutionClientV1
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
    SessionListResultV1,
    SessionListV1,
    SessionSnapshotRequestV1,
    SessionSnapshotV1,
    TurnInterruptV1,
    TurnTextV1,
    decode_response,
    encode_request,
)
from .protocol.connection_profile import (
    AppConnectionProfileV1,
    connection_hello,
    require_profile_operation,
    supports_execution,
    supports_session_discovery,
)
from .protocol.stdio_profile import (
    CONTROL_OPERATIONS,
    MAX_CONTROL_REQUESTS,
    MAX_ORDINARY_REQUESTS,
)

_Result = TypeVar("_Result", bound=AppResultPayloadV1)


@dataclass(frozen=True, slots=True)
class _Pending:
    future: asyncio.Future[object]
    result_type: type[object]
    control: bool
    execution: bool = False
    allow_missing: bool = False


class RemoteAppClientV1:
    """Own one connection, never a process; publish before calling start()."""

    def __init__(
        self, stream: AppMessageStreamV1, *, profile: AppConnectionProfileV1,
        phase_timeout: float = 10.0,
    ) -> None:
        require_timeout(phase_timeout)
        self._hello = b"" if supports_execution(profile) else connection_hello(profile)
        self._profile = profile
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
        self._execution_client: RemoteExecutionClientV1 | None = None

    @property
    def execution_client(self) -> RemoteExecutionClientV1 | None:
        return self._execution_client if self._ready and not self._closed else None

    @property
    def discovery_client(self) -> SessionDiscoveryClientV1 | None:
        """Borrow only the explicitly selected, ready discovery capability."""
        if self._ready and not self._closed and supports_session_discovery(self._profile):
            return self
        return None

    async def start(self, *, timeout: float | None = None) -> None:
        """Negotiate once; an owner may supply its remaining startup budget.

        None preserves the connection phase default. This override applies only
        to the complete hello exchange, never later sends, close or frame IO.
        """
        budget = self._timeout if timeout is None else timeout
        require_timeout(budget)
        if self._started or self._closed:
            raise AppConnectionClosedError()
        self._started = True
        try:
            async with asyncio.timeout(budget):
                hello = await self._stream.receive()
                if supports_execution(self._profile):
                    instance = decode_execution_hello(hello, self._profile.value)
                    self._hello = hello
                    self._execution_client = RemoteExecutionClientV1(instance, self._send_execution)
                elif hello != self._hello:
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
        require_profile_operation(self._profile, operation)
        result = await self._send_encoded(
            lambda request_id: encode_request(AppRequestV1(request_id, operation, payload)),
            result_type, control=operation in CONTROL_OPERATIONS,
        )
        return cast(_Result, result)

    async def _send_execution(
        self, build: Callable[[str], ExecutionCallV1], result_type: type[object],
        control: bool, allow_missing: bool,
    ) -> object:
        if self.execution_client is None:
            raise AppConnectionClosedError()
        return await self._send_encoded(
            lambda request_id: encode_call(build(request_id)), result_type,
            control=control, execution=True, allow_missing=allow_missing,
        )

    async def _send_encoded(
        self, encode: Callable[[str], bytes], result_type: type[object], *,
        control: bool, execution: bool = False, allow_missing: bool = False,
    ) -> object:
        if not self._ready or self._closed:
            raise AppConnectionClosedError()
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
                    encoded = encode(request_id)
                    future: asyncio.Future[object] = (
                        asyncio.get_running_loop().create_future()
                    )
                    # A cancelled local caller still owns a bounded remote slot.
                    future.add_done_callback(_observe_future)
                    self._pending[request_id] = _Pending(
                        future, result_type, control, execution, allow_missing
                    )
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
        return result

    async def _receive_responses(self) -> None:
        try:
            while not self._closed:
                payload = await self._stream.receive()
                execution = self._execution_client is not None and is_execution_frame(payload)
                response = decode_execution_response(payload) if execution else decode_response(payload)
                pending = self._pending.get(response.request_id)
                if pending is None or pending.execution != execution:
                    raise InvalidAppMessageError()
                result = response.result
                if (
                    type(result) not in (AppFailureV1, ExecutionFailureV1)
                    and type(result) is not pending.result_type
                    and not (pending.allow_missing and result is None)
                ):
                    raise InvalidAppMessageError()
                del self._pending[response.request_id]
                self._counts[pending.control] -= 1
                if type(result) is AppFailureV1:
                    pending.future.set_exception(AppServiceError(result.code))
                elif type(result) is ExecutionFailureV1:
                    pending.future.set_exception(ExecutionServiceErrorV1(result.code))
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

    async def list_sessions(self, request: SessionListV1) -> SessionListResultV1:
        result = await self._call(
            AppOperationV1.SESSIONS_LIST, request, SessionListResultV1
        )
        if (
            result.product_id != request.product_id
            or result.scope is not request.scope
            or result.scope_fingerprint != request.scope_fingerprint
            or len(result.candidates) > request.limit
        ):
            await self.close()
            raise InvalidAppMessageError()
        return result

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


def _observe_future(future: asyncio.Future[object]) -> None:
    if not future.cancelled():
        future.exception()


def _failed(task: asyncio.Task[None]) -> bool:
    return task.done() and (task.cancelled() or task.exception() is not None)


def _observe_task(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


__all__ = ["RemoteAppClientV1", "StdioAppClientV1"]
