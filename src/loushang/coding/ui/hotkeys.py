from __future__ import annotations

from loushang.coding.ui.screen_input import CODING_CONVERSATION_INPUT_POLICY
from loushang.harnesstui.conversation.input_policy import (
    CONVERSATION_FOLLOW_UP_ACTION,
    CONVERSATION_QUEUE_EDIT_LAST_ACTION,
    ConversationInputCapabilities,
    ConversationInputPolicy,
    conversation_keybinding_manager,
)
from loushang.tui.keybindings import KeybindingConfig, KeybindingManager


def format_hotkeys(
    keybindings: KeybindingManager | KeybindingConfig | None = None,
    *,
    policy: ConversationInputPolicy = CODING_CONVERSATION_INPUT_POLICY,
    capabilities: ConversationInputCapabilities = ConversationInputCapabilities(),
) -> str:
    manager = conversation_keybinding_manager(keybindings)
    submit_key = _action_key(manager, "tui.input.submit")
    follow_up_key = _action_key(manager, CONVERSATION_FOLLOW_UP_ACTION)
    newline_key = _action_key(
        manager,
        "tui.input.newLine",
        preferred="ctrl+j",
    )
    cancel_keys = _action_keys(
        manager,
        "tui.select.cancel",
        separator="-",
    )
    edit_queue_key = _action_key(
        manager,
        CONVERSATION_QUEUE_EDIT_LAST_ACTION,
        separator="-",
    )
    primary_mode = policy.resolve_running_submit(capabilities)
    primary_description = {
        "steer": "steer current run",
        "follow_up": "queue follow-up",
        None: "input unavailable",
    }[primary_mode]
    follow_up_description = (
        "queue follow-up" if capabilities.follow_up else "follow-up unavailable"
    )
    return "\n".join(
        [
            "Hotkeys:",
            f"Idle {submit_key}: submit prompt",
            f"Running {submit_key}: {primary_description}",
            f"Running {follow_up_key}: {follow_up_description}",
            f"{newline_key}: insert newline",
            f"{cancel_keys}: abort running request",
            f"{edit_queue_key}: edit queued messages",
            "/quit or /exit: quit",
        ]
    )


def _action_key(
    manager: KeybindingManager,
    action: str,
    *,
    preferred: str | None = None,
    separator: str = "+",
) -> str:
    keys = manager.keys_for(action)
    if preferred in keys:
        return _format_key(preferred, separator=separator)
    return _format_key(keys[0], separator=separator) if keys else "Unbound"


def _action_keys(
    manager: KeybindingManager,
    action: str,
    *,
    separator: str = "+",
) -> str:
    keys = manager.keys_for(action)
    return (
        "/".join(_format_key(key, separator=separator) for key in keys)
        if keys
        else "Unbound"
    )


def _format_key(key: str, *, separator: str = "+") -> str:
    names = {
        "escape": "Esc",
        "enter": "Enter",
        "up": "Up",
        "down": "Down",
        "left": "Left",
        "right": "Right",
    }
    modifiers = {
        "ctrl": "Ctrl",
        "shift": "Shift",
        "alt": "Alt",
        "super": "Super",
    }
    parts = key.split("+")
    if len(parts) == 1:
        return names.get(key, key.upper() if len(key) == 1 else key.title())
    return separator.join(
        [
            *(modifiers.get(part, part.title()) for part in parts[:-1]),
            names.get(
                parts[-1],
                parts[-1].upper() if len(parts[-1]) == 1 else parts[-1].title(),
            ),
        ]
    )


__all__ = ["format_hotkeys"]
