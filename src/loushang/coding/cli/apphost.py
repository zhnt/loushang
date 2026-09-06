"""Exact, lazy CLI adapter for the installed Coding AppHost canary."""

from __future__ import annotations

import asyncio
import json
from argparse import ArgumentParser
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Literal, Never, Protocol, TextIO, cast

AppHostCanaryCliOperation = Literal["status", "run", "rollback", "enable"]


class AppHostCanaryCliUsageError(ValueError):
    def __init__(self, message: str, *, usage: str) -> None:
        super().__init__(message)
        self.usage = usage


class _NoExitParser(ArgumentParser):
    def error(self, message: str) -> Never:
        raise AppHostCanaryCliUsageError(message, usage=self.format_usage())


class AppHostCanaryCliResult(Protocol):
    @property
    def succeeded(self) -> bool: ...

    def to_dict(self) -> dict[str, object]: ...


AppHostCanaryCliRunner = Callable[..., Awaitable[AppHostCanaryCliResult]]


def extract_apphost_argv(argv: Sequence[str]) -> tuple[str, ...] | None:
    """Extract only the installed root CLI's exact ``apphost`` family."""

    values = list(argv)
    if values and values[0] == "apphost":
        return tuple(values[1:])
    if len(values) >= 3 and values[0] == "--cwd" and values[2] == "apphost":
        return ("--cwd", values[1], *values[3:])
    if len(values) >= 2 and values[0].startswith("--cwd=") and values[1] == "apphost":
        return (values[0], *values[2:])
    return None


async def run_coding_apphost_command(
    argv: Sequence[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
    cwd: str | Path | None = None,
    canary_runner: AppHostCanaryCliRunner | None = None,
) -> int:
    """Parse one explicit canary operation before normal Coding bootstrap."""

    parser = _parser()
    try:
        namespace = parser.parse_args(list(argv))
    except AppHostCanaryCliUsageError as error:
        stderr.write(error.usage)
        stderr.write(f"Error: {error}\n")
        return 2
    if namespace.help or namespace.family is None or namespace.operation is None:
        stdout.write(parser.format_help())
        return 0

    project_root = (
        Path(namespace.action_cwd or namespace.root_cwd or cwd or Path.cwd())
        .expanduser()
        .resolve()
    )
    if not project_root.is_dir():
        stderr.write("Error: apphost canary cwd is not a directory\n")
        return 2
    runner = canary_runner or _run_installed_canary
    operation = cast(AppHostCanaryCliOperation, namespace.operation)
    try:
        report = await runner(operation=operation, cwd=project_root)
        value = report.to_dict()
    except asyncio.CancelledError:
        raise
    except Exception:
        stderr.write("Error: coding_apphost_canary_command_failed\n")
        return 1
    if namespace.output_format == "json":
        stdout.write(json.dumps(value, sort_keys=True, separators=(",", ":")))
        stdout.write("\n")
    else:
        _write_text(stdout, value)
    return 0 if report.succeeded else 1


async def _run_installed_canary(
    *,
    operation: AppHostCanaryCliOperation,
    cwd: Path,
) -> AppHostCanaryCliResult:
    # Importing the root Coding CLI must not construct or even import the G9
    # composition. The exact command is the sole lazy activation edge.
    from loushang.coding.apphost_canary import (
        CodingAppHostCanaryRequestV1,
        run_coding_apphost_canary,
    )

    return await run_coding_apphost_canary(
        CodingAppHostCanaryRequestV1(operation=operation, cwd=cwd)
    )


def _parser() -> _NoExitParser:
    parser = _NoExitParser(
        prog="loushang apphost",
        add_help=False,
        description="Operate the explicit, default-dark Coding AppHost canary.",
    )
    parser.add_argument("--help", "-h", action="store_true", dest="help")
    parser.add_argument("--cwd", dest="root_cwd")
    families = parser.add_subparsers(dest="family")
    canary = families.add_parser("canary", add_help=False)
    canary.add_argument("--help", "-h", action="store_true", dest="help")
    operations = canary.add_subparsers(dest="operation")
    for operation in ("status", "run", "rollback", "enable"):
        command = operations.add_parser(operation, add_help=False)
        command.add_argument("--help", "-h", action="store_true", dest="help")
        command.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
            dest="output_format",
        )
        command.add_argument("--cwd", dest="action_cwd")
    return parser


def _write_text(stdout: TextIO, value: dict[str, object]) -> None:
    stdout.write(f"Operation: {value['operation']}\n")
    stdout.write(f"State: {value['state']}\n")
    stdout.write(f"Code: {value['code']}\n")
    stdout.write(f"Selection generation: {value['selectionGeneration']}\n")
    if value.get("hostingBackendId") is not None:
        stdout.write(f"Hosting backend: {value['hostingBackendId']}\n")
    transitions = value.get("hostingTransitions")
    if isinstance(transitions, list) and transitions:
        stdout.write(f"Hosting transitions: {', '.join(map(str, transitions))}\n")
    for label, key in (
        ("Receipt fingerprint", "receiptFingerprint"),
        ("Attempt fingerprint", "attemptFingerprint"),
    ):
        if value.get(key) is not None:
            stdout.write(f"{label}: {value[key]}\n")


__all__ = [
    "AppHostCanaryCliResult",
    "AppHostCanaryCliRunner",
    "AppHostCanaryCliUsageError",
    "extract_apphost_argv",
    "run_coding_apphost_command",
]
