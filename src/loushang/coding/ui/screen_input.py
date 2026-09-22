from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loushang.harness.session import SessionOperationResolver
    from loushang.harnesstui.conversation.input_policy import (
        ConversationCapabilities,
        ConversationCapability,
        ConversationOperation,
    )

from loushang.foundation.observability import get_log, log_context
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


def project_coding_capabilities(
    binding_key: tuple[str, ...], resolver: SessionOperationResolver, *, clipboard_declared: bool,
) -> ConversationCapabilities:
    """Read declarations only; never resolve operations or pending approvals."""
    from loushang.harness.session import (
        SessionInputCapability,
        SessionOperationAvailability,
        SessionOperationCapability,
    )
    from loushang.harnesstui.conversation.input_policy import (
        ConversationCapabilities,
        ConversationCapability,
    )

    availability = resolver.availability
    if availability is None:
        availability = SessionOperationAvailability.standard()
    inputs = resolver.input_capabilities
    has_input = availability.supports(SessionOperationCapability.INPUT)

    def declared(operation: ConversationOperation, supported: bool) -> ConversationCapability:
        return ConversationCapability(operation, "available" if supported else "unavailable",
                                      "supported" if supported else "not_supported")

    return ConversationCapabilities(binding_key, (
        ConversationCapability("transcript", "read_only", "read_only"),
        declared("submit", has_input),
        declared("steer", has_input and inputs.supports(SessionInputCapability.STEER)),
        declared("follow_up", has_input and inputs.supports(SessionInputCapability.FOLLOW_UP)),
        declared("interrupt", availability.supports(SessionOperationCapability.LIFECYCLE)
                 and availability.supports(SessionOperationCapability.QUEUE)),
        ConversationCapability("approval_details", "unavailable", "not_projected"),
        ConversationCapability("approve", "unavailable", "not_projected"),
        ConversationCapability("deny", "unavailable", "not_projected"),
        declared("image_paste", True) if clipboard_declared else
        ConversationCapability("image_paste", "unavailable", "not_projected"),
        declared("product_commands", True),  # Standard Coding surface/dispatch is bound by this composition.
    ))

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


def _runtime_observability_context(scope: RuntimeScope):
    return log_context(run_id=scope.run_id)


CODING_SCREEN_RUN_PROFILE = ConversationScreenRunProfile(
    input_router_factory=build_screen_input_router,
    interruption_message=CODING_INTERRUPTION_MESSAGE,
    cancellation_message=CODING_CANCELLATION_MESSAGE,
    runtime=ConversationScreenRuntimeProfile(
        input_router_factory=build_runtime_screen_input_router,
        observe_sweep=_observe_runtime_sweep,
        context_factory=_runtime_observability_context,
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
