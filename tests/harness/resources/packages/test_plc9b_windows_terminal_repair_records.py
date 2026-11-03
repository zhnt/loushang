from __future__ import annotations

from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeLeaseV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
    PackageEpochRuntimeLeaseRecordV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsRuntimeQuiescenceV1,
    _terminal_repaired_runtime_records,
)


def test_windows_terminal_repair_proof_expires_on_later_runtime_record() -> None:
    first = PackageEpochRuntimeLeaseV1.create(
        runtime_id="runtime:one",
        runtime_epoch=1,
        store_root_identity="a" * 64,
        registration_receipt_id="b" * 64,
    )
    second = PackageEpochRuntimeLeaseV1.create(
        runtime_id="runtime:one",
        runtime_epoch=1,
        store_root_identity="a" * 64,
        registration_receipt_id="c" * 64,
    )
    records = (
        PackageEpochRuntimeLeaseRecordV1(1, "store-1", "registered", first),
        PackageEpochRuntimeLeaseRecordV1(2, "store-1", "orphan_repaired", first),
    )
    assert _terminal_repaired_runtime_records(records) == (records[-1],)
    snapshot = PackageWindowsRuntimeQuiescenceV1(
        store_id="store-1",
        owner_revision=3,
        active_runtime_lease_ids=(),
        repaired_runtime_records=(records[-1],),
    )
    assert snapshot.repaired_runtime_records[0].lease == first
    later = records + (
        PackageEpochRuntimeLeaseRecordV1(3, "store-1", "registered", second),
    )
    assert _terminal_repaired_runtime_records(later) == ()
    released = later + (
        PackageEpochRuntimeLeaseRecordV1(4, "store-1", "released", second),
    )
    assert _terminal_repaired_runtime_records(released) == ()
