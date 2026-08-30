from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from loushang.agent import AbortController
from loushang.harness.workspace.exec import (
    AuthorizedProcessExecBackend,
    ExecOutputChunk,
    ExecRequest,
    ExecService,
)
from loushang.harness.workspace.process import (
    ProcessExit,
    ProcessLaunchRequest,
    ProcessStderrTail,
)


@dataclass(slots=True)
class _ProcessHandle:
    stdout: list[bytes] = field(default_factory=lambda: [b"captured\n", b""])
    stderr: list[bytes] = field(default_factory=lambda: [b"warning\n", b""])
    stdin: list[bytes] = field(default_factory=list)
    stdin_closed: bool = False
    closed: bool = False
    wait_forever: bool = False
    wait_cancelled: bool = False
    stdout_wait_forever: bool = False
    stdout_wait_cancelled: bool = False
    terminated: bool = False
    wait_started: asyncio.Event | None = None
    close_started: asyncio.Event | None = None
    allow_close: asyncio.Event | None = None
    close_cancelled: bool = False

    async def read_stdout(self, max_bytes: int = 64 * 1024) -> bytes:
        del max_bytes
        if not self.stdout and self.stdout_wait_forever:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.stdout_wait_cancelled = True
                raise
        return self.stdout.pop(0)

    async def read_stderr(self, max_bytes: int = 64 * 1024) -> bytes:
        del max_bytes
        return self.stderr.pop(0)

    async def write_stdin(self, data: bytes) -> None:
        self.stdin.append(data)

    async def close_stdin(self) -> None:
        self.stdin_closed = True

    async def wait(self) -> ProcessExit:
        if self.wait_started is not None:
            self.wait_started.set()
        if self.wait_forever:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.wait_cancelled = True
                raise
        return ProcessExit(return_code=7)

    async def terminate(self) -> ProcessExit:
        self.terminated = True
        return ProcessExit(return_code=-1)

    async def close(self) -> None:
        if self.close_started is not None:
            self.close_started.set()
        if self.allow_close is not None:
            try:
                await self.allow_close.wait()
            except asyncio.CancelledError:
                self.close_cancelled = True
                raise
        self.closed = True

    def stderr_tail(self) -> ProcessStderrTail:
        return ProcessStderrTail(content=b"warning\n")


@dataclass(slots=True)
class _CapturedLauncher:
    handle: _ProcessHandle
    requests: list[ProcessLaunchRequest] = field(default_factory=list)
    correlation_ids: list[str] = field(default_factory=list)

    async def start(
        self,
        request: ProcessLaunchRequest,
        *,
        correlation_id: str,
        signal: object | None = None,
    ) -> _ProcessHandle:
        del signal
        self.requests.append(request)
        self.correlation_ids.append(correlation_id)
        return self.handle


def test_base_process_operations_execute_only_through_captured_launcher() -> None:
    asyncio.run(_base_process_operations_execute_only_through_captured_launcher())


async def _base_process_operations_execute_only_through_captured_launcher() -> None:
    handle = _ProcessHandle()
    launcher = _CapturedLauncher(handle)
    operations = ExecService(
        backend=AuthorizedProcessExecBackend(launcher)  # type: ignore[arg-type]
    )
    updates: list[ExecOutputChunk] = []
    request = ExecRequest(
        command=("/bin/example", "arg"),
        cwd="/workspace",
        stdin="input",
        effective_environment=(("PATH", "/captured/bin"),),
    )

    result = await operations.execute(request, on_update=updates.append)

    assert launcher.requests == [
        ProcessLaunchRequest(
            command=("/bin/example", "arg"),
            cwd="/workspace",
            effective_environment=(("PATH", "/captured/bin"),),
            stream_stderr=True,
        )
    ]
    assert launcher.correlation_ids[0].startswith("workspace-exec:")
    assert handle.stdin == [b"input"]
    assert handle.stdin_closed is True
    assert handle.closed is True
    assert result.exit_code == 7
    assert result.stdout == "captured\n"
    assert result.stderr == "warning\n"
    assert updates == [
        ExecOutputChunk(stream="stdout", text="captured\n"),
        ExecOutputChunk(stream="stderr", text="warning\n"),
    ]


def test_base_process_operations_terminate_and_join_wait_task_on_timeout() -> None:
    asyncio.run(_base_process_operations_terminate_and_join_wait_task_on_timeout())


async def _base_process_operations_terminate_and_join_wait_task_on_timeout() -> None:
    handle = _ProcessHandle(wait_forever=True)
    operations = ExecService(
        backend=AuthorizedProcessExecBackend(  # type: ignore[arg-type]
            _CapturedLauncher(handle)
        )
    )

    result = await operations.execute(
        ExecRequest(
            command=("/bin/example",),
            cwd="/workspace",
            effective_environment=(),
            timeout_seconds=0.001,
        )
    )

    assert result.exit_code == -1
    assert result.timed_out is True
    assert handle.terminated is True
    assert handle.wait_cancelled is True
    assert handle.closed is True


def test_base_process_operations_terminate_after_post_start_cancellation() -> None:
    asyncio.run(_base_process_operations_terminate_after_post_start_cancellation())


async def _base_process_operations_terminate_after_post_start_cancellation() -> None:
    handle = _ProcessHandle(wait_forever=True)
    operations = ExecService(
        backend=AuthorizedProcessExecBackend(  # type: ignore[arg-type]
            _CapturedLauncher(handle)
        )
    )
    controller = AbortController()
    execution = asyncio.create_task(
        operations.execute(
            ExecRequest(
                command=("/bin/example",),
                cwd="/workspace",
                effective_environment=(),
            ),
            signal=controller.signal,
        )
    )
    await asyncio.sleep(0)
    controller.abort()

    result = await execution

    assert result.exit_code == -1
    assert result.cancelled is True
    assert result.timed_out is False
    assert handle.terminated is True
    assert handle.wait_cancelled is True
    assert handle.closed is True


def test_base_process_operations_finish_cleanup_before_repeated_cancellation() -> None:
    asyncio.run(
        _base_process_operations_finish_cleanup_before_repeated_cancellation()
    )


async def _base_process_operations_finish_cleanup_before_repeated_cancellation(
) -> None:
    wait_started = asyncio.Event()
    close_started = asyncio.Event()
    allow_close = asyncio.Event()
    handle = _ProcessHandle(
        wait_forever=True,
        wait_started=wait_started,
        close_started=close_started,
        allow_close=allow_close,
    )
    operations = ExecService(
        backend=AuthorizedProcessExecBackend(  # type: ignore[arg-type]
            _CapturedLauncher(handle)
        )
    )
    execution = asyncio.create_task(
        operations.execute(
            ExecRequest(
                command=("/bin/example",),
                cwd="/workspace",
                effective_environment=(),
            )
        )
    )
    await wait_started.wait()

    execution.cancel()
    await close_started.wait()
    execution.cancel()
    await asyncio.sleep(0)

    assert execution.done() is False
    assert handle.close_cancelled is False
    allow_close.set()
    with pytest.raises(asyncio.CancelledError):
        await execution

    assert handle.terminated is True
    assert handle.wait_cancelled is True
    assert handle.closed is True
    assert handle.close_cancelled is False


def test_base_process_operations_roll_output_and_retain_full_artifact(
    tmp_path: Path,
) -> None:
    asyncio.run(
        _base_process_operations_roll_output_and_retain_full_artifact(tmp_path)
    )


async def _base_process_operations_roll_output_and_retain_full_artifact(
    tmp_path: Path,
) -> None:
    handle = _ProcessHandle(
        stdout=[b"alpha\n", b"beta\n", b"gamma\n", b""],
    )
    operations = ExecService(
        backend=AuthorizedProcessExecBackend(  # type: ignore[arg-type]
            _CapturedLauncher(handle)
        )
    )

    result = await operations.execute(
        ExecRequest(
            command=("/bin/example",),
            cwd="/workspace",
            effective_environment=(),
            capture_full_output=False,
            rolling_max_bytes=7,
            artifact_dir=str(tmp_path),
        )
    )

    assert result.stdout == "gamma\n"
    assert result.stdout_chunks == ("gamma\n",)
    assert result.stdout_total_lines == 3
    assert result.stdout_total_bytes == 17
    assert result.stdout_truncated is True
    assert result.stdout_truncated_by == "bytes"
    assert result.stdout_artifact_path is not None
    assert Path(result.stdout_artifact_path).read_text(encoding="utf-8") == (
        "alpha\nbeta\ngamma\n"
    )


def test_base_process_operations_do_not_retain_unrequested_output_artifact(
    tmp_path: Path,
) -> None:
    asyncio.run(
        _base_process_operations_do_not_retain_unrequested_output_artifact(tmp_path)
    )


async def _base_process_operations_do_not_retain_unrequested_output_artifact(
    tmp_path: Path,
) -> None:
    handle = _ProcessHandle(stdout=[b"alpha\n", b"beta\n", b""])
    operations = ExecService(
        backend=AuthorizedProcessExecBackend(  # type: ignore[arg-type]
            _CapturedLauncher(handle)
        )
    )

    result = await operations.execute(
        ExecRequest(
            command=("/bin/example",),
            cwd="/workspace",
            effective_environment=(),
            capture_full_output=False,
            rolling_max_bytes=6,
            artifact_dir=str(tmp_path),
            retain_output_artifacts=False,
        )
    )

    assert result.stdout == "beta\n"
    assert result.stdout_artifact_path is None
    assert tuple(tmp_path.iterdir()) == ()


def test_authorized_process_operations_stream_and_retain_full_stderr_artifact(
    tmp_path: Path,
) -> None:
    asyncio.run(
        _authorized_process_operations_stream_and_retain_full_stderr_artifact(
            tmp_path
        )
    )


async def _authorized_process_operations_stream_and_retain_full_stderr_artifact(
    tmp_path: Path,
) -> None:
    handle = _ProcessHandle(
        stdout=[b""],
        stderr=[b"alpha\n", b"beta\n", b"gamma\n", b""],
    )
    operations = ExecService(
        backend=AuthorizedProcessExecBackend(  # type: ignore[arg-type]
            _CapturedLauncher(handle)
        )
    )
    updates: list[ExecOutputChunk] = []

    result = await operations.execute(
        ExecRequest(
            command=("/bin/example",),
            cwd="/workspace",
            effective_environment=(),
            capture_full_output=False,
            rolling_max_bytes=7,
            artifact_dir=str(tmp_path),
        ),
        on_update=updates.append,
    )

    assert result.stderr == "gamma\n"
    assert result.stderr_chunks == ("gamma\n",)
    assert result.stderr_total_lines == 3
    assert result.stderr_total_bytes == 17
    assert result.stderr_truncated is True
    assert result.stderr_truncated_by == "bytes"
    assert result.stderr_artifact_path is not None
    assert Path(result.stderr_artifact_path).read_text(encoding="utf-8") == (
        "alpha\nbeta\ngamma\n"
    )
    assert updates == [
        ExecOutputChunk(stream="stderr", text="alpha\n"),
        ExecOutputChunk(stream="stderr", text="beta\n"),
        ExecOutputChunk(stream="stderr", text="gamma\n"),
    ]


def test_base_process_operations_bound_post_exit_stdout_drain() -> None:
    asyncio.run(_base_process_operations_bound_post_exit_stdout_drain())


async def _base_process_operations_bound_post_exit_stdout_drain() -> None:
    handle = _ProcessHandle(
        stdout=[b"partial\n"],
        stdout_wait_forever=True,
    )
    operations = ExecService(
        backend=AuthorizedProcessExecBackend(  # type: ignore[arg-type]
            _CapturedLauncher(handle),
            post_exit_stdout_timeout_seconds=0.001,
        )
    )

    result = await operations.execute(
        ExecRequest(
            command=("/bin/example",),
            cwd="/workspace",
            effective_environment=(),
        )
    )

    assert result.stdout == "partial\n"
    assert result.stdio_complete is False
    assert result.stdio_drain_reason == "hard_timeout"
    assert handle.stdout_wait_cancelled is True
    assert handle.closed is True
