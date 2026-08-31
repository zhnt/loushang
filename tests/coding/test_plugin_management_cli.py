from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding._plugin_lifecycle import (
    build_coding_plugin_lifecycle,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.control import SettingsManager
from loushang.coding.plugin_enablement_compatibility import (
    CodingPluginEnablementCompatibilityError,
    bind_coding_plugin_enablement_compatibility,
)
from loushang.coding.plugin_management_cli import (
    build_coding_plugin_management_cli_binding,
)
from loushang.harness.cli.plugin_listing import list_plugin_records
from loushang.harness.cli.resource_toggles import (
    ResourceToggleError,
    ResourceToggleRequest,
    apply_resource_toggles,
)
from loushang.harness.config.agent.types import ControlConfig
from loushang.harness.plugin_management import (
    PluginEnablementMigrationError,
    PluginPackageRevisionRefV1,
    plugin_enablement_legacy_input_fingerprint,
)


@dataclass(frozen=True)
class _Settings:
    plugin_sources: tuple[str, ...] = ()
    disabled_plugins: tuple[str, ...] = ()


class _SettingsManager:
    def __init__(self, settings: _Settings) -> None:
        self.settings = settings

    def get_settings(self) -> _Settings:
        return self.settings

    def set_disabled_plugins(
        self,
        names: tuple[str, ...],
        *,
        scope: str,
    ) -> None:
        assert scope == "project"
        self.settings = replace(self.settings, disabled_plugins=tuple(names))

    def bind_plugin_enablement_legacy_mutation_guard(self, authority, guard):
        assert authority is not None
        self.guard = guard

        def publish(projection):
            migrated = set(projection.migrated_plugin_ids)
            retained = {
                item for item in self.settings.disabled_plugins if item not in migrated
            }
            names = tuple(sorted(retained | set(projection.disabled_plugin_ids)))
            self.set_disabled_plugins(names, scope="project")

        return publish


class _FailingCompatibilitySettingsManager(_SettingsManager):
    def __init__(self, settings: _Settings) -> None:
        super().__init__(settings)
        self.fail_publication = True

    def bind_plugin_enablement_legacy_mutation_guard(self, authority, guard):
        assert authority is not None
        self.guard = guard

        def publish(projection):
            if self.fail_publication:
                raise OSError("compatibility sink unavailable")
            migrated = set(projection.migrated_plugin_ids)
            retained = {
                item for item in self.settings.disabled_plugins if item not in migrated
            }
            names = tuple(sorted(retained | set(projection.disabled_plugin_ids)))
            self.set_disabled_plugins(names, scope="project")

        return publish


def test_coding_management_cli_projects_relative_sources_from_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    plugin_root = workspace / "plugins" / "debug-pack"
    plugin_root.mkdir(parents=True)
    (plugin_root / "plugin.json").write_text(
        json.dumps({"name": "debug-pack", "version": "1.2.3"}),
        encoding="utf-8",
    )
    binding = build_coding_plugin_management_cli_binding(
        workspace,
        _SettingsManager(_Settings(plugin_sources=("plugins/debug-pack",))),
    )

    assert list_plugin_records(binding) == [
        {
            "name": "debug-pack",
            "version": "1.2.3",
            "path": str(plugin_root.resolve()),
            "source": str(plugin_root.resolve()),
            "kind": "local",
            "enabled": None,
            "desiredState": "unknown",
            "convergence": "unknown",
            "migrationStatus": None,
        }
    ]


def test_management_binding_expands_tilde_before_workspace_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_home = tmp_path / "user-home"
    workspace = user_home / "workspace"
    workspace.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))

    binding = build_coding_plugin_management_cli_binding(
        "~/workspace",
        _SettingsManager(_Settings()),
    )

    assert (
        binding.scope_id
        == resolve_coding_plugin_lifecycle_state_layout(workspace).scope_id
    )


def test_coding_management_cli_writes_only_derived_legacy_compatibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = _SettingsManager(
        _Settings(disabled_plugins=("managed-pack", "unmigrated-pack"))
    )
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    lifecycle = build_coding_plugin_lifecycle(layout, startup_id="cli-migration")
    key = lifecycle.installation_key("managed-pack")
    try:
        lifecycle.migrate_legacy_enablement(
            key,
            _package("managed-pack"),
            legacy_disabled=True,
            manifest_enabled_default=True,
            legacy_input_fingerprint=plugin_enablement_legacy_input_fingerprint(
                key,
                legacy_disabled=True,
                manifest_enabled_default=True,
            ),
        )
    finally:
        lifecycle.release_owned_process_startup_lease()

    result = apply_resource_toggles(
        settings,
        ResourceToggleRequest(enable_plugins=("managed-pack",)),
        plugin_management=build_coding_plugin_management_cli_binding(
            workspace,
            settings,
        ),
    )

    assert result.messages == ("plugin desired state committed\tenabled\tmanaged-pack",)
    assert settings.get_settings().disabled_plugins == ("unmigrated-pack",)


def test_binding_repairs_compatibility_and_fences_all_legacy_mutators(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings_path = workspace / ".loushang" / "settings.json"
    settings = SettingsManager(
        initial=ControlConfig(disabled_plugins=("managed-pack",)),
        project_settings_path=settings_path,
    )
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    lifecycle = build_coding_plugin_lifecycle(layout, startup_id="fence-test")
    key = lifecycle.installation_key("managed-pack")
    try:
        lifecycle.migrate_legacy_enablement(
            key,
            _package("managed-pack"),
            legacy_disabled=False,
            manifest_enabled_default=True,
            legacy_input_fingerprint=plugin_enablement_legacy_input_fingerprint(
                key,
                legacy_disabled=False,
                manifest_enabled_default=True,
            ),
        )
    finally:
        lifecycle.release_owned_process_startup_lease()

    build_coding_plugin_management_cli_binding(workspace, settings)

    assert settings.get_settings().disabled_plugins == ()
    assert "disabled_plugins" not in settings.get_session_settings()
    writer = bind_coding_plugin_enablement_compatibility(layout, settings)
    assert writer is not None
    with ThreadPoolExecutor(max_workers=4) as pool:
        tuple(pool.map(lambda _index: writer.reconcile(), range(16)))
    assert settings.get_settings().disabled_plugins == ()
    with pytest.raises(RuntimeError, match="authority already bound"):
        settings.bind_plugin_enablement_legacy_mutation_guard(
            object(),
            lambda _plugin_id: None,
        )
    for mutate in (
        lambda: settings.enable_plugin("managed-pack"),
        lambda: settings.disable_plugin("managed-pack"),
        lambda: settings.set_disabled_plugins(("managed-pack",)),
        lambda: settings.update_settings(disabled_plugins=("managed-pack",)),
    ):
        with pytest.raises(PluginEnablementMigrationError) as rejected:
            mutate()
        assert rejected.value.code == "plugin_enablement_legacy_mutation_rejected"
    assert settings.get_settings().disabled_plugins == ()


def test_two_settings_owners_preserve_concurrent_unmigrated_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings_path = workspace / ".loushang" / "settings.json"
    seed = SettingsManager(project_settings_path=settings_path)
    seed.set_disabled_plugins(("managed-pack",), scope="project")
    first = SettingsManager(project_settings_path=settings_path)
    second = SettingsManager(project_settings_path=settings_path)
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    lifecycle = build_coding_plugin_lifecycle(layout, startup_id="multi-settings")
    key = lifecycle.installation_key("managed-pack")
    try:
        lifecycle.migrate_legacy_enablement(
            key,
            _package("managed-pack"),
            legacy_disabled=True,
            manifest_enabled_default=True,
            legacy_input_fingerprint=plugin_enablement_legacy_input_fingerprint(
                key,
                legacy_disabled=True,
                manifest_enabled_default=True,
            ),
        )
    finally:
        lifecycle.release_owned_process_startup_lease()
    first_writer = bind_coding_plugin_enablement_compatibility(layout, first)
    second_writer = bind_coding_plugin_enablement_compatibility(layout, second)
    assert first_writer is not None
    assert second_writer is not None
    first_writer.reconcile()
    second_writer.reconcile()

    second.set_disabled_plugins(
        ("managed-pack", "unmigrated-peer"),
        scope="project",
    )
    first_writer.reconcile()

    reloaded = SettingsManager(project_settings_path=settings_path)
    assert reloaded.get_settings().disabled_plugins == (
        "managed-pack",
        "unmigrated-peer",
    )


def test_compatibility_failure_preserves_canonical_commit_and_restart_repairs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = _FailingCompatibilitySettingsManager(
        _Settings(disabled_plugins=("managed-pack",))
    )
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    lifecycle = build_coding_plugin_lifecycle(layout, startup_id="partial-write")
    key = lifecycle.installation_key("managed-pack")
    try:
        lifecycle.migrate_legacy_enablement(
            key,
            _package("managed-pack"),
            legacy_disabled=True,
            manifest_enabled_default=True,
            legacy_input_fingerprint=plugin_enablement_legacy_input_fingerprint(
                key,
                legacy_disabled=True,
                manifest_enabled_default=True,
            ),
        )
    finally:
        lifecycle.release_owned_process_startup_lease()
    settings.fail_publication = False
    binding = build_coding_plugin_management_cli_binding(workspace, settings)
    settings.fail_publication = True

    with pytest.raises(ResourceToggleError) as raised:
        apply_resource_toggles(
            settings,
            ResourceToggleRequest(enable_plugins=("managed-pack",)),
            plugin_management=binding,
        )

    assert getattr(raised.value, "code", None) == (
        "plugin_enablement_compatibility_publish_failed"
    )
    assert lifecycle.desired.snapshot().installation(key).selection.desired_state == (
        "installed_enabled"
    )
    assert settings.get_settings().disabled_plugins == ("managed-pack",)

    settings.fail_publication = False
    build_coding_plugin_management_cli_binding(workspace, settings)
    assert settings.get_settings().disabled_plugins == ()


def test_existing_receipt_rejects_non_fence_settings_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    lifecycle = build_coding_plugin_lifecycle(layout, startup_id="missing-fence")
    key = lifecycle.installation_key("managed-pack")
    try:
        lifecycle.migrate_legacy_enablement(
            key,
            _package("managed-pack"),
            legacy_disabled=True,
            manifest_enabled_default=True,
            legacy_input_fingerprint=plugin_enablement_legacy_input_fingerprint(
                key,
                legacy_disabled=True,
                manifest_enabled_default=True,
            ),
        )
    finally:
        lifecycle.release_owned_process_startup_lease()
    settings = SimpleNamespace(
        get_settings=lambda: SimpleNamespace(
            plugin_sources=(),
            disabled_plugins=("managed-pack",),
        )
    )

    with pytest.raises(CodingPluginEnablementCompatibilityError) as rejected:
        build_coding_plugin_management_cli_binding(workspace, settings)

    assert rejected.value.code == "coding_plugin_compatibility_fence_unavailable"


def test_management_binding_is_workspace_scoped_and_restart_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    first_layout = resolve_coding_plugin_lifecycle_state_layout(first)
    lifecycle = build_coding_plugin_lifecycle(first_layout, startup_id="scope-test")
    key = lifecycle.installation_key("managed-pack")
    try:
        lifecycle.migrate_legacy_enablement(
            key,
            _package("managed-pack"),
            legacy_disabled=True,
            manifest_enabled_default=True,
            legacy_input_fingerprint=plugin_enablement_legacy_input_fingerprint(
                key,
                legacy_disabled=True,
                manifest_enabled_default=True,
            ),
        )
    finally:
        lifecycle.release_owned_process_startup_lease()

    first_records = list_plugin_records(
        build_coding_plugin_management_cli_binding(
            first,
            _SettingsManager(_Settings()),
        )
    )
    second_records = list_plugin_records(
        build_coding_plugin_management_cli_binding(
            second,
            _SettingsManager(_Settings()),
        )
    )
    restarted_records = list_plugin_records(
        build_coding_plugin_management_cli_binding(
            first,
            _SettingsManager(_Settings()),
        )
    )

    assert first_layout != resolve_coding_plugin_lifecycle_state_layout(second)
    assert first_records == restarted_records
    assert [item["name"] for item in first_records] == ["managed-pack"]
    assert second_records == []


def test_management_binding_is_home_scoped_for_the_same_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first_home = tmp_path / "first-home"
    second_home = tmp_path / "second-home"
    monkeypatch.setenv("LOUSHANG_HOME", str(first_home))
    first_layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    lifecycle = build_coding_plugin_lifecycle(first_layout, startup_id="home-scope")
    key = lifecycle.installation_key("managed-pack")
    try:
        lifecycle.migrate_legacy_enablement(
            key,
            _package("managed-pack"),
            legacy_disabled=True,
            manifest_enabled_default=True,
            legacy_input_fingerprint=plugin_enablement_legacy_input_fingerprint(
                key,
                legacy_disabled=True,
                manifest_enabled_default=True,
            ),
        )
    finally:
        lifecycle.release_owned_process_startup_lease()
    first_records = list_plugin_records(
        build_coding_plugin_management_cli_binding(
            workspace,
            _SettingsManager(_Settings()),
        )
    )

    monkeypatch.setenv("LOUSHANG_HOME", str(second_home))
    second_layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    second_records = list_plugin_records(
        build_coding_plugin_management_cli_binding(
            workspace,
            _SettingsManager(_Settings()),
        )
    )

    monkeypatch.setenv("LOUSHANG_HOME", str(first_home))
    restarted_records = list_plugin_records(
        build_coding_plugin_management_cli_binding(
            workspace,
            _SettingsManager(_Settings()),
        )
    )

    assert first_layout.root != second_layout.root
    assert first_records == restarted_records
    assert [item["name"] for item in first_records] == ["managed-pack"]
    assert second_records == []


def _package(plugin_id: str) -> PluginPackageRevisionRefV1:
    return PluginPackageRevisionRefV1(
        plugin_id=plugin_id,
        plugin_version="1.0.0",
        package_content_digest="1" * 64,
        dependency_lock_digest="2" * 64,
        package_source_identity=f"test:{plugin_id}",
    )
