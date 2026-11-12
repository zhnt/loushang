"""Local AppHost lifecycle and the systemd foreground service adapter."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import socket
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
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


def _uses_managed_backend() -> bool:
    return sys.platform == "win32" or os.environ.get("LOUSHANG_MUX_BACKEND") == "managed"


def control(operation: str, unit: str) -> int:
    if _uses_managed_backend():
        if operation == "logs" or unit != DEFAULT_UNIT:
            print("loushang-mux service: this action requires a systemd user unit", file=sys.stderr)
            return 1
        return control_local(operation, None, as_json=False)
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



def control_local(operation: str, expected: str | None, *, as_json: bool) -> int:
    from ..managed_service import ServiceControlError, control_managed_service

    try:
        if _uses_managed_backend():
            reply = asyncio.run(control_managed_service(operation, expected))
        elif sys.platform == "linux":
            reply = _systemd_control(operation, expected)
        else:
            raise ServiceControlError("platform_unsupported")
    except ServiceControlError as error:
        reply = {"state": "unknown", "errorCode": str(error)}
    except (OSError, subprocess.SubprocessError, ValueError):
        reply = {"state": "unknown", "errorCode": "management_unavailable"}
    if as_json:
        print(json.dumps(reply, ensure_ascii=True))
    elif "errorCode" in reply:
        print(f"loushang-mux service: {reply['errorCode']}", file=sys.stderr)
    else:
        print(reply["state"])
    return int("errorCode" in reply)


def _systemd_control(operation: str, expected: str | None) -> dict[str, object]:
    from ..managed_service import ServiceControlError

    if expected is not None and _systemd_state().get("instanceId") != expected:
        raise ServiceControlError("instance_changed")
    if operation != "status":
        result = subprocess.run(
            ["systemctl", "--user", "--no-pager", operation, "--", DEFAULT_UNIT],
            stdout=subprocess.DEVNULL, timeout=80, check=False,
        )
        if result.returncode != 0:
            raise ServiceControlError(f"{operation}_failed")
    return _systemd_state()


def _systemd_state() -> dict[str, object]:
    from ..managed_service import ServiceControlError

    command = [
        "systemctl", "--user", "--no-pager", "show",
        "--property=LoadState,ActiveState,InvocationID", "--", DEFAULT_UNIT,
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=True)
    properties = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if properties.get("LoadState") != "loaded":
        raise ServiceControlError("management_unavailable")
    state = properties.get("ActiveState", "")
    if state == "active":
        instance = properties.get("InvocationID", "")
        if not re.fullmatch(r"[0-9a-f]{32}", instance):
            raise ServiceControlError("management_unavailable")
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
        return {
            "state": "running", "instanceId": instance,
            "recordRoot": str(runtime / "loushang-host" / "connections"),
        }
    return {"state": {
        "inactive": "not_running", "activating": "starting", "deactivating": "stopping", "failed": "exited",
    }.get(state, "unknown")}


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
