from __future__ import annotations

from pathlib import Path

from loushang.harness.config.agent import SettingsManager
from loushang.harness.environment import resolve_platform_home


def default_global_settings_path() -> Path:
    return resolve_platform_home() / "coding" / "settings.json"


def default_project_settings_path(project_root: str | Path) -> Path:
    return Path(project_root) / ".loushang" / "settings.json"


def open_coding_workspace_settings(workspace: Path) -> SettingsManager:
    return SettingsManager(
        global_settings_path=default_global_settings_path(),
        project_settings_path=default_project_settings_path(workspace),
    )
