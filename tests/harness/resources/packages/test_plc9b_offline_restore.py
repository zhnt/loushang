from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from threading import Lock

import pytest

import loushang.harness.resources.packages.plugin_lifecycle.offline_restore as offline_restore
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
    PackageEpochFenceReceiptV1,
    PackageEpochFenceRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.offline_restore import (
    PackageLegacyRuntimeActivationReceiptV1,
    PackageOfflineRestoreMaterializationReceiptV1,
    PackageOfflineRestoreOwner,
    PackageOfflineRestoreRequestV1,
    PackageOfflineRestoreResultV1,
    PackageOfflineRestoreSnapshotEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverQuiescenceReceiptV1,
    PackageEpochCutoverSnapshotReceiptV1,
)

STORE_ID = "package-store:offline-restore"


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _snapshot(
    *,
    legacy_root_identity: str,
    revision: int,
) -> PackageEpochCutoverSnapshotReceiptV1:
    return PackageEpochCutoverSnapshotReceiptV1.create(
        store_id=STORE_ID,
        legacy_root_identity=legacy_root_identity,
        quiescence_receipt_id=_digest(f"quiescence:{revision}"),
        snapshot_id=_digest(f"snapshot:{revision}:{legacy_root_identity}"),
        snapshot_revision=revision,
        entry_count=7,
        byte_count=101,
    )


def _publish_fence(
    journal: PackageEpochFenceJournal,
    *,
    prior: PackageEpochFenceReceiptV1 | None,
    snapshot: PackageEpochCutoverSnapshotReceiptV1,
    namespace_seed: str,
) -> PackageEpochFenceReceiptV1:
    legacy_identity = (
        snapshot.legacy_root_identity
        if prior is None
        else prior.fenced_root_identity
    )
    request = PackageEpochFenceRequestV1.create(
        store_id=STORE_ID,
        prior_fence=prior,
        legacy_root_identity=legacy_identity,
        fenced_root_identity=_digest(f"fenced:{namespace_seed}"),
        namespace_id=_digest(f"namespace:{namespace_seed}"),
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
        quiescence_receipt_id=snapshot.quiescence_receipt_id,
        snapshot_receipt_id=snapshot.receipt_id,
        root_switch_receipt_id=_digest(f"switch:{namespace_seed}"),
    )
    return journal.publish(request)


@dataclass
class _CoordinationOwner:
    active_runtime_lease_ids: tuple[str, ...] = ()
    active_pre_fence_registration_ids: tuple[str, ...] = ()
    calls: int = 0

    def __post_init__(self) -> None:
        self._lock = Lock()

    @contextmanager
    def exclusive_quiescence(
        self,
        *,
        store_id: str,
    ) -> Iterator[PackageEpochCutoverQuiescenceReceiptV1]:
        with self._lock:
            self.calls += 1
            yield PackageEpochCutoverQuiescenceReceiptV1.create(
                store_id=store_id,
                owner_revision=self.calls,
                active_runtime_lease_ids=self.active_runtime_lease_ids,
                active_pre_fence_registration_ids=(
                    self.active_pre_fence_registration_ids
                ),
            )


@dataclass
class _SnapshotEvidence:
    receipts: dict[str, PackageOfflineRestoreSnapshotEvidenceV1]
    calls: int = 0

    def snapshot(
        self,
        snapshot_receipt_id: str,
    ) -> PackageOfflineRestoreSnapshotEvidenceV1 | None:
        self.calls += 1
        return self.receipts.get(snapshot_receipt_id)


@dataclass
class _MaterializationOwner:
    before_return: Callable[[], None] | None = None
    calls: int = 0
    physical_restores: int = 0
    discards: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._lock = Lock()
        self._receipts: dict[str, PackageOfflineRestoreMaterializationReceiptV1] = {}

    def restore(
        self,
        request: PackageOfflineRestoreRequestV1,
        snapshot: PackageOfflineRestoreSnapshotEvidenceV1,
        quiescence: PackageEpochCutoverQuiescenceReceiptV1,
    ) -> PackageOfflineRestoreMaterializationReceiptV1:
        with self._lock:
            self.calls += 1
            receipt = self._receipts.get(request.request_id)
            if receipt is None:
                self.physical_restores += 1
                receipt = PackageOfflineRestoreMaterializationReceiptV1.create(
                    request,
                    snapshot=snapshot,
                    quiescence_receipt_id=quiescence.receipt_id,
                    restored_root_identity=_digest(
                        f"restored:{request.restore_namespace_id}"
                    ),
                )
                self._receipts[request.request_id] = receipt
            if self.before_return is not None:
                callback = self.before_return
                self.before_return = None
                callback()
            return receipt

    def discard(
        self,
        receipt: PackageOfflineRestoreMaterializationReceiptV1,
    ) -> None:
        self.discards.append(receipt.materialization_receipt_id)


@dataclass
class _ActivationOwner:
    mismatch: bool = False
    before_return: Callable[[], None] | None = None
    calls: int = 0
    physical_activations: int = 0
    deactivations: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._lock = Lock()
        self._receipts: dict[str, PackageLegacyRuntimeActivationReceiptV1] = {}

    def activate(
        self,
        request: PackageOfflineRestoreRequestV1,
        materialization: PackageOfflineRestoreMaterializationReceiptV1,
    ) -> PackageLegacyRuntimeActivationReceiptV1:
        with self._lock:
            self.calls += 1
            receipt = self._receipts.get(request.request_id)
            if receipt is None:
                self.physical_activations += 1
                selected = materialization
                if self.mismatch:
                    forged = materialization.to_dict()
                    forged["restoredRootIdentity"] = _digest("wrong-restored-root")
                    forged["materializationReceiptId"] = offline_restore._fingerprint(
                        {
                            key: value
                            for key, value in forged.items()
                            if key != "materializationReceiptId"
                        }
                    )
                    selected = (
                        PackageOfflineRestoreMaterializationReceiptV1.from_dict(
                            forged
                        )
                    )
                receipt = PackageLegacyRuntimeActivationReceiptV1.create(
                    request,
                    materialization=selected,
                    runtime_instance_id=_digest(f"runtime:{request.request_id}"),
                    runtime_lease_id=_digest(f"lease:{request.request_id}"),
                )
                self._receipts[request.request_id] = receipt
            if self.before_return is not None:
                callback = self.before_return
                self.before_return = None
                callback()
            return receipt

    def deactivate(self, receipt: PackageLegacyRuntimeActivationReceiptV1) -> None:
        self.deactivations.append(receipt.activation_receipt_id)


def _fixture(
    tmp_path: Path,
    *,
    coordination: _CoordinationOwner | None = None,
    materialization: _MaterializationOwner | None = None,
    activation: _ActivationOwner | None = None,
) -> tuple[
    PackageOfflineRestoreOwner,
    PackageOfflineRestoreRequestV1,
    PackageEpochFenceJournal,
    PackageEpochCutoverSnapshotReceiptV1,
    _CoordinationOwner,
    _SnapshotEvidence,
    _MaterializationOwner,
    _ActivationOwner,
]:
    journal = PackageEpochFenceJournal(tmp_path / "package-epoch.jsonl")
    legacy_identity = _digest("pre-b-legacy-root")
    snapshot = _snapshot(legacy_root_identity=legacy_identity, revision=1)
    snapshot_evidence = PackageOfflineRestoreSnapshotEvidenceV1.create(
        snapshot,
        snapshot_tree_digest=_digest("pre-b-snapshot-tree"),
        state_manifest_digest=_digest("pre-b-complete-state"),
    )
    current = _publish_fence(
        journal,
        prior=None,
        snapshot=snapshot,
        namespace_seed="genesis",
    )
    request = PackageOfflineRestoreRequestV1.create(
        current_fence=current,
        genesis_fence=current,
        snapshot_evidence=snapshot_evidence,
        restore_namespace_id=_digest("isolated-restore"),
        legacy_runtime_version="1.9.0",
    )
    coordination = coordination or _CoordinationOwner()
    snapshots = _SnapshotEvidence({snapshot.receipt_id: snapshot_evidence})
    materialization = materialization or _MaterializationOwner()
    activation = activation or _ActivationOwner()
    owner = PackageOfflineRestoreOwner(
        store_id=STORE_ID,
        epoch_journal=journal,
        coordination=coordination,
        snapshots=snapshots,
        materialization=materialization,
        activation=activation,
    )
    return (
        owner,
        request,
        journal,
        snapshot,
        coordination,
        snapshots,
        materialization,
        activation,
    )


def test_offline_restore_binds_genesis_snapshot_and_exactly_replays(
    tmp_path: Path,
) -> None:
    owner, request, journal, snapshot, coordination, snapshots, materializer, activation = (
        _fixture(tmp_path)
    )
    journal_before = journal.path.read_bytes()

    first = owner.restore(request)
    replay = owner.restore(request)

    assert first.disposition == "restored"
    assert first.code == "ok"
    assert first.failure is None
    assert first.materialization is not None
    assert first.activation is not None
    assert replay == first
    assert first.materialization.snapshot_receipt_id == snapshot.receipt_id
    assert first.materialization.legacy_snapshot_exact is True
    assert first.materialization.b_namespace_unreachable is True
    assert first.activation.exclusive_old_runtime is True
    assert first.activation.restored_root_identity == (
        first.materialization.restored_root_identity
    )
    assert coordination.calls == 2
    assert snapshots.calls == 2
    assert materializer.physical_restores == 1
    assert activation.physical_activations == 1
    assert journal.path.read_bytes() == journal_before
    assert PackageOfflineRestoreRequestV1.from_dict(request.to_dict()) == request
    assert PackageOfflineRestoreResultV1.from_dict(first.to_dict()) == first
    serialized = repr((request, first)).lower()
    for forbidden in ("password", "credential", "token", str(tmp_path).lower()):
        assert forbidden not in serialized


def test_offline_restore_refuses_live_writer_before_snapshot_or_restore(
    tmp_path: Path,
) -> None:
    coordination = _CoordinationOwner(active_runtime_lease_ids=(_digest("live"),))
    owner, request, journal, _snapshot_receipt, _, snapshots, materializer, activation = (
        _fixture(tmp_path, coordination=coordination)
    )
    before = journal.path.read_bytes()

    result = owner.restore(request)

    assert result.disposition == "rejected"
    assert result.code == "package_runtime_epoch_unsupported"
    assert result.failure is not None
    assert result.failure.stage == "pre_restore"
    assert result.failure.operator_action == "retry"
    assert snapshots.calls == 0
    assert materializer.calls == 0
    assert activation.calls == 0
    assert journal.path.read_bytes() == before


def test_offline_restore_rejects_stale_current_fence_before_effect(
    tmp_path: Path,
) -> None:
    (
        owner,
        request,
        journal,
        _snapshot_receipt,
        coordination,
        snapshots,
        materializer,
        activation,
    ) = _fixture(tmp_path)
    current = journal.current(STORE_ID)
    assert current is not None
    successor_snapshot = _snapshot(
        legacy_root_identity=current.fenced_root_identity,
        revision=2,
    )
    _publish_fence(
        journal,
        prior=current,
        snapshot=successor_snapshot,
        namespace_seed="successor",
    )

    result = owner.restore(request)

    assert result.disposition == "rejected"
    assert result.code == "package_offline_restore_stale"
    assert coordination.calls == 1
    assert snapshots.calls == 0
    assert materializer.calls == 0
    assert activation.calls == 0


def test_offline_restore_rejects_snapshot_substitution_under_exclusive_lock(
    tmp_path: Path,
) -> None:
    owner, request, journal, snapshot, _, snapshots, materializer, activation = (
        _fixture(tmp_path)
    )
    replacement = _snapshot(
        legacy_root_identity=snapshot.legacy_root_identity,
        revision=2,
    )
    snapshots.receipts[snapshot.receipt_id] = (
        PackageOfflineRestoreSnapshotEvidenceV1.create(
            replacement,
            snapshot_tree_digest=_digest("substituted-tree"),
            state_manifest_digest=_digest("substituted-state"),
        )
    )
    before = journal.path.read_bytes()

    result = owner.restore(request)

    assert result.disposition == "rejected"
    assert result.code == "package_offline_restore_snapshot_invalid"
    assert materializer.calls == 0
    assert activation.calls == 0
    assert journal.path.read_bytes() == before


def test_offline_restore_discards_isolated_tree_when_epoch_drifts(
    tmp_path: Path,
) -> None:
    materializer = _MaterializationOwner()
    owner, request, journal, _snapshot_receipt, _, _, _, activation = _fixture(
        tmp_path,
        materialization=materializer,
    )
    current = journal.current(STORE_ID)
    assert current is not None

    def advance_epoch() -> None:
        successor_snapshot = _snapshot(
            legacy_root_identity=current.fenced_root_identity,
            revision=2,
        )
        _publish_fence(
            journal,
            prior=current,
            snapshot=successor_snapshot,
            namespace_seed="racing-successor",
        )

    materializer.before_return = advance_epoch

    result = owner.restore(request)

    assert result.disposition == "rejected"
    assert result.code == "package_offline_restore_stale"
    assert len(materializer.discards) == 1
    assert activation.calls == 0


def test_offline_restore_deactivates_mismatched_old_runtime_and_discards_tree(
    tmp_path: Path,
) -> None:
    activation = _ActivationOwner(mismatch=True)
    owner, request, journal, _snapshot_receipt, _, _, materializer, _ = _fixture(
        tmp_path,
        activation=activation,
    )
    before = journal.path.read_bytes()

    result = owner.restore(request)

    assert result.disposition == "rejected"
    assert result.code == "package_offline_restore_activation_invalid"
    assert len(activation.deactivations) == 1
    assert len(materializer.discards) == 1
    assert journal.path.read_bytes() == before


def test_offline_restore_deactivates_runtime_and_discards_tree_when_epoch_drifts(
    tmp_path: Path,
) -> None:
    activation = _ActivationOwner()
    owner, request, journal, _snapshot_receipt, _, _, materializer, _ = _fixture(
        tmp_path,
        activation=activation,
    )
    current = journal.current(STORE_ID)
    assert current is not None

    def advance_epoch() -> None:
        successor_snapshot = _snapshot(
            legacy_root_identity=current.fenced_root_identity,
            revision=2,
        )
        _publish_fence(
            journal,
            prior=current,
            snapshot=successor_snapshot,
            namespace_seed="post-activation-successor",
        )

    activation.before_return = advance_epoch

    result = owner.restore(request)

    assert result.disposition == "rejected"
    assert result.code == "package_offline_restore_stale"
    assert len(activation.deactivations) == 1
    assert len(materializer.discards) == 1


def test_offline_restore_concurrent_exact_requests_converge_on_one_effect(
    tmp_path: Path,
) -> None:
    owner, request, journal, _snapshot_receipt, _, _, materializer, activation = (
        _fixture(tmp_path)
    )
    before = journal.path.read_bytes()

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(executor.map(lambda _index: owner.restore(request), range(16)))

    assert len(set(results)) == 1
    assert materializer.physical_restores == 1
    assert activation.physical_activations == 1
    assert journal.path.read_bytes() == before


def test_offline_restore_wire_records_reject_extensions_and_forgery(
    tmp_path: Path,
) -> None:
    owner, request, *_rest = _fixture(tmp_path)
    result = owner.restore(request)
    extended = request.to_dict()
    extended["restorePath"] = "/forged"
    with pytest.raises(ValueError, match="versioned schema"):
        PackageOfflineRestoreRequestV1.from_dict(extended)
    forged = result.to_dict()
    forged["requestId"] = "0" * 64
    with pytest.raises(ValueError, match="request identity"):
        PackageOfflineRestoreResultV1.from_dict(forged)
