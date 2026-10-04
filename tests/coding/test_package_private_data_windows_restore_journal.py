"""Portable phase validation for native Windows restore receipts."""

from __future__ import annotations

import json
import stat
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding.package_private_data_deletion_preview import (
    CodingArchPrivateDataTargetSnapshotV1,
)
from loushang.coding.package_private_data_restore_journal import (
    CodingArchPrivateDataRestoreEventV1,
)
from loushang.coding.package_private_data_restore_records import (
    CodingArchPrivateDataRestorePlanV1,
)
from loushang.coding.package_private_data_windows_restore_journal import (
    CodingWindowsArchPrivateDataRestoreTransaction,
    CodingWindowsArchRestorePublicationV1,
    _decode_event,
    _validate_sequence,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)


def _events() -> tuple[
    CodingArchPrivateDataRestoreEventV1,
    CodingArchPrivateDataRestoreEventV1,
]:
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace:" + "a" * 64,
        plugin_id="coding.arch.default",
    )
    started = CodingArchPrivateDataRestoreEventV1.create(
        revision=1,
        phase="started",
        installation_key=key,
        backup_id="b" * 64,
        deletion_receipt_id="arch-deletion:portable",
    )
    completed = CodingArchPrivateDataRestoreEventV1.create(
        revision=2,
        phase="completed",
        installation_key=key,
        backup_id=started.backup_id,
        deletion_receipt_id=started.deletion_receipt_id,
    )
    return started, completed


def test_windows_restore_event_chain_requires_exact_phases() -> None:
    started, completed = _events()
    _validate_sequence((started, completed))
    for event in (started, completed):
        assert _decode_event(canonical_json_bytes(event.to_dict()) + b"\n") == event
    with pytest.raises(ValueError, match="completion has no start"):
        _validate_sequence(
            (
                CodingArchPrivateDataRestoreEventV1.create(
                    revision=1,
                    phase="completed",
                    installation_key=started.installation_key,
                    backup_id=started.backup_id,
                    deletion_receipt_id=started.deletion_receipt_id,
                ),
            )
        )
    with pytest.raises(ValueError, match="starts conflict"):
        _validate_sequence(
            (
                started,
                CodingArchPrivateDataRestoreEventV1.create(
                    revision=2,
                    phase="started",
                    installation_key=started.installation_key,
                    backup_id=started.backup_id,
                    deletion_receipt_id=started.deletion_receipt_id,
                ),
            )
        )
    with pytest.raises(ValueError, match="starts conflict"):
        _validate_sequence(
            (
                started,
                completed,
                CodingArchPrivateDataRestoreEventV1.create(
                    revision=3,
                    phase="started",
                    installation_key=started.installation_key,
                    backup_id="c" * 64,
                    deletion_receipt_id=started.deletion_receipt_id,
                ),
            )
        )
    with pytest.raises(ValueError, match="noncanonical"):
        _decode_event(json.dumps(started.to_dict(), indent=2).encode())
    with pytest.raises(ValueError, match="invalid"):
        _decode_event(b'{"revision":1,"revision":1}')


def test_windows_restore_transaction_cannot_escape_offline_gate() -> None:
    transaction = CodingWindowsArchPrivateDataRestoreTransaction(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        -1,
    )
    transaction._close()
    with pytest.raises(ValueError, match="transaction is closed"):
        transaction.events()


def test_windows_restore_publication_binds_stage_identity_before_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import loushang.coding.package_private_data_windows_restore_journal as module

    started, _ = _events()
    root = tmp_path / "restored-root"
    source = CodingArchPrivateDataTargetSnapshotV1(
        root_path_digest=sha256(b"original-root").hexdigest(),
        root_identity=(1, 2, stat.S_IFDIR | 0o700, 0, 1),
        members=(),
    )
    plan = CodingArchPrivateDataRestorePlanV1(
        installation_key=started.installation_key,
        backup_id=started.backup_id,
        deletion_receipt_id=started.deletion_receipt_id,
        source_target_id=source.target_id,
        desired_inventory_revision=1,
        target_state="absent",
    )
    product = SimpleNamespace(state_root=tmp_path)
    transaction = CodingWindowsArchPrivateDataRestoreTransaction(
        SimpleNamespace(), product, -1  # type: ignore[arg-type]
    )
    records: dict[Path, bytes] = {}
    monkeypatch.setattr(
        module, "coding_arch_installation_private_data_root", lambda *_args: root
    )
    monkeypatch.setattr(
        module,
        "inspect_windows_product_private_directory_identity",
        lambda _path: (7, 8),
    )
    monkeypatch.setattr(
        module,
        "_capture_windows_target_snapshot",
        lambda _path, *, expected_root: CodingArchPrivateDataTargetSnapshotV1(
            root_path_digest=sha256(b"staged-root").hexdigest(),
            root_identity=(*expected_root, stat.S_IFDIR | 0o700, 0, 1),
            members=(),
        ),
    )
    monkeypatch.setattr(
        CodingWindowsArchPrivateDataRestoreTransaction,
        "_require_plan_current",
        lambda _self, _plan: source,
    )
    monkeypatch.setattr(
        CodingWindowsArchPrivateDataRestoreTransaction,
        "current_start",
        lambda _self: started,
    )
    monkeypatch.setattr(
        module, "read_windows_private_receipt", lambda path, **_kwargs: records.get(path)
    )
    monkeypatch.setattr(
        module, "write_windows_private_receipt", lambda path, raw: records.setdefault(path, raw)
    )
    identity = (9, 10, stat.S_IFDIR | 0o700, 0, 1)
    publication = transaction.prepare_publication(started, plan, source, 2, identity)
    assert publication.stage_name.endswith(".staging")
    assert transaction.publication_for(started, plan) == publication
    assert transaction.prepare_publication(started, plan, source, 2, identity) == publication
    with pytest.raises(ValueError, match="publication changed"):
        transaction.prepare_publication(
            started, plan, source, 2, (11, 12, stat.S_IFDIR | 0o700, 0, 1)
        )
    records[transaction._publication_path(started)] = b'{"restoreId":"duplicate","restoreId":"duplicate"}'
    with pytest.raises(ValueError, match="publication is invalid"):
        transaction.publication_for(started, plan)
    with pytest.raises(ValueError, match="publication fields changed"):
        CodingWindowsArchRestorePublicationV1.from_dict({"restoreId": started.restore_id})


def test_windows_restore_replays_original_publication_after_unrelated_desired_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import loushang.coding.package_private_data_windows_restore_journal as module

    started, _ = _events()
    source = CodingArchPrivateDataTargetSnapshotV1(
        root_path_digest=sha256(b"original-root").hexdigest(),
        root_identity=(1, 2, stat.S_IFDIR | 0o700, 0, 1),
        members=(),
    )
    plan = CodingArchPrivateDataRestorePlanV1(
        installation_key=started.installation_key,
        backup_id=started.backup_id,
        deletion_receipt_id=started.deletion_receipt_id,
        source_target_id=source.target_id,
        desired_inventory_revision=1,
        target_state="absent",
    )
    other_key = replace(started.installation_key, plugin_id="other.plugin")
    changed_key = [other_key]
    desired = SimpleNamespace(
        inventory_revision=2,
        installation=lambda _key: SimpleNamespace(
            latest_instance_revision_ref=object(),
            selection=SimpleNamespace(desired_state="absent"),
        ),
    )
    product = SimpleNamespace(
        state_root=tmp_path,
        desired_state=SimpleNamespace(
            capture=lambda: (
                desired,
                (
                    SimpleNamespace(
                        inventory_revision=2,
                        mutation=SimpleNamespace(installation_key=changed_key[0]),
                    ),
                ),
            )
        ),
    )
    transaction = CodingWindowsArchPrivateDataRestoreTransaction(
        SimpleNamespace(), product, -1  # type: ignore[arg-type]
    )
    publication = CodingWindowsArchRestorePublicationV1(
        restore_id=started.restore_id,
        started_digest=started.record_digest,
        plan_fingerprint=plan.fingerprint,
        generation_number=2,
        stage_identity=(9, 10, stat.S_IFDIR | 0o700, 0, 1),
        parent_identity=(7, 8),
    )
    monkeypatch.setattr(
        module,
        "CodingWindowsArchPrivateDataDeletionTransaction",
        lambda *_args: SimpleNamespace(events=lambda: (), _close=lambda: None),
    )
    monkeypatch.setattr(
        module, "_latest_deletion_receipt", lambda *_args: plan.deletion_receipt_id
    )
    monkeypatch.setattr(
        CodingWindowsArchPrivateDataRestoreTransaction,
        "_verify_plan_archive",
        lambda _self, _plan: source,
    )
    monkeypatch.setattr(
        module,
        "read_windows_private_receipt",
        lambda _path, **_kwargs: canonical_json_bytes(publication.to_dict()) + b"\n",
    )

    assert transaction._require_plan_current(plan) == source
    assert transaction.publication_for(started, plan) == publication
    with pytest.raises(ValueError, match="publication changed"):
        transaction.publication_for(
            started, replace(plan, desired_inventory_revision=2)
        )
    changed_key[0] = started.installation_key
    with pytest.raises(ValueError, match="Product state changed"):
        transaction._require_plan_current(plan)


def test_windows_restore_confirmation_is_immutable_and_strict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import loushang.coding.package_private_data_windows_restore_journal as module

    started, completed = _events()
    restored = CodingArchPrivateDataTargetSnapshotV1(
        root_path_digest=sha256(b"restored-root").hexdigest(),
        root_identity=(1, 2, stat.S_IFDIR | 0o700, 0, 1),
        members=(),
    )
    plan = CodingArchPrivateDataRestorePlanV1(
        installation_key=started.installation_key,
        backup_id=started.backup_id,
        deletion_receipt_id=started.deletion_receipt_id,
        source_target_id=restored.target_id,
        desired_inventory_revision=1,
        target_state="absent",
    )
    transaction = CodingWindowsArchPrivateDataRestoreTransaction(
        SimpleNamespace(), SimpleNamespace(state_root=tmp_path), -1  # type: ignore[arg-type]
    )
    records: dict[Path, bytes] = {}
    monkeypatch.setattr(
        CodingWindowsArchPrivateDataRestoreTransaction,
        "_completed_restore",
        lambda _self, _plan: (completed, restored),
    )
    monkeypatch.setattr(
        module, "windows_listdir_at", lambda _fd: tuple(path.name for path in records)
    )
    monkeypatch.setattr(
        module, "read_windows_private_receipt", lambda path, **_kwargs: records.get(path)
    )
    monkeypatch.setattr(
        module, "write_windows_private_receipt", lambda path, raw: records.setdefault(path, raw)
    )
    confirmation = transaction.confirm_restore(plan)
    assert transaction.confirm_restore(plan) == confirmation
    assert transaction.verify_confirmation(plan, confirmation.confirmation_id) == confirmation
    with pytest.raises(ValueError, match="is stale"):
        transaction.verify_confirmation(plan, "another-confirmation")
    records[transaction._confirmation_path(1)] = b'{"revision":1,"revision":1}'
    with pytest.raises(ValueError, match="is invalid"):
        transaction.verify_confirmation(plan, confirmation.confirmation_id)
