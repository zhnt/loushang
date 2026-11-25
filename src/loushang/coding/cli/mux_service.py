"""Local AppHost lifecycle and the systemd foreground service adapter."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

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
    from loushang.apphost.managed.systemd import start_systemd_application
    from loushang.coding.hosted.managed.service import (
        ServiceControlError,
        control_managed_service,
    )

    notify_socket = _take_systemd_socket()
    if notify_socket is None:
        print("loushang-mux service run requires a systemd notification socket", file=sys.stderr)
        return 1
    if start_systemd_application(
        control_managed_service, notify_socket, _systemd_endpoint, control_error=ServiceControlError,
    ):
        return 0
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
    from loushang.apphost.managed.systemd import run_systemd_user_action

    try:
        return run_systemd_user_action(operation, unit)
    except OSError as error:
        executable = "journalctl" if operation == "logs" else "systemctl"
        print(f"loushang-mux service: cannot run {executable}: {error.strerror}", file=sys.stderr)
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
            from loushang.apphost.managed.systemd import control_systemd_application

            reply = control_systemd_application(
                operation, expected, unit=DEFAULT_UNIT,
                endpoint=_systemd_endpoint, error=ServiceControlError,
            )
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
