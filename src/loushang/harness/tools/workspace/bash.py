import inspect
import os
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, NotRequired, Protocol, TypedDict

from loushang.agent.types import AgentToolResult, TextPart
from loushang.ai.types import ToolCall
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.effects import ProcessEffect
from loushang.harness.policy import (
    build_tool_policy_subject,
    executable_search_path_from_env,
    normalize_command_subject,
)
from loushang.harness.tools.execution import (
    AuthorizedExecution,
    AuthorizedToolAction,
    AuthorizedToolContext,
    PreparedToolAction,
    ToolCallContext,
)
from loushang.harness.workspace.exec import (
    ExecOutputChunk,
    ExecRequest,
    ExecResult,
    ExecService,
    materialize_exec_request,
)

from .builtin_renderers import render_bash_call, render_bash_result
from .runtime import (
    emit_tool_update,
    pi_truncation_details,
    resolve_tool_argument_alias,
)
from .truncate import TruncationResult, truncate_tail, truncation_details
from .types import PiTruncationDetails, ToolDefinition


@dataclass(frozen=True)
class BashSpawnContext:
    command: str
    cwd: str | None
    env: tuple[tuple[str, str], ...]


BashSpawnHook = Callable[[BashSpawnContext], BashSpawnContext]


class BashToolInput(TypedDict):
    command: str | list[str]
    cwd: NotRequired[str]
    env: NotRequired[list[tuple[str, str]] | tuple[tuple[str, str], ...]]
    timeout: NotRequired[int | float]
    timeout_seconds: NotRequired[int | float]
    timeoutSeconds: NotRequired[int | float]
    stdin: NotRequired[str]
    artifact_dir: NotRequired[str]
    artifactDir: NotRequired[str]
    capture_full_output: NotRequired[bool]
    captureFullOutput: NotRequired[bool]
    rolling_max_bytes: NotRequired[int | float]
    rollingMaxBytes: NotRequired[int | float]


class BashToolDetails(TypedDict, total=False):
    exit_code: int | None
    stderr: str
    stdout_total_lines: int
    stdout_total_bytes: int
    stdout_output_lines: int
    stdout_output_bytes: int
    stdout_last_line_partial: bool
    stdout_first_line_exceeds_limit: bool
    stdout_max_lines: int
    stdout_max_bytes: int
    stdout_truncated: bool
    stdout_truncated_by: str | None
    stderr_total_lines: int
    stderr_total_bytes: int
    stderr_output_lines: int
    stderr_output_bytes: int
    stderr_last_line_partial: bool
    stderr_first_line_exceeds_limit: bool
    stderr_max_lines: int
    stderr_max_bytes: int
    stderr_truncated: bool
    stderr_truncated_by: str | None
    stderr_artifact_path: str | None
    stdout_artifact_path: str | None
    timed_out: bool
    cancelled: bool
    truncated: bool
    truncated_by: str | None
    truncation: PiTruncationDetails | None
    full_output_path: str | None
    stream: str


class BashOperations(Protocol):
    """Execute a request using its materialized cwd and environment."""

    async def execute(
        self,
        request: ExecRequest,
        *,
        signal: object | None = None,
        on_update: object | None = None,
    ) -> ExecResult: ...


@dataclass(frozen=True)
class BashToolOptions:
    operations: BashOperations | None = None
    exec_service: ExecService | None = None
    diagnostics_service: DiagnosticsService | None = None
    command_prefix: str | None = None
    shell_path: str | None = None
    spawn_hook: BashSpawnHook | None = None


@dataclass(frozen=True)
class ExecServiceBashOperations:
    exec_service: ExecService

    async def execute(
        self,
        request: ExecRequest,
        *,
        signal: object | None = None,
        on_update: object | None = None,
    ) -> ExecResult:
        return await _execute_exec_service(
            self.exec_service,
            request,
            signal=signal,
            on_update=on_update,
        )


def create_local_bash_operations(
    *, exec_service: ExecService | None = None
) -> BashOperations:
    return ExecServiceBashOperations(exec_service=exec_service or ExecService())


def _build_exec_request(
    params: dict[str, Any],
    *,
    default_cwd: str | None = None,
    command_prefix: str | None = None,
    shell_path: str | None = None,
    spawn_hook: BashSpawnHook | None = None,
) -> ExecRequest:
    command = params.get("command")
    timeout_seconds = _optional_number(
        resolve_tool_argument_alias(
            params,
            canonical="timeout_seconds",
            aliases=("timeoutSeconds", "timeout"),
        ),
        field_name="timeout_seconds",
    )
    cwd = params.get("cwd", default_cwd)
    env = _normalize_env(params.get("env", ()))
    capture_full_output = _optional_bool(
        resolve_tool_argument_alias(
            params,
            canonical="capture_full_output",
            aliases=("captureFullOutput",),
            default=False,
        ),
        field_name="capture_full_output",
        default=False,
    )
    rolling_max_bytes = _required_integer(
        resolve_tool_argument_alias(
            params,
            canonical="rolling_max_bytes",
            aliases=("rollingMaxBytes",),
            default=100 * 1024,
        ),
        field_name="rolling_max_bytes",
    )
    artifact_dir = _optional_string(
        resolve_tool_argument_alias(
            params,
            canonical="artifact_dir",
            aliases=("artifactDir",),
        ),
        field_name="artifact_dir",
    )

    if isinstance(command, str):
        if not command:
            raise TypeError("command must be a non-empty string or sequence of strings")
        resolved_command = f"{command_prefix}\n{command}" if command_prefix else command
        spawn_context = BashSpawnContext(command=resolved_command, cwd=cwd, env=env)
        if spawn_hook is not None:
            spawn_context = spawn_hook(spawn_context)
        normalized_command = _shell_command(
            spawn_context.command, shell_path=shell_path
        )
        cwd = spawn_context.cwd
        env = _normalize_env(spawn_context.env)
    elif not isinstance(command, (list, tuple)) or not command:
        raise TypeError("command must be a non-empty sequence of strings")
    elif not all(isinstance(part, str) for part in command):
        raise TypeError("command must be a non-empty sequence of strings")
    else:
        normalized_command = tuple(command)

    return ExecRequest(
        command=normalized_command,
        cwd=cwd,
        env=env,
        timeout_seconds=timeout_seconds,
        stdin=params.get("stdin"),
        capture_full_output=capture_full_output,
        rolling_max_bytes=rolling_max_bytes,
        artifact_dir=artifact_dir,
    )


@dataclass(frozen=True)
class _BashActionAdapter:
    command_prefix: str | None
    shell_path: str | None
    spawn_hook: BashSpawnHook | None

    def prepare(
        self,
        call: ToolCall,
        context: ToolCallContext,
    ) -> PreparedToolAction:
        arguments = dict(getattr(call, "arguments"))
        exec_request = materialize_exec_request(
            _build_exec_request(
                arguments,
                default_cwd=context.cwd,
                command_prefix=self.command_prefix,
                shell_path=self.shell_path,
                spawn_hook=self.spawn_hook,
            )
        )
        effective_arguments, policy_subject = _bash_policy_facts(
            exec_request,
            arguments=arguments,
            assume_shell=isinstance(arguments.get("command"), str),
        )
        effect = ProcessEffect(exec_request.command)
        return PreparedToolAction(
            tool_name="bash",
            authorization_arguments=effective_arguments,
            execution_arguments={"request": exec_request},
            cwd=exec_request.cwd,
            policy_subject=policy_subject,
            effects=(effect,),
            execution_environment=exec_request.effective_environment,
        )


@dataclass(frozen=True)
class _BashAuthorizedHandler:
    bash_operations: BashOperations

    async def __call__(
        self,
        action: AuthorizedToolAction,
        context: AuthorizedToolContext,
    ) -> AgentToolResult[dict[str, Any]]:
        exec_request = action.execution_arguments.get("request")
        if not isinstance(exec_request, ExecRequest):
            raise TypeError("authorized Bash action requires an ExecRequest")
        selected_bash_operations = context.operation_bindings.get("bash_operations")
        if selected_bash_operations is None and isinstance(
            context.exec_service, ExecService
        ):
            selected_bash_operations = ExecServiceBashOperations(context.exec_service)
        if selected_bash_operations is None:
            selected_bash_operations = self.bash_operations
        partial_output = _BashPartialOutput()

        async def _forward_exec_update(update: ExecOutputChunk) -> None:
            partial_result = partial_output.append(update)
            await emit_tool_update(
                context.on_update,
                partial_result,
            )

        await emit_tool_update(
            context.on_update,
            AgentToolResult(content=[], details=None),
        )
        authorized_request = (
            replace(exec_request, execution_profile=action.execution_profile)
            if action.execution_profile is not None
            else exec_request
        )
        result = await _execute_bash_operations(
            selected_bash_operations,
            authorized_request,
            signal=context.signal,
            on_update=_forward_exec_update,
        )
        if result.timed_out:
            raise TimeoutError(
                _exec_result_error_message(
                    result, _timeout_error_message(exec_request.timeout_seconds)
                )
            )
        if result.cancelled:
            raise RuntimeError(_exec_result_error_message(result, "Command aborted"))
        if result.exit_code != 0 and not result.cancelled:
            raise RuntimeError(
                _exec_result_error_message(
                    result, f"Command exited with code {result.exit_code}"
                )
            )
        return _exec_result_to_tool_result(result)


def _optional_number(value: object, *, field_name: str) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field_name} must be a number")
    return value


def _optional_bool(value: object, *, field_name: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a boolean")
    return value


def _optional_string(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    return value


def _required_integer(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field_name} must be a number")
    resolved = int(value)
    if resolved < 1:
        raise ValueError(f"{field_name} must be >= 1")
    return resolved


def _normalize_env(env: object) -> tuple[tuple[str, str], ...]:
    if isinstance(env, str) or not isinstance(env, (list, tuple)):
        raise TypeError("env must contain 2-item string pairs")
    normalized: list[tuple[str, str]] = []
    for pair in env:
        if isinstance(pair, str) or not isinstance(pair, (list, tuple)):
            raise TypeError("env must contain 2-item string pairs")
        item = tuple(pair)
        if len(item) != 2 or not all(isinstance(part, str) for part in item):
            raise TypeError("env must contain 2-item string pairs")
        normalized.append((item[0], item[1]))
    return tuple(normalized)


def _shell_command(
    command: str, *, shell_path: str | None = None
) -> tuple[str, str, str]:
    shell = shell_path or ("/bin/bash" if os.path.exists("/bin/bash") else "bash")
    return (shell, "-lc", command)


def _bash_policy_facts(
    exec_request: ExecRequest,
    *,
    arguments: dict[str, Any],
    assume_shell: bool = False,
) -> tuple[dict[str, Any], object]:
    execution_environment = exec_request.effective_environment
    assert execution_environment is not None
    command_subject = normalize_command_subject(
        exec_request.command,
        cwd=exec_request.cwd,
        assume_shell=assume_shell,
        stdin=exec_request.stdin,
        executable_search_path=executable_search_path_from_env(
            execution_environment,
            default=os.defpath,
        ),
        environment_overrides=execution_environment,
        environment_is_complete=True,
    )
    effective_arguments = dict(arguments)
    effective_arguments["command"] = (
        command_subject.shell_payload
        if assume_shell and command_subject.shell_payload is not None
        else exec_request.command
    )
    if not assume_shell and command_subject.shell_payload is not None:
        effective_arguments["shell_payload"] = command_subject.shell_payload
    effective_arguments["cwd"] = exec_request.cwd
    if exec_request.stdin is not None:
        effective_arguments["stdin"] = exec_request.stdin
    if exec_request.env or "env" in arguments:
        effective_arguments["env"] = exec_request.env
    policy_subject = build_tool_policy_subject(
        tool_name="bash",
        arguments=effective_arguments,
        cwd=exec_request.cwd,
        command=command_subject,
        effects=(ProcessEffect(exec_request.command),),
    )
    return effective_arguments, policy_subject


def _bash_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "command": {
                "anyOf": [
                    {"type": "string"},
                    {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                ],
            },
            "cwd": {"type": "string"},
            "env": {
                "type": "array",
                "items": {
                    "type": "array",
                    "prefixItems": [{"type": "string"}, {"type": "string"}],
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
            "timeout": {"type": "number"},
            "timeout_seconds": {"type": "number"},
            "timeoutSeconds": {"type": "number"},
            "stdin": {"type": "string"},
            "artifact_dir": {"type": "string"},
            "artifactDir": {"type": "string"},
            "capture_full_output": {"type": "boolean"},
            "captureFullOutput": {"type": "boolean"},
            "rolling_max_bytes": {"type": "number"},
            "rollingMaxBytes": {"type": "number"},
        },
        "required": ["command"],
        "additionalProperties": False,
    }


def _bash_provider_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "number"},
        },
        "required": ["command"],
        "additionalProperties": False,
    }


def create_bash_tool_definition(
    *,
    exec_service: ExecService | None = None,
    diagnostics_service: DiagnosticsService | None = None,
    operations: BashOperations | None = None,
    command_prefix: str | None = None,
    shell_path: str | None = None,
    spawn_hook: BashSpawnHook | None = None,
    options: BashToolOptions | None = None,
) -> ToolDefinition:
    resolved_exec_service = (
        exec_service
        or (options.exec_service if options is not None else None)
        or ExecService()
    )
    resolved_operations = operations or (
        options.operations if options is not None else None
    )
    resolved_command_prefix = (
        command_prefix
        if command_prefix is not None
        else (options.command_prefix if options is not None else None)
    )
    resolved_shell_path = (
        shell_path
        if shell_path is not None
        else (options.shell_path if options is not None else None)
    )
    resolved_spawn_hook = spawn_hook or (
        options.spawn_hook if options is not None else None
    )
    bash_operations = resolved_operations or ExecServiceBashOperations(
        exec_service=resolved_exec_service
    )
    return ToolDefinition(
        name="bash",
        label="Bash",
        description="Execute a shell command through the workspace exec service.",
        parameters=_bash_parameters(),
        provider_parameters=_bash_provider_parameters(),
        execution=AuthorizedExecution(
            action_adapter=_BashActionAdapter(
                command_prefix=resolved_command_prefix,
                shell_path=resolved_shell_path,
                spawn_hook=resolved_spawn_hook,
            ),
            handler=_BashAuthorizedHandler(bash_operations=bash_operations),
        ),
        prompt_snippet="- bash: Execute shell commands. Prefer a single command string; use cwd for the working directory.",
        prompt_guidelines=(
            "Use bash for shell pipelines, redirects, and commands that are easier to express through the user's shell.",
            "Prefer read, grep, find, ls, write, and edit for file operations when those tools are more precise.",
        ),
        render_call=render_bash_call,
        render_result=render_bash_result,
    )


@dataclass
class _BashPartialOutput:
    chunks: list[str] = field(default_factory=list)

    def append(self, update: ExecOutputChunk) -> AgentToolResult[dict[str, Any]]:
        self.chunks.append(update.text)
        truncation = truncate_tail("".join(self.chunks))
        return AgentToolResult(
            content=[TextPart(type="text", text=truncation.content)],
            details={
                "stream": update.stream,
                "truncation": pi_truncation_details(truncation)
                if truncation.truncated
                else None,
                "full_output_path": None,
            },
        )


async def _execute_exec_service(
    exec_service: ExecService,
    exec_request: ExecRequest,
    *,
    signal: object | None,
    on_update: object | None,
) -> ExecResult:
    execute = exec_service.execute
    try:
        signature = inspect.signature(execute)
    except (TypeError, ValueError):
        return await execute(exec_request, signal=signal, on_update=on_update)

    accepts_var_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    kwargs: dict[str, object | None] = {}
    if accepts_var_kwargs or "signal" in signature.parameters:
        kwargs["signal"] = signal
    if accepts_var_kwargs or "on_update" in signature.parameters:
        kwargs["on_update"] = on_update
    return await execute(exec_request, **kwargs)


async def _execute_bash_operations(
    operations: BashOperations,
    exec_request: ExecRequest,
    *,
    signal: object | None,
    on_update: object | None,
) -> ExecResult:
    execute = operations.execute
    try:
        signature = inspect.signature(execute)
    except (TypeError, ValueError):
        return await execute(exec_request, signal=signal, on_update=on_update)

    accepts_var_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    kwargs: dict[str, object | None] = {}
    if accepts_var_kwargs or "signal" in signature.parameters:
        kwargs["signal"] = signal
    if accepts_var_kwargs or "on_update" in signature.parameters:
        kwargs["on_update"] = on_update
    result = execute(exec_request, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, ExecResult):
        raise TypeError("bash operations must return ExecResult")
    return result


def _exec_result_to_tool_result(result: ExecResult) -> AgentToolResult[dict[str, Any]]:
    stdout_preview = _resolve_preview(
        raw=result.stdout,
        preview=result.stdout_preview,
        truncated=result.stdout_truncated,
        truncated_by=result.stdout_truncated_by,
        total_lines=result.stdout_total_lines,
        total_bytes=result.stdout_total_bytes,
    )
    stderr_preview = _resolve_preview(
        raw=result.stderr,
        preview=result.stderr_preview,
        truncated=result.stderr_truncated,
        truncated_by=result.stderr_truncated_by,
        total_lines=result.stderr_total_lines,
        total_bytes=result.stderr_total_bytes,
    )
    output_preview = _resolve_ordered_output_preview(
        result, stdout_preview=stdout_preview, stderr_preview=stderr_preview
    )
    primary_preview = (
        output_preview
        if output_preview.content
        else stdout_preview
        if result.stdout
        else stderr_preview
    )
    full_output_path = result.stdout_artifact_path or result.stderr_artifact_path
    content = output_preview.content or "(no output)"
    truncated = (
        output_preview.truncated or stdout_preview.truncated or stderr_preview.truncated
    )
    truncation_preview = (
        output_preview
        if output_preview.truncated
        else stdout_preview
        if stdout_preview.truncated
        else stderr_preview
    )
    return AgentToolResult(
        content=[TextPart(type="text", text=content)],
        details={
            "exit_code": None if result.cancelled else result.exit_code,
            "stderr": stderr_preview.content,
            **_prefixed_truncation_details("stdout", stdout_preview),
            **_prefixed_truncation_details("stderr", stderr_preview),
            "stderr_artifact_path": result.stderr_artifact_path,
            "timed_out": result.timed_out,
            "cancelled": result.cancelled,
            "truncated": truncated,
            "truncated_by": truncation_preview.truncated_by
            if truncated
            else primary_preview.truncated_by,
            "truncation": pi_truncation_details(truncation_preview)
            if truncated
            else None,
            "full_output_path": full_output_path,
            "stdout_artifact_path": result.stdout_artifact_path,
        },
    )


def _exec_result_error_message(result: ExecResult, message: str) -> str:
    parts: list[str] = []
    stdout_preview = _resolve_preview(
        raw=result.stdout,
        preview=result.stdout_preview,
        truncated=result.stdout_truncated,
        truncated_by=result.stdout_truncated_by,
        total_lines=result.stdout_total_lines,
        total_bytes=result.stdout_total_bytes,
    )
    stderr_preview = _resolve_preview(
        raw=result.stderr,
        preview=result.stderr_preview,
        truncated=result.stderr_truncated,
        truncated_by=result.stderr_truncated_by,
        total_lines=result.stderr_total_lines,
        total_bytes=result.stderr_total_bytes,
    )
    output_preview = _resolve_ordered_output_preview(
        result, stdout_preview=stdout_preview, stderr_preview=stderr_preview
    )
    if output_preview.content:
        parts.append(output_preview.content.rstrip("\n"))
    parts.append(message)
    return "\n\n".join(parts)


def _timeout_error_message(timeout_seconds: float | int | None) -> str:
    if timeout_seconds is None:
        return "Command timed out during execution."
    return f"Command timed out after {_format_timeout_seconds(timeout_seconds)} seconds"


def _format_timeout_seconds(timeout_seconds: float | int) -> str:
    return (
        str(int(timeout_seconds))
        if float(timeout_seconds).is_integer()
        else str(timeout_seconds)
    )


def _combine_stdout_stderr(stdout: str, stderr: str) -> str:
    if not stdout:
        return stderr
    if not stderr:
        return stdout
    separator = "" if stdout.endswith("\n") or stderr.startswith("\n") else "\n"
    return f"{stdout}{separator}{stderr}"


def _resolve_ordered_output_preview(
    result: ExecResult,
    *,
    stdout_preview: TruncationResult,
    stderr_preview: TruncationResult,
) -> TruncationResult:
    if result.output_chunks:
        return truncate_tail("".join(chunk.text for chunk in result.output_chunks))
    combined = _combine_stdout_stderr(stdout_preview.content, stderr_preview.content)
    return truncate_tail(
        combined,
        max_lines=1_000_000,
        max_bytes=max(len(combined.encode("utf-8")), 1),
    )


def _resolve_preview(
    *,
    raw: str,
    preview: str,
    truncated: bool,
    truncated_by: str | None,
    total_lines: int | None = None,
    total_bytes: int | None = None,
) -> TruncationResult:
    if raw:
        resolved = truncate_tail(raw)
        if not preview or preview == resolved.content:
            if truncated and not resolved.truncated:
                resolved = replace(resolved, truncated=True, truncated_by=truncated_by)
            return _with_total_counts(
                resolved, total_lines=total_lines, total_bytes=total_bytes
            )
        preview_result = truncate_tail(preview)
        return _with_total_counts(
            replace(
                preview_result,
                truncated=truncated,
                truncated_by=truncated_by,
                total_lines=resolved.total_lines,
                total_bytes=resolved.total_bytes,
                max_lines=resolved.max_lines,
                max_bytes=resolved.max_bytes,
            ),
            total_lines=total_lines,
            total_bytes=total_bytes,
        )
    if preview:
        preview_result = truncate_tail(preview)
        return _with_total_counts(
            replace(preview_result, truncated=truncated, truncated_by=truncated_by),
            total_lines=total_lines,
            total_bytes=total_bytes,
        )
    return truncate_tail(raw)


def _with_total_counts(
    result: TruncationResult,
    *,
    total_lines: int | None,
    total_bytes: int | None,
) -> TruncationResult:
    if total_lines is None and total_bytes is None:
        return result
    return replace(
        result,
        total_lines=result.total_lines if total_lines is None else total_lines,
        total_bytes=result.total_bytes if total_bytes is None else total_bytes,
    )


def _prefixed_truncation_details(
    prefix: str, result: TruncationResult
) -> dict[str, object]:
    return {
        f"{prefix}_{key}": value for key, value in truncation_details(result).items()
    }
