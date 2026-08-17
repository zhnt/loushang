"""Command discovery and completion commands for the shared RPC host."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol

from loushang.harness.commands import complete_slash_commands, normalize_command_name
from loushang.harness.host.json_projection import (
    HostJsonProjectionError,
    project_host_value,
)
from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.host.rpc.routing import LegacyRpcHandler
from loushang.harness.host.rpc.wire import project_command_descriptor


class _CommandCatalogSession(Protocol):
    """Only the Product command capabilities consumed by this group."""

    def list_commands(self) -> Sequence[object]: ...

    def get_command_argument_completions(
        self,
        command: str,
        prefix: str,
    ) -> Awaitable[Sequence[object] | None]: ...

    def execute_command_async(
        self,
        invocation_name: str,
        args: str,
    ) -> Awaitable[object | None]: ...


class RpcCommandCatalogCommands:
    """Project Product command discovery through the stable JSONL wire."""

    def __init__(
        self,
        *,
        get_session: Callable[[], _CommandCatalogSession],
        output: RpcOutput,
    ) -> None:
        self._get_session = get_session
        self._output = output

    def bindings(self) -> tuple[tuple[str, LegacyRpcHandler], ...]:
        return (
            ("get_commands", self.get_commands),
            ("get_command_completions", self.get_command_completions),
            ("execute_command", self.execute_command),
        )

    async def execute_command(
        self,
        command_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        command_name = payload.get("command")
        if not isinstance(command_name, str):
            self._error(
                command_id,
                "execute_command",
                "execute_command requires a non-empty string command.",
                code="invalid_request",
            )
            return
        invocation_name = normalize_command_name(command_name)
        if not invocation_name:
            self._error(
                command_id,
                "execute_command",
                "execute_command requires a non-empty string command.",
                code="invalid_request",
            )
            return
        args = payload.get("args", "")
        if not isinstance(args, str):
            self._error(
                command_id,
                "execute_command",
                "execute_command args must be a string.",
                code="invalid_request",
            )
            return
        executor = getattr(self._get_session(), "execute_command_async", None)
        if not callable(executor):
            self._error(
                command_id,
                "execute_command",
                "Command execution is not available.",
                code="command_execution_unavailable",
            )
            return
        try:
            execution = executor(invocation_name, args)
            if inspect.isawaitable(execution):
                execution = await execution
        except Exception as error:
            self._error(
                command_id,
                "execute_command",
                f"Failed to execute command {invocation_name!r}: {error}",
                code="command_execution_failed",
            )
            return
        if execution is None:
            self._error(
                command_id,
                "execute_command",
                f"Command not found: {invocation_name}",
                code="command_not_found",
            )
            return
        result = getattr(execution, "result", execution)
        projected_invocation_name = getattr(
            execution,
            "invocation_name",
            invocation_name,
        )
        if not isinstance(projected_invocation_name, str):
            projected_invocation_name = invocation_name
        try:
            projected_result = project_host_value(
                result,
                name="command_result",
                surface="RPC command",
            )
        except HostJsonProjectionError:
            self._error(
                command_id,
                "execute_command",
                f"Command result is not serializable: {invocation_name}",
                code="command_result_not_serializable",
            )
            return
        self._output.success(
            request_id=command_id,
            command="execute_command",
            data={
                "invocationName": projected_invocation_name,
                "args": args,
                "result": projected_result,
            },
        )

    def get_commands(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        session = self._get_session()
        getter = getattr(session, "list_commands", None)
        if not callable(getter):
            self._error(
                command_id,
                "get_commands",
                "Command registry is not available.",
            )
            return
        try:
            raw_commands = getter()
        except Exception as error:
            self._error(
                command_id,
                "get_commands",
                f"Failed to query commands: {error}",
            )
            return
        if not isinstance(raw_commands, list):
            self._error(
                command_id,
                "get_commands",
                "Command registry returned an invalid response.",
            )
            return
        commands = []
        for command in raw_commands:
            try:
                commands.append(project_command_descriptor(command))
            except Exception:
                continue
        self._output.success(
            request_id=command_id,
            command="get_commands",
            data={"commands": commands},
        )

    async def get_command_completions(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        prefix = payload.get("prefix", "")
        if not isinstance(prefix, str):
            self._error(
                command_id,
                "get_command_completions",
                "Command completion prefix must be a string.",
                code="invalid_request",
            )
            return
        command_name = payload.get("command")
        if command_name is not None:
            if not isinstance(command_name, str) or not command_name:
                self._error(
                    command_id,
                    "get_command_completions",
                    "Command completion command must be a non-empty string.",
                    code="invalid_request",
                )
                return
            getter = getattr(
                self._get_session(),
                "get_command_argument_completions",
                None,
            )
            if not callable(getter):
                self._output.success(
                    request_id=command_id,
                    command="get_command_completions",
                    data={"completions": []},
                )
                return
            try:
                completions = await getter(command_name, prefix)
            except Exception as error:
                self._error(
                    command_id,
                    "get_command_completions",
                    f"Failed to query command completions: {error}",
                    code="command_completion_failed",
                )
                return
            self._output.success(
                request_id=command_id,
                command="get_command_completions",
                data={
                    "completions": completions if isinstance(completions, list) else []
                },
            )
            return

        session = self._get_session()
        getter = getattr(session, "list_commands", None)
        if not callable(getter):
            self._error(
                command_id,
                "get_command_completions",
                "Command registry is not available.",
                code="command_registry_unavailable",
            )
            return
        try:
            raw_commands = getter()
            if not isinstance(raw_commands, list):
                raise TypeError("Command registry returned an invalid response.")
            completions = complete_slash_commands(prefix, raw_commands)
        except Exception as error:
            self._error(
                command_id,
                "get_command_completions",
                f"Failed to query command completions: {error}",
                code="command_completion_failed",
            )
            return
        self._output.success(
            request_id=command_id,
            command="get_command_completions",
            data={"completions": completions},
        )

    def _error(
        self,
        command_id: str | None,
        command: str,
        error: str,
        *,
        code: str | None = None,
    ) -> None:
        self._output.error(
            request_id=command_id,
            command=command,
            error=error,
            code=code,
        )


__all__ = ["RpcCommandCatalogCommands"]
