"""Keybinding catalog owned by HarnessTUI continuity surfaces."""

from __future__ import annotations

from loushang.tui.keybindings import (
    KeybindingCatalog,
    KeybindingConfig,
    KeybindingManager,
)

CONTINUITY_PREVIEW_ACTION = "tui.continuity.preview"
CONTINUITY_DOMAIN_ACTION = "tui.continuity.domain"
CONTINUITY_SORT_ACTION = "tui.continuity.sort"

CONTINUITY_KEYBINDING_DEFINITIONS = {
    CONTINUITY_PREVIEW_ACTION: ("space",),
    CONTINUITY_DOMAIN_ACTION: ("tab",),
    CONTINUITY_SORT_ACTION: ("ctrl+s",),
}
CONTINUITY_KEYBINDING_CATALOG = KeybindingCatalog.from_definitions(
    CONTINUITY_KEYBINDING_DEFINITIONS
)


def continuity_keybinding_manager(
    keybindings: KeybindingManager | KeybindingConfig | None = None,
) -> KeybindingManager:
    manager = (
        keybindings
        if isinstance(keybindings, KeybindingManager)
        else KeybindingManager(keybindings)
    )
    return manager.with_catalog(CONTINUITY_KEYBINDING_CATALOG)


__all__ = [
    "CONTINUITY_DOMAIN_ACTION",
    "CONTINUITY_KEYBINDING_CATALOG",
    "CONTINUITY_KEYBINDING_DEFINITIONS",
    "CONTINUITY_PREVIEW_ACTION",
    "CONTINUITY_SORT_ACTION",
    "continuity_keybinding_manager",
]
