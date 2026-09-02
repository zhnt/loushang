from __future__ import annotations

import errno
import multiprocessing
import os
import stat
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import Lock

import pytest

import loushang.harness.resources.packages.plugin_lifecycle.posix_offline_restore as posix_restore
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
    PackageEpochFenceReceiptV1,
    PackageEpochFenceRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.offline_restore import (
    PACKAGE_PRE_B_SNAPSHOT_DOMAINS,
    PackageLegacyRuntimeActivationReceiptV1,
    PackageOfflineRestoreError,
    PackageOfflineRestoreMaterializationReceiptV1,
    PackageOfflineRestoreOwner,
    PackageOfflineRestoreRequestV1,
    PackageOfflineRestoreSnapshotEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverQuiescenceReceiptV1,
    PackageEpochCutoverSnapshotReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_offline_restore import (
    PackagePosixOfflineRestoreMaterializer,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX-native contract")

STORE_ID = "package-store:posix-offline-restore"


def _digest(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode()
    return sha256(value).hexdigest()


def _directory_identity(path: Path) -> str:
    metadata = path.stat()
    return _digest(
        canonical_json_bytes(
            {
                "device": metadata.st_dev,
                "fileType": "directory",
                "identityVersion": 1,
                "inode": metadata.st_ino,
            }
        )
    )


def _tree_metrics(payload: Path) -> tuple[str, int, int]:
    entries: list[dict[str, object]] = []
    byte_count = 0
    for path in sorted(payload.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(payload).as_posix()
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if path.is_dir():
            entries.append(
                {
                    "kind": "directory",
                    "logicalPath": relative,
                    "mode": mode,
                }
            )
            continue
        contents = path.read_bytes()
        byte_count += len(contents)
        entries.append(
            {
                "byteCount": len(contents),
                "contentDigest": _digest(contents),
                "kind": "file",
                "logicalPath": relative,
                "mode": mode,
            }
        )
    document = {"entries": entries, "manifestVersion": 1}
    return _digest(canonical_json_bytes(document)), len(entries), byte_count


def _publish_genesis(
    journal: PackageEpochFenceJournal,
    snapshot: PackageEpochCutoverSnapshotReceiptV1,
    *,
    current_b_root_identity: str,
) -> PackageEpochFenceReceiptV1:
    return journal.publish(
        PackageEpochFenceRequestV1.create(
            store_id=STORE_ID,
            prior_fence=None,
            legacy_root_identity=snapshot.legacy_root_identity,
            fenced_root_identity=current_b_root_identity,
            namespace_id=_digest("current-b-namespace"),
            minimum_runtime_version="2.0.0",
            minimum_runtime_protocol_epoch=2,
            quiescence_receipt_id=snapshot.quiescence_receipt_id,
            snapshot_receipt_id=snapshot.receipt_id,
            root_switch_receipt_id=_digest("root-switch"),
        )
    )


def _state_manifest(
    snapshot: PackageEpochCutoverSnapshotReceiptV1,
    *,
    tree_digest: str,
) -> bytes:
    return canonical_json_bytes(
        {
            "byteCount": snapshot.byte_count,
            "coveredDomains": list(PACKAGE_PRE_B_SNAPSHOT_DOMAINS),
            "entryCount": snapshot.entry_count,
            "legacyRootIdentity": snapshot.legacy_root_identity,
            "manifestVersion": 1,
            "snapshotId": snapshot.snapshot_id,
            "snapshotReceiptId": snapshot.receipt_id,
            "snapshotRevision": snapshot.snapshot_revision,
            "storeId": snapshot.store_id,
            "treeDigest": tree_digest,
        }
    )


def _fixture(
    tmp_path: Path,
) -> tuple[
    PackagePosixOfflineRestoreMaterializer,
    PackageOfflineRestoreRequestV1,
    PackageOfflineRestoreSnapshotEvidenceV1,
    PackageEpochCutoverQuiescenceReceiptV1,
    Path,
    Path,
    Path,
]:
    snapshot_root = tmp_path / "snapshot-authority"
    restore_root = tmp_path / "restore-authority"
    b_root = tmp_path / "current-b-authority"
    snapshot_root.mkdir(mode=0o700)
    restore_root.mkdir(mode=0o700)
    b_root.mkdir(mode=0o700)
    (b_root / "must-not-be-reachable.json").write_bytes(b'{"epoch":"B"}\n')

    snapshot_id = _digest("pre-b-snapshot")
    bundle = snapshot_root / snapshot_id
    payload = bundle / "payload"
    payload.mkdir(parents=True, mode=0o700)
    (payload / "store").mkdir(mode=0o750)
    (payload / "store" / "plugin.py").write_bytes(b"VALUE = 1\n")
    (payload / "state").mkdir(mode=0o700)
    (payload / "state" / "desired.json").write_bytes(b'{"enabled":true}\n')
    (payload / "a").mkdir(mode=0o700)
    (payload / "a" / "z.json").write_bytes(b"{}\n")
    (payload / "a.").write_bytes(b"canonical-order\n")
    (payload / "empty").mkdir(mode=0o500)
    tree_digest, entry_count, byte_count = _tree_metrics(payload)
    snapshot = PackageEpochCutoverSnapshotReceiptV1.create(
        store_id=STORE_ID,
        legacy_root_identity=_digest("legacy-root"),
        quiescence_receipt_id=_digest("cutover-quiescence"),
        snapshot_id=snapshot_id,
        snapshot_revision=1,
        entry_count=entry_count,
        byte_count=byte_count,
    )
    state_manifest = _state_manifest(snapshot, tree_digest=tree_digest)
    (bundle / "state-manifest.json").write_bytes(state_manifest)
    evidence = PackageOfflineRestoreSnapshotEvidenceV1.create(
        snapshot,
        snapshot_tree_digest=tree_digest,
        state_manifest_digest=_digest(state_manifest),
    )
    journal = PackageEpochFenceJournal(tmp_path / "package-epoch.jsonl")
    current = _publish_genesis(
        journal,
        snapshot,
        current_b_root_identity=_directory_identity(b_root),
    )
    request = PackageOfflineRestoreRequestV1.create(
        current_fence=current,
        genesis_fence=current,
        snapshot_evidence=evidence,
        restore_namespace_id=_digest("isolated-restore"),
        legacy_runtime_version="1.9.0",
    )
    quiescence = PackageEpochCutoverQuiescenceReceiptV1.create(
        store_id=STORE_ID,
        owner_revision=1,
        active_runtime_lease_ids=(),
        active_pre_fence_registration_ids=(),
    )
    owner = PackagePosixOfflineRestoreMaterializer(
        snapshot_root,
        restore_root,
        current_b_authority_root=b_root,
        store_id=STORE_ID,
    )
    return owner, request, evidence, quiescence, payload, restore_root, b_root


def _restored_payload(
    restore_root: Path, request: PackageOfflineRestoreRequestV1
) -> Path:
    return restore_root / request.restore_namespace_id / "payload"


@dataclass
class _Snapshots:
    evidence: PackageOfflineRestoreSnapshotEvidenceV1
    calls: int = 0

    def snapshot(
        self,
        snapshot_receipt_id: str,
    ) -> PackageOfflineRestoreSnapshotEvidenceV1 | None:
        self.calls += 1
        if snapshot_receipt_id != self.evidence.snapshot.receipt_id:
            return None
        return self.evidence


@dataclass
class _Coordination:
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
                owner_revision=1,
                active_runtime_lease_ids=(),
                active_pre_fence_registration_ids=(),
            )


@dataclass
class _Activation:
    physical_activations: int = 0

    def __post_init__(self) -> None:
        self._lock = Lock()
        self._receipts: dict[str, PackageLegacyRuntimeActivationReceiptV1] = {}

    def activate(
        self,
        request: PackageOfflineRestoreRequestV1,
        materialization: PackageOfflineRestoreMaterializationReceiptV1,
    ) -> PackageLegacyRuntimeActivationReceiptV1:
        with self._lock:
            receipt = self._receipts.get(request.request_id)
            if receipt is None:
                self.physical_activations += 1
                receipt = PackageLegacyRuntimeActivationReceiptV1.create(
                    request,
                    materialization=materialization,
                    runtime_instance_id=_digest(f"runtime:{request.request_id}"),
                    runtime_lease_id=_digest(f"lease:{request.request_id}"),
                )
                self._receipts[request.request_id] = receipt
            return receipt

    def deactivate(self, receipt: PackageLegacyRuntimeActivationReceiptV1) -> None:
        return None


@dataclass
class _DriftingMaterialization:
    delegate: PackagePosixOfflineRestoreMaterializer
    journal: PackageEpochFenceJournal

    def restore(
        self,
        request: PackageOfflineRestoreRequestV1,
        snapshot: PackageOfflineRestoreSnapshotEvidenceV1,
        quiescence: PackageEpochCutoverQuiescenceReceiptV1,
    ) -> PackageOfflineRestoreMaterializationReceiptV1:
        receipt = self.delegate.restore(request, snapshot, quiescence)
        current = self.journal.current(request.store_id)
        assert current is not None
        self.journal.publish(
            PackageEpochFenceRequestV1.create(
                store_id=request.store_id,
                prior_fence=current,
                legacy_root_identity=current.fenced_root_identity,
                fenced_root_identity=_digest("drifted-b-root"),
                namespace_id=_digest("drifted-b-namespace"),
                minimum_runtime_version="2.0.0",
                minimum_runtime_protocol_epoch=2,
                quiescence_receipt_id=_digest("drifted-quiescence"),
                snapshot_receipt_id=_digest("drifted-snapshot"),
                root_switch_receipt_id=_digest("drifted-root-switch"),
            )
        )
        return receipt

    def discard(
        self,
        receipt: PackageOfflineRestoreMaterializationReceiptV1,
    ) -> None:
        self.delegate.discard(receipt)


def test_posix_offline_restore_materializes_exact_isolated_tree_and_replays(
    tmp_path: Path,
) -> None:
    owner, request, evidence, quiescence, source, restore_root, b_root = _fixture(
        tmp_path
    )
    b_before = (b_root / "must-not-be-reachable.json").read_bytes()

    receipt = owner.restore(request, evidence, quiescence)
    restored = _restored_payload(restore_root, request)
    identity_before = restored.stat().st_ino
    replay = owner.restore(request, evidence, quiescence)

    assert replay == receipt
    assert restored.stat().st_ino == identity_before
    assert receipt.matches(request, evidence)
    assert receipt.legacy_snapshot_exact is True
    assert receipt.b_namespace_unreachable is True
    assert {
        path.relative_to(restored).as_posix(): path.read_bytes()
        for path in restored.rglob("*")
        if path.is_file()
    } == {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    assert not (restored / "state-manifest.json").exists()
    assert (restored / "empty").is_dir()
    assert stat.S_IMODE((restored / "empty").stat().st_mode) == 0o500
    assert stat.S_IMODE((restored / "store" / "plugin.py").stat().st_mode) == (
        stat.S_IMODE((source / "store" / "plugin.py").stat().st_mode)
    )
    assert (b_root / "must-not-be-reachable.json").read_bytes() == b_before
    assert {path.name for path in restore_root.iterdir()} == {
        ".offline-restore.lock",
        request.restore_namespace_id,
    }
    serialized = repr(receipt).lower()
    for forbidden in (str(tmp_path).lower(), "password", "credential", "token"):
        assert forbidden not in serialized


@pytest.mark.parametrize("mutation", ["tree", "state"])
def test_posix_offline_restore_rejects_substituted_snapshot_without_residue(
    tmp_path: Path,
    mutation: str,
) -> None:
    owner, request, evidence, quiescence, source, restore_root, _b_root = _fixture(
        tmp_path
    )
    if mutation == "tree":
        (source / "store" / "plugin.py").write_bytes(b"VALUE = 2\n")
    else:
        manifest = source.parent / "state-manifest.json"
        manifest.write_bytes(manifest.read_bytes() + b"\n")

    with pytest.raises(PackageOfflineRestoreError) as raised:
        owner.restore(request, evidence, quiescence)

    assert raised.value.code == "package_offline_restore_snapshot_invalid"
    assert {path.name for path in restore_root.iterdir()} == {".offline-restore.lock"}


@pytest.mark.parametrize("unsafe_kind", ["symlink", "hardlink", "fifo"])
def test_posix_offline_restore_rejects_aliased_or_special_snapshot_member(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    owner, request, evidence, quiescence, source, restore_root, _b_root = _fixture(
        tmp_path
    )
    target = source / "store" / "plugin.py"
    unsafe = source / "unsafe.py"
    if unsafe_kind == "symlink":
        unsafe.symlink_to(target)
    elif unsafe_kind == "hardlink":
        os.link(target, unsafe)
    else:
        os.mkfifo(unsafe)

    with pytest.raises(PackageOfflineRestoreError) as raised:
        owner.restore(request, evidence, quiescence)

    assert raised.value.code == "package_offline_restore_snapshot_invalid"
    assert {path.name for path in restore_root.iterdir()} == {".offline-restore.lock"}


def test_posix_offline_restore_rejects_extended_snapshot_bundle(
    tmp_path: Path,
) -> None:
    owner, request, evidence, quiescence, source, restore_root, _b_root = _fixture(
        tmp_path
    )
    (source.parent / "foreign.json").write_bytes(b"{}\n")

    with pytest.raises(PackageOfflineRestoreError) as raised:
        owner.restore(request, evidence, quiescence)

    assert raised.value.code == "package_offline_restore_snapshot_invalid"
    assert {path.name for path in restore_root.iterdir()} == {".offline-restore.lock"}


def test_posix_offline_restore_rejects_oversized_snapshot_metadata(
    tmp_path: Path,
) -> None:
    owner, request, evidence, quiescence, source, restore_root, _b_root = _fixture(
        tmp_path
    )
    manifest = source.parent / "state-manifest.json"
    manifest.write_bytes(b"{" + b" " * (1024 * 1024) + b"}")

    with pytest.raises(PackageOfflineRestoreError) as raised:
        owner.restore(request, evidence, quiescence)

    assert raised.value.code == "package_offline_restore_snapshot_invalid"
    assert {path.name for path in restore_root.iterdir()} == {".offline-restore.lock"}


def test_posix_offline_restore_rejects_foreign_precreated_namespace(
    tmp_path: Path,
) -> None:
    owner, request, evidence, quiescence, _source, restore_root, _b_root = _fixture(
        tmp_path
    )
    foreign = restore_root / request.restore_namespace_id
    foreign.mkdir()
    (foreign / "foreign.txt").write_bytes(b"do not delete")

    with pytest.raises(PackageOfflineRestoreError) as raised:
        owner.restore(request, evidence, quiescence)

    assert raised.value.code == "package_offline_restore_materialization_invalid"
    assert (foreign / "foreign.txt").read_bytes() == b"do not delete"


def test_posix_offline_restore_rejects_untrusted_lock_permissions(
    tmp_path: Path,
) -> None:
    owner, request, evidence, quiescence, _source, restore_root, _b_root = _fixture(
        tmp_path
    )
    lock = restore_root / ".offline-restore.lock"
    lock.write_bytes(b"")
    lock.chmod(0o644)

    with pytest.raises(PackageOfflineRestoreError) as raised:
        owner.restore(request, evidence, quiescence)

    assert raised.value.code == "package_offline_restore_materialization_invalid"
    assert lock.exists()
    assert stat.S_IMODE(lock.stat().st_mode) == 0o644


def test_posix_offline_restore_atomic_publish_rejects_racing_namespace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, request, evidence, quiescence, _source, restore_root, _b_root = _fixture(
        tmp_path
    )
    original = posix_restore._rename_directory_noreplace

    def race(
        source_directory_fd: int,
        source_name: str,
        target_directory_fd: int,
        target_name: str,
    ) -> None:
        os.mkdir(target_name, dir_fd=target_directory_fd)
        original(
            source_directory_fd,
            source_name,
            target_directory_fd,
            target_name,
        )

    monkeypatch.setattr(posix_restore, "_rename_directory_noreplace", race)

    with pytest.raises(PackageOfflineRestoreError) as raised:
        owner.restore(request, evidence, quiescence)

    assert raised.value.code == "package_offline_restore_materialization_invalid"
    assert (restore_root / request.restore_namespace_id).is_dir()
    assert not any(path.name.startswith("staging-") for path in restore_root.iterdir())


@pytest.mark.parametrize("phase", ["copy", "receipt", "fsync", "final-validate"])
def test_posix_offline_restore_cleans_exact_namespace_after_injected_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    owner, request, evidence, quiescence, _source, restore_root, _b_root = _fixture(
        tmp_path
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.EIO, f"injected {phase} failure")

    if phase == "copy":
        monkeypatch.setattr(posix_restore, "_copy_tree", fail)
    elif phase == "receipt":
        monkeypatch.setattr(posix_restore, "_write_new_file", fail)
    elif phase == "fsync":
        monkeypatch.setattr(posix_restore, "_fsync_tree", fail)
    else:
        original = posix_restore._validate_restore_namespace
        calls = 0

        def fail_final(*args: object, **kwargs: object):
            nonlocal calls
            calls += 1
            if calls == 2:
                fail()
            return original(*args, **kwargs)

        monkeypatch.setattr(
            posix_restore,
            "_validate_restore_namespace",
            fail_final,
        )

    with pytest.raises(PackageOfflineRestoreError) as raised:
        owner.restore(request, evidence, quiescence)

    assert raised.value.code == "package_offline_restore_materialization_invalid"
    assert {path.name for path in restore_root.iterdir()} == {".offline-restore.lock"}


def test_posix_offline_restore_reports_cleanup_debt_without_deleting_unknown_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, request, evidence, quiescence, _source, restore_root, _b_root = _fixture(
        tmp_path
    )

    def fail_copy(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.ENOSPC, "injected copy failure")

    def fail_cleanup(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.EIO, "injected cleanup failure")

    monkeypatch.setattr(posix_restore, "_copy_tree", fail_copy)
    monkeypatch.setattr(posix_restore, "_remove_owned_namespace", fail_cleanup)

    with pytest.raises(PackageOfflineRestoreError) as raised:
        owner.restore(request, evidence, quiescence)

    assert raised.value.code == "package_offline_restore_cleanup_failed"
    staging = restore_root / f"staging-{request.request_id}"
    assert staging.is_dir()
    assert (staging / "payload").is_dir()


def test_posix_offline_restore_concurrent_owners_converge_on_one_tree(
    tmp_path: Path,
) -> None:
    owner, request, evidence, quiescence, _source, restore_root, _b_root = _fixture(
        tmp_path
    )
    second = PackagePosixOfflineRestoreMaterializer(
        tmp_path / "snapshot-authority",
        restore_root,
        current_b_authority_root=tmp_path / "current-b-authority",
        store_id=STORE_ID,
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        receipts = tuple(
            executor.map(
                lambda index: (owner if index % 2 == 0 else second).restore(
                    request,
                    evidence,
                    quiescence,
                ),
                range(16),
            )
        )

    assert len(set(receipts)) == 1
    assert _restored_payload(restore_root, request).is_dir()
    assert not any(path.name.startswith("staging-") for path in restore_root.iterdir())


def test_posix_offline_restore_candidate_composes_pathless_protocol(
    tmp_path: Path,
) -> None:
    materialization, request, evidence, _quiescence, source, restore_root, b_root = (
        _fixture(tmp_path)
    )
    journal = PackageEpochFenceJournal(tmp_path / "package-epoch.jsonl")
    coordination = _Coordination()
    snapshots = _Snapshots(evidence)
    activation = _Activation()
    owner = PackageOfflineRestoreOwner(
        store_id=STORE_ID,
        epoch_journal=journal,
        coordination=coordination,
        snapshots=snapshots,
        materialization=materialization,
        activation=activation,
    )
    journal_before = journal.path.read_bytes()
    b_before = (b_root / "must-not-be-reachable.json").read_bytes()

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(executor.map(lambda _index: owner.restore(request), range(16)))

    assert len(set(results)) == 1
    result = results[0]
    assert result.disposition == "restored"
    assert result.code == "ok"
    assert result.materialization is not None
    assert result.activation is not None
    assert result.failure is None
    assert result.materialization.legacy_snapshot_exact is True
    assert result.materialization.b_namespace_unreachable is True
    assert result.activation.exclusive_old_runtime is True
    restored = _restored_payload(restore_root, request)
    assert _tree_metrics(restored) == (
        request.snapshot_tree_digest,
        request.snapshot_entry_count,
        request.snapshot_byte_count,
    )
    assert {
        path.relative_to(restored).as_posix(): path.read_bytes()
        for path in restored.rglob("*")
        if path.is_file()
    } == {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    assert activation.physical_activations == 1
    assert coordination.calls == 16
    assert snapshots.calls == 16
    assert journal.path.read_bytes() == journal_before
    assert (b_root / "must-not-be-reachable.json").read_bytes() == b_before


def test_posix_offline_restore_candidate_discards_real_tree_after_fence_drift(
    tmp_path: Path,
) -> None:
    materialization, request, evidence, _quiescence, _source, restore_root, b_root = (
        _fixture(tmp_path)
    )
    journal = PackageEpochFenceJournal(tmp_path / "package-epoch.jsonl")
    coordination = _Coordination()
    activation = _Activation()
    owner = PackageOfflineRestoreOwner(
        store_id=STORE_ID,
        epoch_journal=journal,
        coordination=coordination,
        snapshots=_Snapshots(evidence),
        materialization=_DriftingMaterialization(materialization, journal),
        activation=activation,
    )
    b_before = (b_root / "must-not-be-reachable.json").read_bytes()

    result = owner.restore(request)

    assert result.disposition == "rejected"
    assert result.code == "package_offline_restore_stale"
    assert result.materialization is None
    assert result.activation is None
    assert activation.physical_activations == 0
    assert not (restore_root / request.restore_namespace_id).exists()
    assert not any(path.name.startswith("staging-") for path in restore_root.iterdir())
    assert (b_root / "must-not-be-reachable.json").read_bytes() == b_before


def test_posix_offline_restore_cross_process_lock_publishes_only_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _owner, request, evidence, quiescence, _source, restore_root, b_root = _fixture(
        tmp_path
    )
    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(2)
    results = context.Queue()
    copy_probe = tmp_path / "physical-copy-probe"
    original = posix_restore._copy_tree

    def counted_copy(*args: object, **kwargs: object) -> None:
        descriptor = os.open(
            copy_probe,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        try:
            os.write(descriptor, b"copy\n")
        finally:
            os.close(descriptor)
        original(*args, **kwargs)

    monkeypatch.setattr(posix_restore, "_copy_tree", counted_copy)

    def run_restore() -> None:
        try:
            child_owner = PackagePosixOfflineRestoreMaterializer(
                tmp_path / "snapshot-authority",
                restore_root,
                current_b_authority_root=b_root,
                store_id=STORE_ID,
            )
            barrier.wait(timeout=10)
            receipt = child_owner.restore(request, evidence, quiescence)
            results.put(("ok", receipt.to_dict()))
        except BaseException as exc:  # pragma: no cover - parent reports detail
            results.put(("error", repr(exc)))

    processes = [context.Process(target=run_restore) for _index in range(2)]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=20)
        assert all(not process.is_alive() for process in processes)
        assert all(process.exitcode == 0 for process in processes)
        observed = [results.get(timeout=5) for _index in range(2)]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()
        results.join_thread()

    assert {status for status, _payload in observed} == {"ok"}
    assert observed[0][1] == observed[1][1]
    assert copy_probe.read_bytes() == b"copy\n"
    assert _restored_payload(restore_root, request).is_dir()
    assert not any(path.name.startswith("staging-") for path in restore_root.iterdir())


def test_posix_offline_restore_discard_removes_only_exact_owned_tree(
    tmp_path: Path,
) -> None:
    owner, request, evidence, quiescence, _source, restore_root, b_root = _fixture(
        tmp_path
    )
    receipt = owner.restore(request, evidence, quiescence)
    b_before = (b_root / "must-not-be-reachable.json").read_bytes()

    owner.discard(receipt)
    owner.discard(receipt)

    assert not (restore_root / request.restore_namespace_id).exists()
    assert (b_root / "must-not-be-reachable.json").read_bytes() == b_before


def test_posix_offline_restore_discard_fails_closed_after_tree_tamper(
    tmp_path: Path,
) -> None:
    owner, request, evidence, quiescence, _source, restore_root, _b_root = _fixture(
        tmp_path
    )
    receipt = owner.restore(request, evidence, quiescence)
    restored = _restored_payload(restore_root, request)
    (restored / "foreign.txt").write_bytes(b"not owned")

    with pytest.raises(PackageOfflineRestoreError) as raised:
        owner.discard(receipt)

    assert raised.value.code == "package_offline_restore_cleanup_failed"
    assert (restored / "foreign.txt").read_bytes() == b"not owned"


def test_posix_offline_restore_rejects_noncanonical_durable_receipt(
    tmp_path: Path,
) -> None:
    owner, request, evidence, quiescence, _source, restore_root, _b_root = _fixture(
        tmp_path
    )
    receipt = owner.restore(request, evidence, quiescence)
    marker = restore_root / request.restore_namespace_id / "receipt.json"
    marker.write_bytes(marker.read_bytes() + b"\n")

    with pytest.raises(PackageOfflineRestoreError) as replay_error:
        owner.restore(request, evidence, quiescence)
    with pytest.raises(PackageOfflineRestoreError) as cleanup_error:
        owner.discard(receipt)

    assert replay_error.value.code == "package_offline_restore_materialization_invalid"
    assert cleanup_error.value.code == "package_offline_restore_cleanup_failed"
    assert marker.read_bytes().endswith(b"\n")


def test_posix_offline_restore_revalidates_authority_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, request, evidence, quiescence, _source, restore_root, _b_root = _fixture(
        tmp_path
    )
    original = posix_restore._rename_directory_noreplace

    def swap_root(*args: object) -> None:
        moved = restore_root.with_name("restore-authority-moved")
        restore_root.rename(moved)
        restore_root.mkdir(mode=0o700)
        original(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(posix_restore, "_rename_directory_noreplace", swap_root)

    with pytest.raises(PackageOfflineRestoreError) as raised:
        owner.restore(request, evidence, quiescence)

    assert raised.value.code == "package_offline_restore_materialization_invalid"
    assert tuple(restore_root.iterdir()) == ()
    detached = restore_root.with_name("restore-authority-moved")
    assert {path.name for path in detached.iterdir()} == {".offline-restore.lock"}


def test_posix_offline_restore_revalidates_current_b_after_final_tree_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, request, evidence, quiescence, _source, restore_root, b_root = _fixture(
        tmp_path
    )
    original = posix_restore._validate_restore_namespace
    calls = 0

    def swap_after_final_validation(
        *args: object,
        **kwargs: object,
    ) -> PackageOfflineRestoreMaterializationReceiptV1:
        nonlocal calls
        receipt = original(*args, **kwargs)
        calls += 1
        if calls == 2:
            b_root.rename(b_root.with_name("current-b-authority-moved"))
            b_root.mkdir(mode=0o700)
        return receipt

    monkeypatch.setattr(
        posix_restore,
        "_validate_restore_namespace",
        swap_after_final_validation,
    )

    with pytest.raises(PackageOfflineRestoreError) as raised:
        owner.restore(request, evidence, quiescence)

    assert raised.value.code == "package_offline_restore_materialization_invalid"
    assert {path.name for path in restore_root.iterdir()} == {".offline-restore.lock"}
    assert tuple(b_root.iterdir()) == ()
    moved = b_root.with_name("current-b-authority-moved")
    assert (moved / "must-not-be-reachable.json").is_file()


def test_posix_offline_restore_requires_request_bound_current_b_identity(
    tmp_path: Path,
) -> None:
    _owner, request, evidence, quiescence, _source, restore_root, _b_root = _fixture(
        tmp_path
    )
    substituted_b_root = tmp_path / "substituted-current-b-authority"
    substituted_b_root.mkdir(mode=0o700)
    owner = PackagePosixOfflineRestoreMaterializer(
        tmp_path / "snapshot-authority",
        restore_root,
        current_b_authority_root=substituted_b_root,
        store_id=STORE_ID,
    )

    with pytest.raises(PackageOfflineRestoreError) as raised:
        owner.restore(request, evidence, quiescence)

    assert raised.value.code == "package_offline_restore_materialization_invalid"
    assert {path.name for path in restore_root.iterdir()} == {".offline-restore.lock"}


@pytest.mark.parametrize("authority", ["snapshot", "restore", "current-b"])
def test_posix_offline_restore_rejects_configured_authority_replacement(
    tmp_path: Path,
    authority: str,
) -> None:
    owner, request, evidence, quiescence, _source, restore_root, _b_root = _fixture(
        tmp_path
    )
    selected = {
        "snapshot": tmp_path / "snapshot-authority",
        "restore": restore_root,
        "current-b": tmp_path / "current-b-authority",
    }[authority]
    selected.rename(selected.with_name(f"{selected.name}-moved"))
    selected.mkdir(mode=0o700)

    with pytest.raises(PackageOfflineRestoreError) as raised:
        owner.restore(request, evidence, quiescence)

    assert raised.value.code == (
        "package_offline_restore_snapshot_invalid"
        if authority == "snapshot"
        else "package_offline_restore_materialization_invalid"
    )
    assert tuple(selected.iterdir()) == ()


def test_posix_offline_restore_rejects_nested_authorities(tmp_path: Path) -> None:
    snapshot_root = tmp_path / "snapshot-authority"
    restore_root = snapshot_root / "restore-authority"
    restore_root.mkdir(parents=True, mode=0o700)
    snapshot_root.chmod(0o700)

    with pytest.raises(PackageOfflineRestoreError) as raised:
        PackagePosixOfflineRestoreMaterializer(
            snapshot_root,
            restore_root,
            current_b_authority_root=tmp_path / "current-b-authority",
            store_id=STORE_ID,
        )

    assert raised.value.code == "package_offline_restore_materialization_invalid"


def test_posix_offline_restore_rejects_nonprivate_authority(tmp_path: Path) -> None:
    snapshot_root = tmp_path / "snapshot-authority"
    restore_root = tmp_path / "restore-authority"
    current_b_root = tmp_path / "current-b-authority"
    for root in (snapshot_root, restore_root, current_b_root):
        root.mkdir(mode=0o700)
    snapshot_root.chmod(0o750)

    with pytest.raises(PackageOfflineRestoreError) as raised:
        PackagePosixOfflineRestoreMaterializer(
            snapshot_root,
            restore_root,
            current_b_authority_root=current_b_root,
            store_id=STORE_ID,
        )

    assert raised.value.code == "package_offline_restore_materialization_invalid"


def test_posix_offline_restore_rejects_current_b_nested_in_restore_authority(
    tmp_path: Path,
) -> None:
    snapshot_root = tmp_path / "snapshot-authority"
    restore_root = tmp_path / "restore-authority"
    current_b_root = restore_root / "current-b"
    snapshot_root.mkdir(mode=0o700)
    current_b_root.mkdir(parents=True, mode=0o700)
    restore_root.chmod(0o700)

    with pytest.raises(PackageOfflineRestoreError) as raised:
        PackagePosixOfflineRestoreMaterializer(
            snapshot_root,
            restore_root,
            current_b_authority_root=current_b_root,
            store_id=STORE_ID,
        )

    assert raised.value.code == "package_offline_restore_materialization_invalid"


def test_posix_offline_restore_rejects_snapshot_over_configured_budget_before_effect(
    tmp_path: Path,
) -> None:
    _owner, request, evidence, quiescence, _source, restore_root, b_root = _fixture(
        tmp_path
    )
    owner = PackagePosixOfflineRestoreMaterializer(
        tmp_path / "snapshot-authority",
        restore_root,
        current_b_authority_root=b_root,
        store_id=STORE_ID,
        maximum_entries=evidence.snapshot.entry_count - 1,
    )

    with pytest.raises(PackageOfflineRestoreError) as raised:
        owner.restore(request, evidence, quiescence)

    assert raised.value.code == "package_offline_restore_snapshot_invalid"
    assert tuple(restore_root.iterdir()) == ()


def test_posix_offline_restore_rejects_tree_over_configured_depth(
    tmp_path: Path,
) -> None:
    _owner, request, evidence, quiescence, _source, restore_root, b_root = _fixture(
        tmp_path
    )
    owner = PackagePosixOfflineRestoreMaterializer(
        tmp_path / "snapshot-authority",
        restore_root,
        current_b_authority_root=b_root,
        store_id=STORE_ID,
        maximum_depth=1,
    )

    with pytest.raises(PackageOfflineRestoreError) as raised:
        owner.restore(request, evidence, quiescence)

    assert raised.value.code == "package_offline_restore_snapshot_invalid"
    assert {path.name for path in restore_root.iterdir()} == {".offline-restore.lock"}


def test_posix_offline_restore_closes_source_descriptor_when_target_open_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, request, evidence, quiescence, _source, restore_root, _b_root = _fixture(
        tmp_path
    )
    original = posix_restore._open_regular_file
    observed_source_descriptors: list[int] = []

    def fail_target_open(
        directory_fd: int,
        name: str,
        *,
        create_new: bool = False,
        write: bool,
    ) -> int:
        if create_new:
            raise OSError(errno.ENOSPC, "injected target open failure")
        descriptor = original(
            directory_fd,
            name,
            create_new=create_new,
            write=write,
        )
        observed_source_descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr(posix_restore, "_open_regular_file", fail_target_open)

    with pytest.raises(PackageOfflineRestoreError) as raised:
        owner.restore(request, evidence, quiescence)

    assert raised.value.code == "package_offline_restore_materialization_invalid"
    assert observed_source_descriptors
    for descriptor in observed_source_descriptors:
        with pytest.raises(OSError) as closed:
            os.fstat(descriptor)
        assert closed.value.errno == errno.EBADF
    assert {path.name for path in restore_root.iterdir()} == {".offline-restore.lock"}


@pytest.mark.skipif(
    not Path("/proc/self/fd").is_dir(),
    reason="Linux descriptor evidence requires procfs",
)
def test_posix_offline_restore_releases_native_descriptors(tmp_path: Path) -> None:
    owner, request, evidence, quiescence, _source, restore_root, _b_root = _fixture(
        tmp_path
    )
    authority_paths = {
        (tmp_path / "snapshot-authority").resolve(),
        restore_root.resolve(),
        (tmp_path / "current-b-authority").resolve(),
    }
    before = {
        Path(f"/proc/self/fd/{name}").resolve()
        for name in os.listdir("/proc/self/fd")
        if Path(f"/proc/self/fd/{name}").exists()
    }

    receipt = owner.restore(request, evidence, quiescence)
    owner.discard(receipt)

    after = {
        Path(f"/proc/self/fd/{name}").resolve()
        for name in os.listdir("/proc/self/fd")
        if Path(f"/proc/self/fd/{name}").exists()
    }
    leaked = {
        target
        for target in after - before
        if any(target == root or root in target.parents for root in authority_paths)
    }
    assert leaked == set()
