from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import pytest

import loushang.coding.package_private_data_backup as backup_module
import loushang.coding.package_private_data_backup_expiry as expiry_module
import loushang.coding.package_private_data_restore as restore_module
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
from loushang.coding.package_private_data_backup import (
    CodingArchPrivateDataBackupOwner,
    CodingArchPrivateDataBackupReceiptV1,
)
from loushang.coding.package_private_data_backup_expiry import (
    CodingArchPrivateDataBackupExpiryOwner,
    CodingArchPrivateDataBackupExpiryPlanV1,
)
from loushang.coding.package_private_data_backup_expiry_journal import (
    CodingArchPrivateDataBackupExpiryJournal,
)
from loushang.coding.package_private_data_deletion_owner import (
    CodingArchPrivateDataDeletionOwner,
)
from loushang.coding.package_private_data_restore import (
    CodingArchPrivateDataRestoreOwner,
    CodingArchPrivateDataRestorePlanV1,
)
from loushang.coding.package_private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationJournal,
)
from loushang.coding.package_private_data_restore_journal import (
    CodingArchPrivateDataRestoreJournal,
)
from loushang.coding.package_product_management_cli import (
    build_coding_fenced_product_management_cli_ports,
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
    PluginManagementQueryV1,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionCoordinator,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1


@pytest.mark.skipif(os.name != "posix", reason="POSIX Arch private backup")
def test_interrupted_backup_refuses_nonmatching_staged_bytes(tmp_path: Path) -> None:
    directory_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        backup_module._write_or_verify_file(directory_fd, "cache.json", b"wrong")
        with pytest.raises(ValueError, match="existing content changed"):
            backup_module._write_or_verify_file(
                directory_fd, "cache.json", b"private content"
            )
        assert (tmp_path / "cache.json").read_bytes() == b"wrong"
    finally:
        os.close(directory_fd)


@pytest.mark.skipif(os.name != "posix", reason="POSIX Arch private backup")
def test_backup_write_refuses_zero_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        backup_module._write_or_verify_file(directory_fd, "partial", b"pri")
        with monkeypatch.context() as patch:
            patch.setattr(backup_module.os, "write", lambda fd, content: 0)
            with pytest.raises(OSError, match="made no progress"):
                backup_module._write_or_verify_file(directory_fd, "new", b"private")
            with pytest.raises(OSError, match="made no progress"):
                backup_module._write_or_verify_file(directory_fd, "partial", b"private")
        assert (tmp_path / "new").read_bytes() == b""
        assert (tmp_path / "partial").read_bytes() == b"pri"
    finally:
        os.close(directory_fd)


@pytest.mark.skipif(os.name != "posix", reason="POSIX Arch private backup")
@pytest.mark.parametrize("expire_after_confirmation", (False, True))
def test_arch_backup_retention_survives_source_deletion_and_detects_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    expire_after_confirmation: bool,
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
        (private_root / "cache.json").write_text("retained data", encoding="utf-8")
    finally:
        runtime.dispose_runtime()

    try:
        product = app.runtime_owner.product_owner
        backup = CodingArchPrivateDataBackupOwner(layout, product)
        assert backup.snapshot().records[0].status == "unknown"
        with monkeypatch.context() as patch:
            patch.setattr(
                type(product.desired_state),
                "snapshot",
                lambda self: PluginDesiredStateSnapshotV1(0, ()),
            )
            with pytest.raises(ValueError, match="no Product history"):
                backup.retain(key)
        original_write = backup_module._write_or_verify_file

        def interrupt_copy(parent_fd: int, name: str, content: bytes) -> None:
            if name == "cache.json":
                original_write(parent_fd, name, content[:3])
                raise RuntimeError("injected backup interruption")
            original_write(parent_fd, name, content)

        monkeypatch.setattr(backup_module, "_write_or_verify_file", interrupt_copy)
        with pytest.raises(RuntimeError, match="injected backup interruption"):
            backup.retain(key)
        monkeypatch.setattr(backup_module, "_write_or_verify_file", original_write)
        assert backup.snapshot().records[0].status == "unknown"
        receipt = backup.retain(key)
        with pytest.raises(ValueError, match="removed Installation"):
            CodingArchPrivateDataRestoreOwner(layout, product).restore(
                key, receipt.backup_id
            )
        assert (
            CodingArchPrivateDataBackupReceiptV1.from_dict(receipt.to_dict()) == receipt
        )
        assert backup.retain(key) == receipt
        assert backup.snapshot().records[0].status == "retained"
        projection = build_coding_fenced_product_management_cli_ports(
            layout
        ).queries.snapshot(
            PluginManagementQueryV1(
                correlation_id="arch-backup-retention",
                product_id="coding",
                installation_scope="workspace",
                scope_id=layout.scope_id,
                plugin_ids=("coding.arch.default",),
            )
        )
        assert projection.installations[0].backup_retention is not None
        assert projection.installations[0].backup_retention.status == "retained"
        archive = (
            layout.package_root
            / "installation-backups"
            / coding_arch_installation_private_data_root(layout, key).name
            / receipt.backup_id
        )
        archived_file = next(archive.glob("files/sessions/*/cache.json"))
        assert archived_file.read_text(encoding="utf-8") == "retained data"

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
            confirmation_id="operator:delete-backed-up-arch",
        )
        state.private_data_confirmation.record_confirmation(
            plan, confirmation, actor_id="operator:test", policy_revision="test:1"
        )
        selected = product.desired_state.snapshot()
        removed = product.management.submit(
            PluginManagementCommandV1(
                action="remove",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:remove-backed-up-arch",
                    idempotency_key="operator:remove-backed-up-arch",
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
        assert backup.retain(key) == receipt
        with pytest.raises(ValueError, match="lacks completed deletion"):
            CodingArchPrivateDataRestoreOwner(layout, product).restore(
                key, receipt.backup_id
            )
        deletion_receipt = coordinator.delete(plan, confirmation)
        assert deletion_receipt.disposition == "deleted"
        assert backup.snapshot().records[0].status == "retained"
    finally:
        app.close()

    reopened = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        backup = CodingArchPrivateDataBackupOwner(
            layout, reopened.runtime_owner.product_owner
        )
        restore = CodingArchPrivateDataRestoreOwner(
            layout, reopened.runtime_owner.product_owner
        )
        expiry = CodingArchPrivateDataBackupExpiryOwner(
            layout, reopened.runtime_owner.product_owner
        )
        assert backup.snapshot().records[0].status == "retained"
        restore_plan = restore.preview(key, receipt.backup_id)
        assert restore_plan.target_state == "absent"
        with pytest.raises(ValueError, match="not completed"):
            expiry.preview(key, receipt.backup_id, "missing")
        assert (
            CodingArchPrivateDataRestorePlanV1.from_dict(restore_plan.to_dict())
            == restore_plan
        )
        archived_file.write_text("tampered", encoding="utf-8")
        assert backup.snapshot().records[0].status == "unknown"
        with pytest.raises(ValueError, match="backup file size changed"):
            restore.restore(key, receipt.backup_id)
        projection = build_coding_fenced_product_management_cli_ports(
            layout
        ).queries.snapshot(
            PluginManagementQueryV1(
                correlation_id="arch-backup-tamper",
                product_id="coding",
                installation_scope="workspace",
                scope_id=layout.scope_id,
                plugin_ids=("coding.arch.default",),
            )
        )
        assert projection.installations[0].backup_retention is not None
        assert projection.installations[0].backup_retention.status == "unknown"
        assert archived_file.read_text(encoding="utf-8") == "tampered"
        archived_file.write_text("retained data", encoding="utf-8")
        assert backup.snapshot().records[0].status == "retained"
        source_root = coding_arch_installation_private_data_root(layout, key)
        foreign_stage = source_root.parent / (".arch-restore-" + "0" * 64 + ".staging")
        foreign_stage.mkdir(mode=0o700)
        with pytest.raises(ValueError, match="foreign staging debt"):
            restore.restore(key, receipt.backup_id)
        foreign_stage.rmdir()
        original_restore_write = restore_module._write_or_verify_file

        def interrupt_restore(parent_fd: int, name: str, content: bytes) -> None:
            if name == "cache.json":
                original_restore_write(parent_fd, name, content[:3])
                raise RuntimeError("injected restore interruption")
            original_restore_write(parent_fd, name, content)

        with monkeypatch.context() as patch:
            patch.setattr(restore_module, "_write_or_verify_file", interrupt_restore)
            with pytest.raises(RuntimeError, match="injected restore interruption"):
                restore.restore(key, receipt.backup_id)
        assert not source_root.exists()
        restore_journal = CodingArchPrivateDataRestoreJournal(
            reopened.runtime_owner.product_owner.state_root
        )
        assert tuple(event.phase for event in restore_journal.events()) == ("started",)
        with pytest.raises(ValueError, match="not completed"):
            restore.confirm(key, receipt.backup_id)
        reopened.close()
        reopened = open_coding_fenced_product_application_owner(
            layout,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
        backup = CodingArchPrivateDataBackupOwner(
            layout, reopened.runtime_owner.product_owner
        )
        restore = CodingArchPrivateDataRestoreOwner(
            layout, reopened.runtime_owner.product_owner
        )

        def interrupt_completion(self: object, started: object) -> None:
            raise RuntimeError("injected restore completion interruption")

        with monkeypatch.context() as patch:
            patch.setattr(
                CodingArchPrivateDataRestoreJournal,
                "complete",
                interrupt_completion,
            )
            with pytest.raises(RuntimeError, match="completion interruption"):
                restore.restore(key, receipt.backup_id)
        assert source_root.is_dir()
        assert tuple(event.phase for event in restore_journal.events()) == ("started",)
        reopened.close()
        reopened = open_coding_fenced_product_application_owner(
            layout,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
        backup = CodingArchPrivateDataBackupOwner(
            layout, reopened.runtime_owner.product_owner
        )
        restore = CodingArchPrivateDataRestoreOwner(
            layout, reopened.runtime_owner.product_owner
        )
        restored = restore.restore(key, receipt.backup_id)
        assert restored.disposition == "already_present"
        assert restored.restore_id.startswith("arch-restore:")
        assert restore.preview(key, receipt.backup_id).target_state == "same_bytes"
        assert tuple(event.phase for event in restore_journal.events()) == (
            "started",
            "completed",
        )
        with pytest.raises(ValueError, match="another restore"):
            restore_journal.begin(
                key=key,
                backup_id="0" * 64,
                deletion_receipt_id=deletion_receipt.receipt_id,
            )
        restored_file = next(source_root.glob("sessions/*/cache.json"))
        assert restored_file.read_text(encoding="utf-8") == "retained data"
        assert restore.restore(key, receipt.backup_id).disposition == "already_present"
        confirmation = restore.confirm(key, receipt.backup_id)
        assert confirmation.confirmation_id.startswith("arch-restore-confirm:")
        assert restore.confirm(key, receipt.backup_id) == confirmation
        assert (
            restore.verify_confirmation(
                key, receipt.backup_id, confirmation.confirmation_id
            )
            == confirmation
        )
        expiry = CodingArchPrivateDataBackupExpiryOwner(
            layout, reopened.runtime_owner.product_owner
        )
        expiry_plan = expiry.preview(
            key, receipt.backup_id, confirmation.confirmation_id
        )
        assert expiry_plan.backup_receipt_id == receipt.receipt_id
        assert expiry_plan.restored_target_id == confirmation.restored_target_id
        assert (
            CodingArchPrivateDataBackupExpiryPlanV1.from_dict(expiry_plan.to_dict())
            == expiry_plan
        )
        confirmation_journal = CodingArchPrivateDataRestoreConfirmationJournal(
            reopened.runtime_owner.product_owner.state_root
        )
        assert confirmation_journal.records() == (confirmation,)
        if expire_after_confirmation:
            archived_copy = tmp_path / "retained-archive-copy"
            shutil.copytree(archive, archived_copy)
            expiry_confirmation = expiry.confirm(
                expiry_plan,
                actor_id="operator:test",
                policy_revision="test:1",
            )
            assert (
                expiry.confirm(
                    expiry_plan,
                    actor_id="operator:test",
                    policy_revision="test:1",
                )
                == expiry_confirmation
            )
            original_advance = CodingArchPrivateDataBackupExpiryJournal.advance

            def interrupt_after_rename(self, prior, phase):
                if phase == "renamed":
                    raise RuntimeError("injected expiry rename checkpoint failure")
                return original_advance(self, prior, phase)

            with monkeypatch.context() as patch:
                patch.setattr(
                    CodingArchPrivateDataBackupExpiryJournal,
                    "advance",
                    interrupt_after_rename,
                )
                with pytest.raises(RuntimeError, match="rename checkpoint"):
                    expiry.expire(expiry_plan, expiry_confirmation)
            assert not archive.exists()
            assert backup.snapshot().records[0].status == "expiry_pending"

            def interrupt_before_remove(*_args):
                raise RuntimeError("injected expiry removal failure")

            with monkeypatch.context() as patch:
                patch.setattr(
                    expiry_module, "_remove_tombstone", interrupt_before_remove
                )
                with pytest.raises(RuntimeError, match="removal failure"):
                    expiry.expire(expiry_plan, expiry_confirmation)
            assert backup.snapshot().records[0].status == "expiry_pending"
            expiry_receipt = expiry.expire(expiry_plan, expiry_confirmation)
            assert expiry_receipt.receipt_id.startswith("arch-backup-expiry:")
            assert not archive.exists()
            retention = backup.snapshot().records[0]
            assert retention.status == "expired"
            assert retention.expiry_receipt_id == expiry_receipt.receipt_id
            projected = build_coding_fenced_product_management_cli_ports(
                layout
            ).queries.snapshot(
                PluginManagementQueryV1(
                    correlation_id="arch-backup-expired",
                    product_id="coding",
                    installation_scope="workspace",
                    scope_id=layout.scope_id,
                    plugin_ids=("coding.arch.default",),
                )
            )
            projected_retention = projected.installations[0].backup_retention
            assert projected_retention is not None
            assert projected_retention.status == "expired"
            assert projected_retention.expiry_receipt_id == expiry_receipt.receipt_id
            assert expiry.expire(expiry_plan, expiry_confirmation) == expiry_receipt
            shutil.copytree(archived_copy, archive)
            assert backup.snapshot().records[0].status == "unknown"
            with pytest.raises(ValueError, match="reappeared"):
                expiry.expire(expiry_plan, expiry_confirmation)
            shutil.rmtree(archive)
            reopened.close()
            reopened = open_coding_fenced_product_application_owner(
                layout,
                workspace=workspace,
                runtime_version="2.0.0",
                runtime_protocol_epoch=2,
            )
            reopened_expiry = CodingArchPrivateDataBackupExpiryOwner(
                layout, reopened.runtime_owner.product_owner
            )
            assert (
                reopened_expiry.expire(expiry_plan, expiry_confirmation)
                == expiry_receipt
            )
            reopened_retention = (
                CodingArchPrivateDataBackupOwner(
                    layout, reopened.runtime_owner.product_owner
                )
                .snapshot()
                .records[0]
            )
            assert reopened_retention.status == "expired"
            assert reopened_retention.expiry_receipt_id == expiry_receipt.receipt_id
            with pytest.raises((OSError, ValueError)):
                reopened_expiry.preview(
                    key, receipt.backup_id, confirmation.confirmation_id
                )
            return
        reopened.close()
        reopened = open_coding_fenced_product_application_owner(
            layout,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
        backup = CodingArchPrivateDataBackupOwner(
            layout, reopened.runtime_owner.product_owner
        )
        restore = CodingArchPrivateDataRestoreOwner(
            layout, reopened.runtime_owner.product_owner
        )
        expiry = CodingArchPrivateDataBackupExpiryOwner(
            layout, reopened.runtime_owner.product_owner
        )
        assert (
            restore.verify_confirmation(
                key, receipt.backup_id, confirmation.confirmation_id
            )
            == confirmation
        )
        assert (
            expiry.preview(
                key, receipt.backup_id, confirmation.confirmation_id
            ).fingerprint
            == expiry_plan.fingerprint
        )
        with pytest.raises(ValueError, match="confirmation is stale"):
            restore.verify_confirmation(key, receipt.backup_id, "foreign")
        confirmation_bytes = confirmation_journal.path.read_bytes()
        confirmation_journal.path.write_bytes(confirmation_bytes + b'{"partial":')
        with pytest.raises(ValueError):
            restore.verify_confirmation(
                key, receipt.backup_id, confirmation.confirmation_id
            )
        with pytest.raises(ValueError):
            expiry.preview(key, receipt.backup_id, confirmation.confirmation_id)
        confirmation_journal.path.write_bytes(confirmation_bytes)
        assert (
            restore.verify_confirmation(
                key, receipt.backup_id, confirmation.confirmation_id
            )
            == confirmation
        )
        archived_file.parent.chmod(0o755)
        assert backup.snapshot().records[0].status == "unknown"
        with pytest.raises(ValueError):
            restore.verify_confirmation(
                key, receipt.backup_id, confirmation.confirmation_id
            )
        with pytest.raises(ValueError):
            expiry.preview(key, receipt.backup_id, confirmation.confirmation_id)
        archived_file.parent.chmod(0o700)
        assert backup.snapshot().records[0].status == "retained"
        assert (
            restore.verify_confirmation(
                key, receipt.backup_id, confirmation.confirmation_id
            )
            == confirmation
        )
        restored_file.write_text("modified data", encoding="utf-8")
        with pytest.raises(ValueError, match="backup content changed"):
            restore.restore(key, receipt.backup_id)
        with pytest.raises(ValueError, match="backup content changed"):
            restore.verify_confirmation(
                key, receipt.backup_id, confirmation.confirmation_id
            )
        with pytest.raises(ValueError, match="backup content changed"):
            expiry.preview(key, receipt.backup_id, confirmation.confirmation_id)
        restored_file.write_text("retained data", encoding="utf-8")
        with pytest.raises(ValueError, match="confirmation is stale"):
            restore.verify_confirmation(
                key, receipt.backup_id, confirmation.confirmation_id
            )
        journal_bytes = restore_journal.path.read_bytes()
        restore_journal.path.write_bytes(journal_bytes + b'{"partial":')
        with pytest.raises(ValueError):
            restore.restore(key, receipt.backup_id)
        restore_journal.path.write_bytes(journal_bytes)
        assert restore.restore(key, receipt.backup_id).restore_id == (
            restored.restore_id
        )
        backup_parent = archive.parent
        moved_parent = backup_parent.with_name(backup_parent.name + ".moved")
        backup_parent.rename(moved_parent)
        backup_parent.symlink_to(moved_parent, target_is_directory=True)
        assert backup.snapshot().records[0].status == "unknown"
    finally:
        reopened.close()
