from __future__ import annotations

import io
import os
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
from loushang.harness.resources.packages.plugin_lifecycle.posix_materialization import (
    PackagePhysicalStagingError,
    PosixPackageDependencyMaterializationStore,
    PosixPackagePluginRootMaterializationStore,
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

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX-native contract")

OPERATION_ID = "operation-posix-materialization"
REQUEST_FINGERPRINT = "9" * 64
CLASSIFICATION_FINGERPRINT = "8" * 64
ENVIRONMENT_FINGERPRINT = "7" * 64


@dataclass
class _MemoryAcquired:
    payloads: dict[str, bytes]
    closed: bool = False

    def _open_verified_tree_file(
        self,
        logical_path: str,
    ) -> io.BytesIO:
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
        recovery_identity="recovery-posix-materialization",
    )
    pin = PackageTransactionPinReceiptV1.acquire(
        pin_request,
        pin_id="f" * 64,
        owner_identity="retention-owner",
        owner_revision=1,
        lease_id="lease-posix-materialization",
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


def test_posix_role_stores_publish_exact_trees_and_reuse_same_receipts(
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
    dependency_root.mkdir(mode=0o700)
    plugin_root.mkdir(mode=0o700)
    transfer = PackageVerifiedTreeTransferOwner()
    dependencies = PosixPackageDependencyMaterializationStore(
        dependency_root,
        store_identity="dependency-store",
        transfer=transfer,
    )
    plugins = PosixPackagePluginRootMaterializationStore(
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


def test_posix_store_rejects_precreated_staging_namespace_without_writing(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    staging = root / f"staging-{request.staging_request_id}"
    staging.mkdir(mode=0o700)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"preserve")
    (staging / "payload").symlink_to(outside)
    store = PosixPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
    )

    with pytest.raises(PackagePhysicalStagingError) as raised:
        store.stage_dependency(request, candidate)

    assert raised.value.code == "package_publication_root_untrusted"
    assert outside.read_bytes() == b"preserve"
    assert tuple(root.iterdir()) == (staging,)
    moved = tmp_path / "store-moved"
    root.rename(moved)
    moved.rename(root)


def test_posix_store_rejects_configured_root_replacement_before_opening_sink(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    store = PosixPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
    )
    displaced = tmp_path / "store-displaced"
    root.rename(displaced)
    root.mkdir(mode=0o700)

    with pytest.raises(PackagePhysicalStagingError) as raised:
        store.stage_dependency(request, candidate)

    assert raised.value.code == "package_publication_root_untrusted"
    assert tuple(root.iterdir()) == ()
    root.rmdir()
    displaced.rename(root)
    assert store.stage_dependency(request, candidate).staging_request == request


def test_posix_exact_reuse_rejects_unexpected_sparse_member_without_scanning_it(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    store = PosixPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
    )
    receipt = store.stage_dependency(request, candidate)
    published = root / f"artifact-{receipt.stable_ref.ref_id}"
    unexpected = published / "unexpected-sparse-member"
    descriptor = os.open(unexpected, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.ftruncate(descriptor, 1024 * 1024 * 1024)
    finally:
        os.close(descriptor)

    with pytest.raises(PackagePhysicalStagingError) as raised:
        store.stage_dependency(request, _requests_and_candidates()[1])

    assert raised.value.code == "package_publication_collision"
    assert unexpected.stat().st_size == 1024 * 1024 * 1024


def test_posix_store_does_not_adopt_exact_tree_without_live_owner_evidence(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    first_owner = PosixPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
    )
    first_owner.stage_dependency(request, candidate)
    restarted_without_durable_reuse_proof = PosixPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
    )

    with pytest.raises(PackagePhysicalStagingError) as raised:
        restarted_without_durable_reuse_proof.stage_dependency(
            request,
            _requests_and_candidates()[1],
        )

    assert raised.value.code == "package_publication_collision"


def test_posix_exact_reuse_rejects_new_hardlink_alias(tmp_path: Path) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    store = PosixPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
    )
    receipt = store.stage_dependency(request, candidate)
    published = root / f"artifact-{receipt.stable_ref.ref_id}"
    first_file = next(path for path in published.rglob("*") if path.is_file())
    outside_alias = tmp_path / "outside-hardlink-alias"
    os.link(first_file, outside_alias)

    with pytest.raises(PackagePhysicalStagingError) as raised:
        store.stage_dependency(request, _requests_and_candidates()[1])

    assert raised.value.code == "package_publication_collision"
    outside_alias.unlink()


def test_posix_store_rejects_relative_root_without_using_ambient_cwd() -> None:
    with pytest.raises(PackagePhysicalStagingError) as raised:
        PosixPackageDependencyMaterializationStore(
            Path("relative-store"),
            store_identity="dependency-store",
        )

    assert raised.value.code == "package_publication_root_untrusted"


def test_posix_store_rejects_root_swap_and_releases_every_handle(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    detached = tmp_path / "store-detached"

    def swap_root() -> None:
        root.rename(detached)
        root.mkdir(mode=0o700)

    store = PosixPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        commit_probe=swap_root,
    )

    with pytest.raises(PackagePhysicalStagingError) as raised:
        store.stage_dependency(request, candidate)

    assert raised.value.code == "package_publication_root_untrusted"
    assert tuple(root.iterdir()) == ()
    assert tuple(detached.iterdir()) == ()
    replacement = tmp_path / "store-replacement"
    root.rename(replacement)
    detached.rename(root)
    replacement.rmdir()


def test_posix_store_rejects_ancestor_swap_and_releases_every_handle(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    ancestor = tmp_path / "authority"
    root = ancestor / "store"
    root.mkdir(parents=True, mode=0o700)
    detached = tmp_path / "authority-detached"

    def swap_ancestor() -> None:
        ancestor.rename(detached)
        root.mkdir(parents=True, mode=0o700)

    store = PosixPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        commit_probe=swap_ancestor,
    )

    with pytest.raises(PackagePhysicalStagingError) as raised:
        store.stage_dependency(request, candidate)

    assert raised.value.code == "package_publication_root_untrusted"
    assert tuple(root.iterdir()) == ()
    assert tuple((detached / "store").iterdir()) == ()
    replacement = tmp_path / "authority-replacement"
    ancestor.rename(replacement)
    detached.rename(ancestor)
    (replacement / "store").rmdir()
    replacement.rmdir()


def test_posix_rejection_aborts_partial_tree_and_closes_source_and_store_handles(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    acquired = candidate._acquired
    assert isinstance(acquired, _MemoryAcquired)
    first = candidate.transfer_manifest.entries[0]
    acquired.payloads[first.logical_path] += b"tampered"
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    store = PosixPackageDependencyMaterializationStore(
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
