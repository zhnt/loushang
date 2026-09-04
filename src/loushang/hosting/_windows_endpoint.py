"""Private Windows anonymous-pipe endpoint backend."""

from __future__ import annotations

import asyncio
import math
import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol, TypeVar, cast

from ._endpoint_backend import (
    _EndpointCleanupDebt,
    _EndpointTransport,
    _PlatformEndpointPair,
    _SingleUseProcessInheritance,
)
from ._win32_process import _CtypesWin32Api
from .errors import HostingError, HostingFailureCategory

_T = TypeVar("_T")


class _WindowsEndpointApi(Protocol):
    def create_pipe(self, *, child_reads: bool) -> tuple[int, int]: ...

    def read_pipe(self, handle: int, max_bytes: int) -> bytes: ...

    def write_pipe(self, handle: int, data: bytes) -> None: ...

    def cancel_synchronous_io(self, thread_id: int) -> None: ...

    def close_handle(self, handle: int) -> None: ...


class _WindowsEndpointTransport(_EndpointTransport):
    def __init__(
        self,
        api: _WindowsEndpointApi,
        executor: ThreadPoolExecutor,
        *,
        read_handle: int,
        write_handle: int,
        io_settlement_seconds: float,
    ) -> None:
        self._api = api
        self._executor = executor
        self._read_handle: int | None = read_handle
        self._write_handle: int | None = write_handle
        self._io_settlement_seconds = io_settlement_seconds
        self._read_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._closed = False
        self._closed_event = threading.Event()
        self._operations: set[asyncio.Task[object]] = set()
        self._read_operation: asyncio.Task[bytes] | None = None
        self._write_operation: asyncio.Task[None] | None = None
        self._thread_lock = threading.Lock()
        self._io_threads: set[int] = set()

    async def read(self, max_bytes: int) -> bytes:
        async with self._read_lock:
            operation = self._read_operation
            if operation is None:
                handle = self._read_handle
                if self._closed or handle is None:
                    return b""
                operation = self._blocking_task(
                    self._api.read_pipe, handle, max_bytes
                )
                self._read_operation = operation
            try:
                return await asyncio.shield(operation)
            except OSError:
                if self._closed:
                    return b""
                raise
            finally:
                if operation.done() and self._read_operation is operation:
                    self._read_operation = None

    async def write(self, data: bytes) -> None:
        async with self._write_lock:
            previous = self._write_operation
            if previous is not None:
                try:
                    await asyncio.shield(previous)
                finally:
                    if previous.done() and self._write_operation is previous:
                        self._write_operation = None
            handle = self._write_handle
            if self._closed or handle is None:
                raise BrokenPipeError("Windows host endpoint is closed")
            operation = self._blocking_task(self._api.write_pipe, handle, data)
            self._write_operation = operation
            try:
                await asyncio.shield(operation)
            except OSError as exc:
                if self._closed:
                    raise BrokenPipeError("Windows host endpoint is closed") from exc
                raise
            finally:
                if operation.done() and self._write_operation is operation:
                    self._write_operation = None

    async def close(self) -> None:
        async with self._close_lock:
            if (
                self._closed
                and self._read_handle is None
                and self._write_handle is None
                and not self._operations
            ):
                return
            self._closed = True
            self._closed_event.set()
            failures: list[BaseException] = []
            with self._thread_lock:
                thread_ids = tuple(self._io_threads)
            for thread_id in thread_ids:
                try:
                    self._api.cancel_synchronous_io(thread_id)
                except BaseException as exc:
                    failures.append(exc)
            operations = tuple(self._operations)
            pending: set[asyncio.Task[object]] = set(operations)
            if pending:
                _, pending = await asyncio.wait(
                    pending, timeout=self._io_settlement_seconds
                )
            failures.extend(self._close_host_handles())
            if pending:
                _, pending = await asyncio.wait(
                    pending, timeout=self._io_settlement_seconds
                )
            if pending:
                failures.append(
                    TimeoutError("Windows endpoint I/O did not settle after cancellation")
                )
            if failures:
                raise BaseExceptionGroup(
                    "Windows endpoint transport cleanup failed", failures
                )

    def _blocking_task(
        self, function: Callable[..., _T], *arguments: object
    ) -> asyncio.Task[_T]:
        def invoke() -> _T:
            if self._closed_event.is_set():
                raise OSError("Windows endpoint is closing")
            thread_id = threading.get_native_id()
            with self._thread_lock:
                self._io_threads.add(thread_id)
            try:
                if self._closed_event.is_set():
                    raise OSError("Windows endpoint is closing")
                return function(*arguments)
            finally:
                with self._thread_lock:
                    self._io_threads.discard(thread_id)

        async def run() -> _T:
            return await asyncio.get_running_loop().run_in_executor(
                self._executor, invoke
            )

        task = asyncio.create_task(run(), name="hosting-windows-endpoint-io")
        tracked = cast(asyncio.Task[object], task)
        self._operations.add(tracked)

        def settle(completed: asyncio.Task[object]) -> None:
            self._operations.discard(completed)
            if not completed.cancelled():
                completed.exception()

        tracked.add_done_callback(settle)
        return task

    def _close_host_handles(self) -> list[BaseException]:
        failures: list[BaseException] = []
        for attribute in ("_read_handle", "_write_handle"):
            handle = cast(int | None, getattr(self, attribute))
            if handle is None:
                continue
            try:
                self._api.close_handle(handle)
            except BaseException as exc:
                failures.append(exc)
            else:
                setattr(self, attribute, None)
        return failures


class _WindowsEndpointBackend:
    backend_id = "windows-anonymous-pipes-v1"

    def __init__(
        self,
        *,
        max_endpoints: int = 4,
        io_settlement_seconds: float = 1.0,
        api: _WindowsEndpointApi | None = None,
    ) -> None:
        if type(max_endpoints) is not int or max_endpoints < 1:
            raise ValueError("max_endpoints must be a positive integer")
        if (
            not isinstance(io_settlement_seconds, (int, float))
            or isinstance(io_settlement_seconds, bool)
            or not math.isfinite(io_settlement_seconds)
            or io_settlement_seconds <= 0
        ):
            raise ValueError("io_settlement_seconds must be positive and finite")
        if api is None and os.name != "nt":
            raise HostingError(
                HostingFailureCategory.PLATFORM_UNSUPPORTED,
                "Windows anonymous-pipe endpoints are unavailable",
            )
        self._api = api or _CtypesWin32Api()
        self._io_settlement_seconds = float(io_settlement_seconds)
        self._executor = ThreadPoolExecutor(
            max_workers=max_endpoints * 2,
            thread_name_prefix="loushang-hosting-win32-endpoint",
        )
        self._closed = False
        self._cleanup_lock = threading.Lock()
        self._cleanup_handles: set[int] = set()
        self._orphan_pairs: list[_PlatformEndpointPair] = []

    async def create_pair(
        self,
        *,
        on_create: Callable[[_PlatformEndpointPair], None],
    ) -> _PlatformEndpointPair:
        if self._closed:
            raise HostingError(
                HostingFailureCategory.HOST_CLOSED,
                "Windows endpoint backend is closed",
            )
        owned: list[int] = []
        try:
            child_stdin, host_write = self._api.create_pipe(child_reads=True)
            owned.extend((child_stdin, host_write))
            host_read, child_stdout = self._api.create_pipe(child_reads=False)
            owned.extend((host_read, child_stdout))
        except (HostingError, asyncio.CancelledError) as primary:
            debt = self._close_acquisition_handles(owned)
            if debt is not None:
                primary.add_note(f"endpoint acquisition cleanup also failed: {debt}")
                raise primary from debt
            raise
        except BaseException as exc:
            debt = self._close_acquisition_handles(owned)
            error = HostingError(
                HostingFailureCategory.ENDPOINT_UNAVAILABLE,
                "Windows endpoint pair creation failed",
            )
            if debt is not None:
                error.add_note(f"endpoint acquisition cleanup also failed: {debt}")
                raise error from debt
            raise error from exc

        child_handles = [child_stdin, child_stdout]

        def close_child() -> None:
            failure = _close_owned_handles(self._api, child_handles)
            if failure is not None:
                raise failure

        pair = _PlatformEndpointPair(
            transport=_WindowsEndpointTransport(
                self._api,
                self._executor,
                read_handle=host_read,
                write_handle=host_write,
                io_settlement_seconds=self._io_settlement_seconds,
            ),
            inheritance=_SingleUseProcessInheritance(
                backend_id="windows-job-v1",
                values=(child_stdin, child_stdout),
                close_values=close_child,
            ),
        )
        owned.clear()
        try:
            on_create(pair)
        except BaseException as primary:
            try:
                await pair.close()
            except BaseException as cleanup:
                with self._cleanup_lock:
                    self._orphan_pairs.append(pair)
                debt = _EndpointCleanupDebt(
                    "Windows endpoint attachment cleanup did not settle",
                    cleanup,
                )
                primary.add_note(f"endpoint attachment cleanup also failed: {cleanup}")
                raise primary from debt
            raise
        return pair

    async def close_backend(self) -> None:
        self._closed = True
        failures: list[BaseException] = []
        with self._cleanup_lock:
            pairs = tuple(self._orphan_pairs)
            handle_snapshot = set(self._cleanup_handles)
            handles = list(handle_snapshot)
        for pair in pairs:
            try:
                await pair.close()
            except BaseException as exc:
                failures.append(exc)
            else:
                with self._cleanup_lock:
                    if pair in self._orphan_pairs:
                        self._orphan_pairs.remove(pair)
        handle_failure = _close_owned_handles(self._api, handles)
        with self._cleanup_lock:
            self._cleanup_handles.difference_update(
                handle_snapshot - set(handles)
            )
        if handle_failure is not None:
            failures.append(handle_failure)
        if failures:
            raise _EndpointCleanupDebt(
                "Windows endpoint backend cleanup did not settle",
                BaseExceptionGroup("Windows endpoint backend cleanup failed", failures),
            )
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _close_acquisition_handles(
        self,
        owned: list[int],
    ) -> _EndpointCleanupDebt | None:
        handles = list(reversed(owned))
        failure = _close_owned_handles(self._api, handles)
        if failure is None:
            return None
        with self._cleanup_lock:
            self._cleanup_handles.update(handles)
        return _EndpointCleanupDebt(
            "Windows endpoint acquisition cleanup did not settle",
            failure,
        )


def _close_owned_handles(
    api: _WindowsEndpointApi,
    handles: list[int],
) -> BaseException | None:
    failures: list[Exception] = []
    for handle in tuple(handles):
        try:
            api.close_handle(handle)
        except Exception as exc:
            failures.append(exc)
        else:
            handles.remove(handle)
    if failures:
        return ExceptionGroup("Windows endpoint handle cleanup failed", failures)
    return None


__all__: list[str] = []
