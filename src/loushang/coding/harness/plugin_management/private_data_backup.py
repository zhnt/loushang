"""Complete private-data programs using existing storage/history owners.

Temporary Product binding imports preserve original nominal and fault seams;
they are tracked intermediate dependencies, not final Harness neutrality.
"""

from __future__ import annotations

from pathlib import Path

from loushang.coding.package import private_data_backup as _binding

from . import private_data_backup_records


def retain(
    self: _binding.CodingArchPrivateDataBackupOwner,
    key: _binding.PluginInstallationKeyV1,
) -> _binding.CodingArchPrivateDataBackupReceiptV1:
    source_root = _binding.coding_arch_installation_private_data_root(self.layout, key)
    preview = _binding.CodingArchPrivateDataDeletionPreview(self.layout, self.product)
    with preview._offline():
        state = self.product.desired_state.snapshot().installation(key)
        if state.latest_instance_revision_ref is None:
            raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_01"])
        source = _binding._capture_target_snapshot(
            source_root, private_base=self.layout.private_data_base
        )
        if source.root_identity is None:
            raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_02"])
        receipt = private_data_backup_records.make_backup_receipt(key, source)
        return _binding.retain_private_archive(
            source_root,
            source,
            receipt,
            key,
            private_base=self.layout.private_data_base,
            backup_parent=_binding._backup_parent(self.layout, key),
            io=_binding._private_io,
            codec=_binding._archive_codec,
            recapture=lambda: _binding._capture_target_snapshot(
                source_root, private_base=self.layout.private_data_base
            ),
            prepare=_binding._prepare_private_tree,
            write_file=_binding._write_or_verify_file,
        )


def verify(
    self: _binding.CodingArchPrivateDataBackupOwner,
    key: _binding.PluginInstallationKeyV1,
    backup_id: str,
) -> _binding.CodingArchPrivateDataBackupReceiptV1:
    """Reopen one exact archive without requiring its source to survive."""

    if not _binding._digest(backup_id):
        raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_03"])
    parent = _binding._backup_parent(self.layout, key)
    preview = _binding.CodingArchPrivateDataDeletionPreview(self.layout, self.product)
    with preview._offline():
        return verify_retained_archive(
            self.layout.private_data_base, parent, key, backup_id
        )


def verify_retained_archive(
    private_base: Path,
    parent: Path,
    key: _binding.PluginInstallationKeyV1,
    backup_id: str,
) -> _binding.CodingArchPrivateDataBackupReceiptV1:
    with _binding.closing_descriptor(
        _binding._open_private_path(private_base, parent)
    ) as parent_fd:
        receipt, source = _binding._read_manifest(parent_fd, backup_id)
        if receipt.installation_key != key or receipt.backup_id != backup_id:
            raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_04"])
        _binding._verify_archive(parent_fd, backup_id, key, source, receipt)
        return receipt


def retention_snapshot(
    self: _binding.CodingArchPrivateDataBackupReadSource,
) -> _binding.PluginBackupRetentionSnapshotV1:
    from loushang.coding.package.private_data_backup_expiry_journal import (
        CodingArchPrivateDataBackupExpiryJournal,
    )
    from loushang.coding.package.private_data_backup_expiry_records import (
        _tombstone_name,
    )

    self.epoch_runtime.assert_current()
    key = _binding.PluginInstallationKeyV1(
        product_id=_binding._PRIVATE_DATA_PROGRAM_VALUES["value_05"],
        installation_scope="workspace",
        scope_id=self.layout.scope_id,
        plugin_id=_binding._PLUGIN_ID,
    )
    expiry_phase: _binding.PluginBackupRetentionStatus = "unknown"
    expiry_receipt_id: str | None = None
    try:
        events = CodingArchPrivateDataBackupExpiryJournal(
            self.epoch_runtime.control_root / "product-state"
        ).events()
        latest = events[-1] if events else None
        pending = latest is not None and latest.phase in {"started", "renamed"}
        allowed_tombstone = (
            _tombstone_name(latest.plan, latest.confirmation)
            if pending and latest is not None
            else None
        )
        receipts = _binding._retained_receipts(
            self.layout, key, allowed_tombstone=allowed_tombstone
        )
        if (
            latest is not None
            and latest.phase == "completed"
            and any(item.backup_id == latest.plan.backup_id for item in receipts)
        ):
            raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_06"])
        if pending:
            expiry_phase = "expiry_pending"
        elif receipts:
            expiry_phase = "retained"
        elif latest is not None and latest.phase == "completed":
            if latest.receipt is None or latest.plan.installation_key != key:
                raise ValueError(_binding._PRIVATE_DATA_PROGRAM_VALUES["value_08"])
            expiry_phase = "expired"
            expiry_receipt_id = latest.receipt.receipt_id
        trust = "verified"
    except (OSError, ValueError):
        receipts = ()
        trust = "untrusted"
        expiry_phase = "unknown"
    self.epoch_runtime.assert_current()
    revision = _binding._backup_retention_revision(
        expiry_phase, expiry_receipt_id, receipts, trust
    )
    return _binding.PluginBackupRetentionSnapshotV1(
        owner_revision=_binding._PRIVATE_DATA_PROGRAM_VALUES["value_07"] + revision,
        records=(
            _binding.PluginBackupRetentionRecordV1(
                installation_key=key,
                status=expiry_phase,
                expiry_receipt_id=expiry_receipt_id,
            ),
        ),
    )
