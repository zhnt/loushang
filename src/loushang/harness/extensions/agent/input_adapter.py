"""Wire adapter for the shared extension Agent input profile.

The adapter is Product-neutral: Products bind their public extension message
shape to this normalized input runtime while Harness owns delivery policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, cast
from uuid import uuid4

from loushang.ai.types import ImagePart
from loushang.harness.extensions.agent.input import (
    ExtensionApplicationInput,
    ExtensionInputRuntime,
    ExtensionUserInput,
    UserInputDeliveryMode,
)
from loushang.harness.transcript import ApplicationDeliveryMode, ApplicationMessage


class ExtensionInputAgentPort(Protocol):
    """The minimal live-Agent state needed for Coding wire-policy decisions."""

    @property
    def is_streaming(self) -> bool: ...


@dataclass
class ExtensionInputAdapter:
    """Normalize extension input and call the typed shared runtime."""

    agent: ExtensionInputAgentPort
    runtime: ExtensionInputRuntime

    async def send_message(
        self, message: object, options: object | None = None
    ) -> None:
        if not isinstance(message, dict):
            raise TypeError("send_message expects a message object.")
        custom_type = message.get("customType", message.get("custom_type"))
        if not isinstance(custom_type, str) or not custom_type:
            raise ValueError("send_message requires custom_type.")
        content = message.get("content", "")
        normalized_content = content if isinstance(content, str | list) else str(content)
        opts = options if isinstance(options, dict) else {}
        app_message = ApplicationMessage(
            application_message_id=str(uuid4()),
            custom_type=custom_type,
            content=normalized_content,
            display=bool(message.get("display", True)),
            details=message.get("details"),
            timestamp=datetime.now(timezone.utc).timestamp(),
            origin="extension",
            delivery_mode=_application_delivery_mode(
                deliver_as=opts.get("deliverAs", opts.get("deliver_as")),
                trigger_turn=bool(opts.get("triggerTurn", opts.get("trigger_turn"))),
                streaming=self.agent.is_streaming,
            ),
        )
        await self.runtime.deliver_application_input(
            ExtensionApplicationInput(message=app_message)
        )

    async def send_user_message(
        self, content: object, options: object | None = None
    ) -> None:
        text, images = _normalize_user_content(content)
        opts = options if isinstance(options, dict) else {}
        if not self.agent.is_streaming:
            await self.runtime.deliver_user_input(
                ExtensionUserInput(text=text, images=images)
            )
            return
        deliver_as = opts.get("deliverAs", opts.get("deliver_as"))
        if deliver_as in {"followUp", "follow_up"}:
            mode: UserInputDeliveryMode = "follow_up"
        elif deliver_as == "steer":
            mode = "steering"
        else:
            raise RuntimeError(
                "Agent is already processing. Specify deliverAs "
                "('steer' or 'followUp') to queue the message."
            )
        await self.runtime.deliver_user_input(
            ExtensionUserInput(text=text, images=images, delivery_mode=mode)
        )

    def has_pending_messages(self) -> bool:
        return self.runtime.has_pending_messages()


def _application_delivery_mode(
    *, deliver_as: object, trigger_turn: bool, streaming: bool
) -> ApplicationDeliveryMode:
    if deliver_as in {"nextTurn", "next_turn"}:
        return "next_turn"
    if deliver_as in {"followUp", "follow_up"}:
        return "follow_up"
    if streaming:
        return "steering"
    if trigger_turn:
        return "trigger_turn"
    return "direct"


def _normalize_user_content(content: object) -> tuple[str, list[ImagePart] | None]:
    if isinstance(content, str):
        return content, None
    if not isinstance(content, list):
        raise TypeError("send_user_message expects a string or content block list.")
    text_parts: list[str] = []
    images: list[ImagePart] = []
    for part in content:
        part_type = _part_type(part)
        if part_type == "text":
            text = _part_text(part)
            if text is not None:
                text_parts.append(text)
        elif part_type == "image":
            images.append(cast(ImagePart, part))
    return "\n".join(text_parts), images or None


def _part_type(part: object) -> str | None:
    value = part.get("type") if isinstance(part, dict) else getattr(part, "type", None)
    return value if isinstance(value, str) else None


def _part_text(part: object) -> str | None:
    value = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
    return value if isinstance(value, str) else None


__all__ = ["ExtensionInputAdapter"]
