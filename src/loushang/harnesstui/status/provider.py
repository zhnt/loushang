from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import cast

from loushang.harnesstui.status.line import (
    StatusLineAutoValue,
    StatusLineSeparator,
    StatusLineSettings,
    StatusLineStyle,
)
from loushang.harnesstui.status.snapshot import StatusSnapshot


class StatusProvider:
    def __init__(
        self,
        *,
        model_label: str | None,
        cwd: str,
        branch: str | None,
        session_label: Callable[[], str | None],
        thinking_level: Callable[[], str | None],
        running: Callable[[], bool],
        permission_profile: Callable[[], str | None] | None = None,
        statusline_settings: StatusLineSettings | None = None,
        on_statusline_settings_changed: Callable[[StatusLineSettings], None]
        | None = None,
    ) -> None:
        self._model_label = model_label
        self._cwd = cwd
        self._branch = branch
        self._session_label = session_label
        self._thinking_level = thinking_level
        self._running = running
        self._permission_profile = permission_profile or (lambda: None)
        self._statusline_settings = statusline_settings or StatusLineSettings()
        self._on_statusline_settings_changed = on_statusline_settings_changed

    def is_visible(self) -> bool:
        return self._statusline_settings.enabled

    def statusline_settings(self) -> StatusLineSettings:
        return self._statusline_settings

    def update_context(
        self,
        *,
        model_label: str | None,
        cwd: str,
        branch: str | None,
    ) -> None:
        """Refresh session-bound display facts after an in-process switch."""

        self._model_label = model_label
        self._cwd = cwd
        self._branch = branch

    def snapshot(self) -> StatusSnapshot:
        return StatusSnapshot(
            model_label=self._model_label,
            cwd=self._cwd,
            branch=self._branch,
            session_label=self._session_label(),
            thinking_level=self._thinking_level(),
            running=self._running(),
            statusline_visible=self.is_visible(),
            permission_profile=self._permission_profile(),
            statusline_settings=self._statusline_settings,
        )

    def set_visible(self, visible: bool | None) -> str:
        if visible is not None:
            self._set_statusline_settings(
                replace(self._statusline_settings, enabled=visible)
            )
        return f"Status line: {'on' if self.is_visible() else 'off'}"

    def apply_statusline_settings(self, settings: StatusLineSettings) -> str:
        self._set_statusline_settings(settings)
        return self.set_visible(None)

    def apply_statusline_setting(self, item_id: str, value: str) -> str:
        normalized = value.casefold()
        if item_id in {"statusline", "statusline.enabled"}:
            enabled = _as_bool(normalized)
            if enabled is None:
                return "Invalid status line enabled value."
            return self.set_visible(enabled)
        bool_field = _bool_statusline_field(item_id)
        if bool_field is not None:
            enabled = _as_bool(normalized)
            if enabled is None:
                return f"Invalid status line {bool_field.replace('_', ' ')} value."
            # The validated field name and value are compatible, but mypy cannot
            # express field-sensitive typing for dynamic dataclass replacement.
            self._set_statusline_settings(
                replace(self._statusline_settings, **{bool_field: enabled})  # type: ignore[arg-type]
            )
            return f"Status line {bool_field.replace('_', ' ')}: {normalized}"
        if item_id in {"statusline.field.queue", "statusline.field.message"}:
            field_name = item_id.rsplit(".", 1)[-1]
            if normalized not in {"auto", "true", "false"}:
                return f"Invalid status line {field_name} value."
            self._set_statusline_settings(
                replace(
                    self._statusline_settings,
                    **{field_name: cast(StatusLineAutoValue, normalized)},  # type: ignore[arg-type]
                )
            )
            return f"Status line {field_name}: {normalized}"
        if item_id == "statusline.separator":
            if normalized not in {"pipe", "dot"}:
                return "Invalid status line separator value."
            self._set_statusline_settings(
                replace(
                    self._statusline_settings,
                    separator=cast(StatusLineSeparator, normalized),
                )
            )
            return f"Status line separator: {normalized}"
        if item_id == "statusline.style":
            if normalized not in {"codex-like", "muted", "plain"}:
                return "Invalid status line style value."
            self._set_statusline_settings(
                replace(
                    self._statusline_settings, style=cast(StatusLineStyle, normalized)
                )
            )
            return f"Status line style: {normalized}"
        return f"Unknown status line setting: {item_id}"

    def settings_summary_text(self) -> str:
        return f"Settings\nStatus line: {'true' if self.is_visible() else 'false'}"

    def _set_statusline_settings(self, settings: StatusLineSettings) -> None:
        self._statusline_settings = settings
        if self._on_statusline_settings_changed is not None:
            self._on_statusline_settings_changed(settings)


def _as_bool(value: str) -> bool | None:
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def _bool_statusline_field(item_id: str) -> str | None:
    return {
        "statusline.field.model": "model",
        "statusline.field.workspace": "workspace",
        "statusline.field.branch": "branch",
        "statusline.field.session": "session",
        "statusline.field.permissions": "permissions",
        "statusline.field.runtime": "runtime",
    }.get(item_id)


__all__ = ["StatusProvider"]
