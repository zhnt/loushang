from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from loushang.agent.types import AgentMessage, AgentToolResult, CustomAgentMessage
from loushang.ai.json_codec import (
    deserialize_message,
    serialize_content_part,
    serialize_message,
)
from loushang.ai.types import AssistantMessage, ToolResultMessage, UserMessage
from loushang.foundation.json import require_json_value

CustomMessageSerializer = Callable[[CustomAgentMessage], dict[str, Any]]
CustomMessageDeserializer = Callable[[dict[str, Any]], CustomAgentMessage]


@dataclass(frozen=True)
class CustomMessageJsonCodec:
    role: str
    message_type: type[CustomAgentMessage]
    serialize: CustomMessageSerializer
    deserialize: CustomMessageDeserializer


class AgentMessageJsonCodec:
    """Compose the AI message codec with product-provided message codecs."""

    def __init__(self, registrations: Iterable[CustomMessageJsonCodec] = ()) -> None:
        self._by_role: dict[str, CustomMessageJsonCodec] = {}
        self._registrations: list[CustomMessageJsonCodec] = []
        for registration in registrations:
            self.register(registration)

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(self._by_role)

    def register(self, registration: CustomMessageJsonCodec) -> None:
        role = registration.role
        if not role:
            raise ValueError("Custom message codec role must not be empty.")
        if role in self._by_role:
            raise ValueError(f"Custom message codec role is already registered: {role}")
        if any(
            existing.message_type is registration.message_type
            for existing in self._registrations
        ):
            raise ValueError(
                "Custom message codec type is already registered: "
                f"{registration.message_type.__name__}"
            )
        self._by_role[role] = registration
        self._registrations.append(registration)

    def serialize(self, message: AgentMessage) -> dict[str, Any]:
        if isinstance(message, UserMessage | AssistantMessage | ToolResultMessage):
            return serialize_message(message)
        for registration in self._registrations:
            if isinstance(message, registration.message_type):
                payload = registration.serialize(message)
                encoded_role = payload.get("role")
                if encoded_role != registration.role:
                    raise ValueError(
                        "Custom message codec emitted an unexpected role: "
                        f"expected {registration.role!r}, got {encoded_role!r}"
                    )
                return payload
        raise ValueError(f"Unsupported custom agent message type: {type(message)!r}")

    def deserialize(self, payload: dict[str, Any]) -> AgentMessage:
        role = payload["role"]
        if role in {"user", "assistant", "toolResult"}:
            return deserialize_message(payload)
        registration = self._by_role.get(role)
        if registration is None:
            raise ValueError(f"Unsupported custom agent message role: {role}")
        message = registration.deserialize(payload)
        if not isinstance(message, registration.message_type):
            raise TypeError(
                "Custom message codec returned an unexpected type: "
                f"expected {registration.message_type.__name__}, "
                f"got {type(message).__name__}"
            )
        return message


def serialize_tool_result(
    result: AgentToolResult[Any],
    *,
    target: str = "event",
) -> dict[str, Any]:
    if target == "event":
        snapshot = result.for_event()
        details = snapshot.event_details()
    elif target == "transcript":
        snapshot = result.for_presentation()
        details = snapshot.transcript_details()
    elif target == "hook":
        snapshot = result.for_hook()
        details = snapshot.hook_details()
    else:
        raise ValueError(f"Unsupported tool result projection target: {target}")
    payload = require_json_value(
        {
            "content": [serialize_content_part(part) for part in snapshot.content],
            "details": details,
            "terminate": snapshot.terminate,
        },
        name="tool_result",
    )
    if not isinstance(payload, dict):
        raise TypeError("Serialized tool results must be JSON objects")
    return payload


__all__ = [
    "AgentMessageJsonCodec",
    "CustomMessageDeserializer",
    "CustomMessageJsonCodec",
    "CustomMessageSerializer",
    "serialize_tool_result",
]
