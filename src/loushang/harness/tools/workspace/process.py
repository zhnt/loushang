from __future__ import annotations

import asyncio
import os
import signal as signal_module
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .operations import raise_if_operation_aborted


@dataclass(frozen=True)
class ExternalProcessResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ExternalProcessStreamResult:
    returncode: int
    stderr: str
    stopped_early: bool


async def run_external_process(
    command: Sequence[str],
    *,
    cwd: Path | str,
    signal: object | None = None,
) -> ExternalProcessResult:
    raise_if_operation_aborted(signal)
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    communicate_task = asyncio.create_task(process.communicate())
    abort_task = (
        asyncio.create_task(_wait_for_abort(signal)) if signal is not None else None
    )
    tasks = {communicate_task, *([abort_task] if abort_task is not None else [])}
    try:
        while not communicate_task.done():
            # Keep a bounded wake-up in addition to the child-watcher signal.
            # Some contained Linux hosts can reap a very short-lived process
            # without waking the selector even though asyncio queued the exit
            # callback. Cycling the loop settles that callback without imposing
            # a process runtime limit.
            done, _pending = await asyncio.wait(
                tasks,
                timeout=0.01,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if abort_task is not None and abort_task in done:
                _kill_process(process)
                if not await _settle_task(communicate_task, timeout=1):
                    communicate_task.cancel()
                    await asyncio.gather(communicate_task, return_exceptions=True)
                raise_if_operation_aborted(signal)
                raise RuntimeError("Operation aborted")
            if communicate_task in done:
                break
        stdout, stderr = communicate_task.result()
    except asyncio.CancelledError:
        _kill_process(process)
        communicate_task.cancel()
        await asyncio.gather(communicate_task, return_exceptions=True)
        raise
    finally:
        if abort_task is not None and not abort_task.done():
            abort_task.cancel()
            await asyncio.gather(abort_task, return_exceptions=True)
    return ExternalProcessResult(
        returncode=process.returncode if process.returncode is not None else 0,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )


async def run_external_process_lines(
    command: Sequence[str],
    *,
    cwd: Path | str,
    on_stdout_line: Callable[[str], bool],
    signal: object | None = None,
) -> ExternalProcessStreamResult:
    raise_if_operation_aborted(signal)
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    stdout_task = asyncio.create_task(_stream_stdout_lines(process, on_stdout_line))
    stderr_task = asyncio.create_task(
        process.stderr.read() if process.stderr is not None else _empty_bytes()
    )
    abort_task = (
        asyncio.create_task(_wait_for_abort(signal)) if signal is not None else None
    )
    tasks = [stdout_task, *([abort_task] if abort_task is not None else [])]
    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    if abort_task is not None and abort_task in done:
        _kill_process(process)
        await _wait_for_process_exit(process)
        stdout_task.cancel()
        stderr_task.cancel()
        raise_if_operation_aborted(signal)
        raise RuntimeError("Operation aborted")

    stopped_early = await stdout_task
    if abort_task is not None:
        abort_task.cancel()
    await _wait_for_process_exit(process)
    stderr = await _read_stderr_result(stderr_task)
    return ExternalProcessStreamResult(
        returncode=process.returncode if process.returncode is not None else 0,
        stderr=stderr.decode("utf-8", errors="replace"),
        stopped_early=stopped_early,
    )


async def _stream_stdout_lines(
    process: asyncio.subprocess.Process,
    on_stdout_line: Callable[[str], bool],
) -> bool:
    if process.stdout is None:
        return False
    stopped_early = False
    while True:
        line = await process.stdout.readline()
        if not line:
            return stopped_early
        should_continue = on_stdout_line(
            line.decode("utf-8", errors="replace").rstrip("\n")
        )
        if not should_continue:
            stopped_early = True
            _kill_process(process)
            return stopped_early


async def _wait_for_process_exit(process: asyncio.subprocess.Process) -> None:
    if await _wait_for_returncode(process, timeout=1):
        return
    _kill_process(process)
    await _wait_for_returncode(process, timeout=None)


async def _settle_task(task: asyncio.Task[object], *, timeout: float) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while not task.done():
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return False
        await asyncio.wait(
            {task},
            timeout=min(0.01, remaining),
            return_when=asyncio.FIRST_COMPLETED,
        )
    return True


async def _wait_for_returncode(
    process: asyncio.subprocess.Process,
    *,
    timeout: float | None,
) -> bool:
    deadline = (
        asyncio.get_running_loop().time() + timeout
        if timeout is not None
        else None
    )
    while process.returncode is None:
        if deadline is not None and asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.01)
    return True


async def _read_stderr_result(stderr_task: asyncio.Task[bytes]) -> bytes:
    try:
        return await stderr_task
    except asyncio.CancelledError:
        return b""


async def _empty_bytes() -> bytes:
    return b""


async def _wait_for_abort(signal: object | None) -> None:
    while signal is not None and not getattr(signal, "aborted", False):
        await asyncio.sleep(0.01)


def _kill_process(process: asyncio.subprocess.Process) -> None:
    try:
        if process.pid is not None and hasattr(os, "killpg"):
            os.killpg(process.pid, signal_module.SIGKILL)
            return
    except ProcessLookupError:
        return
    except OSError:
        pass
    try:
        process.kill()
    except ProcessLookupError:
        return
