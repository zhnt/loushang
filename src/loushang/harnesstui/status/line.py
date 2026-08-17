from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from loushang.tui import StatusField

StatusLineAutoValue = Literal["auto", "true", "false"]
StatusLineSeparator = Literal["pipe", "dot"]
StatusLineStyle = Literal["codex-like", "muted", "plain"]


@dataclass(frozen=True, slots=True)
class StatusLineSettings:
    enabled: bool = True
    model: bool = True
    workspace: bool = True
    branch: bool = True
    session: bool = True
    permissions: bool = True
    runtime: bool = True
    queue: StatusLineAutoValue = "auto"
    message: StatusLineAutoValue = "auto"
    separator: StatusLineSeparator = "pipe"
    style: StatusLineStyle = "codex-like"


@dataclass(frozen=True, slots=True)
class StatusLinePreviewSnapshot:
    model_label: str | None
    cwd: str
    branch: str | None
    session_label: str | None
    running: bool
    permission_profile: str | None = None
    pending_followups: int = 0
    pending_steers: int = 0
    status_message: str | None = None


def status_line_fields(
    snapshot: StatusLinePreviewSnapshot,
    settings: StatusLineSettings,
) -> tuple[StatusField, ...]:
    fields: list[StatusField] = []
    if settings.model:
        fields.append(StatusField(snapshot.model_label or "model", priority=100, token="model"))
    if settings.workspace:
        fields.append(StatusField(cwd_label(snapshot.cwd), priority=90, token="workspace"))
    if settings.branch:
        fields.append(StatusField(snapshot.branch or "no-branch", priority=80, token="branch"))
    if settings.session:
        fields.append(StatusField(snapshot.session_label or "no-session", priority=70, token="session"))
    if settings.permissions:
        fields.append(
            StatusField(
                f"perm={snapshot.permission_profile or 'standard'}",
                priority=35,
                token="permissions",
            )
        )
    if settings.runtime:
        runtime_text = "running" if snapshot.running else "idle"
        runtime_token = "runtime.running" if snapshot.running else "runtime.idle"
        fields.append(StatusField(runtime_text, priority=60, token=runtime_token))
    if _show_auto_field(settings.queue, snapshot.pending_followups > 0 or snapshot.pending_steers > 0):
        fields.append(
            StatusField(
                f"queued={max(0, snapshot.pending_followups)} steer={max(0, snapshot.pending_steers)}",
                priority=50,
                token="queue",
            )
        )
    if _show_auto_field(settings.message, bool(snapshot.status_message)):
        fields.append(StatusField(snapshot.status_message or "no status", priority=40, token="message"))
    return tuple(fields)


def status_line_separator(settings: StatusLineSettings) -> str:
    if settings.separator == "dot":
        return " · "
    return " | "


def status_line_style_mode(settings: StatusLineSettings) -> StatusLineStyle:
    return settings.style if settings.style in {"codex-like", "muted", "plain"} else "codex-like"


def status_line_settings_from_control(settings: object | None) -> StatusLineSettings:
    if settings is None:
        return StatusLineSettings()
    if isinstance(settings, StatusLineSettings):
        return settings
    defaults = StatusLineSettings()
    return StatusLineSettings(
        enabled=bool(_setting_value(settings, "enabled", defaults.enabled)),
        model=bool(_setting_value(settings, "model", defaults.model)),
        workspace=bool(_setting_value(settings, "workspace", defaults.workspace)),
        branch=bool(_setting_value(settings, "branch", defaults.branch)),
        session=bool(_setting_value(settings, "session", defaults.session)),
        permissions=bool(
            _setting_value(settings, "permissions", defaults.permissions)
        ),
        runtime=bool(_setting_value(settings, "runtime", defaults.runtime)),
        queue=cast(StatusLineAutoValue, _setting_value(settings, "queue", defaults.queue)),
        message=cast(StatusLineAutoValue, _setting_value(settings, "message", defaults.message)),
        separator=cast(StatusLineSeparator, _setting_value(settings, "separator", defaults.separator)),
        style=cast(StatusLineStyle, _setting_value(settings, "style", defaults.style)),
    )


def status_line_settings_to_patch(settings: StatusLineSettings) -> dict[str, object]:
    return {
        "enabled": settings.enabled,
        "model": settings.model,
        "workspace": settings.workspace,
        "branch": settings.branch,
        "session": settings.session,
        "permissions": settings.permissions,
        "runtime": settings.runtime,
        "queue": settings.queue,
        "message": settings.message,
        "separator": settings.separator,
        "style": settings.style,
    }


def cwd_label(cwd: str) -> str:
    if not cwd:
        return "cwd"
    return cwd.rstrip("/").rsplit("/", 1)[-1] or cwd


def _setting_value(settings: object, key: str, default: object) -> object:
    if isinstance(settings, Mapping):
        return settings.get(key, default)
    return getattr(settings, key, default)


def _show_auto_field(value: StatusLineAutoValue, has_data: bool) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    return has_data


__all__ = [
    "StatusLinePreviewSnapshot",
    "StatusLineSettings",
    "cwd_label",
    "status_line_fields",
    "status_line_settings_from_control",
    "status_line_settings_to_patch",
    "status_line_separator",
    "status_line_style_mode",
]
