"""Coding CLI for reviewing and explicitly applying retained Git workspaces."""

from __future__ import annotations

import json
from argparse import ArgumentParser
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Literal, TextIO

from loushang.coding.worktree import create_coding_git_workspace_manager
from loushang.harness.workspace import (
    GitApplyPlan,
    GitWorkspaceError,
    GitWorkspaceManager,
    GitWorkspaceRecord,
)

WorkspaceOutputFormat = Literal["text", "json"]
ManagerFactory = Callable[..., GitWorkspaceManager]


class WorkspaceCliUsageError(ValueError):
    def __init__(self, message: str, *, usage: str) -> None:
        super().__init__(message)
        self.usage = usage


class _NoExitParser(ArgumentParser):
    def error(self, message: str) -> None:
        raise WorkspaceCliUsageError(message, usage=self.format_usage())


def extract_workspace_argv(argv: Sequence[str]) -> tuple[str, ...] | None:
    values = list(argv)
    if values and values[0] == "workspace":
        return tuple(values[1:])
    if len(values) >= 3 and values[0] == "--cwd" and values[2] == "workspace":
        return ("--cwd", values[1], *values[3:])
    if (
        len(values) >= 2
        and values[0].startswith("--cwd=")
        and values[1] == "workspace"
    ):
        return (values[0], *values[2:])
    return None


async def run_coding_workspace_command(
    argv: Sequence[str],
    *,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    cwd: str | Path | None = None,
    manager_factory: ManagerFactory = create_coding_git_workspace_manager,
) -> int:
    try:
        namespace = _parser().parse_args(list(argv))
    except WorkspaceCliUsageError as error:
        stderr.write(error.usage)
        stderr.write(f"Error: {error}\n")
        return 2
    if namespace.help or namespace.command is None:
        stdout.write(_parser().format_help())
        return 0
    if namespace.command != "list" and not namespace.workspace_ref:
        stderr.write(_parser().format_usage())
        stderr.write(f"Error: {namespace.command} requires WORKSPACE_REF\n")
        return 2
    project_root = Path(namespace.cwd or cwd or Path.cwd()).expanduser().resolve()
    try:
        manager = manager_factory(cwd=project_root)
        await manager.reconcile()
        if namespace.command == "list":
            _write_records(
                stdout,
                manager.list_records(),
                output_format=namespace.output_format,
            )
            return 0
        record = manager.get(namespace.workspace_ref)
        if namespace.command == "show":
            _write_record(stdout, record, output_format=namespace.output_format)
            return 0
        if namespace.command == "diff":
            patch = manager.artifact_diff(record.workspace_ref)
            stdout.write(patch)
            if not patch.endswith("\n"):
                stdout.write("\n")
            return 0
        if namespace.command == "apply":
            plan = await manager.plan_apply_workspace(
                record.workspace_ref,
                target=project_root,
            )
            if not namespace.yes and not _confirm_apply(stdin, stdout, plan):
                stderr.write("Error: apply was not confirmed; pass --yes to approve it.\n")
                return 2
            result = await manager.apply(plan)
            stdout.write(
                f"Applied {result.artifact_ref} to {plan.target_path}\n"
            )
            return 0
        if namespace.command == "discard":
            if not namespace.yes and not _confirm_discard(stdin, stdout, record):
                stderr.write(
                    "Error: discard was not confirmed; pass --yes to approve it.\n"
                )
                return 2
            result = await manager.discard(record.workspace_ref)
            stdout.write(f"Discarded {result.workspace_ref}\n")
            return 0
        raise AssertionError(f"unknown workspace command: {namespace.command}")
    except (GitWorkspaceError, OSError, ValueError) as error:
        stderr.write(f"Error: {error}\n")
        return 1


def _parser() -> _NoExitParser:
    parser = _NoExitParser(
        prog="loushang workspace",
        add_help=False,
        description="Review and explicitly hand off retained Coding workspaces.",
    )
    parser.add_argument("--help", "-h", action="store_true", dest="help")
    parser.add_argument("--cwd")
    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser("list", add_help=False)
    list_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        dest="output_format",
    )
    list_parser.add_argument("--help", "-h", action="store_true", dest="help")

    for command in ("show", "diff", "apply", "discard"):
        command_parser = subparsers.add_parser(command, add_help=False)
        command_parser.add_argument("workspace_ref", nargs="?")
        command_parser.add_argument("--help", "-h", action="store_true", dest="help")
        if command == "show":
            command_parser.add_argument(
                "--format",
                choices=("text", "json"),
                default="text",
                dest="output_format",
            )
        if command in {"apply", "discard"}:
            command_parser.add_argument("--yes", action="store_true")
    return parser


def _write_records(
    stdout: TextIO,
    records: tuple[GitWorkspaceRecord, ...],
    *,
    output_format: WorkspaceOutputFormat,
) -> None:
    if output_format == "json":
        stdout.write(json.dumps([asdict(record) for record in records], indent=2))
        stdout.write("\n")
        return
    if not records:
        stdout.write("No Git workspace records for this repository.\n")
        return
    stdout.write("STATUS\tWORKSPACE\tARTIFACTS\tPATH\n")
    for record in records:
        stdout.write(
            f"{record.status}\t{record.workspace_ref}\t"
            f"{len(record.artifact_refs)}\t{record.path}\n"
        )


def _write_record(
    stdout: TextIO,
    record: GitWorkspaceRecord,
    *,
    output_format: WorkspaceOutputFormat,
) -> None:
    value = asdict(record)
    if output_format == "json":
        stdout.write(json.dumps(value, indent=2))
        stdout.write("\n")
        return
    for key, item in value.items():
        if isinstance(item, tuple):
            rendered = ", ".join(str(part) for part in item) or "-"
        else:
            rendered = str(item)
        stdout.write(f"{key}: {rendered}\n")


def _confirm_apply(stdin: TextIO, stdout: TextIO, plan: GitApplyPlan) -> bool:
    if not getattr(stdin, "isatty", lambda: False)():
        return False
    stdout.write(
        f"Apply {plan.artifact_ref} touching {len(plan.touched_paths)} path(s)? "
        "[y/N] "
    )
    stdout.flush()
    return stdin.readline().strip().lower() in {"y", "yes"}


def _confirm_discard(
    stdin: TextIO,
    stdout: TextIO,
    record: GitWorkspaceRecord,
) -> bool:
    if not getattr(stdin, "isatty", lambda: False)():
        return False
    stdout.write(f"Discard live workspace {record.path}? [y/N] ")
    stdout.flush()
    return stdin.readline().strip().lower() in {"y", "yes"}


__all__ = [
    "WorkspaceCliUsageError",
    "extract_workspace_argv",
    "run_coding_workspace_command",
]
