from __future__ import annotations

import io
import os
import shutil
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle import (
    windows_materialization,
)
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
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging import (
    PackageArtifactStagingRequestV1,
    PackagePluginRootTargetV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreSettlementJournal,
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
    WindowsPackageDependencyReadOnlyStore,
    WindowsPackagePluginRootMaterializationStore,
    WindowsPackagePluginRootReadOnlyStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    windows_rename_at,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-native contract")

OPERATION_ID = "operation-windows-materialization"
REQUEST_FINGERPRINT = "9" * 64
CLASSIFICATION_FINGERPRINT = "8" * 64
ENVIRONMENT_FINGERPRINT = "7" * 64


def test_windows_store_gc_deletes_exact_root_and_replays_absence(
    tmp_path: Path,
) -> None:
    _, _, request, candidate, _, _ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir()
    settlements = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    store = WindowsPackagePluginRootMaterializationStore(
        root,
        store_identity="plugin-revision-store",
        settlement_journal=settlements,
    )
    receipt = store.stage_root(request, candidate)
    (settlement,) = settlements.records()
    assert settlement.receipt == receipt

    result = store.delete_settlement(settlement)
    assert result.disposition == "deleted"
    assert not (root / settlement.final_name).exists()
    assert store.delete_settlement(settlement).disposition == "already_absent"
    assert settlements.is_tombstoned(receipt.stable_ref.ref_id)
    with pytest.raises(PackagePhysicalStagingError):
        store.read_root_file(settlement, "root_plugin/__init__.py", max_bytes=4096)
    with pytest.raises(PackagePhysicalStagingError):
        store.stage_root(request, candidate)


def test_windows_root_store_reads_only_live_exact_settlement_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, request, candidate, _, root_payloads = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir()
    settlements = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    store = WindowsPackagePluginRootMaterializationStore(
        root,
        store_identity="plugin-revision-store",
        settlement_journal=settlements,
    )
    store.stage_root(request, candidate)
    (settlement,) = settlements.records()
    logical_path = "root_plugin/__init__.py"

    assert (
        store.read_root_file(settlement, logical_path, max_bytes=4096)
        == root_payloads[logical_path]
    )
    reopened_journal = PackageStoreSettlementJournal(settlements.path)
    reopened = WindowsPackagePluginRootMaterializationStore(
        root,
        store_identity="plugin-revision-store",
        settlement_journal=reopened_journal,
    )
    assert (
        reopened.read_root_file(settlement, logical_path, max_bytes=4096)
        == root_payloads[logical_path]
    )
    members = tuple((path, len(payload)) for path, payload in root_payloads.items())
    original_events = reopened_journal.read_events
    replay_count = 0

    def counted_events():
        nonlocal replay_count
        replay_count += 1
        return original_events()

    monkeypatch.setattr(reopened_journal, "read_events", counted_events)
    assert reopened.read_root_files(settlement, members) == tuple(
        root_payloads[path] for path, _ in members
    )
    assert replay_count == 1
    with pytest.raises(PackagePhysicalStagingError):
        reopened.read_root_files(settlement, (members[0], members[0]))
    with pytest.raises(PackagePhysicalStagingError):
        reopened.read_root_file(settlement, "../outside", max_bytes=4096)
    with pytest.raises(PackagePhysicalStagingError):
        reopened.read_root_file(settlement, logical_path, max_bytes=4)

    published = root / settlement.final_name / logical_path
    published.write_bytes(b"tampered")
    with pytest.raises(PackagePhysicalStagingError):
        reopened.read_root_file(settlement, logical_path, max_bytes=4096)
    with pytest.raises(PackagePhysicalStagingError):
        reopened.read_root_files(settlement, members)


def test_windows_root_store_adoption_requires_configured_store_and_native_root(
    tmp_path: Path,
) -> None:
    _, _, request, _, _, _ = _requests_and_candidates()
    target = request.root_target
    assert target is not None
    root = tmp_path / "store"
    root.mkdir()
    settlements = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    store = WindowsPackagePluginRootMaterializationStore(
        root,
        store_identity="plugin-revision-store",
        package_store_id="package-store",
        settlement_journal=settlements,
    )
    metadata = root.stat()
    root_identity = sha256(
        canonical_json_bytes(
            {
                "device": metadata.st_dev,
                "fileType": "directory",
                "inode": metadata.st_ino,
                "identityVersion": 1,
            }
        )
    ).hexdigest()
    assert store.authorize_adoption(
        store_id="package-store", current_root_identity=root_identity, target=target
    )
    assert not store.authorize_adoption(
        store_id="another-store", current_root_identity=root_identity, target=target
    )
    assert not store.authorize_adoption(
        store_id="package-store", current_root_identity="0" * 64, target=target
    )
    unbound = WindowsPackagePluginRootMaterializationStore(
        root,
        store_identity="plugin-revision-store",
        settlement_journal=settlements,
    )
    assert not unbound.authorize_adoption(
        store_id="package-store", current_root_identity=root_identity, target=target
    )
    root.rename(tmp_path / "moved-store")
    root.mkdir()
    assert not store.authorize_adoption(
        store_id="package-store", current_root_identity=root_identity, target=target
    )


def test_windows_read_only_root_store_preserves_journals_and_file_bytes(
    tmp_path: Path,
) -> None:
    _, _, request, candidate, _, root_payloads = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir()
    journal = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    writer = WindowsPackagePluginRootMaterializationStore(
        root, store_identity="plugin-revision-store", settlement_journal=journal
    )
    writer.stage_root(request, candidate)
    (settlement,) = journal.records()
    files_before = tuple(
        sorted(
            (str(path.relative_to(tmp_path)), path.read_bytes())
            for path in tmp_path.rglob("*")
            if path.is_file()
        )
    )
    reader = WindowsPackagePluginRootReadOnlyStore(
        root, store_identity="plugin-revision-store", settlement_journal=journal
    )
    logical_path = "root_plugin/__init__.py"
    assert (
        reader.read_root_file(settlement, logical_path, max_bytes=4096)
        == root_payloads[logical_path]
    )
    members = tuple((path, len(payload)) for path, payload in root_payloads.items())
    assert reader.read_root_files(settlement, members) == tuple(
        root_payloads[path] for path, _ in members
    )
    assert files_before == tuple(
        sorted(
            (str(path.relative_to(tmp_path)), path.read_bytes())
            for path in tmp_path.rglob("*")
            if path.is_file()
        )
    )
    assert not hasattr(reader, "delete_settlement")


def test_windows_read_only_dependency_store_binds_settlement_and_bytes(
    tmp_path: Path,
) -> None:
    dependency_request, dependency_candidate, _, _, payloads, _ = (
        _requests_and_candidates()
    )
    root = tmp_path / "dependency-store"
    root.mkdir()
    journal = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    writer = WindowsPackageDependencyMaterializationStore(
        root, store_identity="dependency-store", settlement_journal=journal
    )
    writer.stage_dependency(dependency_request, dependency_candidate)
    (settlement,) = journal.records()
    before = tuple(
        sorted(
            (str(path.relative_to(tmp_path)), path.read_bytes())
            for path in tmp_path.rglob("*")
            if path.is_file()
        )
    )
    reader = WindowsPackageDependencyReadOnlyStore(
        root, store_identity="dependency-store", settlement_journal=journal
    )
    members = tuple((path, len(body)) for path, body in payloads.items())
    assert reader.read_dependency_files(settlement, members) == tuple(
        payloads[path] for path, _ in members
    )
    assert before == tuple(
        sorted(
            (str(path.relative_to(tmp_path)), path.read_bytes())
            for path in tmp_path.rglob("*")
            if path.is_file()
        )
    )
    with pytest.raises(PackagePhysicalStagingError):
        reader.read_dependency_files(settlement, (members[0], members[0]))
    published = root / settlement.final_name / members[0][0]
    published.write_bytes(b"changed")
    with pytest.raises(PackagePhysicalStagingError):
        reader.read_dependency_files(settlement, members)


def test_windows_read_only_root_store_refuses_replaced_root_without_mutation(
    tmp_path: Path,
) -> None:
    _, _, request, candidate, _, _ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir()
    journal = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    writer = WindowsPackagePluginRootMaterializationStore(
        root, store_identity="plugin-revision-store", settlement_journal=journal
    )
    writer.stage_root(request, candidate)
    (settlement,) = journal.records()
    reader = WindowsPackagePluginRootReadOnlyStore(
        root, store_identity="plugin-revision-store", settlement_journal=journal
    )
    before = journal.path.read_bytes()
    root.rename(tmp_path / "moved-store")
    root.mkdir()

    with pytest.raises(PackagePhysicalStagingError) as refused:
        reader.read_root_file(
            settlement, "root_plugin/__init__.py", max_bytes=4096
        )
    assert refused.value.code == "package_publication_root_untrusted"
    assert journal.path.read_bytes() == before


def test_windows_read_only_root_store_refuses_partial_journal_without_repair(
    tmp_path: Path,
) -> None:
    _, _, request, candidate, _, _ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir()
    journal = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    writer = WindowsPackagePluginRootMaterializationStore(
        root, store_identity="plugin-revision-store", settlement_journal=journal
    )
    writer.stage_root(request, candidate)
    (settlement,) = journal.records()
    reader = WindowsPackagePluginRootReadOnlyStore(
        root, store_identity="plugin-revision-store", settlement_journal=journal
    )
    with journal.path.open("ab") as handle:
        handle.write(b'{"partial":')
    before = journal.path.read_bytes()

    with pytest.raises(PackagePhysicalStagingError):
        reader.read_root_file(
            settlement, "root_plugin/__init__.py", max_bytes=4096
        )
    assert journal.path.read_bytes() == before


def test_windows_read_only_root_store_refuses_file_swap_after_tree_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, request, candidate, _, root_payloads = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir()
    journal = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    writer = WindowsPackagePluginRootMaterializationStore(
        root, store_identity="plugin-revision-store", settlement_journal=journal
    )
    writer.stage_root(request, candidate)
    (settlement,) = journal.records()
    reader = WindowsPackagePluginRootReadOnlyStore(
        root, store_identity="plugin-revision-store", settlement_journal=journal
    )
    logical_path = "root_plugin/__init__.py"
    published = root / settlement.final_name / logical_path
    original = windows_materialization._validate_existing_tree

    def swap_after_validation(*args: object, **kwargs: object):
        result = original(*args, **kwargs)
        published.rename(tmp_path / "moved-file")
        published.write_bytes(root_payloads[logical_path])
        return result

    monkeypatch.setattr(
        windows_materialization, "_validate_existing_tree", swap_after_validation
    )
    with pytest.raises(PackagePhysicalStagingError) as refused:
        reader.read_root_file(settlement, logical_path, max_bytes=4096)
    assert refused.value.code == "package_publication_collision"


def test_windows_read_only_root_store_does_not_create_empty_owner_state(
    tmp_path: Path,
) -> None:
    root = tmp_path / "store"
    root.mkdir()
    journal = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")

    WindowsPackagePluginRootReadOnlyStore(
        root, store_identity="plugin-revision-store", settlement_journal=journal
    )

    assert not journal.path.exists()
    assert not journal.path.with_name(f"{journal.path.name}.lock").exists()
    assert not journal.path.with_name(f"{journal.path.name}.owner.lock").exists()


def test_windows_dependency_store_reuses_content_tree_and_ref_wide_tombstone(
    tmp_path: Path,
) -> None:
    first_request, first_candidate, *_ = _requests_and_candidates(
        "operation:windows-shared-first"
    )
    second_request, second_candidate, *_ = _requests_and_candidates(
        "operation:windows-shared-second"
    )
    root = tmp_path / "dependency-store"
    root.mkdir()
    settlements = PackageStoreSettlementJournal(
        tmp_path / "dependency-settlements.jsonl"
    )
    store = WindowsPackageDependencyMaterializationStore(
        root, store_identity="dependency-store", settlement_journal=settlements
    )
    first = store.stage_dependency(first_request, first_candidate)
    second = store.stage_dependency(second_request, second_candidate)
    assert first.stable_ref == second.stable_ref
    assert first != second
    (first_settlement, second_settlement) = settlements.records()
    assert first_settlement.tree_identity == second_settlement.tree_identity
    assert first_settlement.final_name == second_settlement.final_name
    assert len(tuple(root.glob("artifact-*"))) == 1
    assert store.delete_settlement(first_settlement).disposition == "deleted"
    assert store.delete_settlement(second_settlement).disposition == "already_absent"
    assert len(settlements.read_events()) == 3
    assert settlements.is_tombstoned(first.stable_ref.ref_id)
    with pytest.raises(PackagePhysicalStagingError):
        store.stage_dependency(second_request, second_candidate)


def test_windows_dependency_store_refuses_changed_tree_before_alias(
    tmp_path: Path,
) -> None:
    first_request, first_candidate, *_ = _requests_and_candidates(
        "operation:windows-shared-tamper-first"
    )
    second_request, second_candidate, *_ = _requests_and_candidates(
        "operation:windows-shared-tamper-second"
    )
    root = tmp_path / "dependency-store"
    root.mkdir()
    settlements = PackageStoreSettlementJournal(
        tmp_path / "dependency-settlements.jsonl"
    )
    store = WindowsPackageDependencyMaterializationStore(
        root, store_identity="dependency-store", settlement_journal=settlements
    )
    store.stage_dependency(first_request, first_candidate)
    (settlement,) = settlements.records()
    (root / settlement.final_name / "dependency" / "__init__.py").write_bytes(
        b"TAMPERED\n"
    )
    with pytest.raises(PackagePhysicalStagingError):
        store.stage_dependency(second_request, second_candidate)
    assert settlements.records() == (settlement,)


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
    operation_id: str = OPERATION_ID,
) -> VerifiedWheelArtifactV1:
    entries = _entries(payloads)
    return VerifiedWheelArtifactV1(
        operation_id=operation_id,
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


def _requests_and_candidates(
    operation_id: str = OPERATION_ID,
) -> tuple[
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
        operation_id=operation_id,
    )
    root_evidence = _evidence(
        node_id="root",
        distribution="root-plugin",
        version="1.0",
        payloads=root_payloads,
        artifact_digest="6" * 64,
        operation_id=operation_id,
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
        operation_id=operation_id,
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
        operation_id=operation_id,
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


def test_windows_handle_relative_rename_preserves_directory_identity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rooted-rename"
    root.mkdir()
    root_fd = open_windows_directory(root, share_delete=True)
    child_fd = open_windows_directory(
        "staging-object",
        dir_fd=root_fd,
        create_new=True,
        share_delete=True,
    )
    expected = (os.fstat(child_fd).st_dev, os.fstat(child_fd).st_ino)
    os.close(child_fd)
    try:
        windows_rename_at(root_fd, "staging-object", "settled-object")
    finally:
        os.close(root_fd)

    assert not (root / "staging-object").exists()
    assert (root / "settled-object").is_dir()
    settled = (root / "settled-object").stat()
    assert (settled.st_dev, settled.st_ino) == expected


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
        settlement_journal=PackageStoreSettlementJournal(
            tmp_path / "dependency-settlements.jsonl"
        ),
        transfer=transfer,
    )
    plugins = WindowsPackagePluginRootMaterializationStore(
        plugin_root,
        store_identity="plugin-revision-store",
        settlement_journal=PackageStoreSettlementJournal(
            tmp_path / "plugin-settlements.jsonl"
        ),
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
        settlement_journal=PackageStoreSettlementJournal(
            tmp_path / "settlements.jsonl"
        ),
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
        settlement_journal=PackageStoreSettlementJournal(
            tmp_path / "settlements.jsonl"
        ),
        commit_probe=replace_root,
    )

    with pytest.raises(PackagePhysicalStagingError) as raised:
        store.stage_dependency(request, candidate)

    assert raised.value.code == "package_publication_root_untrusted"
    if detached.exists():
        assert tuple(detached.iterdir()) == ()
        if root.exists():
            shutil.rmtree(root)
        detached.rename(root)
    else:
        assert tuple(root.iterdir()) == ()
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
        settlement_journal=PackageStoreSettlementJournal(
            tmp_path / "settlements.jsonl"
        ),
        commit_probe=replace_ancestor,
    )

    with pytest.raises(PackagePhysicalStagingError) as raised:
        store.stage_dependency(request, candidate)

    assert raised.value.code == "package_publication_root_untrusted"
    assert sentinel.read_bytes() == b"preserve"
    if detached.exists():
        assert tuple((detached / "store").iterdir()) == ()
        if ancestor.is_symlink():
            ancestor.unlink()
        detached.rename(ancestor)
    else:
        assert tuple(root.iterdir()) == ()


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
        settlement_journal=PackageStoreSettlementJournal(
            tmp_path / "settlements.jsonl"
        ),
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
        settlement_journal=PackageStoreSettlementJournal(
            tmp_path / "settlements.jsonl"
        ),
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
        settlement_journal=PackageStoreSettlementJournal(
            tmp_path / "settlements.jsonl"
        ),
    )

    with pytest.raises(PackagePhysicalStagingError) as raised:
        store.stage_dependency(request, candidate)

    assert raised.value.code == "package_artifact_identity_changed"
    assert tuple(root.iterdir()) == ()
    moved = tmp_path / "store-moved"
    root.rename(moved)
    moved.rename(root)


def test_windows_store_does_not_adopt_tree_without_settlement_authority(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir()
    first_owner = WindowsPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        settlement_journal=PackageStoreSettlementJournal(
            tmp_path / "first-owner-settlements.jsonl"
        ),
    )
    first_owner.stage_dependency(request, candidate)
    restarted_without_durable_proof = WindowsPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        settlement_journal=PackageStoreSettlementJournal(
            tmp_path / "different-owner-settlements.jsonl"
        ),
    )

    with pytest.raises(PackagePhysicalStagingError) as raised:
        restarted_without_durable_proof.stage_dependency(
            request,
            _requests_and_candidates()[1],
        )

    assert raised.value.code == "package_publication_collision"


def test_windows_store_reuses_exact_tree_after_owner_restart_without_journal_append(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir()
    journal = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    first_owner = WindowsPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        settlement_journal=journal,
    )
    receipt = first_owner.stage_dependency(request, candidate)

    restarted = WindowsPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        settlement_journal=PackageStoreSettlementJournal(journal.path),
    )
    assert restarted.validate_dependency_receipt(receipt) == receipt
    reused = restarted.stage_dependency(request, _requests_and_candidates()[1])

    assert reused == receipt
    assert len(journal.records()) == 1


@pytest.mark.parametrize("role", ["dependency", "root"])
def test_windows_read_validation_keeps_partial_settlement_tail_unchanged(
    tmp_path: Path, role: str,
) -> None:
    dependency_request, dependency_candidate, root_request, root_candidate, *_ = (
        _requests_and_candidates()
    )
    root = tmp_path / "store"
    root.mkdir()
    journal = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    if role == "dependency":
        owner = WindowsPackageDependencyMaterializationStore(
            root, store_identity="dependency-store", settlement_journal=journal
        )
        receipt = owner.stage_dependency(dependency_request, dependency_candidate)
        validate = owner.read_validate_dependency_receipt
    else:
        root_owner = WindowsPackagePluginRootMaterializationStore(
            root, store_identity="plugin-revision-store", settlement_journal=journal
        )
        receipt = root_owner.stage_root(root_request, root_candidate)
        validate = root_owner.read_validate_root_receipt
    before = journal.path.read_bytes()
    assert validate(receipt) == receipt
    assert journal.path.read_bytes() == before

    [settlement] = journal.records()
    file_path = next(
        path for path in (root / settlement.final_name).rglob("*") if path.is_file()
    )
    original_bytes = file_path.read_bytes()
    file_path.write_bytes(b"changed physical Store bytes")
    with pytest.raises(PackagePhysicalStagingError) as changed:
        validate(receipt)
    assert changed.value.code == "package_publication_collision"
    assert journal.path.read_bytes() == before
    file_path.write_bytes(original_bytes)
    assert validate(receipt) == receipt

    with journal.path.open("ab") as output:
        output.write(b'{"partial":')
    incomplete = journal.path.read_bytes()
    with pytest.raises(PackagePhysicalStagingError) as raised:
        validate(receipt)
    assert raised.value.code == "package_publication_root_untrusted"
    assert journal.path.read_bytes() == incomplete


def test_windows_store_recovers_renamed_tree_when_receipt_delivery_is_lost(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir()
    journal = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")

    def lose_receipt() -> None:
        raise RuntimeError("simulated crash after durable namespace settlement")

    interrupted = WindowsPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        settlement_journal=journal,
        receipt_probe=lose_receipt,
    )
    with pytest.raises(PackagePhysicalStagingError) as raised:
        interrupted.stage_dependency(request, candidate)

    assert raised.value.code == "package_publication_root_untrusted"
    (record,) = journal.records()
    assert (root / record.final_name).is_dir()
    recovered = WindowsPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        settlement_journal=PackageStoreSettlementJournal(journal.path),
    ).stage_dependency(request, _requests_and_candidates()[1])
    assert recovered == record.receipt
    assert len(journal.records()) == 1


def test_windows_durable_reuse_rejects_same_bytes_with_different_tree_identity(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir()
    journal = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    first_owner = WindowsPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        settlement_journal=journal,
    )
    receipt = first_owner.stage_dependency(request, candidate)
    published = root / f"artifact-{receipt.stable_ref.ref_id}"
    detached = tmp_path / "detached-published-tree"
    published.rename(detached)
    shutil.copytree(detached, published)

    restarted = WindowsPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        settlement_journal=PackageStoreSettlementJournal(journal.path),
    )
    with pytest.raises(PackagePhysicalStagingError) as raised:
        restarted.validate_dependency_receipt(receipt)

    assert raised.value.code == "package_publication_collision"
    assert len(journal.records()) == 1


def test_windows_settlement_journal_rejects_store_root_rebinding(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir()
    journal = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    WindowsPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        settlement_journal=journal,
    ).stage_dependency(request, candidate)
    displaced = tmp_path / "displaced-store"
    root.rename(displaced)
    root.mkdir()

    with pytest.raises(PackagePhysicalStagingError) as raised:
        WindowsPackageDependencyMaterializationStore(
            root,
            store_identity="dependency-store",
            settlement_journal=PackageStoreSettlementJournal(journal.path),
        )

    assert raised.value.code == "package_publication_root_untrusted"


def test_windows_store_rejects_relative_root_without_ambient_cwd(
    tmp_path: Path,
) -> None:
    with pytest.raises(PackagePhysicalStagingError) as raised:
        WindowsPackageDependencyMaterializationStore(
            Path("relative-store"),
            store_identity="dependency-store",
            settlement_journal=PackageStoreSettlementJournal(
                tmp_path / "settlements.jsonl"
            ),
        )

    assert raised.value.code == "package_publication_root_untrusted"
