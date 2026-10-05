from __future__ import annotations

import os
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
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_snapshot import (
    PackageWindowsEpochSnapshotEvidenceStore,
    PackageWindowsEpochSnapshotOwner,
    PackageWindowsSnapshotSharedMemberV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_offline_restore import (
    PackageWindowsOfflineRestoreMaterializer,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    prepare_windows_product_control_root,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-native contract")

STORE_ID = "package-store:windows-pre-b-snapshot"


def _identity(root: Path) -> str:
    metadata = root.stat()
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


def _owner(
    tmp_path: Path,
) -> tuple[PackageWindowsEpochSnapshotOwner, Path, dict[str, Path]]:
    snapshot_root = tmp_path / "snapshots"
    prepare_windows_product_control_root(snapshot_root)
    store = tmp_path / "legacy"
    prepare_windows_product_control_root(store)
    (store / "plugin.whl").write_bytes(b"wheel bytes")
    (store / "package-lock.json").write_bytes(b'{"version":1}')
    roots = {domain: tmp_path / domain for domain in PACKAGE_PRE_B_SNAPSHOT_DOMAINS}
    for domain, root in roots.items():
        if domain not in {"store_bytes", "binding_history", "lock_history"}:
            prepare_windows_product_control_root(root)
    for domain in ("store_bytes", "binding_history", "lock_history"):
        roots[domain] = store
    (roots["desired_state"] / "desired.json").write_bytes(b'{"enabled":true}')
    (roots["source_configuration"] / "settings.json").write_bytes(b"{}")
    members: dict[str, tuple[str, ...] | None] = dict.fromkeys(
        PACKAGE_PRE_B_SNAPSHOT_DOMAINS
    )
    members["store_bytes"] = ("plugin.whl",)
    members["binding_history"] = ("package-lock.json",)
    members["lock_history"] = ("package-lock.json",)
    owner = PackageWindowsEpochSnapshotOwner(
        snapshot_root,
        store_id=STORE_ID,
        domain_roots=roots,
        domain_members=members,
        shared_members=(
            PackageWindowsSnapshotSharedMemberV1(
                source_root=store,
                member_name="package-lock.json",
                domains=("binding_history", "lock_history"),
            ),
        ),
        legacy_root_pointer_name="legacy",
    )
    return owner, snapshot_root, roots


def test_windows_publishes_complete_authenticated_snapshot_and_replays(
    tmp_path: Path,
) -> None:
    owner, snapshot_root, roots = _owner(tmp_path)
    arguments = {
        "store_id": STORE_ID,
        "legacy_root_identity": _identity(roots["store_bytes"]),
        "quiescence_receipt_id": sha256(b"quiescent").hexdigest(),
    }

    receipt = owner.capture(**arguments)
    assert owner.capture(**arguments) == receipt
    reader = PackageWindowsEpochSnapshotEvidenceStore(snapshot_root, store_id=STORE_ID)
    evidence = reader.snapshot(receipt.receipt_id)
    assert evidence is not None
    assert evidence.snapshot == receipt
    assert (
        reader.read_regular_member(
            receipt.receipt_id, domain="store_bytes", member_name="plugin.whl"
        )
        == b"wheel bytes"
    )
    assert reader.list_domain_members(receipt.receipt_id, domain="binding_history") == (
        "package-lock.json",
    )
    assert reader.list_domain_members(
        receipt.receipt_id, domain="legacy_root_pointer"
    ) == ("legacy-root-pointer.json",)
    assert not list(snapshot_root.glob("staging-*"))


def test_windows_snapshot_refuses_missing_member_before_publication(
    tmp_path: Path,
) -> None:
    owner, snapshot_root, roots = _owner(tmp_path)
    (roots["store_bytes"] / "plugin.whl").unlink()

    with pytest.raises(ValueError, match="source member coverage is incomplete"):
        owner.capture(
            store_id=STORE_ID,
            legacy_root_identity=_identity(roots["store_bytes"]),
            quiescence_receipt_id=sha256(b"quiescent").hexdigest(),
        )

    assert not list(snapshot_root.glob("staging-*"))
    assert not list(snapshot_root.glob("*.evidence.json"))


def test_windows_snapshot_excludes_live_fence_coordination_lock(tmp_path: Path) -> None:
    owner, snapshot_root, roots = _owner(tmp_path)
    coordination = roots["fence_record"] / "coordination.lock"
    coordination.write_bytes(b"live lock")

    receipt = owner.capture(
        store_id=STORE_ID,
        legacy_root_identity=_identity(roots["store_bytes"]),
        quiescence_receipt_id=sha256(b"quiescent").hexdigest(),
    )

    reader = PackageWindowsEpochSnapshotEvidenceStore(snapshot_root, store_id=STORE_ID)
    assert reader.list_domain_members(receipt.receipt_id, domain="fence_record") == ()
    assert coordination.read_bytes() == b"live lock"


def test_windows_snapshot_reader_refuses_payload_tamper(tmp_path: Path) -> None:
    owner, snapshot_root, roots = _owner(tmp_path)
    receipt = owner.capture(
        store_id=STORE_ID,
        legacy_root_identity=_identity(roots["store_bytes"]),
        quiescence_receipt_id=sha256(b"quiescent").hexdigest(),
    )
    (
        snapshot_root / receipt.snapshot_id / "payload" / "store_bytes" / "plugin.whl"
    ).write_bytes(b"changed")

    reader = PackageWindowsEpochSnapshotEvidenceStore(snapshot_root, store_id=STORE_ID)
    with pytest.raises(PackageOfflineRestoreError) as captured:
        reader.snapshot(receipt.receipt_id)
    assert captured.value.code == "package_offline_restore_snapshot_invalid"


def test_windows_published_snapshot_restores_through_native_product_port(
    tmp_path: Path,
) -> None:
    owner, snapshot_root, roots = _owner(tmp_path)
    quiescence = PackageEpochCutoverQuiescenceReceiptV1.create(
        store_id=STORE_ID,
        owner_revision=1,
        active_runtime_lease_ids=(),
        active_pre_fence_registration_ids=(),
    )
    receipt = owner.capture(
        store_id=STORE_ID,
        legacy_root_identity=_identity(roots["store_bytes"]),
        quiescence_receipt_id=quiescence.receipt_id,
    )
    evidence = owner.snapshot(receipt.receipt_id)
    assert evidence is not None
    current_b = tmp_path / "current-b"
    restore_root = tmp_path / "restore"
    current_b.mkdir()
    restore_root.mkdir()
    fences = PackageEpochFenceJournal(tmp_path / "epoch.jsonl")
    fence = fences.publish(
        PackageEpochFenceRequestV1.create(
            store_id=STORE_ID,
            prior_fence=None,
            legacy_root_identity=receipt.legacy_root_identity,
            fenced_root_identity=_identity(current_b),
            namespace_id=sha256(b"current-b").hexdigest(),
            minimum_runtime_version="2.0.0",
            minimum_runtime_protocol_epoch=2,
            quiescence_receipt_id=quiescence.receipt_id,
            snapshot_receipt_id=receipt.receipt_id,
            root_switch_receipt_id=sha256(b"root-switch").hexdigest(),
        )
    )
    request = PackageOfflineRestoreRequestV1.create(
        current_fence=fence,
        genesis_fence=fence,
        snapshot_evidence=evidence,
        restore_namespace_id=sha256(b"restore").hexdigest(),
        legacy_runtime_version="1.9.0",
    )
    materializer = PackageWindowsOfflineRestoreMaterializer(
        snapshot_root,
        restore_root,
        current_b_authority_root=current_b,
        store_id=STORE_ID,
    )

    restored = materializer.restore(request, evidence, quiescence)

    assert restored.legacy_snapshot_exact
    assert (
        restore_root
        / request.restore_namespace_id
        / "payload"
        / "store_bytes"
        / "plugin.whl"
    ).read_bytes() == b"wheel bytes"
