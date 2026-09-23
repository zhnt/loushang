from __future__ import annotations

import errno
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
    PackageEpochFenceRequestV1,
    PackageEpochRuntimeAdmissionOwner,
    PackageEpochRuntimeAdmissionRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
    PackageEpochRuntimeLeaseRegistry,
    PackageEpochRuntimeLeaseRegistryError,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductFileEpochTransactionGuard,
)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux rooted lease journal")


@pytest.fixture
def registry(tmp_path: Path) -> Iterator[PackageEpochRuntimeLeaseRegistry]:
    fences = PackageEpochFenceJournal(tmp_path / "epoch-fence.jsonl")
    fences.publish(
        PackageEpochFenceRequestV1.create(
            store_id="package-store:test",
            prior_fence=None,
            legacy_root_identity="1" * 64,
            fenced_root_identity="2" * 64,
            namespace_id="3" * 64,
            minimum_runtime_version="2.0.0",
            minimum_runtime_protocol_epoch=2,
            quiescence_receipt_id="4" * 64,
            snapshot_receipt_id="5" * 64,
            root_switch_receipt_id="6" * 64,
        )
    )
    root_fd = os.open(
        tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    file_io = RootedFileIO(tmp_path, root_fd)
    try:
        yield PackageEpochRuntimeLeaseRegistry(
            path=tmp_path / "runtime-leases.jsonl",
            coordination_lock=tmp_path / "epoch-coordination",
            file_io=file_io,
            fences=fences,
            store_id="package-store:test",
        )
    finally:
        file_io.cleanup()
        os.close(root_fd)


def test_registered_runtime_is_admitted_from_complete_durable_snapshot(
    registry: PackageEpochRuntimeLeaseRegistry,
) -> None:
    handle = registry.register(runtime_id="runtime:first", runtime_protocol_epoch=2)
    try:
        snapshot = registry.snapshot(store_id="package-store:test")
        assert snapshot.active_leases == (handle.lease,)
        fence = registry.fences.current("package-store:test")
        assert fence is not None
        request = PackageEpochRuntimeAdmissionRequestV1.create(
            fence=fence,
            runtime_id=handle.lease.runtime_id,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
            runtime_epoch=handle.lease.runtime_epoch,
            store_root_identity=handle.lease.store_root_identity,
            lease_id=handle.lease.lease_id,
        )
        result = PackageEpochRuntimeAdmissionOwner(
            fences=registry.fences, leases=registry
        ).admit(request)
        assert result.disposition == "admitted"
    finally:
        handle.release()
    with pytest.raises(PackageEpochRuntimeLeaseRegistryError, match="active"):
        registry.snapshot(store_id="package-store:test")


def test_registry_reports_all_live_leases_and_refuses_old_protocol(
    registry: PackageEpochRuntimeLeaseRegistry,
) -> None:
    with pytest.raises(PackageEpochRuntimeLeaseRegistryError, match="protocol"):
        registry.register(runtime_id="runtime:old", runtime_protocol_epoch=1)
    first = registry.register(runtime_id="runtime:first", runtime_protocol_epoch=2)
    with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as duplicate:
        registry.register(runtime_id="runtime:first", runtime_protocol_epoch=2)
    assert duplicate.value.code == "package_epoch_lease_identity_conflict"
    second = registry.register(runtime_id="runtime:second", runtime_protocol_epoch=2)
    try:
        snapshot = registry.snapshot(store_id="package-store:test")
        assert {item.lease_id for item in snapshot.active_leases} == {
            first.lease.lease_id,
            second.lease.lease_id,
        }
        with pytest.raises(PackageEpochRuntimeLeaseRegistryError, match="live"):
            registry.repair_orphan(first.lease.lease_id)
    finally:
        first.release()
        second.release()


def test_rooted_product_guard_pairs_with_lease_registration_and_cutover(
    registry: PackageEpochRuntimeLeaseRegistry,
) -> None:
    handle = registry.register(runtime_id="runtime:first", runtime_protocol_epoch=2)
    guard = PackageProductFileEpochTransactionGuard(
        store_id=registry.store_id,
        coordination_lock=registry.coordination_lock,
        file_io=registry._io,
    )
    try:
        with guard.shared_runtime(store_id=registry.store_id):
            assert registry.snapshot(store_id=registry.store_id).active_leases == (
                handle.lease,
            )
            with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as busy:
                registry.register(runtime_id="runtime:second", runtime_protocol_epoch=2)
            assert busy.value.code == "package_epoch_lease_busy"
            with pytest.raises(BlockingIOError):
                with registry._io.bind(registry.coordination_lock) as cutover:
                    cutover.acquire_lock(exclusive=True, suffix=".lock")
    finally:
        handle.release()


def test_registry_refuses_stale_fence_and_changed_store(
    registry: PackageEpochRuntimeLeaseRegistry,
) -> None:
    with pytest.raises(PackageEpochRuntimeLeaseRegistryError, match="store"):
        registry.snapshot(store_id="package-store:other")
    registry.fences.publish(
        PackageEpochFenceRequestV1.create(
            store_id="package-store:test",
            prior_fence=registry.fences.current("package-store:test"),
            legacy_root_identity="2" * 64,
            fenced_root_identity="7" * 64,
            namespace_id="8" * 64,
            minimum_runtime_version="3.0.0",
            minimum_runtime_protocol_epoch=3,
            quiescence_receipt_id="9" * 64,
            snapshot_receipt_id="a" * 64,
            root_switch_receipt_id="b" * 64,
        )
    )
    with pytest.raises(PackageEpochRuntimeLeaseRegistryError, match="protocol"):
        registry.register(runtime_id="runtime:stale", runtime_protocol_epoch=2)


def test_crashed_runtime_requires_proven_orphan_repair(
    registry: PackageEpochRuntimeLeaseRegistry, tmp_path: Path
) -> None:
    script = """
import os
import sys
from pathlib import Path
from loushang.harness.journal._rooted_io import RootedFileIO
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import PackageEpochFenceJournal
from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import PackageEpochRuntimeLeaseRegistry

root = Path(sys.argv[1])
fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
owner = PackageEpochRuntimeLeaseRegistry(
    path=root / "runtime-leases.jsonl",
    coordination_lock=root / "epoch-coordination",
    file_io=RootedFileIO(root, fd),
    fences=PackageEpochFenceJournal(root / "epoch-fence.jsonl"),
    store_id="package-store:test",
)
handle = owner.register(runtime_id="runtime:crashed", runtime_protocol_epoch=2)
sys.stdout.write(handle.lease.lease_id)
sys.stdout.flush()
os._exit(0)
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    lease_id = child.stdout
    assert len(lease_id) == 64

    with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as raised:
        registry.snapshot(store_id="package-store:test")
    assert raised.value.code == "package_epoch_lease_orphaned"
    registry.repair_orphan(lease_id)
    with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as absent:
        registry.snapshot(store_id="package-store:test")
    assert absent.value.code == "package_epoch_lease_absent"


def test_permission_failure_is_unknown_liveness_not_proof_of_live_lease(
    registry: PackageEpochRuntimeLeaseRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = registry.register(runtime_id="runtime:first", runtime_protocol_epoch=2)
    original_stat = RootedFile.stat

    def denied_lease_stat(rooted: RootedFile) -> os.stat_result:
        if rooted._name.endswith(".lease"):
            raise PermissionError(errno.EACCES, "denied")
        return original_stat(rooted)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(RootedFile, "stat", denied_lease_stat)
            with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as snapshot:
                registry.snapshot(store_id=registry.store_id)
            assert snapshot.value.code == "package_epoch_lease_liveness_unknown"
            with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as repair:
                registry.repair_orphan(handle.lease.lease_id)
            assert repair.value.code == "package_epoch_lease_liveness_unknown"
    finally:
        handle.release()


def test_lease_journal_link_swap_fails_without_following_target(
    registry: PackageEpochRuntimeLeaseRegistry, tmp_path: Path
) -> None:
    handle = registry.register(runtime_id="runtime:first", runtime_protocol_epoch=2)
    handle.release()
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(registry.path.read_bytes())
    before = outside.read_bytes()
    registry.path.unlink()
    registry.path.symlink_to(outside)

    with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as raised:
        registry.register(runtime_id="runtime:second", runtime_protocol_epoch=2)
    assert raised.value.code == "package_epoch_lease_journal_corrupt"
    assert outside.read_bytes() == before
