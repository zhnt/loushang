from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

import loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry as windows_lease_registry
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
    PackageEpochFenceRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
    PackageEpochRuntimeLeaseRecordV1,
    PackageEpochRuntimeLeaseRegistryError,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsEpochRuntimeLeaseRegistry,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-native lease contract")
_STORE_ID = "package-store:windows"


def _fenced_control(root: Path) -> PackageEpochFenceJournal:
    root.mkdir()
    fences = PackageEpochFenceJournal(root / "epoch.jsonl")
    fences.publish(
        PackageEpochFenceRequestV1.create(
            store_id=_STORE_ID,
            prior_fence=None,
            legacy_root_identity="1" * 64,
            fenced_root_identity="2" * 64,
            namespace_id="3" * 64,
            minimum_runtime_version="1.0.0",
            minimum_runtime_protocol_epoch=1,
            quiescence_receipt_id="4" * 64,
            snapshot_receipt_id="5" * 64,
            root_switch_receipt_id="6" * 64,
        )
    )
    return fences


def test_windows_runtime_lease_registers_releases_and_fences_quiescence(
    tmp_path: Path,
) -> None:
    control = tmp_path / "control"
    fences = _fenced_control(control)
    registry = PackageWindowsEpochRuntimeLeaseRegistry(
        control_root=control, fences=fences, store_id=_STORE_ID
    )
    handle = None
    try:
        handle = registry.register(runtime_id="runtime:one", runtime_protocol_epoch=1)
        assert registry.review_orphans(store_id=_STORE_ID) == ()
        assert registry.snapshot(store_id=_STORE_ID).active_leases == (handle.lease,)
        with registry.exclusive_runtime_quiescence(store_id=_STORE_ID) as held:
            assert held.active_runtime_lease_ids == (handle.lease.lease_id,)
            with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as busy:
                registry.close()
            assert busy.value.code == "package_epoch_lease_busy"
        with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as live:
            registry.repair_orphan(handle.lease.lease_id)
        assert live.value.code == "package_epoch_lease_live"
        with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as duplicate:
            registry.register(runtime_id="runtime:one", runtime_protocol_epoch=1)
        assert duplicate.value.code == "package_epoch_lease_identity_conflict"
        handle.release()
        with registry.exclusive_runtime_quiescence(store_id=_STORE_ID) as held:
            assert held.active_runtime_lease_ids == ()
    finally:
        if handle is not None:
            handle.release()
        registry.close()
    with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as closed:
        registry.register(runtime_id="runtime:later", runtime_protocol_epoch=1)
    assert closed.value.code == "package_epoch_lease_closed"


def test_windows_runtime_lease_refuses_unfenced_registration_without_journal(
    tmp_path: Path,
) -> None:
    control = tmp_path / "control"
    control.mkdir()
    fences = PackageEpochFenceJournal(control / "epoch.jsonl")
    registry = PackageWindowsEpochRuntimeLeaseRegistry(
        control_root=control, fences=fences, store_id=_STORE_ID
    )
    try:
        with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as refused:
            registry.register(runtime_id="runtime:one", runtime_protocol_epoch=1)
        assert refused.value.code == "package_epoch_unfenced"
        assert not registry.path.exists()
    finally:
        registry.close()


def test_windows_runtime_lease_orphan_requires_explicit_repair(
    tmp_path: Path,
) -> None:
    control = tmp_path / "control"
    fences = _fenced_control(control)
    script = "\n".join(
        (
            "import os, sys",
            "from pathlib import Path",
            "from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import PackageEpochFenceJournal",
            "from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import PackageWindowsEpochRuntimeLeaseRegistry",
            "control = Path(sys.argv[1])",
            "registry = PackageWindowsEpochRuntimeLeaseRegistry(control_root=control, fences=PackageEpochFenceJournal(control / 'epoch.jsonl'), store_id=sys.argv[2])",
            "handle = registry.register(runtime_id='runtime:crashed', runtime_protocol_epoch=1)",
            "os._exit(0)",
        )
    )
    child = subprocess.run(
        (sys.executable, "-c", script, str(control), _STORE_ID),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert child.returncode == 0, child.stderr
    registry = PackageWindowsEpochRuntimeLeaseRegistry(
        control_root=control, fences=fences, store_id=_STORE_ID
    )
    try:
        with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as orphan:
            registry.snapshot(store_id=_STORE_ID)
        assert orphan.value.code == "package_epoch_lease_orphaned"
        with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as quiescence:
            with registry.exclusive_runtime_quiescence(store_id=_STORE_ID):
                pass
        assert quiescence.value.code == "package_epoch_lease_orphaned"
        [registration] = registry.path.read_text(encoding="utf-8").splitlines()
        lease_id = PackageEpochRuntimeLeaseRecordV1.from_dict(
            json.loads(registration)
        ).lease.lease_id
        before_review = registry.path.read_bytes()
        (orphaned,) = registry.review_orphans(store_id=_STORE_ID)
        assert orphaned.lease_id == lease_id
        assert registry.path.read_bytes() == before_review
        with registry.guard_orphan_recovery(
            store_id=_STORE_ID, lease_id=lease_id
        ) as guarded:
            assert guarded == orphaned
            with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as busy:
                registry.close()
            assert busy.value.code == "package_epoch_lease_busy"
            assert registry.path.read_bytes() == before_review
        assert registry.review_orphans(store_id=_STORE_ID) == (orphaned,)

        @contextmanager
        def refuse_stale(lease: object):
            assert lease == orphaned
            raise ValueError("stale Product proof")
            yield

        with pytest.raises(ValueError, match="stale Product proof"):
            registry.repair_orphan(lease_id, validation_guard=refuse_stale)
        assert registry.path.read_bytes() == before_review
        with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as still_orphaned:
            with registry.exclusive_runtime_quiescence(store_id=_STORE_ID):
                pytest.fail("Orphan lease was repaired after refused proof")
        assert still_orphaned.value.code == "package_epoch_lease_orphaned"

        events: list[str] = []

        @contextmanager
        def require_proof(lease: object):
            assert lease == orphaned
            events.append("entered")
            try:
                yield
            finally:
                events.append("exited")

        registry.repair_orphan(lease_id, validation_guard=require_proof)
        assert events == ["entered", "exited"]
        assert registry.review_orphans(store_id=_STORE_ID) == ()
        with registry.exclusive_runtime_quiescence(store_id=_STORE_ID) as held:
            assert held.active_runtime_lease_ids == ()
            [repaired] = held.repaired_runtime_records
            assert repaired.kind == "orphan_repaired"
            assert repaired.lease == orphaned
            assert repaired.record_revision < held.owner_revision
        with registry.register(
            runtime_id=orphaned.runtime_id, runtime_protocol_epoch=1
        ):
            pass
        with registry.exclusive_runtime_quiescence(store_id=_STORE_ID) as held:
            assert held.repaired_runtime_records == ()
    finally:
        registry.close()


def test_windows_runtime_lease_rejects_partial_journal_tail(tmp_path: Path) -> None:
    control = tmp_path / "control"
    fences = _fenced_control(control)
    registry = PackageWindowsEpochRuntimeLeaseRegistry(
        control_root=control, fences=fences, store_id=_STORE_ID
    )
    try:
        with registry.register(runtime_id="runtime:one", runtime_protocol_epoch=1):
            pass
        with registry.path.open("ab") as journal:
            journal.write(b'{"schemaVersion":')
            journal.flush()
            os.fsync(journal.fileno())
        with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as corrupt:
            registry.snapshot(store_id=_STORE_ID)
        assert corrupt.value.code == "package_epoch_lease_journal_corrupt"
    finally:
        registry.close()


def test_windows_runtime_lease_exit_failure_does_not_leak_local_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = tmp_path / "control"
    fences = _fenced_control(control)
    registry = PackageWindowsEpochRuntimeLeaseRegistry(
        control_root=control, fences=fences, store_id=_STORE_ID
    )
    original = registry._root.assert_visible
    calls = 0

    def fail_on_exit() -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("control root identity changed")
        original()

    try:
        monkeypatch.setattr(registry._root, "assert_visible", fail_on_exit)
        with pytest.raises(OSError, match="identity changed"):
            registry.register(runtime_id="runtime:one", runtime_protocol_epoch=1)
        monkeypatch.setattr(registry._root, "assert_visible", original)
        [registration] = registry.path.read_text(encoding="utf-8").splitlines()
        lease_id = PackageEpochRuntimeLeaseRecordV1.from_dict(
            json.loads(registration)
        ).lease.lease_id
        with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as orphan:
            registry.snapshot(store_id=_STORE_ID)
        assert orphan.value.code == "package_epoch_lease_orphaned"
        registry.repair_orphan(lease_id)
    finally:
        monkeypatch.setattr(registry._root, "assert_visible", original)
        registry.close()


def test_windows_runtime_lease_full_journal_does_not_register(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = tmp_path / "control"
    fences = _fenced_control(control)
    registry = PackageWindowsEpochRuntimeLeaseRegistry(
        control_root=control, fences=fences, store_id=_STORE_ID
    )
    try:
        with registry.register(runtime_id="runtime:one", runtime_protocol_epoch=1):
            pass
        before = registry.path.read_bytes()
        monkeypatch.setattr(
            windows_lease_registry, "_MAX_JOURNAL_BYTES", len(before) + 1
        )
        with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as full:
            registry.register(runtime_id="runtime:two", runtime_protocol_epoch=1)
        assert full.value.code == "package_epoch_lease_journal_full"
        assert registry.path.read_bytes() == before
        with registry.exclusive_runtime_quiescence(store_id=_STORE_ID) as held:
            assert held.active_runtime_lease_ids == ()
    finally:
        registry.close()
