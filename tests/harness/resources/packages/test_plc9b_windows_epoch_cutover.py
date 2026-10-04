from __future__ import annotations

import ctypes as C
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from ctypes import wintypes as W
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import Lock

import pytest

import loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover as windows_epoch_cutover
from loushang.coding._plugin_lifecycle import (
    _CODING_PLUGIN_RUNTIME_BOOT_ID,
    _release_process_startup_lease,
    build_coding_plugin_lifecycle,
    build_coding_plugin_management_application,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_epoch_layout import resolve_coding_package_epoch_layout
from loushang.coding.package_product_runtime import open_coding_package_product_state
from loushang.foundation.platform_paths import PlatformPaths
from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
    PackageEpochRuntimeLeaseRegistryError,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverQuiescenceReceiptV1,
    PackageEpochCutoverSnapshotReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover import (
    PackageWindowsEpochCutoverError,
    PackageWindowsEpochCutoverOwner,
    PackageWindowsEpochCutoverRequestV1,
    PackageWindowsEpochCutoverResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_pre_fence_registration import (
    PackageWindowsPreFenceRegistrationError,
    PackageWindowsPreFenceRegistrationOwner,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsEpochTransactionGuard,
    PackageProductWindowsFencedRuntimeOwner,
    PackageProductWindowsStoreRootAdmission,
    PackageWindowsCurrentEpochCutoverCoordinationOwner,
    PackageWindowsFirstEpochCutoverCoordinationOwner,
    prepare_windows_product_control_root,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-native contract")

STORE_ID = "package-store:windows-cutover"


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
    legacy.mkdir(parents=True)
    epochs.mkdir()
    (legacy / "state.json").write_bytes(b'{"legacy":true}\n')
    return authority, legacy, epochs


def _private_control_root(tmp_path: Path) -> Path:
    control = tmp_path / "control"
    assert prepare_windows_product_control_root(control) == control
    assert prepare_windows_product_control_root(control) == control
    return control


def _set_directory_dacl(path: Path, *, world_read: bool) -> None:
    with WindowsPrivateDirectoryAcl() as acl:
        descriptor = C.c_void_p()
        dacl = C.c_void_p()
        present = W.BOOL()
        defaulted = W.BOOL()
        sddl = "D:P" + "".join(
            f"(A;;FA;;;{sid})" for sid in sorted({acl._user_sid, "S-1-5-18"})
        )
        if world_read:
            sddl += "(A;;FR;;;WD)"
        try:
            assert acl._security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, C.byref(descriptor), None
            )
            assert acl._security.GetSecurityDescriptorDacl(
                descriptor, C.byref(present), C.byref(dacl), C.byref(defaulted)
            )
            assert present.value and dacl.value
            change = acl._security.SetNamedSecurityInfoW
            change.argtypes = [W.LPWSTR, C.c_int, W.DWORD] + [C.c_void_p] * 4
            change.restype = W.DWORD
            assert change(str(path), 1, 0x80000004, None, None, dacl, None) == 0
        finally:
            if descriptor.value is not None:
                assert not acl._kernel.LocalFree(descriptor)


def _owner(
    tmp_path: Path,
    *,
    coordination: _CoordinationOwner | None = None,
    snapshots: _SnapshotOwner | None = None,
    before_fence_probe=None,
) -> tuple[
    PackageWindowsEpochCutoverOwner,
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
    owner = PackageWindowsEpochCutoverOwner(
        authority,
        store_id=STORE_ID,
        epoch_journal=journal,
        coordination=coordination,
        snapshots=snapshots,
        before_fence_probe=before_fence_probe,
    )
    return owner, journal, coordination, snapshots, authority, legacy, epochs


def _request(
    owner: PackageWindowsEpochCutoverOwner,
    *,
    namespace_id: str = "a" * 64,
) -> PackageWindowsEpochCutoverRequestV1:
    return PackageWindowsEpochCutoverRequestV1.create(
        store_id=STORE_ID,
        prior_fence=None,
        expected_legacy_root_identity=owner.current_root_identity(),
        namespace_id=namespace_id,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )


def test_windows_cutover_uses_epoch_append_as_the_only_atomic_root_pointer(
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
    assert len(journal.records()) == 1
    assert journal.current(STORE_ID) == result.fence
    assert result.fence.request.root_switch_receipt_id == (
        result.switch_receipt.switch_receipt_id
    )
    assert result.fence.request.namespace_id == request.namespace_id
    assert result.fence.fenced_root_identity == owner.current_root_identity()
    assert (
        PackageWindowsEpochCutoverOwner.reopen_fenced(
            authority,
            store_id=STORE_ID,
            epoch_journal=journal,
            epochs_root_name="epochs",
        )
        == result
    )
    assert (epochs / request.namespace_id).is_dir()
    assert (legacy / "state.json").read_bytes() == legacy_before
    assert not (authority / "active-root").exists()
    assert PackageWindowsEpochCutoverRequestV1.from_dict(request.to_dict()) == request
    assert PackageWindowsEpochCutoverResultV1.from_dict(result.to_dict()) == result
    serialized = repr((request, result)).lower()
    for forbidden in ("password", "credential", "token", str(tmp_path).lower()):
        assert forbidden not in serialized

    detached = tmp_path / "detached-authority"
    authority.rename(detached)
    detached.rename(authority)
    detached_epoch = tmp_path / "detached-epoch"
    (epochs / request.namespace_id).rename(detached_epoch)
    detached_epoch.rmdir()


def test_windows_cutover_reopen_requires_current_selected_root(tmp_path: Path) -> None:
    owner, journal, _coordination, _snapshots, authority, _legacy, epochs = _owner(
        tmp_path
    )
    with pytest.raises(PackageWindowsEpochCutoverError) as unfenced:
        PackageWindowsEpochCutoverOwner.reopen_fenced(
            authority,
            store_id=STORE_ID,
            epoch_journal=journal,
            epochs_root_name="epochs",
        )
    assert unfenced.value.code == "package_epoch_fence_stale"

    request = _request(owner)
    result = owner.cutover(request)
    selected = epochs / request.namespace_id
    moved = epochs / "moved-selected"
    selected.rename(moved)
    selected.mkdir()
    with pytest.raises(PackageWindowsEpochCutoverError) as changed:
        PackageWindowsEpochCutoverOwner.reopen_fenced(
            authority,
            store_id=STORE_ID,
            epoch_journal=journal,
            epochs_root_name="epochs",
        )
    assert changed.value.code == "package_epoch_cutover_identity_changed"
    selected.rmdir()
    moved.rename(selected)
    assert (
        PackageWindowsEpochCutoverOwner.reopen_fenced(
            authority,
            store_id=STORE_ID,
            epoch_journal=journal,
            epochs_root_name="epochs",
        )
        == result
    )


def test_windows_product_epoch_owner_holds_fence_and_runtime_gate(
    tmp_path: Path,
) -> None:
    authority, _legacy, epochs = _layout(tmp_path)
    control = _private_control_root(tmp_path)
    fences = PackageEpochFenceJournal(control / "epoch.jsonl")
    cutover = PackageWindowsEpochCutoverOwner(
        authority,
        store_id=STORE_ID,
        epoch_journal=fences,
        coordination=_CoordinationOwner(),
        snapshots=_SnapshotOwner(),
    )
    with pytest.raises(PackageWindowsEpochCutoverError) as unfenced:
        PackageProductWindowsFencedRuntimeOwner.open(
            authority_root=authority,
            control_root=control,
            store_id=STORE_ID,
            epochs_root_name="epochs",
        )
    assert unfenced.value.code == "package_epoch_fence_stale"
    result = cutover.cutover(_request(cutover))
    assert result.fence is not None
    product = PackageProductWindowsFencedRuntimeOwner.open(
        authority_root=authority,
        control_root=control,
        store_id=STORE_ID,
        epochs_root_name="epochs",
    )
    try:
        assert product.cutover_result == result
        product.assert_current()
        state_root = control / "product-state"
        source_root = control / "product-sources"
        dependency_root = control / "dependency-store"
        assert not state_root.exists()
        assert not source_root.exists()
        assert not dependency_root.exists()
        state_root.write_bytes(b"not a Product directory")
        with pytest.raises(OSError):
            product.prepare_product_state_root()
        state_root.unlink()
        assert product.prepare_product_state_root() == state_root
        assert product.prepare_product_state_root() == state_root
        assert product.prepare_product_source_root() == source_root
        assert product.prepare_product_dependency_root() == dependency_root
        assert result.switch_receipt is not None
        assert product.selected_store_root() == epochs / result.switch_receipt.namespace_id
        assert state_root.is_dir()
        assert source_root.is_dir()
        assert dependency_root.is_dir()
        handle = product.registry.register(
            runtime_id="runtime:product-test", runtime_protocol_epoch=2
        )
        try:
            with product.exclusive_runtime_quiescence() as held:
                assert held.active_runtime_lease_ids == (handle.lease.lease_id,)
                product.assert_current()
                with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as busy:
                    product.close()
                assert busy.value.code == "package_epoch_lease_busy"
            with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as live_close:
                product.close()
            assert live_close.value.code == "package_epoch_lease_live"
        finally:
            handle.release()
        with product.exclusive_runtime_quiescence() as held:
            assert held.active_runtime_lease_ids == ()
        with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as old_protocol:
            product.issue_runtime_lease(
                runtime_id="runtime:old-protocol",
                runtime_version="2.0.0",
                runtime_protocol_epoch=1,
            )
        assert old_protocol.value.code == "package_runtime_protocol_unsupported"
        with pytest.raises(ValueError, match="runtime version"):
            product.issue_runtime_lease(
                runtime_id="runtime:invalid-version",
                runtime_version="",
                runtime_protocol_epoch=2,
            )
        with product.exclusive_runtime_quiescence() as held:
            assert held.active_runtime_lease_ids == ()
        session = product.issue_runtime_lease(
            runtime_id="runtime:admitted-session",
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
        assert session.admission_request.store_id == STORE_ID
        assert session.admission_request.fence_id == result.fence.fence_id
        guard = PackageProductWindowsEpochTransactionGuard(product)
        root_admission = PackageProductWindowsStoreRootAdmission(
            epoch_runtime=product
        )
        with guard.shared_runtime(store_id=STORE_ID):
            admitted = root_admission.admit(session.admission_request)
            assert admitted.disposition == "admitted"
            with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as nested:
                product.registry.register(
                    runtime_id="runtime:nested",
                    runtime_protocol_epoch=2,
                )
            assert nested.value.code == "package_epoch_lease_busy"
            with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as guard_close:
                product.close()
            assert guard_close.value.code == "package_epoch_lease_busy"
        with pytest.raises(RuntimeError, match="injected transaction failure"):
            with guard.shared_runtime(store_id=STORE_ID):
                raise RuntimeError("injected transaction failure")
        assert tuple(
            lease.lease_id
            for lease in product.registry.snapshot(store_id=STORE_ID).active_leases
        ) == (session.admission_request.lease_id,)
        with product.exclusive_runtime_quiescence() as held:
            assert held.active_runtime_lease_ids == (
                session.admission_request.lease_id,
            )
        with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as session_close:
            product.close()
        assert session_close.value.code == "package_epoch_lease_live"
        session.release()
        with product.exclusive_runtime_quiescence() as held:
            assert held.active_runtime_lease_ids == ()
        assert result.switch_receipt is not None
        selected = epochs / result.switch_receipt.namespace_id
        moved = epochs / "moved-product-selected"
        selected.rename(moved)
        selected.mkdir()
        try:
            with pytest.raises(PackageWindowsEpochCutoverError) as replaced:
                product.assert_current()
            assert replaced.value.code == "package_epoch_cutover_identity_changed"
            assert (
                root_admission.admit(session.admission_request).disposition
                == "rejected"
            )
        finally:
            selected.rmdir()
            moved.rename(selected)
        product.assert_current()
        try:
            with pytest.raises(PackageWindowsEpochCutoverError) as unavailable:
                with product.exclusive_runtime_quiescence():
                    selected.rename(moved)
                    selected.mkdir()
            assert unavailable.value.code == "package_epoch_cutover_identity_changed"
        finally:
            selected.rmdir()
            moved.rename(selected)
    finally:
        product.close()
    with pytest.raises(ValueError, match="closed"):
        product.assert_current()
    reopened = PackageProductWindowsFencedRuntimeOwner.open(
        authority_root=authority,
        control_root=control,
        store_id=STORE_ID,
        epochs_root_name="epochs",
    )
    try:
        assert reopened.prepare_product_state_root() == state_root
        assert reopened.prepare_product_source_root() == source_root
        assert reopened.prepare_product_dependency_root() == dependency_root
    finally:
        reopened.close()


def test_windows_product_epoch_owner_rejects_extra_acl_trustee(
    tmp_path: Path,
) -> None:
    authority, _legacy, _epochs = _layout(tmp_path)
    control = _private_control_root(tmp_path)
    fences = PackageEpochFenceJournal(control / "epoch.jsonl")
    cutover = PackageWindowsEpochCutoverOwner(
        authority,
        store_id=STORE_ID,
        epoch_journal=fences,
        coordination=_CoordinationOwner(),
        snapshots=_SnapshotOwner(),
    )
    cutover.cutover(_request(cutover))
    _set_directory_dacl(control, world_read=True)
    try:
        with pytest.raises(OSError, match="extra trustees"):
            prepare_windows_product_control_root(control)
        with pytest.raises(OSError, match="extra trustees"):
            PackageProductWindowsFencedRuntimeOwner.open(
                authority_root=authority,
                control_root=control,
                store_id=STORE_ID,
                epochs_root_name="epochs",
            )
    finally:
        _set_directory_dacl(control, world_read=False)

    product = PackageProductWindowsFencedRuntimeOwner.open(
        authority_root=authority,
        control_root=control,
        store_id=STORE_ID,
        epochs_root_name="epochs",
    )
    try:
        child = product.prepare_product_state_root()
        _set_directory_dacl(child, world_read=True)
        with pytest.raises(OSError, match="extra trustees"):
            product.assert_current()
    finally:
        _set_directory_dacl(control / "product-state", world_read=False)
        product.close()


def test_windows_fenced_coding_product_opens_real_state_owners(
    tmp_path: Path,
) -> None:
    paths = PlatformPaths(
        home=tmp_path / "home",
        data=tmp_path / "data",
        state=tmp_path / "state",
        cache=tmp_path / "cache",
        runtime=tmp_path / "runtime",
        temporary=tmp_path / "temporary",
    )
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(
        tmp_path, platform_paths=paths
    )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    epoch.legacy_root.mkdir(parents=True)
    epoch.epochs_root.mkdir()
    epoch.control_root.parent.mkdir(parents=True)
    assert (
        prepare_windows_product_control_root(epoch.control_root) == epoch.control_root
    )
    fences = PackageEpochFenceJournal(epoch.control_root / "epoch.jsonl")
    cutover = PackageWindowsEpochCutoverOwner(
        epoch.authority_root,
        store_id=epoch.store_id,
        epoch_journal=fences,
        coordination=_CoordinationOwner(),
        snapshots=_SnapshotOwner(),
        epochs_root_name=epoch.epochs_root_name,
    )
    request = PackageWindowsEpochCutoverRequestV1.create(
        store_id=epoch.store_id,
        prior_fence=None,
        expected_legacy_root_identity=cutover.current_root_identity(),
        namespace_id="e" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    assert cutover.cutover(request).disposition == "fenced"
    product = PackageProductWindowsFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        state = open_coding_package_product_state(lifecycle, product)
        assert state.state_root == epoch.control_root / "product-state"
        assert state.gc_gate.path == state.state_root / "gc-reservations.jsonl"
        assert state.desired_state.path == state.state_root / "desired-state.jsonl"
        assert state.state_root.is_dir()
        product.assert_current()
    finally:
        product.close()


def test_windows_coding_legacy_startup_holds_pre_fence_registration(
    tmp_path: Path,
) -> None:
    paths = PlatformPaths(
        home=tmp_path / "home",
        data=tmp_path / "data",
        state=tmp_path / "state",
        cache=tmp_path / "cache",
        runtime=tmp_path / "runtime",
        temporary=tmp_path / "temporary",
    )
    layout = resolve_coding_plugin_lifecycle_state_layout(
        tmp_path, platform_paths=paths
    )
    lifecycle = build_coding_plugin_lifecycle(
        layout, startup_id="windows-pre-fence-test"
    )
    epoch = resolve_coding_package_epoch_layout(layout)
    try:
        pre_fence = PackageWindowsPreFenceRegistrationOwner(
            epoch.control_root,
            store_id=epoch.store_id,
            fences=PackageEpochFenceJournal(epoch.control_root / "epoch.jsonl"),
        )
        with pre_fence.exclusive_quiescence(store_id=epoch.store_id) as held:
            assert len(held.active_registration_ids) == 1
    finally:
        lifecycle.release_owned_process_startup_lease()
    with pre_fence.exclusive_quiescence(store_id=epoch.store_id) as held:
        assert held.active_registration_ids == ()


def test_windows_coding_management_writer_registers_before_state_recovery(
    tmp_path: Path,
) -> None:
    paths = PlatformPaths(
        home=tmp_path / "home",
        data=tmp_path / "data",
        state=tmp_path / "state",
        cache=tmp_path / "cache",
        runtime=tmp_path / "runtime",
        temporary=tmp_path / "temporary",
    )
    layout = resolve_coding_plugin_lifecycle_state_layout(
        tmp_path, platform_paths=paths
    )
    epoch = resolve_coding_package_epoch_layout(layout)
    try:
        build_coding_plugin_management_application(layout)
        pre_fence = PackageWindowsPreFenceRegistrationOwner(
            epoch.control_root,
            store_id=epoch.store_id,
            fences=PackageEpochFenceJournal(epoch.control_root / "epoch.jsonl"),
        )
        with pre_fence.exclusive_quiescence(store_id=epoch.store_id) as held:
            assert len(held.active_registration_ids) == 1
    finally:
        _release_process_startup_lease(
            layout, startup_id=_CODING_PLUGIN_RUNTIME_BOOT_ID
        )


def test_windows_current_b_cutover_uses_product_lease_coordination(
    tmp_path: Path,
) -> None:
    authority, _legacy, _epochs = _layout(tmp_path)
    control = _private_control_root(tmp_path)
    fences = PackageEpochFenceJournal(control / "epoch.jsonl")
    pre_fence = PackageWindowsPreFenceRegistrationOwner(
        control, store_id=STORE_ID, fences=fences
    )
    first_owner = PackageWindowsEpochCutoverOwner(
        authority,
        store_id=STORE_ID,
        epoch_journal=fences,
        coordination=PackageWindowsFirstEpochCutoverCoordinationOwner(pre_fence),
        snapshots=_SnapshotOwner(),
    )
    first_request = _request(first_owner)
    legacy = pre_fence.register(startup_id="coding:legacy-one")
    try:
        refused_first = first_owner.cutover(first_request)
        assert refused_first.disposition == "rejected"
        assert refused_first.failure is not None
        assert refused_first.failure.evidence_ref == legacy.registration_id
    finally:
        legacy.release()
    first = first_owner.cutover(first_request)
    assert first.fence is not None
    with pytest.raises(PackageWindowsPreFenceRegistrationError) as fenced_old:
        pre_fence.register(startup_id="coding:legacy-after-fence")
    assert fenced_old.value.code == "package_runtime_epoch_unsupported"
    product = PackageProductWindowsFencedRuntimeOwner.open(
        authority_root=authority,
        control_root=control,
        store_id=STORE_ID,
        epochs_root_name="epochs",
    )
    try:
        current_coordination = PackageWindowsCurrentEpochCutoverCoordinationOwner(
            product.registry
        )
        upgrade = PackageWindowsEpochCutoverOwner(
            authority,
            store_id=STORE_ID,
            epoch_journal=fences,
            coordination=current_coordination,
            snapshots=_SnapshotOwner(),
        )
        request = PackageWindowsEpochCutoverRequestV1.create(
            store_id=STORE_ID,
            prior_fence=first.fence,
            expected_legacy_root_identity=upgrade.current_root_identity(),
            namespace_id="2" * 64,
            minimum_runtime_version="3.0.0",
            minimum_runtime_protocol_epoch=3,
        )
        session = product.issue_runtime_lease(
            runtime_id="runtime:current-b",
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
        try:
            refused = upgrade.cutover(request)
            assert refused.disposition == "rejected"
            assert refused.code == "package_runtime_epoch_unsupported"
            assert refused.failure is not None
            assert refused.failure.evidence_ref == session.admission_request.lease_id
            product.assert_current()
        finally:
            session.release()
        advanced = upgrade.cutover(request)
        assert advanced.disposition == "fenced"
        assert advanced.fence is not None
        assert advanced.fence.epoch == first.fence.epoch + 1
        with pytest.raises(ValueError, match="epoch changed"):
            product.assert_current()
    finally:
        product.close()


def test_windows_first_b_refuses_unattributed_runtime_history(tmp_path: Path) -> None:
    control = _private_control_root(tmp_path)
    fences = PackageEpochFenceJournal(control / "epoch.jsonl")
    pre_fence = PackageWindowsPreFenceRegistrationOwner(
        control, store_id=STORE_ID, fences=fences
    )
    (control / "runtime-leases.jsonl").write_bytes(b"")
    coordination = PackageWindowsFirstEpochCutoverCoordinationOwner(pre_fence)
    with pytest.raises(PackageWindowsPreFenceRegistrationError) as stale:
        with coordination.exclusive_quiescence(store_id=STORE_ID):
            pass
    assert stale.value.code == "package_pre_fence_runtime_history_present"


def test_windows_cutover_advances_only_from_the_exact_current_namespace(
    tmp_path: Path,
) -> None:
    owner, journal, coordination, snapshots, _authority, _legacy, epochs = _owner(
        tmp_path
    )
    first_request = _request(owner, namespace_id="a" * 64)
    first = owner.cutover(first_request)
    assert first.fence is not None
    second_request = PackageWindowsEpochCutoverRequestV1.create(
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
    assert (
        PackageWindowsEpochCutoverOwner.reopen_fenced(
            _authority,
            store_id=STORE_ID,
            epoch_journal=journal,
            epochs_root_name="epochs",
        )
        == second
    )
    assert replay == second
    assert len(journal.records()) == 2
    assert coordination.calls == 2
    assert snapshots.calls == 2
    assert (epochs / first_request.namespace_id).is_dir()
    assert (epochs / second_request.namespace_id).is_dir()


def test_windows_cutover_concurrent_exact_requests_converge_once(
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


@pytest.mark.parametrize(
    ("coordination", "evidence_ref"),
    (
        (_CoordinationOwner(active_pre_fence_registration_ids=("b" * 64,)), "b" * 64),
        (_CoordinationOwner(active_runtime_lease_ids=("c" * 64,)), "c" * 64),
    ),
)
def test_windows_cutover_refuses_live_writer_before_native_mutation(
    tmp_path: Path,
    coordination: _CoordinationOwner,
    evidence_ref: str,
) -> None:
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
    assert result.failure.evidence_ref == evidence_ref
    assert coordination.calls == 1
    assert snapshots.calls == 0
    assert journal.records() == ()
    assert tuple(epochs.iterdir()) == ()
    assert (legacy / "state.json").read_bytes() == legacy_before


def test_windows_cutover_rejects_precreated_namespace_without_trusting_it(
    tmp_path: Path,
) -> None:
    owner, journal, _coordination, snapshots, _authority, _legacy, epochs = _owner(
        tmp_path
    )
    request = _request(owner, namespace_id="d" * 64)
    forged = epochs / request.namespace_id
    forged.mkdir()
    (forged / "attacker").write_bytes(b"preserve")

    with pytest.raises(PackageWindowsEpochCutoverError) as raised:
        owner.cutover(request)

    assert raised.value.code == "package_epoch_cutover_namespace_conflict"
    assert snapshots.calls == 1
    assert journal.records() == ()
    assert (forged / "attacker").read_bytes() == b"preserve"


@pytest.mark.parametrize("target", ("authority", "epochs"))
def test_windows_cutover_blocks_namespace_swap_and_cleans_residue(
    tmp_path: Path,
    target: str,
) -> None:
    authority, legacy, epochs = _layout(tmp_path)
    detached = tmp_path / f"{target}-detached"

    def attempt_swap() -> None:
        selected = authority if target == "authority" else epochs
        selected.rename(detached)

    journal = PackageEpochFenceJournal(tmp_path / "package-epoch.jsonl")
    owner = PackageWindowsEpochCutoverOwner(
        authority,
        store_id=STORE_ID,
        epoch_journal=journal,
        coordination=_CoordinationOwner(),
        snapshots=_SnapshotOwner(),
        before_fence_probe=attempt_swap,
    )
    request = _request(owner, namespace_id="e" * 64)

    with pytest.raises(PackageWindowsEpochCutoverError) as raised:
        owner.cutover(request)

    assert raised.value.code == "package_epoch_cutover_identity_changed"
    assert journal.records() == ()
    assert not (epochs / request.namespace_id).exists()
    assert not detached.exists()
    assert (legacy / "state.json").read_bytes() == b'{"legacy":true}\n'
    movable = tmp_path / "authority-movable"
    authority.rename(movable)
    movable.rename(authority)


def test_windows_cutover_releases_every_native_descriptor(
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
        coordination=_CoordinationOwner(active_pre_fence_registration_ids=("5" * 64,)),
    )

    real_open_chain = windows_epoch_cutover._open_ancestor_chain
    real_open_directory_at = windows_epoch_cutover._open_directory_at
    real_close = windows_epoch_cutover.os.close
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
        windows_epoch_cutover, "_open_ancestor_chain", tracking_open_chain
    )
    monkeypatch.setattr(
        windows_epoch_cutover, "_open_directory_at", tracking_open_directory_at
    )
    monkeypatch.setattr(windows_epoch_cutover.os, "close", tracking_close)

    success = success_owner.cutover(_request(success_owner))
    assert success.disposition == "fenced"
    assert opened == set()

    refusal = refusal_owner.cutover(_request(refusal_owner, namespace_id="6" * 64))
    assert refusal.disposition == "rejected"
    assert opened == set()


def test_windows_cutover_records_reject_extended_or_forged_wire_values(
    tmp_path: Path,
) -> None:
    owner, _journal, _coordination, _snapshots, *_paths = _owner(tmp_path)
    request = _request(owner)
    extended = request.to_dict()
    extended["legacyPath"] = r"C:\\forged"
    with pytest.raises(ValueError, match="versioned schema"):
        PackageWindowsEpochCutoverRequestV1.from_dict(extended)
    forged = request.to_dict()
    forged["requestId"] = "0" * 64
    with pytest.raises(ValueError, match="does not match"):
        PackageWindowsEpochCutoverRequestV1.from_dict(forged)
