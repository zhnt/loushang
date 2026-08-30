from __future__ import annotations

from loushang.coding.control.settings_store import (
    default_global_settings_path,
    default_project_settings_path,
)
from loushang.coding.lsp.discovery import (
    default_global_lsp_config_path,
    default_project_lsp_config_path,
)


def test_coding_config_uses_platform_home_and_keeps_project_scope(
    tmp_path,
    monkeypatch,
) -> None:
    platform_home = tmp_path / "user-home"
    project = tmp_path / "project"
    monkeypatch.setenv("LOUSHANG_HOME", str(platform_home))

    assert default_global_settings_path() == (
        platform_home / "coding" / "settings.json"
    )
    assert default_global_lsp_config_path() == platform_home / "coding" / "lsp.json"
    assert default_project_settings_path(project) == (
        project / ".loushang" / "settings.json"
    )
    assert default_project_lsp_config_path(project) == (
        project / ".loushang" / "lsp.json"
    )
