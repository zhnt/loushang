from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from loushang.harness.cli.plugin_listing import list_plugin_records
from loushang.harness.resources.plugins.manager import PluginManager


def test_plugin_listing_uses_read_only_resolution_authority(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "review-pack"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({"name": "review-pack", "version": "1"}),
        encoding="utf-8",
    )

    def reject_legacy_resolution(*args, **kwargs):
        del args, kwargs
        raise AssertionError("listing must not use PluginManager.add_plugin_source")

    monkeypatch.setattr(PluginManager, "add_plugin_source", reject_legacy_resolution)

    records = list_plugin_records(_SettingsManager(_Settings((str(root),))))

    assert records == [
        {
            "name": "review-pack",
            "version": "1",
            "path": str(root.resolve()),
            "source": str(root.resolve()),
            "kind": "local",
            "enabled": True,
        }
    ]


@dataclass(frozen=True)
class _Settings:
    plugin_sources: tuple[str, ...]
    disabled_plugins: tuple[str, ...] = ()


class _SettingsManager:
    def __init__(self, settings: _Settings) -> None:
        self._settings = settings

    def get_settings(self) -> _Settings:
        return self._settings
