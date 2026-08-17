from types import SimpleNamespace

import pytest

from loushang.ai.errors import UnsupportedCapabilityError
from loushang.ai.types import (
    AssistantMessage,
    ImagePart,
    TextPart,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from loushang.ai.utils.capabilities import (
    context_has_image_input,
    validate_image_input_compatibility,
)


def test_image_requirement_includes_all_message_roles_that_can_carry_images() -> None:
    image = ImagePart(type="image", data="aGVsbG8=", mime_type="image/png")

    assert context_has_image_input(
        [UserMessage(role="user", content=[image], timestamp=0.0)]
    )
    assert context_has_image_input(
        [
            ToolResultMessage(
                role="toolResult",
                tool_call_id="call-1",
                tool_name="view_image",
                content=[image],
                is_error=False,
                timestamp=0.0,
            )
        ]
    )
    assert context_has_image_input(
        [
            AssistantMessage(
                role="assistant",
                content=[image],
                api="test",
                provider="test",
                endpoint="test",
                model="test",
                response_id=None,
                usage=Usage(0, 0, 0, 0, 0, None),
                stop_reason="stop",
                error_message=None,
                timestamp=0.0,
            )
        ]
    )
    assert not context_has_image_input(
        [
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="hello")],
                timestamp=0.0,
            )
        ]
    )


def test_image_compatibility_uses_the_shared_requirement() -> None:
    messages = [
        ToolResultMessage(
            role="toolResult",
            tool_call_id="call-1",
            tool_name="view_image",
            content=[ImagePart(type="image", data="aGVsbG8=", mime_type="image/png")],
            is_error=False,
            timestamp=0.0,
        )
    ]

    with pytest.raises(
        UnsupportedCapabilityError, match="does not support image input"
    ):
        validate_image_input_compatibility(
            SimpleNamespace(id="text-only", supports_image_input=False),
            messages,
        )

    validate_image_input_compatibility(
        SimpleNamespace(id="vision", supports_image_input=True),
        messages,
    )
