"""Product-neutral policy and keybindings for Harness conversation input."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from loushang.tui.keybindings import (
    KeybindingCatalog,
    KeybindingConfig,
    KeybindingManager,
)

RunningSubmitMode: TypeAlias = Literal["steer", "follow_up"]

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
) -> KeybindingManager:
    """Compose conversation actions over generic keybinding definitions."""

    manager = (
        keybindings
        if isinstance(keybindings, KeybindingManager)
        else KeybindingManager(keybindings)
    )
    return manager.with_catalog(CONVERSATION_KEYBINDING_CATALOG)


__all__ = [
    "CONVERSATION_FOLLOW_UP_ACTION",
    "CONVERSATION_KEYBINDING_CATALOG",
    "CONVERSATION_KEYBINDING_DEFINITIONS",
    "CONVERSATION_PASTE_IMAGE_ACTION",
    "CONVERSATION_QUEUE_EDIT_LAST_ACTION",
    "ConversationInputCapabilities",
    "ConversationInputPolicy",
    "DEFAULT_CONVERSATION_INPUT_POLICY",
    "RunningSubmitMode",
    "conversation_keybinding_manager",
]
