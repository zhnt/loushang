"""Composition of Agent hooks contributed by a Product extension runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Protocol, TypeVar, cast

from loushang.agent.tool_output import STRICT_JSON_TOOL_OUTPUT_PROJECTOR
from loushang.agent.types import (
    AfterToolCallContext,
    AfterToolCallResult,
    AgentMessage,
    AgentToolResult,
    BeforeToolCallContext,
    BeforeToolCallResult,
    TransformContextFn,
)
from loushang.ai.types import ToolCall
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.extensions.context import ExtensionContext, SessionActionDecision
from loushang.harness.extensions.routing import (
    ExtensionRoutePlan,
    ExtensionRouter,
    ResolvedExtensionRoute,
    RouteStep,
)
from loushang.harness.extensions.types import (
    BeforeAgentStartResult,
    ContextResult,
    LoadedExtension,
    ToolCallDecision,
    ToolResultDecision,
)

CwdProvider = Callable[[], str]
BeforeToolCallHook = Callable[
    [BeforeToolCallContext, object | None],
    Awaitable[BeforeToolCallResult | None],
]
AfterToolCallHook = Callable[
    [AfterToolCallContext, object | None],
    Awaitable[AfterToolCallResult | None],
]
ContextTransformHook = TransformContextFn
ContextFactory = Callable[[LoadedExtension], ExtensionContext]
RuntimeErrorHandler = Callable[[LoadedExtension, str, Exception], None]
BeforeAgentStartEventFactory = Callable[
    ["BeforeAgentStartState", ResolvedExtensionRoute], object
]
BeforeAgentStartResultCoercer = Callable[[object], BeforeAgentStartResult | None]
SessionDecisionCoercer = Callable[[SessionActionDecision], SessionActionDecision]
T = TypeVar("T", bound=SessionActionDecision)


class ExtensionAgentHookPort(Protocol):
    """Extension callbacks that can participate in an Agent loop."""

    async def emit_context(
        self,
        messages: list[AgentMessage],
        signal: object | None = None,
        *,
        cwd: str = "",
    ) -> list[AgentMessage]: ...

    async def before_tool_call(
        self,
        context: BeforeToolCallContext,
        signal: object | None = None,
    ) -> BeforeToolCallResult | None: ...

    async def after_tool_call(
        self,
        context: AfterToolCallContext,
        signal: object | None = None,
    ) -> AfterToolCallResult | None: ...


class ExtensionHookAgentPort(Protocol):
    """Mutable Agent hook slots used by the extension hook runtime."""

    @property
    def transform_context(self) -> ContextTransformHook | None: ...

    @transform_context.setter
    def transform_context(self, value: ContextTransformHook | None) -> None: ...

    @property
    def before_tool_call(self) -> BeforeToolCallHook | None: ...

    @before_tool_call.setter
    def before_tool_call(self, value: BeforeToolCallHook | None) -> None: ...

    @property
    def after_tool_call(self) -> AfterToolCallHook | None: ...

    @after_tool_call.setter
    def after_tool_call(self, value: AfterToolCallHook | None) -> None: ...


@dataclass
class ExtensionAgentHookRuntime:
    """Install extension context and tool hooks without Product imports."""

    agent: ExtensionHookAgentPort
    extension_runtime: ExtensionAgentHookPort
    get_cwd: CwdProvider

    def install(self) -> None:
        existing_transform = self.agent.transform_context
        existing_before = self.agent.before_tool_call
        existing_after = self.agent.after_tool_call

        async def _transform_context(
            messages: list[AgentMessage],
            signal: object | None = None,
        ) -> list[AgentMessage]:
            current_messages = messages
            if existing_transform is not None:
                current_messages = await existing_transform(current_messages, signal)
            return await self.extension_runtime.emit_context(
                current_messages,
                signal,
                cwd=self.get_cwd(),
            )

        async def _before_tool_call(
            context: BeforeToolCallContext,
            signal: object | None = None,
        ) -> BeforeToolCallResult | None:
            return await compose_before_tool_call_hooks(
                context,
                signal,
                [
                    hook
                    for hook in (
                        existing_before,
                        self.extension_runtime.before_tool_call,
                    )
                    if hook is not None
                ],
            )

        async def _after_tool_call(
            context: AfterToolCallContext,
            signal: object | None = None,
        ) -> AfterToolCallResult | None:
            return await compose_after_tool_call_hooks(
                context,
                signal,
                [
                    hook
                    for hook in (
                        existing_after,
                        self.extension_runtime.after_tool_call,
                    )
                    if hook is not None
                ],
            )

        self.agent.transform_context = _transform_context
        self.agent.before_tool_call = _before_tool_call
        self.agent.after_tool_call = _after_tool_call


@dataclass(frozen=True)
class _BeforeToolState:
    event: BeforeToolCallContext
    changed: bool = False
    result: BeforeToolCallResult | None = None


@dataclass(frozen=True)
class _AfterToolState:
    event: AfterToolCallContext
    changed: bool = False


class ExtensionToolHookDispatcher:
    """Reduce extension tool decisions through an existing route plan.

    This is the product-neutral successor to Coding's ``HookDispatcher``. It
    owns only Agent tool values and extension routing; context and error
    projection remain injected Product ports.
    """

    def __init__(
        self,
        extensions: Sequence[LoadedExtension],
        *,
        context_factory: ContextFactory,
        diagnostics: list[DiagnosticDraft],
        runtime_error_handler: RuntimeErrorHandler | None = None,
        route_plan: ExtensionRoutePlan | None = None,
    ) -> None:
        self._context_factory = context_factory
        self._diagnostics = diagnostics
        plan = route_plan or ExtensionRoutePlan.from_extensions(
            extensions, diagnostics=diagnostics
        )
        self._router = ExtensionRouter(
            plan,
            diagnostics=diagnostics,
            runtime_error_handler=runtime_error_handler,
            include_route_id_in_error_metadata=False,
            include_provenance_in_error_metadata=False,
        )

    async def before_tool_call(
        self,
        event: BeforeToolCallContext,
        signal: object | None = None,
    ) -> BeforeToolCallResult | None:
        del signal

        def reducer(
            state: _BeforeToolState,
            decision: object,
            route: ResolvedExtensionRoute,
        ) -> RouteStep[_BeforeToolState]:
            if not isinstance(decision, ToolCallDecision):
                self._diagnostics.append(
                    DiagnosticDraft(
                        code="invalid_extension_tool_call_decision",
                        message="tool_call hooks must return ToolCallDecision or None.",
                        source_path=route.extension.source_path,
                    )
                )
                return RouteStep(state)
            if decision.diagnostics:
                self._diagnostics.extend(decision.diagnostics)
            current_event = state.event
            tool_name = decision.tool_name or current_event.tool_call.name
            arguments = cast(
                dict[str, Any],
                decision.arguments
                if decision.arguments is not None
                else current_event.args,
            )
            changed = state.changed
            if tool_name != current_event.tool_call.name or arguments != current_event.args:
                changed = True
                current_event = replace(
                    current_event,
                    tool_call=ToolCall(
                        type="toolCall",
                        id=current_event.tool_call.id,
                        name=tool_name,
                        arguments=arguments,
                        thought_signature=current_event.tool_call.thought_signature,
                    ),
                    args=arguments,
                )
            result = (
                BeforeToolCallResult(
                    block=True,
                    reason=decision.reason,
                    tool_name=current_event.tool_call.name if changed else None,
                    arguments=cast(dict[str, Any], current_event.args)
                    if changed
                    else None,
                )
                if decision.block
                else None
            )
            return RouteStep(
                _BeforeToolState(event=current_event, changed=changed, result=result),
                stop=result is not None,
            )

        state = (
            await self._router.intercept(
                "tool_call",
                _BeforeToolState(event=event),
                event_factory=lambda state, _route: state.event,
                reducer=reducer,
                context_factory=self._context_factory,
            )
        ).state
        if state.result is not None:
            return state.result
        if not state.changed:
            return None
        return BeforeToolCallResult(
            tool_name=state.event.tool_call.name,
            arguments=cast(dict[str, Any], state.event.args),
        )

    async def after_tool_call(
        self,
        event: AfterToolCallContext,
        signal: object | None = None,
    ) -> AfterToolCallResult | None:
        del signal

        def reducer(
            state: _AfterToolState,
            decision: object,
            route: ResolvedExtensionRoute,
        ) -> RouteStep[_AfterToolState]:
            if not isinstance(decision, ToolResultDecision):
                self._diagnostics.append(
                    DiagnosticDraft(
                        code="invalid_extension_tool_result_decision",
                        message="tool_result hooks must return ToolResultDecision or None.",
                        source_path=route.extension.source_path,
                    )
                )
                return RouteStep(state)
            if decision.diagnostics:
                self._diagnostics.extend(decision.diagnostics)
            if decision.result is None:
                return RouteStep(state)
            if not isinstance(decision.result, AgentToolResult):
                self._diagnostics.append(
                    DiagnosticDraft(
                        code="invalid_extension_tool_result_decision",
                        message=(
                            "tool_result decisions must return AgentToolResult "
                            "instances when overriding results."
                        ),
                        source_path=route.extension.source_path,
                    )
                )
                return RouteStep(state)
            return RouteStep(
                _AfterToolState(
                    event=replace(
                        state.event,
                        result=decision.result,
                        hook_details=decision.result.hook_details(),
                    ),
                    changed=True,
                )
            )

        state = (
            await self._router.reduce(
                "tool_result",
                _AfterToolState(event=event),
                event_factory=lambda state, _route: state.event,
                reducer=reducer,
                context_factory=self._context_factory,
            )
        ).state
        if not state.changed:
            return None
        return AfterToolCallResult(
            content=state.event.result.content,
            details=state.event.result.details,
            terminate=state.event.result.terminate,
            projector=state.event.result.projector,
        )


@dataclass(frozen=True)
class BeforeAgentStartState:
    """Shared reduction state for a before-agent-start hook route."""

    system_prompt: str
    extra_messages: tuple[object, ...] = ()
    diagnostics: tuple[DiagnosticDraft, ...] = ()
    system_prompt_changed: bool = False


@dataclass
class ContextHookEvent:
    """Neutral context-hook event; products may project their own aliases."""

    messages: list[AgentMessage]


class ExtensionPromptHookDispatcher:
    """Run shared context and before-agent-start hook reductions."""

    def __init__(
        self,
        router: ExtensionRouter,
        *,
        diagnostics: list[DiagnosticDraft],
    ) -> None:
        self._router = router
        self._diagnostics = diagnostics

    async def transform_context(
        self,
        messages: list[AgentMessage],
        *,
        context_factory: ContextFactory,
    ) -> list[AgentMessage]:
        def reducer(
            state: list[AgentMessage],
            result: object,
            route: ResolvedExtensionRoute,
        ) -> RouteStep[list[AgentMessage]]:
            if not isinstance(result, ContextResult):
                self._diagnostics.append(
                    DiagnosticDraft(
                        code="invalid_extension_context_result",
                        message="context hooks must return ContextResult or None.",
                        source_path=route.extension.source_path,
                    )
                )
                return RouteStep(state)
            if result.diagnostics:
                self._diagnostics.extend(result.diagnostics)
            return RouteStep(
                cast(list[AgentMessage], result.messages)
                if result.messages is not None
                else state
            )

        return (
            await self._router.reduce(
                "context",
                deepcopy(messages),
                event_factory=lambda state, _route: ContextHookEvent(messages=state),
                reducer=reducer,
                context_factory=context_factory,
            )
        ).state

    async def reduce_before_agent_start(
        self,
        *,
        system_prompt: str,
        context_factory: ContextFactory,
        event_factory: BeforeAgentStartEventFactory,
        result_coercer: BeforeAgentStartResultCoercer,
    ) -> BeforeAgentStartResult | None:
        def reducer(
            state: BeforeAgentStartState,
            result: object,
            _route: ResolvedExtensionRoute,
        ) -> RouteStep[BeforeAgentStartState]:
            coerced = result_coercer(result)
            if coerced is None:
                return RouteStep(state)
            next_system_prompt = coerced.system_prompt
            if next_system_prompt is None and coerced.system_prompt_append:
                next_system_prompt = f"{state.system_prompt}\n\n{coerced.system_prompt_append}"
            return RouteStep(
                BeforeAgentStartState(
                    system_prompt=(
                        next_system_prompt
                        if next_system_prompt is not None
                        else state.system_prompt
                    ),
                    extra_messages=(*state.extra_messages, *coerced.extra_messages),
                    diagnostics=(*state.diagnostics, *coerced.diagnostics),
                    system_prompt_changed=(
                        state.system_prompt_changed or next_system_prompt is not None
                    ),
                )
            )

        state = (
            await self._router.reduce(
                "before_agent_start",
                BeforeAgentStartState(system_prompt=system_prompt),
                event_factory=event_factory,
                reducer=reducer,
                context_factory=context_factory,
            )
        ).state
        diagnostics = list(state.diagnostics)
        if diagnostics:
            self._diagnostics.extend(diagnostics)
        if not state.extra_messages and not state.system_prompt_changed and not diagnostics:
            return None
        return BeforeAgentStartResult(
            system_prompt=state.system_prompt if state.system_prompt_changed else None,
            extra_messages=list(state.extra_messages),
            diagnostics=diagnostics,
        )


class ExtensionSessionHookDispatcher:
    """Observe and reduce Product session-hook values through one route plan."""

    def __init__(
        self,
        router: ExtensionRouter,
        *,
        diagnostics: list[DiagnosticDraft],
    ) -> None:
        self._router = router
        self._diagnostics = diagnostics

    async def observe_session(
        self,
        event_name: str,
        event: object,
        *,
        context_factory: ContextFactory,
    ) -> None:
        await self._router.observe(
            event_name,
            event,
            context_factory=context_factory,
        )

    async def reduce_session_decision(
        self,
        event_name: str,
        event: object,
        *,
        context_factory: ContextFactory,
        result_type: type[T],
        decision_coercer: Callable[[SessionActionDecision], T] | None = None,
    ) -> T | None:
        def reducer(
            state: T | None,
            result: object,
            route: ResolvedExtensionRoute,
        ) -> RouteStep[T | None]:
            if not isinstance(result, SessionActionDecision):
                self._diagnostics.append(
                    DiagnosticDraft(
                        code=f"invalid_extension_{event_name}_decision",
                        message=(
                            f"{event_name} hooks must return "
                            f"{result_type.__name__} or None."
                        ),
                        source_path=route.extension.source_path,
                    )
                )
                return RouteStep(state)
            if result.diagnostics:
                self._diagnostics.extend(result.diagnostics)
            if isinstance(result, result_type):
                return RouteStep(result)
            if decision_coercer is None:
                self._diagnostics.append(
                    DiagnosticDraft(
                        code=f"invalid_extension_{event_name}_decision",
                        message=(
                            f"{event_name} hooks must return "
                            f"{result_type.__name__} or None."
                        ),
                        source_path=route.extension.source_path,
                    )
                )
                return RouteStep(state)
            return RouteStep(decision_coercer(result))

        return (
            await self._router.reduce(
                event_name,
                None,
                event_factory=lambda _state, _route: event,
                reducer=reducer,
                context_factory=context_factory,
            )
        ).state


async def compose_before_tool_call_hooks(
    context: Any,
    signal: object | None,
    hooks: Sequence[BeforeToolCallHook],
) -> BeforeToolCallResult | None:
    """Run before hooks in order while preserving prior modifications."""

    current_context = context
    changed = False

    for hook in hooks:
        result = await hook(current_context, signal)
        if result is None:
            continue
        if result.tool_name is not None or result.arguments is not None:
            changed = True
            current_context = _apply_before_tool_call_result(current_context, result)
        if result.block:
            return BeforeToolCallResult(
                block=True,
                reason=result.reason,
                tool_name=current_context.tool_call.name if changed else None,
                arguments=current_context.args if changed else None,
            )

    if not changed:
        return None
    return BeforeToolCallResult(
        tool_name=current_context.tool_call.name,
        arguments=current_context.args,
    )


def _apply_before_tool_call_result(context: Any, result: BeforeToolCallResult):
    tool_name = result.tool_name or context.tool_call.name
    arguments = result.arguments if result.arguments is not None else context.args
    return replace(
        context,
        tool_call=ToolCall(
            type="toolCall",
            id=context.tool_call.id,
            name=tool_name,
            arguments=arguments,
            thought_signature=context.tool_call.thought_signature,
        ),
        args=arguments,
    )


async def compose_after_tool_call_hooks(
    context: Any,
    signal: object | None,
    hooks: Sequence[AfterToolCallHook],
) -> AfterToolCallResult | None:
    """Run after hooks in order while preserving result projection semantics."""

    current_context = context
    changed = False

    for hook in hooks:
        result = await hook(current_context, signal)
        if result is None:
            continue
        next_result = current_context.result
        details_provided = result.details_provided
        projection_changed = details_provided or result.projector is not None
        if (
            result.content is not None
            or details_provided
            or result.terminate is not None
            or result.projector is not None
        ):
            changed = True
            next_result = replace(
                current_context.result,
                content=result.content
                if result.content is not None
                else current_context.result.content,
                details=result.details
                if details_provided
                else current_context.result.details,
                terminate=result.terminate
                if result.terminate is not None
                else current_context.result.terminate,
                projector=(
                    result.projector
                    if result.projector is not None
                    else (
                        current_context.result.projector
                        if not details_provided
                        else STRICT_JSON_TOOL_OUTPUT_PROJECTOR
                    )
                ),
            )
        next_is_error = (
            result.is_error if result.is_error is not None else current_context.is_error
        )
        if next_is_error != current_context.is_error:
            changed = True
        current_context = replace(
            current_context,
            result=next_result,
            is_error=next_is_error,
            hook_details=(
                next_result.hook_details()
                if projection_changed
                else current_context.hook_details
            ),
        )

    if not changed:
        return None
    return AfterToolCallResult(
        content=current_context.result.content,
        details=current_context.result.details,
        is_error=current_context.is_error,
        terminate=current_context.result.terminate,
        projector=current_context.result.projector,
    )


__all__ = [
    "ExtensionAgentHookRuntime",
    "ExtensionAgentHookPort",
    "compose_after_tool_call_hooks",
    "compose_before_tool_call_hooks",
    "BeforeAgentStartState",
    "ContextHookEvent",
    "ExtensionPromptHookDispatcher",
    "ExtensionSessionHookDispatcher",
    "ExtensionToolHookDispatcher",
]
