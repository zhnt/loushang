"""Foreground connection lifetime, independent of application construction."""

from __future__ import annotations

import asyncio

from .client import AppClientV1
from .dispatch import dispatch_request
from .framing import (
    AppConnectionClosedError,
    AppConnectionEOFError,
    AppFramedStreamV1,
    require_timeout,
)
from .protocol import (
    AppErrorCodeV1,
    AppFailureV1,
    AppRequestV1,
    AppResponseV1,
    AppResultPayloadV1,
    AppServiceError,
    InvalidAppMessageError,
    decode_request,
    encode_response,
)
from .protocol.stdio_profile import (
    CONTROL_OPERATIONS,
    MAX_CONTROL_REQUESTS,
    MAX_ORDINARY_REQUESTS,
    STDIO_HELLO_V1,
    connection_request_number,
)


class AppServerConnectionV1:
    """Own request tasks and IO, never the injected service/application."""

    def __init__(
        self,
        client: AppClientV1,
        stream: AppFramedStreamV1,
        *,
        phase_timeout: float = 10.0,
    ) -> None:
        require_timeout(phase_timeout)
        self._client = client
        self._stream = stream
        self._timeout = phase_timeout
        self._tasks: set[asyncio.Task[None]] = set()
        self._receiver: asyncio.Task[None] | None = None
        self._fault: asyncio.Future[None] | None = None
        self._counts = {False: 0, True: 0}
        self._last_id = 0
        self._started = False
        self._closed = False
        self._close_lock = asyncio.Lock()

    async def serve(self) -> None:
        if self._started or self._closed:
            raise AppConnectionClosedError()
        self._started = True
        self._fault = asyncio.get_running_loop().create_future()
        try:
            async with asyncio.timeout(self._timeout):
                await self._stream.send(STDIO_HELLO_V1)
                if await self._stream.receive() != STDIO_HELLO_V1:
                    raise InvalidAppMessageError()
            self._receiver = asyncio.create_task(self._receive_requests())
            completed, _ = await asyncio.wait(
                {self._receiver, self._fault}, return_when=asyncio.FIRST_COMPLETED
            )
            if self._fault in completed:
                raise AppConnectionClosedError()
            await self._receiver
        except TimeoutError:
            raise AppConnectionClosedError() from None
        finally:
            await self.close()

    async def _receive_requests(self) -> None:
        while not self._closed:
            try:
                payload = await self._stream.receive()
            except AppConnectionEOFError:
                return
            request = decode_request(payload)
            number = connection_request_number(request.request_id)
            if number <= self._last_id:
                raise InvalidAppMessageError()
            self._last_id = number
            control = request.operation in CONTROL_OPERATIONS
            maximum = MAX_CONTROL_REQUESTS if control else MAX_ORDINARY_REQUESTS
            if self._counts[control] >= maximum:
                await self._stream.send(
                    encode_response(
                        AppResponseV1(
                            request.request_id,
                            AppFailureV1(AppErrorCodeV1.OPERATION_UNAVAILABLE),
                        )
                    )
                )
                continue
            self._counts[control] += 1
            task = asyncio.create_task(self._execute(request, control=control))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _execute(self, request: AppRequestV1, *, control: bool) -> None:
        try:
            try:
                result: AppResultPayloadV1 = await dispatch_request(
                    self._client, request
                )
            except AppServiceError as error:
                result = AppFailureV1(error.code)
            except Exception:
                result = AppFailureV1(AppErrorCodeV1.OPERATION_UNAVAILABLE)
            await self._stream.send(
                encode_response(AppResponseV1(request.request_id, result))
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            if self._fault is not None and not self._fault.done():
                self._fault.set_result(None)
        finally:
            self._counts[control] -= 1

    async def close(self) -> None:
        async with self._close_lock:
            self._closed = True
            tasks = set(self._tasks)
            if self._receiver is not None:
                tasks.add(self._receiver)
            for task in tasks:
                if not task.done():
                    task.cancel()
            pending: set[asyncio.Task[None]] = set()
            if tasks:
                done, pending = await asyncio.wait(tasks, timeout=self._timeout)
                for task in done:
                    if not task.cancelled():
                        task.exception()
            await self._stream.close()
            if pending:
                raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)


__all__ = ["AppServerConnectionV1"]
