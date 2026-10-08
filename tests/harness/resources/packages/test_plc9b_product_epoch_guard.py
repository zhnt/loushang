from __future__ import annotations

from pathlib import Path

import pytest

from loushang.harness.journal import JournalLockUnavailable, journal_file_lock
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductFileEpochTransactionGuard,
)


def test_product_transaction_blocks_cutover_on_exact_coordination_lock(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "private" / "epoch-coordination"
    guard = PackageProductFileEpochTransactionGuard(
        store_id="package-store:product", coordination_lock=lock_path
    )

    with guard.shared_runtime(store_id="package-store:product"):
        with pytest.raises(JournalLockUnavailable):
            with journal_file_lock(lock_path, "exclusive", blocking=False):
                pytest.fail("cutover entered during a Product transaction")

    with journal_file_lock(lock_path, "exclusive", blocking=False):
        pass


def test_product_transaction_rejects_changed_store_before_lock_creation(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "private" / "epoch-coordination"
    guard = PackageProductFileEpochTransactionGuard(
        store_id="package-store:product", coordination_lock=lock_path
    )

    with pytest.raises(ValueError, match="store"):
        with guard.shared_runtime(store_id="package-store:other"):
            pytest.fail("changed store entered the Product epoch guard")
    assert not lock_path.parent.exists()
