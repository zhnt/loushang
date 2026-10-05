from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

import loushang.coding.package_private_data_deletion_owner as deletion_module
from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_installation_private_data import (
    coding_arch_installation_private_data_root,
    prepare_coding_product_arch_private_data_root,
)
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionJournal,
)
from loushang.coding.package_private_data_deletion_owner import (
    CodingArchPrivateDataDeletionOwner,
)
from loushang.coding.package_product_runtime import (
    open_coding_fenced_product_application_owner,
    open_coding_package_product_state,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management import (
    PluginDesiredStateMutationV1,
    PluginManagementCommandV1,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionCoordinator,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1


@pytest.mark.skipif(os.name != "posix", reason="POSIX private-data owner")
def test_product_arch_private_data_deletion_requires_remove_and_replays_receipt(
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
    app = open_coding_fenced_product_application_owner(
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
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "session", cwd=str(workspace), persist=True
        )
    )
    session_id = manager.get_header().conversation_id
    runtime = app.factory_for_session(manager).create(
        PackageProductRuntimeRequestV1(
            product_id="coding", session_id=session_id, cwd=str(workspace)
        )
    )
    try:
        runtime.activate()
        private_root = prepare_coding_product_arch_private_data_root(
            layout, runtime, session_id=session_id
        )
        (private_root / "cache.json").write_text('{"private":true}', encoding="utf-8")
    finally:
        runtime.dispose_runtime()
    installation_root = coding_arch_installation_private_data_root(layout, key)
    assert installation_root.is_dir()
    unrelated = layout.package_root / "unrelated-private.txt"
    unrelated.write_text("preserve", encoding="utf-8")

    try:
        product = app.runtime_owner.product_owner
        state = open_coding_package_product_state(layout, app.epoch_runtime)
        data_owner = CodingArchPrivateDataDeletionOwner(
            layout,
            product,
            state.private_data_confirmation,
            state.private_data_deletion,
        )
        coordinator = PluginPrivateDataDeletionCoordinator(
            data_owner, confirmation_authority=state.private_data_confirmation
        )
        plan = coordinator.preview(key)
        confirmation = PluginPrivateDataDeletionConfirmationV1(
            plan_fingerprint=plan.fingerprint,
            confirmation_id="operator:delete-arch-cache",
        )
        with pytest.raises(ValueError, match="not authorized"):
            coordinator.delete(plan, confirmation)
        state.private_data_confirmation.record_confirmation(
            plan, confirmation, actor_id="operator:test", policy_revision="test:1"
        )
        with pytest.raises(ValueError, match="removed first"):
            coordinator.delete(plan, confirmation)
        assert installation_root.is_dir()

        selected = product.desired_state.snapshot()
        removed = product.management.submit(
            PluginManagementCommandV1(
                action="remove",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:remove-arch-data",
                    idempotency_key="operator:remove-arch-data",
                    expected_inventory_revision=selected.inventory_revision,
                    installation_key=key,
                    desired_state="absent",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision="operator:1",
                ),
            )
        )
        assert removed.result is not None
        assert removed.result.disposition == "succeeded"
        receipt = coordinator.delete(plan, confirmation)
        assert receipt.disposition == "deleted"
        assert not installation_root.exists()
        assert unrelated.read_text(encoding="utf-8") == "preserve"
    finally:
        app.close()

    reopened = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        state = open_coding_package_product_state(layout, reopened.epoch_runtime)
        data_owner = CodingArchPrivateDataDeletionOwner(
            layout,
            reopened.runtime_owner.product_owner,
            state.private_data_confirmation,
            state.private_data_deletion,
        )
        coordinator = PluginPrivateDataDeletionCoordinator(
            data_owner, confirmation_authority=state.private_data_confirmation
        )
        assert coordinator.delete(plan, confirmation) == receipt
        assert state.private_data_deletion.receipt_for(plan, confirmation) == receipt
        assert len(state.private_data_deletion.events()) == 3
        assert unrelated.read_text(encoding="utf-8") == "preserve"
        absent_plan = coordinator.preview(key)
        assert absent_plan.target_id.startswith("absent:")
        absent_confirmation = PluginPrivateDataDeletionConfirmationV1(
            plan_fingerprint=absent_plan.fingerprint,
            confirmation_id="operator:confirm-already-absent",
        )
        state.private_data_confirmation.record_confirmation(
            absent_plan,
            absent_confirmation,
            actor_id="operator:test",
            policy_revision="test:1",
        )
        absent_receipt = coordinator.delete(absent_plan, absent_confirmation)
        assert absent_receipt.disposition == "already_absent"
        assert len(state.private_data_deletion.events()) == 5
        assert unrelated.read_text(encoding="utf-8") == "preserve"
    finally:
        reopened.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX private-data owner")
@pytest.mark.parametrize(
    "interruption", ("after_rename", "before_receipt", "tampered_tombstone")
)
def test_product_arch_deletion_recovers_exact_started_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interruption: str
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
    app = open_coding_fenced_product_application_owner(
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
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "session", cwd=str(workspace), persist=True
        )
    )
    session_id = manager.get_header().conversation_id
    runtime = app.factory_for_session(manager).create(
        PackageProductRuntimeRequestV1(
            product_id="coding", session_id=session_id, cwd=str(workspace)
        )
    )
    try:
        runtime.activate()
        private_root = prepare_coding_product_arch_private_data_root(
            layout, runtime, session_id=session_id
        )
        (private_root / "cache.json").write_text("private", encoding="utf-8")
    finally:
        runtime.dispose_runtime()
    installation_root = coding_arch_installation_private_data_root(layout, key)

    try:
        product = app.runtime_owner.product_owner
        state = open_coding_package_product_state(layout, app.epoch_runtime)
        data_owner = CodingArchPrivateDataDeletionOwner(
            layout,
            product,
            state.private_data_confirmation,
            state.private_data_deletion,
        )
        coordinator = PluginPrivateDataDeletionCoordinator(
            data_owner, confirmation_authority=state.private_data_confirmation
        )
        plan = coordinator.preview(key)
        confirmation = PluginPrivateDataDeletionConfirmationV1(
            plan_fingerprint=plan.fingerprint,
            confirmation_id="operator:crash-recovery",
        )
        state.private_data_confirmation.record_confirmation(
            plan, confirmation, actor_id="operator:test", policy_revision="test:1"
        )
        selected = product.desired_state.snapshot()
        removed = product.management.submit(
            PluginManagementCommandV1(
                action="remove",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:remove-for-crash",
                    idempotency_key="operator:remove-for-crash",
                    expected_inventory_revision=selected.inventory_revision,
                    installation_key=key,
                    desired_state="absent",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision="operator:1",
                ),
            )
        )
        assert removed.result is not None
        assert removed.result.disposition == "succeeded"

        def interrupt(*_args: object) -> None:
            raise RuntimeError("injected deletion interruption")

        if interruption in {"after_rename", "tampered_tombstone"}:
            original = deletion_module._remove_members
            monkeypatch.setattr(deletion_module, "_remove_members", interrupt)
        else:
            original = CodingArchPrivateDataDeletionJournal.record_completion
            monkeypatch.setattr(
                CodingArchPrivateDataDeletionJournal, "record_completion", interrupt
            )
        with pytest.raises(RuntimeError, match="injected deletion interruption"):
            coordinator.delete(plan, confirmation)
        if interruption in {"after_rename", "tampered_tombstone"}:
            monkeypatch.setattr(deletion_module, "_remove_members", original)
        else:
            monkeypatch.setattr(
                CodingArchPrivateDataDeletionJournal, "record_completion", original
            )
        assert not installation_root.exists()
        pending = state.private_data_deletion.current_start()
        assert pending is not None and pending.phase == "renamed"
        assert state.private_data_deletion.receipt_for(plan, confirmation) is None
    finally:
        app.close()

    from loushang.coding.package_private_data_read_owner import (
        CodingArchPrivateDataReadOwner,
    )

    workspace_stat = workspace.lstat()
    reader = CodingArchPrivateDataReadOwner.open(
        layout=layout,
        workspace=workspace,
        workspace_identity=(workspace_stat.st_dev, workspace_stat.st_ino),
    )
    try:
        assert reader.deletion_preview(key) == plan
    finally:
        reader.close()

    if interruption == "tampered_tombstone":
        (tombstone,) = installation_root.parent.glob(".deleting-*")
        (cache_file,) = tombstone.glob("sessions/*/cache.json")
        cache_file.write_text("changed after start", encoding="utf-8")

    reopened = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        state = open_coding_package_product_state(layout, reopened.epoch_runtime)
        data_owner = CodingArchPrivateDataDeletionOwner(
            layout,
            reopened.runtime_owner.product_owner,
            state.private_data_confirmation,
            state.private_data_deletion,
        )
        coordinator = PluginPrivateDataDeletionCoordinator(
            data_owner, confirmation_authority=state.private_data_confirmation
        )
        assert coordinator.preview(key) == plan
        if interruption == "tampered_tombstone":
            with pytest.raises(ValueError, match="tombstone member changed"):
                coordinator.delete(plan, confirmation)
            assert state.private_data_deletion.receipt_for(plan, confirmation) is None
            assert cache_file.read_text(encoding="utf-8") == "changed after start"
            return
        receipt = coordinator.delete(plan, confirmation)
        assert receipt.disposition == "deleted"
        assert state.private_data_deletion.current_start() is None
        assert state.private_data_deletion.receipt_for(plan, confirmation) == receipt
        assert not installation_root.exists()
    finally:
        reopened.close()
