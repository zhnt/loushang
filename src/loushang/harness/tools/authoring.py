"""Product-neutral authoring surface for explicitly bound tools."""

from __future__ import annotations

import inspect
import json
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from inspect import signature
from pathlib import Path
from typing import (
    Annotated,
    Any,
    NotRequired,
    Required,
    get_args,
    get_origin,
    get_type_hints,
)

from loushang.agent.types import AgentToolResult, TextPart
from loushang.ai.types import ToolCall
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.effects import (
    FilesystemEffect,
    FilesystemOperation,
    NetworkEffect,
    ProcessEffect,
    PublicationEffect,
)
from loushang.harness.policy import (
    build_tool_policy_subject,
    executable_search_path_from_env,
    normalize_command_subject,
)
from loushang.harness.tools.core import (
    _TOOL_SPEC_ATTR,
    DecoratedTool,
    DecoratedToolSpec,
    ToolContextProvider,
    ToolDefinition,
    apply_schema_overrides,
    infer_schema_from_signature,
    tool,
)
from loushang.harness.tools.execution import (
    AuthorizedExecution,
    AuthorizedToolAction,
    AuthorizedToolContext,
    DirectExecution,
    DirectToolContext,
    PreparedToolAction,
    ToolActionAdapter,
    ToolCallContext,
)
from loushang.harness.workspace.exec import ExecService

ToolEventSink = Callable[[Mapping[str, object]], Awaitable[None] | None]


@dataclass(frozen=True)
class ToolContext:
    """Restricted context injected into a decorated tool handler."""

    tool_call_id: str
    cwd: str | None = None
    diagnostics: DiagnosticsService | None = None
    signal: object | None = None
    model: object | None = None
    event_sink: ToolEventSink | None = None
    exec_service: ExecService | None = None


def _titleize_tool_name(name: str) -> str:
    return name.replace("_", " ").title()


def _unwrap_annotation(annotation: object) -> object:
    origin = get_origin(annotation)
    if origin is Annotated:
        return _unwrap_annotation(get_args(annotation)[0])
    if origin in (Required, NotRequired):
        return _unwrap_annotation(get_args(annotation)[0])
    return annotation


def _resolve_context_parameter_name(fn: Callable[..., object]) -> str | None:
    hints = get_type_hints(fn, include_extras=True)
    context_parameter_name: str | None = None
    for parameter_name in signature(fn).parameters:
        annotation = hints.get(parameter_name)
        if annotation is None:
            continue
        if _unwrap_annotation(annotation) is ToolContext:
            if context_parameter_name is not None:
                raise TypeError(
                    "tool functions may declare at most one ToolContext parameter"
                )
            context_parameter_name = parameter_name
    return context_parameter_name


def _normalize_plain_return_value(value: object) -> AgentToolResult[Any]:
    if value is None:
        return AgentToolResult(content=[], details={})
    if isinstance(value, AgentToolResult):
        return value
    if isinstance(value, str):
        return AgentToolResult(
            content=[TextPart(type="text", text=value)],
            details=value,
        )
    if isinstance(value, (dict, list, int, float, bool)):
        text = json.dumps(value, ensure_ascii=False)
        return AgentToolResult(
            content=[TextPart(type="text", text=text)],
            details=value,
        )
    raise TypeError(
        f"unsupported plain return type for decorated tool: {type(value).__name__}"
    )


@dataclass(frozen=True)
class _DecoratedDirectHandler:
    spec: DecoratedToolSpec
    context_parameter_name: str | None = None

    async def __call__(
        self,
        call: ToolCall,
        context: DirectToolContext,
    ) -> AgentToolResult[Any]:
        return await _invoke_decorated_tool(
            self.spec,
            call.arguments,
            context_parameter_name=self.context_parameter_name,
            context=ToolContext(
                tool_call_id=context.tool_call_id,
                cwd=context.cwd,
                diagnostics=context.diagnostics
                if isinstance(context.diagnostics, DiagnosticsService)
                else None,
                signal=context.signal,
                model=context.model,
            ),
        )


@dataclass(frozen=True)
class _DecoratedAuthorizedHandler:
    spec: DecoratedToolSpec
    context_parameter_name: str | None = None

    async def __call__(
        self,
        action: AuthorizedToolAction,
        context: AuthorizedToolContext,
    ) -> AgentToolResult[Any]:
        return await _invoke_decorated_tool(
            self.spec,
            action.execution_arguments,
            context_parameter_name=self.context_parameter_name,
            context=ToolContext(
                tool_call_id=context.tool_call_id,
                cwd=context.cwd,
                diagnostics=context.diagnostics
                if isinstance(context.diagnostics, DiagnosticsService)
                else None,
                signal=context.signal,
                model=context.model,
                event_sink=context.event_sink
                if callable(context.event_sink)
                else None,
                exec_service=context.exec_service
                if isinstance(context.exec_service, ExecService)
                else None,
            ),
        )


async def _invoke_decorated_tool(
    spec: DecoratedToolSpec,
    params: Mapping[str, Any],
    *,
    context_parameter_name: str | None,
    context: ToolContext,
) -> AgentToolResult[Any]:
    call_params = {
        str(name): _thaw_execution_value(value)
        for name, value in params.items()
    }
    if context_parameter_name is not None:
        call_params[context_parameter_name] = context
    bound = signature(spec.fn).bind_partial(**call_params)
    result = spec.fn(*bound.args, **bound.kwargs)
    if inspect.isawaitable(result):
        result = await result
    return _normalize_plain_return_value(result)


def _thaw_execution_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(name): _thaw_execution_value(item)
            for name, item in value.items()
        }
    if isinstance(value, tuple):
        return [_thaw_execution_value(item) for item in value]
    return value


def _resolve_decorated_spec(obj: object) -> DecoratedToolSpec:
    if isinstance(obj, DecoratedToolSpec):
        return obj
    if isinstance(obj, DecoratedTool):
        return obj.__loushang_tool_spec__
    spec = getattr(obj, _TOOL_SPEC_ATTR, None)
    if isinstance(spec, DecoratedToolSpec):
        return spec
    raise TypeError("expected a decorated tool")


def direct_tool(
    obj: DecoratedToolSpec | DecoratedTool | object,
) -> ToolDefinition:
    """Bind a decorated tool that consumes no common protected resource."""

    spec = _resolve_decorated_spec(obj)
    context_parameter_name = _resolve_context_parameter_name(spec.fn)
    return _build_decorated_definition(
        spec,
        execution=DirectExecution(
            _DecoratedDirectHandler(
                spec,
                context_parameter_name=context_parameter_name,
            )
        ),
        context_parameter_name=context_parameter_name,
    )


def authorized_tool(
    obj: DecoratedToolSpec | DecoratedTool | object,
    *,
    action: ToolActionAdapter,
) -> ToolDefinition:
    """Bind a decorated tool whose action must pass through the Gateway."""

    spec = _resolve_decorated_spec(obj)
    context_parameter_name = _resolve_context_parameter_name(spec.fn)
    return _build_decorated_definition(
        spec,
        execution=AuthorizedExecution(
            action_adapter=action,
            handler=_DecoratedAuthorizedHandler(
                spec,
                context_parameter_name=context_parameter_name,
            ),
        ),
        context_parameter_name=context_parameter_name,
    )


def _build_decorated_definition(
    obj: DecoratedToolSpec,
    *,
    execution: DirectExecution | AuthorizedExecution,
    context_parameter_name: str | None,
) -> ToolDefinition:
    name = obj.name if obj.name is not None else obj.fn.__name__
    description = (
        obj.description
        if obj.description is not None
        else (obj.fn.__doc__.strip() if obj.fn.__doc__ else "")
    )
    label = obj.label if obj.label is not None else _titleize_tool_name(name)
    parameters = apply_schema_overrides(
        infer_schema_from_signature(
            obj.fn,
            exclude_names=(
                {context_parameter_name}
                if context_parameter_name is not None
                else None
            ),
        ),
        obj.schema_overrides,
    )
    return ToolDefinition(
        name=name,
        label=label,
        description=description,
        parameters=parameters,
        execution=execution,
        prompt_snippet=obj.prompt_snippet,
        prompt_guidelines=tuple(obj.prompt_guidelines),
    )


@dataclass(frozen=True, slots=True)
class FilesystemActionAdapter:
    """Prepare one filesystem action with resolved, authority-bearing paths."""

    operation: FilesystemOperation
    path_argument: str = "path"
    default_path: str | None = None
    authorization_fields: tuple[str, ...] = ()

    def prepare(
        self,
        call: ToolCall,
        context: ToolCallContext,
    ) -> PreparedToolAction:
        raw_path = call.arguments.get(self.path_argument, self.default_path)
        if not isinstance(raw_path, str) or not raw_path:
            raise TypeError(
                f"{self.path_argument} must be a non-empty string"
            )
        resolved = _resolve_path(raw_path, cwd=context.cwd)
        authorization_arguments: dict[str, Any] = {"path": resolved}
        for field_name in self.authorization_fields:
            if field_name not in call.arguments:
                raise TypeError(
                    f"authorized filesystem action requires {field_name!r}"
                )
            authorization_arguments[field_name] = call.arguments[field_name]
        effect = FilesystemEffect(self.operation, (resolved,))
        return PreparedToolAction(
            tool_name=call.name,
            authorization_arguments=authorization_arguments,
            execution_arguments=call.arguments,
            cwd=context.cwd,
            effects=(effect,),
        )


@dataclass(frozen=True, slots=True)
class ProcessActionAdapter:
    """Prepare a simple command-bearing action for process execution."""

    command_argument: str = "command"
    assume_shell: bool = False

    def prepare(
        self,
        call: ToolCall,
        context: ToolCallContext,
    ) -> PreparedToolAction:
        raw_command = call.arguments.get(self.command_argument)
        if isinstance(raw_command, str):
            if not raw_command:
                raise TypeError("command must be non-empty")
            command = ("/bin/sh", "-lc", raw_command)
        elif isinstance(raw_command, (list, tuple)) and raw_command and all(
            isinstance(part, str) and part for part in raw_command
        ):
            command = tuple(raw_command)
        else:
            raise TypeError("command must be a non-empty string or string sequence")
        cwd = _optional_string(call.arguments.get("cwd"), default=context.cwd)
        environment = call.arguments.get("env", ())
        stdin = call.arguments.get("stdin")
        command_subject = normalize_command_subject(
            command,
            cwd=cwd,
            assume_shell=self.assume_shell or isinstance(raw_command, str),
            stdin=stdin if isinstance(stdin, str) else None,
            executable_search_path=executable_search_path_from_env(
                environment,
                default=os.defpath,
            ),
            environment_overrides=environment,
        )
        authorization_arguments = dict(call.arguments)
        authorization_arguments["command"] = (
            command_subject.shell_payload
            if isinstance(raw_command, str)
            and command_subject.shell_payload is not None
            else command
        )
        authorization_arguments["cwd"] = cwd
        effect = ProcessEffect(command)
        subject = build_tool_policy_subject(
            tool_name=call.name,
            arguments=authorization_arguments,
            cwd=cwd,
            command=command_subject,
            effects=(effect,),
        )
        return PreparedToolAction(
            tool_name=call.name,
            authorization_arguments=authorization_arguments,
            execution_arguments=call.arguments,
            cwd=cwd,
            policy_subject=subject,
            effects=(effect,),
        )


@dataclass(frozen=True, slots=True)
class NetworkActionAdapter:
    target_argument: str = "url"
    mutation: bool = False

    def prepare(
        self,
        call: ToolCall,
        context: ToolCallContext,
    ) -> PreparedToolAction:
        target = call.arguments.get(self.target_argument)
        if not isinstance(target, str) or not target:
            raise TypeError(
                f"{self.target_argument} must be a non-empty string"
            )
        effect = NetworkEffect(target=target, mutation=self.mutation)
        return _effect_action(call, context, effect)


@dataclass(frozen=True, slots=True)
class PublicationActionAdapter:
    target_argument: str = "target"
    repository_argument: str | None = "repository"
    remote_argument: str | None = "remote"

    def prepare(
        self,
        call: ToolCall,
        context: ToolCallContext,
    ) -> PreparedToolAction:
        target = call.arguments.get(self.target_argument)
        if not isinstance(target, str) or not target:
            raise TypeError(
                f"{self.target_argument} must be a non-empty string"
            )
        repository = _optional_argument(
            call.arguments,
            self.repository_argument,
        )
        remote = _optional_argument(call.arguments, self.remote_argument)
        return _effect_action(
            call,
            context,
            PublicationEffect(
                target=target,
                repository=repository,
                remote=remote,
            ),
        )


def _effect_action(
    call: ToolCall,
    context: ToolCallContext,
    effect: NetworkEffect | PublicationEffect,
) -> PreparedToolAction:
    arguments = dict(call.arguments)
    subject = build_tool_policy_subject(
        tool_name=call.name,
        arguments=arguments,
        cwd=context.cwd,
        effects=(effect,),
    )
    return PreparedToolAction(
        tool_name=call.name,
        authorization_arguments=arguments,
        execution_arguments=call.arguments,
        cwd=context.cwd,
        policy_subject=subject,
        effects=(effect,),
    )


def _resolve_path(raw_path: str, *, cwd: str | None) -> str:
    path = Path(raw_path).expanduser()
    if not path.is_absolute() and cwd:
        path = Path(cwd) / path
    return str(path.resolve(strict=False))


def _optional_string(value: object, *, default: str | None) -> str | None:
    if value is None:
        return default
    if not isinstance(value, str):
        raise TypeError("value must be a string or None")
    return value


def _optional_argument(
    arguments: Mapping[str, Any],
    name: str | None,
) -> str | None:
    if name is None:
        return None
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be a non-empty string or None")
    return value


__all__ = [
    "DecoratedTool",
    "DecoratedToolSpec",
    "FilesystemActionAdapter",
    "NetworkActionAdapter",
    "ProcessActionAdapter",
    "PublicationActionAdapter",
    "ToolContext",
    "ToolContextProvider",
    "ToolEventSink",
    "authorized_tool",
    "direct_tool",
    "tool",
]
