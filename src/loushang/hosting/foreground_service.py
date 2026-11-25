"""Native termination handlers and readiness for foreground services."""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path


@contextmanager
def foreground_stop_signals(
    stop: Callable[[], None], *, include_interrupt: bool = False,
) -> Iterator[None]:
    if os.name != "posix":
        raise RuntimeError("foreground service signals require POSIX")
    loop = asyncio.get_running_loop()
    signals = (signal.SIGTERM, signal.SIGINT) if include_interrupt else (signal.SIGTERM,)
    with ExitStack() as handlers:
        for signum in signals:
            if not include_interrupt:
                handlers.callback(signal.signal, signum, signal.getsignal(signum))
            loop.add_signal_handler(signum, stop)
            handlers.callback(loop.remove_signal_handler, signum)
        yield


def notify_systemd_ready(notify_socket: str, *, pid: int | None = None) -> None:
    """Send readiness with the optional adopted main PID to the supplied socket."""
    if sys.platform != "linux":
        raise RuntimeError("systemd notification requires Linux")
    address = "\0" + notify_socket[1:] if notify_socket.startswith("@") else notify_socket
    message = b"READY=1" if pid is None else f"MAINPID={pid}\nREADY=1".encode()
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notifier:
        notifier.settimeout(1)
        notifier.sendto(message, address)


def in_current_systemd_scope(pid: int) -> bool:
    """Compare an admitted PID with the current service control group."""
    return sys.platform == "linux" and (
        Path(f"/proc/{pid}/cgroup").read_bytes() == Path("/proc/self/cgroup").read_bytes()
    )


def run_systemd_user_action(operation: str, unit: str, *, quiet: bool = False) -> int:
    if sys.platform != "linux":
        raise RuntimeError("systemd user control requires Linux")
    if operation == "logs":
        return subprocess.run(
            ["journalctl", "--user", "--no-pager", "--lines=100", "--user-unit", unit],
            check=False,
        ).returncode
    command = ["systemctl", "--user", "--no-pager", operation, "--", unit]
    if quiet:
        return subprocess.run(command, stdout=subprocess.DEVNULL, timeout=80, check=False).returncode
    return subprocess.run(command, check=False).returncode


def read_systemd_user_unit(unit: str) -> dict[str, str]:
    if sys.platform != "linux":
        raise RuntimeError("systemd user status requires Linux")
    result = subprocess.run(
        ["systemctl", "--user", "--no-pager", "show",
         "--property=LoadState,ActiveState,InvocationID", "--", unit],
        capture_output=True, text=True, timeout=10, check=True,
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
