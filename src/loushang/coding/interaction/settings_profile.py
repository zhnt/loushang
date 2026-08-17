"""Coding-owned declarations for the shared boolean-settings mechanism."""

from __future__ import annotations

from loushang.harnesstui.settings.schema import (
    BooleanSettingBinding,
    BooleanSettingCopy,
)

CODING_SETTING_BINDINGS = (
    BooleanSettingBinding(
        "terminal.progress",
        "Terminal progress",
        "get_show_terminal_progress",
        "set_show_terminal_progress",
        "Terminal progress",
    ),
    BooleanSettingBinding(
        "terminal.show_images",
        "Show images",
        "get_show_images",
        "set_show_images",
        "Show images",
    ),
    BooleanSettingBinding(
        "terminal.clear_on_shrink",
        "Clear on shrink",
        "get_clear_on_shrink",
        "set_clear_on_shrink",
        "Clear on shrink",
    ),
    BooleanSettingBinding(
        "images.auto_resize",
        "Image auto-resize",
        "get_image_auto_resize",
        "set_image_auto_resize",
        "Image auto-resize",
    ),
    BooleanSettingBinding(
        "images.block_images",
        "Block images",
        "get_block_images",
        "set_block_images",
        "Block images",
    ),
    BooleanSettingBinding(
        "retry.enabled",
        "Retry",
        "get_retry_enabled",
        "set_retry_enabled",
        "Retry",
    ),
)

CODING_SETTING_COPY = BooleanSettingCopy(
    unknown=lambda item_id: f"Unknown setting: {item_id}",
    invalid=lambda binding: f"Invalid {binding.label} value.",
    unavailable=lambda binding: f"{binding.status_label} is not available.",
    applied=lambda binding, enabled: (
        f"{binding.status_label}: {'on' if enabled else 'off'}"
    ),
)

__all__ = [
    "CODING_SETTING_BINDINGS",
    "CODING_SETTING_COPY",
]
