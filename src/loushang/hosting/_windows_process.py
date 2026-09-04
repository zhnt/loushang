"""Private Windows Job Object process backend for Hosting."""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Protocol, TypeVar, cast

from ._launch_preparation import _ManagedSpawnEffect
from ._process_backend import _ProcessInheritance, _ProcessTransport
from ._win32_process import (
    _CtypesWin32Api,
    _Win32CreateNotStarted,
    _Win32CreateSettledWithoutProcess,
    _Win32SpawnHandles,
)
from .contracts import (
    ProcessLaunchRequest,
    ProcessStdinMode,
    ProcessStdoutMode,
)
from .errors import HostingError, HostingFailureCategory

_TREE_POLL_SECONDS = 0.01
_INITIAL_TERMINATION_EXIT_CODE = 0xE0000001
_FORCEFUL_TERMINATION_EXIT_CODE = 0xE0000002
_IO_SETTLEMENT_SECONDS = 1.0
_T = TypeVar("_T")


class _Win32Api(Protocol):
    def spawn(
        self,
        request: ProcessLaunchRequest,
        endpoint_handles: tuple[int, int] | None = None,
    ) -> _Win32SpawnHandles: ...

    def spawn_restricted(
        self,
        request: ProcessLaunchRequest,
        endpoint_handles: tuple[int, int],
        *,
        executable_handle: int,
        cwd_handle: int,
        token: int,
        job: int,
        stderr_handle: int,
        begin_effect: Callable[[], None],
    ) -> _Win32SpawnHandles: ...

    def read_pipe(self, handle: int, max_bytes: int) -> bytes: ...

    def write_pipe(self, handle: int, data: bytes) -> None: ...

    def wait_process(self, handle: int) -> int: ...

    def process_return_code(self, handle: int) -> int | None: ...

    def job_is_empty(self, handle: int) -> bool: ...

    def terminate_job(self, handle: int, exit_code: int) -> None: ...

    def close_handle(self, handle: int) -> None: ...

    def cancel_synchronous_io(self, thread_id: int) -> None: ...


class _WindowsProcess:
    def __init__(
        self,
        api: _Win32Api,
        executor: ThreadPoolExecutor,
        handles: _Win32SpawnHandles,
    ) -> None:
        if handles.process <= 0 or handles.job <= 0:
            raise RuntimeError("Windows process has invalid owner handles")
        self._api = api
        self._executor = executor
        self._process_handle: int | None = handles.process
        self._job_handle: int | None = handles.job
        self._stdin_write = handles.stdin_write
        self._stdout_read = handles.stdout_read
        self._stderr_read = handles.stderr_read
        self._cleanup_handles = list(handles.cleanup_handles)
        self._stdin_closed = False
        self._handles_closed = False
        self._close_lock = asyncio.Lock()
        self._stdin_operation_lock = asyncio.Lock()
        self._stdout_operation_lock = asyncio.Lock()
        self._stderr_operation_lock = asyncio.Lock()
        self._operations: set[asyncio.Task[object]] = set()
        self._operations_fenced = False
        self._stdout_operation: asyncio.Task[bytes] | None = None
        self._stderr_operation: asyncio.Task[bytes] | None = None
        self._stdin_operation: asyncio.Task[None] | None = None
        self._wait_operation: asyncio.Task[int] | None = None
        self._thread_lock = threading.Lock()
        self._io_threads: dict[str, int] = {}
        self._closed_event = threading.Event()

    @property
    def return_code(self) -> int | None:
        if self._process_handle is None:
            return None
        return self._api.process_return_code(self._process_handle)

    async def read_stdout(self, max_bytes: int) -> bytes:
        async with self._stdout_operation_lock:
            operation = self._stdout_operation
            if operation is None:
                handle = self._stdout_read
                if self._operations_fenced or handle is None:
                    return b""
                operation = self._blocking_task(
                    "stdout", self._api.read_pipe, handle, max_bytes
                )
                self._stdout_operation = operation
            try:
                return await asyncio.shield(operation)
            except OSError:
                if self._operations_fenced:
                    return b""
                raise
            finally:
                if operation.done() and self._stdout_operation is operation:
                    self._stdout_operation = None

    async def read_stderr(self, max_bytes: int) -> bytes:
        async with self._stderr_operation_lock:
            operation = self._stderr_operation
            if operation is None:
                handle = self._stderr_read
                if self._operations_fenced or handle is None:
                    return b""
                operation = self._blocking_task(
                    "stderr", self._api.read_pipe, handle, max_bytes
                )
                self._stderr_operation = operation
            try:
                return await asyncio.shield(operation)
            except OSError:
                if self._operations_fenced:
                    return b""
                raise
            finally:
                if operation.done() and self._stderr_operation is operation:
                    self._stderr_operation = None

    async def write_stdin(self, data: bytes) -> None:
        async with self._stdin_operation_lock:
            previous = self._stdin_operation
            if previous is not None:
                try:
                    await asyncio.shield(previous)
                finally:
                    if previous.done() and self._stdin_operation is previous:
                        self._stdin_operation = None
            handle = self._stdin_write
            if (
                self._operations_fenced
                or handle is None
                or self._stdin_closed
            ):
                raise BrokenPipeError("Windows process stdin is closed")
            operation = self._blocking_task(
                "stdin", self._api.write_pipe, handle, data
            )
            self._stdin_operation = operation
            try:
                await asyncio.shield(operation)
            finally:
                if operation.done() and self._stdin_operation is operation:
                    self._stdin_operation = None

    async def close_stdin(self) -> None:
        if self._stdin_closed:
            return
        self._stdin_closed = True
        operation = self._stdin_operation
        if operation is not None and not operation.done():
            self._cancel_active_io(("stdin",))
        async with self._stdin_operation_lock:
            handle = self._stdin_write
            self._stdin_write = None
            if handle is not None:
                self._api.close_handle(handle)

    async def wait(self) -> int:
        operation = self._wait_operation
        if operation is None:
            handle = self._process_handle
            if handle is None:
                raise OSError("Windows process handle is closed")
            operation = self._blocking_task("wait", self._api.wait_process, handle)
            self._wait_operation = operation
        return await asyncio.shield(operation)

    def job_is_empty(self) -> bool:
        if self._job_handle is None:
            return True
        return self._api.job_is_empty(self._job_handle)

    def terminate_job(self, exit_code: int) -> None:
        if self._job_handle is None:
            return
        self._api.terminate_job(self._job_handle, exit_code)

    async def wait_job(self) -> None:
        while not self.job_is_empty():
            await asyncio.sleep(_TREE_POLL_SECONDS)

    async def close_handles(self) -> None:
        async with self._close_lock:
            if self._handles_closed:
                return
            if self._wait_operation is None and self._process_handle is not None:
                self._wait_operation = self._blocking_task(
                    "wait",
                    self._api.wait_process,
                    self._process_handle,
                    allow_when_closing=True,
                )
            self._operations_fenced = True
            self._closed_event.set()
            self._cancel_active_io(("stdin", "stdout", "stderr"))
            errors: list[Exception] = []
            self._close_handle_attribute("_job_handle", errors)
            operations = {
                operation
                for operation in (
                    self._stdin_operation,
                    self._stdout_operation,
                    self._stderr_operation,
                    self._wait_operation,
                )
                if operation is not None and not operation.done()
            }
            pending = operations
            if pending:
                _, pending = await asyncio.wait(
                    pending, timeout=_IO_SETTLEMENT_SECONDS
                )
                if pending:
                    errors.append(
                        TimeoutError("Windows process I/O did not settle during close")
                    )
            for attribute, operation in (
                ("_stdin_write", self._stdin_operation),
                ("_stdout_read", self._stdout_operation),
                ("_stderr_read", self._stderr_operation),
            ):
                if operation not in pending:
                    self._close_handle_attribute(attribute, errors)
            if self._wait_operation not in pending:
                self._close_handle_attribute("_process_handle", errors)
            for handle in tuple(self._cleanup_handles):
                try:
                    self._api.close_handle(handle)
                except Exception as exc:
                    errors.append(exc)
                else:
                    self._cleanup_handles.remove(handle)
            if errors:
                raise ExceptionGroup("Windows process handle cleanup failed", errors)
            self._handles_closed = not self._cleanup_handles

    def _close_handle_attribute(
        self,
        attribute: str,
        errors: list[Exception],
    ) -> None:
        handle = cast(int | None, getattr(self, attribute))
        if handle is None:
            return
        try:
            self._api.close_handle(handle)
        except Exception as exc:
            errors.append(exc)
        else:
            setattr(self, attribute, None)

    def _blocking_task(
        self,
        operation_name: str,
        function: Callable[..., _T],
        *arguments: object,
        allow_when_closing: bool = False,
    ) -> asyncio.Task[_T]:
        def invoke() -> _T:
            if self._closed_event.is_set() and not allow_when_closing:
                raise OSError("Windows process transport is closing")
            thread_id = threading.get_native_id()
            with self._thread_lock:
                self._io_threads[operation_name] = thread_id
            try:
                if self._closed_event.is_set() and not allow_when_closing:
                    raise OSError("Windows process transport is closing")
                return function(*arguments)
            finally:
                with self._thread_lock:
                    if self._io_threads.get(operation_name) == thread_id:
                        self._io_threads.pop(operation_name, None)

        async def run() -> _T:
            return await asyncio.get_running_loop().run_in_executor(
                self._executor, invoke
            )

        task = asyncio.create_task(run(), name="hosting-windows-blocking-operation")
        tracked = cast(asyncio.Task[object], task)
        self._operations.add(tracked)

        def settle(completed: asyncio.Task[object]) -> None:
            self._operations.discard(completed)
            if not completed.cancelled():
                completed.exception()

        tracked.add_done_callback(settle)
        return task

    def _cancel_active_io(self, names: tuple[str, ...] | None = None) -> None:
        cancel = getattr(self._api, "cancel_synchronous_io", None)
        if not callable(cancel):
            return
        with self._thread_lock:
            thread_ids = tuple(
                thread_id
                for name, thread_id in self._io_threads.items()
                if names is None or name in names
            )
        for thread_id in thread_ids:
            try:
                cancel(thread_id)
            except OSError:
                continue


class _WindowsProcessBackend:
    backend_id = "windows-job-v1"

    def __init__(
        self,
        *,
        max_processes: int = 4,
        api: _Win32Api | None = None,
    ) -> None:
        if type(max_processes) is not int or max_processes < 1:
            raise ValueError("max_processes must be a positive integer")
        if api is None and os.name != "nt":
            raise HostingError(
                HostingFailureCategory.PLATFORM_UNSUPPORTED,
                "Windows Job Objects are unavailable",
            )
        self._api = api or _CtypesWin32Api()
        # One root wait plus one operation for each byte stream can block per
        # process. The extra worker keeps spawn available below the capacity
        # fence; control operations never enter this executor.
        self._executor = ThreadPoolExecutor(
            max_workers=max_processes * 4 + 1,
            thread_name_prefix="loushang-hosting-win32",
        )
        self._closed = False
        self._orphan_processes: list[_WindowsProcess] = []

    async def spawn(
        self,
        request: ProcessLaunchRequest,
        *,
        on_spawn: Callable[[_ProcessTransport], None],
        inheritance: _ProcessInheritance | None = None,
    ) -> _WindowsProcess:
        if inheritance is not None and (
            request.streams.stdin is not ProcessStdinMode.CLOSED
            or request.streams.stdout is not ProcessStdoutMode.DISCARD
        ):
            raise HostingError(
                HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                "inherited endpoints reserve child stdin and stdout",
            )
        endpoint_handles = _claim_endpoint(inheritance, self.backend_id)
        spawn_task = asyncio.create_task(
            self._spawn_once(request, endpoint_handles),
            name="hosting-windows-process-spawn",
        )
        cancellation: asyncio.CancelledError | None = None
        while True:
            try:
                handles = await asyncio.shield(spawn_task)
                break
            except asyncio.CancelledError as exc:
                if spawn_task.cancelled():
                    raise
                if cancellation is None:
                    cancellation = exc
            except BaseException as exc:
                if cancellation is not None:
                    raise cancellation from exc
                raise

        process = _WindowsProcess(self._api, self._executor, handles)
        try:
            if inheritance is not None:
                inheritance.mark_transferred()
            on_spawn(process)
        except BaseException as primary:
            try:
                await self._reclaim_failed_attachment(process)
            except BaseException as cleanup:
                self._orphan_processes.append(process)
                primary.add_note(f"Windows spawn attachment cleanup also failed: {cleanup}")
                raise primary from cleanup
            raise
        if cancellation is not None:
            raise cancellation
        return process

    async def _spawn_once(
        self,
        request: ProcessLaunchRequest,
        endpoint_handles: tuple[int, int] | None,
    ) -> _Win32SpawnHandles:
        if endpoint_handles is None:
            return await asyncio.get_running_loop().run_in_executor(
                self._executor, self._api.spawn, request
            )
        return await asyncio.get_running_loop().run_in_executor(
            self._executor, self._api.spawn, request, endpoint_handles
        )

    async def _spawn_static_prepared(
        self,
        material: object,
        request: ProcessLaunchRequest,
        *,
        effect: _ManagedSpawnEffect,
        on_spawn: Callable[[_ProcessTransport], None],
        inheritance: _ProcessInheritance | None,
    ) -> _WindowsProcess:
        from ._windows_launch_preparation import _WindowsRestrictedLaunchMaterial

        try:
            if type(material) is not _WindowsRestrictedLaunchMaterial:
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "Windows process backend requires restricted launch material",
                )
            if request != material.request:
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "Windows restricted launch request changed before spawn",
                )
            if inheritance is None:
                raise HostingError(
                    HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                    "Windows restricted launch requires endpoint inheritance",
                )
            if (
                request.streams.stdin is not ProcessStdinMode.CLOSED
                or request.streams.stdout is not ProcessStdoutMode.DISCARD
            ):
                raise HostingError(
                    HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                    "Windows inherited endpoint reserves stdin and stdout",
                )
            endpoint_handles = _claim_endpoint(inheritance, self.backend_id)
            assert endpoint_handles is not None
            (
                executable_handle,
                cwd_handle,
                token_handle,
                job_handle,
                stderr_handle,
            ) = material._claim_handles()
            preparation_handles = (
                executable_handle,
                cwd_handle,
                token_handle,
                job_handle,
                stderr_handle,
            )
            if (
                len(set(preparation_handles)) != len(preparation_handles)
                or set(endpoint_handles) & set(preparation_handles)
                or any(handle <= 0 for handle in (*endpoint_handles, *preparation_handles))
            ):
                raise HostingError(
                    HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                    "Windows endpoint and preparation handles collide",
                )
        except BaseException as cause:
            raise effect.not_created(cause) from cause

        spawn_task = asyncio.create_task(
            self._spawn_restricted_once(
                request,
                endpoint_handles,
                executable_handle=executable_handle,
                cwd_handle=cwd_handle,
                token=token_handle,
                job=job_handle,
                stderr_handle=stderr_handle,
                begin_effect=effect.begin_effect,
            ),
            name="hosting-windows-restricted-process-spawn",
        )
        cancellation: asyncio.CancelledError | None = None
        while True:
            try:
                handles = await asyncio.shield(spawn_task)
                break
            except asyncio.CancelledError as exc:
                if spawn_task.cancelled():
                    raise
                if cancellation is None:
                    cancellation = exc
            except _Win32CreateNotStarted as failure:
                raise effect.not_created(failure.cause) from failure
            except _Win32CreateSettledWithoutProcess as failure:
                raise effect.settled_without_process(failure.cause) from failure
            except BaseException as exc:
                if cancellation is not None:
                    raise cancellation from exc
                raise

        process = _WindowsProcess(self._api, self._executor, handles)
        material._mark_transferred()
        attached = False
        try:
            # The process owns Job/stderr before publication.  Publish the
            # provisional owner before the endpoint transfer can fail so the
            # outer reservation remains the retryable cleanup authority.
            on_spawn(process)
            attached = True
            inheritance.mark_transferred()
        except BaseException as primary:
            if not attached and not effect.observes(process):
                try:
                    await self._reclaim_failed_attachment(process)
                except BaseException as cleanup:
                    self._orphan_processes.append(process)
                    primary.add_note(
                        f"Windows prepared attachment cleanup also failed: {cleanup}"
                    )
                    raise primary from cleanup
            raise
        if cancellation is not None:
            raise cancellation
        return process

    async def _spawn_restricted_once(
        self,
        request: ProcessLaunchRequest,
        endpoint_handles: tuple[int, int],
        *,
        executable_handle: int,
        cwd_handle: int,
        token: int,
        job: int,
        stderr_handle: int,
        begin_effect: Callable[[], None],
    ) -> _Win32SpawnHandles:
        operation = partial(
            self._api.spawn_restricted,
            request,
            endpoint_handles,
            executable_handle=executable_handle,
            cwd_handle=cwd_handle,
            token=token,
            job=job,
            stderr_handle=stderr_handle,
            begin_effect=begin_effect,
        )
        return await asyncio.get_running_loop().run_in_executor(
            self._executor,
            operation,
        )

    def tree_exited(self, process: _ProcessTransport) -> bool:
        return _require_windows_process(process).job_is_empty()

    async def wait_tree(self, process: _ProcessTransport) -> None:
        await _require_windows_process(process).wait_job()

    async def terminate_tree(self, process: _ProcessTransport) -> None:
        _require_windows_process(process).terminate_job(
            _INITIAL_TERMINATION_EXIT_CODE
        )

    async def kill_tree(self, process: _ProcessTransport) -> None:
        _require_windows_process(process).terminate_job(
            _FORCEFUL_TERMINATION_EXIT_CODE
        )

    async def close_process_handles(self, process: _ProcessTransport) -> None:
        owned = _require_windows_process(process)
        failure: BaseException | None = None
        try:
            if not owned.job_is_empty():
                owned.terminate_job(_FORCEFUL_TERMINATION_EXIT_CODE)
        except BaseException as exc:
            failure = exc
        try:
            await owned.close_handles()
        except BaseException as exc:
            if failure is not None:
                raise BaseExceptionGroup(
                    "Windows process final safety cleanup failed", [failure, exc]
                )
            raise
        if failure is not None:
            raise failure

    async def close_backend(self) -> None:
        if self._closed:
            return
        self._closed = True
        failures: list[BaseException] = []
        for process in tuple(self._orphan_processes):
            try:
                await self._reclaim_failed_attachment(process)
            except BaseException as exc:
                failures.append(exc)
            else:
                self._orphan_processes.remove(process)
        if failures:
            self._closed = False
            raise BaseExceptionGroup(
                "Windows backend orphan cleanup failed",
                failures,
            )
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _abort_construction(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)

    async def _reclaim_failed_attachment(self, process: _WindowsProcess) -> None:
        failure: BaseException | None = None
        try:
            process.terminate_job(_FORCEFUL_TERMINATION_EXIT_CODE)
            await process.wait_job()
            await process.wait()
        except BaseException as exc:
            failure = exc
        try:
            await process.close_handles()
        except BaseException as exc:
            if failure is not None:
                raise BaseExceptionGroup(
                    "Windows spawn attachment cleanup failed", [failure, exc]
                )
            raise
        if failure is not None:
            raise failure


def _require_windows_process(process: _ProcessTransport) -> _WindowsProcess:
    if not isinstance(process, _WindowsProcess):
        raise TypeError("Windows backend requires its own process transport")
    return process


def _claim_endpoint(
    inheritance: _ProcessInheritance | None,
    backend_id: str,
) -> tuple[int, int] | None:
    if inheritance is None:
        return None
    values = inheritance.claim(backend_id=backend_id)
    if len(values) != 2 or any(type(value) is not int or value <= 0 for value in values):
        raise HostingError(
            HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
            "Windows endpoint inheritance must contain stdin and stdout handles",
        )
    return values[0], values[1]


__all__: list[str] = []
