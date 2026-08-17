from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, NotRequired, TypedDict

from loushang.foundation.json import JSONValue


class UsageCost(TypedDict):
    input: float
    output: float
    cacheRead: float
    cacheWrite: float
    total: float


@dataclass(frozen=True)
class Usage:
    input: int
    output: int
    cache_read: int
    cache_write: int
    total_tokens: int
    cost: UsageCost | None


@dataclass(frozen=True)
class TextPart:
    type: Literal["text"]
    text: str
    text_signature: str | dict[str, Any] | None = None


@dataclass(frozen=True)
class ImagePart:
    type: Literal["image"]
    data: str
    mime_type: str


@dataclass(frozen=True)
class ThinkingPart:
    type: Literal["thinking"]
    thinking: str
    thinking_signature: str | None = None
    redacted: bool = False


@dataclass(frozen=True)
class ToolCall:
    type: Literal["toolCall"]
    id: str
    name: str
    arguments: dict[str, Any]
    thought_signature: str | None = None


@dataclass(frozen=True)
class AssistantMessage:
    role: Literal["assistant"]
    content: list[TextPart | ThinkingPart | ToolCall | ImagePart]
    api: str
    provider: str
    endpoint: str
    model: str
    response_id: str | None
    usage: Usage
    stop_reason: "StopReason"
    error_message: str | None
    timestamp: float
    response_model: str | None = None
    error_info: dict[str, JSONValue] | None = None

    def __post_init__(self) -> None:
        for field_name in ("api", "provider", "endpoint", "model"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"AssistantMessage.{field_name} must be non-empty")
            object.__setattr__(self, field_name, value.strip())


@dataclass(frozen=True)
class UserMessage:
    role: Literal["user"]
    content: str | list[TextPart | ImagePart]
    timestamp: float


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolResultMessage:
    role: Literal["toolResult"]
    tool_call_id: str
    tool_name: str
    content: list[TextPart | ImagePart]
    is_error: bool
    timestamp: float
    details: JSONValue = None
    terminate: bool = False


Message = UserMessage | AssistantMessage | ToolResultMessage


@dataclass(frozen=True)
class Context:
    system_prompt: str | None = None
    messages: list[Message] = field(default_factory=list)
    tools: list[Tool] | None = None


# Stop reason aligned with pi-ai
StopReason = Literal["stop", "length", "toolUse", "error", "aborted"]


# Optional structured text signature (e.g., for OpenAI responses metadata)
class TextSignatureV1(TypedDict, total=False):
    v: Literal[1]
    id: str
    phase: Literal["commentary", "final_answer"]


class DoneEvent(TypedDict):
    type: Literal["done"]
    reason: Literal["stop", "length", "toolUse"]
    message: AssistantMessage


class StartEvent(TypedDict):
    type: Literal["start"]
    partial: AssistantMessage


class TextStartEvent(TypedDict):
    type: Literal["text_start"]
    content_index: int
    partial: AssistantMessage


class TextDeltaEvent(TypedDict):
    type: Literal["text_delta"]
    content_index: int
    delta: str
    partial: AssistantMessage


class TextEndEvent(TypedDict):
    type: Literal["text_end"]
    content_index: int
    content: str
    partial: AssistantMessage


class ThinkingStartEvent(TypedDict):
    type: Literal["thinking_start"]
    content_index: int
    partial: AssistantMessage


class ThinkingDeltaEvent(TypedDict):
    type: Literal["thinking_delta"]
    content_index: int
    delta: str
    partial: AssistantMessage


class ThinkingEndEvent(TypedDict):
    type: Literal["thinking_end"]
    content_index: int
    content: str
    partial: AssistantMessage


class ToolCallStartEvent(TypedDict):
    type: Literal["toolcall_start"]
    content_index: int
    partial: AssistantMessage


class ToolCallDeltaEvent(TypedDict):
    type: Literal["toolcall_delta"]
    content_index: int
    delta: str
    partial: AssistantMessage


class ToolCallEndEvent(TypedDict):
    type: Literal["toolcall_end"]
    content_index: int
    tool_call: ToolCall
    partial: AssistantMessage


class ImageStartEvent(TypedDict):
    type: Literal["image_start"]
    content_index: int
    partial: AssistantMessage


class ImageEndEvent(TypedDict):
    type: Literal["image_end"]
    content_index: int
    image: ImagePart
    partial: AssistantMessage


class ErrorEvent(TypedDict):
    type: Literal["error"]
    reason: Literal["aborted", "error"]
    error: AssistantMessage
    code: NotRequired[int]
    error_info: NotRequired[dict[str, JSONValue]]


AssistantMessageEvent = (
    StartEvent
    | TextStartEvent
    | TextDeltaEvent
    | TextEndEvent
    | ThinkingStartEvent
    | ThinkingDeltaEvent
    | ThinkingEndEvent
    | ToolCallStartEvent
    | ToolCallDeltaEvent
    | ToolCallEndEvent
    | ImageStartEvent
    | ImageEndEvent
    | DoneEvent
    | ErrorEvent
)
