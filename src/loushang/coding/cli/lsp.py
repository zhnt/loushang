"""Read-only Coding LSP catalog status and doctor commands."""

from __future__ import annotations

import json
from argparse import ArgumentParser
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, Never, TextIO

from loushang.coding.capabilities import (
    CODING_LSP_CAPABILITY,
    coding_capability_mount_mode,
)
from loushang.coding.lsp.discovery import (
    LspCatalogSnapshot,
    coding_lsp_config_paths,
    default_lsp_environment,
    discover_lsp_catalog,
)


class LspCliUsageError(ValueError):
    def __init__(self, message: str, *, usage: str) -> None:
        super().__init__(message)
        self.usage = usage


class _NoExitParser(ArgumentParser):
    def error(self, message: str) -> Never:
        raise LspCliUsageError(message, usage=self.format_usage())


def extract_lsp_argv(argv: Sequence[str]) -> tuple[str, ...] | None:
    values = list(argv)
    if values and values[0] == "lsp":
        return tuple(values[1:])
    if len(values) >= 3 and values[0] == "--cwd" and values[2] == "lsp":
        return ("--cwd", values[1], *values[3:])
    if len(values) >= 2 and values[0].startswith("--cwd=") and values[1] == "lsp":
        return (values[0], *values[2:])
    return None


async def run_coding_lsp_command(
    argv: Sequence[str],
    *,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    cwd: str | Path | None = None,
    services: Any | None = None,
    build_services: Callable[[Path], Any],
) -> int:
    """Inspect Product configuration without constructing a session or process."""

    del stdin
    try:
        namespace = _parser().parse_args(list(argv))
    except LspCliUsageError as error:
        stderr.write(error.usage)
        stderr.write(f"Error: {error}\n")
        return 2
    if namespace.help or namespace.command is None:
        stdout.write(_parser().format_help())
        return 0

    project_root = Path(namespace.cwd or cwd or Path.cwd()).expanduser().resolve()
    if not project_root.is_dir():
        stderr.write(f"Error: not a directory: {project_root}\n")
        return 2
    try:
        resolved_services = services or build_services(project_root)
        settings_manager = getattr(resolved_services, "settings_manager", None)
        mode = coding_capability_mount_mode(
            settings_manager,
            CODING_LSP_CAPABILITY,
        )
        global_config, project_config = coding_lsp_config_paths(
            settings_manager,
            workspace_root=project_root,
        )
        snapshot = discover_lsp_catalog(
            workspace_root=project_root,
            baseline_environment=default_lsp_environment(),
            global_config_path=global_config,
            project_config_path=project_config,
        )
    except (OSError, UnicodeError, TypeError, ValueError) as error:
        stderr.write(f"Error: {error}\n")
        return 1

    if namespace.output_format == "json":
        _write_json(stdout, mode=mode, snapshot=snapshot)
    else:
        _write_text(
            stdout,
            mode=mode,
            snapshot=snapshot,
            doctor=namespace.command == "doctor",
        )
    if namespace.command == "doctor" and mode != "disabled":
        return 0 if _doctor_ready(snapshot) else 1
    return 0


def _parser() -> _NoExitParser:
    parser = _NoExitParser(
        prog="loushang lsp",
        add_help=False,
        description="Inspect Coding LSP configuration without starting a server.",
    )
    parser.add_argument("--help", "-h", action="store_true", dest="help")
    parser.add_argument("--cwd")
    subparsers = parser.add_subparsers(dest="command")
    for command in ("status", "doctor"):
        command_parser = subparsers.add_parser(command, add_help=False)
        command_parser.add_argument("--help", "-h", action="store_true", dest="help")
        command_parser.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
            dest="output_format",
        )
    return parser


def _write_json(
    stdout: TextIO,
    *,
    mode: str,
    snapshot: LspCatalogSnapshot,
) -> None:
    stdout.write(
        json.dumps(
            {
                "scope": "catalog",
                "capability": CODING_LSP_CAPABILITY,
                "mount_mode": mode,
                "catalog_generation": snapshot.generation,
                "admitted_count": snapshot.admitted_count,
                "process_start_attempted": False,
                "servers": [asdict(record) for record in snapshot.records],
            },
            indent=2,
        )
    )
    stdout.write("\n")


def _write_text(
    stdout: TextIO,
    *,
    mode: str,
    snapshot: LspCatalogSnapshot,
    doctor: bool,
) -> None:
    stdout.write("Scope: catalog (offline)\n")
    stdout.write(f"Capability: {CODING_LSP_CAPABILITY} ({mode})\n")
    stdout.write(f"Catalog: {snapshot.generation}\n")
    stdout.write(f"Admitted servers: {snapshot.admitted_count}\n")
    stdout.write("Process start attempted: no\n")
    if snapshot.records:
        stdout.write("STATE\tSERVER\tSOURCE\tDETAIL\n")
        for record in snapshot.records:
            stdout.write(
                f"{record.state}\t{record.definition_id}\t{record.source}\t"
                f"{record.detail}\n"
            )
    if doctor:
        if mode == "disabled":
            stdout.write("Doctor: capability is disabled.\n")
        elif _doctor_ready(snapshot):
            stdout.write("Doctor: ready.\n")
        elif snapshot.admitted_count:
            stdout.write("Doctor: configuration errors require attention.\n")
        else:
            stdout.write(
                "Doctor: no language server is available; install a Product "
                "default or configure .loushang/lsp.json.\n"
            )


def _doctor_ready(snapshot: LspCatalogSnapshot) -> bool:
    return snapshot.admitted_count > 0 and not any(
        record.state == "rejected" for record in snapshot.records
    )


__all__ = [
    "LspCliUsageError",
    "extract_lsp_argv",
    "run_coding_lsp_command",
]
