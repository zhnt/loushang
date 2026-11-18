"""Bounded Content-Length JSON-RPC peer over an existing process handle.

Own the stream buffer, reader task, request futures and close settlement once.
Protocol-specific method handling and graceful shutdown sequences stay with
the client subclass. This peer grants no process launch authority.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from typing import ClassVar

from .lifecycle import wait_for_process_exit
from .types import ProcessHandle


class ContentLengthJsonRpcProcessTransport:
    """Own reader/writer/request lifetime for protocol-specific subclasses.

    The subclass supplies request entry, reader start and cancellation policy;
    this base is not a standalone public-request peer.
    """

    _protocol_label: ClassVar[str] = "JSON-RPC"
    _process_label: ClassVar[str] = "process"
    _reader_task_name: ClassVar[str] = "json-rpc-process-reader"
    _process_exit_task_name: ClassVar[str] = "json-rpc-process-exit"
    _max_header_bytes: ClassVar[int] = 16 * 1024
    _max_message_bytes: ClassVar[int] = 4 * 1024 * 1024
    _max_pending_requests: ClassVar[int] = 128
    _cancel_request_method: ClassVar[str]
    _error_type: ClassVar[type[Exception]] = RuntimeError
    _response_error_type: ClassVar[type[Exception]] = RuntimeError

    def __init__(
        self,
        handle: ProcessHandle,
        *,
        request_timeout_seconds: float,
        shutdown_timeout_seconds: float,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self._initialize_process_binding(
            handle,
            request_timeout_seconds=request_timeout_seconds,
            shutdown_timeout_seconds=shutdown_timeout_seconds,
        )
        self._initialize_transport_state(on_close=on_close)
        self._initialize_connection_state()
        self._initialize_request_metrics()

    def _initialize_process_binding(
        self,
        handle: ProcessHandle,
        *,
        request_timeout_seconds: float,
        shutdown_timeout_seconds: float,
    ) -> None:
        self._handle = handle
        self._request_timeout_seconds = request_timeout_seconds
        self._shutdown_timeout_seconds = shutdown_timeout_seconds

    def _initialize_transport_state(
        self, *, on_close: Callable[[], None] | None
    ) -> None:
        self._on_close = on_close
        self._buffer = bytearray()
        self._write_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._pending: dict[int, asyncio.Future[object]] = {}
        self._next_request_id = 1
        self._reader_task: asyncio.Task[None] | None = None

    def _initialize_connection_state(self) -> None:
        self._state = "open"

    def _initialize_request_metrics(self) -> None:
        self._request_count = 0
        self._timeout_count = 0
        self._last_request_duration_ms: float | None = None
        self._last_error: str | None = None

    def _start_reader(self) -> None:
        self._reader_task = asyncio.create_task(
            self._reader_loop(), name=self._reader_task_name
        )

    @staticmethod
    def _is_transient_response_error(error: BaseException) -> bool:
        return False

    async def _handle_method(self, message: Mapping[str, object], method: str) -> None:
        """The client may handle incoming protocol-specific requests/notifications."""

    async def _shutdown_protocol(self) -> None:
        """The client may perform its graceful protocol sequence before close."""

    @property
    def is_closed(self) -> bool:
        return self._state == "closed" or (
            self._reader_task is not None and self._reader_task.done()
        )

    @property
    def request_count(self) -> int:
        return self._request_count

    @property
    def timeout_count(self) -> int:
        return self._timeout_count

    @property
    def last_request_duration_ms(self) -> float | None:
        return self._last_request_duration_ms

    @property
    def last_error(self) -> str | None:
        return self._last_error

    async def _request(
        self,
        method: str,
        params: Mapping[str, object],
        *,
        timeout_seconds: float | None,
        allow_closing: bool,
    ) -> object:
        if self.is_closed or (self._state == "closing" and (not allow_closing)):
            raise self._error_type(f"{self._protocol_label} connection is closed")
        if len(self._pending) >= self._max_pending_requests:
            raise self._error_type(f"too many pending {self._protocol_label} requests")
        request_id = self._next_request_id
        self._next_request_id += 1
        self._request_count += 1
        started_at = time.monotonic()
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": dict(params),
                }
            )
            timeout = timeout_seconds or self._request_timeout_seconds
            try:
                return await asyncio.wait_for(asyncio.shield(future), timeout)
            except TimeoutError:
                self._timeout_count += 1
                self._last_error = "request_timeout"
                future.cancel()
                with suppress(self._error_type):
                    await self._notify(
                        self._cancel_request_method,
                        {"id": request_id},
                        allow_closing=allow_closing,
                    )
                raise self._error_type(
                    f"{self._protocol_label} request {method!r} timed out after {timeout:g}s"
                ) from None
            except asyncio.CancelledError:
                future.cancel()
                with suppress(self._error_type):
                    await self._notify(
                        self._cancel_request_method,
                        {"id": request_id},
                        allow_closing=allow_closing,
                    )
                raise
            except self._response_error_type as exc:
                if not self._is_transient_response_error(exc):
                    self._last_error = "request_failed"
                raise
            except BaseException:
                self._last_error = "request_failed"
                raise
        finally:
            self._last_request_duration_ms = round(
                (time.monotonic() - started_at) * 1000, 3
            )
            self._pending.pop(request_id, None)

    async def notify(self, method: str, params: Mapping[str, object]) -> None:
        await self._notify(method, params, allow_closing=False)

    async def _notify(
        self, method: str, params: Mapping[str, object], *, allow_closing: bool
    ) -> None:
        if self.is_closed or (self._state == "closing" and (not allow_closing)):
            raise self._error_type(f"{self._protocol_label} connection is closed")
        await self._write_message(
            {"jsonrpc": "2.0", "method": method, "params": dict(params)}
        )

    async def shutdown(self) -> None:
        async with self._lifecycle_lock:
            if self._state == "closed":
                return
            if self._state == "closing":
                return
            self._state = "closing"
            try:
                await self._cancel_pending_for_close()
                await self._shutdown_protocol()
            finally:
                try:
                    await self._handle.close()
                finally:
                    await self._settle_reader()
                    self._state = "closed"
                    self._fail_pending(
                        self._error_type(
                            f"{self._protocol_label} connection was closed"
                        )
                    )

    async def abort(self) -> None:
        async with self._lifecycle_lock:
            if self._state == "closed":
                return
            self._state = "closing"
            self._fail_pending(
                self._error_type(f"{self._protocol_label} connection was aborted")
            )
            try:
                await self._handle.close()
            finally:
                await self._settle_reader()
                self._state = "closed"
                self._fail_pending(
                    self._error_type(f"{self._protocol_label} connection was aborted")
                )

    async def _wait_for_exit(self) -> None:
        await wait_for_process_exit(
            self._handle,
            timeout_seconds=self._shutdown_timeout_seconds,
            task_name=self._process_exit_task_name,
            error_type=self._error_type,
            error_message=f"waiting for {self._process_label} exit failed",
        )

    async def _cancel_pending_for_close(self) -> None:
        request_ids = tuple(self._pending)
        self._fail_pending(
            self._error_type(f"{self._protocol_label} connection is closing")
        )
        for request_id in request_ids:
            with suppress(self._error_type):
                await self._notify(
                    self._cancel_request_method, {"id": request_id}, allow_closing=True
                )

    async def _settle_reader(self) -> None:
        task = self._reader_task
        if task is None or task is asyncio.current_task():
            return
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError, self._error_type):
            await task

    async def _write_message(self, message: Mapping[str, object]) -> None:
        body = json.dumps(
            _thaw_json(message), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        if len(body) > self._max_message_bytes:
            raise self._error_type(
                f"outbound {self._protocol_label} message exceeds the size limit"
            )
        payload = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
        async with self._write_lock:
            await self._handle.write_stdin(payload)

    async def _reader_loop(self) -> None:
        error: BaseException | None = None
        try:
            while True:
                message = await self._read_message()
                await self._dispatch(message)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            error = exc
        finally:
            if self._state == "open":
                self._state = "closed"
                if error is None:
                    error = self._error_type(f"{self._process_label} closed stdout")
                elif not isinstance(error, self._error_type):
                    error = self._error_type(
                        f"{self._protocol_label} reader failed: {error}"
                    )
                self._last_error = "connection_closed"
                self._fail_pending(error)
            if self._on_close is not None:
                with suppress(Exception):
                    self._on_close()

    async def _read_message(self) -> Mapping[str, object]:
        while b"\r\n\r\n" not in self._buffer:
            if len(self._buffer) > self._max_header_bytes:
                raise self._error_type(
                    f"{self._protocol_label} header exceeds the size limit"
                )
            await self._read_chunk()
        raw_header, _, remainder = self._buffer.partition(b"\r\n\r\n")
        self._buffer = bytearray(remainder)
        content_length: int | None = None
        for line in raw_header.split(b"\r\n"):
            name, separator, value = line.partition(b":")
            if not separator:
                raise self._error_type(f"malformed {self._protocol_label} header")
            if name.strip().lower() == b"content-length":
                try:
                    content_length = int(value.strip())
                except ValueError as exc:
                    raise self._error_type(
                        f"invalid {self._protocol_label} Content-Length"
                    ) from exc
        if content_length is None or not 0 <= content_length <= self._max_message_bytes:
            raise self._error_type(
                f"invalid or missing {self._protocol_label} Content-Length"
            )
        while len(self._buffer) < content_length:
            await self._read_chunk()
        body = bytes(self._buffer[:content_length])
        del self._buffer[:content_length]
        try:
            value = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise self._error_type(
                f"invalid {self._protocol_label} JSON payload"
            ) from exc
        if not isinstance(value, Mapping):
            raise self._error_type(f"{self._protocol_label} message must be an object")
        return value

    async def _read_chunk(self) -> None:
        chunk = await self._handle.read_stdout()
        if not chunk:
            if self._buffer:
                raise self._error_type(f"{self._process_label} closed stdout mid-frame")
            raise EOFError
        self._buffer.extend(chunk)

    async def _dispatch(self, message: Mapping[str, object]) -> None:
        if "method" in message:
            method = message.get("method")
            if not isinstance(method, str):
                raise self._error_type(
                    f"{self._protocol_label} method must be a string"
                )
            await self._handle_method(message, method)
            return
        response_id = message.get("id")
        if not isinstance(response_id, int) or isinstance(response_id, bool):
            raise self._error_type(
                f"{self._protocol_label} response id must be an integer"
            )
        future = self._pending.get(response_id)
        if future is None or future.done():
            return
        error = message.get("error")
        if error is not None:
            future.set_exception(self._response_error_type(error))
        else:
            future.set_result(message.get("result"))

    def _fail_pending(self, error: BaseException) -> None:
        for future in tuple(self._pending.values()):
            if not future.done():
                future.set_exception(error)
        self._pending.clear()


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(name): _thaw_json(item) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(item) for item in value]
    return value


__all__ = ["ContentLengthJsonRpcProcessTransport"]
