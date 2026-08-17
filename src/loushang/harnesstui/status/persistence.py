from __future__ import annotations

from collections.abc import Callable

from loushang.harnesstui.status.line import (
    StatusLineSettings,
    status_line_settings_from_control,
    status_line_settings_to_patch,
)


def statusline_settings_from_store(
    settings_store: object | None,
) -> StatusLineSettings | None:
    """Read status-line settings from a duck-typed product settings store."""

    if settings_store is None:
        return None
    getter = getattr(settings_store, "get_statusline_settings", None)
    if not callable(getter):
        return None
    return status_line_settings_from_control(getter())


def statusline_settings_persistence_callback(
    settings_store: object | None,
    *,
    scope: str = "global",
) -> Callable[[StatusLineSettings], None] | None:
    """Build a status-line persistence callback over a product settings store."""

    if settings_store is None:
        return None
    setter = getattr(settings_store, "set_statusline_settings", None)
    if not callable(setter):
        return None

    def _save(settings: StatusLineSettings) -> None:
        setter(status_line_settings_to_patch(settings), scope=scope)

    return _save


__all__ = [
    "statusline_settings_from_store",
    "statusline_settings_persistence_callback",
]
