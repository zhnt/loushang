from __future__ import annotations

import shutil
import sys
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
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverQuiescenceReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_snapshot import (
    PackagePosixEpochSnapshotEvidenceStore,
    PackagePosixEpochSnapshotOwner,
    PackagePosixSnapshotSharedMemberV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_offline_restore import (
    PackagePosixOfflineRestoreMaterializer,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux rooted snapshot publication"
)

_STORE_ID = "package-store:snapshot-test"
_QUIESCENCE_ID = "a" * 64


def _directory_identity(path: Path) -> str:
    metadata = path.stat()
    return sha256(
        canonical_json_bytes(
            {
                "device": metadata.st_dev,
                "fileType": "directory",
                "identityVersion": 1,
                "inode": metadata.st_ino,
            }
        )
    ).hexdigest()


def _snapshot_fixture(
    tmp_path: Path,
) -> tuple[PackagePosixEpochSnapshotOwner, Path, Path, dict[str, Path]]:
    snapshot_root = tmp_path / "snapshots"
    source_root = tmp_path / "sources"
    for directory in (snapshot_root, source_root):
        directory.mkdir(mode=0o700)
    domains = {}
    for domain in PACKAGE_PRE_B_SNAPSHOT_DOMAINS:
        path = source_root / domain
        path.mkdir(mode=0o700)
        domains[domain] = path
    (domains["store_bytes"] / "state.json").write_bytes(b'{"legacy":1}\n')
    (domains["source_configuration"] / "sources.json").write_bytes(b"{}\n")
    owner = PackagePosixEpochSnapshotOwner(
        snapshot_root, store_id=_STORE_ID, domain_roots=domains
    )
    return owner, snapshot_root, domains["store_bytes"], domains


@pytest.mark.parametrize("overlap", ("same", "nested"))
def test_snapshot_refuses_overlapping_pre_b_domain_roots(
    tmp_path: Path, overlap: str
) -> None:
    snapshot_root = tmp_path / "snapshots"
    source_root = tmp_path / "sources"
    snapshot_root.mkdir(mode=0o700)
    source_root.mkdir(mode=0o700)
    domains = {}
    for domain in PACKAGE_PRE_B_SNAPSHOT_DOMAINS:
        path = source_root / domain
        path.mkdir(mode=0o700)
        domains[domain] = path
    shared = domains["binding_history"]
    if overlap == "nested":
        shared = shared / "lock-history"
        shared.mkdir(mode=0o700)
    domains["lock_history"] = shared

    with pytest.raises(ValueError, match="overlap"):
        PackagePosixEpochSnapshotOwner(
            snapshot_root, store_id=_STORE_ID, domain_roots=domains
        )


@pytest.mark.parametrize(
    "coverage", ("complete", "missing", "duplicate", "added_after_owner")
)
def test_snapshot_partitions_colocated_domain_members_exactly(
    tmp_path: Path, coverage: str
) -> None:
    snapshot_root = tmp_path / "snapshots"
    source_root = tmp_path / "sources"
    snapshot_root.mkdir(mode=0o700)
    source_root.mkdir(mode=0o700)
    domains = {}
    for domain in PACKAGE_PRE_B_SNAPSHOT_DOMAINS:
        path = source_root / domain
        path.mkdir(mode=0o700)
        domains[domain] = path
    shared = domains["desired_state"]
    (shared / "desired.jsonl").write_bytes(b"desired\n")
    (shared / "instance.jsonl").write_bytes(b"instance\n")
    domains["instance_state"] = shared
    members: dict[str, tuple[str, ...] | None] = {
        domain: None for domain in PACKAGE_PRE_B_SNAPSHOT_DOMAINS
    }
    members["desired_state"] = ("desired.jsonl",)
    members["instance_state"] = {
        "complete": ("instance.jsonl",),
        "missing": (),
        "duplicate": ("desired.jsonl",),
        "added_after_owner": ("instance.jsonl",),
    }[coverage]
    owner = PackagePosixEpochSnapshotOwner(
        snapshot_root,
        store_id=_STORE_ID,
        domain_roots=domains,
        domain_members=members,
    )
    if coverage == "added_after_owner":
        (shared / "unexpected.jsonl").write_bytes(b"late\n")
    if coverage != "complete":
        with pytest.raises(ValueError, match="coverage"):
            owner.capture(
                store_id=_STORE_ID,
                legacy_root_identity=_directory_identity(domains["store_bytes"]),
                quiescence_receipt_id=_QUIESCENCE_ID,
            )
        assert not list(snapshot_root.glob("*.evidence.json"))
        return
    receipt = owner.capture(
        store_id=_STORE_ID,
        legacy_root_identity=_directory_identity(domains["store_bytes"]),
        quiescence_receipt_id=_QUIESCENCE_ID,
    )
    assert owner.snapshot(receipt.receipt_id) is not None
    payload = snapshot_root / receipt.snapshot_id / "payload"
    assert (payload / "desired_state" / "desired.jsonl").read_bytes() == b"desired\n"
    assert (payload / "instance_state" / "instance.jsonl").read_bytes() == b"instance\n"
    assert not (payload / "desired_state" / "instance.jsonl").exists()
    shutil.rmtree(source_root)
    assert (
        PackagePosixEpochSnapshotEvidenceStore(
            snapshot_root, store_id=_STORE_ID
        ).snapshot(receipt.receipt_id)
        is not None
    )


def test_snapshot_copies_only_explicit_shared_member_alias(
    tmp_path: Path,
) -> None:
    snapshot_root = tmp_path / "snapshots"
    source_root = tmp_path / "sources"
    snapshot_root.mkdir(mode=0o700)
    source_root.mkdir(mode=0o700)
    domains = {}
    for domain in PACKAGE_PRE_B_SNAPSHOT_DOMAINS:
        path = source_root / domain
        path.mkdir(mode=0o700)
        domains[domain] = path
    shared = domains["binding_history"]
    (shared / "package-lock.json").write_bytes(b'{"version":4}\n')
    domains["lock_history"] = shared
    members: dict[str, tuple[str, ...] | None] = {
        domain: None for domain in PACKAGE_PRE_B_SNAPSHOT_DOMAINS
    }
    members["binding_history"] = ("package-lock.json",)
    members["lock_history"] = ("package-lock.json",)
    alias = PackagePosixSnapshotSharedMemberV1(
        source_root=shared,
        member_name="package-lock.json",
        domains=("binding_history", "lock_history"),
    )
    owner = PackagePosixEpochSnapshotOwner(
        snapshot_root,
        store_id=_STORE_ID,
        domain_roots=domains,
        domain_members=members,
        shared_members=(alias,),
    )
    receipt = owner.capture(
        store_id=_STORE_ID,
        legacy_root_identity=_directory_identity(domains["store_bytes"]),
        quiescence_receipt_id=_QUIESCENCE_ID,
    )
    payload = snapshot_root / receipt.snapshot_id / "payload"
    for domain in alias.domains:
        assert (payload / domain / alias.member_name).read_bytes() == b'{"version":4}\n'
    shutil.rmtree(source_root)
    reopened = PackagePosixEpochSnapshotEvidenceStore(snapshot_root, store_id=_STORE_ID)
    assert reopened.snapshot(receipt.receipt_id) is not None
    for domain in alias.domains:
        assert (
            reopened.read_regular_member(
                receipt.receipt_id,
                domain=domain,
                member_name=alias.member_name,
            )
            == b'{"version":4}\n'
        )
    assert (
        reopened.read_regular_member(
            receipt.receipt_id,
            domain="binding_history",
            member_name="absent.json",
        )
        is None
    )
    (payload / "binding_history" / "package-lock.json").write_bytes(b'{"version":3}\n')
    with pytest.raises(PackageOfflineRestoreError, match="snapshot"):
        reopened.read_regular_member(
            receipt.receipt_id,
            domain="lock_history",
            member_name=alias.member_name,
        )


def test_snapshot_derives_legacy_root_pointer_from_verified_store_identity(
    tmp_path: Path,
) -> None:
    _, snapshot_root, legacy_root, domains = _snapshot_fixture(tmp_path)
    with pytest.raises(ValueError, match="root name does not match"):
        PackagePosixEpochSnapshotOwner(
            snapshot_root,
            store_id=_STORE_ID,
            domain_roots=domains,
            legacy_root_pointer_name="different-root",
        )
    owner = PackagePosixEpochSnapshotOwner(
        snapshot_root,
        store_id=_STORE_ID,
        domain_roots=domains,
        legacy_root_pointer_name=legacy_root.name,
    )
    identity = _directory_identity(legacy_root)
    receipt = owner.capture(
        store_id=_STORE_ID,
        legacy_root_identity=identity,
        quiescence_receipt_id=_QUIESCENCE_ID,
    )
    pointer = (
        snapshot_root
        / receipt.snapshot_id
        / "payload"
        / "legacy_root_pointer"
        / "legacy-root-pointer.json"
    )
    assert pointer.read_bytes() == canonical_json_bytes(
        {
            "legacyRootIdentity": identity,
            "legacyRootName": legacy_root.name,
            "recordVersion": 1,
            "storeId": _STORE_ID,
        }
    )
    (domains["legacy_root_pointer"] / "unaccounted.json").write_bytes(b"{}\n")
    with pytest.raises(ValueError, match="pointer source must be empty"):
        owner.capture(
            store_id=_STORE_ID,
            legacy_root_identity=identity,
            quiescence_receipt_id=_QUIESCENCE_ID,
        )
    shutil.rmtree(domains["legacy_root_pointer"])
    assert owner.snapshot(receipt.receipt_id) is not None


def test_snapshot_is_durable_and_reopen_validates_complete_domains(
    tmp_path: Path,
) -> None:
    owner, snapshot_root, legacy_root, _domains = _snapshot_fixture(tmp_path)
    legacy_identity = _directory_identity(legacy_root)
    receipt = owner.capture(
        store_id=_STORE_ID,
        legacy_root_identity=legacy_identity,
        quiescence_receipt_id=_QUIESCENCE_ID,
    )
    assert (
        owner.capture(
            store_id=_STORE_ID,
            legacy_root_identity=legacy_identity,
            quiescence_receipt_id=_QUIESCENCE_ID,
        )
        == receipt
    )
    shutil.rmtree(legacy_root.parent)
    snapshot_root.chmod(0o500)
    try:
        reopened = PackagePosixEpochSnapshotEvidenceStore(
            snapshot_root, store_id=_STORE_ID
        )
        evidence = reopened.snapshot(receipt.receipt_id)
    finally:
        snapshot_root.chmod(0o700)
    assert evidence is not None
    assert evidence.snapshot == receipt
    assert evidence.covered_domains == PACKAGE_PRE_B_SNAPSHOT_DOMAINS
    assert (
        snapshot_root / receipt.snapshot_id / "payload" / "store_bytes" / "state.json"
    ).read_bytes() == b'{"legacy":1}\n'


def test_snapshot_retries_after_bundle_publication_before_evidence_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from loushang.harness.resources.packages.plugin_lifecycle import (
        posix_epoch_snapshot as snapshot_module,
    )

    owner, snapshot_root, legacy_root, domains = _snapshot_fixture(tmp_path)
    original_write = snapshot_module._write_new_file
    injected = False

    def fail_index_once(directory_fd: int, name: str, contents: bytes) -> None:
        nonlocal injected
        if name.startswith(".index-staging-") and not injected:
            injected = True
            raise OSError("injected crash before evidence index")
        original_write(directory_fd, name, contents)

    monkeypatch.setattr(snapshot_module, "_write_new_file", fail_index_once)
    with pytest.raises(OSError, match="injected crash"):
        owner.capture(
            store_id=_STORE_ID,
            legacy_root_identity=_directory_identity(legacy_root),
            quiescence_receipt_id=_QUIESCENCE_ID,
        )
    assert injected
    monkeypatch.setattr(snapshot_module, "_write_new_file", original_write)
    reopened = PackagePosixEpochSnapshotOwner(
        snapshot_root, store_id=_STORE_ID, domain_roots=domains
    )
    receipt = reopened.capture(
        store_id=_STORE_ID,
        legacy_root_identity=_directory_identity(legacy_root),
        quiescence_receipt_id=_QUIESCENCE_ID,
    )
    assert reopened.snapshot(receipt.receipt_id) is not None
    assert not list(snapshot_root.glob(".staging-*"))


def test_snapshot_refuses_tampered_bundle_on_read_and_exact_retry(
    tmp_path: Path,
) -> None:
    owner, snapshot_root, legacy_root, _domains = _snapshot_fixture(tmp_path)
    receipt = owner.capture(
        store_id=_STORE_ID,
        legacy_root_identity=_directory_identity(legacy_root),
        quiescence_receipt_id=_QUIESCENCE_ID,
    )
    payload = (
        snapshot_root / receipt.snapshot_id / "payload" / "store_bytes" / "state.json"
    )
    payload.write_bytes(b'{"tampered":true}\n')
    with pytest.raises(PackageOfflineRestoreError):
        owner.snapshot(receipt.receipt_id)
    with pytest.raises(PackageOfflineRestoreError):
        owner.capture(
            store_id=_STORE_ID,
            legacy_root_identity=_directory_identity(legacy_root),
            quiescence_receipt_id=_QUIESCENCE_ID,
        )
    assert not list(snapshot_root.glob(".staging-*"))


def test_snapshot_refuses_replaced_legacy_root_before_publication(
    tmp_path: Path,
) -> None:
    owner, snapshot_root, legacy_root, _domains = _snapshot_fixture(tmp_path)
    expected_identity = _directory_identity(legacy_root)
    legacy_root.rename(legacy_root.with_name("removed-store-bytes"))
    legacy_root.mkdir(mode=0o700)
    with pytest.raises(OSError):
        owner.capture(
            store_id=_STORE_ID,
            legacy_root_identity=expected_identity,
            quiescence_receipt_id=_QUIESCENCE_ID,
        )
    assert not list(snapshot_root.glob("*.evidence.json"))
    assert not list(snapshot_root.glob(".staging-*"))


def test_published_snapshot_is_consumed_by_real_posix_offline_restore(
    tmp_path: Path,
) -> None:
    owner, snapshot_root, legacy_root, _domains = _snapshot_fixture(tmp_path)
    receipt = owner.capture(
        store_id=_STORE_ID,
        legacy_root_identity=_directory_identity(legacy_root),
        quiescence_receipt_id=_QUIESCENCE_ID,
    )
    evidence = PackagePosixEpochSnapshotEvidenceStore(
        snapshot_root, store_id=_STORE_ID
    ).snapshot(receipt.receipt_id)
    assert evidence is not None
    current_b_root = tmp_path / "current-b"
    restore_root = tmp_path / "restore"
    current_b_root.mkdir(mode=0o700)
    restore_root.mkdir(mode=0o700)
    journal = PackageEpochFenceJournal(tmp_path / "epoch.jsonl")
    fence = journal.publish(
        PackageEpochFenceRequestV1.create(
            store_id=_STORE_ID,
            prior_fence=None,
            legacy_root_identity=receipt.legacy_root_identity,
            fenced_root_identity=_directory_identity(current_b_root),
            namespace_id="b" * 64,
            minimum_runtime_version="2.0.0",
            minimum_runtime_protocol_epoch=2,
            quiescence_receipt_id=receipt.quiescence_receipt_id,
            snapshot_receipt_id=receipt.receipt_id,
            root_switch_receipt_id="c" * 64,
        )
    )
    request = PackageOfflineRestoreRequestV1.create(
        current_fence=fence,
        genesis_fence=fence,
        snapshot_evidence=evidence,
        restore_namespace_id="d" * 64,
        legacy_runtime_version="1.9.0",
    )
    quiescence = PackageEpochCutoverQuiescenceReceiptV1.create(
        store_id=_STORE_ID,
        owner_revision=1,
        active_runtime_lease_ids=(),
        active_pre_fence_registration_ids=(),
    )
    materializer = PackagePosixOfflineRestoreMaterializer(
        snapshot_root,
        restore_root,
        current_b_authority_root=current_b_root,
        store_id=_STORE_ID,
    )
    restored = materializer.restore(request, evidence, quiescence)
    assert restored.snapshot_receipt_id == receipt.receipt_id
    assert (
        restore_root
        / request.restore_namespace_id
        / "payload"
        / "store_bytes"
        / "state.json"
    ).read_bytes() == b'{"legacy":1}\n'
