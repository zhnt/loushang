from __future__ import annotations

from loushang.foundation.observability import get_log
from loushang.foundation.runtime_scope import RuntimeScope, RuntimeSweepReport
from loushang.harnesstui.conversation.host import (
    ConversationScreenRunProfile,
    ConversationScreenRuntimeProfile,
)
from loushang.harnesstui.conversation.input import (
    ClipboardImageInputRouterBuilder,
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

log = get_log(__name__).bind(component="CodingScreenRuntime")

build_screen_input_router = bind_clipboard_image_input_router(
    policy=CODING_CONVERSATION_INPUT_POLICY,
)


def build_runtime_screen_input_router(
    scope: RuntimeScope,
) -> ClipboardImageInputRouterBuilder:
    """Bind the application-owned runtime scope into the standard router."""

    return bind_clipboard_image_input_router(
        policy=CODING_CONVERSATION_INPUT_POLICY,
        runtime_scope=scope,
    )


def _observe_runtime_sweep(report: RuntimeSweepReport) -> None:
    log.debug_event(
        "runtime",
        "sweep",
        inspected=report.inspected,
        active=report.active,
        removed=report.removed,
        removed_bytes=report.removed_bytes,
        skipped=report.skipped,
        failed=report.failed,
    )


CODING_SCREEN_RUN_PROFILE = ConversationScreenRunProfile(
    input_router_factory=build_screen_input_router,
    interruption_message=CODING_INTERRUPTION_MESSAGE,
    cancellation_message=CODING_CANCELLATION_MESSAGE,
    runtime=ConversationScreenRuntimeProfile(
        input_router_factory=build_runtime_screen_input_router,
        observe_sweep=_observe_runtime_sweep,
    ),
)

__all__ = [
    "CODING_CANCELLATION_MESSAGE",
    "CODING_CONVERSATION_INPUT_POLICY",
    "CODING_INTERRUPTION_MESSAGE",
    "CODING_SCREEN_RUN_PROFILE",
    "build_runtime_screen_input_router",
    "build_screen_input_router",
]
