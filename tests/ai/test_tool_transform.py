from __future__ import annotations

from loushang.ai.tool.transform import (
    MISSING_TOOL_RESULT_TEXT,
    SYNTHETIC_TOOL_RESULT_REASON,
    TOOL_RESULTS_PROCESSED_ASSISTANT_TEXT,
    MessagePairingError,
    coerce_cross_provider_assistant_message,
    insert_assistant_bridge_after_tool_results,
    transform_messages,
)
from loushang.ai.types import (
    AssistantMessage,
    TextPart,
    ThinkingPart,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)


def _usage() -> Usage:
    return Usage(
        input=0,
        output=0,
        cache_read=0,
        cache_write=0,
        total_tokens=0,
        cost={},
    )


def _assistant_with_tool_call() -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[
            ToolCall(type="toolCall", id="call_1", name="calc", arguments={"x": 1})
        ],
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
        response_id="resp_1",
        usage=_usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=0.0,
    )


def _assistant_with_signatures(*, endpoint: str = "test-endpoint") -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[
            ThinkingPart(
                type="thinking",
                thinking="private reasoning",
                thinking_signature='{"type":"reasoning","id":"rs_1"}',
            ),
            TextPart(type="text", text="answer", text_signature='{"v":1,"id":"msg_1"}'),
            ToolCall(
                type="toolCall",
                id="call_1",
                name="calc",
                arguments={"x": 1},
                thought_signature='{"type":"reasoning.encrypted"}',
            ),
        ],
        api="openai-responses",
        provider="openai",
        endpoint=endpoint,
        model="gpt-source",
        response_id="resp_1",
        usage=_usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=0.0,
    )


def test_transform_messages_marks_synthetic_tool_results() -> None:
    transformed = transform_messages(
        [_assistant_with_tool_call()], pairing_mode="repair"
    )

    synthetic = transformed[1]
    assert synthetic.role == "toolResult"
    assert synthetic.content == [TextPart(type="text", text=MISSING_TOOL_RESULT_TEXT)]
    assert synthetic.is_error is True
    assert synthetic.details == {
        "synthetic": True,
        "reason": SYNTHETIC_TOOL_RESULT_REASON,
    }


def test_insert_assistant_bridge_uses_shared_repair_text() -> None:
    transformed = insert_assistant_bridge_after_tool_results(
        [
            {"role": "tool", "tool_call_id": "call_1", "name": "calc", "content": "42"},
            {"role": "user", "content": "next"},
        ]
    )

    assert transformed == [
        {"role": "tool", "tool_call_id": "call_1", "name": "calc", "content": "42"},
        {"role": "assistant", "content": TOOL_RESULTS_PROCESSED_ASSISTANT_TEXT},
        {"role": "user", "content": "next"},
    ]


def test_transform_messages_strict_mode_rejects_missing_tool_result() -> None:
    try:
        transform_messages(
            [
                _assistant_with_tool_call(),
                UserMessage(role="user", content="next", timestamp=0.0),
            ],
            pairing_mode="strict",
        )
    except ValueError as error:
        assert str(error) == "Missing tool results before next message"
        assert isinstance(error, MessagePairingError)
        assert error.diagnostic.code == "missing_tool_result"
        assert error.diagnostic.path == "messages[0].content[0]"
        return

    raise AssertionError("strict mode should reject missing tool results")


def test_coerce_cross_provider_assistant_message_requires_same_model_identity() -> None:
    message = _assistant_with_signatures()

    transformed = coerce_cross_provider_assistant_message(
        message,
        target_api="openai-responses",
        target_provider="openai",
        target_endpoint="test-endpoint",
        target_model="gpt-target",
    )

    assert transformed.content == [
        TextPart(type="text", text="private reasoning"),
        TextPart(type="text", text="answer"),
        ToolCall(type="toolCall", id="call_1", name="calc", arguments={"x": 1}),
    ]


def test_coerce_assistant_message_preserves_signatures_for_same_target() -> None:
    message = _assistant_with_signatures()

    transformed = coerce_cross_provider_assistant_message(
        message,
        target_api="openai-responses",
        target_provider="openai",
        target_endpoint="test-endpoint",
        target_model="gpt-source",
    )

    assert transformed is message


def test_coerce_assistant_message_removes_signatures_for_different_endpoint() -> None:
    message = _assistant_with_signatures()

    transformed = coerce_cross_provider_assistant_message(
        message,
        target_api="openai-responses",
        target_provider="openai",
        target_endpoint="other-endpoint",
        target_model="gpt-source",
    )

    assert transformed.content == [
        TextPart(type="text", text="private reasoning"),
        TextPart(type="text", text="answer"),
        ToolCall(type="toolCall", id="call_1", name="calc", arguments={"x": 1}),
    ]


def test_cross_provider_assistant_message_removes_tool_call_thought_signature() -> None:
    message = AssistantMessage(
        role="assistant",
        content=[
            ThinkingPart(
                type="thinking",
                thinking="private reasoning",
                thinking_signature="thinking-sig",
            ),
            ToolCall(
                type="toolCall",
                id="call_123",
                name="bash",
                arguments={"command": "pwd"},
                thought_signature='{"type":"reasoning.encrypted","id":"call_123"}',
            ),
        ],
        api="openai-responses",
        provider="custom-openai",
        endpoint="test-endpoint",
        model="gpt-5",
        response_id=None,
        usage=_usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=0.0,
    )

    coerced = coerce_cross_provider_assistant_message(
        message, target_api="anthropic-messages"
    )

    assert coerced.content[0].type == "text"
    assert coerced.content[1] == ToolCall(
        type="toolCall",
        id="call_123",
        name="bash",
        arguments={"command": "pwd"},
        thought_signature=None,
    )


def test_transform_messages_normalizes_tool_call_and_matching_result_ids() -> None:
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(
                type="toolCall",
                id="call_1|fc_1",
                name="read",
                arguments={"path": "README.md"},
            ),
        ],
        api="openai-responses",
        provider="custom-openai",
        endpoint="test-endpoint",
        model="gpt-5",
        response_id=None,
        usage=_usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=0.0,
    )
    result = ToolResultMessage(
        role="toolResult",
        tool_call_id="call_1|fc_1",
        tool_name="read",
        content=[TextPart(type="text", text="done")],
        is_error=False,
        timestamp=0.0,
    )

    transformed = transform_messages(
        [assistant, result],
        normalize_tool_call_id=lambda tool_call_id, _message: tool_call_id.replace(
            "|", "_"
        ),
        pairing_mode="repair",
    )

    transformed_assistant = transformed[0]
    transformed_result = transformed[1]
    assert isinstance(transformed_assistant, AssistantMessage)
    assert isinstance(transformed_result, ToolResultMessage)
    assert transformed_assistant.content[0].id == "call_1_fc_1"
    assert transformed_result.tool_call_id == "call_1_fc_1"


def test_transform_messages_adds_synthetic_results_only_for_missing_tool_calls() -> (
    None
):
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(
                type="toolCall",
                id="call_1|fc_1",
                name="read",
                arguments={"path": "README.md"},
            ),
            ToolCall(
                type="toolCall",
                id="call_2|fc_2",
                name="bash",
                arguments={"command": "pwd"},
            ),
        ],
        api="openai-responses",
        provider="custom-openai",
        endpoint="test-endpoint",
        model="gpt-5",
        response_id=None,
        usage=_usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=0.0,
    )
    result = ToolResultMessage(
        role="toolResult",
        tool_call_id="call_1|fc_1",
        tool_name="read",
        content=[TextPart(type="text", text="done")],
        is_error=False,
        timestamp=0.0,
    )

    transformed = transform_messages(
        [assistant, result],
        normalize_tool_call_id=lambda tool_call_id, _message: tool_call_id.replace(
            "|", "_"
        ),
        pairing_mode="repair",
    )

    synthetic_results = [
        message
        for message in transformed
        if isinstance(message, ToolResultMessage) and message.is_error
    ]
    assert synthetic_results == [
        ToolResultMessage(
            role="toolResult",
            tool_call_id="call_2_fc_2",
            tool_name="bash",
            content=[TextPart(type="text", text="No result provided")],
            is_error=True,
            timestamp=0.0,
            details={"synthetic": True, "reason": SYNTHETIC_TOOL_RESULT_REASON},
        )
    ]


def test_transform_messages_keeps_aborted_assistant_as_turn_boundary() -> None:
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(
                type="toolCall",
                id="call_1",
                name="read",
                arguments={"path": "README.md"},
            )
        ],
        api="anthropic-messages",
        provider="moonshot",
        endpoint="test-endpoint",
        model="kimi-for-coding",
        response_id=None,
        usage=_usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=0.0,
    )
    aborted = AssistantMessage(
        role="assistant",
        content=[TextPart(type="text", text="")],
        api="anthropic-messages",
        provider="moonshot",
        endpoint="test-endpoint",
        model="kimi-for-coding",
        response_id=None,
        usage=_usage(),
        stop_reason="aborted",
        error_message="Request aborted by user",
        timestamp=1.0,
    )
    user = UserMessage(
        role="user", content=[TextPart(type="text", text="hello")], timestamp=2.0
    )

    transformed = transform_messages([assistant, aborted, user], pairing_mode="repair")

    assert [getattr(message, "role", None) for message in transformed] == [
        "assistant",
        "toolResult",
        "assistant",
        "user",
    ]
    boundary = transformed[2]
    assert isinstance(boundary, AssistantMessage)
    assert boundary.stop_reason == "stop"
    assert boundary.error_message is None
    assert boundary.content == [TextPart(type="text", text="Request aborted by user")]
