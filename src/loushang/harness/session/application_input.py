from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from loushang.harness.transcript import (
    ApplicationDeliveryMode,
    ApplicationMessage,
    CommitResult,
)

CommitApplicationMessage = Callable[[ApplicationMessage], Awaitable[CommitResult]]
DirectApplicationProjector = Callable[[ApplicationMessage, str], Awaitable[None]]
TriggerTurnRunner = Callable[[ApplicationMessage], Awaitable[None]]
VisibleText = Callable[[ApplicationMessage], str]
ApplicationInputDisposition = Literal[
    "staged",
    "committed",
    "already_committed",
    "queued",
    "triggered",
]


class ApplicationInputQueuePort(Protocol):
    def append_next_turn_message(self, message: object) -> None: ...

    def queue_steering_message(self, visible_text: str, message: object) -> None: ...

    def queue_follow_up_message(self, visible_text: str, message: object) -> None: ...

    def has_pending_messages(self) -> bool: ...


@dataclass(frozen=True)
class ApplicationInputDelivery:
    application_message_id: str
    delivery_mode: ApplicationDeliveryMode
    disposition: ApplicationInputDisposition
    record_id: str | None = None


@dataclass
class ApplicationInputRuntime:
    """Route application input while one injected committer owns durability."""

    commit_application_message: CommitApplicationMessage
    queue: ApplicationInputQueuePort
    project_direct: DirectApplicationProjector
    run_trigger_turn: TriggerTurnRunner
    visible_text: VisibleText = lambda message: _visible_text(message)
    _projected_direct_message_ids: set[str] = field(
        default_factory=set,
        init=False,
        repr=False,
    )

    async def deliver(self, message: ApplicationMessage) -> ApplicationInputDelivery:
        if message.delivery_mode == "direct":
            return await self._commit_direct(message)
        if message.delivery_mode == "trigger_turn":
            await self.run_trigger_turn(message)
            return _delivery(message, disposition="triggered")
        if message.delivery_mode == "next_turn":
            self.queue.append_next_turn_message(message)
            return _delivery(message, disposition="queued")
        if message.delivery_mode == "steering":
            self.queue.queue_steering_message(self.visible_text(message), message)
            return _delivery(message, disposition="queued")
        if message.delivery_mode == "follow_up":
            self.queue.queue_follow_up_message(self.visible_text(message), message)
            return _delivery(message, disposition="queued")
        raise ValueError(
            f"Unsupported application delivery mode: {message.delivery_mode}"
        )

    def has_pending_messages(self) -> bool:
        return self.queue.has_pending_messages()

    async def _commit_direct(
        self, message: ApplicationMessage
    ) -> ApplicationInputDelivery:
        result = await self.commit_application_message(message)
        if message.application_message_id not in self._projected_direct_message_ids:
            await self.project_direct(message, result.record_id)
            self._projected_direct_message_ids.add(message.application_message_id)
        return _delivery(
            message,
            disposition=result.disposition,
            record_id=result.record_id,
        )


def _delivery(
    message: ApplicationMessage,
    *,
    disposition: ApplicationInputDisposition,
    record_id: str | None = None,
) -> ApplicationInputDelivery:
    return ApplicationInputDelivery(
        application_message_id=message.application_message_id,
        delivery_mode=message.delivery_mode,
        disposition=disposition,
        record_id=record_id,
    )


def _visible_text(message: ApplicationMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    text_parts: list[str] = []
    for part in message.content:
        if getattr(part, "type", None) != "text":
            continue
        text = getattr(part, "text", None)
        if isinstance(text, str):
            text_parts.append(text)
    if text_parts:
        return "\n".join(text_parts)
    return "[image]" if message.content else ""


__all__ = [
    "ApplicationInputDelivery",
    "ApplicationInputRuntime",
]
