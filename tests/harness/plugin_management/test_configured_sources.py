from __future__ import annotations

import json
from pathlib import Path

import pytest

from loushang.harness.plugin_management.configured_sources import (
    ConfiguredPluginSourceIdentityConflict,
    ConfiguredPluginSourceProfile,
    project_configured_plugin_sources,
)


def _plugin(root: Path, name: str) -> None:
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps({"name": name, "version": "1.2.3"}), encoding="utf-8"
    )


def test_configured_sources_use_product_profile_and_leave_source_unchanged(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "plugins" / "review"
    _plugin(plugin, "review")
    before = (plugin / "plugin.json").read_bytes()
    profile = ConfiguredPluginSourceProfile(
        product_id="example",
        installation_scope="tenant",
        scope_id="team",
        workspace_root=tmp_path,
        source_strings=("plugins/review",),
        owner_revision_namespace="example-config",
    )

    [record] = project_configured_plugin_sources(profile).records

    assert record.installation_key.product_id == "example"
    assert record.installation_key.installation_scope == "tenant"
    assert record.installation_key.scope_id == "team"
    assert record.source_location == str(plugin)
    assert project_configured_plugin_sources(profile).owner_revision.startswith(
        "example-config:"
    )
    assert (plugin / "plugin.json").read_bytes() == before


def test_configured_source_identity_conflict_is_generic(tmp_path: Path) -> None:
    _plugin(tmp_path / "first", "same")
    _plugin(tmp_path / "second", "same")
    profile = ConfiguredPluginSourceProfile(
        product_id="example",
        installation_scope="workspace",
        scope_id="workspace",
        workspace_root=tmp_path,
        source_strings=("first", "second"),
        owner_revision_namespace="example-config",
    )

    with pytest.raises(ConfiguredPluginSourceIdentityConflict) as error:
        project_configured_plugin_sources(profile)

    assert error.value.plugin_id == "same"


def test_configured_source_profile_requires_an_absolute_product_root() -> None:
    with pytest.raises(ValueError, match="workspace root must be absolute"):
        ConfiguredPluginSourceProfile(
            product_id="example",
            installation_scope="workspace",
            scope_id="workspace",
            workspace_root=Path("relative"),
            source_strings=("plugins/review",),
            owner_revision_namespace="example-config",
        )
