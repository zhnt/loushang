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
    from loushang.coding.hosted.local import CodingLocalCommandV1


DEFAULT_UNIT = "loushang-host.service"
OPERATIONS = ("start", "stop", "restart", "status", "logs", "run")


def register_arguments(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    foreground: argparse.ArgumentParser,
) -> None:
    foreground.add_argument(
        "--systemd", action="store_true", help="signal readiness to the systemd user manager"
    )
    service = commands.add_parser("service", help="control the local AppHost service")
    service.add_argument("operation", choices=OPERATIONS)
    service.add_argument("--unit", type=unit_name, default=DEFAULT_UNIT)
    service.add_argument("--json", action="store_true", help="return the local service state as JSON")
    service.add_argument("--instance", help="require this running instance for stop or restart")


def _take_systemd_socket() -> str | None:
    address = os.environ.pop("NOTIFY_SOCKET", "")
    if sys.platform == "linux" and address.startswith(("/", "@")):
        return address
    return None


def foreground_notification_socket(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> str | None:
    if not args.systemd:
        return None
    if args.describe or sys.platform != "linux":
        parser.error("--systemd requires a Linux service launch without --describe")
    address = _take_systemd_socket()
    if address is None:
        parser.error("--systemd requires the systemd notification socket")
    return address


def run_command(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.connection_root is not None or args.endpoint is not None:
        parser.error("service selects a systemd unit with --unit")
    if args.operation == "run":
        if args.unit != DEFAULT_UNIT or args.json or args.instance is not None:
            parser.error("service run requires the default unit without client options")
        return run_systemd_host()
    if args.instance is not None and (
        args.operation not in {"stop", "restart"} or re.fullmatch(r"[0-9a-f]{32}", args.instance) is None
    ):
        parser.error("--instance requires a lowercase hexadecimal instance ID and stop or restart")
    if args.json or args.instance is not None:
        if args.unit != DEFAULT_UNIT or args.operation == "logs":
            parser.error("this operation requires the default local service and a lifecycle action")
        return control_local(args.operation, args.instance, as_json=args.json)
    return control(args.operation, args.unit)


def run_systemd_host() -> int:
    """Start the existing managed Host and hand its PID directly to systemd."""
    from loushang.coding.hosted.managed.service import (
        ServiceControlError,
        control_managed_service,
    )

    notify_socket = _take_systemd_socket()
    if notify_socket is None:
        print("loushang-mux service run requires a systemd notification socket", file=sys.stderr)
        return 1
    started = None
    try:
        previous = asyncio.run(control_managed_service("status", None))
        if previous["state"] == "running":
            raise ServiceControlError("already_running")
        result = asyncio.run(control_managed_service("start", None))
        pid = result.get("pid")
        if result["state"] != "running" or type(pid) is not int or pid <= 0:
            raise ServiceControlError("start_failed")
        if Path(f"/proc/{pid}/cgroup").read_bytes() != Path("/proc/self/cgroup").read_bytes():
            raise ServiceControlError("process_scope_mismatch")
        started = result
        endpoint = _systemd_endpoint()
        temporary = endpoint.with_suffix(".tmp")
        temporary.write_text(json.dumps({"recordRoot": started["recordRoot"]}) + "\n")
        temporary.replace(endpoint)
        address = "\0" + notify_socket[1:] if notify_socket.startswith("@") else notify_socket
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notifier:
            notifier.settimeout(1)
            notifier.sendto(f"MAINPID={pid}\nREADY=1".encode(), address)
        return 0
    except (ServiceControlError, OSError, ValueError, KeyError):
        if started is not None:
            asyncio.run(control_managed_service("stop", started.get("instanceId")))
        print("loushang-mux service: systemd_host_start_failed", file=sys.stderr)
        return 1


def _systemd_endpoint() -> Path:
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    return runtime / "loushang-host" / "endpoint.json"


def unit_name(value: str) -> str:
    if not re.fullmatch(r"loushang-host(?:@[a-zA-Z0-9_.-]{1,128})?\.service", value):
        raise argparse.ArgumentTypeError(
            "expected loushang-host.service or loushang-host@NAME.service"
        )
    return value


def _uses_managed_backend() -> bool:
    return sys.platform == "win32" or os.environ.get("LOUSHANG_MUX_BACKEND") == "managed"


def control(operation: str, unit: str) -> int:
    if sys.platform == "darwin":
        if unit != DEFAULT_UNIT:
            return 1
        if operation == "logs":
            from loushang.coding.hosted.macos_service import print_logs
            return print_logs()
        return control_local(operation, None, as_json=False)
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
    from loushang.coding.hosted.managed.service import (
        ServiceControlError,
        control_managed_service,
    )

    try:
        if sys.platform == "darwin":
            from loushang.coding.hosted.macos_service import control_launchd_service
            reply = control_launchd_service(operation, expected)
        elif _uses_managed_backend():
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
    from loushang.coding.hosted.managed.service import ServiceControlError

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
    from loushang.coding.hosted.managed.service import ServiceControlError

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
        try:
            record_root = json.loads(_systemd_endpoint().read_text())["recordRoot"]
            if type(record_root) is not str or not Path(record_root).is_absolute():
                raise ValueError("invalid record root")
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ServiceControlError("management_unavailable") from error
        return {
            "state": "running", "instanceId": instance,
            "recordRoot": record_root,
        }
    return {"state": {
        "inactive": "not_running", "activating": "starting", "deactivating": "stopping", "failed": "exited",
    }.get(state, "unknown")}


async def run_host(
    command: CodingLocalCommandV1, notify_socket: str | None, log_ready: Callable[[], None]
) -> None:
    if notify_socket is None:
        await command.run(ready=log_ready)
        return
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
