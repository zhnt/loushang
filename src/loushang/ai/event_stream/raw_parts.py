from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from loushang.foundation.json import JSONValue


class ResponseStartPart(TypedDict):
    type: Literal["response_start"]
    response_id: str


class ResponseDonePart(TypedDict):
    type: Literal["response_done"]


class ResponseErrorPart(TypedDict):
    type: Literal["response_error"]
    message: str
    code: NotRequired[int]
    error_info: NotRequired[dict[str, JSONValue]]
    provider_response_summary: NotRequired[str]


class TextDeltaPart(TypedDict):
    type: Literal["text_delta"]
    text: str


class TextSignatureDeltaPart(TypedDict):
    type: Literal["text_signature_delta"]
    signature: str


class ThinkingDeltaPart(TypedDict):
    type: Literal["thinking_delta"]
    text: str


class ThinkingSignatureDeltaPart(TypedDict):
    type: Literal["thinking_signature_delta"]
    signature: str


class RedactedThinkingPart(TypedDict):
    type: Literal["redacted_thinking"]
    signature: str


class ToolCallStartPart(TypedDict):
    type: Literal["tool_call_start"]
    id: str
    name: str
    index: NotRequired[int]


class ToolCallArgsDeltaPart(TypedDict):
    type: Literal["tool_call_args_delta"]
    delta: str
    tool_call_id: NotRequired[str]
    index: NotRequired[int]


class ToolCallDonePart(TypedDict):
    type: Literal["tool_call_done"]
    tool_call_id: NotRequired[str]
    index: NotRequired[int]


class ToolCallThoughtSignaturePart(TypedDict):
    type: Literal["tool_call_thought_signature"]
    tool_call_id: str
    thought_signature: str


class ImagePartRaw(TypedDict):
    type: Literal["image_part"]
    data: str
    mime_type: str


class UsageDeltaPart(TypedDict, total=False):
    type: Literal["usage_delta"]
    input: int
    output: int
    cache_read: int
    cache_write: int
    total_tokens: int


class UsageCostMultiplierPart(TypedDict):
    type: Literal["usage_cost_multiplier"]
    multiplier: float


class StopReasonPart(TypedDict):
    type: Literal["stop_reason"]
    stop_reason: str


class AbortedPart(TypedDict):
    type: Literal["aborted"]


RawPart = (
    ResponseStartPart
    | ResponseDonePart
    | ResponseErrorPart
    | TextDeltaPart
    | TextSignatureDeltaPart
    | ThinkingDeltaPart
    | ThinkingSignatureDeltaPart
    | RedactedThinkingPart
    | ToolCallStartPart
    | ToolCallArgsDeltaPart
    | ToolCallDonePart
    | ToolCallThoughtSignaturePart
    | ImagePartRaw
    | UsageDeltaPart
    | UsageCostMultiplierPart
    | StopReasonPart
    | AbortedPart
)
