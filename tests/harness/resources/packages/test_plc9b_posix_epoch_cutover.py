from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import Lock

import pytest

import loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover as posix_epoch_cutover
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverQuiescenceReceiptV1,
    PackageEpochCutoverSnapshotReceiptV1,
    PackagePosixEpochCutoverError,
    PackagePosixEpochCutoverOwner,
    PackagePosixEpochCutoverRequestV1,
    PackagePosixEpochCutoverResultV1,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX-native contract")

STORE_ID = "package-store:posix-cutover"


@dataclass
class _CoordinationOwner:
    active_runtime_lease_ids: tuple[str, ...] = ()
    active_pre_fence_registration_ids: tuple[str, ...] = ()
    owner_revision: int = 1
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
                owner_revision=self.owner_revision,
                active_runtime_lease_ids=self.active_runtime_lease_ids,
                active_pre_fence_registration_ids=(
                    self.active_pre_fence_registration_ids
                ),
            )


@dataclass
class _SnapshotOwner:
    calls: int = 0

    def capture(
        self,
        *,
        store_id: str,
        legacy_root_identity: str,
        quiescence_receipt_id: str,
    ) -> PackageEpochCutoverSnapshotReceiptV1:
        self.calls += 1
        return PackageEpochCutoverSnapshotReceiptV1.create(
            store_id=store_id,
            legacy_root_identity=legacy_root_identity,
            quiescence_receipt_id=quiescence_receipt_id,
            snapshot_id=sha256(
                f"{store_id}:{legacy_root_identity}".encode()
            ).hexdigest(),
            snapshot_revision=self.calls,
            entry_count=3,
            byte_count=17,
        )


def _layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    authority = tmp_path / "package-authority"
    legacy = authority / "legacy"
    epochs = authority / "epochs"
    authority.mkdir(mode=0o700)
    legacy.mkdir(mode=0o700)
    epochs.mkdir(mode=0o700)
    (legacy / "state.json").write_bytes(b'{"legacy":true}\n')
    return authority, legacy, epochs


def _owner(
    tmp_path: Path,
    *,
    coordination: _CoordinationOwner | None = None,
    snapshots: _SnapshotOwner | None = None,
    before_fence_probe=None,
) -> tuple[
    PackagePosixEpochCutoverOwner,
    PackageEpochFenceJournal,
    _CoordinationOwner,
    _SnapshotOwner,
    Path,
    Path,
    Path,
]:
    authority, legacy, epochs = _layout(tmp_path)
    journal = PackageEpochFenceJournal(tmp_path / "package-epoch.jsonl")
    coordination = coordination or _CoordinationOwner()
    snapshots = snapshots or _SnapshotOwner()
    owner = PackagePosixEpochCutoverOwner(
        authority,
        store_id=STORE_ID,
        epoch_journal=journal,
        coordination=coordination,
        snapshots=snapshots,
        before_fence_probe=before_fence_probe,
    )
    return owner, journal, coordination, snapshots, authority, legacy, epochs


def _request(
    owner: PackagePosixEpochCutoverOwner,
    *,
    namespace_id: str = "a" * 64,
) -> PackagePosixEpochCutoverRequestV1:
    return PackagePosixEpochCutoverRequestV1.create(
        store_id=STORE_ID,
        prior_fence=None,
        expected_legacy_root_identity=owner.current_root_identity(),
        namespace_id=namespace_id,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )


def test_posix_cutover_uses_epoch_append_as_the_only_atomic_root_pointer(
    tmp_path: Path,
) -> None:
    owner, journal, coordination, snapshots, authority, legacy, epochs = _owner(
        tmp_path
    )
    request = _request(owner)
    legacy_before = (legacy / "state.json").read_bytes()

    result = owner.cutover(request)
    replay = owner.cutover(request)

    assert result.disposition == "fenced"
    assert result.code == "ok"
    assert result.fence is not None
    assert result.switch_receipt is not None
    assert result.failure is None
    assert replay == result
    assert coordination.calls == 1
    assert snapshots.calls == 1
    assert journal.records() == (journal.records()[0],)
    assert journal.current(STORE_ID) == result.fence
    assert result.fence.request.root_switch_receipt_id == (
        result.switch_receipt.switch_receipt_id
    )
    assert result.fence.request.snapshot_receipt_id == (
        result.switch_receipt.snapshot_receipt_id
    )
    assert result.fence.request.quiescence_receipt_id == (
        result.switch_receipt.quiescence_receipt_id
    )
    assert result.fence.request.namespace_id == request.namespace_id
    assert result.fence.fenced_root_identity == owner.current_root_identity()
    assert (epochs / request.namespace_id).is_dir()
    assert (legacy / "state.json").read_bytes() == legacy_before
    assert not (authority / "active-root").exists()
    assert PackagePosixEpochCutoverRequestV1.from_dict(request.to_dict()) == request
    assert PackagePosixEpochCutoverResultV1.from_dict(result.to_dict()) == result
    serialized = repr((request, result)).lower()
    for forbidden in ("password", "credential", "token", str(tmp_path).lower()):
        assert forbidden not in serialized

    detached = tmp_path / "detached-authority"
    authority.rename(detached)
    detached.rename(authority)
    detached_epoch = tmp_path / "detached-epoch"
    (epochs / request.namespace_id).rename(detached_epoch)
    detached_epoch.rmdir()


def test_posix_cutover_advances_only_from_the_exact_current_namespace(
    tmp_path: Path,
) -> None:
    owner, journal, coordination, snapshots, _authority, _legacy, epochs = _owner(
        tmp_path
    )
    first_request = _request(owner, namespace_id="a" * 64)
    first = owner.cutover(first_request)
    assert first.fence is not None
    second_request = PackagePosixEpochCutoverRequestV1.create(
        store_id=STORE_ID,
        prior_fence=first.fence,
        expected_legacy_root_identity=owner.current_root_identity(),
        namespace_id="2" * 64,
        minimum_runtime_version="3.0.0",
        minimum_runtime_protocol_epoch=3,
    )

    second = owner.cutover(second_request)
    replay = owner.cutover(second_request)

    assert second.fence is not None
    assert second.fence.epoch == 2
    assert second.fence.request.prior_fence_id == first.fence.fence_id
    assert second.fence.request.legacy_root_identity == first.fence.fenced_root_identity
    assert second.fence.fenced_root_identity == owner.current_root_identity()
    assert replay == second
    assert len(journal.records()) == 2
    assert coordination.calls == 2
    assert snapshots.calls == 2
    assert (epochs / first_request.namespace_id).is_dir()
    assert (epochs / second_request.namespace_id).is_dir()


def test_posix_cutover_concurrent_exact_requests_converge_once(
    tmp_path: Path,
) -> None:
    owner, journal, coordination, snapshots, _authority, _legacy, epochs = _owner(
        tmp_path
    )
    request = _request(owner, namespace_id="3" * 64)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(executor.map(lambda _index: owner.cutover(request), range(16)))

    assert len(set(results)) == 1
    assert len(journal.records()) == 1
    assert snapshots.calls == 1
    assert coordination.calls >= 1
    assert tuple(path.name for path in epochs.iterdir()) == (request.namespace_id,)


def test_posix_cutover_refuses_live_pre_fence_writer_before_native_mutation(
    tmp_path: Path,
) -> None:
    registration_id = "b" * 64
    coordination = _CoordinationOwner(
        active_pre_fence_registration_ids=(registration_id,)
    )
    snapshots = _SnapshotOwner()
    owner, journal, _, _, _authority, legacy, epochs = _owner(
        tmp_path,
        coordination=coordination,
        snapshots=snapshots,
    )
    request = _request(owner)
    legacy_before = (legacy / "state.json").read_bytes()

    result = owner.cutover(request)

    assert result.disposition == "rejected"
    assert result.code == "package_runtime_epoch_unsupported"
    assert result.fence is None
    assert result.switch_receipt is None
    assert result.failure is not None
    assert result.failure.barrier == "pre_fence"
    assert result.failure.operator_action == "upgrade_runtime"
    assert result.failure.evidence_ref == coordination.active_pre_fence_registration_ids[0]
    assert coordination.calls == 1
    assert snapshots.calls == 0
    assert journal.records() == ()
    assert tuple(epochs.iterdir()) == ()
    assert (legacy / "state.json").read_bytes() == legacy_before
    assert PackagePosixEpochCutoverResultV1.from_dict(result.to_dict()) == result


def test_posix_cutover_refuses_fence_aware_live_lease_without_append(
    tmp_path: Path,
) -> None:
    lease_id = "c" * 64
    coordination = _CoordinationOwner(active_runtime_lease_ids=(lease_id,))
    owner, journal, _, snapshots, _authority, _legacy, epochs = _owner(
        tmp_path,
        coordination=coordination,
    )

    result = owner.cutover(_request(owner))

    assert result.disposition == "rejected"
    assert result.code == "package_runtime_epoch_unsupported"
    assert result.failure is not None
    assert result.failure.evidence_ref == lease_id
    assert snapshots.calls == 0
    assert journal.records() == ()
    assert tuple(epochs.iterdir()) == ()


def test_posix_cutover_rejects_precreated_namespace_without_trusting_it(
    tmp_path: Path,
) -> None:
    owner, journal, _coordination, snapshots, _authority, _legacy, epochs = _owner(
        tmp_path
    )
    request = _request(owner, namespace_id="d" * 64)
    forged = epochs / request.namespace_id
    forged.mkdir()
    (forged / "attacker").write_bytes(b"preserve")

    with pytest.raises(PackagePosixEpochCutoverError) as raised:
        owner.cutover(request)

    assert raised.value.code == "package_epoch_cutover_namespace_conflict"
    assert snapshots.calls == 1
    assert journal.records() == ()
    assert (forged / "attacker").read_bytes() == b"preserve"


def test_posix_cutover_detects_authority_root_swap_before_fence_and_cleans_residue(
    tmp_path: Path,
) -> None:
    authority, legacy, epochs = _layout(tmp_path)
    detached = tmp_path / "package-authority-detached"
    replacement = tmp_path / "package-authority-replacement"

    def swap_authority() -> None:
        authority.rename(detached)
        replacement.mkdir()
        replacement.rename(authority)

    journal = PackageEpochFenceJournal(tmp_path / "package-epoch.jsonl")
    owner = PackagePosixEpochCutoverOwner(
        authority,
        store_id=STORE_ID,
        epoch_journal=journal,
        coordination=_CoordinationOwner(),
        snapshots=_SnapshotOwner(),
        before_fence_probe=swap_authority,
    )
    request = _request(owner, namespace_id="e" * 64)

    with pytest.raises(PackagePosixEpochCutoverError) as raised:
        owner.cutover(request)

    assert raised.value.code == "package_epoch_cutover_identity_changed"
    assert journal.records() == ()
    assert not (detached / "epochs" / request.namespace_id).exists()
    authority.rmdir()
    detached.rename(authority)
    assert (legacy / "state.json").read_bytes() == b'{"legacy":true}\n'
    assert tuple(epochs.iterdir()) == ()


def test_posix_cutover_detects_epochs_directory_swap_before_fence(
    tmp_path: Path,
) -> None:
    authority, legacy, epochs = _layout(tmp_path)
    detached_epochs = authority / "epochs-detached"

    def swap_epochs() -> None:
        epochs.rename(detached_epochs)
        epochs.mkdir(mode=0o700)

    journal = PackageEpochFenceJournal(tmp_path / "package-epoch.jsonl")
    owner = PackagePosixEpochCutoverOwner(
        authority,
        store_id=STORE_ID,
        epoch_journal=journal,
        coordination=_CoordinationOwner(),
        snapshots=_SnapshotOwner(),
        before_fence_probe=swap_epochs,
    )
    request = _request(owner, namespace_id="1" * 64)

    with pytest.raises(PackagePosixEpochCutoverError) as raised:
        owner.cutover(request)

    assert raised.value.code == "package_epoch_cutover_identity_changed"
    assert journal.records() == ()
    assert not (detached_epochs / request.namespace_id).exists()
    epochs.rmdir()
    detached_epochs.rename(epochs)
    assert (legacy / "state.json").read_bytes() == b'{"legacy":true}\n'
    assert tuple(epochs.iterdir()) == ()


def test_posix_cutover_detects_authority_permission_drift_before_fence(
    tmp_path: Path,
) -> None:
    authority, legacy, epochs = _layout(tmp_path)

    def widen_authority() -> None:
        authority.chmod(0o755)

    journal = PackageEpochFenceJournal(tmp_path / "package-epoch.jsonl")
    owner = PackagePosixEpochCutoverOwner(
        authority,
        store_id=STORE_ID,
        epoch_journal=journal,
        coordination=_CoordinationOwner(),
        snapshots=_SnapshotOwner(),
        before_fence_probe=widen_authority,
    )
    request = _request(owner, namespace_id="4" * 64)

    with pytest.raises(PackagePosixEpochCutoverError) as raised:
        owner.cutover(request)

    assert raised.value.code == "package_epoch_cutover_identity_changed"
    assert journal.records() == ()
    assert not (epochs / request.namespace_id).exists()
    authority.chmod(0o700)
    assert (legacy / "state.json").read_bytes() == b'{"legacy":true}\n'


def test_posix_cutover_releases_every_native_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    success_root = tmp_path / "success"
    success_root.mkdir()
    success_owner, *_success = _owner(success_root)
    refusal_root = tmp_path / "refusal"
    refusal_root.mkdir()
    refusal_owner, *_refusal = _owner(
        refusal_root,
        coordination=_CoordinationOwner(
            active_pre_fence_registration_ids=("5" * 64,)
        ),
    )

    real_open_chain = posix_epoch_cutover._open_ancestor_chain
    real_open_directory_at = posix_epoch_cutover._open_directory_at
    real_close = posix_epoch_cutover.os.close
    opened: set[int] = set()

    def tracking_open_chain(*args, **kwargs):
        descriptors = real_open_chain(*args, **kwargs)
        opened.update(descriptors)
        return descriptors

    def tracking_open_directory_at(*args, **kwargs):
        descriptor = real_open_directory_at(*args, **kwargs)
        opened.add(descriptor)
        return descriptor

    def tracking_close(descriptor: int) -> None:
        opened.discard(descriptor)
        real_close(descriptor)

    monkeypatch.setattr(
        posix_epoch_cutover,
        "_open_ancestor_chain",
        tracking_open_chain,
    )
    monkeypatch.setattr(
        posix_epoch_cutover,
        "_open_directory_at",
        tracking_open_directory_at,
    )
    monkeypatch.setattr(posix_epoch_cutover.os, "close", tracking_close)

    success = success_owner.cutover(_request(success_owner))
    assert success.disposition == "fenced"
    assert opened == set()

    refusal = refusal_owner.cutover(
        _request(refusal_owner, namespace_id="6" * 64)
    )
    assert refusal.disposition == "rejected"
    assert opened == set()


def test_posix_cutover_records_reject_extended_or_forged_wire_values(
    tmp_path: Path,
) -> None:
    owner, _journal, _coordination, _snapshots, *_paths = _owner(tmp_path)
    request = _request(owner)
    extended = request.to_dict()
    extended["legacyPath"] = "/tmp/forged"
    with pytest.raises(ValueError, match="versioned schema"):
        PackagePosixEpochCutoverRequestV1.from_dict(extended)
    forged = request.to_dict()
    forged["requestId"] = "0" * 64
    with pytest.raises(ValueError, match="does not match"):
        PackagePosixEpochCutoverRequestV1.from_dict(forged)
