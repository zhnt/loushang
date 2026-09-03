from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceError,
    PackageEpochFenceJournal,
    PackageEpochFenceReceiptV1,
    PackageEpochFenceRequestV1,
    PackageEpochLeaseSnapshotV1,
    PackageEpochRuntimeAdmissionOwner,
    PackageEpochRuntimeAdmissionRequestV1,
    PackageEpochRuntimeAdmissionResultV1,
    PackageEpochRuntimeLeaseV1,
)


def _digest(seed: str) -> str:
    return (seed * 64)[:64]


def _publish_two_epochs(
    tmp_path: Path,
) -> tuple[
    PackageEpochFenceJournal,
    PackageEpochFenceReceiptV1,
    PackageEpochFenceReceiptV1,
]:
    journal = PackageEpochFenceJournal(tmp_path / "package-epoch.jsonl")
    first_request = PackageEpochFenceRequestV1.create(
        store_id="package-store:default",
        prior_fence=None,
        legacy_root_identity=_digest("1"),
        fenced_root_identity=_digest("2"),
        namespace_id=_digest("3"),
        minimum_runtime_version="1.0.0",
        minimum_runtime_protocol_epoch=1,
        quiescence_receipt_id=_digest("4"),
        snapshot_receipt_id=_digest("5"),
        root_switch_receipt_id=_digest("6"),
    )
    first = journal.publish(first_request)
    second_request = PackageEpochFenceRequestV1.create(
        store_id="package-store:default",
        prior_fence=first,
        legacy_root_identity=first.fenced_root_identity,
        fenced_root_identity=_digest("7"),
        namespace_id=_digest("8"),
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
        quiescence_receipt_id=_digest("9"),
        snapshot_receipt_id=_digest("a"),
        root_switch_receipt_id=_digest("b"),
    )
    second = journal.publish(second_request)
    return journal, first, second


@dataclass
class _LeaseAuthority:
    snapshot_value: PackageEpochLeaseSnapshotV1
    calls: int = 0

    def snapshot(self, *, store_id: str) -> PackageEpochLeaseSnapshotV1:
        self.calls += 1
        assert store_id == self.snapshot_value.store_id
        return self.snapshot_value


@dataclass
class _ChangingFenceAuthority:
    fences: tuple[PackageEpochFenceReceiptV1, PackageEpochFenceReceiptV1]
    calls: int = 0

    def current(self, store_id: str) -> PackageEpochFenceReceiptV1:
        assert store_id == self.fences[0].store_id
        fence = self.fences[min(self.calls, 1)]
        self.calls += 1
        return fence


@dataclass
class _InvalidLeaseAuthority:
    calls: int = 0

    def snapshot(self, *, store_id: str) -> object:
        self.calls += 1
        assert store_id == "package-store:default"
        return object()


def test_b4c0_epoch_contract_is_dark_versioned_and_exactly_replayable(
    tmp_path: Path,
) -> None:
    journal, first, second = _publish_two_epochs(tmp_path)

    assert journal.publish(first.request) == second
    assert journal.publish(second.request) == second
    assert PackageEpochFenceRequestV1.from_dict(second.request.to_dict()) == (
        second.request
    )
    assert type(second).from_dict(second.to_dict()) == second
    assert PackageEpochFenceJournal(journal.path).records() == journal.records()
    assert len(journal.records()) == 2


def test_epoch_runtime_admission_rejects_newer_epoch_before_lease_authority(
    tmp_path: Path,
) -> None:
    journal, _first, current = _publish_two_epochs(tmp_path)
    lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id="runtime:old",
        runtime_epoch=1,
        store_root_identity=_digest("2"),
        registration_receipt_id=_digest("c"),
    )
    leases = _LeaseAuthority(
        PackageEpochLeaseSnapshotV1.create(
            store_id=current.store_id,
            owner_revision=1,
            active_leases=(lease,),
        )
    )
    owner = PackageEpochRuntimeAdmissionOwner(fences=journal, leases=leases)
    request = PackageEpochRuntimeAdmissionRequestV1.create(
        fence=current,
        runtime_id=lease.runtime_id,
        runtime_version="1.0.0",
        runtime_protocol_epoch=1,
        runtime_epoch=lease.runtime_epoch,
        store_root_identity=lease.store_root_identity,
        lease_id=lease.lease_id,
    )

    result = owner.admit(request)

    assert result.disposition == "rejected"
    assert result.code == "package_runtime_epoch_unsupported"
    assert result.failure is not None
    assert result.failure.operator_action == "upgrade_runtime"
    assert leases.calls == 0
    assert len(journal.records()) == 2


def test_epoch_runtime_admission_rejects_mixed_active_epoch_without_mutation(
    tmp_path: Path,
) -> None:
    journal, first, current = _publish_two_epochs(tmp_path)
    current_lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id="runtime:current",
        runtime_epoch=current.epoch,
        store_root_identity=current.fenced_root_identity,
        registration_receipt_id=_digest("d"),
    )
    stale_lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id="runtime:stale",
        runtime_epoch=first.epoch,
        store_root_identity=first.fenced_root_identity,
        registration_receipt_id=_digest("e"),
    )
    leases = _LeaseAuthority(
        PackageEpochLeaseSnapshotV1.create(
            store_id=current.store_id,
            owner_revision=2,
            active_leases=(stale_lease, current_lease),
        )
    )
    owner = PackageEpochRuntimeAdmissionOwner(fences=journal, leases=leases)
    request = PackageEpochRuntimeAdmissionRequestV1.create(
        fence=current,
        runtime_id=current_lease.runtime_id,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        runtime_epoch=current_lease.runtime_epoch,
        store_root_identity=current_lease.store_root_identity,
        lease_id=current_lease.lease_id,
    )
    records_before = journal.records()

    result = owner.admit(request)

    assert result.disposition == "rejected"
    assert result.code == "package_runtime_epoch_unsupported"
    assert result.failure is not None
    assert result.failure.operator_action == "offline_restore"
    assert leases.calls == 1
    assert journal.records() == records_before


def test_epoch_runtime_admission_accepts_exact_current_single_epoch_snapshot(
    tmp_path: Path,
) -> None:
    journal, _first, current = _publish_two_epochs(tmp_path)
    lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id="runtime:current",
        runtime_epoch=current.epoch,
        store_root_identity=current.fenced_root_identity,
        registration_receipt_id=_digest("f"),
    )
    leases = _LeaseAuthority(
        PackageEpochLeaseSnapshotV1.create(
            store_id=current.store_id,
            owner_revision=3,
            active_leases=(lease,),
        )
    )
    owner = PackageEpochRuntimeAdmissionOwner(fences=journal, leases=leases)
    request = PackageEpochRuntimeAdmissionRequestV1.create(
        fence=current,
        runtime_id=lease.runtime_id,
        runtime_version="2.0.0+build.1",
        runtime_protocol_epoch=2,
        runtime_epoch=lease.runtime_epoch,
        store_root_identity=lease.store_root_identity,
        lease_id=lease.lease_id,
    )
    records_before = journal.records()

    result = owner.admit(request)

    assert result.disposition == "admitted"
    assert result.code == "ok"
    assert result.receipt is not None
    assert result.receipt.lease_owner_revision == 3
    assert result.failure is None
    assert leases.calls == 1
    assert journal.records() == records_before
    assert PackageEpochRuntimeAdmissionResultV1.from_dict(result.to_dict()) == result


def test_epoch_runtime_admission_rechecks_fence_after_lease_snapshot(
    tmp_path: Path,
) -> None:
    _journal, _first, current = _publish_two_epochs(tmp_path)
    successor_request = PackageEpochFenceRequestV1.create(
        store_id=current.store_id,
        prior_fence=current,
        legacy_root_identity=current.fenced_root_identity,
        fenced_root_identity=_digest("0"),
        namespace_id=_digest("a"),
        minimum_runtime_version="3.0.0",
        minimum_runtime_protocol_epoch=3,
        quiescence_receipt_id=_digest("b"),
        snapshot_receipt_id=_digest("c"),
        root_switch_receipt_id=_digest("d"),
    )
    successor = PackageEpochFenceReceiptV1.create(successor_request)
    fences = _ChangingFenceAuthority((current, successor))
    lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id="runtime:racing",
        runtime_epoch=current.epoch,
        store_root_identity=current.fenced_root_identity,
        registration_receipt_id=_digest("e"),
    )
    leases = _LeaseAuthority(
        PackageEpochLeaseSnapshotV1.create(
            store_id=current.store_id,
            owner_revision=4,
            active_leases=(lease,),
        )
    )
    owner = PackageEpochRuntimeAdmissionOwner(fences=fences, leases=leases)
    request = PackageEpochRuntimeAdmissionRequestV1.create(
        fence=current,
        runtime_id=lease.runtime_id,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        runtime_epoch=lease.runtime_epoch,
        store_root_identity=lease.store_root_identity,
        lease_id=lease.lease_id,
    )

    result = owner.admit(request)

    assert result.disposition == "rejected"
    assert result.failure is not None
    assert result.failure.operator_action == "upgrade_runtime"
    assert result.failure.evidence_ref == successor.fence_id
    assert fences.calls == 2
    assert leases.calls == 1


def test_epoch_runtime_admission_rejects_invalid_lease_owner_projection(
    tmp_path: Path,
) -> None:
    journal, _first, current = _publish_two_epochs(tmp_path)
    lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id="runtime:invalid-projection",
        runtime_epoch=current.epoch,
        store_root_identity=current.fenced_root_identity,
        registration_receipt_id=_digest("1"),
    )
    leases = _InvalidLeaseAuthority()
    owner = PackageEpochRuntimeAdmissionOwner(
        fences=journal,
        leases=leases,  # type: ignore[arg-type]
    )
    request = PackageEpochRuntimeAdmissionRequestV1.create(
        fence=current,
        runtime_id=lease.runtime_id,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        runtime_epoch=lease.runtime_epoch,
        store_root_identity=lease.store_root_identity,
        lease_id=lease.lease_id,
    )

    result = owner.admit(request)

    assert result.disposition == "rejected"
    assert result.failure is not None
    assert result.failure.operator_action == "offline_restore"
    assert leases.calls == 1


def test_epoch_journal_concurrent_exact_publish_appends_each_epoch_once(
    tmp_path: Path,
) -> None:
    journal = PackageEpochFenceJournal(tmp_path / "package-epoch.jsonl")
    request = PackageEpochFenceRequestV1.create(
        store_id="package-store:default",
        prior_fence=None,
        legacy_root_identity=_digest("1"),
        fenced_root_identity=_digest("2"),
        namespace_id=_digest("3"),
        minimum_runtime_version="1.0.0",
        minimum_runtime_protocol_epoch=1,
        quiescence_receipt_id=_digest("4"),
        snapshot_receipt_id=_digest("5"),
        root_switch_receipt_id=_digest("6"),
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        receipts = tuple(executor.map(lambda _index: journal.publish(request), range(16)))

    assert len(set(receipts)) == 1
    assert len(journal.records()) == 1


def test_epoch_journal_repairs_only_an_incomplete_final_record(tmp_path: Path) -> None:
    journal, _first, _second = _publish_two_epochs(tmp_path)
    expected = journal.records()
    with journal.path.open("ab") as stream:
        stream.write(b'{"recordVersion":')

    assert PackageEpochFenceJournal(journal.path).records() == expected
    assert journal.path.read_bytes().endswith(b"\n")


def test_epoch_journal_rejects_duplicate_json_keys_with_stable_error(
    tmp_path: Path,
) -> None:
    journal = PackageEpochFenceJournal(tmp_path / "package-epoch.jsonl")
    journal.path.write_text(
        '{"recordVersion":1,"recordVersion":1}\n',
        encoding="utf-8",
    )

    with pytest.raises(PackageEpochFenceError) as caught:
        journal.records()

    assert caught.value.code == "package_epoch_journal_corrupt"
    assert caught.value.path == journal.path
