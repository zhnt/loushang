"""Target-aware model shell tool.

Unlike the compatibility ``bash`` tool, this definition accepts only plaintext
script text.  It resolves the target shell before authorization, binds the
plain script and resolved shell metadata into policy, then executes the frozen
transport argv through the normal workspace gateway.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal, NotRequired, Protocol, TypedDict

from loushang.ai.types import ToolCall
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.effects import ProcessEffect
from loushang.harness.environment import (
    HostEnvironment,
    LocalHostEnvironmentProbe,
)
from loushang.harness.policy import (
    build_tool_policy_subject,
    shell_command_policy_subject,
)
from loushang.harness.tools.execution import (
    AuthorizedExecution,
    PreparedToolAction,
    ToolCallContext,
)
from loushang.harness.workspace.exec import (
    ExecService,
    materialize_exec_request,
)
from loushang.harness.workspace.shell import (
    LocalShellResolver,
    ResolvedShell,
    ShellSelection,
    compile_shell_launch,
)

from .bash import (
    BashOperations,
    ExecServiceBashOperations,
    _BashAuthorizedHandler,
    _build_exec_request,
)
from .builtin_renderers import render_bash_call, render_bash_result
from .types import ToolDefinition

WORKSPACE_COMMAND_CAPABILITY = "workspace.command"


class ShellToolInput(TypedDict):
    command: str
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


class ShellResolver(Protocol):
    def resolve(self, selection: ShellSelection | None = None) -> ResolvedShell: ...


ShellResolverFactory = Callable[
    [HostEnvironment, Mapping[str, str], str],
    ShellResolver,
]


@dataclass(frozen=True)
class ShellToolOptions:
    operations: BashOperations | None = None
    exec_service: ExecService | None = None
    diagnostics_service: DiagnosticsService | None = None
    environment: HostEnvironment | None = None
    selection: ShellSelection = ShellSelection()
    command_prefix: str | None = None
    resolver_factory: ShellResolverFactory | None = None
    target_id: str = "local"

    def __post_init__(self) -> None:
        if not isinstance(self.target_id, str) or not self.target_id:
            raise ValueError("shell target_id must be a non-empty string")


@dataclass(frozen=True)
class _ShellActionAdapter:
    environment: HostEnvironment
    selection: ShellSelection
    command_prefix: str | None
    resolver_factory: ShellResolverFactory

    def prepare(
        self,
        call: ToolCall,
        context: ToolCallContext,
    ) -> PreparedToolAction:
        arguments = dict(getattr(call, "arguments"))
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            raise TypeError("command must be a non-empty string")
        script = f"{self.command_prefix}\n{command}" if self.command_prefix else command

        placeholder_arguments = dict(arguments)
        placeholder_arguments["command"] = ["loushang-shell-placeholder"]
        request = materialize_exec_request(
            _build_exec_request(
                placeholder_arguments,
                default_cwd=context.cwd,
            )
        )
        assert request.cwd is not None
        assert request.effective_environment is not None
        environment = dict(request.effective_environment)
        resolver = self.resolver_factory(self.environment, environment, request.cwd)
        resolved_shell = resolver.resolve(self.selection)
        launch = compile_shell_launch(
            resolved_shell,
            script,
            cwd=request.cwd,
            effective_environment=request.effective_environment,
        )
        exec_request = replace(request, command=launch.argv)
        dialect: Literal["powershell", "cmd", "posix"] = (
            "powershell"
            if resolved_shell.kind == "powershell"
            else "cmd"
            if resolved_shell.kind == "cmd"
            else "posix"
        )
        command_subject = shell_command_policy_subject(
            launch.argv,
            script=launch.plain_script,
            dialect=dialect,
            shell_flavor=resolved_shell.flavor,
            cwd=launch.cwd,
        )
        effect = ProcessEffect(exec_request.command)
        effective_arguments = dict(arguments)
        effective_arguments.update(
            {
                "command": launch.plain_script,
                "cwd": launch.cwd,
                "resolved_shell": {
                    "executable": resolved_shell.executable,
                    "flavor": resolved_shell.flavor,
                    "kind": resolved_shell.kind,
                    "source": resolved_shell.source,
                    "target_id": resolved_shell.target_id,
                    "transport": launch.transport,
                },
            }
        )
        if exec_request.env or "env" in arguments:
            effective_arguments["env"] = exec_request.env
        policy_subject = build_tool_policy_subject(
            tool_name="shell",
            capability_id=WORKSPACE_COMMAND_CAPABILITY,
            arguments=effective_arguments,
            cwd=exec_request.cwd,
            command=command_subject,
            effects=(effect,),
        )
        return PreparedToolAction(
            tool_name="shell",
            authorization_arguments=effective_arguments,
            execution_arguments={"request": exec_request},
            cwd=exec_request.cwd,
            policy_subject=policy_subject,
            effects=(effect,),
            execution_environment=exec_request.effective_environment,
        )


def _local_resolver_factory(
    environment: HostEnvironment,
    environ: Mapping[str, str],
    cwd: str,
) -> ShellResolver:
    return LocalShellResolver(
        environment=environment,
        environ=environ,
        cwd=cwd,
    )


def _shell_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
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


def _shell_provider_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "number"},
        },
        "required": ["command"],
        "additionalProperties": False,
    }


def create_shell_tool_definition(
    *,
    exec_service: ExecService | None = None,
    diagnostics_service: DiagnosticsService | None = None,
    operations: BashOperations | None = None,
    environment: HostEnvironment | None = None,
    selection: ShellSelection | None = None,
    command_prefix: str | None = None,
    resolver_factory: ShellResolverFactory | None = None,
    target_id: str | None = None,
    options: ShellToolOptions | None = None,
) -> ToolDefinition:
    resolved_exec_service = (
        exec_service
        or (options.exec_service if options is not None else None)
        or ExecService()
    )
    resolved_operations = operations or (
        options.operations if options is not None else None
    )
    resolved_environment = (
        environment
        or (options.environment if options is not None else None)
        or LocalHostEnvironmentProbe().detect()
    )
    resolved_selection = selection or (
        options.selection if options is not None else ShellSelection()
    )
    resolved_prefix = (
        command_prefix
        if command_prefix is not None
        else (options.command_prefix if options is not None else None)
    )
    resolved_resolver_factory = resolver_factory or (
        options.resolver_factory
        if options is not None and options.resolver_factory is not None
        else _local_resolver_factory
    )
    resolved_target_id = (
        target_id
        if target_id is not None
        else (options.target_id if options is not None else "local")
    )
    if not resolved_target_id:
        raise ValueError("shell target_id must be a non-empty string")
    shell_operations = resolved_operations or ExecServiceBashOperations(
        exec_service=resolved_exec_service
    )
    is_windows = resolved_environment.os_family == "windows"
    return ToolDefinition(
        name="shell",
        label="PowerShell" if is_windows else "Shell",
        description=(
            "Execute a PowerShell script through the workspace exec service. "
            "Use Windows PowerShell 5.1-compatible syntax unless the resolved "
            "shell metadata explicitly indicates PowerShell 7."
            if is_windows
            else "Execute a shell script through the workspace exec service."
        ),
        parameters=_shell_parameters(),
        provider_parameters=_shell_provider_parameters(),
        execution=AuthorizedExecution(
            action_adapter=_ShellActionAdapter(
                environment=resolved_environment,
                selection=resolved_selection,
                command_prefix=resolved_prefix,
                resolver_factory=(
                    lambda target_environment, environ, cwd: _resolver_with_target_id(
                        resolved_resolver_factory,
                        target_environment,
                        environ,
                        cwd,
                        resolved_target_id,
                    )
                ),
            ),
            handler=_BashAuthorizedHandler(bash_operations=shell_operations),
        ),
        prompt_snippet=(
            "- shell: Execute PowerShell scripts on Windows. Use PowerShell "
            "syntax, not Bash syntax."
            if is_windows
            else "- shell: Execute scripts using the resolved target shell."
        ),
        prompt_guidelines=(
            (
                "Use PowerShell cmdlets and PowerShell pipelines; do not emit Bash syntax such as export, test -f, or $(...).",
                "Keep scripts compatible with Windows PowerShell 5.1 unless PowerShell 7-only syntax is required and known to be available.",
                "Prefer one literal command per tool call for routine inspection and checks; compound scripts, pipelines, redirects, and dynamic expressions may require approval.",
                "Prefer read, grep, find, ls, write, and edit for file operations when those tools are more precise.",
            )
            if is_windows
            else (
                "Use shell for pipelines, redirects, and commands that are easier to express through the target shell.",
                "Prefer read, grep, find, ls, write, and edit for file operations when those tools are more precise.",
            )
        ),
        render_call=render_bash_call,
        render_result=render_bash_result,
    )


def _resolver_with_target_id(
    factory: ShellResolverFactory,
    environment: HostEnvironment,
    environ: Mapping[str, str],
    cwd: str,
    target_id: str,
) -> ShellResolver:
    resolver = factory(environment, environ, cwd)
    if isinstance(resolver, LocalShellResolver) and resolver.target_id != target_id:
        return replace(resolver, target_id=target_id)
    return resolver


__all__ = [
    "ShellResolver",
    "ShellResolverFactory",
    "ShellToolInput",
    "ShellToolOptions",
    "WORKSPACE_COMMAND_CAPABILITY",
    "create_shell_tool_definition",
]
