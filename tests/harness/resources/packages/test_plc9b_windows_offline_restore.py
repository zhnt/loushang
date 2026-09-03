from __future__ import annotations

import os
import stat
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
    PackageEpochFenceRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.offline_restore import (
    PACKAGE_PRE_B_SNAPSHOT_DOMAINS,
    PackageOfflineRestoreError,
    PackageOfflineRestoreRequestV1,
    PackageOfflineRestoreSnapshotEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverQuiescenceReceiptV1,
    PackageEpochCutoverSnapshotReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_offline_restore import (
    PackageWindowsOfflineRestoreMaterializer,
)
from loushang.harness.sandbox.package_windows_legacy_runtime import (
    PackageWindowsLegacyRuntimeActivationOwner,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-native contract")

STORE_ID = "package-store:windows-offline-restore"


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


def _fixture(
    tmp_path: Path,
) -> tuple[
    PackageWindowsOfflineRestoreMaterializer,
    PackageOfflineRestoreRequestV1,
    PackageOfflineRestoreSnapshotEvidenceV1,
    PackageEpochCutoverQuiescenceReceiptV1,
    Path,
    Path,
    Path,
]:
    snapshot_root = tmp_path / "snapshot-authority"
    restore_root = tmp_path / "restore-authority"
    current_b_root = tmp_path / "current-b-authority"
    for root in (snapshot_root, restore_root, current_b_root):
        root.mkdir()
    (current_b_root / "must-not-be-reachable.json").write_bytes(b'{"epoch":"B"}\n')
    snapshot_id = _digest("windows-pre-b-snapshot")
    bundle = snapshot_root / snapshot_id
    payload = bundle / "payload"
    payload.mkdir(parents=True)
    (payload / "store").mkdir()
    (payload / "store" / "plugin.py").write_bytes(b"VALUE = 1\n")
    (payload / "state").mkdir()
    (payload / "state" / "desired.json").write_bytes(b'{"enabled":true}\n')
    (payload / "empty").mkdir()
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
    state_manifest = canonical_json_bytes(
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
    (bundle / "state-manifest.json").write_bytes(state_manifest)
    evidence = PackageOfflineRestoreSnapshotEvidenceV1.create(
        snapshot,
        snapshot_tree_digest=tree_digest,
        state_manifest_digest=_digest(state_manifest),
    )
    journal = PackageEpochFenceJournal(tmp_path / "package-epoch.jsonl")
    current = journal.publish(
        PackageEpochFenceRequestV1.create(
            store_id=STORE_ID,
            prior_fence=None,
            legacy_root_identity=snapshot.legacy_root_identity,
            fenced_root_identity=_directory_identity(current_b_root),
            namespace_id=_digest("current-b-namespace"),
            minimum_runtime_version="2.0.0",
            minimum_runtime_protocol_epoch=2,
            quiescence_receipt_id=snapshot.quiescence_receipt_id,
            snapshot_receipt_id=snapshot.receipt_id,
            root_switch_receipt_id=_digest("root-switch"),
        )
    )
    request = PackageOfflineRestoreRequestV1.create(
        current_fence=current,
        genesis_fence=current,
        snapshot_evidence=evidence,
        restore_namespace_id=_digest("isolated-windows-restore"),
        legacy_runtime_version="1.9.0",
    )
    quiescence = PackageEpochCutoverQuiescenceReceiptV1.create(
        store_id=STORE_ID,
        owner_revision=1,
        active_runtime_lease_ids=(),
        active_pre_fence_registration_ids=(),
    )
    owner = PackageWindowsOfflineRestoreMaterializer(
        snapshot_root,
        restore_root,
        current_b_authority_root=current_b_root,
        store_id=STORE_ID,
    )
    return (
        owner,
        request,
        evidence,
        quiescence,
        payload,
        restore_root,
        current_b_root,
    )


def test_windows_materializes_exact_tree_replays_and_discards(tmp_path: Path) -> None:
    owner, request, evidence, quiescence, source, restore_root, _ = _fixture(tmp_path)

    receipt = owner.restore(request, evidence, quiescence)
    replay = owner.restore(request, evidence, quiescence)

    assert replay == receipt
    restored = restore_root / request.restore_namespace_id / "payload"
    assert _tree_metrics(restored) == _tree_metrics(source)
    assert receipt.legacy_snapshot_exact
    assert receipt.b_namespace_unreachable
    owner.discard(receipt)
    assert not (restore_root / request.restore_namespace_id).exists()
    owner.discard(receipt)


def test_windows_concurrent_owners_converge_on_one_tree(tmp_path: Path) -> None:
    owner, request, evidence, quiescence, _, restore_root, current_b_root = _fixture(
        tmp_path
    )
    second = PackageWindowsOfflineRestoreMaterializer(
        tmp_path / "snapshot-authority",
        restore_root,
        current_b_authority_root=current_b_root,
        store_id=STORE_ID,
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        receipts = tuple(
            executor.map(
                lambda candidate: candidate.restore(request, evidence, quiescence),
                (owner, second, owner, second, owner, second, owner, second),
            )
        )

    assert len(set(receipts)) == 1
    assert set(restore_root.iterdir()) == {
        restore_root / ".offline-restore.lock",
        restore_root / request.restore_namespace_id,
    }


def test_windows_rejects_snapshot_tamper_without_restore_residue(
    tmp_path: Path,
) -> None:
    owner, request, evidence, quiescence, source, restore_root, _ = _fixture(tmp_path)
    (source / "store" / "plugin.py").write_bytes(b"VALUE = 2\n")

    with pytest.raises(PackageOfflineRestoreError) as captured:
        owner.restore(request, evidence, quiescence)

    assert captured.value.code == "package_offline_restore_snapshot_invalid"
    assert set(restore_root.iterdir()) == {restore_root / ".offline-restore.lock"}


def test_windows_rejects_replaced_current_b_authority(tmp_path: Path) -> None:
    owner, request, evidence, quiescence, _, restore_root, current_b_root = _fixture(
        tmp_path
    )
    replaced = tmp_path / "replaced-current-b"
    current_b_root.rename(replaced)
    current_b_root.mkdir()

    with pytest.raises(PackageOfflineRestoreError) as captured:
        owner.restore(request, evidence, quiescence)

    assert captured.value.code == "package_offline_restore_materialization_invalid"
    assert set(restore_root.iterdir()) == {restore_root / ".offline-restore.lock"}


def test_windows_appcontainer_activation_is_exclusive_replayable_and_reversible(
    tmp_path: Path,
) -> None:
    owner, request, evidence, quiescence, _, restore_root, current_b_root = _fixture(
        tmp_path
    )
    materialization = owner.restore(request, evidence, quiescence)
    activation_root = tmp_path / "activation-authority"
    activation_root.mkdir()
    command = (
        os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"),
        "/d",
        "/q",
        "/c",
        (
            "> %LOUSHANG_LEGACY_RUNTIME_READY_PATH% "
            "echo %LOUSHANG_LEGACY_RUNTIME_READY_TOKEN% && "
            "choice /C Y /N /D Y /T 60 >nul 2>&1"
        ),
    )
    activation = PackageWindowsLegacyRuntimeActivationOwner(
        restore_root,
        activation_root,
        current_b_authority_root=current_b_root,
        store_id=STORE_ID,
        legacy_runtime_version=request.legacy_runtime_version,
        command=command,
    )

    receipt = activation.activate(request, materialization)
    replay = activation.activate(request, materialization)

    assert replay == receipt
    assert receipt.exclusive_old_runtime
    assert (activation_root / "active-runtime.json").is_file()
    runtime_root = activation_root / f"runtime-{request.request_id}"
    assert (runtime_root / "ready.txt").is_file()

    activation.deactivate(receipt)
    assert not (activation_root / "active-runtime.json").exists()
    assert not runtime_root.exists()
    activation.deactivate(receipt)
