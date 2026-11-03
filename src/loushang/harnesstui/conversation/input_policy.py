"""Product-neutral policy and keybindings for Harness conversation input."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Literal, TypeAlias

from loushang.tui.keybindings import (
    KeybindingCatalog,
    KeybindingConfig,
    KeybindingManager,
)

RunningSubmitMode: TypeAlias = Literal["steer", "follow_up"]

ConversationOperation: TypeAlias = Literal[
    "transcript", "submit", "steer", "follow_up", "interrupt",
    "approval_details", "approve", "deny", "image_paste", "product_commands",
]
_OPERATIONS = frozenset({
    "transcript", "submit", "steer", "follow_up", "interrupt",
    "approval_details", "approve", "deny", "image_paste", "product_commands",
})
CapabilityAvailability: TypeAlias = Literal["available", "read_only", "unavailable"]
CapabilityReason: TypeAlias = Literal[
    "supported", "read_only", "no_member", "snapshot_required", "closing",
    "membership_pending", "no_interaction", "presentation_required",
    "protocol_unavailable", "binding_changed", "not_projected", "not_supported",
]
_REASONS = frozenset({
    "supported", "read_only", "no_member", "snapshot_required", "closing",
    "membership_pending", "no_interaction", "presentation_required",
    "protocol_unavailable", "binding_changed", "not_projected", "not_supported",
})


@dataclass(frozen=True, slots=True)
class ConversationCapability:
    """Presentation only: never a permission, receipt, or execution promise."""

    operation: ConversationOperation
    availability: CapabilityAvailability
    reason: CapabilityReason

    def __post_init__(self) -> None:
        if (type(self.operation) is not str or self.operation not in _OPERATIONS
                or type(self.availability) is not str
                or self.availability not in {"available", "read_only", "unavailable"}
                or type(self.reason) is not str or self.reason not in _REASONS):
            raise ValueError("invalid conversation capability")


@dataclass(frozen=True, slots=True)
class ConversationCapabilities:
    """Immutable complete observation, scoped to an opaque view binding.

    Consumers must obtain a fresh projection for current eligibility. Binding
    equality is necessary but not sufficient for reusing an old observation.
    """

    binding_key: tuple[str, ...]
    entries: tuple[ConversationCapability, ...]

    def __post_init__(self) -> None:
        if (type(self.binding_key) is not tuple or not self.binding_key
                or any(type(value) is not str for value in self.binding_key)
                or type(self.entries) is not tuple
                or any(type(entry) is not ConversationCapability for entry in self.entries)
                or len(self.entries) != len(_OPERATIONS)
                or {entry.operation for entry in self.entries} != _OPERATIONS):
            raise ValueError("invalid conversation capability snapshot")

    def get(self, operation: ConversationOperation, *, binding_key: tuple[str, ...]) -> ConversationCapability:
        if binding_key != self.binding_key:
            return ConversationCapability(operation, "unavailable", "binding_changed")
        for entry in self.entries:
            if entry.operation == operation:
                return entry
        raise ValueError("invalid conversation operation")

CONVERSATION_FOLLOW_UP_ACTION = "conversation.input.followUp"
CONVERSATION_PASTE_IMAGE_ACTION = "conversation.input.pasteImage"
CONVERSATION_QUEUE_EDIT_LAST_ACTION = "tui.queue.editLast"
CONVERSATION_KEYBINDING_DEFINITIONS = {
    CONVERSATION_FOLLOW_UP_ACTION: ("alt+enter",),
    CONVERSATION_PASTE_IMAGE_ACTION: ("ctrl+v",),
    CONVERSATION_QUEUE_EDIT_LAST_ACTION: ("alt+up",),
}
CONVERSATION_KEYBINDING_CATALOG = KeybindingCatalog.from_definitions(
    CONVERSATION_KEYBINDING_DEFINITIONS
)
_WINDOWS_CONVERSATION_KEYBINDING_CATALOG = KeybindingCatalog.from_definitions(
    {
        **CONVERSATION_KEYBINDING_DEFINITIONS,
        CONVERSATION_PASTE_IMAGE_ACTION: ("ctrl+v", "alt+v"),
    }
)


@dataclass(frozen=True, slots=True)
class ConversationInputCapabilities:
    """Harness-declared input facts projected into the neutral TUI adapter."""

    steer: bool = True
    follow_up: bool = True

    def supports(self, mode: RunningSubmitMode) -> bool:
        return self.steer if mode == "steer" else self.follow_up


@dataclass(frozen=True, slots=True)
class ConversationInputPolicy:
    """Choose the primary running-submit action with a deterministic fallback."""

    primary_running_submit: RunningSubmitMode = "steer"

    def resolve_running_submit(
        self,
        capabilities: ConversationInputCapabilities,
    ) -> RunningSubmitMode | None:
        primary = self.primary_running_submit
        if capabilities.supports(primary):
            return primary
        fallback: RunningSubmitMode = "follow_up" if primary == "steer" else "steer"
        return fallback if capabilities.supports(fallback) else None


DEFAULT_CONVERSATION_INPUT_POLICY = ConversationInputPolicy()


def conversation_keybinding_manager(
    keybindings: KeybindingManager | KeybindingConfig | None = None,
    *,
    platform_name: str | None = None,
) -> KeybindingManager:
    """Compose conversation actions over generic keybinding definitions."""

    manager = (
        keybindings
        if isinstance(keybindings, KeybindingManager)
        else KeybindingManager(keybindings)
    )
    resolved_platform = sys.platform if platform_name is None else platform_name
    catalog = (
        _WINDOWS_CONVERSATION_KEYBINDING_CATALOG
        if resolved_platform == "win32"
        else CONVERSATION_KEYBINDING_CATALOG
    )
    return manager.with_catalog(catalog)


__all__ = [
    "CONVERSATION_FOLLOW_UP_ACTION",
    "CONVERSATION_KEYBINDING_CATALOG",
    "CONVERSATION_KEYBINDING_DEFINITIONS",
    "CONVERSATION_PASTE_IMAGE_ACTION",
    "CONVERSATION_QUEUE_EDIT_LAST_ACTION",
    "ConversationCapabilities",
    "ConversationCapability",
    "ConversationInputCapabilities",
    "ConversationInputPolicy",
    "DEFAULT_CONVERSATION_INPUT_POLICY",
    "RunningSubmitMode",
    "conversation_keybinding_manager",
]
