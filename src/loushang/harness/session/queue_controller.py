from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, cast

from loushang.ai.types import ImagePart, TextPart, UserMessage
from loushang.foundation.observability import get_log
from loushang.harness.events.session import (
    QueuedMessageSnapshot,
    QueueKind,
    QueueSnapshot,
)
from loushang.harness.runtime.input_queue import HostInputQueue
from loushang.harness.runtime.turn import TurnInputQueue
from loushang.harness.runtime.types import QueueMode

PreflightUserInput = Callable[[str], object]
RejectExtensionCommand = Callable[[str], None]
QueueUpdateEmitter = Callable[[], None]

log = get_log(__name__).bind(component="QueueController")


class AgentQueueStatePort(Protocol):
    messages: list[object]


class AgentQueuePort(Protocol):
    state: AgentQueueStatePort
    steering_mode: QueueMode
    follow_up_mode: QueueMode

    def clear_all_queues(self) -> None: ...

    def has_queued_messages(self) -> bool: ...

    def steer(self, message: object) -> object: ...

    def follow_up(self, message: object) -> object: ...

    def enqueue_mailbox(self, message: object) -> object: ...


@dataclass
class QueueController:
    agent: AgentQueuePort
    preflight_user_input: PreflightUserInput
    reject_extension_command: RejectExtensionCommand
    emit_queue_update: QueueUpdateEmitter
    _queue: TurnInputQueue[object] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._queue = TurnInputQueue(
            submit=self._submit,
            clear_delivery_queue=self.agent.clear_all_queues,
            has_delivery_messages=self.agent.has_queued_messages,
            notify=self.emit_queue_update,
            observe=self._observe_queue_event,
        )

    @property
    def pending_message_count(self) -> int:
        return self._queue.pending_count

    @property
    def input_queue(self) -> HostInputQueue[object]:
        """Expose the existing queue to Product-neutral input facades."""

        return self._queue

    def get_steering_messages(self) -> list[str]:
        return self._queue.texts("steering")

    def get_follow_up_messages(self) -> list[str]:
        return self._queue.texts("follow_up")

    def get_queue_snapshot(self) -> QueueSnapshot:
        return self._queue.snapshot()

    def append_next_turn_message(self, message: object) -> None:
        self._queue.append_next_turn(message)

    def drain_next_turn_messages(self) -> list[object]:
        return self._queue.drain_next_turn()

    def has_pending_messages(self) -> bool:
        return self._queue.has_pending()

    def steer(self, user_input: str, images: list[ImagePart] | None = None) -> None:
        self.reject_extension_command(user_input)
        preflight = self.preflight_user_input(user_input)
        if getattr(preflight, "consumed", False):
            return
        self.queue_prepared_steering(str(getattr(preflight, "text")), images=images)

    def follow_up(self, user_input: str, images: list[ImagePart] | None = None) -> None:
        self.reject_extension_command(user_input)
        preflight = self.preflight_user_input(user_input)
        if getattr(preflight, "consumed", False):
            return
        self.queue_prepared_follow_up(str(getattr(preflight, "text")), images=images)

    def queue_prepared_steering(
        self, text: str, images: list[ImagePart] | None = None
    ) -> None:
        self.queue_steering_message(text, _user_message(text, images=images))

    def queue_prepared_follow_up(
        self, text: str, images: list[ImagePart] | None = None
    ) -> None:
        self.queue_follow_up_message(text, _user_message(text, images=images))

    def queue_steering_message(self, visible_text: str, message: object) -> None:
        self._queue.enqueue(
            "steering",
            text=visible_text,
            payload=message,
        )

    def queue_follow_up_message(self, visible_text: str, message: object) -> None:
        self._queue.enqueue(
            "follow_up",
            text=visible_text,
            payload=message,
        )

    def queue_mailbox_message(self, message: object) -> None:
        """Deliver system input without creating an editable queue snapshot."""

        self.agent.enqueue_mailbox(message)

    def clear_queue(self) -> dict[str, list[str]]:
        steering = self.get_steering_messages()
        follow_up = self.get_follow_up_messages()
        self._queue.clear()
        log.debug_event(
            "agent", "queue.cleared", steering=len(steering), follow_up=len(follow_up)
        )
        return {"steering": steering, "followUp": follow_up, "follow_up": follow_up}

    def mark_message_consumed(self, message: object) -> bool:
        return self._queue.consume_visible(
            message,
            fallback_text=_visible_message_text(message),
        )

    def prepare_continue_run(self) -> bool:
        last_message = (
            self.agent.state.messages[-1] if self.agent.state.messages else None
        )
        return self._queue.prepare_continue(
            previous_turn_completed=getattr(last_message, "role", None) == "assistant",
            steering_mode=cast(QueueMode, self.agent.steering_mode),
            follow_up_mode=cast(QueueMode, self.agent.follow_up_mode),
        )

    def _submit(self, kind: QueueKind, message: object) -> object:
        if kind == "steering":
            return self.agent.steer(message)
        return self.agent.follow_up(message)

    @staticmethod
    def _observe_queue_event(event: str, item: QueuedMessageSnapshot) -> None:
        _debug_queue_event(f"queue.message_{event}", item)


def _user_message(text: str, images: list[ImagePart] | None = None) -> UserMessage:
    content: list[TextPart | ImagePart] = [TextPart(type="text", text=text)]
    if images:
        content.extend(images)
    return UserMessage(role="user", content=content, timestamp=0.0)


def _visible_message_text(message: object) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            _content_part_text(part) or ""
            for part in content
            if _content_part_type(part) == "text"
        )
    return ""


def _content_part_type(part: object) -> str | None:
    if isinstance(part, dict):
        value = part.get("type")
        return value if isinstance(value, str) else None
    value = getattr(part, "type", None)
    return value if isinstance(value, str) else None


def _content_part_text(part: object) -> str | None:
    if isinstance(part, dict):
        value = part.get("text")
        return value if isinstance(value, str) else None
    value = getattr(part, "text", None)
    return value if isinstance(value, str) else None


def _debug_queue_event(name: str, item: QueuedMessageSnapshot) -> None:
    log.debug_event("agent", name, id=item.id, kind=item.kind, text_len=len(item.text))
