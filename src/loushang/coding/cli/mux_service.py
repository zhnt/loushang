"""Coding AppHost commands and optional foreground readiness."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys

OPERATIONS = ("start", "stop", "restart", "status", "logs")


def register_arguments(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    foreground: argparse.ArgumentParser,
) -> None:
    foreground.add_argument(
        "--systemd", action="store_true", help="signal readiness to the systemd user manager"
    )
    service = commands.add_parser("service", help="control the local AppHost service")
    service.add_argument("operation", choices=OPERATIONS)
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
        parser.error("service uses the local managed AppHost")
    if args.instance is not None and (
        args.operation not in {"stop", "restart"} or re.fullmatch(r"[0-9a-f]{32}", args.instance) is None
    ):
        parser.error("--instance requires a lowercase hexadecimal instance ID and stop or restart")
    try:
        if args.operation == "logs":
            if args.json:
                parser.error("service logs does not accept --json")
            return _logs()
        return control_local(args.operation, args.instance, as_json=args.json)
    except KeyboardInterrupt:
        return 130


def _logs() -> int:
    if sys.platform == "darwin":
        from loushang.coding.hosted.macos_service import print_logs
        return print_logs()
    if sys.platform == "linux":
        from loushang.apphost.managed.contracts import ManagedServiceKeyV1
        from loushang.apphost.managed.defaults import resolve_managed_defaults
        from loushang.coding.cli.lmux import main

        namespace = resolve_managed_defaults().namespace
        service = ManagedServiceKeyV1("coding", namespace.platform_home)
        return main(["logs", "--server", service.service_id])
    print("loushang-mux service: logs_unavailable", file=sys.stderr)
    return 1


def control_local(operation: str, expected: str | None, *, as_json: bool) -> int:
    from loushang.coding.hosted.managed.service import (
        ServiceControlError,
        control_managed_service,
    )

    try:
        if sys.platform == "darwin":
            from loushang.coding.hosted.macos_service import control_launchd_service
            reply = control_launchd_service(operation, expected)
        elif sys.platform in {"linux", "win32"}:
            reply = asyncio.run(control_managed_service(operation, expected))
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
