from __future__ import annotations

from pathlib import Path


def default_global_settings_path() -> Path:
    return Path.home() / ".loushang" / "coding" / "settings.json"


def default_project_settings_path(project_root: str | Path) -> Path:
    return Path(project_root) / ".loushang" / "settings.json"
