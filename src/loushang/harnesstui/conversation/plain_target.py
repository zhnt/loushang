from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from loushang.harnesstui.conversation.projection import (
    ConversationProjectionBinding,
    ConversationProjector,
)
from loushang.harnesstui.conversation.tool_transcript import (
    ToolCallSnapshot,
    ToolTranscriptBlock,
    ToolTranscriptProjector,
)

ProjectionEventT = TypeVar("ProjectionEventT")


class PlainConversationProjectionPort(Protocol):
    """Render product-neutral conversation content for a plain surface."""

    def render_user(self, text: str) -> None: ...

    def begin_assistant(self) -> None: ...

    def write_assistant_delta(self, text: str) -> None: ...

    def end_assistant(self, final_text: str) -> None: ...

    def render_error(self, text: str) -> None: ...

    def render_tool_block(self, block: ToolTranscriptBlock) -> None: ...

    def render_status(self, text: str) -> None: ...


@dataclass(slots=True)
class PlainConversationProjectionTarget:
    """Map projected conversation facts onto a plain renderer."""

    renderer: PlainConversationProjectionPort

    def run_started(self, *, start_time: Callable[[], float]) -> None:
        del start_time

    def queues_updated(
        self,
        *,
        steers: tuple[str, ...],
        followups: tuple[str, ...],
    ) -> None:
        del steers, followups

    def user_message(self, text: str) -> None:
        self.renderer.render_user(text)

    def assistant_started(self) -> None:
        self.renderer.begin_assistant()

    def assistant_delta(self, delta: str) -> None:
        self.renderer.write_assistant_delta(delta)

    def assistant_finished(
        self,
        final_text: str,
        *,
        error_message: str | None,
        show_error: bool,
    ) -> None:
        # Plain output must not commit an errored (including intentionally aborted)
        # assistant draft. The next run replaces the pending draft buffer.
        if error_message is not None:
            if show_error:
                self.renderer.render_error(error_message)
            return
        self.renderer.end_assistant(final_text)

    def assistant_error(self, error_message: str) -> None:
        self.renderer.render_error(error_message)

    def tool_started(
        self,
        tool_call_id: str,
        snapshot: ToolCallSnapshot,
    ) -> None:
        del tool_call_id, snapshot

    def tool_finished(
        self,
        block: ToolTranscriptBlock,
        *,
        elapsed_seconds: float,
    ) -> None:
        del elapsed_seconds
        self.renderer.render_tool_block(block)

    def tool_result_message(self, block: ToolTranscriptBlock) -> None:
        self.renderer.render_tool_block(block)

    def retry_started(
        self,
        *,
        attempt: int | None,
        max_attempts: int | None,
        delay_ms: int | float | None,
        error_message: str | None,
    ) -> None:
        self.renderer.render_status(
            f"[retry] attempt {attempt}/{max_attempts} in {delay_ms}ms: {error_message}"
        )

    def compaction_started(self, *, reason: str | None) -> None:
        self.renderer.render_status(f"[compact] start: {reason}")

    def compaction_finished(
        self,
        *,
        error_message: str | None,
        summary: str,
        tokens_before: int | None,
    ) -> None:
        del summary, tokens_before
        if error_message:
            self.renderer.render_status(f"[compact] error: {error_message}")
        else:
            self.renderer.render_status("[compact] done")


def build_plain_conversation_projection(
    renderer: PlainConversationProjectionPort,
    *,
    tool_projector: ToolTranscriptProjector,
    event_handler_factory: Callable[
        [ConversationProjector], Callable[[ProjectionEventT], None]
    ],
    tool_calls: dict[str, ToolCallSnapshot] | None = None,
    rendered_tool_results: set[str] | None = None,
    rendered_assistant_errors: set[int | str] | None = None,
    last_error_message: str | None = None,
) -> ConversationProjectionBinding[ProjectionEventT]:
    """Build a plain target, neutral projector, and product event binding."""

    projector = ConversationProjector(
        target=PlainConversationProjectionTarget(renderer=renderer),
        tool_projector=tool_projector,
        measure_tool_elapsed=False,
        tool_finish_cleanup="before_projection",
        tool_calls=tool_calls if tool_calls is not None else {},
        rendered_tool_results=(
            rendered_tool_results if rendered_tool_results is not None else set()
        ),
        rendered_assistant_errors=(
            rendered_assistant_errors
            if rendered_assistant_errors is not None
            else set()
        ),
        last_error_message=last_error_message,
    )
    return ConversationProjectionBinding(
        projector=projector,
        event_handler=event_handler_factory(projector),
    )


__all__ = [
    "PlainConversationProjectionPort",
    "PlainConversationProjectionTarget",
    "build_plain_conversation_projection",
]
