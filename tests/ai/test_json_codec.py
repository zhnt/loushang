from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

import pytest

from loushang.ai.json_codec import (
    deserialize_content_part,
    deserialize_message,
    deserialize_usage,
    serialize_assistant_message_event,
    serialize_content_part,
    serialize_json_value,
    serialize_message,
    serialize_usage,
)
from loushang.ai.types import (
    AssistantMessage,
    AssistantMessageEvent,
    ImagePart,
    TextPart,
    ThinkingPart,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)


class _HostileTruthValue:
    def __bool__(self) -> bool:
        raise AssertionError("boolean truthiness must not be evaluated")


def _assistant_message() -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[TextPart(type="text", text="done")],
        api="responses",
        provider="example",
        endpoint="test-endpoint",
        model="example-1",
        response_id="response-1",
        usage=Usage(
            input=2,
            output=3,
            cache_read=1,
            cache_write=0,
            total_tokens=6,
            cost=None,
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=10.0,
    )


def test_message_codec_round_trips_ai_messages() -> None:
    message = _assistant_message()
    payload = serialize_message(message)

    assert payload["endpoint"] == "test-endpoint"
    restored = deserialize_message(payload)
    assert restored == message
    assert isinstance(restored, AssistantMessage)
    assert f"{restored.provider}:{restored.endpoint}:{restored.model}" == (
        "example:test-endpoint:example-1"
    )


def test_message_codec_requires_json_details() -> None:
    message = ToolResultMessage(
        role="toolResult",
        tool_call_id="call-1",
        tool_name="read",
        content=[TextPart(type="text", text="ok")],
        is_error=False,
        timestamp=11.0,
        details={"path": "notes.txt"},
    )

    assert serialize_message(message)["details"] == {"path": "notes.txt"}

    message = replace(message, details=cast(Any, {"path": Path("notes.txt")}))
    with pytest.raises(TypeError, match="message.details.path"):
        serialize_message(message)


def test_tool_result_message_codec_persists_terminate_for_replay() -> None:
    message = ToolResultMessage(
        role="toolResult",
        tool_call_id="call-1",
        tool_name="finish",
        content=[TextPart(type="text", text="done")],
        is_error=False,
        timestamp=11.0,
        details={"ok": True},
        terminate=True,
    )

    encoded = serialize_message(message)

    assert encoded["terminate"] is True
    assert deserialize_message(encoded) == message

    encoded["terminate"] = "true"
    with pytest.raises(ValueError, match="terminate must be a boolean"):
        deserialize_message(encoded)


@pytest.mark.parametrize("field_name", ["is_error", "terminate"])
@pytest.mark.parametrize("value", [1, object(), _HostileTruthValue()])
def test_tool_result_message_codec_requires_exact_boolean_fields(
    field_name: str,
    value: object,
) -> None:
    message = ToolResultMessage(
        role="toolResult",
        tool_call_id="call-1",
        tool_name="finish",
        content=[TextPart(type="text", text="done")],
        is_error=False,
        timestamp=11.0,
        details={"ok": True},
    )

    with pytest.raises(TypeError, match="must be a boolean"):
        serialize_message(replace(message, **{field_name: cast(Any, value)}))

    encoded = serialize_message(message)
    wire_name = "isError" if field_name == "is_error" else "terminate"
    encoded[wire_name] = value
    with pytest.raises(ValueError, match="must be a boolean"):
        deserialize_message(encoded)


def test_tool_result_message_codec_requires_is_error_on_decode() -> None:
    message = ToolResultMessage(
        role="toolResult",
        tool_call_id="call-1",
        tool_name="finish",
        content=[TextPart(type="text", text="done")],
        is_error=False,
        timestamp=11.0,
    )
    encoded = serialize_message(message)
    del encoded["isError"]

    with pytest.raises(ValueError, match="isError must be a boolean"):
        deserialize_message(encoded)


def test_assistant_event_codec_uses_the_message_codec() -> None:
    message = _assistant_message()

    assert serialize_assistant_message_event(
        {"type": "done", "reason": "stop", "message": message}
    ) == {
        "type": "done",
        "reason": "stop",
        "message": serialize_message(message),
    }


def test_agent_transcript_codec_reuses_ai_message_wire_format() -> None:
    from loushang.harness.transcript import create_agent_transcript_message_codec

    codec = create_agent_transcript_message_codec()
    message = _assistant_message()
    payload = serialize_message(message)

    assert codec.serialize(message) == payload
    assert codec.deserialize(payload) == deserialize_message(payload)


def test_json_value_codec_rejects_implicit_object_projection() -> None:
    @dataclass
    class Detail:
        path: Path

    with pytest.raises(TypeError, match="got Detail"):
        serialize_json_value(Detail(path=Path("notes.txt")))
    with pytest.raises(TypeError, match="got tuple"):
        serialize_json_value({"items": (1, 2)})
    with pytest.raises(TypeError, match="got object"):
        serialize_json_value(object())


@pytest.mark.parametrize(
    "part",
    [
        TextPart(type="text", text="hello", text_signature="signature"),
        ImagePart(type="image", data="aGVsbG8=", mime_type="image/png"),
        ThinkingPart(
            type="thinking",
            thinking="reason",
            thinking_signature="signature",
            redacted=True,
        ),
        ToolCall(
            type="toolCall",
            id="call-1",
            name="read",
            arguments={"path": "README.md"},
            thought_signature="signature",
        ),
    ],
)
def test_content_part_codec_round_trips_supported_parts(part: object) -> None:
    encoded = serialize_content_part(cast(Any, part))

    assert deserialize_content_part(encoded) == part


def test_content_part_codec_rejects_unknown_parts() -> None:
    with pytest.raises(ValueError, match="Unsupported content part type"):
        serialize_content_part(cast(Any, object()))
    with pytest.raises(ValueError, match="Unsupported content part type: audio"):
        deserialize_content_part({"type": "audio"})


def test_usage_codec_accepts_snake_case_and_rejects_partial_cost() -> None:
    usage = deserialize_usage(
        {
            "input": 1,
            "output": 2,
            "cache_read": 3,
            "cache_write": 4,
            "total_tokens": 10,
            "cost": {
                "input": 0.1,
                "output": 0.2,
                "cache_read": 0.3,
                "cache_write": 0.4,
                "total": 1.0,
            },
        }
    )

    assert serialize_usage(usage)["cost"] == {
        "input": 0.1,
        "output": 0.2,
        "cacheRead": 0.3,
        "cacheWrite": 0.4,
        "total": 1.0,
    }
    assert (
        serialize_usage(Usage(1, 2, 0, 0, 3, cast(Any, {"input": -1.0})))["cost"]
        is None
    )


@pytest.mark.parametrize(
    "message",
    [
        UserMessage(role="user", content="hello", timestamp=1.0),
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="hello")],
            timestamp=2.0,
        ),
        ToolResultMessage(
            role="toolResult",
            tool_call_id="call-1",
            tool_name="read",
            content=[ImagePart(type="image", data="aGVsbG8=", mime_type="image/png")],
            is_error=False,
            timestamp=3.0,
            details={"ok": True},
        ),
    ],
)
def test_message_codec_round_trips_other_ai_messages(message: object) -> None:
    assert deserialize_message(serialize_message(cast(Any, message))) == message


def test_message_codec_rejects_unknown_message_and_role() -> None:
    with pytest.raises(ValueError, match="Unsupported AI message type"):
        serialize_message(cast(Any, object()))
    with pytest.raises(ValueError, match="Unsupported AI message role: system"):
        deserialize_message({"role": "system"})
    with pytest.raises(ValueError, match="Unsupported user content part"):
        deserialize_message(
            {
                "role": "user",
                "content": [{"type": "thinking", "thinking": "no"}],
                "timestamp": 1.0,
            }
        )


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (
            {"type": "text_start", "content_index": 0},
            {"type": "text_start", "contentIndex": 0},
        ),
        (
            {"type": "text_delta", "content_index": 1, "delta": "x"},
            {"type": "text_delta", "contentIndex": 1, "delta": "x"},
        ),
        (
            {"type": "thinking_end", "content_index": 2, "content": "why"},
            {"type": "thinking_end", "contentIndex": 2, "content": "why"},
        ),
        (
            {
                "type": "toolcall_end",
                "content_index": 3,
                "tool_call": ToolCall(
                    type="toolCall", id="call-1", name="read", arguments={}
                ),
            },
            {
                "type": "toolcall_end",
                "contentIndex": 3,
                "toolCall": {
                    "type": "toolCall",
                    "id": "call-1",
                    "name": "read",
                    "arguments": {},
                    "thoughtSignature": None,
                },
            },
        ),
        (
            {
                "type": "image_end",
                "content_index": 4,
                "image": ImagePart(
                    type="image", data="aGVsbG8=", mime_type="image/png"
                ),
            },
            {
                "type": "image_end",
                "contentIndex": 4,
                "image": {
                    "type": "image",
                    "data": "aGVsbG8=",
                    "mimeType": "image/png",
                },
            },
        ),
    ],
)
def test_assistant_event_codec_serializes_delta_variants(
    event: dict[str, object], expected: dict[str, object]
) -> None:
    assert (
        serialize_assistant_message_event(cast(AssistantMessageEvent, event))
        == expected
    )


def test_assistant_event_codec_serializes_start_error_and_rejects_unknown() -> None:
    message = _assistant_message()

    assert serialize_assistant_message_event({"type": "start", "partial": message}) == {
        "type": "start",
        "partial": serialize_message(message),
    }
    assert serialize_assistant_message_event(
        {"type": "error", "reason": "error", "error": message}
    ) == {
        "type": "error",
        "reason": "error",
        "error": serialize_message(message),
    }
    with pytest.raises(ValueError, match="Unsupported assistant message event"):
        serialize_assistant_message_event(
            cast(AssistantMessageEvent, {"type": "unknown"})
        )
