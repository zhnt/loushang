from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from loushang.coding._plugin_lifecycle import (
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_legacy_desired_evidence import (
    CodingLegacyDesiredError,
    parse_coding_legacy_desired_evidence,
    read_coding_legacy_desired_evidence,
)
from loushang.coding.package_pre_b_snapshot import (
    prepare_and_cutover_coding_package_store_from_legacy,
    prepare_coding_package_cutover_roots,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)


def _old_desired_journal(tmp_path: Path, *, enabled: bool):
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=lifecycle.scope_id,
        plugin_id="review-pack",
    )
    package = PluginPackageRevisionRefV1(
        plugin_id="review-pack",
        plugin_version="1",
        package_content_digest="1" * 64,
        dependency_lock_digest="2" * 64,
        package_source_identity="local:/original/review-pack",
    )
    ledger = PluginDesiredStateLedger(lifecycle.desired_state)
    ledger.commit(
        PluginDesiredStateMutationV1(
            operation_id="old-install",
            idempotency_key="old-install",
            expected_inventory_revision=0,
            installation_key=key,
            desired_state="installed_disabled",
            package_revision=package,
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    if enabled:
        ledger.commit(
            PluginDesiredStateMutationV1(
                operation_id="old-enable",
                idempotency_key="old-enable",
                expected_inventory_revision=1,
                installation_key=key,
                desired_state="installed_enabled",
                package_revision=None,
                actor_id="old-operator",
                policy_revision="old-policy:1",
            )
        )
    return (
        lifecycle,
        epoch,
        workspace,
        key,
        ledger.snapshot(),
        lifecycle.desired_state.read_bytes(),
    )


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize("enabled", [False, True])
def test_first_b_snapshot_preserves_old_desired_enablement(
    tmp_path: Path, enabled: bool
) -> None:
    lifecycle, epoch, workspace, key, expected, raw = _old_desired_journal(
        tmp_path, enabled=enabled
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="a" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    assert cutover.attempt.result.disposition == "fenced"
    lifecycle.desired_state.write_bytes(b"changed old desired journal")
    owner = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        evidence = read_coding_legacy_desired_evidence(lifecycle, owner)
    finally:
        owner.close()
    assert evidence is not None
    assert evidence.snapshot == expected
    assert evidence.snapshot.installation(key).selection.desired_state == (
        "installed_enabled" if enabled else "installed_disabled"
    )
    assert evidence == parse_coding_legacy_desired_evidence(raw, lifecycle=lifecycle)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_first_b_snapshot_reports_missing_old_desired_journal(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="a" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    assert cutover.attempt.result.disposition == "fenced"
    owner = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        assert read_coding_legacy_desired_evidence(lifecycle, owner) is None
    finally:
        owner.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize("mutation", ["partial_tail", "duplicate_key", "foreign_scope"])
def test_old_desired_projection_refuses_ambiguous_journal(
    tmp_path: Path, mutation: str
) -> None:
    lifecycle, _epoch, _workspace, _key, _snapshot, raw = _old_desired_journal(
        tmp_path, enabled=False
    )
    if mutation == "partial_tail":
        raw = raw.removesuffix(b"\n")
    elif mutation == "duplicate_key":
        key = next(iter(json.loads(raw.splitlines()[0])))
        raw = b'{"' + key.encode() + b'":null,' + raw[1:]
    else:
        other = tmp_path / "other-workspace"
        other.mkdir(mode=0o700)
        lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
            tmp_path / "other-session-state", cwd=other
        )
    with pytest.raises(CodingLegacyDesiredError):
        parse_coding_legacy_desired_evidence(raw, lifecycle=lifecycle)
