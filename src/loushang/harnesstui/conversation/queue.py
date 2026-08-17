"""Product-neutral pending conversation queue helpers."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from loushang.harness.session import SessionOperationRuntime
from loushang.tui import PendingQueueView, PendingSection


class TraceFn(Protocol):
    def __call__(self, name: str, **data: Any) -> None: ...


def pending_queue_view(operations: SessionOperationRuntime) -> PendingQueueView:
    """Project a typed Session queue into a TUI view."""
    return PendingQueueView(
        sections=(
            PendingSection(
                label="Messages to be submitted after next tool call",
                items=tuple(session_pending_messages(operations, "steering")),
                hint="press esc to interrupt and send immediately",
            ),
            PendingSection(
                label="Messages to be submitted at end of turn",
                items=tuple(session_pending_messages(operations, "follow_up")),
            ),
        )
    )


def session_pending_messages(
    operations: SessionOperationRuntime,
    queue: Literal["steering", "follow_up"],
) -> list[str]:
    """Read and normalize a pending-message collection defensively."""
    try:
        messages = (
            operations.get_steering_messages()
            if queue == "steering"
            else operations.get_follow_up_messages()
        )
    except Exception:
        return []
    return [str(message) for message in messages]


def cleared_queue_messages(cleared: Any) -> list[str]:
    """Normalize the supported shapes returned by a queue-clearing operation."""
    if not isinstance(cleared, dict):
        return []
    steering = _safe_message_list(cleared.get("steering"))
    follow_up = _safe_message_list(cleared.get("follow_up"))
    if not follow_up:
        follow_up = _safe_message_list(cleared.get("followUp"))
    return [*steering, *follow_up]


async def restore_queued_messages(
    operations: SessionOperationRuntime,
    current_text: str,
    *,
    trace: TraceFn | None = None,
) -> str | None:
    """Clear a typed Session queue and prepend its messages to the draft."""
    try:
        cleared = operations.clear_queue()
    except Exception:
        _trace(trace, "queue.dequeue.unavailable")
        return None
    queued = cleared_queue_messages(cleared)
    if not queued:
        _trace(trace, "queue.dequeue.empty")
        return None
    _trace(trace, "queue.dequeued", count=len(queued), current_text_len=len(current_text))
    return "\n\n".join([*queued, current_text] if current_text.strip() else queued)


def _safe_message_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _trace(trace: TraceFn | None, name: str, **data: Any) -> None:
    if trace is not None:
        trace(name, **data)


__all__ = [
    "cleared_queue_messages",
    "pending_queue_view",
    "restore_queued_messages",
    "session_pending_messages",
]
