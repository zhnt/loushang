from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from loushang.coding._plugin_lifecycle import (
    build_coding_plugin_lifecycle,
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.harness.plugin_management import (
    PluginEnablementMigrationError,
    PluginEnablementMigrationJournal,
    PluginEnablementMigrationRequestV1,
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)


def test_coding_composes_private_enablement_migration_and_imports_once(
    tmp_path: Path,
) -> None:
    layout = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session",
        cwd=tmp_path / "workspace",
    )
    lifecycle = build_coding_plugin_lifecycle(layout, startup_id="migration-test")
    key = lifecycle.installation_key("coding.base")
    try:
        migrated = lifecycle.migrate_legacy_enablement(
            key,
            _package(),
            legacy_disabled=True,
            manifest_enabled_default=True,
            legacy_input_fingerprint=hashlib.sha256(b"legacy").hexdigest(),
        )

        assert layout.enablement_migration == (
            layout.root / "enablement-migration.jsonl"
        )
        assert migrated.phase == "compatibility_window"
        assert migrated.disposition == "seeded"
        assert (
            lifecycle.desired.snapshot().installation(key).selection.desired_state
            == "installed_disabled"
        )
    finally:
        lifecycle.release_owned_process_startup_lease()


def test_coding_refuses_future_migration_epoch_before_management_recovery(
    tmp_path: Path,
) -> None:
    layout = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session",
        cwd=tmp_path / "workspace",
    )
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=layout.scope_id,
        plugin_id="coding.base",
    )
    journal = PluginEnablementMigrationJournal(layout.enablement_migration)
    journal.accept(
        PluginEnablementMigrationRequestV1(
            installation_key=key,
            package_revision=_package(),
            legacy_disabled=False,
            manifest_enabled_default=True,
            legacy_input_fingerprint=hashlib.sha256(b"future").hexdigest(),
            migration_epoch=2,
        ),
        accepted_desired_inventory_revision=0,
        prior_desired_history_revision=None,
    )

    with pytest.raises(PluginEnablementMigrationError) as incompatible:
        build_coding_plugin_lifecycle(layout, startup_id="old-runtime")

    assert incompatible.value.code == "plugin_enablement_migration_epoch_unsupported"
    assert not layout.management_operations.exists()


def _package() -> PluginPackageRevisionRefV1:
    return PluginPackageRevisionRefV1(
        plugin_id="coding.base",
        plugin_version="1.0.0",
        package_content_digest="1" * 64,
        dependency_lock_digest="2" * 64,
        package_source_identity="embedded:coding.base",
    )
