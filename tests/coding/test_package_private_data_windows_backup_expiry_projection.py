"""Conservative Windows backup status from native expiry receipts."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.package_private_data_windows_backup as backup_module
import loushang.coding.package_private_data_windows_backup_expiry_journal as journal
from loushang.coding.package_private_data_windows_backup import (
    CodingWindowsArchPrivateDataBackupOwner,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1


@contextmanager
def _guard() -> Iterator[None]:
    yield


def test_windows_backup_status_requires_terminal_receipt_for_expired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace:" + "a" * 64,
        plugin_id="coding.arch.default",
    )
    latest = SimpleNamespace(
        phase="completed",
        plan=SimpleNamespace(
            installation_key=key, backup_id="b" * 64, fingerprint="c" * 64
        ),
        confirmation=SimpleNamespace(confirmation_id="accepted"),
        receipt=SimpleNamespace(receipt_id="arch-backup-expiry:proof"),
    )
    product = SimpleNamespace(
        assert_private_data_read_authority_current=lambda: None,
        gc_gate=SimpleNamespace(read_guard=_guard),
        desired_state=SimpleNamespace(
            snapshot=lambda: SimpleNamespace(
                installation=lambda key: SimpleNamespace(
                    latest_instance_revision_ref="installed"
                )
            )
        ),
        state_root=tmp_path,
    )
    owner = object.__new__(CodingWindowsArchPrivateDataBackupOwner)
    object.__setattr__(
        owner, "layout", SimpleNamespace(scope_id="workspace:" + "a" * 64)
    )
    object.__setattr__(owner, "product", product)
    monkeypatch.setattr(
        journal.CodingWindowsArchBackupExpiryTransaction,
        "_scan",
        lambda self: ((latest,), None),
    )

    class FakeAcl:
        def __enter__(self) -> FakeAcl:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def validate(self, descriptor: int) -> None:
            return None

    monkeypatch.setattr(backup_module, "WindowsPrivateDirectoryAcl", FakeAcl)
    monkeypatch.setattr(
        backup_module,
        "inspect_windows_product_private_directory_identity",
        lambda path: (1, 4),
    )
    native_open_directory = backup_module.open_windows_directory
    monkeypatch.setattr(
        backup_module,
        "open_windows_directory",
        lambda path, **kwargs: (
            native_open_directory(path, **kwargs)
            if os.name == "nt"
            else os.open(path, os.O_RDONLY)
        ),
    )
    monkeypatch.setattr(backup_module, "_directory_identity", lambda fd: (1, 4))
    monkeypatch.setattr(backup_module, "_retained_receipts", lambda *args, **kwargs: ())

    record = owner.snapshot().records[0]
    assert record.status == "expired"
    assert record.expiry_receipt_id == latest.receipt.receipt_id

    latest.phase = "renamed"
    pending = owner.snapshot().records[0]
    assert pending.status == "expiry_pending"
    assert pending.expiry_receipt_id is None

    latest.phase = "completed"
    latest.receipt = None
    unknown = owner.snapshot().records[0]
    assert unknown.status == "unknown"
    assert unknown.expiry_receipt_id is None

    latest.receipt = SimpleNamespace(receipt_id="arch-backup-expiry:proof")
    monkeypatch.setattr(
        backup_module,
        "_retained_receipts",
        lambda *args, **kwargs: (SimpleNamespace(backup_id=latest.plan.backup_id),),
    )
    assert owner.snapshot().records[0].status == "unknown"

    monkeypatch.setattr(
        journal.CodingWindowsArchBackupExpiryTransaction,
        "_scan",
        lambda self: ((latest,), 5),
    )
    assert owner.snapshot().records[0].status == "unknown"

    def missing_state(path: Path) -> tuple[int, int]:
        raise FileNotFoundError(path)

    monkeypatch.setattr(
        backup_module,
        "inspect_windows_product_private_directory_identity",
        missing_state,
    )
    monkeypatch.setattr(
        backup_module,
        "open_windows_directory",
        lambda path, **kwargs: pytest.fail("read created Product state"),
    )
    assert owner.snapshot().records[0].status == "unknown"
