from __future__ import annotations

import base64
import csv
import io
import os
import stat
import zipfile
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.harness.package_product.product_gc_executor import (
    PackageProductGcExecutionError,
    PackageProductRootGcCommandV1,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductHostInputs,
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_root_gc_runtime import (
    open_windows_local_wheel_product_root_gc,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.package_gc_binding import (
    PluginPackageGcBindingJournal,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.records import PluginDesiredStateMutationV1
from loushang.harness.plugin_management.service import PluginManagementService
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.offline_restore import (
    PACKAGE_PRE_B_SNAPSHOT_DOMAINS,
    PackageOfflineRestoreOwner,
    PackageOfflineRestoreRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreSettlementJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover import (
    PackageWindowsEpochCutoverError,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_offline_restore import (
    PackageWindowsOfflineRestoreMaterializer,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleIntentV1,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
    PackageProductLocalWheelDependencyV1,
    PackageProductLocalWheelPolicy,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
    PackageWindowsCurrentEpochCutoverCoordinationOwner,
    prepare_windows_product_control_root,
)
from loushang.harness.resources.packages.product_windows_pre_b_snapshot import (
    PackageProductWindowsPreBSnapshotOwner,
    reopen_windows_product_cutover,
)
from loushang.harness.sandbox.package_windows_legacy_runtime import (
    PackageWindowsLegacyRuntimeActivationOwner,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-native contract")

STORE_ID = "package-store:windows-product-snapshot"


def _local_wheel(
    project: str, version: str, *, requires_dist: tuple[str, ...] = ()
) -> bytes:
    normalized = project.replace("-", "_")
    dist_info = f"{normalized}-{version}.dist-info"
    files = {
        f"{normalized}/__init__.py": b"VALUE = 1\n",
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\n"
            b"Generator: plc9b-windows-product-gc\n"
            b"Root-Is-Purelib: true\n"
            b"Tag: py3-none-any\n\n"
        ),
        f"{dist_info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {project}\nVersion: {version}\n"
            + "".join(f"Requires-Dist: {item}\n" for item in requires_dist)
            + "\n"
        ).encode(),
    }
    rows = [
        (
            name,
            "sha256="
            + base64.urlsafe_b64encode(sha256(body).digest()).rstrip(b"=").decode(),
            str(len(body)),
        )
        for name, body in files.items()
    ]
    rows.append((f"{dist_info}/RECORD", "", ""))
    record = io.StringIO(newline="")
    csv.writer(record, lineterminator="\n").writerows(rows)
    files[f"{dist_info}/RECORD"] = record.getvalue().encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in files.items():
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, body)
    return output.getvalue()


def _product(
    tmp_path: Path,
) -> tuple[PackageProductWindowsPreBSnapshotOwner, Path, Path, Path]:
    authority = tmp_path / "package-authority"
    prepare_windows_product_control_root(authority)
    prepare_windows_product_control_root(authority / "epochs")
    control = tmp_path / "control"
    prepare_windows_product_control_root(control)
    snapshot_root = authority / "snapshots"
    prepare_windows_product_control_root(snapshot_root)
    roots = {domain: authority / domain for domain in PACKAGE_PRE_B_SNAPSHOT_DOMAINS}
    roots["store_bytes"] = authority / "legacy"
    for root in roots.values():
        prepare_windows_product_control_root(root)
    (roots["store_bytes"] / "plugin.whl").write_bytes(b"wheel bytes")
    owner = PackageProductWindowsPreBSnapshotOwner(
        snapshot_root,
        store_id=STORE_ID,
        domain_roots=roots,
        domain_members=dict.fromkeys(PACKAGE_PRE_B_SNAPSHOT_DOMAINS),
        legacy_root_pointer_name="legacy",
    )
    return owner, authority, control, snapshot_root


def _cutover(
    owner: PackageProductWindowsPreBSnapshotOwner,
    authority: Path,
    control: Path,
    *,
    snapshot_admission=None,
):
    return owner.cutover_from_legacy(
        authority_root=authority,
        control_root=control,
        legacy_root_name="legacy",
        epochs_root_name="epochs",
        namespace_id=sha256(b"first-b-windows-product").hexdigest(),
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
        snapshot_admission=snapshot_admission,
    )


def test_windows_product_first_b_uses_authenticated_snapshot_before_fence(
    tmp_path: Path,
) -> None:
    owner, authority, control, _ = _product(tmp_path)
    admitted: list[str] = []

    def admit(receipt) -> None:
        evidence = owner.snapshot(receipt.receipt_id)
        assert evidence is not None
        assert evidence.snapshot == receipt
        assert (
            owner.read_regular_member(
                receipt.receipt_id, domain="store_bytes", member_name="plugin.whl"
            )
            == b"wheel bytes"
        )
        admitted.append(receipt.receipt_id)

    attempt = _cutover(owner, authority, control, snapshot_admission=admit)

    assert attempt.result.disposition == "fenced"
    assert attempt.result.fence is not None
    assert admitted == [attempt.result.fence.request.snapshot_receipt_id]
    assert (
        reopen_windows_product_cutover(
            authority_root=authority,
            control_root=control,
            store_id=STORE_ID,
            epochs_root_name="epochs",
        )
        == attempt.result
    )


def test_windows_product_snapshot_admission_refusal_leaves_no_fence(
    tmp_path: Path,
) -> None:
    owner, authority, control, _ = _product(tmp_path)

    def refuse(_receipt) -> None:
        raise ValueError("operator did not accept old state")

    with pytest.raises(PackageWindowsEpochCutoverError):
        _cutover(owner, authority, control, snapshot_admission=refuse)

    assert PackageEpochFenceJournal(control / "epoch.jsonl").current(STORE_ID) is None
    assert not list((authority / "epochs").iterdir())


def test_windows_product_first_b_restore_activates_and_settles_old_runtime(
    tmp_path: Path,
) -> None:
    snapshots, authority, control, snapshot_root = _product(tmp_path)
    attempt = _cutover(snapshots, authority, control)
    fence = attempt.result.fence
    assert fence is not None
    evidence = snapshots.snapshot(fence.request.snapshot_receipt_id)
    assert evidence is not None
    current_b_root = authority / "epochs" / attempt.request.namespace_id
    b_marker = current_b_root / "epoch-b.txt"
    b_marker.write_bytes(b"current B stays intact")
    fence_bytes = (control / "epoch.jsonl").read_bytes()
    restore_root = tmp_path / "restore-authority"
    activation_root = tmp_path / "activation-authority"
    restore_root.mkdir()
    activation_root.mkdir()
    request = PackageOfflineRestoreRequestV1.create(
        current_fence=fence,
        genesis_fence=fence,
        snapshot_evidence=evidence,
        restore_namespace_id=sha256(b"windows-product-first-b-restore").hexdigest(),
        legacy_runtime_version="1.9.0",
    )
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
    materializer = PackageWindowsOfflineRestoreMaterializer(
        snapshot_root,
        restore_root,
        current_b_authority_root=current_b_root,
        store_id=STORE_ID,
    )
    activation = PackageWindowsLegacyRuntimeActivationOwner(
        restore_root,
        activation_root,
        current_b_authority_root=current_b_root,
        store_id=STORE_ID,
        legacy_runtime_version=request.legacy_runtime_version,
        command=command,
    )
    product = PackageProductWindowsFencedRuntimeOwner.open(
        authority_root=authority,
        control_root=control,
        store_id=STORE_ID,
        epochs_root_name="epochs",
    )
    restored = None
    try:
        drill = PackageOfflineRestoreOwner(
            store_id=STORE_ID,
            epoch_journal=product.registry.fences,
            coordination=PackageWindowsCurrentEpochCutoverCoordinationOwner(
                product.registry
            ),
            snapshots=snapshots,
            materialization=materializer,
            activation=activation,
        )
        restored = drill.restore(request)
        assert restored.disposition == "restored"
        assert restored.materialization is not None
        assert restored.activation is not None
        assert restored.materialization.legacy_snapshot_exact
        assert restored.materialization.b_namespace_unreachable
        assert restored.activation.exclusive_old_runtime
        assert (
            restore_root
            / request.restore_namespace_id
            / "payload"
            / "store_bytes"
            / "plugin.whl"
        ).read_bytes() == b"wheel bytes"
        assert b_marker.read_bytes() == b"current B stays intact"
    finally:
        try:
            if restored is not None and restored.activation is not None:
                activation.deactivate_required(restored.activation)
            if restored is not None and restored.materialization is not None:
                materializer.discard(restored.materialization)
        finally:
            product.close()
    assert not (restore_root / request.restore_namespace_id).exists()
    assert not (activation_root / "active-runtime.json").exists()
    assert (control / "epoch.jsonl").read_bytes() == fence_bytes
    assert PackageEpochFenceJournal(control / "epoch.jsonl").current(STORE_ID) == fence


def test_windows_product_local_wheel_composition_activates_on_current_fence(
    tmp_path: Path,
) -> None:
    snapshot, authority, control, _ = _product(tmp_path)
    attempt = _cutover(snapshot, authority, control)
    assert attempt.result.disposition == "fenced"
    product = PackageProductWindowsFencedRuntimeOwner.open(
        authority_root=authority,
        control_root=control,
        store_id=STORE_ID,
        epochs_root_name="epochs",
    )
    try:
        state_root = product.prepare_product_state_root()
        source_root = product.prepare_product_source_root()
        gate = PluginPackageGcReservationJournal(state_root / "gc-reservations.jsonl")
        desired = PluginDesiredStateLedger(
            state_root / "desired-state.jsonl", gc_gate=gate
        )
        management = PluginManagementService(
            desired_state=desired,
            operation_journal_path=state_root / "management-operations.jsonl",
        )
        management.recover()
        bindings = PluginPackageGcBindingJournal(state_root / "gc-bindings.jsonl")
        host = PosixLocalWheelProductHostInputs.current_host(
            max_transport_bytes=2 * 1024 * 1024
        )
        policy = PackageProductLocalWheelPolicy(
            product_id="coding",
            project_scope_id="workspace:windows-product",
            source_root=source_root,
            bindings=(),
            policy_revision="windows-product-policy:1",
            quota_profile_revision="windows-product-quota:1",
            resolution_environment_fingerprint=host.environment.fingerprint,
            authority_id="windows-product-source",
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        session_owner = WindowsLocalWheelProductSessionOwner(
            workspace=workspace,
            policy=policy,
            host_inputs=host,
            root_store_identity=f"windows-product-root:{STORE_ID}",
            dependency_store_identity=f"windows-product-dependency:{STORE_ID}",
            epoch_runtime=product,
            management=management,
            desired_state=desired,
            gc_bindings=bindings,
            gc_gate=gate,
            actor_id="product:coding",
            desired_policy_revision="windows-desired-policy:1",
            recovery_identity=f"windows-product-recovery:{STORE_ID}",
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
        factory = session_owner.factory_for_session(
            session_id="session:windows-product",
            cwd=workspace,
            runtime_id="runtime:windows-product-composition",
        )
        try:
            binding = factory.create(
                PackageProductRuntimeRequestV1(
                    product_id="coding",
                    session_id="session:windows-product",
                    cwd=str(workspace),
                )
            )
            try:
                assert binding.activate() is binding
                assert (
                    binding.product_runtime_id == "runtime:windows-product-composition"
                )
                assert binding.session_id == "session:windows-product"
                assert binding.mode == "enforced"
            finally:
                binding.dispose_runtime()
        finally:
            factory.dispose_unbound_runtime()
        second = session_owner.factory_for_session(
            session_id="session:windows-replaced-workspace",
            cwd=workspace,
            runtime_id="runtime:windows-replaced-workspace",
        )
        moved = tmp_path / "moved-workspace"
        workspace.rename(moved)
        workspace.mkdir()
        try:
            with pytest.raises(ValueError, match="workspace identity changed"):
                second.create(
                    PackageProductRuntimeRequestV1(
                        product_id="coding",
                        session_id="session:windows-replaced-workspace",
                        cwd=str(workspace),
                    )
                )
        finally:
            second.dispose_unbound_runtime()
            workspace.rmdir()
            moved.rename(workspace)
        assert product.registry.snapshot(store_id=STORE_ID).active_leases == ()
    finally:
        product.close()


def test_windows_product_dependency_gc_requires_root_retirement_and_quiescence(
    tmp_path: Path,
) -> None:
    snapshots, authority, control, _ = _product(tmp_path)
    assert _cutover(snapshots, authority, control).result.disposition == "fenced"
    product = PackageProductWindowsFencedRuntimeOwner.open(
        authority_root=authority,
        control_root=control,
        store_id=STORE_ID,
        epochs_root_name="epochs",
    )
    try:
        state_root = product.prepare_product_state_root()
        source_root = product.prepare_product_source_root()
        gate = PluginPackageGcReservationJournal(state_root / "gc-reservations.jsonl")
        desired = PluginDesiredStateLedger(
            state_root / "desired-state.jsonl", gc_gate=gate
        )
        management = PluginManagementService(
            desired_state=desired,
            operation_journal_path=state_root / "management-operations.jsonl",
        )
        management.recover()
        bindings = PluginPackageGcBindingJournal(state_root / "gc-bindings.jsonl")
        root_source = source_root / "acme_plugin-1.0-py3-none-any.whl"
        dependency_source = source_root / "dependency-2.0-py3-none-any.whl"
        root_payload = _local_wheel(
            "acme-plugin", "1.0", requires_dist=("dependency==2.0",)
        )
        dependency_payload = _local_wheel("dependency", "2.0")
        root_source.write_bytes(root_payload)
        dependency_source.write_bytes(dependency_payload)
        host = PosixLocalWheelProductHostInputs.current_host(
            max_transport_bytes=2 * 1024 * 1024
        )
        policy = PackageProductLocalWheelPolicy(
            product_id="coding",
            project_scope_id="workspace:windows-product",
            source_root=source_root,
            bindings=(
                PackageProductLocalWheelBindingV1(
                    source_identity=str(root_source),
                    requested_package="acme-plugin==1.0",
                    plugin_id="acme.plugin",
                    artifact_digest=sha256(root_payload).hexdigest(),
                ),
            ),
            dependencies=(
                PackageProductLocalWheelDependencyV1(
                    source_identity=str(dependency_source),
                    project_name="dependency",
                    version="2.0",
                    artifact_digest=sha256(dependency_payload).hexdigest(),
                ),
            ),
            policy_revision="windows-dependency-policy:1",
            quota_profile_revision="windows-dependency-quota:1",
            resolution_environment_fingerprint=host.environment.fingerprint,
            authority_id="windows-dependency-source",
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        owner = WindowsLocalWheelProductSessionOwner(
            workspace=workspace,
            policy=policy,
            host_inputs=host,
            root_store_identity=f"windows-product-root:{STORE_ID}",
            dependency_store_identity=f"windows-product-dependency:{STORE_ID}",
            epoch_runtime=product,
            management=management,
            desired_state=desired,
            gc_bindings=bindings,
            gc_gate=gate,
            actor_id="product:coding",
            desired_policy_revision="windows-desired-policy:1",
            recovery_identity=f"windows-product-recovery:{STORE_ID}",
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
        factory = owner.factory_for_session(
            session_id="session:windows-dependency-install",
            cwd=workspace,
            runtime_id="runtime:windows-dependency-install",
        )
        binding = None
        try:
            binding = factory.create(
                PackageProductRuntimeRequestV1(
                    product_id="coding",
                    session_id="session:windows-dependency-install",
                    cwd=str(workspace),
                )
            )
            binding.activate()
            installed = binding.lifecycle.route(
                PackageProductLifecycleIntentV1(
                    operation_id="operator:windows-dependency-install",
                    action="install",
                    source=str(root_source),
                    scope="project",
                ),
                entrypoint="cli",
            )
            assert installed.handled
            assert installed.record is not None
            assert installed.record.lifecycle == "installed"
        finally:
            if binding is None:
                factory.dispose_unbound_runtime()
            else:
                binding.dispose_runtime()

        selected = desired.snapshot()
        (installation,) = selected.installations
        removed = management.submit(
            PluginManagementCommandV1(
                action="remove",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:windows-dependency-remove",
                    idempotency_key="operator:windows-dependency-remove",
                    expected_inventory_revision=selected.inventory_revision,
                    installation_key=installation.installation_key,
                    desired_state="absent",
                    package_revision=None,
                    actor_id="product:coding",
                    policy_revision="windows-desired-policy:1",
                ),
            )
        )
        assert removed.status == "terminal"
        gc = open_windows_local_wheel_product_root_gc(owner)
        gc.prepare()
        (candidate,) = gc.candidates()
        (retained,) = gc.dependency_inspections()
        assert retained.retention.disposition == "retained"
        assert retained.target is None
        (dependency_settlement,) = PackageStoreSettlementJournal(
            state_root / "dependency-settlements.jsonl"
        ).records()
        with pytest.raises(PackageProductGcExecutionError) as early:
            gc.delete_dependency(
                retained.retention.dependency_ref.ref_id,
                expected_settlement_id=dependency_settlement.settlement_id,
                operation_id="operator:windows-dependency-early-delete",
                idempotency_key="operator:windows-dependency-early-delete",
            )
        assert early.value.code == "plugin_package_gc_dependency_target_unavailable"
        assert not (state_root / "dependency-gc.jsonl").exists()
        assert (
            gc.execute(
                PackageProductRootGcCommandV1(
                    candidate=candidate,
                    reservation_operation_id="operator:windows-dependency-gc-reserve",
                    reservation_idempotency_key="operator:windows-dependency-gc-reserve",
                    attempt_operation_id="operator:windows-dependency-gc-root",
                    attempt_idempotency_key="operator:windows-dependency-gc-root",
                )
            ).disposition
            == "succeeded"
        )
        (orphan,) = gc.dependency_inspections()
        assert orphan.retention.disposition == "orphan_candidate"
        assert orphan.target is not None
        dependency_tree = (
            owner.dependency_store_root / orphan.target.settlement.final_name
        )
        assert dependency_tree.is_dir()
        live = owner.factory_for_session(
            session_id="session:windows-dependency-live",
            cwd=workspace,
            runtime_id="runtime:windows-dependency-live",
        )
        try:
            with pytest.raises(PackageProductGcExecutionError) as busy:
                gc.delete_dependency(
                    orphan.retention.dependency_ref.ref_id,
                    expected_settlement_id=orphan.target.settlement_id,
                    operation_id="operator:windows-dependency-live-delete",
                    idempotency_key="operator:windows-dependency-live-delete",
                )
            assert busy.value.code == "plugin_package_gc_runtime_active"
            assert dependency_tree.is_dir()
        finally:
            live.dispose_unbound_runtime()
        deleted = gc.delete_dependency(
            orphan.retention.dependency_ref.ref_id,
            expected_settlement_id=orphan.target.settlement_id,
            operation_id="operator:windows-dependency-delete",
            idempotency_key="operator:windows-dependency-delete",
        )
        assert deleted.disposition == "succeeded"
        assert not dependency_tree.exists()
        assert (
            gc.delete_dependency(
                orphan.retention.dependency_ref.ref_id,
                expected_settlement_id=orphan.target.settlement_id,
                operation_id="operator:windows-dependency-delete",
                idempotency_key="operator:windows-dependency-delete",
            )
            == deleted
        )
    finally:
        product.close()
