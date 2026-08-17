from __future__ import annotations

from types import MappingProxyType, SimpleNamespace

import pytest

from loushang.ai.context import (
    NormalizationResult,
    NormalizedContext,
    ensure_normalized_context,
    is_normalized_context,
    normalize_context,
    normalize_context_result,
)
from loushang.ai.errors import AIRequestValidationError
from loushang.ai.tool.transform import MessagePairingError
from loushang.ai.types import (
    AssistantMessage,
    Context,
    ImagePart,
    TextPart,
    ThinkingPart,
    Tool,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)


def _usage() -> object:
    from loushang.ai.types import Usage

    return Usage(
        input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
    )


def _write_tool() -> Tool:
    return Tool(
        name="write",
        description="Write a file",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    )


def _diagnostic_snapshot(
    result: NormalizationResult,
) -> list[tuple[str, str, str, str]]:
    return [
        (diagnostic.code, diagnostic.path, diagnostic.message, diagnostic.level)
        for diagnostic in result.diagnostics
    ]


class _DuckTypedTool:
    name = "calc"
    description = "calculate"
    parameters = {"type": "object"}


class _UnknownMessage:
    role = "custom"


class _UnknownPart:
    type = "custom"


def test_normalize_context_accepts_tool_dataclasses_and_dicts() -> None:
    normalized = normalize_context(
        {
            "messages": [],
            "tools": [
                Tool(
                    name="read",
                    description="Read a file",
                    parameters={"type": "object"},
                ),
                {
                    "name": "write",
                    "description": "Write a file",
                    "parameters": {"type": "object"},
                },
            ],
        }
    )

    assert normalized.tools == (
        Tool(name="read", description="Read a file", parameters={"type": "object"}),
        Tool(name="write", description="Write a file", parameters={"type": "object"}),
    )


def test_normalize_context_rejects_duck_typed_tools() -> None:
    with pytest.raises(TypeError, match="Unsupported tool type"):
        normalize_context({"messages": [], "tools": [_DuckTypedTool()]})


def test_normalize_context_rejects_dict_tools_with_invalid_names() -> None:
    with pytest.raises(TypeError, match="Unsupported tool name type"):
        normalize_context(
            {
                "messages": [],
                "tools": [{"name": "", "description": "bad"}],
            }
        )


def test_normalize_context_rejects_tool_dataclasses_with_invalid_names() -> None:
    with pytest.raises(TypeError, match="Unsupported tool name type"):
        normalize_context(
            {
                "messages": [],
                "tools": [
                    Tool(
                        name="",
                        description="bad",
                        parameters={"type": "object"},
                    )
                ],
            }
        )


def test_normalize_context_rejects_dict_tools_with_non_object_parameters() -> None:
    with pytest.raises(TypeError, match="Unsupported tool parameters type"):
        normalize_context(
            {
                "messages": [],
                "tools": [
                    {
                        "name": "calc",
                        "description": "Calculate values",
                        "parameters": "bad",
                    }
                ],
            }
        )


def test_normalize_context_rejects_tool_dataclasses_with_non_object_parameters() -> (
    None
):
    with pytest.raises(TypeError, match="Unsupported tool parameters type"):
        normalize_context(
            {
                "messages": [],
                "tools": [
                    Tool(
                        name="calc",
                        description="Calculate values",
                        parameters="bad",  # type: ignore[arg-type]
                    )
                ],
            }
        )


def test_normalize_context_rejects_context_tools_with_non_object_parameters() -> None:
    with pytest.raises(TypeError, match="Unsupported tool parameters type"):
        normalize_context(
            Context(
                messages=[],
                tools=[
                    Tool(
                        name="calc",
                        description="Calculate values",
                        parameters="bad",  # type: ignore[arg-type]
                    )
                ],
            )
        )


def test_normalize_context_rejects_context_tools_with_invalid_names() -> None:
    with pytest.raises(TypeError, match="Unsupported tool name type"):
        normalize_context(
            Context(
                messages=[],
                tools=[
                    Tool(
                        name="",
                        description="bad",
                        parameters={"type": "object"},
                    )
                ],
            )
        )


def test_normalize_context_rejects_context_dict_tools_with_non_object_parameters() -> (
    None
):
    with pytest.raises(TypeError, match="Unsupported tool parameters type"):
        normalize_context(
            Context(
                messages=[],
                tools=[  # type: ignore[list-item]
                    {
                        "name": "calc",
                        "description": "Calculate values",
                        "parameters": "bad",
                    }
                ],
            )
        )


def test_normalize_context_rejects_non_string_system_prompt() -> None:
    with pytest.raises(TypeError, match="Unsupported system_prompt type"):
        normalize_context({"system_prompt": {"text": "system"}, "messages": []})


def test_normalize_context_rejects_unknown_message_objects() -> None:
    with pytest.raises(TypeError, match="Unsupported message type after normalization"):
        normalize_context({"messages": [_UnknownMessage()]})


def test_normalize_context_rejects_unknown_dict_message_roles() -> None:
    with pytest.raises(TypeError, match="Unsupported message role"):
        normalize_context({"messages": [{"role": "custom", "content": "hello"}]})


def test_normalize_context_canonicalizes_non_dict_mapping_messages() -> None:
    normalized = normalize_context(
        {"messages": [MappingProxyType({"role": "user", "content": "hello"})]}
    )

    assert normalized.messages == (
        UserMessage(
            role="user",
            content=[TextPart(type="text", text="hello")],
            timestamp=0.0,
        ),
    )


def test_normalize_context_rejects_unknown_user_content_parts() -> None:
    with pytest.raises(TypeError, match="Unsupported user content part type"):
        normalize_context(
            {"messages": [{"role": "user", "content": [{"type": "audio"}]}]}
        )


def test_normalize_context_rejects_unknown_user_content_part_objects() -> None:
    with pytest.raises(TypeError, match="Unsupported user content part object"):
        normalize_context({"messages": [{"role": "user", "content": [_UnknownPart()]}]})


def test_normalize_context_returns_immutable_normalized_context() -> None:
    normalized = normalize_context({"messages": []})

    assert isinstance(normalized, NormalizedContext)
    assert is_normalized_context(normalized) is True
    assert normalized.messages == ()
    assert normalized.tools == ()
    assert normalized.to_dict() == {
        "system_prompt": None,
        "messages": (),
        "tools": (),
    }
    with pytest.raises(AttributeError):
        setattr(normalized, "system_prompt", "changed")


def test_normalize_context_uses_tuple_shell_and_copies_tool_parameters() -> None:
    arguments = {"x": 1}
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(type="toolCall", id="call_1", name="calc", arguments=arguments)
        ],
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
        response_id=None,
        usage=_usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=1.0,
    )
    tool_parameters = {
        "type": "object",
        "properties": {"x": {"type": "number"}},
    }
    tool = Tool(
        name="calc",
        description="Calculate values",
        parameters=tool_parameters,
    )
    tool_result = ToolResultMessage(
        role="toolResult",
        tool_call_id="call_1",
        tool_name="calc",
        content=[TextPart(type="text", text="1")],
        is_error=False,
        timestamp=2.0,
    )

    normalized = normalize_context(
        {
            "messages": [assistant, tool_result],
            "tools": [tool],
        }
    )

    normalized_assistant = normalized.messages[0]
    assert normalized.messages == (assistant, tool_result)
    assert isinstance(normalized_assistant, AssistantMessage)
    assert normalized_assistant.content == [
        ToolCall(type="toolCall", id="call_1", name="calc", arguments={"x": 1})
    ]
    assert normalized.tools[0] is not tool
    assert normalized.tools == (
        Tool(
            name="calc",
            description="Calculate values",
            parameters={
                "type": "object",
                "properties": {"x": {"type": "number"}},
            },
        ),
    )

    tool_parameters["type"] = "mutated"
    assert normalized.tools[0].parameters["type"] == "object"
    tool_parameters["properties"]["x"]["type"] = "string"
    assert normalized.tools[0].parameters["properties"]["x"]["type"] == "string"


def test_normalize_context_rejects_unknown_top_level_fields() -> None:
    with pytest.raises(TypeError, match="Unsupported Context field"):
        normalize_context({"messages": [], "payload": {"x": 1}})


def test_ensure_normalized_context_revalidates_normalized_context() -> None:
    normalized = normalize_context({"messages": []})

    ensured = ensure_normalized_context(normalized)

    assert ensured == normalized
    assert ensured is not normalized
    assert is_normalized_context(ensured) is True


def test_normalize_context_rejects_legacy_marker_dict() -> None:
    with pytest.raises(TypeError, match="Unsupported Context field"):
        normalize_context(
            {
                "_loushang_normalized_context": True,
                "messages": [{"role": "system", "content": "system text"}],
            }
        )


def test_normalize_context_result_wraps_normalized_context() -> None:
    result = normalize_context_result({"messages": []})

    assert isinstance(result, NormalizationResult)
    assert isinstance(result.context, NormalizedContext)
    assert result.context.messages == ()
    assert result.context.tools == ()
    assert result.diagnostics == ()


def test_normalize_context_result_reports_missing_tool_result_repair() -> None:
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(type="toolCall", id="call_1", name="calc", arguments={"x": 1})
        ],
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
        response_id=None,
        usage=_usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=1.0,
    )

    result = normalize_context_result({"messages": [assistant]}, pairing_mode="repair")

    assert _diagnostic_snapshot(result) == [
        (
            "missing_tool_result_repaired",
            "messages[0].content[0]",
            "Inserted synthetic error result for missing tool call 'call_1'.",
            "warning",
        )
    ]


def test_normalize_context_result_reports_tool_call_id_repairs() -> None:
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(type="toolCall", id="call:1", name="calc", arguments={"x": 1})
        ],
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
        response_id=None,
        usage=_usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=1.0,
    )
    tool_result = ToolResultMessage(
        role="toolResult",
        tool_call_id="call:1",
        tool_name="calc",
        content=[TextPart(type="text", text="1")],
        is_error=False,
        timestamp=2.0,
    )

    result = normalize_context_result(
        {"messages": [assistant, tool_result]},
        model=SimpleNamespace(
            api="anthropic-messages",
            provider_id="anthropic",
            id="claude-test",
        ),
    )

    assert _diagnostic_snapshot(result) == [
        (
            "tool_call_id_normalized",
            "messages[0].content[0]",
            "Normalized tool call id 'call:1' to 'call_1'.",
            "warning",
        ),
        (
            "tool_result_id_normalized",
            "messages[1]",
            "Normalized tool result id 'call:1' to 'call_1'.",
            "warning",
        ),
    ]


def test_normalize_context_result_keeps_original_paths_after_system_messages() -> None:
    result = normalize_context_result(
        {
            "messages": [
                {"role": "system", "content": "system"},
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "failed"}],
                    "api": "openai-responses",
                    "provider": "openai",
                    "endpoint": "responses",
                    "model": "gpt-test",
                    "stopReason": "error",
                    "errorMessage": "provider failed",
                },
            ]
        }
    )

    assert _diagnostic_snapshot(result) == [
        (
            "error_assistant_dropped",
            "messages[1]",
            "Dropped error assistant message during normalization.",
            "warning",
        )
    ]


def test_normalize_context_result_skips_tool_diagnostics_for_dropped_error_assistant() -> (
    None
):
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(
                type="toolCall",
                id="call:1",
                name="calc",
                arguments={"x": 1},
                thought_signature="thought-sig",
            )
        ],
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
        response_id=None,
        usage=_usage(),
        stop_reason="error",
        error_message="provider failed",
        timestamp=1.0,
    )
    tool_result = ToolResultMessage(
        role="toolResult",
        tool_call_id="call:1",
        tool_name="calc",
        content=[TextPart(type="text", text="1")],
        is_error=False,
        timestamp=2.0,
    )

    result = normalize_context_result(
        {"messages": [assistant, tool_result]},
        model=SimpleNamespace(
            api="anthropic-messages",
            provider_id="anthropic",
            id="claude-test",
        ),
        pairing_mode="repair",
    )

    assert len(result.context.messages) == 1
    normalized_result = result.context.messages[0]
    assert isinstance(normalized_result, ToolResultMessage)
    assert normalized_result.tool_call_id == "call_1"
    assert _diagnostic_snapshot(result) == [
        (
            "error_assistant_dropped",
            "messages[0]",
            "Dropped error assistant message during normalization.",
            "warning",
        ),
        (
            "tool_result_id_normalized",
            "messages[1]",
            "Normalized tool result id 'call:1' to 'call_1'.",
            "warning",
        ),
    ]


def test_normalize_context_result_skips_tool_diagnostics_for_aborted_boundary() -> None:
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(
                type="toolCall",
                id="call:1",
                name="calc",
                arguments={"x": 1},
                thought_signature="thought-sig",
            )
        ],
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
        response_id=None,
        usage=_usage(),
        stop_reason="aborted",
        error_message="Request aborted by user",
        timestamp=1.0,
    )
    tool_result = ToolResultMessage(
        role="toolResult",
        tool_call_id="call:1",
        tool_name="calc",
        content=[TextPart(type="text", text="1")],
        is_error=False,
        timestamp=2.0,
    )

    result = normalize_context_result(
        {"messages": [assistant, tool_result]},
        model=SimpleNamespace(
            api="anthropic-messages",
            provider_id="anthropic",
            id="claude-test",
        ),
        pairing_mode="repair",
    )

    assert len(result.context.messages) == 2
    boundary = result.context.messages[0]
    assert isinstance(boundary, AssistantMessage)
    assert boundary.stop_reason == "stop"
    assert boundary.content == [TextPart(type="text", text="Request aborted by user")]
    normalized_result = result.context.messages[1]
    assert isinstance(normalized_result, ToolResultMessage)
    assert normalized_result.tool_call_id == "call_1"
    assert _diagnostic_snapshot(result) == [
        (
            "aborted_assistant_repaired",
            "messages[0]",
            "Repaired aborted assistant message as a text turn boundary.",
            "warning",
        ),
        (
            "tool_result_id_normalized",
            "messages[1]",
            "Normalized tool result id 'call:1' to 'call_1'.",
            "warning",
        ),
    ]


def test_normalize_context_result_keeps_repair_paths_when_tool_ids_collide() -> None:
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(type="toolCall", id="call:1", name="calc", arguments={"x": 1}),
            ToolCall(type="toolCall", id="call_1", name="read", arguments={}),
        ],
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
        response_id=None,
        usage=_usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=1.0,
    )

    result = normalize_context_result(
        {"messages": [assistant]},
        model=SimpleNamespace(
            api="anthropic-messages",
            provider_id="anthropic",
            id="claude-test",
        ),
        pairing_mode="repair",
    )

    normalized = result.context.messages[0]
    assert isinstance(normalized, AssistantMessage)
    tool_calls = [part for part in normalized.content if isinstance(part, ToolCall)]
    assert len(tool_calls) == 2
    assert tool_calls[1].id == "call_1"
    assert tool_calls[0].id != "call_1"
    assert len({tool_call.id for tool_call in tool_calls}) == 2

    synthetic_results = [
        message
        for message in result.context.messages
        if isinstance(message, ToolResultMessage)
    ]
    assert [message.tool_call_id for message in synthetic_results] == [
        tool_call.id for tool_call in tool_calls
    ]
    assert _diagnostic_snapshot(result)[:3] == [
        (
            "tool_call_id_normalized",
            "messages[0].content[0]",
            f"Normalized tool call id 'call:1' to {tool_calls[0].id!r}.",
            "warning",
        ),
        (
            "missing_tool_result_repaired",
            "messages[0].content[0]",
            f"Inserted synthetic error result for missing tool call {tool_calls[0].id!r}.",
            "warning",
        ),
        (
            "missing_tool_result_repaired",
            "messages[0].content[1]",
            "Inserted synthetic error result for missing tool call 'call_1'.",
            "warning",
        ),
    ]


def test_normalize_context_result_reports_cross_provider_downgrades_and_signature_removal() -> (
    None
):
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ThinkingPart(
                type="thinking",
                thinking="private reasoning",
                thinking_signature="thinking-sig",
            ),
            TextPart(type="text", text="answer", text_signature="text-sig"),
            ToolCall(
                type="toolCall",
                id="call_1",
                name="calc",
                arguments={"x": 1},
                thought_signature="thought-sig",
            ),
        ],
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
        response_id=None,
        usage=_usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=1.0,
    )
    tool_result = ToolResultMessage(
        role="toolResult",
        tool_call_id="call_1",
        tool_name="calc",
        content=[TextPart(type="text", text="1")],
        is_error=False,
        timestamp=2.0,
    )

    result = normalize_context_result(
        {"messages": [assistant, tool_result]},
        model=SimpleNamespace(
            api="anthropic-messages",
            provider_id="anthropic",
            id="claude-test",
        ),
    )

    assert _diagnostic_snapshot(result) == [
        (
            "thinking_signature_removed",
            "messages[0].content[0]",
            "Removed provider-specific thinking signature.",
            "warning",
        ),
        (
            "thinking_downgraded_to_text",
            "messages[0].content[0]",
            "Downgraded provider-specific thinking to text.",
            "warning",
        ),
        (
            "text_signature_removed",
            "messages[0].content[1]",
            "Removed provider-specific text signature.",
            "warning",
        ),
        (
            "tool_call_thought_signature_removed",
            "messages[0].content[2]",
            "Removed provider-specific tool call thought signature.",
            "warning",
        ),
    ]


def test_normalize_context_propagates_target_endpoint_to_signature_coercion() -> None:
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ThinkingPart(
                type="thinking",
                thinking="private reasoning",
                thinking_signature="thinking-sig",
            ),
            TextPart(type="text", text="answer", text_signature="text-sig"),
            ToolCall(
                type="toolCall",
                id="call_1",
                name="calc",
                arguments={"x": 1},
                thought_signature="thought-sig",
            ),
        ],
        api="openai-responses",
        provider="openai",
        endpoint="source-endpoint",
        model="gpt-test",
        response_id=None,
        usage=_usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=1.0,
    )
    tool_result = ToolResultMessage(
        role="toolResult",
        tool_call_id="call_1",
        tool_name="calc",
        content=[TextPart(type="text", text="1")],
        is_error=False,
        timestamp=2.0,
    )

    normalized = normalize_context(
        {"messages": [assistant, tool_result]},
        model=SimpleNamespace(
            api="openai-responses",
            provider_id="openai",
            endpoint_id="target-endpoint",
            id="gpt-test",
        ),
    )

    normalized_assistant = normalized.messages[0]
    assert isinstance(normalized_assistant, AssistantMessage)
    assert normalized_assistant.content == [
        TextPart(type="text", text="private reasoning"),
        TextPart(type="text", text="answer"),
        ToolCall(type="toolCall", id="call_1", name="calc", arguments={"x": 1}),
    ]


def test_normalize_context_result_reports_dropped_thinking_blocks() -> None:
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ThinkingPart(
                type="thinking",
                thinking="private reasoning",
                thinking_signature="thinking-sig",
                redacted=True,
            ),
            ThinkingPart(type="thinking", thinking="   "),
            TextPart(type="text", text="answer"),
        ],
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
        response_id=None,
        usage=_usage(),
        stop_reason="stop",
        error_message=None,
        timestamp=1.0,
    )

    result = normalize_context_result(
        {"messages": [assistant]},
        model=SimpleNamespace(
            api="anthropic-messages",
            provider_id="anthropic",
            id="claude-test",
        ),
    )

    normalized = result.context.messages[0]
    assert isinstance(normalized, AssistantMessage)
    assert normalized.content == [TextPart(type="text", text="answer")]
    assert _diagnostic_snapshot(result) == [
        (
            "thinking_signature_removed",
            "messages[0].content[0]",
            "Removed provider-specific thinking signature.",
            "warning",
        ),
        (
            "redacted_thinking_dropped",
            "messages[0].content[0]",
            "Dropped redacted thinking block while coercing assistant message.",
            "warning",
        ),
        (
            "empty_thinking_dropped",
            "messages[0].content[1]",
            "Dropped empty thinking block while coercing assistant message.",
            "warning",
        ),
    ]


def test_normalize_context_revalidates_existing_context_with_target_model() -> None:
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(type="toolCall", id="call:1", name="calc", arguments={"x": 1})
        ],
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
        response_id=None,
        usage=_usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=1.0,
    )
    tool_result = ToolResultMessage(
        role="toolResult",
        tool_call_id="call:1",
        tool_name="calc",
        content=[TextPart(type="text", text="1")],
        is_error=False,
        timestamp=2.0,
    )
    first = normalize_context({"messages": [assistant, tool_result]})

    reprojected = normalize_context(
        first,
        model=SimpleNamespace(
            api="anthropic-messages",
            provider_id="anthropic",
            id="claude-test",
        ),
    )

    assert reprojected is not first
    next_assistant = reprojected.messages[0]
    next_tool_result = reprojected.messages[1]
    assert isinstance(next_assistant, AssistantMessage)
    assert isinstance(next_tool_result, ToolResultMessage)
    assert next_assistant.content[0] == ToolCall(
        type="toolCall",
        id="call_1",
        name="calc",
        arguments={"x": 1},
    )
    assert next_tool_result.tool_call_id == "call_1"


def test_ensure_normalized_context_returns_revalidated_context() -> None:
    normalized = normalize_context(
        {"messages": []},
        model=SimpleNamespace(
            api="openai-responses",
            provider_id="custom",
            id="gpt-test",
        ),
    )

    ensured = ensure_normalized_context(
        normalized,
        model=SimpleNamespace(
            api="openai-responses",
            provider_id="custom",
            id="gpt-test",
        ),
    )

    assert ensured == normalized
    assert ensured is not normalized


def test_normalize_context_revalidates_existing_context_for_pairing_mode() -> None:
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(type="toolCall", id="call_1", name="calc", arguments={"x": 1})
        ],
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
        response_id=None,
        usage=_usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=1.0,
    )
    repaired = normalize_context({"messages": [assistant]}, pairing_mode="repair")

    revalidated = normalize_context(repaired, pairing_mode="strict")

    assert revalidated == repaired
    assert revalidated is not repaired


def test_normalized_context_does_not_bypass_strict_pairing() -> None:
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(type="toolCall", id="call_1", name="calc", arguments={"x": 1})
        ],
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
        response_id=None,
        usage=_usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=1.0,
    )
    malformed = NormalizedContext(system_prompt=None, messages=(assistant,))

    with pytest.raises(MessagePairingError, match="Missing tool result"):
        normalize_context(malformed, pairing_mode="strict")

    result = normalize_context_result(malformed, pairing_mode="repair")

    assert len(result.context.messages) == 2
    assert result.diagnostics[0].code == "missing_tool_result_repaired"


@pytest.mark.parametrize("arguments", [None, "{}", [1], 1])
def test_normalize_context_rejects_non_mapping_tool_arguments(
    arguments: object,
) -> None:
    with pytest.raises(AIRequestValidationError, match="arguments must be a mapping"):
        normalize_context(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "toolCall",
                                "id": "call_1",
                                "name": "calc",
                                "arguments": arguments,
                            }
                        ],
                    }
                ]
            },
            pairing_mode="repair",
        )


def test_normalized_context_rejects_typed_non_mapping_tool_arguments() -> None:
    tool_call = ToolCall(
        type="toolCall",
        id="call_1",
        name="calc",
        arguments="{}",  # type: ignore[arg-type]
    )
    assistant = AssistantMessage(
        role="assistant",
        content=[tool_call],
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
        response_id=None,
        usage=_usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=1.0,
    )

    with pytest.raises(AIRequestValidationError, match="arguments must be a mapping"):
        normalize_context(
            NormalizedContext(system_prompt=None, messages=(assistant,)),
            pairing_mode="repair",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("isError", "false"), ("is_error", 0)],
)
def test_normalize_context_rejects_non_boolean_tool_result_flags(
    field: str,
    value: object,
) -> None:
    with pytest.raises(AIRequestValidationError, match="must be a boolean"):
        normalize_context(
            {
                "messages": [
                    {
                        "role": "toolResult",
                        "toolCallId": "call_1",
                        "toolName": "calc",
                        "content": [],
                        field: value,
                    }
                ]
            },
            pairing_mode="repair",
        )


def test_normalize_context_rejects_non_boolean_redacted_flag() -> None:
    with pytest.raises(AIRequestValidationError, match="redacted must be a boolean"):
        normalize_context(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "thinking",
                                "thinking": "private",
                                "redacted": "false",
                            }
                        ],
                    }
                ]
            }
        )


@pytest.mark.parametrize("value", [True, -1, 1.5, float("nan"), float("inf")])
def test_normalize_context_rejects_invalid_usage_token_counts(value: object) -> None:
    with pytest.raises(AIRequestValidationError, match="non-negative integer"):
        normalize_context(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [],
                        "usage": {"input": value},
                    }
                ]
            }
        )


def test_normalized_context_rejects_invalid_typed_usage() -> None:
    assistant = AssistantMessage(
        role="assistant",
        content=[],
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
        response_id=None,
        usage=Usage(
            input=-1,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost=None,
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=1.0,
    )

    with pytest.raises(AIRequestValidationError, match="non-negative integer"):
        normalize_context(NormalizedContext(system_prompt=None, messages=(assistant,)))


def test_normalize_context_accepts_pi_style_assistant_and_tool_result_dicts() -> None:
    normalized = normalize_context(
        {
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "thinking",
                            "thinking": "private reasoning",
                            "thinkingSignature": "thinking-sig",
                        },
                        {
                            "type": "toolCall",
                            "id": "call_1",
                            "name": "read_image",
                            "arguments": {"path": "diagram.png"},
                            "thoughtSignature": "tool-call-sig",
                        },
                    ],
                    "api": "openai-responses",
                    "provider": "custom-openai",
                    "endpoint": "test-endpoint",
                    "model": "gpt-5",
                    "responseId": "resp_1",
                    "usage": {
                        "input": 1,
                        "output": 2,
                        "cacheRead": 3,
                        "cacheWrite": 4,
                        "totalTokens": 10,
                        "cost": {"usd": 0.01},
                    },
                    "stopReason": "toolUse",
                    "errorMessage": None,
                    "timestamp": 123.0,
                    "responseModel": "gpt-5",
                },
                {
                    "role": "toolResult",
                    "toolCallId": "call_1",
                    "toolName": "read_image",
                    "content": [
                        {"type": "text", "text": "A diagram."},
                        {"type": "image", "data": "aW1hZ2U=", "mimeType": "image/png"},
                    ],
                    "isError": False,
                    "timestamp": 124.0,
                    "details": {"source": "test"},
                },
            ],
        }
    )

    assistant = normalized.messages[0]
    tool_result = normalized.messages[1]

    assert len(normalized.messages) == 2
    assert isinstance(assistant, AssistantMessage)
    assert assistant.content == [
        ThinkingPart(
            type="thinking",
            thinking="private reasoning",
            thinking_signature="thinking-sig",
        ),
        ToolCall(
            type="toolCall",
            id="call_1",
            name="read_image",
            arguments={"path": "diagram.png"},
            thought_signature="tool-call-sig",
        ),
    ]
    assert assistant.response_id == "resp_1"
    assert assistant.usage.cache_read == 3
    assert assistant.stop_reason == "toolUse"
    assert assistant.response_model == "gpt-5"
    assert isinstance(tool_result, ToolResultMessage)
    assert tool_result.tool_call_id == "call_1"
    assert tool_result.tool_name == "read_image"
    assert tool_result.content == [
        TextPart(type="text", text="A diagram."),
        ImagePart(type="image", data="aW1hZ2U=", mime_type="image/png"),
    ]
    assert tool_result.details == {"source": "test"}


def test_normalize_context_canonicalizes_user_dicts_once() -> None:
    normalized = normalize_context(
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Look"},
                        {"type": "image", "data": "aW1n", "mimeType": "image/png"},
                    ],
                    "timestamp": 125.0,
                }
            ]
        }
    )

    user = normalized.messages[0]

    assert isinstance(user, UserMessage)
    assert user.content == [
        TextPart(type="text", text="Look"),
        ImagePart(type="image", data="aW1n", mime_type="image/png"),
    ]
    assert user.timestamp == 125.0


def test_normalize_context_preserves_unknown_usage_cost() -> None:
    normalized = normalize_context(
        {
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "hello"}],
                    "api": "openai-responses",
                    "provider": "openai",
                    "endpoint": "test-endpoint",
                    "model": "gpt-4.1",
                    "responseId": "resp_1",
                    "usage": {
                        "input": 1,
                        "output": 2,
                        "cacheRead": 0,
                        "cacheWrite": 0,
                        "totalTokens": 3,
                    },
                    "stopReason": "stop",
                    "timestamp": 123.0,
                }
            ],
        }
    )

    assistant = normalized.messages[0]

    assert isinstance(assistant, AssistantMessage)
    assert assistant.usage.cost is None


@pytest.mark.parametrize(
    "cost",
    [
        {},
        {"input": 0.1},
        {
            "input": -0.1,
            "output": 0.2,
            "cacheRead": 0.0,
            "cacheWrite": 0.0,
            "total": 0.1,
        },
        {
            "input": float("nan"),
            "output": 0.2,
            "cacheRead": 0.0,
            "cacheWrite": 0.0,
            "total": 0.2,
        },
    ],
)
def test_normalize_context_rejects_invalid_usage_cost(
    cost: dict[str, float],
) -> None:
    normalized = normalize_context(
        {
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "hello"}],
                    "api": "openai-responses",
                    "provider": "openai",
                    "endpoint": "test-endpoint",
                    "model": "gpt-4.1",
                    "usage": {
                        "input": 1,
                        "output": 2,
                        "cacheRead": 0,
                        "cacheWrite": 0,
                        "totalTokens": 3,
                        "cost": cost,
                    },
                    "stopReason": "stop",
                    "timestamp": 123.0,
                }
            ],
        }
    )

    assistant = normalized.messages[0]
    assert isinstance(assistant, AssistantMessage)
    assert assistant.usage.cost is None


def test_normalize_context_canonicalizes_usage_cost_aliases() -> None:
    normalized = normalize_context(
        {
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "hello"}],
                    "api": "openai-responses",
                    "provider": "openai",
                    "endpoint": "test-endpoint",
                    "model": "gpt-4.1",
                    "usage": {
                        "input": 1,
                        "output": 2,
                        "cacheRead": 0,
                        "cacheWrite": 0,
                        "totalTokens": 3,
                        "cost": {
                            "input": 0.1,
                            "output": 0.2,
                            "cache_read": 0.0,
                            "cache_write": 0.0,
                            "total": 0.3,
                        },
                    },
                    "stopReason": "stop",
                    "timestamp": 123.0,
                }
            ],
        }
    )

    assistant = normalized.messages[0]

    assert isinstance(assistant, AssistantMessage)
    assert assistant.usage.cost == {
        "input": 0.1,
        "output": 0.2,
        "cacheRead": 0.0,
        "cacheWrite": 0.0,
        "total": 0.3,
    }


def test_normalize_context_accepts_string_assistant_dict_content() -> None:
    normalized = normalize_context(
        {
            "messages": [
                {
                    "role": "assistant",
                    "content": "Plain assistant text.",
                    "api": "openai-responses",
                    "provider": "openai",
                    "endpoint": "responses",
                    "model": "gpt-test",
                    "timestamp": 1,
                },
            ],
        }
    )

    assistant = normalized.messages[0]

    assert isinstance(assistant, AssistantMessage)
    assert assistant.content == [TextPart(type="text", text="Plain assistant text.")]


def test_normalize_context_keeps_malformed_historical_tool_call_recoverable() -> None:
    normalized = normalize_context(
        {
            "messages": [
                AssistantMessage(
                    role="assistant",
                    content=[
                        ToolCall(
                            type="toolCall",
                            id="write-empty",
                            name="write",
                            arguments={},
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
                    timestamp=1.0,
                ),
                ToolResultMessage(
                    role="toolResult",
                    tool_call_id="write-empty",
                    tool_name="write",
                    content=[
                        TextPart(
                            type="text",
                            text=(
                                'Validation failed for tool "write":\n'
                                "  - path: is required\n"
                                "  - content: is required"
                            ),
                        )
                    ],
                    is_error=True,
                    timestamp=2.0,
                ),
                UserMessage(
                    role="user",
                    content=[TextPart(type="text", text="你好")],
                    timestamp=3.0,
                ),
            ],
            "tools": [_write_tool()],
        }
    )

    assert [getattr(message, "role", None) for message in normalized.messages] == [
        "assistant",
        "toolResult",
        "user",
    ]
