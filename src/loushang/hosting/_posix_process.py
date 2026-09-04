"""Private POSIX process-group backend for Hosting."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
from collections.abc import Callable

from ._process_backend import _ProcessInheritance, _ProcessTransport
from .contracts import (
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
)
from .errors import HostingError, HostingFailureCategory

_TREE_POLL_SECONDS = 0.01
_FAILED_ATTACHMENT_SETTLEMENT_SECONDS = 1.0


class _PosixProcess:
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        process_group_id = process.pid
        if type(process_group_id) is not int or process_group_id <= 0:
            raise RuntimeError("POSIX process has no valid process-group identity")
        self._process = process
        self._process_group_id = process_group_id
        self._stdin_closed = False
        self._handles_closed = False
        self._close_lock = asyncio.Lock()

    @property
    def return_code(self) -> int | None:
        return self._process.returncode

    async def read_stdout(self, max_bytes: int) -> bytes:
        reader = self._process.stdout
        if reader is None:
            return b""
        return await reader.read(max_bytes)

    async def read_stderr(self, max_bytes: int) -> bytes:
        reader = self._process.stderr
        if reader is None:
            return b""
        return await reader.read(max_bytes)

    async def write_stdin(self, data: bytes) -> None:
        writer = self._process.stdin
        if writer is None or self._stdin_closed:
            raise BrokenPipeError("POSIX process stdin is closed")
        writer.write(data)
        await writer.drain()

    async def close_stdin(self) -> None:
        if self._stdin_closed:
            return
        self._stdin_closed = True
        writer = self._process.stdin
        if writer is None:
            return
        writer.close()

    async def wait(self) -> int:
        # ``asyncio.subprocess.Process.wait()`` may remain pending after the
        # root has exited while a descendant still owns one of the pipe write
        # ends.  Hosting must observe the root exit independently so it can
        # start reclaiming that descendant tree instead of waiting for pipe
        # EOF.  The child watcher updates ``returncode`` when the root is
        # reaped, independently of pipe transport settlement.
        while self._process.returncode is None:
            await asyncio.sleep(_TREE_POLL_SECONDS)
        return self._process.returncode

    def group_exists(self) -> bool:
        try:
            os.killpg(self._process_group_id, 0)
        except ProcessLookupError:
            return False
        return True

    def signal_group(self, group_signal: signal.Signals) -> None:
        try:
            os.killpg(self._process_group_id, group_signal)
        except ProcessLookupError:
            return

    async def wait_group(self) -> None:
        while self.group_exists():
            await asyncio.sleep(_TREE_POLL_SECONDS)

    async def close_handles(self) -> None:
        async with self._close_lock:
            if self._handles_closed:
                return
            self._handles_closed = True
            await self.close_stdin()
            for reader in (self._process.stdout, self._process.stderr):
                _close_reader_transport(reader)
            transport = getattr(self._process, "_transport", None)
            close = getattr(transport, "close", None)
            if callable(close):
                close()


class _PosixProcessBackend:
    backend_id = "posix-process-group-v1"

    def __init__(self) -> None:
        if (
            os.name != "posix"
            or not callable(getattr(os, "setsid", None))
            or not callable(getattr(os, "killpg", None))
            or not callable(getattr(asyncio, "create_subprocess_exec", None))
        ):
            raise HostingError(
                HostingFailureCategory.PLATFORM_UNSUPPORTED,
                "POSIX process groups are unavailable",
            )

    async def spawn(
        self,
        request: ProcessLaunchRequest,
        *,
        on_spawn: Callable[[_ProcessTransport], None],
        inheritance: _ProcessInheritance | None = None,
    ) -> _PosixProcess:
        if inheritance is not None and (
            request.streams.stdin is not ProcessStdinMode.CLOSED
            or request.streams.stdout is not ProcessStdoutMode.DISCARD
        ):
            raise HostingError(
                HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                "inherited endpoints reserve child stdin and stdout",
            )
        endpoint_descriptors = _claim_endpoint(inheritance, self.backend_id)
        operation = (
            self._spawn_once(request)
            if endpoint_descriptors is None
            else self._spawn_once(request, endpoint_descriptors)
        )
        spawn_task = asyncio.create_task(
            operation,
            name="hosting-posix-process-spawn",
        )
        cancellation: asyncio.CancelledError | None = None
        while True:
            try:
                process = await asyncio.shield(spawn_task)
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

        try:
            if inheritance is not None:
                inheritance.mark_transferred()
            on_spawn(process)
        except BaseException as primary:
            try:
                await self._reclaim_failed_attachment(process)
            except BaseException as cleanup:
                primary.add_note(f"POSIX spawn attachment cleanup also failed: {cleanup}")
                raise primary from cleanup
            raise
        if cancellation is not None:
            raise cancellation
        return process

    async def _spawn_once(
        self,
        request: ProcessLaunchRequest,
        endpoint_descriptors: tuple[int, int] | None = None,
    ) -> _PosixProcess:
        if endpoint_descriptors is None:
            stdin: int = (
                asyncio.subprocess.PIPE
                if request.streams.stdin is ProcessStdinMode.PIPE
                else subprocess.DEVNULL
            )
            stdout: int = (
                asyncio.subprocess.PIPE
                if request.streams.stdout is ProcessStdoutMode.PIPE
                else subprocess.DEVNULL
            )
        else:
            stdin, stdout = endpoint_descriptors
        process = await asyncio.create_subprocess_exec(
            *request.argv,
            cwd=request.cwd,
            env=dict(request.effective_environment),
            start_new_session=True,
            close_fds=True,
            stdin=stdin,
            stdout=stdout,
            stderr=(
                asyncio.subprocess.PIPE
                if request.streams.stderr
                in {ProcessStderrMode.PIPE, ProcessStderrMode.CAPTURE_TAIL}
                else subprocess.DEVNULL
            ),
        )
        try:
            return _PosixProcess(process)
        except BaseException:
            process.kill()
            await process.wait()
            raise

    def tree_exited(self, process: _ProcessTransport) -> bool:
        return not _require_posix_process(process).group_exists()

    async def wait_tree(self, process: _ProcessTransport) -> None:
        await _require_posix_process(process).wait_group()

    async def terminate_tree(self, process: _ProcessTransport) -> None:
        _require_posix_process(process).signal_group(signal.SIGTERM)

    async def kill_tree(self, process: _ProcessTransport) -> None:
        _require_posix_process(process).signal_group(signal.SIGKILL)

    async def close_process_handles(self, process: _ProcessTransport) -> None:
        owned = _require_posix_process(process)
        failures: list[BaseException] = []
        try:
            if owned.group_exists():
                owned.signal_group(signal.SIGKILL)
        except BaseException as exc:
            failures.append(exc)
        try:
            await owned.close_handles()
        except BaseException as exc:
            failures.append(exc)
        if failures:
            raise BaseExceptionGroup("POSIX process final cleanup failed", failures)

    async def close_backend(self) -> None:
        return

    async def _reclaim_failed_attachment(self, process: _PosixProcess) -> None:
        failures: list[BaseException] = []
        try:
            process.signal_group(signal.SIGKILL)
        except BaseException as exc:
            failures.append(exc)
        try:
            await process.wait()
        except BaseException as exc:
            failures.append(exc)
        try:
            await asyncio.wait_for(
                process.wait_group(), _FAILED_ATTACHMENT_SETTLEMENT_SECONDS
            )
        except BaseException as exc:
            failures.append(exc)
        try:
            await process.close_handles()
        except BaseException as exc:
            failures.append(exc)
        if failures:
            raise BaseExceptionGroup(
                "POSIX spawn attachment cleanup failed", failures
            )


def _require_posix_process(process: _ProcessTransport) -> _PosixProcess:
    if not isinstance(process, _PosixProcess):
        raise TypeError("POSIX backend requires its own process transport")
    return process


def _claim_endpoint(
    inheritance: _ProcessInheritance | None,
    backend_id: str,
) -> tuple[int, int] | None:
    if inheritance is None:
        return None
    values = inheritance.claim(backend_id=backend_id)
    if len(values) != 2 or any(type(value) is not int or value < 0 for value in values):
        raise HostingError(
            HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
            "POSIX endpoint inheritance must contain stdin and stdout descriptors",
        )
    return values[0], values[1]


def _close_reader_transport(reader: object | None) -> None:
    if reader is None:
        return
    transport = getattr(reader, "_transport", None)
    close = getattr(transport, "close", None)
    if callable(close):
        close()


__all__: list[str] = []
