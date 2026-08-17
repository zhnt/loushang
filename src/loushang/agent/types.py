from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import cached_property
from typing import (
    Any,
    Generic,
    Literal,
    NotRequired,
    Protocol,
    TypeAlias,
    TypedDict,
    TypeVar,
    cast,
    runtime_checkable,
)

from loushang.agent.tool_output import (
    STRICT_JSON_TOOL_OUTPUT_PROJECTOR,
    FunctionalToolOutputProjector,
    ToolOutputPreviewPolicy,
    ToolOutputProjectionError,
    ToolOutputProjector,
    bound_tool_output_preview,
)
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.json_codec import deserialize_content_part, serialize_content_part
from loushang.ai.model import Model
from loushang.ai.options import (
    CallOptions,
    ReasoningOptions,
)
from loushang.ai.types import (
    AssistantMessage,
    AssistantMessageEvent,
    Context,
    ImagePart,
    Message,
    TextPart,
    ToolCall,
    ToolResultMessage,
    Usage,
)
from loushang.foundation.json import JSONValue, require_json_value

TDetails = TypeVar("TDetails")


class _AfterToolCallDetailsUnset:
    __slots__ = ()


_AFTER_TOOL_CALL_DETAILS_UNSET = _AfterToolCallDetailsUnset()

ToolExecutionMode: TypeAlias = Literal["sequential", "parallel"]
ThinkingLevel: TypeAlias = Literal["off", "minimal", "low", "medium", "high", "xhigh"]
AgentToolCall: TypeAlias = ToolCall


class AgentThinkingBudgetMap(TypedDict, total=False):
    minimal: int
    low: int
    medium: int
    high: int


@dataclass(frozen=True)
class BeforeToolCallResult:
    block: bool | None = None
    reason: str | None = None
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None


@dataclass(frozen=True, init=False)
class AfterToolCallResult:
    content: list[TextPart | ImagePart] | None = None
    details: object | None = None
    is_error: bool | None = None
    terminate: bool | None = None
    projector: ToolOutputProjector[Any] | None = None
    _details_provided_state: bool = field(
        default=False,
        repr=False,
        compare=False,
    )

    def __init__(
        self,
        content: list[TextPart | ImagePart] | None = None,
        details: object | None = _AFTER_TOOL_CALL_DETAILS_UNSET,
        is_error: bool | None = None,
        terminate: bool | None = None,
        projector: ToolOutputProjector[Any] | None = None,
        _details_provided_state: bool | None = None,
    ) -> None:
        _require_optional_exact_bool(is_error, name="is_error")
        _require_optional_exact_bool(terminate, name="terminate")
        _require_optional_exact_bool(
            _details_provided_state,
            name="_details_provided_state",
        )
        if details is _AFTER_TOOL_CALL_DETAILS_UNSET:
            details_provided = False
        elif details is None and _details_provided_state is not None:
            details_provided = _details_provided_state
        else:
            details_provided = True
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "details", details if details_provided else None)
        object.__setattr__(self, "is_error", is_error)
        object.__setattr__(self, "terminate", terminate)
        object.__setattr__(self, "projector", projector)
        object.__setattr__(self, "_details_provided_state", details_provided)

    @property
    def details_provided(self) -> bool:
        return self._details_provided_state


def _require_optional_exact_bool(value: object, *, name: str) -> None:
    if value is not None and type(value) is not bool:
        raise TypeError(f"AfterToolCallResult.{name} must be bool or None")


class CustomAgentMessage:
    """
    Python equivalent of pi-agent's extensible CustomAgentMessages surface.

    Apps should subclass this base type to introduce custom agent-level messages.
    """


AgentMessage: TypeAlias = Message | CustomAgentMessage


@dataclass(frozen=True)
class AgentToolResult(Generic[TDetails]):
    content: list[TextPart | ImagePart]
    details: TDetails
    terminate: bool = False
    projector: ToolOutputProjector[TDetails] = field(
        default=cast(
            ToolOutputProjector[TDetails],
            STRICT_JSON_TOOL_OUTPUT_PROJECTOR,
        ),
        compare=False,
        repr=False,
    )

    def transcript_details(self) -> JSONValue:
        return require_json_value(
            self._transcript_projection,
            name="tool_output.details",
        )

    def event_details(self) -> JSONValue:
        return require_json_value(
            self._event_projection,
            name="tool_output.details",
        )

    def hook_details(self) -> JSONValue:
        return require_json_value(
            self._hook_projection,
            name="tool_output.details",
        )

    @cached_property
    def _transcript_projection(self) -> JSONValue:
        return _snapshot_tool_output_projection(
            lambda: self.projector.to_transcript_details(self.details),
            target="transcript",
        )

    @cached_property
    def _event_projection(self) -> JSONValue:
        return _snapshot_tool_output_projection(
            lambda: self.projector.to_event_details(self.details),
            target="event",
        )

    @cached_property
    def _hook_projection(self) -> JSONValue:
        return _snapshot_tool_output_projection(
            lambda: self.projector.to_hook_details(self.details),
            target="hook",
        )

    def log_preview(
        self,
        policy: ToolOutputPreviewPolicy = ToolOutputPreviewPolicy(),
    ) -> str:
        return bound_tool_output_preview(
            self.projector.log_preview(self.details, policy),
            policy,
        )

    def for_presentation(self) -> AgentToolResult[JSONValue]:
        terminate = _require_tool_output_terminate(
            self.terminate,
            target="transcript",
        )
        return AgentToolResult(
            content=_snapshot_tool_output_content(self.content, target="transcript"),
            details=self.transcript_details(),
            terminate=terminate,
        )

    def for_event(self) -> AgentToolResult[JSONValue]:
        terminate = _require_tool_output_terminate(
            self.terminate,
            target="event",
        )
        event_projection = self.event_details()
        return AgentToolResult(
            content=_snapshot_tool_output_content(self.content, target="event"),
            details=require_json_value(event_projection),
            terminate=terminate,
            projector=FunctionalToolOutputProjector(
                transcript=lambda details: self.transcript_details(),
                event=lambda details: event_projection,
                hook=lambda details: event_projection,
            ),
        )

    def for_hook(self) -> AgentToolResult[JSONValue]:
        terminate = _require_tool_output_terminate(
            self.terminate,
            target="hook",
        )
        return AgentToolResult(
            content=_snapshot_tool_output_content(self.content, target="hook"),
            details=self.hook_details(),
            terminate=terminate,
        )


def _require_tool_output_terminate(value: object, *, target: str) -> bool:
    if type(value) is not bool:
        raise ToolOutputProjectionError(
            target,
            "Tool output terminate must be a boolean",
            path="tool_output.terminate",
            value_type=type(value).__name__,
        )
    return cast(bool, value)


def _snapshot_tool_output_content(
    content: list[TextPart | ImagePart],
    *,
    target: str,
) -> list[TextPart | ImagePart]:
    if type(content) is not list:
        raise ToolOutputProjectionError(
            target,
            "Tool output content must be a list",
            path="tool_output.content",
            value_type=type(content).__name__,
        )
    snapshot: list[TextPart | ImagePart] = []
    for index, part in enumerate(content):
        path = f"tool_output.content[{index}]"
        try:
            _validate_tool_output_content_part(part, target=target, path=path)
            payload = require_json_value(serialize_content_part(part), name=path)
            if not isinstance(payload, dict):
                raise TypeError("Serialized content parts must be JSON objects")
            restored = deserialize_content_part(payload)
            if type(restored) not in (TextPart, ImagePart):
                raise TypeError("Tool result content must contain text or image parts")
        except ToolOutputProjectionError:
            raise
        except Exception as exc:
            error_path = getattr(exc, "path", path)
            value_type = getattr(exc, "value_type", type(part).__name__)
            raise ToolOutputProjectionError(
                target,
                f"Tool output {target} projection failed at {error_path}: {value_type}",
                path=error_path,
                value_type=value_type,
            ) from exc
        snapshot.append(cast(TextPart | ImagePart, restored))
    return snapshot


def _validate_tool_output_content_part(
    part: object,
    *,
    target: str,
    path: str,
) -> None:
    if type(part) is TextPart:
        text_part = cast(TextPart, part)
        _require_content_literal(
            text_part.type,
            "text",
            target=target,
            path=f"{path}.type",
        )
        _require_content_string(text_part.text, target=target, path=f"{path}.text")
        signature = text_part.text_signature
        if (
            signature is not None
            and type(signature) is not str
            and type(signature) is not dict
        ):
            raise ToolOutputProjectionError(
                target,
                "Tool output textSignature must be a string, object, or null",
                path=f"{path}.textSignature",
                value_type=type(signature).__name__,
            )
        return
    if type(part) is ImagePart:
        image_part = cast(ImagePart, part)
        _require_content_literal(
            image_part.type,
            "image",
            target=target,
            path=f"{path}.type",
        )
        _require_content_string(
            image_part.data,
            target=target,
            path=f"{path}.data",
        )
        _require_content_string(
            image_part.mime_type,
            target=target,
            path=f"{path}.mimeType",
        )
        return
    raise ToolOutputProjectionError(
        target,
        "Tool result content must contain exact TextPart or ImagePart values",
        path=path,
        value_type=type(part).__name__,
    )


def _require_content_literal(
    value: object,
    expected: str,
    *,
    target: str,
    path: str,
) -> None:
    if type(value) is not str or value != expected:
        raise ToolOutputProjectionError(
            target,
            f"Tool output content type must be {expected!r}",
            path=path,
            value_type=type(value).__name__,
        )


def _require_content_string(value: object, *, target: str, path: str) -> None:
    if type(value) is not str:
        raise ToolOutputProjectionError(
            target,
            "Tool output content field must be a string",
            path=path,
            value_type=type(value).__name__,
        )


def _snapshot_tool_output_projection(
    project: Callable[[], object],
    *,
    target: str,
) -> JSONValue:
    try:
        return require_json_value(project(), name="tool_output.details")
    except ToolOutputProjectionError as exc:
        error_target = exc.target if exc.target == target else target
        raise ToolOutputProjectionError(
            error_target,
            str(exc),
            path=exc.path,
            value_type=exc.value_type,
        ) from exc
    except Exception as exc:
        path = getattr(exc, "path", "tool_output.details")
        value_type = getattr(exc, "value_type", type(exc).__name__)
        raise ToolOutputProjectionError(
            target,
            f"Tool output {target} projection failed at {path}: {value_type}",
            path=path,
            value_type=value_type,
        ) from exc


class AgentToolUpdateCallback(Protocol[TDetails]):
    def __call__(
        self, partial_result: AgentToolResult[TDetails]
    ) -> Awaitable[None] | None: ...


@runtime_checkable
class StreamFn(Protocol):
    def __call__(
        self,
        model: Model,
        context: Context,
        options: CallOptions | None = None,
    ) -> AssistantMessageEventStream | Awaitable[AssistantMessageEventStream]: ...


class ConvertToLlmFn(Protocol):
    def __call__(
        self, messages: list[AgentMessage]
    ) -> list[Message] | Awaitable[list[Message]]: ...


class TransformContextFn(Protocol):
    def __call__(
        self, messages: list[AgentMessage], signal: object | None = None
    ) -> Awaitable[list[AgentMessage]]: ...


@dataclass(frozen=True)
class ModelCallPreparation:
    """Final Agent-level model context awaiting caller-owned options binding."""

    purpose: str
    sequence: int
    model: Model
    context: Context
    options: CallOptions

    def __post_init__(self) -> None:
        if not isinstance(self.purpose, str) or not self.purpose.strip():
            raise ValueError("model call purpose must be a non-empty string")
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 1
        ):
            raise ValueError("model call sequence must be a positive integer")


class PrepareModelCallFn(Protocol):
    def __call__(
        self,
        preparation: ModelCallPreparation,
    ) -> CallOptions | Awaitable[CallOptions]: ...


@runtime_checkable
class AgentTool(Protocol[TDetails]):
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def parameters(self) -> dict[str, Any]: ...

    @property
    def label(self) -> str: ...

    @property
    def prepare_arguments(self) -> Callable[[object], dict[str, Any]] | None: ...

    @property
    def execution_mode(self) -> ToolExecutionMode: ...

    def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: object | None = None,
        on_update: AgentToolUpdateCallback[TDetails] | None = None,
    ) -> Awaitable[AgentToolResult[TDetails]]: ...


class _AgentToolWithDefaultExecutionMode(Generic[TDetails]):
    execution_mode: ToolExecutionMode = "parallel"

    def __init__(self, tool: object) -> None:
        self._tool = tool

    @property
    def name(self) -> str:
        return cast(str, getattr(self._tool, "name"))

    @property
    def description(self) -> str:
        return cast(str, getattr(self._tool, "description"))

    @property
    def parameters(self) -> dict[str, Any]:
        return cast(dict[str, Any], getattr(self._tool, "parameters"))

    @property
    def label(self) -> str:
        return cast(str, getattr(self._tool, "label"))

    @property
    def prepare_arguments(self) -> Callable[[object], dict[str, Any]] | None:
        return cast(
            Callable[[object], dict[str, Any]] | None,
            getattr(self._tool, "prepare_arguments", None),
        )

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: object | None = None,
        on_update: AgentToolUpdateCallback[TDetails] | None = None,
    ) -> AgentToolResult[TDetails]:
        execute = cast(AgentTool[TDetails], self._tool).execute
        return await execute(tool_call_id, params, signal, on_update)


def is_agent_tool_like(tool: object) -> bool:
    return all(
        hasattr(tool, field_name)
        for field_name in ("name", "description", "parameters", "label")
    ) and callable(getattr(tool, "execute", None))


def ensure_agent_tool(tool: AgentTool[TDetails] | object) -> AgentTool[Any]:
    if isinstance(tool, AgentTool):
        return tool
    if is_agent_tool_like(tool):
        return _AgentToolWithDefaultExecutionMode(tool)
    raise TypeError(
        "Agent tools must define name, description, parameters, label, execute, and optional execution_mode"
    )


def normalize_agent_tools(
    tools: list[AgentTool[Any]] | None,
) -> list[AgentTool[Any]] | None:
    if tools is None:
        return None
    return [
        ensure_agent_tool(tool)
        if is_agent_tool_like(tool)
        else cast(AgentTool[Any], tool)
        for tool in tools
    ]


@dataclass(frozen=True)
class AgentContext:
    system_prompt: str
    messages: list[AgentMessage] = field(default_factory=list)
    tools: list[AgentTool[Any]] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tools", normalize_agent_tools(self.tools))


@dataclass(frozen=True)
class BeforeToolCallContext:
    assistant_message: AssistantMessage
    tool_call: AgentToolCall
    args: object
    context: AgentContext


@dataclass(frozen=True)
class AfterToolCallContext:
    assistant_message: AssistantMessage
    tool_call: AgentToolCall
    args: object
    result: AgentToolResult[Any]
    is_error: bool
    context: AgentContext
    hook_details: JSONValue = None


@dataclass(frozen=True, kw_only=True)
class AgentLoopConfig:
    model: Model
    convert_to_llm: ConvertToLlmFn
    call_options: CallOptions = field(default_factory=CallOptions)
    transform_context: TransformContextFn | None = None
    get_mailbox_messages: Callable[[], Awaitable[list[AgentMessage]]] | None = None
    get_steering_messages: Callable[[], Awaitable[list[AgentMessage]]] | None = None
    get_follow_up_messages: Callable[[], Awaitable[list[AgentMessage]]] | None = None
    tool_execution: ToolExecutionMode = "parallel"
    before_tool_call: (
        Callable[
            [BeforeToolCallContext, object | None],
            Awaitable[BeforeToolCallResult | None],
        ]
        | None
    ) = None
    after_tool_call: (
        Callable[
            [AfterToolCallContext, object | None], Awaitable[AfterToolCallResult | None]
        ]
        | None
    ) = None
    prepare_model_call: PrepareModelCallFn | None = None
    require_prepared_request_conformance: bool = False


class AgentState:
    """
    Mutable runtime state for Agent.

    Contract for `messages` and `tools`:
    - getters return the live internal lists
    - whole-list replacement must go through `set_messages()` / `set_tools()`
    - `set_*()` copies the top-level list
    - incremental mutations on the returned lists (for example `append()` or `clear()`)
      intentionally mutate the current agent state
    """

    def __init__(
        self,
        system_prompt: str,
        model: Model,
        thinking_level: ThinkingLevel,
        tools: list[AgentTool[Any]] | None = None,
        messages: list[AgentMessage] | None = None,
        is_streaming: bool = False,
        streaming_message: AgentMessage | None = None,
        pending_tool_calls: set[str] | None = None,
        error_message: str | None = None,
    ) -> None:
        self.system_prompt = system_prompt
        self.model = model
        self.thinking_level = thinking_level
        self._tools = list(normalize_agent_tools(tools) or [])
        self._messages = list(messages or [])
        self.is_streaming = is_streaming
        self.streaming_message = streaming_message
        self.pending_tool_calls = set(pending_tool_calls or set())
        self.error_message = error_message

    @property
    def tools(self) -> list[AgentTool[Any]]:
        return self._tools

    @property
    def messages(self) -> list[AgentMessage]:
        return self._messages

    def set_tools(self, tools: list[AgentTool[Any]]) -> None:
        """Replace the tools list, copying the top-level container."""
        self._tools = list(normalize_agent_tools(tools) or [])

    def set_messages(self, messages: list[AgentMessage]) -> None:
        """Replace the messages list, copying the top-level container."""
        self._messages = list(messages)


@dataclass(frozen=True)
class AgentOptions:
    initial_state: AgentState | dict[str, Any] | object | None = None
    convert_to_llm: ConvertToLlmFn | None = None
    transform_context: TransformContextFn | None = None
    stream_fn: StreamFn | None = None
    call_options: CallOptions | None = None
    before_tool_call: (
        Callable[
            [BeforeToolCallContext, object | None],
            Awaitable[BeforeToolCallResult | None],
        ]
        | None
    ) = None
    after_tool_call: (
        Callable[
            [AfterToolCallContext, object | None], Awaitable[AfterToolCallResult | None]
        ]
        | None
    ) = None
    steering_mode: Literal["all", "one-at-a-time"] = "one-at-a-time"
    follow_up_mode: Literal["all", "one-at-a-time"] = "one-at-a-time"
    session_id: str | None = None
    thinking_budgets: AgentThinkingBudgetMap | None = None
    max_retry_delay_ms: int | None = None
    tool_execution: ToolExecutionMode = "parallel"
    prepare_model_call: PrepareModelCallFn | None = None


class AgentStartEvent(TypedDict):
    type: Literal["agent_start"]


class AgentEndEvent(TypedDict):
    type: Literal["agent_end"]
    messages: list[AgentMessage]


class TurnStartEvent(TypedDict):
    type: Literal["turn_start"]


class TurnEndEvent(TypedDict):
    type: Literal["turn_end"]
    message: AgentMessage
    tool_results: list[ToolResultMessage]


class MessageStartEvent(TypedDict):
    type: Literal["message_start"]
    message: AgentMessage


class MessageUpdateEvent(TypedDict):
    type: Literal["message_update"]
    message: AgentMessage
    assistant_message_event: AssistantMessageEvent


class MessageEndEvent(TypedDict):
    type: Literal["message_end"]
    message: AgentMessage


class ToolExecutionStartEvent(TypedDict):
    type: Literal["tool_execution_start"]
    tool_call_id: str
    tool_name: str
    args: object


class ToolExecutionUpdateEvent(TypedDict):
    type: Literal["tool_execution_update"]
    tool_call_id: str
    tool_name: str
    args: object
    partial_result: AgentToolResult[Any]


class ToolExecutionEndEvent(TypedDict):
    type: Literal["tool_execution_end"]
    tool_call_id: str
    tool_name: str
    result: AgentToolResult[Any]
    is_error: bool
    duration_ms: NotRequired[int]


AgentEvent: TypeAlias = (
    AgentStartEvent
    | AgentEndEvent
    | TurnStartEvent
    | TurnEndEvent
    | MessageStartEvent
    | MessageUpdateEvent
    | MessageEndEvent
    | ToolExecutionStartEvent
    | ToolExecutionUpdateEvent
    | ToolExecutionEndEvent
)


class ProxyStartEvent(TypedDict):
    type: Literal["start"]


class ProxyTextStartEvent(TypedDict):
    type: Literal["text_start"]
    content_index: int


class ProxyTextDeltaEvent(TypedDict):
    type: Literal["text_delta"]
    content_index: int
    delta: str


class ProxyTextEndEvent(TypedDict):
    type: Literal["text_end"]
    content_index: int
    content_signature: NotRequired[str]


class ProxyThinkingStartEvent(TypedDict):
    type: Literal["thinking_start"]
    content_index: int


class ProxyThinkingDeltaEvent(TypedDict):
    type: Literal["thinking_delta"]
    content_index: int
    delta: str


class ProxyThinkingEndEvent(TypedDict):
    type: Literal["thinking_end"]
    content_index: int
    content_signature: NotRequired[str]


class ProxyToolCallStartEvent(TypedDict):
    type: Literal["toolcall_start"]
    content_index: int
    id: str
    tool_name: str


class ProxyToolCallDeltaEvent(TypedDict):
    type: Literal["toolcall_delta"]
    content_index: int
    delta: str


class ProxyToolCallEndEvent(TypedDict):
    type: Literal["toolcall_end"]
    content_index: int


class ProxyDoneEvent(TypedDict):
    type: Literal["done"]
    reason: Literal["stop", "length", "toolUse"]
    usage: Usage


class ProxyErrorEvent(TypedDict):
    type: Literal["error"]
    reason: Literal["aborted", "error"]
    usage: Usage
    error_message: NotRequired[str]


ProxyAssistantMessageEvent: TypeAlias = (
    ProxyStartEvent
    | ProxyTextStartEvent
    | ProxyTextDeltaEvent
    | ProxyTextEndEvent
    | ProxyThinkingStartEvent
    | ProxyThinkingDeltaEvent
    | ProxyThinkingEndEvent
    | ProxyToolCallStartEvent
    | ProxyToolCallDeltaEvent
    | ProxyToolCallEndEvent
    | ProxyDoneEvent
    | ProxyErrorEvent
)


@dataclass(frozen=True, kw_only=True)
class ProxyStreamOptions:
    signal: object | None = None
    max_output_tokens: int | None = None
    temperature: float | int | None = None
    reasoning: ReasoningOptions | None = None
    auth_token: str
    proxy_url: str
    max_tokens: int | None = None


__all__ = [
    "AfterToolCallContext",
    "AfterToolCallResult",
    "AgentContext",
    "AgentEvent",
    "AgentLoopConfig",
    "AgentMessage",
    "AgentOptions",
    "AgentState",
    "AgentThinkingBudgetMap",
    "AgentTool",
    "AgentToolCall",
    "AgentToolResult",
    "AgentToolUpdateCallback",
    "BeforeToolCallContext",
    "BeforeToolCallResult",
    "ConvertToLlmFn",
    "CustomAgentMessage",
    "ProxyAssistantMessageEvent",
    "ProxyStreamOptions",
    "ModelCallPreparation",
    "PrepareModelCallFn",
    "StreamFn",
    "ThinkingLevel",
    "ToolExecutionMode",
    "ToolOutputPreviewPolicy",
    "ToolOutputProjector",
    "TransformContextFn",
]
