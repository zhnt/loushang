from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from loushang.ai.context import normalize_context
from loushang.ai.model import OpenAICompletionsConfig, OpenAIResponsesConfig
from loushang.ai.tool.providers import (
    to_anthropic_tools,
    to_openai_completions_tool_result_message,
    to_openai_completions_tools,
    to_openai_responses_tool_result_input,
    to_openai_responses_tools,
)
from loushang.ai.types import (
    AssistantMessage,
    ImagePart,
    TextPart,
    ThinkingPart,
    Tool,
    ToolCall,
    ToolResultMessage,
    Usage,
)

_UNPAIRED_HIGH_SURROGATE = "\ud83d"


def _assistant_tool_call(api: str) -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[
            ToolCall(
                type="toolCall",
                id="call_1",
                name="read",
                arguments={"path": "README.md"},
            )
        ],
        api=api,
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
        response_id=None,
        usage=Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost={},
        ),
        stop_reason="toolUse",
        error_message=None,
        timestamp=0.0,
    )


def _schema_with_meta_keys() -> dict[str, object]:
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": "urn:test-tool",
        "$comment": "schema metadata should not be sent to OpenAPI-style providers",
        "$defs": {"command": {"type": "string"}},
        "definitions": {"legacy": {"type": "number"}},
        "type": "object",
        "properties": {
            "command": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "$anchor": "nested-command",
                "type": "string",
            },
            "refProp": {
                "$ref": "#/$defs/command",
                "type": "string",
            },
            "choice": {
                "anyOf": [
                    {"$comment": "strip nested array meta", "type": "string"},
                    {"type": "number"},
                ],
            },
        },
        "required": ["command"],
    }


def _expected_sanitized_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "refProp": {
                "$ref": "#/$defs/command",
                "type": "string",
            },
            "choice": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "number"},
                ],
            },
        },
        "required": ["command"],
    }


def test_tool_provider_payloads_strip_schema_meta_keys_without_mutating_input() -> None:
    parameters = _schema_with_meta_keys()
    original = deepcopy(parameters)
    tool = Tool(name="probe", description="Probe", parameters=parameters)

    anthropic_payload = to_anthropic_tools([tool])
    completions_payload = to_openai_completions_tools([tool])
    responses_payload = to_openai_responses_tools([tool])

    assert anthropic_payload[0]["input_schema"] == _expected_sanitized_schema()
    assert (
        completions_payload[0]["function"]["parameters"] == _expected_sanitized_schema()
    )
    assert responses_payload[0]["parameters"] == _expected_sanitized_schema()
    assert parameters == original


def test_openai_completions_provider_build_tools_strips_schema_meta_keys() -> None:
    from loushang.ai.protocols.openai_chat_completions import _build_tools

    payload = _build_tools(
        [
            Tool(
                name="probe",
                description="Probe",
                parameters=_schema_with_meta_keys(),
            )
        ],
        OpenAICompletionsConfig(),
    )

    assert payload is not None
    assert payload[0]["function"]["parameters"] == _expected_sanitized_schema()


def test_openai_completions_provider_uses_image_placeholder_when_model_cannot_accept_images() -> (
    None
):
    from loushang.ai.protocols.openai_chat_completions import _tool_result_payload

    message = ToolResultMessage(
        role="toolResult",
        tool_call_id="call_1",
        tool_name="read_image",
        content=[ImagePart(type="image", data="aW1hZ2U=", mime_type="image/png")],
        is_error=False,
        timestamp=0.0,
    )

    tool_payload, image_blocks = _tool_result_payload(
        message,
        OpenAICompletionsConfig(),
        SimpleNamespace(input=("text",)),
    )

    assert tool_payload == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "(see attached image)",
    }
    assert image_blocks == []


def test_openai_completions_provider_sanitizes_unpaired_surrogates_in_payload_text() -> (
    None
):
    from loushang.ai.protocols.openai_chat_completions import _build_messages

    payload = _build_messages(
        SimpleNamespace(input=("text",), reasoning=False),
        normalize_context(
            {
                "system_prompt": f"system {_UNPAIRED_HIGH_SURROGATE} prompt",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"user {_UNPAIRED_HIGH_SURROGATE} text 🙈",
                            }
                        ],
                    },
                    _assistant_tool_call("openai-completions"),
                    ToolResultMessage(
                        role="toolResult",
                        tool_call_id="call_1",
                        tool_name="read",
                        content=[
                            TextPart(
                                type="text",
                                text=f"tool {_UNPAIRED_HIGH_SURROGATE} result 🙈",
                            )
                        ],
                        is_error=False,
                        timestamp=0.0,
                    ),
                ],
            }
        ),
        OpenAICompletionsConfig(),
    )

    assert payload[0]["content"] == "system  prompt"
    assert payload[1]["content"] == "user  text 🙈"
    assert payload[-1]["content"] == "tool  result 🙈"


def test_openai_responses_provider_uses_image_placeholder_when_model_cannot_accept_images() -> (
    None
):
    from loushang.ai.protocols._openai_responses import _tool_result_payload

    message = ToolResultMessage(
        role="toolResult",
        tool_call_id="call_1|fc_1",
        tool_name="read_image",
        content=[ImagePart(type="image", data="aW1hZ2U=", mime_type="image/png")],
        is_error=False,
        timestamp=0.0,
    )

    payload = _tool_result_payload(
        message,
        SimpleNamespace(input=("text",)),
        {"call_1|fc_1": "call_1|fc_1"},
    )

    assert payload == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "(see attached image)",
    }


def test_openai_responses_provider_preserves_image_only_tool_result() -> None:
    from loushang.ai.protocols._openai_responses import _tool_result_payload

    message = ToolResultMessage(
        role="toolResult",
        tool_call_id="call_1|fc_1",
        tool_name="read_image",
        content=[ImagePart(type="image", data="aW1hZ2U=", mime_type="image/png")],
        is_error=False,
        timestamp=0.0,
    )

    payload = _tool_result_payload(
        message,
        SimpleNamespace(input=("text", "image")),
        {"call_1|fc_1": "call_1|fc_1"},
    )

    assert payload == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": [
            {
                "type": "input_image",
                "detail": "auto",
                "image_url": "data:image/png;base64,aW1hZ2U=",
            }
        ],
    }


def test_openai_responses_provider_sanitizes_unpaired_surrogates_in_payload_text() -> (
    None
):
    from loushang.ai.protocols._openai_responses import convert_responses_messages

    payload = convert_responses_messages(
        SimpleNamespace(input=("text",), reasoning=False),
        normalize_context(
            {
                "system_prompt": f"system {_UNPAIRED_HIGH_SURROGATE} prompt",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"user {_UNPAIRED_HIGH_SURROGATE} text 🙈",
                            }
                        ],
                    },
                    _assistant_tool_call("openai-responses"),
                    ToolResultMessage(
                        role="toolResult",
                        tool_call_id="call_1",
                        tool_name="read",
                        content=[
                            TextPart(
                                type="text",
                                text=f"tool {_UNPAIRED_HIGH_SURROGATE} result 🙈",
                            )
                        ],
                        is_error=False,
                        timestamp=0.0,
                    ),
                ],
            }
        ),
        OpenAIResponsesConfig(),
    )

    assert payload[0]["content"] == "system  prompt"
    assert payload[1]["content"] == [{"type": "input_text", "text": "user  text 🙈"}]
    assert payload[-1]["output"] == "tool  result 🙈"


def test_anthropic_provider_sanitizes_unpaired_surrogates_in_payload_text() -> None:
    from loushang.ai.protocols.anthropic_messages import (
        _build_anthropic_message_payloads,
    )

    messages, system = _build_anthropic_message_payloads(
        normalize_context(
            {
                "system_prompt": f"system {_UNPAIRED_HIGH_SURROGATE} prompt",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"user {_UNPAIRED_HIGH_SURROGATE} text 🙈",
                            }
                        ],
                    },
                    AssistantMessage(
                        role="assistant",
                        content=[
                            TextPart(
                                type="text",
                                text=f"assistant {_UNPAIRED_HIGH_SURROGATE} text 🙈",
                            ),
                            ThinkingPart(
                                type="thinking",
                                thinking=f"thinking {_UNPAIRED_HIGH_SURROGATE} text 🙈",
                            ),
                            ToolCall(
                                type="toolCall",
                                id="call_1",
                                name="read",
                                arguments={"path": "README.md"},
                            ),
                        ],
                        api="anthropic-messages",
                        provider="anthropic",
                        endpoint="test-endpoint",
                        model="claude",
                        response_id=None,
                        usage=Usage(
                            input=0,
                            output=0,
                            cache_read=0,
                            cache_write=0,
                            total_tokens=0,
                            cost={},
                        ),
                        stop_reason="toolUse",
                        error_message=None,
                        timestamp=0.0,
                    ),
                    ToolResultMessage(
                        role="toolResult",
                        tool_call_id="call_1",
                        tool_name="read",
                        content=[
                            TextPart(
                                type="text",
                                text=f"tool {_UNPAIRED_HIGH_SURROGATE} result 🙈",
                            )
                        ],
                        is_error=False,
                        timestamp=0.0,
                    ),
                ],
            }
        )
    )

    assert system == [{"type": "text", "text": "system  prompt"}]
    assert messages[0]["content"] == [{"type": "text", "text": "user  text 🙈"}]
    assert messages[1]["content"] == [
        {"type": "text", "text": "assistant  text 🙈"},
        {"type": "text", "text": "thinking  text 🙈"},
        {
            "type": "tool_use",
            "id": "call_1",
            "name": "read",
            "input": {"path": "README.md"},
        },
    ]
    assert messages[2]["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "call_1",
            "content": "tool  result 🙈",
            "is_error": False,
        }
    ]


def test_openai_responses_tool_result_helper_preserves_images_in_function_output() -> (
    None
):
    message = ToolResultMessage(
        role="toolResult",
        tool_call_id="call_1",
        tool_name="read_image",
        content=[
            TextPart(type="text", text="A red circle."),
            ImagePart(type="image", data="aW1hZ2U=", mime_type="image/png"),
        ],
        is_error=False,
        timestamp=0.0,
    )

    payload = to_openai_responses_tool_result_input(message)

    assert payload == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": [
            {"type": "input_text", "text": "A red circle."},
            {
                "type": "input_image",
                "detail": "auto",
                "image_url": "data:image/png;base64,aW1hZ2U=",
            },
        ],
    }


def test_openai_completions_tool_result_helper_uses_image_placeholder_text() -> None:
    message = ToolResultMessage(
        role="toolResult",
        tool_call_id="call_1",
        tool_name="read_image",
        content=[ImagePart(type="image", data="aW1hZ2U=", mime_type="image/png")],
        is_error=False,
        timestamp=0.0,
    )

    payload = to_openai_completions_tool_result_message(message, include_name=True)

    assert payload == {
        "role": "tool",
        "tool_call_id": "call_1",
        "name": "read_image",
        "content": "(see attached image)",
    }
