"""Shared local OS mechanics for one-shot and hosted workspace processes."""

from __future__ import annotations

import asyncio
import ntpath
import os
import signal as signal_module
import subprocess
from collections.abc import Mapping

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


async def spawn_local_process(
    *,
    command: tuple[str, ...],
    cwd: str,
    environment: Mapping[str, str],
    pipe_stdin: bool,
) -> asyncio.subprocess.Process:
    if _is_windows():
        return await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            env=dict(environment),
            creationflags=_CREATE_NO_WINDOW,
            stdin=asyncio.subprocess.PIPE if pipe_stdin else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    return await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        env=dict(environment),
        start_new_session=True,
        stdin=asyncio.subprocess.PIPE if pipe_stdin else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def terminate_local_process_tree(process: object) -> bool:
    """Best-effort terminate one local process tree.

    The return value reports whether a platform tree primitive accepted the
    request. Callers must still settle the root process and apply their normal
    escalation timeout.
    """

    if _is_windows():
        return await _signal_windows_process_tree(process, force=False)
    return _signal_process_group(
        process,
        group_signal=signal_module.SIGTERM,
        fallback_method="terminate",
    )


async def kill_local_process_tree(process: object) -> bool:
    """Best-effort forcefully terminate one local process tree."""

    if _is_windows():
        return await _signal_windows_process_tree(process, force=True)
    return _signal_process_group(
        process,
        group_signal=signal_module.SIGKILL,
        fallback_method="kill",
    )


def terminate_local_process(process: object) -> None:
    _signal_process_group(
        process,
        group_signal=signal_module.SIGTERM,
        fallback_method="terminate",
    )


def kill_local_process(process: object) -> None:
    _signal_process_group(
        process,
        group_signal=signal_module.SIGKILL,
        fallback_method="kill",
    )


def _signal_process_group(
    process: object,
    *,
    group_signal: signal_module.Signals,
    fallback_method: str,
) -> bool:
    pid = getattr(process, "pid", None)
    try:
        if isinstance(pid, int) and pid > 0 and hasattr(os, "killpg"):
            os.killpg(pid, group_signal)
            return True
    except ProcessLookupError:
        return True
    except OSError:
        pass
    fallback = getattr(process, fallback_method, None)
    if not callable(fallback):
        return False
    try:
        fallback()
    except ProcessLookupError:
        return True
    return False


async def _signal_windows_process_tree(process: object, *, force: bool) -> bool:
    pid = getattr(process, "pid", None)
    taskkill_path = _windows_system_executable("taskkill.exe")
    if not isinstance(pid, int) or pid <= 0 or taskkill_path is None:
        _fallback_process_signal(process, force=force)
        return False

    command = [taskkill_path, "/PID", str(pid), "/T"]
    if force:
        command.append("/F")
    try:
        taskkill = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            creationflags=_CREATE_NO_WINDOW,
        )
        return_code = await taskkill.wait()
    except (OSError, ValueError):
        _fallback_process_signal(process, force=force)
        return False
    if return_code == 0:
        return True
    _fallback_process_signal(process, force=force)
    return False


def _fallback_process_signal(process: object, *, force: bool) -> None:
    method = getattr(process, "kill" if force else "terminate", None)
    if not callable(method):
        return
    try:
        method()
    except ProcessLookupError:
        return


def _windows_system_executable(name: str) -> str | None:
    system_root = _case_insensitive_environment_value("SystemRoot")
    if system_root is None:
        system_root = _case_insensitive_environment_value("WINDIR")
    if not system_root:
        return None
    return ntpath.join(system_root, "System32", name)


def _case_insensitive_environment_value(name: str) -> str | None:
    folded_name = name.casefold()
    for key, value in os.environ.items():
        if key.casefold() == folded_name:
            return value
    return None


def _is_windows() -> bool:
    return os.name == "nt"


__all__ = [
    "kill_local_process_tree",
    "kill_local_process",
    "spawn_local_process",
    "terminate_local_process_tree",
    "terminate_local_process",
]
