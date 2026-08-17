"""Hosted execution bindings for model-visible Harness tools."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol

from loushang.agent.types import AgentToolResult
from loushang.ai.types import ToolCall
from loushang.harness.authorization import EffectiveExecutionProfile
from loushang.harness.effects import ToolEffect
from loushang.harness.policy import ToolPolicySubject

ToolUpdateCallback = Callable[[object], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class ToolCallContext:
    """Non-model invocation state carried alongside one prepared tool call."""

    tool_call_id: str
    cwd: str | None = None
    diagnostics: object | None = None
    signal: object | None = None
    model: object | None = None
    event_sink: object | None = None
    exec_service: object | None = None
    on_update: ToolUpdateCallback | None = None
    operation_bindings: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def direct(self) -> DirectToolContext:
        return DirectToolContext(
            tool_call_id=self.tool_call_id,
            cwd=self.cwd,
            diagnostics=self.diagnostics,
            signal=self.signal,
            model=self.model,
            on_update=self.on_update,
        )

    def authorized(self) -> AuthorizedToolContext:
        return AuthorizedToolContext(
            tool_call_id=self.tool_call_id,
            cwd=self.cwd,
            diagnostics=self.diagnostics,
            signal=self.signal,
            model=self.model,
            event_sink=self.event_sink,
            exec_service=self.exec_service,
            on_update=self.on_update,
            operation_bindings=MappingProxyType(dict(self.operation_bindings)),
        )


@dataclass(frozen=True, slots=True)
class DirectToolContext:
    """Invocation state that deliberately excludes protected-resource ports."""

    tool_call_id: str
    cwd: str | None = None
    diagnostics: object | None = None
    signal: object | None = None
    model: object | None = None
    on_update: ToolUpdateCallback | None = None


@dataclass(frozen=True, slots=True)
class AuthorizedToolContext:
    """Invocation state exposed only after the authorization route is selected."""

    tool_call_id: str
    cwd: str | None = None
    diagnostics: object | None = None
    signal: object | None = None
    model: object | None = None
    event_sink: object | None = None
    exec_service: object | None = None
    on_update: ToolUpdateCallback | None = None
    operation_bindings: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True, slots=True)
class PreparedToolAction:
    """Immutable-input candidate produced before Policy and Approval."""

    tool_name: str
    authorization_arguments: Mapping[str, Any]
    execution_arguments: Mapping[str, Any]
    cwd: str | None
    effects: tuple[ToolEffect, ...] = ()
    policy_subject: ToolPolicySubject | None = None
    execution_environment: object | None = None


@dataclass(frozen=True, slots=True)
class AuthorizedToolAction:
    """One frozen action admitted for exactly one handler invocation."""

    tool_name: str
    authorization_arguments: Mapping[str, Any]
    execution_arguments: Mapping[str, Any]
    cwd: str | None
    fingerprint: str
    effects: tuple[ToolEffect, ...] = ()
    actor_id: str = "root"
    execution_profile: EffectiveExecutionProfile | None = None
    policy_code: str | None = None
    approval_action_id: str | None = None
    audit_details: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({}),
        repr=False,
    )


class DirectToolHandler(Protocol):
    async def __call__(
        self,
        call: ToolCall,
        context: DirectToolContext,
    ) -> AgentToolResult[Any]: ...


LegacyToolExecute = Callable[
    [str, dict[str, Any], object | None, object | None],
    Awaitable[AgentToolResult[Any]],
]


@dataclass(frozen=True, slots=True)
class _CallableDirectHandler:
    execute: LegacyToolExecute

    async def __call__(
        self,
        call: ToolCall,
        context: DirectToolContext,
    ) -> AgentToolResult[Any]:
        return await self.execute(
            call.id,
            dict(call.arguments),
            context.signal,
            context.on_update,
        )


def direct_execution(execute: LegacyToolExecute) -> DirectExecution:
    """Explicitly bind an AgentTool-shaped callable to the direct route."""

    if not callable(execute):
        raise TypeError("direct execution handler must be callable")
    return DirectExecution(_CallableDirectHandler(execute))


class ToolActionAdapter(Protocol):
    def prepare(
        self,
        call: ToolCall,
        context: ToolCallContext,
    ) -> PreparedToolAction: ...


@dataclass(frozen=True, slots=True)
class CallableToolActionAdapter:
    prepare_action: Callable[[ToolCall, ToolCallContext], PreparedToolAction]

    def prepare(
        self,
        call: ToolCall,
        context: ToolCallContext,
    ) -> PreparedToolAction:
        return self.prepare_action(call, context)


class AuthorizedToolHandler(Protocol):
    async def __call__(
        self,
        action: AuthorizedToolAction,
        context: AuthorizedToolContext,
    ) -> AgentToolResult[Any]: ...


@dataclass(frozen=True, slots=True)
class DirectExecution:
    handler: DirectToolHandler


@dataclass(frozen=True, slots=True)
class AuthorizedExecution:
    action_adapter: ToolActionAdapter
    handler: AuthorizedToolHandler


ExecutionBinding = DirectExecution | AuthorizedExecution


class _ExecutableToolDefinition(Protocol):
    """Structural port consumed by the execution host."""

    @property
    def name(self) -> str: ...

    @property
    def execution(self) -> ExecutionBinding: ...


class ToolAuthorizationGateway(Protocol):
    async def execute(
        self,
        prepared: PreparedToolAction,
        handler: AuthorizedToolHandler,
        context: AuthorizedToolContext,
    ) -> AgentToolResult[Any]: ...


class ToolExecutionHost:
    """Dispatch final prepared calls through one explicit execution binding."""

    def __init__(self, gateway: ToolAuthorizationGateway | None = None) -> None:
        self._gateway = gateway

    async def dispatch(
        self,
        definition: _ExecutableToolDefinition,
        call: ToolCall,
        context: ToolCallContext,
    ) -> AgentToolResult[Any]:
        if context.signal is not None and getattr(context.signal, "aborted", False):
            raise RuntimeError("Operation aborted")
        binding = definition.execution
        if isinstance(binding, DirectExecution):
            return await binding.handler(call, context.direct())
        if isinstance(binding, AuthorizedExecution):
            if self._gateway is None:
                raise RuntimeError(
                    f"authorized tool {definition.name!r} requires a session gateway"
                )
            prepared = binding.action_adapter.prepare(call, context)
            if prepared.tool_name != definition.name:
                raise ValueError(
                    "authorized action tool name must match its ToolDefinition"
                )
            return await self._gateway.execute(
                prepared,
                binding.handler,
                context.authorized(),
            )
        raise TypeError(f"unsupported execution binding: {type(binding).__name__}")


__all__ = [
    "AuthorizedExecution",
    "AuthorizedToolAction",
    "AuthorizedToolContext",
    "AuthorizedToolHandler",
    "CallableToolActionAdapter",
    "DirectExecution",
    "DirectToolContext",
    "DirectToolHandler",
    "ExecutionBinding",
    "PreparedToolAction",
    "ToolActionAdapter",
    "ToolAuthorizationGateway",
    "ToolCallContext",
    "ToolExecutionHost",
    "direct_execution",
]
