"""Portable checks for the native Windows backup-expiry candidate journal."""

from __future__ import annotations

import stat
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.package_private_data_windows_backup_expiry_journal as journal
from loushang.coding.package_private_data_backup_expiry_records import (
    CodingArchPrivateDataBackupExpiryConfirmationV1,
    CodingArchPrivateDataBackupExpiryPlanV1,
    CodingArchPrivateDataBackupExpiryReceiptV1,
)
from loushang.coding.package_private_data_deletion_preview import (
    CodingArchPrivateDataMemberV1,
    CodingArchPrivateDataTargetSnapshotV1,
)
from loushang.coding.package_private_data_windows_archive_snapshot import (
    CodingWindowsArchBackupArchiveSnapshotV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)


def _candidate() -> tuple[
    CodingArchPrivateDataBackupExpiryPlanV1,
    CodingArchPrivateDataBackupExpiryConfirmationV1,
    CodingWindowsArchBackupArchiveSnapshotV1,
]:
    files = CodingArchPrivateDataTargetSnapshotV1(
        root_path_digest=sha256(b"archive/files").hexdigest(),
        root_identity=(1, 2, stat.S_IFDIR | 0o700, 0, 1),
        members=(),
    )
    archive = CodingWindowsArchBackupArchiveSnapshotV1(
        root_path_digest=sha256(b"archive").hexdigest(),
        root_identity=(1, 3, stat.S_IFDIR | 0o700, 0, 1),
        files=files,
        manifest=CodingArchPrivateDataMemberV1(
            "manifest.json",
            "file",
            (1, 4, stat.S_IFREG | 0o600, 1, 1),
            sha256(b"x").hexdigest(),
        ),
    )
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace:" + "a" * 64,
        plugin_id="coding.arch.default",
    )
    plan = CodingArchPrivateDataBackupExpiryPlanV1(
        installation_key=key,
        backup_id="b" * 64,
        backup_receipt_id="arch-backup:" + "b" * 64,
        source_target_id="present:" + "c" * 64,
        confirmation_id="arch-restore-confirm:" + "d" * 64,
        restore_completion_digest="e" * 64,
        restored_target_id="present:" + "f" * 64,
        desired_inventory_revision=3,
        archive_root_identity=archive.root_identity,
        archive_target_id=archive.target_id,
    )
    return (
        plan,
        CodingArchPrivateDataBackupExpiryConfirmationV1.create(
            plan, actor_id="operator:test", policy_revision="test:1"
        ),
        archive,
    )


def _events() -> tuple[journal.CodingWindowsArchBackupExpiryEventV1, ...]:
    plan, confirmation, archive = _candidate()
    receipt = CodingArchPrivateDataBackupExpiryReceiptV1.create(plan, confirmation)
    return (
        journal.CodingWindowsArchBackupExpiryEventV1(
            1, "confirmed", plan, confirmation
        ),
        journal.CodingWindowsArchBackupExpiryEventV1(
            2, "started", plan, confirmation, archive
        ),
        journal.CodingWindowsArchBackupExpiryEventV1(
            3, "renamed", plan, confirmation, archive
        ),
        journal.CodingWindowsArchBackupExpiryEventV1(
            4, "completed", plan, confirmation, archive, receipt
        ),
    )


def test_windows_expiry_events_require_exact_sequence_and_archive() -> None:
    events = _events()
    _, _, archive = _candidate()
    journal._validate_sequence(events)
    for event in events:
        assert (
            journal.CodingWindowsArchBackupExpiryEventV1.from_dict(event.to_dict())
            == event
        )
    with pytest.raises(ValueError, match="history changed"):
        journal._validate_sequence((events[0], replace(events[2], revision=2)))
    with pytest.raises(ValueError, match="history overlaps"):
        journal._validate_sequence((events[0], replace(events[0], revision=2)))
    with pytest.raises(ValueError, match="history changed"):
        journal._validate_sequence(
            (events[0], events[1], replace(events[3], revision=3))
        )
    with pytest.raises(ValueError, match="archive changed"):
        replace(
            events[1],
            archive=replace(archive, root_identity=(1, 5, stat.S_IFDIR | 0o700, 0, 1)),
        )
    with pytest.raises(ValueError, match="receipt changed"):
        replace(events[3], receipt=None)


def test_windows_expiry_confirm_and_start_are_replayable_under_product_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, confirmation, archive = _candidate()
    saved: dict[str, bytes] = {}
    monkeypatch.setattr(
        journal.CodingWindowsArchPrivateDataBackupExpiryPreview,
        "__post_init__",
        lambda self: None,
    )
    monkeypatch.setattr(
        journal.CodingWindowsArchPrivateDataBackupExpiryPreview,
        "_preview_locked",
        lambda self, restore, key, backup_id, confirmation_id: plan,
    )
    monkeypatch.setattr(journal, "windows_listdir_at", lambda state_fd: tuple(saved))
    monkeypatch.setattr(
        journal,
        "read_windows_private_receipt",
        lambda path, maximum_bytes: saved.get(path.name),
    )

    def publish(path: Path, raw: bytes, *, maximum_bytes: int) -> None:
        assert len(raw) <= maximum_bytes == journal._MAX_EVENT_BYTES
        if path.name + ".stage" in saved and saved[path.name + ".stage"] != raw:
            raise ValueError("receipt stage conflicts")
        saved.pop(path.name + ".stage", None)
        if path.name in saved and saved[path.name] != raw:
            raise ValueError("receipt changed")
        saved[path.name] = raw

    monkeypatch.setattr(
        journal,
        "write_windows_private_receipt",
        publish,
    )
    transaction = journal.CodingWindowsArchBackupExpiryTransaction(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(state_root=tmp_path),  # type: ignore[arg-type]
        SimpleNamespace(state_fd=5, _require_active=lambda: None),  # type: ignore[arg-type]
    )
    assert (
        transaction.confirm(plan, actor_id="operator:test", policy_revision="test:1")
        == confirmation
    )
    assert (
        transaction.confirm(plan, actor_id="operator:test", policy_revision="test:1")
        == confirmation
    )
    with pytest.raises(ValueError, match="unfinished"):
        transaction.confirm(plan, actor_id="operator:other", policy_revision="test:1")
    started = transaction.begin(plan, confirmation, archive)
    assert started.phase == "started"
    assert transaction.begin(plan, confirmation, archive) == started
    assert len(transaction.events()) == 2
    with pytest.raises(ValueError, match="out of order"):
        transaction.advance(started, "completed")
    saved["arch-backup-expiry-00000002.json"] = b'{"revision":2,"revision":2}\n'
    with pytest.raises(ValueError, match="event is invalid"):
        transaction.events()
    saved["arch-backup-expiry-00000002.json"] = (
        canonical_json_bytes(started.to_dict()) + b"\n"
    )
    saved["arch-backup-expiry-00000003.json.stage"] = b"incomplete"
    with pytest.raises(ValueError, match="needs recovery"):
        transaction.events()
    with pytest.raises(ValueError, match="stage conflicts"):
        transaction.advance(started, "renamed")
    saved["arch-backup-expiry-00000003.json.stage"] = (
        canonical_json_bytes(_events()[2].to_dict()) + b"\n"
    )
    renamed = transaction.advance(started, "renamed")
    assert renamed.phase == "renamed"
    assert transaction.advance(renamed, "renamed") == renamed
    completed = transaction.advance(renamed, "completed")
    assert completed.receipt == CodingArchPrivateDataBackupExpiryReceiptV1.create(
        plan, confirmation
    )
    assert transaction.events() == _events()
    with pytest.raises(ValueError, match="checkpoint changed"):
        transaction.advance(started, "renamed")


def test_windows_expiry_event_accepts_full_archive_with_long_nested_names() -> None:
    plan, confirmation, archive = _candidate()
    session = "a" * 64
    parent = f"sessions/{session}"
    device = 2**64 - 1
    sessions_identity = (device, 6, stat.S_IFDIR | 0o700, 0, 1)
    session_identity = (device, 7, stat.S_IFDIR | 0o700, 0, 1)
    file_identity = (
        device,
        0,
        stat.S_IFREG | 0o600,
        1,
        1790922727000000000,
    )
    members = (
        CodingArchPrivateDataMemberV1("sessions", "directory", sessions_identity),
        CodingArchPrivateDataMemberV1(parent, "directory", session_identity),
        *(
            CodingArchPrivateDataMemberV1(
                f"{parent}/{'页' * 251}{index:04d}",
                "file",
                (file_identity[0], 2**64 - 1 - index, *file_identity[2:]),
                sha256(b"x").hexdigest(),
            )
            for index in range(4094)
        ),
    )
    assert len(members) == 4096
    assert len(members[-1].relative_path.rsplit("/", 1)[-1]) == 255
    archive = replace(
        archive,
        root_identity=(device, 3, stat.S_IFDIR | 0o700, 0, 1),
        files=replace(
            archive.files,
            root_identity=(device, 2, stat.S_IFDIR | 0o700, 0, 1),
            members=members,
        ),
    )
    plan = replace(
        plan,
        archive_root_identity=archive.root_identity,
        archive_target_id=archive.target_id,
    )
    confirmation = CodingArchPrivateDataBackupExpiryConfirmationV1.create(
        plan, actor_id="operator:test", policy_revision="test:1"
    )
    event = journal.CodingWindowsArchBackupExpiryEventV1(
        2, "started", plan, confirmation, archive
    )
    payload = canonical_json_bytes(event.to_dict()) + b"\n"
    assert 4 * 1024 * 1024 < len(payload) <= journal._MAX_EVENT_BYTES
