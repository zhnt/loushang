"""Coding-owned Session command projection for live LSP state."""

from __future__ import annotations

import shlex
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from loushang.coding.lsp.status import (
    LspSessionStatus,
    disabled_lsp_session_status,
)
from loushang.harness.commands import SessionCommandDescriptor
from loushang.harness.resources.source import create_source_info
from loushang.harness.session import CommandExecutionResult

LSP_SESSION_COMMAND_NAME = "lsp"


class LspSessionRuntime(Protocol):
    def status(self) -> LspSessionStatus: ...

    async def stop(
        self,
        *,
        definition_id: str,
        workspace_root: str | Path,
    ) -> bool: ...


def lsp_session_command_descriptor() -> SessionCommandDescriptor:
    return SessionCommandDescriptor(
        name=LSP_SESSION_COMMAND_NAME,
        description="Show or stop language servers owned by this session",
        source="builtin",
        source_info=create_source_info(
            "<builtin>",
            source="builtin",
            scope="project",
            origin="top-level",
        ),
        argument_hint="[status | stop <server-id> <root>]",
    )


async def execute_lsp_session_command(
    runtime: LspSessionRuntime | None,
    args: str,
) -> CommandExecutionResult:
    try:
        values = shlex.split(args)
    except ValueError as exc:
        return _result(status="error", message=f"Invalid /lsp arguments: {exc}")
    action = values[0] if values else "status"
    if action == "status":
        if len(values) != 1 and values:
            return _usage_error()
        status = (
            runtime.status() if runtime is not None else disabled_lsp_session_status()
        )
        return _status_result(status)
    if action != "stop" or len(values) != 3:
        return _usage_error()
    if runtime is None:
        return _result(
            status="error",
            message="Coding LSP is disabled for this session.",
        )
    definition_id, workspace_root = values[1:]
    try:
        stopped = await runtime.stop(
            definition_id=definition_id,
            workspace_root=workspace_root,
        )
    except (KeyError, OSError, ValueError) as exc:
        return _result(status="error", message=str(exc))
    except Exception:
        return _result(
            status="error",
            message=f"Failed to stop LSP Server {definition_id}.",
        )
    status = runtime.status()
    projected = _status_payload(status)
    projected.update(
        {
            "action": "stop",
            "stopped": stopped,
            "message": (
                f"Stopped LSP Server {definition_id}."
                if stopped
                else f"No matching running LSP Server: {definition_id}."
            ),
        }
    )
    return CommandExecutionResult(
        invocation_name=LSP_SESSION_COMMAND_NAME,
        result=projected,
    )


def _status_result(status: LspSessionStatus) -> CommandExecutionResult:
    payload = _status_payload(status)
    payload["display"] = _status_display(status)
    return CommandExecutionResult(
        invocation_name=LSP_SESSION_COMMAND_NAME,
        result=payload,
    )


def _status_payload(status: LspSessionStatus) -> dict[str, object]:
    value = asdict(status)
    value["servers"] = list(value["servers"])
    return {
        "source": "builtin",
        "command": LSP_SESSION_COMMAND_NAME,
        "status": "ok",
        **value,
        "starting_count": status.starting_count,
        "ready_count": status.ready_count,
        "failed_count": status.failed_count,
    }


def _status_display(status: LspSessionStatus) -> str:
    if not status.enabled:
        return "LSP session capability: disabled"
    lines = [
        "LSP session runtime: "
        f"{status.ready_count} ready, {status.starting_count} starting, "
        f"{status.failed_count} failed"
    ]
    if not status.servers:
        lines.append("No language server has been started in this session.")
    for server in status.servers:
        lines.append(
            f"{server.state}\t{server.definition_id}\t{server.workspace_root}\t"
            f"documents={server.open_document_count}\t"
            f"diagnostics={server.current_diagnostic_count}\t"
            f"requests={server.request_count}\ttimeouts={server.timeout_count}\t"
            f"replacements={server.replacement_count}"
        )
    return "\n".join(lines)


def _usage_error() -> CommandExecutionResult:
    return _result(
        status="error",
        message="Usage: /lsp [status | stop <server-id> <root>]",
    )


def _result(*, status: str, message: str) -> CommandExecutionResult:
    return CommandExecutionResult(
        invocation_name=LSP_SESSION_COMMAND_NAME,
        result={
            "source": "builtin",
            "command": LSP_SESSION_COMMAND_NAME,
            "status": status,
            "message": message,
        },
    )


__all__ = [
    "LSP_SESSION_COMMAND_NAME",
    "LspSessionRuntime",
    "execute_lsp_session_command",
    "lsp_session_command_descriptor",
]
