"""Typed extension-originated input delivery for a live Agent profile.

Products parse their extension wire API before constructing these requests.
This profile never imports ``harness.session`` or accepts raw extension
dictionaries.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from loushang.ai.types import ImagePart
from loushang.harness.transcript import ApplicationMessage


class ApplicationInputDeliveryPort(Protocol):
    """Application-message delivery capability supplied by session assembly."""

    async def deliver(self, message: ApplicationMessage) -> object: ...

    def has_pending_messages(self) -> bool: ...


class PreparedUserInputQueuePort(Protocol):
    """Prepared user-input queue capability supplied by session assembly."""

    def queue_prepared_steering(
        self, text: str, images: list[ImagePart] | None = None
    ) -> None: ...

    def queue_prepared_follow_up(
        self, text: str, images: list[ImagePart] | None = None
    ) -> None: ...


RunPrompt = Callable[[str, list[ImagePart] | None], Awaitable[None]]
UserInputDeliveryMode = Literal["prompt", "steering", "follow_up"]


@dataclass(frozen=True)
class ExtensionApplicationInput:
    """A normalized extension application message ready for delivery."""

    message: ApplicationMessage


@dataclass(frozen=True)
class ExtensionUserInput:
    """A normalized user prompt, steering item, or follow-up item."""

    text: str
    images: list[ImagePart] | None = None
    delivery_mode: UserInputDeliveryMode = "prompt"


@dataclass
class ExtensionInputRuntime:
    """Deliver normalized input through injected application and queue ports."""

    application_inputs: ApplicationInputDeliveryPort
    prepared_user_inputs: PreparedUserInputQueuePort
    run_prompt: RunPrompt

    async def deliver_application_input(self, request: ExtensionApplicationInput) -> None:
        await self.application_inputs.deliver(request.message)

    async def deliver_user_input(self, request: ExtensionUserInput) -> None:
        if request.delivery_mode == "prompt":
            await self.run_prompt(request.text, request.images)
            return
        if request.delivery_mode == "steering":
            self.prepared_user_inputs.queue_prepared_steering(
                request.text, images=request.images
            )
            return
        self.prepared_user_inputs.queue_prepared_follow_up(
            request.text, images=request.images
        )

    def has_pending_messages(self) -> bool:
        return self.application_inputs.has_pending_messages()


__all__ = [
    "ApplicationInputDeliveryPort",
    "ExtensionApplicationInput",
    "ExtensionInputRuntime",
    "ExtensionUserInput",
    "PreparedUserInputQueuePort",
]
