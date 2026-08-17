from __future__ import annotations

from loushang.coding.control import StatusLineControlSettings
from loushang.harnesstui.status.line import (
    StatusLineSettings,
    status_line_settings_to_patch,
)


class _SettingsManager:
    def __init__(self, settings: object) -> None:
        self.settings = settings
        self.saved: list[tuple[dict[str, object], str]] = []

    def get_statusline_settings(self) -> object:
        return self.settings

    def set_statusline_settings(self, patch: dict[str, object], *, scope: str) -> None:
        self.saved.append((patch, scope))


def test_statusline_settings_adapter_reads_settings_store() -> None:
    from loushang.harnesstui.status.persistence import (
        statusline_settings_from_store,
    )

    control_settings = StatusLineControlSettings(
        enabled=False,
        queue="true",
        separator="dot",
        style="muted",
    )
    manager = _SettingsManager(control_settings)

    assert statusline_settings_from_store(manager) == StatusLineSettings(
        enabled=False,
        queue="true",
        separator="dot",
        style="muted",
    )
    assert statusline_settings_from_store(None) is None
    assert statusline_settings_from_store(object()) is None


def test_statusline_settings_adapter_persists_patch_in_requested_scope() -> None:
    from loushang.harnesstui.status.persistence import (
        statusline_settings_persistence_callback,
    )

    settings = StatusLineSettings(enabled=False, queue="true", style="plain")
    manager = _SettingsManager(StatusLineSettings())

    callback = statusline_settings_persistence_callback(manager, scope="workspace")

    assert callback is not None
    callback(settings)
    assert manager.saved == [(status_line_settings_to_patch(settings), "workspace")]

    default_callback = statusline_settings_persistence_callback(manager)
    assert default_callback is not None
    default_callback(settings)
    assert manager.saved[-1] == (status_line_settings_to_patch(settings), "global")
    assert statusline_settings_persistence_callback(None) is None
    assert statusline_settings_persistence_callback(object()) is None
