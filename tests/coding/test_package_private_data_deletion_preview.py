from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_installation_private_data import (
    prepare_coding_product_arch_private_data_root,
)
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.package_private_data_deletion_preview import (
    CodingArchPrivateDataDeletionPreview,
    CodingArchPrivateDataTargetSnapshotV1,
)
from loushang.coding.package_product_runtime import (
    open_coding_fenced_product_application_owner,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1


@pytest.mark.skipif(os.name != "posix", reason="POSIX private-data preview")
def test_product_arch_private_data_preview_is_fenced_and_detects_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="a" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=layout.scope_id,
        plugin_id="coding.arch.default",
    )
    preview = CodingArchPrivateDataDeletionPreview(
        layout, owner.runtime_owner.product_owner
    )
    absent = preview.plan_for(key)
    assert absent.target_id.startswith("absent:")
    absent_snapshot = preview.snapshot_for(key)
    assert (
        CodingArchPrivateDataTargetSnapshotV1.from_dict(absent_snapshot.to_dict())
        == absent_snapshot
    )
    assert not (layout.package_root / "installation-private-data").exists()
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "session", cwd=str(workspace), persist=True
        )
    )
    session_id = manager.get_header().conversation_id
    runtime = owner.factory_for_session(manager).create(
        PackageProductRuntimeRequestV1(
            product_id="coding", session_id=session_id, cwd=str(workspace)
        )
    )
    try:
        runtime.activate()
        private_root = prepare_coding_product_arch_private_data_root(
            layout, runtime, session_id=session_id
        )
        marker = private_root / "cache.json"
        marker.write_text('{"v":1}', encoding="utf-8")
        with pytest.raises(ValueError, match="runtime is active"):
            preview.plan_for(key)
    finally:
        runtime.dispose_runtime()
    try:
        first = preview.plan_for(key)
        assert first.target_id.startswith("present:")
        assert first.target_id != absent.target_id
        snapshot = preview.snapshot_for(key)
        assert snapshot.target_id == first.target_id
        assert (
            CodingArchPrivateDataTargetSnapshotV1.from_dict(snapshot.to_dict())
            == snapshot
        )
        missing_parent = snapshot.to_dict()
        missing_parent["members"] = [
            member
            for member in missing_parent["members"]
            if member["relativePath"] != "sessions"
        ]
        with pytest.raises(ValueError, match="parent is missing"):
            CodingArchPrivateDataTargetSnapshotV1.from_dict(missing_parent)
        assert marker.read_text(encoding="utf-8") == '{"v":1}'
        marker.write_text('{"v":2}', encoding="utf-8")
        second = preview.plan_for(key)
        assert second.target_id != first.target_id
        foreign = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id="workspace:" + "0" * 64,
            plugin_id="coding.arch.default",
        )
        with pytest.raises(ValueError, match="Installation key changed"):
            preview.plan_for(foreign)
        (private_root / "unsafe").symlink_to(tmp_path)
        with pytest.raises(ValueError, match="member is unsafe"):
            preview.plan_for(key)
        assert marker.read_text(encoding="utf-8") == '{"v":2}'
    finally:
        owner.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX private-data preview")
def test_arch_private_data_preview_rejects_foreign_product_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    foreign_workspace = tmp_path / "foreign"
    foreign_workspace.mkdir(mode=0o700)
    foreign_layout = resolve_coding_plugin_lifecycle_state_layout(foreign_workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="a" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        with pytest.raises(ValueError, match="owner is not bound"):
            CodingArchPrivateDataDeletionPreview(
                foreign_layout, owner.runtime_owner.product_owner
            )
        assert not (foreign_layout.package_root / "installation-private-data").exists()
    finally:
        owner.close()
