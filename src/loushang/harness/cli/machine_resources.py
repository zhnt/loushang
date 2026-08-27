"""CLI adapter for the Harness machine-resource control plane."""

from __future__ import annotations

import json
from argparse import ArgumentParser
from collections.abc import Sequence
from pathlib import Path
from typing import Never, TextIO

from loushang.foundation.platform_paths import PlatformPaths
from loushang.harness.machine_resources import (
    MACHINE_RESOURCE_SCHEMA_VERSION,
    MachineResourceCleanRequest,
    clean_machine_resources,
    inspect_machine_resources,
    migrate_machine_resources,
    plan_machine_resource_migration,
    resolve_machine_resource_layout,
)


class MachineResourceCliUsageError(ValueError):
    def __init__(self, message: str, *, usage: str) -> None:
        super().__init__(message)
        self.usage = usage


class _NoExitParser(ArgumentParser):
    def error(self, message: str) -> Never:
        raise MachineResourceCliUsageError(message, usage=self.format_usage())


def extract_machine_resource_argv(argv: Sequence[str]) -> tuple[str, ...] | None:
    """Extract ``storage`` while preserving a leading common ``--cwd``."""

    values = list(argv)
    if values and values[0] == "storage":
        return tuple(values[1:])
    if len(values) >= 3 and values[0] == "--cwd" and values[2] == "storage":
        return ("--cwd", values[1], *values[3:])
    if len(values) >= 2 and values[0].startswith("--cwd=") and values[1] == "storage":
        return (values[0], *values[2:])
    return None


async def run_machine_resource_command(
    argv: Sequence[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
    cwd: str | Path | None = None,
    platform_paths: PlatformPaths | None = None,
) -> int:
    """Run paths/status/clean/migrate without constructing a model Session."""

    parser = _parser()
    try:
        namespace = parser.parse_args(list(argv))
    except MachineResourceCliUsageError as error:
        stderr.write(error.usage)
        stderr.write(f"Error: {error}\n")
        return 2
    if namespace.help or namespace.command is None:
        stdout.write(parser.format_help())
        return 0
    try:
        layout = resolve_machine_resource_layout(
            platform_paths=platform_paths,
            cwd=namespace.cwd or cwd,
        )
        if namespace.command == "paths":
            value = layout.to_dict()
            _write_result(stdout, value, output_format=namespace.output_format)
            return 0
        if namespace.command == "status":
            value = inspect_machine_resources(
                layout,
                max_entries=namespace.max_entries,
            ).to_dict()
            _write_result(stdout, value, output_format=namespace.output_format)
            return 0
        if namespace.command == "clean":
            result = clean_machine_resources(
                layout,
                MachineResourceCleanRequest(
                    targets=tuple(namespace.targets)
                    if namespace.targets
                    else (
                        "runtime",
                        "diagnostics",
                        "orphan_session_assets",
                    ),
                    apply=namespace.apply,
                ),
            )
            _write_result(
                stdout,
                result.to_dict(),
                output_format=namespace.output_format,
            )
            return (
                1
                if namespace.apply and any(report.failed for report in result.reports)
                else 0
            )
        if namespace.command == "migrate":
            plan = plan_machine_resource_migration(layout)
            if not namespace.apply:
                _write_result(
                    stdout,
                    {"applied": False, **plan.to_dict()},
                    output_format=namespace.output_format,
                )
                return 0
            results = await migrate_machine_resources(layout, plan)
            value = {
                "schemaVersion": MACHINE_RESOURCE_SCHEMA_VERSION,
                "applied": True,
                "results": [result.to_dict() for result in results],
                "diagnostics": [
                    diagnostic.to_dict() for diagnostic in plan.diagnostics
                ],
            }
            _write_result(stdout, value, output_format=namespace.output_format)
            planning_failed = any(
                diagnostic.code != "already_present" for diagnostic in plan.diagnostics
            )
            return (
                1
                if planning_failed
                or any(result.disposition == "failed" for result in results)
                else 0
            )
        raise AssertionError(f"unknown storage command: {namespace.command}")
    except (OSError, TypeError, ValueError) as error:
        stderr.write(f"Error: {error}\n")
        return 1


def _parser() -> _NoExitParser:
    parser = _NoExitParser(
        prog="loushang storage",
        add_help=False,
        description=(
            "Inspect and maintain machine-local sessions, state, runtime, scratch, "
            "logs, and image/output assets."
        ),
    )
    parser.add_argument("--help", "-h", action="store_true", dest="help")
    parser.add_argument("--cwd")
    subparsers = parser.add_subparsers(dest="command")
    for command in ("paths", "status", "clean", "migrate"):
        command_parser = subparsers.add_parser(command, add_help=False)
        command_parser.add_argument("--help", "-h", action="store_true", dest="help")
        command_parser.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
            dest="output_format",
        )
        if command == "status":
            command_parser.add_argument(
                "--max-entries",
                type=int,
                default=10_000,
                dest="max_entries",
            )
        elif command == "clean":
            command_parser.add_argument(
                "--target",
                action="append",
                choices=("runtime", "diagnostics", "orphan_session_assets"),
                default=[],
                dest="targets",
            )
            command_parser.add_argument(
                "--apply",
                action="store_true",
                help="apply the cleanup; otherwise return a non-mutating preview",
            )
        elif command == "migrate":
            command_parser.add_argument(
                "--apply",
                action="store_true",
                help="copy planned compatibility sessions into canonical storage",
            )
    return parser


def _write_result(
    stdout: TextIO,
    value: dict[str, object],
    *,
    output_format: str,
) -> None:
    if output_format == "json":
        stdout.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        return
    resources = value.get("resources")
    if isinstance(resources, list):
        stdout.write("RESOURCE\tMODE\tLIFETIME\tSTATE\tBYTES\tPATH\n")
        for item in resources:
            if not isinstance(item, dict):
                continue
            stdout.write(
                f"{item.get('resourceId', '-')}\t{item.get('mode', '-')}\t"
                f"{item.get('lifetime', '-')}\t{item.get('state', '-')}\t"
                f"{item.get('bytes', '-')}\t{item.get('path', '-')}\n"
            )
        return
    reports = value.get("reports")
    if isinstance(reports, list):
        stdout.write(f"Applied: {'yes' if value.get('applied') else 'no'}\n")
        stdout.write("TARGET\tCANDIDATES\tREMOVED\tBYTES\tACTIVE\tSKIPPED\tFAILED\n")
        for item in reports:
            if isinstance(item, dict):
                stdout.write(
                    f"{item['target']}\t{item['candidates']}\t{item['removed']}\t"
                    f"{item['removedBytes']}\t{item['active']}\t{item['skipped']}\t"
                    f"{item['failed']}\n"
                )
        return
    candidates = value.get("candidates")
    results = value.get("results")
    stdout.write(f"Applied: {'yes' if value.get('applied') else 'no'}\n")
    selected = results if isinstance(results, list) else candidates
    if isinstance(selected, list):
        stdout.write("DISPOSITION\tCONVERSATION\tSOURCE\tDESTINATION\n")
        for item in selected:
            if isinstance(item, dict):
                stdout.write(
                    f"{item.get('disposition', 'planned')}\t"
                    f"{item.get('conversationId', '-')}\t{item.get('source', '-')}\t"
                    f"{item.get('destination', '-')}\n"
                )
    diagnostics = value.get("diagnostics")
    if isinstance(diagnostics, list) and diagnostics:
        stdout.write("Diagnostics:\n")
        for item in diagnostics:
            if isinstance(item, dict):
                stdout.write(
                    f"  {item.get('code', 'unknown')}: {item.get('source', '-')}: "
                    f"{item.get('detail', '')}\n"
                )


__all__ = [
    "MachineResourceCliUsageError",
    "extract_machine_resource_argv",
    "run_machine_resource_command",
]
