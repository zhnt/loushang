from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

import pytest

from loushang.coding._plugin_lifecycle import (
    CodingPluginLifecycleError,
    build_coding_plugin_lifecycle,
    build_coding_plugin_management_application,
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.harness.plugin_management import (
    PluginEnablementFinalizationEvidenceV1,
    PluginEnablementMigrationError,
    PluginEnablementMigrationJournal,
    PluginEnablementMigrationRequestV1,
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)


class _ApprovedFinalization:
    def verify_finalization(self, migration: object, evidence: object) -> None:
        return None


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


@pytest.mark.parametrize("installation_scope", ["process", "tenant"])
def test_coding_migration_refuses_foreign_installation_scope_before_writes(
    tmp_path: Path, installation_scope: Literal["process", "tenant"]
) -> None:
    layout = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session", cwd=tmp_path / "workspace"
    )
    lifecycle = build_coding_plugin_lifecycle(layout, startup_id="scope-test")
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope=installation_scope,
        scope_id=layout.scope_id,
        plugin_id="coding.base",
    )
    try:
        with pytest.raises(CodingPluginLifecycleError) as refused:
            lifecycle.migrate_legacy_enablement(
                key,
                _package(),
                legacy_disabled=False,
                manifest_enabled_default=True,
                legacy_input_fingerprint=hashlib.sha256(b"foreign-scope").hexdigest(),
            )
        assert refused.value.code == "coding_plugin_enablement_migration_scope_mismatch"
        assert not layout.enablement_migration.exists()
        assert not layout.management_operations.exists()
    finally:
        lifecycle.release_owned_process_startup_lease()


@pytest.mark.parametrize("installation_scope", ["process", "tenant"])
def test_coding_default_bootstrap_refuses_foreign_installation_before_writes(
    tmp_path: Path, installation_scope: Literal["process", "tenant"]
) -> None:
    layout = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session", cwd=tmp_path / "workspace"
    )
    lifecycle = build_coding_plugin_lifecycle(layout, startup_id="default-scope-test")
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope=installation_scope,
        scope_id=layout.scope_id,
        plugin_id="coding.base",
    )
    try:
        with pytest.raises(CodingPluginLifecycleError) as refused:
            lifecycle.bootstrap_first_party_default(key, _package())
        assert refused.value.code == "coding_plugin_default_bootstrap_scope_mismatch"
        assert not layout.desired_state.exists()
        assert not layout.management_operations.exists()
    finally:
        lifecycle.release_owned_process_startup_lease()


def test_coding_default_bootstrap_refuses_foreign_package_revision(
    tmp_path: Path,
) -> None:
    layout = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session", cwd=tmp_path / "workspace"
    )
    lifecycle = build_coding_plugin_lifecycle(layout, startup_id="default-revision-test")
    key = lifecycle.installation_key("coding.arch.default")
    try:
        with pytest.raises(CodingPluginLifecycleError) as refused:
            lifecycle.bootstrap_first_party_default(key, _package())
        assert refused.value.code == "coding_plugin_default_bootstrap_revision_mismatch"
        assert not layout.desired_state.exists()
        assert not layout.management_operations.exists()
    finally:
        lifecycle.release_owned_process_startup_lease()


def test_coding_migration_cannot_finalize_without_production_recovery_authority(
    tmp_path: Path,
) -> None:
    layout = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session", cwd=tmp_path / "workspace"
    )
    lifecycle = build_coding_plugin_lifecycle(layout, startup_id="finalization-gate")
    key = lifecycle.installation_key("coding.base")
    try:
        migrated = lifecycle.migrate_legacy_enablement(
            key,
            _package(),
            legacy_disabled=False,
            manifest_enabled_default=True,
            legacy_input_fingerprint=hashlib.sha256(b"finalization-gate").hexdigest(),
        )
        before = layout.enablement_migration.read_bytes()
        evidence = PluginEnablementFinalizationEvidenceV1(
            minimum_runtime_version="1.0.0",
            minimum_migration_epoch=1,
            backup_receipt="backup:verified",
            restore_test_receipt="restore:test:passed",
            roll_forward_procedure="runbook:plugin-enable:v1",
        )

        with pytest.raises(PluginEnablementMigrationError) as refused:
            lifecycle.enablement_migrations.finalize(migrated.migration_id, evidence)

        assert refused.value.code == "plugin_enablement_finalization_authority_unavailable"
        assert layout.enablement_migration.read_bytes() == before
        assert lifecycle.enablement_migrations.journal.snapshot(key).phase == (
            "compatibility_window"
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


def test_coding_runtime_and_read_only_management_refuse_finalized_newer_version(
    tmp_path: Path,
) -> None:
    layout = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session", cwd=tmp_path / "workspace"
    )
    lifecycle = build_coding_plugin_lifecycle(layout, startup_id="version-author")
    key = lifecycle.installation_key("coding.base")
    try:
        migrated = lifecycle.migrate_legacy_enablement(
            key,
            _package(),
            legacy_disabled=False,
            manifest_enabled_default=True,
            legacy_input_fingerprint=hashlib.sha256(b"version").hexdigest(),
        )
        evidence = PluginEnablementFinalizationEvidenceV1(
            minimum_runtime_version="9999.0",
            minimum_migration_epoch=1,
            backup_receipt="backup:verified",
            restore_test_receipt="restore:test:passed",
            roll_forward_procedure="runbook:plugin-enable:v1",
        )
        lifecycle.enablement_migrations.journal.finalize(
            migrated.migration_id,
            evidence,
            authority=_ApprovedFinalization(),
        )
    finally:
        lifecycle.release_owned_process_startup_lease()

    with pytest.raises(PluginEnablementMigrationError) as runtime:
        build_coding_plugin_lifecycle(layout, startup_id="version-reader")
    assert runtime.value.code == "plugin_enablement_migration_runtime_version_unsupported"
    with pytest.raises(PluginEnablementMigrationError) as management:
        build_coding_plugin_management_application(layout, read_only=True)
    assert management.value.code == runtime.value.code


def _package() -> PluginPackageRevisionRefV1:
    return PluginPackageRevisionRefV1(
        plugin_id="coding.base",
        plugin_version="1.0.0",
        package_content_digest="1" * 64,
        dependency_lock_digest="2" * 64,
        package_source_identity="embedded:coding.base",
    )
