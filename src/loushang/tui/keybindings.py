from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

KeyId = str
KeybindingAction = str
KeybindingConfig = Mapping[KeybindingAction, KeyId | Sequence[KeyId] | None]


DEFAULT_KEYBINDINGS: dict[KeybindingAction, tuple[KeyId, ...]] = {
    "tui.editor.cursorUp": ("up",),
    "tui.editor.cursorDown": ("down",),
    "tui.editor.cursorLeft": ("left", "ctrl+b"),
    "tui.editor.cursorRight": ("right", "ctrl+f"),
    "tui.editor.cursorWordLeft": ("alt+left", "ctrl+left", "alt+b"),
    "tui.editor.cursorWordRight": ("alt+right", "ctrl+right", "alt+f"),
    "tui.editor.cursorLineStart": ("home", "ctrl+a", "alt+<"),
    "tui.editor.cursorLineEnd": ("end", "ctrl+e", "alt+>"),
    "tui.editor.selectCharLeft": ("shift+left",),
    "tui.editor.selectCharRight": ("shift+right",),
    "tui.editor.selectWordLeft": ("ctrl+shift+left", "alt+shift+b"),
    "tui.editor.selectWordRight": ("ctrl+shift+right", "alt+shift+f"),
    "tui.editor.selectLineStart": ("shift+home",),
    "tui.editor.selectLineEnd": ("shift+end",),
    "tui.editor.jumpForward": ("ctrl+]",),
    "tui.editor.jumpBackward": ("ctrl+alt+]",),
    "tui.editor.pageUp": ("pageUp",),
    "tui.editor.pageDown": ("pageDown",),
    "tui.editor.deleteCharBackward": ("backspace",),
    "tui.editor.deleteCharForward": ("delete", "ctrl+d"),
    "tui.editor.deleteWordBackward": ("ctrl+w", "alt+backspace"),
    "tui.editor.deleteWordForward": ("alt+d", "alt+delete"),
    "tui.editor.deleteToLineStart": ("ctrl+u",),
    "tui.editor.deleteToLineEnd": ("ctrl+k",),
    "tui.editor.yank": ("ctrl+y",),
    "tui.editor.yankPop": ("alt+y",),
    "tui.editor.undo": ("ctrl+-", "ctrl+_", "alt+u"),
    "tui.editor.redo": ("alt+r",),
    "tui.input.newLine": ("shift+enter", "alt+enter", "ctrl+j"),
    "tui.input.submit": ("enter",),
    "tui.input.tab": ("tab",),
    "tui.input.copy": ("ctrl+c",),
    "tui.transcript.open": ("ctrl+o",),
    "app.clipboard.pasteImage": ("ctrl+v",),
    "tui.queue.editLast": ("alt+up",),
    "tui.select.up": ("up", "shift+tab"),
    "tui.select.down": ("down", "alt+down"),
    "tui.select.pageUp": ("pageUp",),
    "tui.select.pageDown": ("pageDown",),
    "tui.select.confirm": ("enter",),
    "tui.select.cancel": ("escape", "ctrl+c"),
    "tui.continuity.preview": ("space",),
    "tui.continuity.domain": ("tab",),
    "tui.continuity.sort": ("ctrl+s",),
}

_MODIFIER_ORDER = ("ctrl", "shift", "alt", "super")
_ALIASES = {
    "esc": "escape",
    "return": "enter",
    "alt_enter": "alt+enter",
    "alt_up": "alt+up",
    "alt_down": "alt+down",
    "alt_left": "alt+left",
    "alt_right": "alt+right",
    "ctrl_a": "ctrl+a",
    "ctrl_b": "ctrl+b",
    "ctrl_c": "ctrl+c",
    "ctrl_d": "ctrl+d",
    "ctrl_e": "ctrl+e",
    "ctrl_f": "ctrl+f",
    "ctrl_g": "ctrl+g",
    "ctrl_j": "ctrl+j",
    "ctrl_k": "ctrl+k",
    "ctrl_o": "ctrl+o",
    "ctrl_u": "ctrl+u",
    "ctrl_w": "ctrl+w",
    "ctrl_y": "ctrl+y",
    "alt_y": "alt+y",
}


@dataclass(frozen=True, slots=True)
class KeybindingConflict:
    key: KeyId
    action_ids: tuple[KeybindingAction, ...]


class KeybindingManager:
    def __init__(
        self,
        user_bindings: KeybindingConfig | None = None,
        definitions: Mapping[KeybindingAction, Sequence[KeyId]] | None = None,
    ) -> None:
        self._definitions = {
            action: tuple(normalize_key_id(key) for key in keys)
            for action, keys in (definitions or DEFAULT_KEYBINDINGS).items()
        }
        self._user_bindings = dict(user_bindings or {})
        self._resolved: dict[KeybindingAction, tuple[KeyId, ...]] = {}
        self._conflicts: tuple[KeybindingConflict, ...] = ()
        self._rebuild()

    def matches(self, key: KeyId, action: KeybindingAction) -> bool:
        return normalize_key_id(key) in self._resolved.get(action, ())

    def keys_for(self, action: KeybindingAction) -> tuple[KeyId, ...]:
        return self._resolved.get(action, ())

    def conflicts(self) -> tuple[KeybindingConflict, ...]:
        return self._conflicts

    def resolved(self) -> dict[KeybindingAction, tuple[KeyId, ...]]:
        return dict(self._resolved)

    def _rebuild(self) -> None:
        claims: dict[KeyId, set[KeybindingAction]] = {}
        for action, keys in self._user_bindings.items():
            if action not in self._definitions:
                continue
            for key in _normalize_keys(keys):
                claims.setdefault(key, set()).add(action)

        self._conflicts = tuple(
            KeybindingConflict(key=key, action_ids=tuple(sorted(action_ids)))
            for key, action_ids in sorted(claims.items())
            if len(action_ids) > 1
        )

        for action, default_keys in self._definitions.items():
            user_keys = self._user_bindings.get(action, None)
            self._resolved[action] = (
                default_keys if user_keys is None else _normalize_keys(user_keys)
            )


def normalize_key_id(key: KeyId) -> KeyId:
    key = (
        _ALIASES.get(key, key)
        .replace("pageup", "pageUp")
        .replace("pagedown", "pageDown")
    )
    parts = key.split("+")
    if len(parts) <= 1:
        return key
    base = parts[-1]
    modifiers = [part for part in _MODIFIER_ORDER if part in parts[:-1]]
    return "+".join([*modifiers, base])


def _normalize_keys(keys: KeyId | Sequence[KeyId] | None) -> tuple[KeyId, ...]:
    if keys is None:
        return ()
    raw_keys = (keys,) if isinstance(keys, str) else tuple(keys)
    seen: set[KeyId] = set()
    normalized: list[KeyId] = []
    for key in raw_keys:
        normalized_key = normalize_key_id(key)
        if normalized_key in seen:
            continue
        seen.add(normalized_key)
        normalized.append(normalized_key)
    return tuple(normalized)
