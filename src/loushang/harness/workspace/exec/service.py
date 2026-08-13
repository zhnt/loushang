from __future__ import annotations

import asyncio
import codecs
import inspect
import os
import tempfile
from collections.abc import Awaitable
from contextlib import suppress
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, Protocol, TextIO

from loushang.harness.workspace._local_process import (
    kill_local_process_tree,
    spawn_local_process,
)
from loushang.harness.workspace.truncation import truncate_tail

from .errors import ExecLaunchError, ExecLaunchErrorKind
from .types import (
    ExecOutputChunk,
    ExecRequest,
    ExecResult,
    ExecUpdateCallback,
    StdioDrainReason,
    materialize_exec_request,
)


class ExecBackend(Protocol):
    """Execute a materialized request without rereading cwd or environment."""

    def __call__(
        self,
        request: ExecRequest,
        *,
        signal: object | None = None,
        on_update: ExecUpdateCallback | None = None,
    ) -> Awaitable[ExecResult] | ExecResult: ...


class ExecService:
    def __init__(
        self,
        *,
        backend: ExecBackend | None = None,
        execution_profile: object | None = None,
    ) -> None:
        self._backend = backend if backend is not None else LocalExecBackend()
        self.execution_profile = execution_profile

    async def execute(
        self,
        request: ExecRequest,
        *,
        signal: object | None = None,
        on_update: ExecUpdateCallback | None = None,
    ) -> ExecResult:
        request = materialize_exec_request(request)
        result = self._backend(request, signal=signal, on_update=on_update)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, ExecResult):
            raise TypeError("exec backend must return ExecResult")
        return result


class LocalExecBackend:
    """Run one already-materialized request as a local child process."""

    def __init__(
        self,
        *,
        read_chunk_bytes: int = 64 * 1024,
        post_exit_stdio_grace_seconds: float = 0.5,
        post_exit_stdio_hard_timeout_seconds: float = 2.0,
    ) -> None:
        if read_chunk_bytes < 1:
            raise ValueError("read_chunk_bytes must be >= 1")
        if post_exit_stdio_grace_seconds <= 0:
            raise ValueError("post_exit_stdio_grace_seconds must be > 0")
        if post_exit_stdio_hard_timeout_seconds <= 0:
            raise ValueError("post_exit_stdio_hard_timeout_seconds must be > 0")
        if post_exit_stdio_hard_timeout_seconds < post_exit_stdio_grace_seconds:
            raise ValueError(
                "post_exit_stdio_hard_timeout_seconds must be >= "
                "post_exit_stdio_grace_seconds"
            )
        self._read_chunk_bytes = read_chunk_bytes
        self._normal_output_drain_policy = _OutputDrainPolicy(
            idle_timeout_seconds=post_exit_stdio_grace_seconds,
            hard_timeout_seconds=post_exit_stdio_hard_timeout_seconds,
        )

    async def __call__(
        self,
        request: ExecRequest,
        *,
        signal: object | None = None,
        on_update: ExecUpdateCallback | None = None,
    ) -> ExecResult:
        assert request.effective_environment is not None
        assert request.cwd is not None
        env = dict(request.effective_environment)

        _validate_local_launch(request.command, request.cwd)
        try:
            process = await spawn_local_process(
                command=request.command,
                cwd=request.cwd,
                environment=env,
                pipe_stdin=request.stdin is not None,
            )
        except FileNotFoundError as exc:
            raise _file_not_found_error(
                command=request.command,
                cwd=request.cwd,
                cause=exc,
            ) from exc
        except OSError as exc:
            raise ExecLaunchError(
                "spawn_failed",
                command=request.command,
                cwd=request.cwd,
                cause=exc,
            ) from exc

        stdout_capture = _StreamCapture(
            stream_name="stdout",
            capture_full_output=request.capture_full_output,
            retain_output_artifact=request.retain_output_artifacts,
            rolling_max_bytes=request.rolling_max_bytes,
            artifact_dir=request.artifact_dir,
        )
        stderr_capture = _StreamCapture(
            stream_name="stderr",
            capture_full_output=request.capture_full_output,
            retain_output_artifact=request.retain_output_artifacts,
            rolling_max_bytes=request.rolling_max_bytes,
            artifact_dir=request.artifact_dir,
        )
        output_capture = _OutputCapture(
            capture_full_output=request.capture_full_output,
            rolling_max_bytes=request.rolling_max_bytes,
        )
        activity = _OutputActivity(asyncio.get_running_loop().time())

        async def _publish(
            stream_name: Literal["stdout", "stderr"],
            sink: _StreamCapture,
            text: str,
        ) -> None:
            if not text:
                return
            activity.mark()
            sink.append(text)
            output_chunk = ExecOutputChunk(stream=stream_name, text=text)
            output_capture.append(output_chunk)
            if on_update is not None:
                update = on_update(output_chunk)
                if inspect.isawaitable(update):
                    await update

        async def _read_stream(
            stream_name: Literal["stdout", "stderr"],
            stream,
            sink: _StreamCapture,
        ) -> None:
            decoder = _IncrementalTextChunks(max_chunk_chars=self._read_chunk_bytes)
            try:
                while True:
                    chunk = await stream.read(self._read_chunk_bytes)
                    if not chunk:
                        break
                    activity.mark()
                    for text in decoder.feed(chunk):
                        await _publish(stream_name, sink, text)
            finally:
                for text in decoder.finish():
                    await _publish(stream_name, sink, text)

        stdout_task = asyncio.create_task(
            _read_stream("stdout", process.stdout, stdout_capture)
        )
        stderr_task = asyncio.create_task(
            _read_stream("stderr", process.stderr, stderr_capture)
        )
        root_exit_task = asyncio.create_task(_wait_for_root_process_exit(process))
        settlement_task = asyncio.create_task(process.wait())

        abort_task = (
            asyncio.create_task(_wait_for_abort(signal)) if signal is not None else None
        )
        timed_out = False
        cancelled = False
        force_terminated = False
        drain_outcome = _OutputDrainOutcome.complete()

        try:
            await _write_process_stdin(process, request.stdin)
            if request.timeout_seconds is None and abort_task is None:
                await asyncio.shield(root_exit_task)
            else:
                waiters: set[asyncio.Task[int] | asyncio.Task[None]] = {root_exit_task}
                if abort_task is not None:
                    waiters.add(abort_task)
                done, pending = await asyncio.wait(
                    waiters,
                    timeout=request.timeout_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if root_exit_task in done:
                    pass
                elif abort_task is not None and abort_task in done:
                    cancelled = True
                    force_terminated = True
                    await _kill_process(process)
                    await asyncio.shield(root_exit_task)
                else:
                    timed_out = True
                    force_terminated = True
                    await _kill_process(process)
                    await asyncio.shield(root_exit_task)
                for task in pending:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        except asyncio.CancelledError:
            force_terminated = True
            await _kill_process(process)
            if not root_exit_task.done():
                await asyncio.shield(root_exit_task)
            raise
        finally:
            if abort_task is not None and not abort_task.done():
                abort_task.cancel()
                await asyncio.gather(abort_task, return_exceptions=True)
            if not root_exit_task.done():
                force_terminated = True
                await _kill_process(process)
                await asyncio.shield(root_exit_task)
            activity.mark()
            try:
                drain_outcome = await _drain_output_tasks(
                    process,
                    (stdout_task, stderr_task),
                    activity=activity,
                    policy=(
                        _FORCED_OUTPUT_DRAIN_POLICY
                        if force_terminated
                        else self._normal_output_drain_policy
                    ),
                )
            finally:
                _close_reader_transport(process.stdout)
                _close_reader_transport(process.stderr)
                try:
                    await settlement_task
                finally:
                    stdout_capture.close()
                    stderr_capture.close()

        stdout = stdout_capture.content
        stderr = stderr_capture.content
        stdout_preview, stdout_artifact_path = _build_preview_from_capture(
            stdout_capture,
            max_lines=request.preview_max_lines,
            max_bytes=request.preview_max_bytes,
        )
        stderr_preview, stderr_artifact_path = _build_preview_from_capture(
            stderr_capture,
            max_lines=request.preview_max_lines,
            max_bytes=request.preview_max_bytes,
        )
        return ExecResult(
            exit_code=process.returncode
            if process.returncode is not None
            else (-1 if timed_out or cancelled else 0),
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            cancelled=cancelled,
            stdout_chunks=tuple(stdout_capture.chunks),
            stderr_chunks=tuple(stderr_capture.chunks),
            output_chunks=tuple(output_capture.chunks),
            stdout_preview=stdout_preview.content,
            stderr_preview=stderr_preview.content,
            stdout_truncated=stdout_preview.truncated,
            stdout_truncated_by=stdout_preview.truncated_by,
            stderr_truncated=stderr_preview.truncated,
            stderr_truncated_by=stderr_preview.truncated_by,
            stdout_artifact_path=stdout_artifact_path,
            stderr_artifact_path=stderr_artifact_path,
            stdout_total_lines=stdout_capture.total_lines,
            stdout_total_bytes=stdout_capture.total_bytes,
            stderr_total_lines=stderr_capture.total_lines,
            stderr_total_bytes=stderr_capture.total_bytes,
            stdio_complete=drain_outcome.is_complete,
            stdio_drain_reason=drain_outcome.reason,
        )


@dataclass
class _OutputActivity:
    last_at: float

    def mark(self) -> None:
        self.last_at = asyncio.get_running_loop().time()


@dataclass(frozen=True)
class _OutputDrainPolicy:
    idle_timeout_seconds: float
    hard_timeout_seconds: float


@dataclass(frozen=True)
class _OutputDrainOutcome:
    reason: StdioDrainReason | None

    @property
    def is_complete(self) -> bool:
        return self.reason is None

    @classmethod
    def complete(cls) -> _OutputDrainOutcome:
        return cls(reason=None)


_FORCED_OUTPUT_DRAIN_POLICY = _OutputDrainPolicy(
    idle_timeout_seconds=0.1,
    hard_timeout_seconds=0.5,
)


class _IncrementalTextChunks:
    def __init__(self, *, max_chunk_chars: int) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="surrogateescape")
        self._max_chunk_chars = max_chunk_chars
        self._pending = ""

    def feed(self, content: bytes) -> tuple[str, ...]:
        self._pending += self._decoder.decode(content, final=False)
        return self._take_chunks(final=False)

    def finish(self) -> tuple[str, ...]:
        self._pending += self._decoder.decode(b"", final=True)
        return self._take_chunks(final=True)

    def _take_chunks(self, *, final: bool) -> tuple[str, ...]:
        chunks: list[str] = []
        while self._pending:
            newline_index = self._pending.find("\n")
            if 0 <= newline_index < self._max_chunk_chars:
                boundary = newline_index + 1
            elif len(self._pending) >= self._max_chunk_chars:
                boundary = self._max_chunk_chars
            elif final:
                boundary = len(self._pending)
            else:
                break
            chunks.append(self._pending[:boundary])
            self._pending = self._pending[boundary:]
        return tuple(chunks)


def _validate_local_launch(command: tuple[str, ...], cwd: str) -> None:
    if not cwd or not os.path.exists(cwd):
        raise ExecLaunchError("cwd_not_found", command=command, cwd=cwd)
    if not os.path.isdir(cwd):
        raise ExecLaunchError("cwd_not_directory", command=command, cwd=cwd)
    if not command or not command[0]:
        raise ExecLaunchError("executable_not_found", command=command, cwd=cwd)


def _file_not_found_error(
    *,
    command: tuple[str, ...],
    cwd: str,
    cause: FileNotFoundError,
) -> ExecLaunchError:
    if not os.path.exists(cwd):
        kind: ExecLaunchErrorKind = "cwd_not_found"
    elif not os.path.isdir(cwd):
        kind = "cwd_not_directory"
    else:
        kind = "executable_not_found"
    return ExecLaunchError(kind, command=command, cwd=cwd, cause=cause)


async def _wait_for_root_process_exit(
    process: asyncio.subprocess.Process,
) -> int:
    # asyncio's public Process.wait() settles only after pipe transports close.
    # A descendant may inherit those pipes after the root has already exited,
    # so observe the root return code separately before applying drain grace.
    while process.returncode is None:
        await asyncio.sleep(0.01)
    return process.returncode


async def _write_process_stdin(
    process: asyncio.subprocess.Process,
    content: str | None,
) -> None:
    if process.stdin is None:
        return
    input_bytes = (
        content.encode("utf-8", errors="surrogateescape")
        if content is not None
        else b""
    )
    try:
        process.stdin.write(input_bytes)
        await process.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        # A short-lived command may exit without reading stdin. Its process
        # result remains authoritative; a closed pipe is not an exec failure.
        pass
    finally:
        process.stdin.close()
        with suppress(BrokenPipeError, ConnectionResetError):
            await process.stdin.wait_closed()


async def _drain_output_tasks(
    process: asyncio.subprocess.Process,
    tasks: tuple[asyncio.Task[None], asyncio.Task[None]],
    *,
    activity: _OutputActivity,
    policy: _OutputDrainPolicy,
) -> _OutputDrainOutcome:
    loop = asyncio.get_running_loop()
    hard_deadline = loop.time() + policy.hard_timeout_seconds
    pending = set(tasks)
    while pending:
        idle_deadline = activity.last_at + policy.idle_timeout_seconds
        remaining = max(
            0.0,
            min(idle_deadline, hard_deadline) - loop.time(),
        )
        done, pending = await asyncio.wait(
            pending,
            timeout=remaining,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if done:
            try:
                for task in done:
                    task.result()
            except BaseException:
                await _cancel_tasks(pending)
                raise
            continue
        now = loop.time()
        if now >= hard_deadline:
            reason: StdioDrainReason = "hard_timeout"
        elif now >= activity.last_at + policy.idle_timeout_seconds:
            reason = "idle_timeout"
        else:
            continue

        _close_reader_transport(process.stdout)
        _close_reader_transport(process.stderr)
        await _cancel_tasks(pending)
        return _OutputDrainOutcome(reason=reason)
    return _OutputDrainOutcome.complete()


async def _cancel_tasks(tasks: set[asyncio.Task[None]]) -> None:
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _close_reader_transport(stream: object | None) -> None:
    transport = getattr(stream, "_transport", None)
    close = getattr(transport, "close", None)
    if callable(close):
        close()


@dataclass
class _StreamCapture:
    stream_name: str
    capture_full_output: bool
    retain_output_artifact: bool
    rolling_max_bytes: int
    artifact_dir: str | None
    chunks: list[str] = field(default_factory=list)
    _chunk_bytes: int = 0
    _artifact_path: str | None = None
    _artifact_handle: TextIO | None = None
    _rolled: bool = False
    _total_bytes: int = 0
    _total_lines: int = 0
    _line_open: bool = False
    _last_was_carriage_return: bool = False

    @property
    def content(self) -> str:
        return "".join(self.chunks)

    @property
    def artifact_path(self) -> str | None:
        return self._artifact_path

    @property
    def rolled(self) -> bool:
        return self._rolled

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    @property
    def total_lines(self) -> int:
        return self._total_lines

    def append(self, text: str) -> None:
        if not text:
            return
        self._total_bytes += len(_output_bytes(text))
        self._record_lines(text)
        if self.capture_full_output:
            self.chunks.append(text)
            return

        self._ensure_artifact_handle().write(text)
        self.chunks.append(text)
        self._chunk_bytes += len(_output_bytes(text))
        self._trim_rolling_chunks()

    def close(self) -> None:
        if self._line_open:
            self._total_lines += 1
            self._line_open = False
        if self._artifact_handle is not None:
            self._artifact_handle.close()
            self._artifact_handle = None
        if not self.retain_output_artifact:
            self.discard_artifact()

    def _record_lines(self, text: str) -> None:
        for character in text:
            if character == "\r":
                self._total_lines += 1
                self._line_open = False
                self._last_was_carriage_return = True
            elif character == "\n":
                if not self._last_was_carriage_return:
                    self._total_lines += 1
                self._line_open = False
                self._last_was_carriage_return = False
            else:
                self._line_open = True
                self._last_was_carriage_return = False

    def discard_artifact(self) -> None:
        if self._artifact_path is None:
            return
        try:
            Path(self._artifact_path).unlink(missing_ok=True)
        finally:
            self._artifact_path = None

    def _ensure_artifact_handle(self) -> TextIO:
        if self._artifact_handle is not None:
            return self._artifact_handle
        fd, path = tempfile.mkstemp(
            prefix=f"loushang-exec-{self.stream_name}-",
            suffix=".log",
            dir=self.artifact_dir,
        )
        self._artifact_path = path
        self._artifact_handle = os.fdopen(
            fd,
            "w",
            encoding="utf-8",
            errors="surrogateescape",
        )
        return self._artifact_handle

    def _trim_rolling_chunks(self) -> None:
        while self._chunk_bytes > self.rolling_max_bytes and len(self.chunks) > 1:
            removed = self.chunks.pop(0)
            self._chunk_bytes -= len(_output_bytes(removed))
            self._rolled = True
        if self._chunk_bytes <= self.rolling_max_bytes or not self.chunks:
            return

        trimmed = truncate_tail(
            self.chunks[0],
            max_lines=1_000_000,
            max_bytes=self.rolling_max_bytes,
        ).content
        self.chunks[0] = trimmed
        self._chunk_bytes = len(_output_bytes(trimmed))
        self._rolled = True


@dataclass
class _OutputCapture:
    capture_full_output: bool
    rolling_max_bytes: int
    chunks: list[ExecOutputChunk] = field(default_factory=list)
    _chunk_bytes: int = 0

    def append(self, chunk: ExecOutputChunk) -> None:
        if not chunk.text:
            return
        self.chunks.append(chunk)
        if self.capture_full_output:
            return
        self._chunk_bytes += len(_output_bytes(chunk.text))
        self._trim_rolling_chunks()

    def _trim_rolling_chunks(self) -> None:
        while self._chunk_bytes > self.rolling_max_bytes and len(self.chunks) > 1:
            removed = self.chunks.pop(0)
            self._chunk_bytes -= len(_output_bytes(removed.text))
        if self._chunk_bytes <= self.rolling_max_bytes or not self.chunks:
            return

        trimmed = truncate_tail(
            self.chunks[0].text,
            max_lines=1_000_000,
            max_bytes=self.rolling_max_bytes,
        ).content
        self.chunks[0] = ExecOutputChunk(stream=self.chunks[0].stream, text=trimmed)
        self._chunk_bytes = len(_output_bytes(trimmed))


async def _kill_process(process: asyncio.subprocess.Process) -> None:
    await kill_local_process_tree(process)


async def _wait_for_abort(signal: object | None) -> None:
    while signal is not None and not getattr(signal, "aborted", False):
        await asyncio.sleep(0.01)


def _build_preview(
    content: str,
    *,
    max_lines: int,
    max_bytes: int,
    artifact_dir: str | None,
    stream_name: str,
):
    preview = truncate_tail(content, max_lines=max_lines, max_bytes=max_bytes)
    if not preview.truncated or not content:
        return preview, None
    artifact_path = _write_output_artifact(
        content, artifact_dir=artifact_dir, stream_name=stream_name
    )
    return preview, artifact_path


def _build_preview_from_capture(
    capture: _StreamCapture,
    *,
    max_lines: int,
    max_bytes: int,
):
    if capture.capture_full_output:
        if not capture.retain_output_artifact:
            return (
                truncate_tail(
                    capture.content,
                    max_lines=max_lines,
                    max_bytes=max_bytes,
                ),
                None,
            )
        return _build_preview(
            capture.content,
            max_lines=max_lines,
            max_bytes=max_bytes,
            artifact_dir=capture.artifact_dir,
            stream_name=capture.stream_name,
        )

    preview = truncate_tail(capture.content, max_lines=max_lines, max_bytes=max_bytes)
    truncated = preview.truncated or capture.rolled
    if not truncated or not capture.content:
        capture.discard_artifact()
        return preview, None
    if preview.truncated:
        return preview, capture.artifact_path
    return replace(preview, truncated=True, truncated_by="bytes"), capture.artifact_path


def _write_output_artifact(
    content: str, *, artifact_dir: str | None, stream_name: str
) -> str:
    fd, path = tempfile.mkstemp(
        prefix=f"loushang-exec-{stream_name}-", suffix=".log", dir=artifact_dir
    )
    try:
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
            errors="surrogateescape",
        ) as handle:
            handle.write(content)
    except Exception:
        os.close(fd)
        raise
    return path


def _output_bytes(content: str) -> bytes:
    return content.encode("utf-8", errors="surrogateescape")


__all__ = ["ExecBackend", "ExecService", "LocalExecBackend"]
