from __future__ import annotations

import io
import json
import os
import shutil
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.harness.resources.packages.plugin_lifecycle.posix_materialization as posix_materialization
from loushang.harness.plugin_management.package_gc_binding import (
    PluginPackageGcBindingV1,
    PluginPackageGcClaimV1,
    _binding_id,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcDeletionStartV2,
)
from loushang.harness.plugin_management.package_gc_results import (
    PluginPackageGcResultError,
    PluginPackageGcResultJournal,
)
from loushang.harness.plugin_management.package_gc_target import (
    PluginPackageGcTargetError,
    resolve_plugin_package_gc_root_target,
)
from loushang.harness.plugin_management.records import PluginPackageRevisionRefV1
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    NormalizedPackageRequirementV1,
    ResolvedPackageRequirementV1,
    VerifiedClosurePlanNodeV2,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_admission import (
    package_operation_fingerprint,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    DependencyClosureLockV2,
    PluginRevisionRefV1,
    VerifiedArtifactRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_materialization import (
    PackagePhysicalStagingError,
    PosixPackageDependencyMaterializationStore,
    PosixPackagePluginRootMaterializationStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageDesiredStateCommitRequestV1,
    _desired_request_identity,
    _fingerprint,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging import (
    PackageArtifactStagingRequestV1,
    PackagePluginRootTargetV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_gc import (
    PackageStoreGcResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PACKAGE_STORE_SETTLEMENT_JOURNAL_CODEC,
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

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX-native contract")

OPERATION_ID = "operation-posix-materialization"
REQUEST_FINGERPRINT = "9" * 64
CLASSIFICATION_FINGERPRINT = "8" * 64
ENVIRONMENT_FINGERPRINT = "7" * 64


def test_gc_root_target_requires_exact_handoff_set_and_physical_settlement(
    tmp_path: Path,
) -> None:
    dependency_request, dependency_candidate, request, candidate, _, _ = (
        _requests_and_candidates()
    )
    dependency_root = tmp_path / "dependency-store"
    root = tmp_path / "root-store"
    dependency_root.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    dependency_store = PosixPackageDependencyMaterializationStore(
        dependency_root,
        store_identity="dependency-store",
        settlement_journal=PackageStoreSettlementJournal(
            tmp_path / "dependency-settlements.jsonl"
        ),
    )
    root_settlements = PackageStoreSettlementJournal(
        tmp_path / "root-settlements.jsonl"
    )
    root_store = PosixPackagePluginRootMaterializationStore(
        root,
        store_identity="plugin-revision-store",
        settlement_journal=root_settlements,
    )
    dependency_ref = dependency_store.stage_dependency(
        dependency_request, dependency_candidate
    ).stable_ref
    root_ref = root_store.stage_root(request, candidate).stable_ref
    assert isinstance(dependency_ref, VerifiedArtifactRefV1)
    assert isinstance(root_ref, PluginRevisionRefV1)
    plan = VerifiedClosurePlanV2.create(
        operation_id=request.operation_id,
        attempt_epoch=request.attempt_epoch,
        root_node_id=request.node_id,
        resolution_environment_fingerprint=ENVIRONMENT_FINGERPRINT,
        nodes=(request.plan_node, dependency_request.plan_node),
        max_depth=1,
    )
    assert plan.fingerprint == request.verified_plan_fingerprint
    closure = DependencyClosureLockV2.create(
        plan,
        stable_refs={
            request.node_id: root_ref,
            dependency_request.node_id: dependency_ref,
        },
    )
    committed_sets = PackageCommittedSetJournal(tmp_path / "committed-sets.jsonl")
    committed = committed_sets.publish(
        closure,
        request_fingerprint=REQUEST_FINGERPRINT,
        product_id="coding",
        scope_id="workspace:test",
        installation_id="installation-test",
        plugin_id="plugin-test",
        classification_fingerprint=CLASSIFICATION_FINGERPRINT,
    )
    command_id = "gc-target-install"
    command_fingerprint = sha256(command_id.encode()).hexdigest()
    operation_fingerprint = package_operation_fingerprint(
        request.operation_id, REQUEST_FINGERPRINT
    )
    identity = _desired_request_identity(
        command_id=command_id,
        command_fingerprint=command_fingerprint,
        expected_inventory_revision=0,
        operation_id=request.operation_id,
        operation_fingerprint=operation_fingerprint,
        request_fingerprint=REQUEST_FINGERPRINT,
        attempt_epoch=request.attempt_epoch,
        product_id="coding",
        scope_id="workspace:test",
        installation_id="installation-test",
        plugin_id="plugin-test",
        committed_set_id=committed.set_id,
        root_ref=root_ref,
        request_version=1,
    )
    desired_request = PackageDesiredStateCommitRequestV1(
        desired_request_id=_fingerprint(identity),
        command_id=command_id,
        command_fingerprint=command_fingerprint,
        expected_inventory_revision=0,
        operation_id=request.operation_id,
        operation_fingerprint=operation_fingerprint,
        request_fingerprint=REQUEST_FINGERPRINT,
        attempt_epoch=request.attempt_epoch,
        product_id="coding",
        scope_id="workspace:test",
        installation_id="installation-test",
        plugin_id="plugin-test",
        committed_set_id=committed.set_id,
        root_ref=root_ref,
    )
    package_revision = PluginPackageRevisionRefV1(
        plugin_id="plugin-test",
        plugin_version=root_ref.version,
        package_content_digest=root_ref.artifact_digest,
        dependency_lock_digest=closure.lock_digest,
        package_source_identity=request.plan_node.canonical_source_identity,
    )
    binding = PluginPackageGcBindingV1(
        record_revision=1,
        binding_id=_binding_id(desired_request, package_revision, 1),
        request=desired_request,
        package_revision=package_revision,
        desired_transition_revision=1,
    )
    claim = PluginPackageGcClaimV1.create(
        record_revision=1,
        request=desired_request,
        package_revision=package_revision,
    )
    sets = committed_sets.records()
    settlements = root_settlements.records()
    target = resolve_plugin_package_gc_root_target(
        package_revision,
        bindings=(binding,),
        claims=(claim,),
        committed_sets=sets,
        settlements=settlements,
    )
    assert target.settlement_id == settlements[0].settlement_id
    assert target.claim == claim

    for evidence, expected_code in (
        ({"bindings": ()}, "plugin_package_gc_binding_unavailable"),
        ({"claims": ()}, "plugin_package_gc_claim_unavailable"),
        ({"committed_sets": ()}, "plugin_package_gc_set_unavailable"),
        ({"settlements": ()}, "plugin_package_gc_settlement_unavailable"),
        (
            {"settlements": (settlements[0], settlements[0])},
            "plugin_package_gc_settlement_unavailable",
        ),
    ):
        with pytest.raises(PluginPackageGcTargetError) as caught:
            resolve_plugin_package_gc_root_target(
                package_revision,
                bindings=evidence.get("bindings", (binding,)),
                claims=evidence.get("claims", (claim,)),
                committed_sets=evidence.get("committed_sets", sets),
                settlements=evidence.get("settlements", settlements),
            )
        assert caught.value.code == expected_code

    mismatched = replace(package_revision, package_source_identity="other-source")
    alias = PluginPackageGcBindingV1(
        record_revision=2,
        binding_id=_binding_id(desired_request, mismatched, 1),
        request=desired_request,
        package_revision=mismatched,
        desired_transition_revision=1,
    )
    with pytest.raises(PluginPackageGcTargetError) as aliased:
        resolve_plugin_package_gc_root_target(
            package_revision,
            bindings=(binding, alias),
            claims=(claim,),
            committed_sets=sets,
            settlements=settlements,
        )
    assert aliased.value.code == "plugin_package_gc_root_aliased"
    alias_command_id = "gc-target-pending-alias"
    alias_fingerprint = sha256(alias_command_id.encode()).hexdigest()
    alias_identity = _desired_request_identity(
        command_id=alias_command_id,
        command_fingerprint=alias_fingerprint,
        expected_inventory_revision=1,
        operation_id=request.operation_id,
        operation_fingerprint=operation_fingerprint,
        request_fingerprint=REQUEST_FINGERPRINT,
        attempt_epoch=request.attempt_epoch,
        product_id="coding",
        scope_id="workspace:test",
        installation_id="installation-test",
        plugin_id="plugin-test",
        committed_set_id=committed.set_id,
        root_ref=root_ref,
        request_version=1,
    )
    pending_request = replace(
        desired_request,
        desired_request_id=_fingerprint(alias_identity),
        command_id=alias_command_id,
        command_fingerprint=alias_fingerprint,
        expected_inventory_revision=1,
    )
    pending_claim = PluginPackageGcClaimV1.create(
        record_revision=2,
        request=pending_request,
        package_revision=mismatched,
    )
    with pytest.raises(PluginPackageGcTargetError) as pending_alias:
        resolve_plugin_package_gc_root_target(
            package_revision,
            bindings=(binding,),
            claims=(claim, pending_claim),
            committed_sets=sets,
            settlements=settlements,
        )
    assert pending_alias.value.code == "plugin_package_gc_root_aliased"
    with pytest.raises(PluginPackageGcTargetError) as source_changed:
        resolve_plugin_package_gc_root_target(
            mismatched,
            bindings=(alias,),
            claims=(PluginPackageGcClaimV1.create(
                record_revision=1,
                request=desired_request,
                package_revision=mismatched,
            ),),
            committed_sets=sets,
            settlements=settlements,
        )
    assert source_changed.value.code == "plugin_package_gc_set_mismatch"


def test_posix_store_gc_deletes_only_recorded_root_and_replays_absence(
    tmp_path: Path,
) -> None:
    dependency_request, dependency_candidate, request, candidate, _, _ = (
        _requests_and_candidates()
    )
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    settlements = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    store = PosixPackagePluginRootMaterializationStore(
        root,
        store_identity="plugin-revision-store",
        settlement_journal=settlements,
    )
    receipt = store.stage_root(request, candidate)
    (settlement,) = settlements.records()
    assert settlement.receipt == receipt

    result = store._store.delete_settlement(settlement)
    assert result.disposition == "deleted"
    assert result.stable_ref_id == receipt.stable_ref.ref_id
    assert not (root / settlement.final_name).exists()
    replay = store._store.delete_settlement(settlement)
    assert replay.disposition == "already_absent"
    assert settlements.is_tombstoned(receipt.stable_ref.ref_id)
    marker = json.loads(settlements.path.read_text(encoding="utf-8").splitlines()[-1])
    with pytest.raises(ValueError):
        PACKAGE_STORE_SETTLEMENT_JOURNAL_CODEC.decode_record(marker)
    with pytest.raises(PackagePhysicalStagingError):
        store.stage_root(request, candidate)
    restarted = PosixPackagePluginRootMaterializationStore(
        root,
        store_identity="plugin-revision-store",
        settlement_journal=PackageStoreSettlementJournal(settlements.path),
    )
    with pytest.raises(PackagePhysicalStagingError):
        restarted.stage_root(request, candidate)

    dependency_root = tmp_path / "dependency-store"
    dependency_root.mkdir(mode=0o700)
    other_store = PosixPackageDependencyMaterializationStore(
        dependency_root,
        store_identity="dependency-store",
        settlement_journal=PackageStoreSettlementJournal(settlements.path),
    )
    other_store.stage_dependency(dependency_request, dependency_candidate)
    assert len(settlements.records()) == 2


def test_store_gc_result_debt_replays_and_success_is_terminal(tmp_path: Path) -> None:
    _, _, request, candidate, _, _ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    settlements = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    store = PosixPackagePluginRootMaterializationStore(
        root,
        store_identity="plugin-revision-store",
        settlement_journal=settlements,
    )
    store.stage_root(request, candidate)
    (settlement,) = settlements.records()
    start = PluginPackageGcDeletionStartV2(
        journal_revision=1,
        reservation_id="a" * 64,
        operation_id="gc-delete-start",
        idempotency_key="gc-delete-start-request",
        target_settlement_ids=(settlement.settlement_id,),
    )
    journal = PluginPackageGcResultJournal(tmp_path / "gc-results.jsonl")
    failed = journal.record(
        start,
        settlement=settlement,
        operation_id="gc-attempt-1",
        idempotency_key="gc-attempt-1-request",
        error_code="store.transient_failure",
    )
    assert failed.disposition == "retryable_failure"
    reopened = PluginPackageGcResultJournal(journal.path)
    assert reopened.attempts(start) == (failed,)
    with pytest.raises(PluginPackageGcResultError) as wrong_start:
        reopened.attempts(replace(start, operation_id="different-deletion-start"))
    assert wrong_start.value.code == "plugin_package_gc_result_conflict"
    with pytest.raises(PluginPackageGcResultError) as reused_key:
        reopened.record(
            start,
            settlement=settlement,
            operation_id="gc-attempt-conflicting",
            idempotency_key="gc-attempt-1-request",
            error_code="store.other_failure",
        )
    assert reused_key.value.code == "plugin_package_gc_result_conflict"

    store._store.delete_settlement(settlement)
    result = store._store.delete_settlement(settlement)
    assert result.disposition == "already_absent"
    succeeded = reopened.record(
        start,
        settlement=settlement,
        operation_id="gc-attempt-2",
        idempotency_key="gc-attempt-2-request",
        store_result=result,
    )
    assert succeeded.disposition == "succeeded"
    assert PluginPackageGcResultJournal(journal.path).attempts(start) == (
        failed,
        succeeded,
    )
    assert reopened.record(
        start,
        settlement=settlement,
        operation_id="gc-attempt-2",
        idempotency_key="gc-attempt-2-request",
        store_result=result,
    ) == succeeded
    with pytest.raises(PluginPackageGcResultError) as terminal:
        reopened.record(
            start,
            settlement=settlement,
            operation_id="gc-attempt-3",
            idempotency_key="gc-attempt-3-request",
            error_code="store.retry_after_success",
        )
    assert terminal.value.code == "plugin_package_gc_result_terminal"


def test_store_gc_result_refuses_a_different_store_identity(tmp_path: Path) -> None:
    _, _, request, candidate, _, _ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    settlements = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    store = PosixPackagePluginRootMaterializationStore(
        root,
        store_identity="plugin-revision-store",
        settlement_journal=settlements,
    )
    store.stage_root(request, candidate)
    (settlement,) = settlements.records()
    start = PluginPackageGcDeletionStartV2(
        journal_revision=1,
        reservation_id="a" * 64,
        operation_id="gc-delete-start",
        idempotency_key="gc-delete-start-request",
        target_settlement_ids=(settlement.settlement_id,),
    )
    other_store_result = PackageStoreGcResultV1.create(
        SimpleNamespace(
            settlement_id=settlement.settlement_id,
            store_identity="other-store",
            receipt=settlement.receipt,
            tree_identity=settlement.tree_identity,
        ),
        disposition="deleted",
    )
    journal = PluginPackageGcResultJournal(tmp_path / "gc-results.jsonl")
    with pytest.raises(PluginPackageGcResultError) as mismatch:
        journal.record(
            start,
            settlement=settlement,
            operation_id="gc-attempt-1",
            idempotency_key="gc-attempt-1-request",
            store_result=other_store_result,
        )
    assert mismatch.value.code == "plugin_package_gc_result_mismatch"
    assert journal.attempts(start) == ()


def test_posix_store_gc_refuses_replaced_tree_without_touching_outside(
    tmp_path: Path,
) -> None:
    _, _, request, candidate, _, _ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    settlements = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    store = PosixPackagePluginRootMaterializationStore(
        root,
        store_identity="plugin-revision-store",
        settlement_journal=settlements,
    )
    store.stage_root(request, candidate)
    (settlement,) = settlements.records()
    published = root / settlement.final_name
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"preserve")
    published.chmod(0o700)
    victim = published / settlement.file_identities[0].logical_path
    victim.unlink()
    victim.symlink_to(outside)

    with pytest.raises(PackagePhysicalStagingError) as collision:
        store._store.delete_settlement(settlement)
    assert collision.value.retryable is False
    assert outside.read_bytes() == b"preserve"
    assert published.is_dir()
    start = PluginPackageGcDeletionStartV2(
        journal_revision=1,
        reservation_id="a" * 64,
        operation_id="gc-delete-start",
        idempotency_key="gc-delete-start-request",
        target_settlement_ids=(settlement.settlement_id,),
    )
    journal = PluginPackageGcResultJournal(tmp_path / "gc-results.jsonl")
    debt = journal.record(
        start,
        settlement=settlement,
        operation_id="gc-attempt-1",
        idempotency_key="gc-attempt-1-request",
        error_code=collision.value.code,
        terminal=True,
    )
    assert debt.disposition == "terminal_failure"
    assert PluginPackageGcResultJournal(journal.path).attempts(start) == (debt,)
    with pytest.raises(PluginPackageGcResultError) as blocked:
        journal.record(
            start,
            settlement=settlement,
            operation_id="gc-attempt-2",
            idempotency_key="gc-attempt-2-request",
            error_code="store.retry_without_repair",
        )
    assert blocked.value.code == "plugin_package_gc_result_terminal"


def test_posix_store_gc_retries_after_partial_file_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, request, candidate, _, _ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    settlements = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    store = PosixPackagePluginRootMaterializationStore(
        root,
        store_identity="plugin-revision-store",
        settlement_journal=settlements,
    )
    store.stage_root(request, candidate)
    (settlement,) = settlements.records()
    unlink = posix_materialization.os.unlink
    failed = False

    def fail_after_one_unlink(path: str, *, dir_fd: int) -> None:
        nonlocal failed
        unlink(path, dir_fd=dir_fd)
        if not failed:
            failed = True
            raise OSError("injected partial deletion")

    monkeypatch.setattr(posix_materialization.os, "unlink", fail_after_one_unlink)
    with pytest.raises(PackagePhysicalStagingError):
        store._store.delete_settlement(settlement)
    monkeypatch.setattr(posix_materialization.os, "unlink", unlink)
    assert failed
    assert store._store.delete_settlement(settlement).disposition == "deleted"
    assert not (root / settlement.final_name).exists()


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
        settlement_journal=PackageStoreSettlementJournal(
            tmp_path / "dependency-settlements.jsonl"
        ),
        transfer=transfer,
    )
    plugins = PosixPackagePluginRootMaterializationStore(
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
        settlement_journal=PackageStoreSettlementJournal(
            tmp_path / "settlements.jsonl"
        ),
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
        settlement_journal=PackageStoreSettlementJournal(
            tmp_path / "settlements.jsonl"
        ),
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
        settlement_journal=PackageStoreSettlementJournal(
            tmp_path / "settlements.jsonl"
        ),
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


def test_posix_store_does_not_adopt_exact_tree_without_settlement_authority(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    first_owner = PosixPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        settlement_journal=PackageStoreSettlementJournal(
            tmp_path / "first-owner-settlements.jsonl"
        ),
    )
    first_owner.stage_dependency(request, candidate)
    restarted_without_durable_reuse_proof = PosixPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        settlement_journal=PackageStoreSettlementJournal(
            tmp_path / "different-owner-settlements.jsonl"
        ),
    )

    with pytest.raises(PackagePhysicalStagingError) as raised:
        restarted_without_durable_reuse_proof.stage_dependency(
            request,
            _requests_and_candidates()[1],
        )

    assert raised.value.code == "package_publication_collision"


def test_posix_store_reuses_exact_tree_after_owner_restart_without_journal_append(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    journal = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    first_owner = PosixPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        settlement_journal=journal,
    )
    receipt = first_owner.stage_dependency(request, candidate)

    restarted = PosixPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        settlement_journal=PackageStoreSettlementJournal(journal.path),
    )
    assert restarted.validate_dependency_receipt(receipt) == receipt
    reused = restarted.stage_dependency(request, _requests_and_candidates()[1])

    assert reused == receipt
    assert len(journal.records()) == 1


def test_posix_store_recovers_renamed_tree_when_receipt_delivery_is_lost(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    journal = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")

    def lose_receipt() -> None:
        raise RuntimeError("simulated crash after durable namespace settlement")

    interrupted = PosixPackageDependencyMaterializationStore(
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
    recovered = PosixPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        settlement_journal=PackageStoreSettlementJournal(journal.path),
    ).stage_dependency(request, _requests_and_candidates()[1])
    assert recovered == record.receipt
    assert len(journal.records()) == 1


def test_posix_atomic_rename_rejects_foreign_final_created_after_precheck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, request, candidate, _, _ = _requests_and_candidates()
    root = tmp_path / "plugin-store"
    root.mkdir(mode=0o700)
    settlements = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    original = posix_materialization._rename_directory_noreplace

    def race(
        source_directory_fd: int,
        source_name: str,
        target_directory_fd: int,
        target_name: str,
    ) -> None:
        os.mkdir(target_name, mode=0o700, dir_fd=target_directory_fd)
        original(
            source_directory_fd,
            source_name,
            target_directory_fd,
            target_name,
        )

    monkeypatch.setattr(posix_materialization, "_rename_directory_noreplace", race)
    store = PosixPackagePluginRootMaterializationStore(
        root,
        store_identity="plugin-revision-store",
        settlement_journal=settlements,
    )

    with pytest.raises(PackagePhysicalStagingError) as raised:
        store.stage_root(request, candidate)

    assert raised.value.code == "package_publication_collision"
    (record,) = settlements.records()
    assert {entry.name for entry in root.iterdir()} == {record.final_name}
    assert list((root / record.final_name).iterdir()) == []
    (root / record.final_name).rmdir()
    monkeypatch.undo()

    restarted = PosixPackagePluginRootMaterializationStore(
        root,
        store_identity="plugin-revision-store",
        settlement_journal=PackageStoreSettlementJournal(settlements.path),
    )
    receipt = restarted.stage_root(request, _requests_and_candidates()[3])
    assert restarted.validate_root_receipt(receipt) == receipt
    records = settlements.records()
    assert len(records) in {1, 2}
    assert all(recorded.receipt == receipt for recorded in records)
    if len(records) == 2:
        assert records[0].tree_identity != records[1].tree_identity
    else:
        assert records[0].tree_identity.to_native() == (
            (root / records[0].final_name).stat().st_dev,
            (root / records[0].final_name).stat().st_ino,
        )


def test_posix_durable_reuse_rejects_same_bytes_with_different_tree_identity(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    journal = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    first_owner = PosixPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        settlement_journal=journal,
    )
    receipt = first_owner.stage_dependency(request, candidate)
    published = root / f"artifact-{receipt.stable_ref.ref_id}"
    detached = tmp_path / "detached-published-tree"
    published.rename(detached)
    shutil.copytree(detached, published)

    restarted = PosixPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        settlement_journal=PackageStoreSettlementJournal(journal.path),
    )
    with pytest.raises(PackagePhysicalStagingError) as raised:
        restarted.validate_dependency_receipt(receipt)

    assert raised.value.code == "package_publication_collision"
    assert len(journal.records()) == 1


def test_posix_settlement_journal_rejects_store_root_rebinding(
    tmp_path: Path,
) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    journal = PackageStoreSettlementJournal(tmp_path / "settlements.jsonl")
    PosixPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        settlement_journal=journal,
    ).stage_dependency(request, candidate)
    displaced = tmp_path / "displaced-store"
    root.rename(displaced)
    root.mkdir(mode=0o700)

    with pytest.raises(PackagePhysicalStagingError) as raised:
        PosixPackageDependencyMaterializationStore(
            root,
            store_identity="dependency-store",
            settlement_journal=PackageStoreSettlementJournal(journal.path),
        )

    assert raised.value.code == "package_publication_root_untrusted"


def test_posix_exact_reuse_rejects_new_hardlink_alias(tmp_path: Path) -> None:
    request, candidate, *_ = _requests_and_candidates()
    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    store = PosixPackageDependencyMaterializationStore(
        root,
        store_identity="dependency-store",
        settlement_journal=PackageStoreSettlementJournal(
            tmp_path / "settlements.jsonl"
        ),
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


def test_posix_store_rejects_relative_root_without_using_ambient_cwd(
    tmp_path: Path,
) -> None:
    with pytest.raises(PackagePhysicalStagingError) as raised:
        PosixPackageDependencyMaterializationStore(
            Path("relative-store"),
            store_identity="dependency-store",
            settlement_journal=PackageStoreSettlementJournal(
                tmp_path / "settlements.jsonl"
            ),
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
        settlement_journal=PackageStoreSettlementJournal(
            tmp_path / "settlements.jsonl"
        ),
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
        settlement_journal=PackageStoreSettlementJournal(
            tmp_path / "settlements.jsonl"
        ),
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
