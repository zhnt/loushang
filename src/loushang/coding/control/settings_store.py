from __future__ import annotations

from pathlib import Path

from loushang.harness.config.agent import SettingsManager
from loushang.harness.environment import resolve_platform_home


def default_global_settings_path() -> Path:
    return resolve_platform_home() / "coding" / "settings.json"


def default_project_settings_path(project_root: str | Path) -> Path:
    return Path(project_root) / ".loushang" / "settings.json"


def open_coding_workspace_settings(
    workspace: Path | None,
    *,
    global_settings_path: str | Path | None = None,
    project_settings_path: str | Path | None = None,
) -> SettingsManager:
    """Bind Coding's settings locations to the shared SettingsManager."""
    global_path = (
        Path(global_settings_path)
        if global_settings_path is not None
        else default_global_settings_path()
    )
    if project_settings_path is not None:
        project_settings_path = Path(project_settings_path)
    elif workspace:
        project_settings_path = default_project_settings_path(workspace)
    return SettingsManager(
        global_settings_path=global_path,
        project_settings_path=project_settings_path,
    )
