from __future__ import annotations

from dataclasses import dataclass, field

from loushang.harnesstui.status.line import StatusLineSettings


@dataclass(frozen=True, slots=True)
class StatusSnapshot:
    model_label: str | None
    cwd: str
    branch: str | None
    session_label: str | None
    thinking_level: str | None
    running: bool
    statusline_visible: bool
    permission_profile: str | None = None
    statusline_settings: StatusLineSettings = field(default_factory=StatusLineSettings)


__all__ = ["StatusSnapshot"]
