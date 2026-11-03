from __future__ import annotations

import ctypes
import json
import os
import stat
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path

import pytest

import loushang.harness.sandbox.package_windows_legacy_runtime as windows_runtime
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
    PackageEpochFenceRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.offline_restore import (
    PACKAGE_PRE_B_SNAPSHOT_DOMAINS,
    PackageLegacyRuntimeActivationReceiptV1,
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
            "for /L %i in (1,1,2147483647) do ver >nul 2>&1"
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

    start = windows_runtime._ActivationStartIntentV1.create(
        request,
        materialization,
        sandbox_profile_digest=activation._profile_digest,
        profile_name=f"Loushang.PLC9B.{request.request_id[:32]}",
        job_name=f"Local\\Loushang.PLC9B.{request.request_id[:32]}",
    )
    starting_path = activation_root / "starting-runtime.json"
    starting_path.write_bytes(canonical_json_bytes(start.to_dict()))
    with pytest.raises(PackageOfflineRestoreError):
        activation.review_incomplete_start(request, materialization)
    assert not (activation_root / ".legacy-runtime.lock").exists()
    with pytest.raises(PackageOfflineRestoreError):
        activation.activate(request, materialization)
    assert starting_path.is_file()
    assert not (activation_root / "active-runtime.json").exists()
    assert activation.review_incomplete_start(request, materialization) == start
    starting_path.unlink()

    profile_name = f"Loushang.PLC9B.{request.request_id[:32]}"
    preexisting_profile_sid = windows_runtime._create_new_profile(profile_name)
    try:
        with pytest.raises(PackageOfflineRestoreError):
            activation.activate(request, materialization)
        with pytest.raises(OSError, match="already owned"):
            windows_runtime._create_new_profile(profile_name)
        assert not (activation_root / "active-runtime.json").exists()
    finally:
        windows_runtime._free_sid(preexisting_profile_sid)
        windows_runtime._delete_profile(profile_name)

    preexisting_job = windows_runtime._create_or_open_job(
        f"Local\\Loushang.PLC9B.{request.request_id[:32]}"
    )
    try:
        with pytest.raises(PackageOfflineRestoreError):
            activation.activate(request, materialization)
        assert not (activation_root / "active-runtime.json").exists()
    finally:
        windows_runtime._close_handle(preexisting_job)

    receipt = activation.activate(request, materialization)
    replay = activation.activate(request, materialization)

    assert replay == receipt
    assert starting_path.read_bytes() == canonical_json_bytes(start.to_dict())
    with pytest.raises(PackageOfflineRestoreError):
        activation.review_incomplete_start(request, materialization)
    assert receipt.exclusive_old_runtime
    assert (activation_root / "active-runtime.json").is_file()
    runtime_root = activation_root / f"runtime-{request.request_id}"
    assert (runtime_root / "ready.txt").is_file()

    changed_profile = PackageWindowsLegacyRuntimeActivationOwner(
        restore_root,
        activation_root,
        current_b_authority_root=current_b_root,
        store_id=STORE_ID,
        legacy_runtime_version=request.legacy_runtime_version,
        command=(*command, "changed-profile"),
    )
    with pytest.raises(PackageOfflineRestoreError):
        changed_profile.deactivate_required(receipt)
    assert (activation_root / "active-runtime.json").is_file()

    reopened = PackageWindowsLegacyRuntimeActivationOwner(
        restore_root,
        activation_root,
        current_b_authority_root=current_b_root,
        store_id=STORE_ID,
        legacy_runtime_version=request.legacy_runtime_version,
        command=command,
    )
    assert reopened.activate(request, materialization) == receipt
    assert reopened._jobs == {}
    reopened.deactivate_required(receipt)
    assert not (activation_root / "active-runtime.json").exists()
    assert not runtime_root.exists()
    assert (activation_root / "settling-runtime.json").is_file()
    assert reopened.read_settlement(receipt) == reopened.settle_required(receipt)
    with pytest.raises(PackageOfflineRestoreError) as missing:
        reopened.deactivate_required(receipt)
    assert missing.value.code == "package_offline_restore_cleanup_failed"
    activation.deactivate(receipt)


def test_windows_legacy_runtime_settlement_retries_and_reopens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
            "for /L %i in (1,1,2147483647) do ver >nul 2>&1"
        ),
    )

    def opener(
        command_to_run: tuple[str, ...],
    ) -> PackageWindowsLegacyRuntimeActivationOwner:
        return PackageWindowsLegacyRuntimeActivationOwner(
            restore_root,
            activation_root,
            current_b_authority_root=current_b_root,
            store_id=STORE_ID,
            legacy_runtime_version=request.legacy_runtime_version,
            command=command_to_run,
        )

    first = opener(command)
    activation = first.activate(request, materialization)
    starting_path = activation_root / "starting-runtime.json"
    original_start = starting_path.read_bytes()
    starting_path.write_bytes(b"{}")
    with pytest.raises(PackageOfflineRestoreError):
        first.settle_required(activation)
    assert (activation_root / "active-runtime.json").is_file()
    starting_path.write_bytes(original_start)
    original_write = windows_runtime._write_new_file

    def interrupt_receipt(directory_fd: int, name: str, contents: bytes) -> None:
        if name == "settled-runtime.json":
            raise OSError("simulated receipt publication interruption")
        original_write(directory_fd, name, contents)

    monkeypatch.setattr(windows_runtime, "_write_new_file", interrupt_receipt)
    with pytest.raises(PackageOfflineRestoreError) as interrupted:
        first.settle_required(activation)
    assert interrupted.value.code == "package_offline_restore_cleanup_failed"
    assert (activation_root / "settling-runtime.json").is_file()
    assert not (activation_root / "settled-runtime.json").exists()
    monkeypatch.setattr(windows_runtime, "_write_new_file", original_write)

    changed_profile = opener((*command, "changed-profile"))
    with pytest.raises(PackageOfflineRestoreError):
        changed_profile.settle_required(activation)

    reopened = opener(command)
    settled = reopened.settle_required(activation)
    assert reopened.read_settlement(activation) == settled
    assert reopened.settle_required(activation) == settled
    assert not (activation_root / "active-runtime.json").exists()
    assert not (activation_root / f"runtime-{request.request_id}").exists()
    with pytest.raises(PackageOfflineRestoreError):
        reopened.activate(request, materialization)

    settled_path = activation_root / "settled-runtime.json"
    original_settled_bytes = settled_path.read_bytes()
    settled_path.write_bytes(b"{}")
    with pytest.raises(PackageOfflineRestoreError):
        opener(command).read_settlement(activation)
    settled_path.write_bytes(original_settled_bytes)
    lock_path = activation_root / ".legacy-runtime.lock"
    lock_path.unlink()
    with pytest.raises(PackageOfflineRestoreError):
        opener(command).read_settlement(activation)
    assert not lock_path.exists()


def test_windows_missing_readiness_settles_job_before_profile_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, request, evidence, quiescence, _, restore_root, current_b_root = _fixture(
        tmp_path
    )
    materialization = owner.restore(request, evidence, quiescence)
    activation_root = tmp_path / "activation-authority"
    activation_root.mkdir()
    activation = PackageWindowsLegacyRuntimeActivationOwner(
        restore_root,
        activation_root,
        current_b_authority_root=current_b_root,
        store_id=STORE_ID,
        legacy_runtime_version=request.legacy_runtime_version,
        command=(
            os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"),
            "/d",
            "/q",
            "/c",
            "for /L %i in (1,1,2147483647) do ver >nul 2>&1",
        ),
    )
    awaited = False

    def interrupt_ready(
        _path: Path, _token: str, _process: int, _timeout: float
    ) -> None:
        nonlocal awaited
        awaited = True
        raise TimeoutError("simulated missing readiness")

    monkeypatch.setattr(windows_runtime, "_await_ready", interrupt_ready)
    with pytest.raises(PackageOfflineRestoreError) as failed:
        activation.activate(request, materialization)
    assert awaited
    assert failed.value.code == "package_offline_restore_activation_invalid"
    assert not (activation_root / "active-runtime.json").exists()
    assert not (activation_root / "starting-runtime.json").exists()
    assert not (activation_root / f"runtime-{request.request_id}").exists()

    profile_name = f"Loushang.PLC9B.{request.request_id[:32]}"
    profile_sid = windows_runtime._create_new_profile(profile_name)
    try:
        job = windows_runtime._create_or_open_job(
            f"Local\\Loushang.PLC9B.{request.request_id[:32]}"
        )
        try:
            assert windows_runtime._job_active_processes(job) == 0
        finally:
            windows_runtime._close_handle(job)
    finally:
        windows_runtime._free_sid(profile_sid)
        windows_runtime._delete_profile(profile_name)


def test_windows_atomic_job_membership_failure_waits_and_clears_start_debt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, request, evidence, quiescence, _, restore_root, current_b_root = _fixture(
        tmp_path
    )
    materialization = owner.restore(request, evidence, quiescence)
    activation_root = tmp_path / "activation-authority"
    activation_root.mkdir()
    activation = PackageWindowsLegacyRuntimeActivationOwner(
        restore_root,
        activation_root,
        current_b_authority_root=current_b_root,
        store_id=STORE_ID,
        legacy_runtime_version=request.legacy_runtime_version,
        command=(
            os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"),
            "/d",
            "/q",
            "/c",
            "ver",
        ),
    )
    kernel = windows_runtime._kernel32()
    membership_checked = False
    resumed = False

    class _KernelProxy:
        def __getattr__(self, name: str) -> object:
            if name == "IsProcessInJob":
                return self.reject_membership
            if name == "ResumeThread":
                return self.record_resume
            return getattr(kernel, name)

        def reject_membership(
            self, _process: object, _job: object, _result: object
        ) -> bool:
            nonlocal membership_checked
            membership_checked = True
            ctypes.set_last_error(5)
            return False

        def record_resume(self, thread: object) -> int:
            nonlocal resumed
            resumed = True
            return int(kernel.ResumeThread(thread))

    monkeypatch.setattr(windows_runtime, "_kernel32", lambda: _KernelProxy())
    with pytest.raises(PackageOfflineRestoreError) as failed:
        activation.activate(request, materialization)
    assert membership_checked
    assert not resumed
    assert failed.value.code == "package_offline_restore_activation_invalid"
    assert not (activation_root / "starting-runtime.json").exists()
    assert not (activation_root / "active-runtime.json").exists()
    assert not (activation_root / f"runtime-{request.request_id}").exists()
    profile_name = f"Loushang.PLC9B.{request.request_id[:32]}"
    sid = windows_runtime._create_new_profile(profile_name)
    try:
        assert sid > 0
    finally:
        windows_runtime._free_sid(sid)
        windows_runtime._delete_profile(profile_name)


def test_windows_job_creation_attribute_failure_never_launches_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, request, evidence, quiescence, _, restore_root, current_b_root = _fixture(
        tmp_path
    )
    materialization = owner.restore(request, evidence, quiescence)
    activation_root = tmp_path / "activation-authority"
    activation_root.mkdir()
    activation = PackageWindowsLegacyRuntimeActivationOwner(
        restore_root,
        activation_root,
        current_b_authority_root=current_b_root,
        store_id=STORE_ID,
        legacy_runtime_version=request.legacy_runtime_version,
        command=(os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"),),
    )
    kernel = windows_runtime._kernel32()
    job_attribute_attempted = False
    process_created = False

    class _KernelProxy:
        def __getattr__(self, name: str) -> object:
            if name == "UpdateProcThreadAttribute":
                return self.reject_job_attribute
            if name == "CreateProcessW":
                return self.record_creation
            return getattr(kernel, name)

        def reject_job_attribute(self, *args: object) -> bool:
            nonlocal job_attribute_attempted
            if args[2] == windows_runtime._PROC_THREAD_ATTRIBUTE_JOB_LIST:
                job_attribute_attempted = True
                ctypes.set_last_error(87)
                return False
            return bool(kernel.UpdateProcThreadAttribute(*args))

        def record_creation(self, *args: object) -> bool:
            nonlocal process_created
            process_created = True
            return bool(kernel.CreateProcessW(*args))

    monkeypatch.setattr(windows_runtime, "_kernel32", lambda: _KernelProxy())
    with pytest.raises(PackageOfflineRestoreError) as failed:
        activation.activate(request, materialization)
    assert job_attribute_attempted
    assert not process_created
    assert failed.value.code == "package_offline_restore_activation_invalid"
    assert not (activation_root / "starting-runtime.json").exists()
    assert not (activation_root / "active-runtime.json").exists()
    assert not (activation_root / f"runtime-{request.request_id}").exists()
    profile_name = f"Loushang.PLC9B.{request.request_id[:32]}"
    sid = windows_runtime._create_new_profile(profile_name)
    try:
        assert sid > 0
    finally:
        windows_runtime._free_sid(sid)
        windows_runtime._delete_profile(profile_name)


def test_windows_partial_acl_grant_is_revoked_before_start_debt_clears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, request, evidence, quiescence, _, restore_root, current_b_root = _fixture(
        tmp_path
    )
    materialization = owner.restore(request, evidence, quiescence)
    activation_root = tmp_path / "activation-authority"
    activation_root.mkdir()
    activation = PackageWindowsLegacyRuntimeActivationOwner(
        restore_root,
        activation_root,
        current_b_authority_root=current_b_root,
        store_id=STORE_ID,
        legacy_runtime_version=request.legacy_runtime_version,
        command=(os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"),),
    )
    native_mutate = windows_runtime._mutate_path_acl
    native_revoke = windows_runtime._revoke_path
    granted: list[tuple[Path, bool]] = []
    revoked: list[tuple[Path, bool]] = []

    def fail_after_second_grant(
        path: Path,
        sid: int,
        *,
        access_mode: int,
        permissions: int,
        recursive: bool,
    ) -> None:
        native_mutate(
            path,
            sid,
            access_mode=access_mode,
            permissions=permissions,
            recursive=recursive,
        )
        if access_mode == windows_runtime._GRANT_ACCESS:
            granted.append((path, recursive))
            if len(granted) == 2:
                raise OSError("injected failure after ACL publication")

    def record_revoke(path: Path, sid: str, *, recursive: bool) -> None:
        revoked.append((path, recursive))
        native_revoke(path, sid, recursive=recursive)

    monkeypatch.setattr(windows_runtime, "_mutate_path_acl", fail_after_second_grant)
    monkeypatch.setattr(windows_runtime, "_revoke_path", record_revoke)
    with pytest.raises(PackageOfflineRestoreError) as failed:
        activation.activate(request, materialization)
    assert failed.value.code == "package_offline_restore_activation_invalid"
    assert len(granted) == 2
    assert revoked == list(reversed(granted))
    assert not (activation_root / "starting-runtime.json").exists()
    assert not (activation_root / "active-runtime.json").exists()
    assert not (activation_root / f"runtime-{request.request_id}").exists()
    profile_name = f"Loushang.PLC9B.{request.request_id[:32]}"
    sid = windows_runtime._create_new_profile(profile_name)
    try:
        assert sid > 0
    finally:
        windows_runtime._free_sid(sid)
        windows_runtime._delete_profile(profile_name)


def test_windows_legacy_runtime_settles_after_original_host_exits(
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
            "for /L %i in (1,1,2147483647) do ver >nul 2>&1"
        ),
    )
    child = r"""
import json
import os
import sys
from loushang.harness.resources.packages.plugin_lifecycle.offline_restore import (
    PackageOfflineRestoreMaterializationReceiptV1,
    PackageOfflineRestoreRequestV1,
)
from loushang.harness.sandbox.package_windows_legacy_runtime import (
    PackageWindowsLegacyRuntimeActivationOwner,
)
data = json.loads(sys.stdin.read())
owner = PackageWindowsLegacyRuntimeActivationOwner(
    data["restoreRoot"], data["activationRoot"],
    current_b_authority_root=data["currentBRoot"],
    store_id=data["storeId"], legacy_runtime_version=data["legacyRuntimeVersion"],
    command=data["command"],
)
receipt = owner.activate(
    PackageOfflineRestoreRequestV1.from_dict(data["request"]),
    PackageOfflineRestoreMaterializationReceiptV1.from_dict(data["materialization"]),
)
print(json.dumps(receipt.to_dict()), flush=True)
os._exit(0)
"""
    launched = subprocess.run(
        [sys.executable, "-c", child],
        input=json.dumps(
            {
                "restoreRoot": str(restore_root),
                "activationRoot": str(activation_root),
                "currentBRoot": str(current_b_root),
                "storeId": STORE_ID,
                "legacyRuntimeVersion": request.legacy_runtime_version,
                "command": command,
                "request": request.to_dict(),
                "materialization": materialization.to_dict(),
            }
        ),
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    activation = PackageLegacyRuntimeActivationReceiptV1.from_dict(
        json.loads(launched.stdout)
    )
    reopened = PackageWindowsLegacyRuntimeActivationOwner(
        restore_root,
        activation_root,
        current_b_authority_root=current_b_root,
        store_id=STORE_ID,
        legacy_runtime_version=request.legacy_runtime_version,
        command=command,
    )
    deadline = time.monotonic() + 5
    while True:
        try:
            settled = reopened.settle_required(activation)
            break
        except PackageOfflineRestoreError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)
    assert reopened.read_settlement(activation) == settled
    assert not (activation_root / "active-runtime.json").exists()
