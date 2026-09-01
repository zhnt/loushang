from __future__ import annotations

import io
import os
import shutil
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    NormalizedPackageRequirementV1,
    ResolvedPackageRequirementV1,
    VerifiedClosurePlanNodeV2,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    PluginRevisionRefV1,
    VerifiedArtifactRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging import (
    PackageArtifactStagingRequestV1,
    PackagePluginRootTargetV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinReceiptV1,
    PackageTransactionPinRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.tree_transfer import (
    PackageVerifiedTreeEntryV1,
    PackageVerifiedTreeManifestV1,
    PackageVerifiedTreeTransferOwner,
    verified_tree_digest,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    VerifiedWheelArtifactV1,
    VerifiedWheelCandidate,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_materialization import (
    PackagePhysicalStagingError,
    WindowsPackageDependencyMaterializationStore,
    WindowsPackagePluginRootMaterializationStore,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-native contract")

OPERATION_ID = "operation-windows-materialization"
REQUEST_FINGERPRINT = "9" * 64
CLASSIFICATION_FINGERPRINT = "8" * 64
ENVIRONMENT_FINGERPRINT = "7" * 64


@dataclass
class _MemoryAcquired:
    payloads: dict[str, bytes]
    closed: bool = False

    def _open_verified_tree_file(self, logical_path: str) -> io.BytesIO:
        if self.closed:
            raise RuntimeError("candidate is closed")
        return io.BytesIO(self.payloads[logical_path])

    def suspend_for_recovery(self) -> None:
        self.closed = True


def _entries(payloads: dict[str, bytes]) -> tuple[PackageVerifiedTreeEntryV1, ...]:
    return tuple(
        PackageVerifiedTreeEntryV1(
            logical_path=logical_path,
            content_digest=sha256(payload).hexdigest(),
            byte_count=len(payload),
        )
        for logical_path, payload in sorted(
            payloads.items(), key=lambda item: tuple(item[0].split("/"))
        )
    )


def _evidence(
    *,
    node_id: str,
    distribution: str,
    version: str,
    payloads: dict[str, bytes],
    artifact_digest: str,
) -> VerifiedWheelArtifactV1:
    entries = _entries(payloads)
    return VerifiedWheelArtifactV1(
        operation_id=OPERATION_ID,
        attempt_epoch=1,
        node_id=node_id,
        distribution=distribution,
        version=version,
        wheel_filename=f"{distribution.replace('-', '_')}-{version}-py3-none-any.whl",
        compatible_tags=("py3-none-any",),
        artifact_digest=artifact_digest,
        artifact_size=123,
        wheel_metadata_digest="a" * 64,
        package_metadata_digest="b" * 64,
        record_digest="c" * 64,
        record_verified=True,
        entry_count=len(entries),
        expanded_byte_count=sum(entry.byte_count for entry in entries),
        extraction_tree_digest=verified_tree_digest(entries),
    )


def _candidate(
    evidence: VerifiedWheelArtifactV1,
    payloads: dict[str, bytes],
) -> VerifiedWheelCandidate:
    return VerifiedWheelCandidate(
        acquired=_MemoryAcquired(dict(payloads)),  # type: ignore[arg-type]
        evidence=evidence,
        transfer_manifest=PackageVerifiedTreeManifestV1.create(
            evidence,
            entries=_entries(payloads),
        ),
        requires_dist=(),
        requires_python=None,
        provides_extra=(),
    )


def _requests_and_candidates() -> tuple[
    PackageArtifactStagingRequestV1,
    VerifiedWheelCandidate,
    PackageArtifactStagingRequestV1,
    VerifiedWheelCandidate,
    dict[str, bytes],
    dict[str, bytes],
]:
    dependency_payloads = {
        "dependency/__init__.py": b"DEPENDENCY = 1\n",
        "dependency-2.0.dist-info/METADATA": b"Name: dependency\nVersion: 2.0\n",
    }
    root_payloads = {
        "root_plugin/__init__.py": b"PLUGIN = 1\n",
        "root_plugin-1.0.dist-info/METADATA": b"Name: root-plugin\nVersion: 1.0\n",
    }
    dependency_evidence = _evidence(
        node_id="dependency-node",
        distribution="dependency",
        version="2.0",
        payloads=dependency_payloads,
        artifact_digest="4" * 64,
    )
    root_evidence = _evidence(
        node_id="root",
        distribution="root-plugin",
        version="1.0",
        payloads=root_payloads,
        artifact_digest="6" * 64,
    )
    dependency_node = VerifiedClosurePlanNodeV2(
        node_id=dependency_evidence.node_id,
        role="dependency",
        distribution=dependency_evidence.distribution,
        version=dependency_evidence.version,
        canonical_source_identity="https://packages.example.test/dependency.whl",
        source_envelope_fingerprint="1" * 64,
        acquisition_receipt_fingerprint="2" * 64,
        wheel_evidence_fingerprint=dependency_evidence.fingerprint,
        artifact_digest=dependency_evidence.artifact_digest,
        extraction_tree_digest=dependency_evidence.extraction_tree_digest,
        selected_extras=(),
        requirements=(),
        selected_edges=(),
    )
    requirement = ResolvedPackageRequirementV1(
        requirement=NormalizedPackageRequirementV1.parse("dependency==2.0"),
        marker_applies=True,
        selected_node_id=dependency_node.node_id,
        expected_source_identity=dependency_node.canonical_source_identity,
        expected_artifact_digest=dependency_node.artifact_digest,
    )
    root_node = VerifiedClosurePlanNodeV2(
        node_id=root_evidence.node_id,
        role="root",
        distribution=root_evidence.distribution,
        version=root_evidence.version,
        canonical_source_identity="https://packages.example.test/root.whl",
        source_envelope_fingerprint="d" * 64,
        acquisition_receipt_fingerprint="e" * 64,
        wheel_evidence_fingerprint=root_evidence.fingerprint,
        artifact_digest=root_evidence.artifact_digest,
        extraction_tree_digest=root_evidence.extraction_tree_digest,
        selected_extras=(),
        requirements=(requirement,),
        selected_edges=(dependency_node.node_id,),
    )
    plan = VerifiedClosurePlanV2.create(
        operation_id=OPERATION_ID,
        attempt_epoch=1,
        root_node_id=root_node.node_id,
        resolution_environment_fingerprint=ENVIRONMENT_FINGERPRINT,
        nodes=(root_node, dependency_node),
        max_depth=1,
    )
    pin_request = PackageTransactionPinRequestV1.create(
        plan,
        request_fingerprint=REQUEST_FINGERPRINT,
        classification_fingerprint=CLASSIFICATION_FINGERPRINT,
        recovery_identity="recovery-windows-materialization",
    )
    pin = PackageTransactionPinReceiptV1.acquire(
        pin_request,
        pin_id="f" * 64,
        owner_identity="retention-owner",
        owner_revision=1,
        lease_id="lease-windows-materialization",
        lease_revision=1,
    )
    target = PackagePluginRootTargetV1.create(
        operation_id=OPERATION_ID,
        request_fingerprint=REQUEST_FINGERPRINT,
        product_id="coding",
        scope_id="workspace:test",
        installation_id="installation-test",
        plugin_id="plugin-test",
        authority_id="plugin-target-authority",
        authority_revision="target-revision:1",
    )
    dependency_request = PackageArtifactStagingRequestV1.create(
        plan,
        node_id=dependency_node.node_id,
        request_fingerprint=REQUEST_FINGERPRINT,
        classification_fingerprint=CLASSIFICATION_FINGERPRINT,
        pin_receipt=pin,
    )
    root_request = PackageArtifactStagingRequestV1.create(
        plan,
        node_id=root_node.node_id,
        request_fingerprint=REQUEST_FINGERPRINT,
        classification_fingerprint=CLASSIFICATION_FINGERPRINT,
        pin_receipt=pin,
        root_target=target,
    )
    return (
        dependency_request,
        _candidate(dependency_evidence, dependency_payloads),
        root_request,
        _candidate(root_evidence, root_payloads),
        dependency_payloads,
        root_payloads,
    )


def _assert_tree(root: Path, final_name: str, payloads: dict[str, bytes]) -> None:
    published = root / final_name
    assert published.is_dir()
    assert {
        path.relative_to(published).as_posix(): path.read_bytes()
        for path in published.rglob("*")
        if path.is_file()
    } == payloads


def test_windows_role_stores_publish_exact_trees_and_reuse_same_receipts(
    tmp_path: Path,
) -> None:
    (
        dependency_request,
        dependency_candidate,
        root_request,
        root_candidate,
        dependency_payloads,
        root_payloads,
    ) = _requests_and_candidates()
    dependency_root = tmp_path / "dependency-store"
    plugin_root = tmp_path / "plugin-store"
    dependency_root.mkdir()
    plugin_root.mkdir()
    transfer = PackageVerifiedTreeTransferOwner()
    dependencies = WindowsPackageDependencyMaterializationStore(
        dependency_root,
        store_identity="dependency-store",
        transfer=transfer,
    )
    plugins = WindowsPackagePluginRootMaterializationStore(
        plugin_root,
        store_identity="plugin-revision-store",
        transfer=transfer,
    )

    dependency_receipt = dependencies.stage_dependency(
        dependency_request,
        dependency_candidate,
    )
    root_receipt = plugins.stage_root(root_request, root_candidate)
    dependency_retry = dependencies.stage_dependency(
        dependency_request,
        _requests_and_candidates()[1],
    )
    root_retry = plugins.stage_root(root_request, _requests_and_candidates()[3])

    assert dependency_retry == dependency_receipt
    assert root_retry == root_receipt
    assert isinstance(dependency_receipt.stable_ref, VerifiedArtifactRefV1)
    assert isinstance(root_receipt.stable_ref, PluginRevisionRefV1)
    _assert_tree(
        dependency_root,
        f"artifact-{dependency_receipt.stable_ref.ref_id}",
        dependency_payloads,
    )
    _assert_tree(
        plugin_root,
        f"revision-{root_receipt.stable_ref.ref_id}",
        root_payloads,
    )
    dependency_moved = tmp_path / "dependency-store-moved"
    plugin_moved = tmp_path / "plugin-store-moved"
    dependency_root.rename(dependency_moved)
    plugin_root.rename(plugin_moved)
    dependency_moved.rename(dependency_root)
    plugin_moved.rename(plugin_root)


def test_windows_store_rejects_configured_root_replacement_before_sink(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir()
    store = WindowsPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
    )
    displaced = tmp_path / "store-displaced"
    root.rename(displaced)
    root.mkdir()

    with pytest.raises(PackagePhysicalStagingError) as raised:
        store.stage_dependency(request, candidate)

    assert raised.value.code == "package_publication_root_untrusted"
    assert tuple(root.iterdir()) == ()
    root.rmdir()
    displaced.rename(root)


def test_windows_store_rejects_root_replacement_aba_and_releases_handles(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir()
    detached = tmp_path / "store-detached"

    def replace_root() -> None:
        root.rename(detached)
        shutil.copytree(detached, root)

    store = WindowsPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        commit_probe=replace_root,
    )

    with pytest.raises(PackagePhysicalStagingError) as raised:
        store.stage_dependency(request, candidate)

    assert raised.value.code == "package_publication_root_untrusted"
    assert tuple(detached.iterdir()) == ()
    shutil.rmtree(root)
    detached.rename(root)
    moved = tmp_path / "store-moved"
    root.rename(moved)
    moved.rename(root)


def test_windows_store_rejects_ancestor_reparse_without_outside_write(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    ancestor = tmp_path / "authority"
    root = ancestor / "store"
    root.mkdir(parents=True)
    detached = tmp_path / "authority-detached"
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"preserve")

    def replace_ancestor() -> None:
        ancestor.rename(detached)
        ancestor.symlink_to(outside, target_is_directory=True)

    store = WindowsPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        commit_probe=replace_ancestor,
    )

    with pytest.raises(PackagePhysicalStagingError) as raised:
        store.stage_dependency(request, candidate)

    assert raised.value.code == "package_publication_root_untrusted"
    assert sentinel.read_bytes() == b"preserve"
    assert tuple((detached / "store").iterdir()) == ()
    ancestor.unlink()
    detached.rename(ancestor)


def test_windows_store_rejects_nested_reparse_before_namespace_rename(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"preserve")
    staging = root / f"staging-{request.staging_request_id}"
    detached_entry = staging / "dependency-detached"

    def replace_entry() -> None:
        (staging / "dependency").rename(detached_entry)
        (staging / "dependency").symlink_to(outside, target_is_directory=True)

    store = WindowsPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        commit_probe=replace_entry,
    )

    with pytest.raises(PackagePhysicalStagingError) as raised:
        store.stage_dependency(request, candidate)

    assert raised.value.code == "package_publication_root_untrusted"
    assert sentinel.read_bytes() == b"preserve"
    assert not any(path.name.startswith("artifact-") for path in root.iterdir())
    (staging / "dependency").unlink()
    shutil.rmtree(staging)
    moved = tmp_path / "store-moved"
    root.rename(moved)
    moved.rename(root)


def test_windows_store_rejects_staging_handle_swap_and_closes_every_handle(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"preserve")
    staging = root / f"staging-{request.staging_request_id}"
    detached_staging = root / "detached-staging"

    def replace_staging() -> None:
        staging.rename(detached_staging)
        staging.symlink_to(outside, target_is_directory=True)

    store = WindowsPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        commit_probe=replace_staging,
    )

    with pytest.raises(PackagePhysicalStagingError) as raised:
        store.stage_dependency(request, candidate)

    assert raised.value.code == "package_publication_root_untrusted"
    assert sentinel.read_bytes() == b"preserve"
    assert not any(path.name.startswith("artifact-") for path in root.iterdir())
    staging.unlink()
    shutil.rmtree(detached_staging)
    moved = tmp_path / "store-moved"
    root.rename(moved)
    moved.rename(root)


def test_windows_rejection_aborts_partial_tree_and_releases_handles(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    acquired = candidate._acquired
    assert isinstance(acquired, _MemoryAcquired)
    first = candidate.transfer_manifest.entries[0]
    acquired.payloads[first.logical_path] += b"tampered"
    root = tmp_path / "store"
    root.mkdir()
    store = WindowsPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
    )

    with pytest.raises(PackagePhysicalStagingError) as raised:
        store.stage_dependency(request, candidate)

    assert raised.value.code == "package_artifact_identity_changed"
    assert tuple(root.iterdir()) == ()
    moved = tmp_path / "store-moved"
    root.rename(moved)
    moved.rename(root)


def test_windows_store_does_not_adopt_tree_without_live_owner_evidence(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir()
    first_owner = WindowsPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
    )
    first_owner.stage_dependency(request, candidate)
    restarted_without_durable_proof = WindowsPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
    )

    with pytest.raises(PackagePhysicalStagingError) as raised:
        restarted_without_durable_proof.stage_dependency(
            request,
            _requests_and_candidates()[1],
        )

    assert raised.value.code == "package_publication_collision"


def test_windows_store_rejects_relative_root_without_ambient_cwd() -> None:
    with pytest.raises(PackagePhysicalStagingError) as raised:
        WindowsPackageDependencyMaterializationStore(
            Path("relative-store"),
            store_identity="dependency-store",
        )

    assert raised.value.code == "package_publication_root_untrusted"
