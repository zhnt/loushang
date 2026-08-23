from __future__ import annotations

from loushang.harnesstui.conversation.host import ConversationScreenRunProfile
from loushang.harnesstui.conversation.input import (
    bind_clipboard_image_input_router,
)
from loushang.harnesstui.conversation.input_policy import (
    DEFAULT_CONVERSATION_INPUT_POLICY,
)

CODING_INTERRUPTION_MESSAGE = (
    "Conversation interrupted - tell the model what to do differently."
)
CODING_CANCELLATION_MESSAGE = "Operation aborted"

CODING_CONVERSATION_INPUT_POLICY = DEFAULT_CONVERSATION_INPUT_POLICY

build_screen_input_router = bind_clipboard_image_input_router(
    policy=CODING_CONVERSATION_INPUT_POLICY,
)
CODING_SCREEN_RUN_PROFILE = ConversationScreenRunProfile(
    input_router_factory=build_screen_input_router,
    interruption_message=CODING_INTERRUPTION_MESSAGE,
    cancellation_message=CODING_CANCELLATION_MESSAGE,
)

__all__ = [
    "CODING_CANCELLATION_MESSAGE",
    "CODING_CONVERSATION_INPUT_POLICY",
    "CODING_INTERRUPTION_MESSAGE",
    "CODING_SCREEN_RUN_PROFILE",
    "build_screen_input_router",
]
