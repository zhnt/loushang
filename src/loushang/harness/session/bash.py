"""Standard Bash execution binding for composed Agent sessions.

Products provide the selected Bash definition, transcript append callback, and
optional extension hook.  This module owns the Bash-specific parameter shape,
operation binding, streaming, abort, result normalization, and transcript
recording.  Historical command-execution names remain compatibility aliases.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from loushang.agent import AbortController
from loushang.harness.conversation import CommandExecutionRecord
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.workspace.exec import ExecOutputChunk

CommandOutputCallback = Callable[[ExecOutputChunk], Awaitable[None] | None]
AppendCommandRecord = Callable[[CommandExecutionRecord], Awaitable[object]]
ContextRefresher = Callable[[], None]
CommandDefinitionProvider = Callable[[], ToolDefinition | None]
CommandCallIdFactory = Callable[[], str]
CommandParametersBuilder = Callable[[str, str], Mapping[str, object]]


class CommandToolExecutor(Protocol):
    """Exact tool-host operation consumed by Bash execution."""

    def __call__(
        self,
        definition: ToolDefinition,
        *,
        tool_call_id: str,
        arguments: dict[str, object],
        signal: object | None = None,
        on_update: Callable[[object], Awaitable[None]] | None = None,
        operation_bindings: Mapping[str, object] | None = None,
    ) -> Awaitable[object]: ...


@dataclass(frozen=True)
class UserBashRequest:
    command: str
    cwd: str
    exclude_from_context: bool


@dataclass(frozen=True)
class UserBashHookResult:
    """Optional intercepted result or execution operations for a Bash command."""

    result: Mapping[str, object] | None = None
    operations: object | None = None


BashCommandHook = Callable[[UserBashRequest], Awaitable[UserBashHookResult | None]]


@dataclass
class BashCommandExecutionRuntime:
    """Run one Bash tool at a time and commit its result to the transcript."""

    command_name: str
    get_cwd: Callable[[], str]
    get_definition: CommandDefinitionProvider
    build_execution_params: CommandParametersBuilder
    create_call_id: CommandCallIdFactory
    execute_definition: CommandToolExecutor
    append_record: AppendCommandRecord
    refresh_context: ContextRefresher
    before_execute: BashCommandHook | None = None
    operations: object | None = None
    _abort_controller: AbortController | None = field(default=None, init=False)

    @property
    def is_running(self) -> bool:
        return self._abort_controller is not None

    async def execute(
        self,
        command: str,
        *,
        cwd: str | None = None,
        env: list[list[str] | tuple[str, str]]
        | tuple[tuple[str, str], ...]
        | None = None,
        timeout_seconds: float | None = None,
        stdin: str | None = None,
        exclude_from_context: bool = False,
        on_output: CommandOutputCallback | None = None,
        operations: object | None = None,
    ) -> dict[str, object]:
        if self._abort_controller is not None:
            raise RuntimeError(f"{self.command_name} execution already in progress")

        controller = AbortController()
        self._abort_controller = controller
        streamed_chunks: list[str] = []
        try:
            effective_cwd = cwd or self.get_cwd()
            selected_operations = (
                operations if operations is not None else self.operations
            )
            if self.before_execute is not None:
                interception = await self.before_execute(
                    UserBashRequest(
                        command=command,
                        cwd=effective_cwd,
                        exclude_from_context=exclude_from_context,
                    )
                )
                if interception is not None:
                    if interception.result is not None:
                        result = dict(interception.result)
                        await self.record_result(
                            command=command,
                            result=result,
                            exclude_from_context=exclude_from_context,
                        )
                        return result
                    if interception.operations is not None:
                        selected_operations = interception.operations

            definition = self.get_definition()
            if definition is None:
                raise RuntimeError(f"{self.command_name} tool is not registered")

            async def forward_update(partial_result: object) -> None:
                details = getattr(partial_result, "details", None)
                stream = details.get("stream") if isinstance(details, dict) else None
                if stream not in {"stdout", "stderr"}:
                    return
                text = "".join(
                    block.text
                    for block in getattr(partial_result, "content", ())
                    if getattr(block, "type", None) == "text"
                    and isinstance(getattr(block, "text", None), str)
                )
                if not text:
                    return
                streamed_chunks.append(text)
                if on_output is None:
                    return
                forwarded = on_output(ExecOutputChunk(stream=stream, text=text))
                if inspect.isawaitable(forwarded):
                    await forwarded

            params: dict[str, object] = (
                {"command": command, "cwd": effective_cwd}
                if getattr(definition, "name", None) == "shell"
                else dict(self.build_execution_params(command, effective_cwd))
            )
            if env is not None:
                params["env"] = [list(pair) for pair in env]
            if timeout_seconds is not None:
                params["timeout_seconds"] = timeout_seconds
            if stdin is not None:
                params["stdin"] = stdin
            try:
                tool_result = await self.execute_definition(
                    definition,
                    tool_call_id=self.create_call_id(),
                    arguments=params,
                    signal=controller.signal,
                    on_update=forward_update,
                    operation_bindings=(
                        {"bash_operations": selected_operations}
                        if selected_operations is not None
                        else None
                    ),
                )
                result = bash_result_from_tool_result(tool_result)
            except RuntimeError as exc:
                if "Command aborted" not in str(exc) or not getattr(
                    controller.signal, "aborted", False
                ):
                    raise
                result = {
                    "output": "".join(streamed_chunks),
                    "exit_code": None,
                    "cancelled": True,
                    "truncated": False,
                    "full_output_path": None,
                }

            await self.record_result(
                command=command,
                result=result,
                exclude_from_context=exclude_from_context,
            )
            return result
        finally:
            if self._abort_controller is controller:
                self._abort_controller = None

    def abort(self) -> None:
        if self._abort_controller is not None:
            self._abort_controller.abort()

    async def record_result(
        self,
        *,
        command: str,
        result: Mapping[str, object],
        exclude_from_context: bool,
    ) -> None:
        exit_code = result.get("exit_code")
        await self.append_record(
            CommandExecutionRecord(
                command=command,
                output=str(result.get("output") or ""),
                exit_code=exit_code if type(exit_code) is int else None,
                cancelled=bool(result.get("cancelled", False)),
                truncated=bool(result.get("truncated", False)),
                full_output_path=(
                    str(result["full_output_path"])
                    if isinstance(result.get("full_output_path"), str)
                    and result.get("full_output_path")
                    else None
                ),
                exclude_from_context=exclude_from_context,
            )
        )
        self.refresh_context()


def bash_result_from_tool_result(tool_result: object) -> dict[str, object]:
    """Normalize a stable workspace Bash result into a transcript record."""

    details = getattr(tool_result, "details", None)
    details = details if isinstance(details, Mapping) else {}
    output = "".join(
        block.text
        for block in getattr(tool_result, "content", ())
        if getattr(block, "type", None) == "text"
        and isinstance(getattr(block, "text", None), str)
    )
    stderr = details.get("stderr")
    if isinstance(stderr, str) and stderr and stderr not in output:
        output = output + stderr
    return {
        "output": output,
        "exit_code": details.get("exit_code"),
        "cancelled": bool(details.get("cancelled", False)),
        "truncated": bool(
            details.get("truncated", False) or details.get("stderr_truncated", False)
        ),
        "full_output_path": details.get("stdout_artifact_path")
        or details.get("stderr_artifact_path"),
    }


@dataclass(frozen=True)
class BashExecutionPorts:
    """Product callbacks needed to bind the standard Bash runtime."""

    get_cwd: Callable[[], str]
    get_definition: CommandDefinitionProvider
    execute_definition: CommandToolExecutor
    create_call_id: CommandCallIdFactory
    append_record: AppendCommandRecord
    refresh_context: ContextRefresher
    before_execute: BashCommandHook | None = None
    build_execution_params: CommandParametersBuilder | None = None
    operations: object | None = None


class BashExecutionRuntime:
    """Reusable Product binding over the shared Bash execution mechanics."""

    def __init__(self, ports: BashExecutionPorts, *, shell_path: str = "/bin/bash"):
        self._runtime = BashCommandExecutionRuntime(
            command_name="Bash",
            get_cwd=ports.get_cwd,
            get_definition=ports.get_definition,
            execute_definition=ports.execute_definition,
            build_execution_params=ports.build_execution_params
            or _default_execution_params(shell_path),
            create_call_id=ports.create_call_id,
            append_record=ports.append_record,
            refresh_context=ports.refresh_context,
            before_execute=ports.before_execute,
            operations=ports.operations,
        )

    @property
    def is_running(self) -> bool:
        return self._runtime.is_running

    @property
    def has_pending_messages(self) -> bool:
        return False

    async def execute(
        self,
        command: str,
        *,
        cwd: str | None = None,
        env: list[list[str] | tuple[str, str]]
        | tuple[tuple[str, str], ...]
        | None = None,
        timeout_seconds: float | None = None,
        stdin: str | None = None,
        exclude_from_context: bool = False,
        on_output: CommandOutputCallback | None = None,
        operations: object | None = None,
    ) -> dict[str, object]:
        return await self._runtime.execute(
            command,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
            stdin=stdin,
            exclude_from_context=exclude_from_context,
            on_output=on_output,
            operations=operations,
        )

    async def record_result(
        self,
        *,
        command: str,
        result: Mapping[str, object],
        exclude_from_context: bool = False,
    ) -> None:
        await self._runtime.record_result(
            command=command,
            result=result,
            exclude_from_context=exclude_from_context,
        )

    def abort(self) -> None:
        self._runtime.abort()


def _default_execution_params(shell_path: str) -> CommandParametersBuilder:
    def build(command: str, cwd: str) -> Mapping[str, object]:
        return {"command": [shell_path, "-lc", command], "cwd": cwd}

    return build


# Compatibility aliases retained for callers of the former capabilities module.
CommandHook = BashCommandHook
SessionCommandExecutionRuntime = BashCommandExecutionRuntime
UserCommandHookResult = UserBashHookResult
UserCommandRequest = UserBashRequest
command_result_from_tool_result = bash_result_from_tool_result


__all__ = [
    "AppendCommandRecord",
    "BashCommandExecutionRuntime",
    "BashCommandHook",
    "BashExecutionPorts",
    "BashExecutionRuntime",
    "CommandCallIdFactory",
    "CommandDefinitionProvider",
    "CommandHook",
    "CommandOutputCallback",
    "CommandParametersBuilder",
    "CommandToolExecutor",
    "ContextRefresher",
    "SessionCommandExecutionRuntime",
    "UserBashHookResult",
    "UserBashRequest",
    "UserCommandHookResult",
    "UserCommandRequest",
    "bash_result_from_tool_result",
    "command_result_from_tool_result",
]
