"""Shared command invocation and result formatting for product hosts."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass


class CommandExecutionError(RuntimeError):
    """Raised when a session command cannot be executed."""


@dataclass(frozen=True, slots=True)
class CommandExecutionRequest:
    command: str
    args: str = ""
    result_format: str = "raw"


@dataclass(frozen=True, slots=True)
class CommandExecutionResult:
    command: str
    args: str
    result: object


async def execute_command(
    session: object,
    request: CommandExecutionRequest,
) -> CommandExecutionResult:
    """Invoke the session command capability and normalize its result."""

    invocation_name = request.command.strip()
    if invocation_name.startswith("/"):
        invocation_name = invocation_name[1:].strip()
    if not invocation_name:
        raise CommandExecutionError(
            "--command requires a non-empty command name."
        )

    executor = getattr(session, "execute_command_async", None)
    if not callable(executor):
        raise CommandExecutionError("command execution is not available.")
    try:
        execution = executor(invocation_name, request.args)
        if inspect.isawaitable(execution):
            execution = await execution
    except Exception as error:
        raise CommandExecutionError(str(error)) from error
    if execution is None:
        raise CommandExecutionError(f"command not found: {invocation_name}")

    result = getattr(execution, "result", _MISSING)
    if result is _MISSING:
        result = execution
    return CommandExecutionResult(invocation_name, request.args, result)


def format_command_execution_result(
    result: CommandExecutionResult,
    *,
    result_format: str = "raw",
) -> str:
    """Format a normalized result without imposing a product command schema."""

    if result_format == "json":
        return (
            json.dumps(
                {
                    "command": result.command,
                    "args": result.args,
                    "result": json_safe_command_result(result.result),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    if result.result is None:
        return ""
    value = result.result
    if isinstance(value, (dict, list, tuple)):
        try:
            text = json.dumps(value, ensure_ascii=False)
        except TypeError:
            text = repr(value)
    else:
        text = str(value)
    return f"{text}\n"


def json_safe_command_result(result: object) -> object:
    try:
        json.dumps(result, ensure_ascii=False)
        return result
    except TypeError:
        return repr(result)


_MISSING = object()


__all__ = [
    "CommandExecutionError",
    "CommandExecutionRequest",
    "CommandExecutionResult",
    "execute_command",
    "format_command_execution_result",
    "json_safe_command_result",
]
