"""systemd user service adapter for the foreground Coding Host."""

from __future__ import annotations

import argparse
import asyncio
import re
import signal
import socket
import subprocess
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..hosted_local import CodingLocalCommandV1


DEFAULT_UNIT = "loushang-host.service"
OPERATIONS = ("start", "stop", "restart", "status", "logs")


def unit_name(value: str) -> str:
    if not re.fullmatch(r"loushang-host(?:@[a-zA-Z0-9_.-]{1,128})?\.service", value):
        raise argparse.ArgumentTypeError(
            "expected loushang-host.service or loushang-host@NAME.service"
        )
    return value


def control(operation: str, unit: str) -> int:
    if sys.platform != "linux":
        print("loushang-mux service requires Linux and a systemd user manager", file=sys.stderr)
        return 1
    if operation == "logs":
        argv = ["journalctl", "--user", "--no-pager", "--lines=100", "--user-unit", unit]
    else:
        argv = ["systemctl", "--user", "--no-pager", operation, "--", unit]
    try:
        return subprocess.run(argv, check=False).returncode
    except OSError as error:
        print(f"loushang-mux service: cannot run {argv[0]}: {error.strerror}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


async def run_host(
    command: CodingLocalCommandV1, notify_socket: str, log_ready: Callable[[], None]
) -> None:
    address = "\0" + notify_socket[1:] if notify_socket.startswith("@") else notify_socket
    loop = asyncio.get_running_loop()
    host = asyncio.current_task()
    assert host is not None
    stopping = False

    def terminate() -> None:
        nonlocal stopping
        if not stopping:
            stopping = True
            command.fence()
            host.cancel()

    def ready() -> None:
        log_ready()
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notifier:
            notifier.settimeout(1)
            notifier.sendto(b"READY=1", address)

    previous = signal.getsignal(signal.SIGTERM)
    loop.add_signal_handler(signal.SIGTERM, terminate)
    try:
        await command.run(ready=ready)
    except asyncio.CancelledError:
        if not stopping:
            raise
        await command.close()
    finally:
        loop.remove_signal_handler(signal.SIGTERM)
        signal.signal(signal.SIGTERM, previous)
