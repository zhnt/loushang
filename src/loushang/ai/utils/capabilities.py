from __future__ import annotations

from collections.abc import Iterable

from loushang.ai.errors import UnsupportedCapabilityError
from loushang.ai.types import (
    AssistantMessage,
    ImagePart,
    ToolResultMessage,
    UserMessage,
)


def context_has_image_input(messages: Iterable[object]) -> bool:
    """Return whether a message sequence requires image-input support."""

    for message in messages:
        if (
            isinstance(message, UserMessage | AssistantMessage)
            and isinstance(message.content, list)
            and any(isinstance(part, ImagePart) for part in message.content)
        ):
            return True
        if isinstance(message, ToolResultMessage) and any(
            isinstance(part, ImagePart) for part in message.content
        ):
            return True
    return False


def validate_image_input_compatibility(
    model: object,
    messages: Iterable[object],
) -> None:
    """Reject a text-only model when the effective history contains images."""

    if not context_has_image_input(messages) or bool(
        getattr(model, "supports_image_input", False)
    ):
        return
    model_id = str(getattr(model, "id", "unknown"))
    raise UnsupportedCapabilityError(
        f"Cannot switch to {model_id!r}: this conversation contains images, "
        "but the model does not support image input",
        model=model_id,
        details={"capability": "image_input"},
    )


__all__ = [
    "context_has_image_input",
    "validate_image_input_compatibility",
]
