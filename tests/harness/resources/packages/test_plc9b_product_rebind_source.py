from __future__ import annotations

import os
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.harness.journal import journal_file_lock
from loushang.harness.package_product.product_pinned_adoption import (
    PackageProductPinnedAdoptionOwner,
)
from loushang.harness.package_product.product_rebind_cleanup import (
    PackageProductRebindCleanupReader,
    PackageProductRebindCleanupReadError,
)
from loushang.harness.package_product.product_rebind_decision import (
    PackageProductRebindDecisionError,
    PackageProductRebindDecisionOwner,
)
from loushang.harness.package_product.product_rebind_lease import (
    PackageProductRebindLeaseReader,
    PackageProductRebindLeaseReadError,
)
from loushang.harness.package_product.product_rebind_preflight import (
    PackageProductAcquiredRebindPreflightError,
    PackageProductAcquiredRebindPreflightV1,
    PackageProductPinnedRebindPreflightV1,
    PackageProductResolvingRebindPreflightV1,
)
from loushang.harness.package_product.product_rebind_source import (
    PackageProductRebindSourceReader,
    PackageProductRebindSourceReadError,
)
from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    BoundedAcquisitionReceiptV1,
    PackageAcquisitionBudgetV1,
    PackageAcquisitionOwner,
    PackageAcquisitionRequestV1,
    PackageQuarantineCleanupTargetV1,
    PackageQuarantineStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.cleanup import (
    PackageQuarantineCleanupJournal,
    PackageQuarantineCleanupOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    NormalizedPackageRequirementV1,
    PackageClosureBudgetV1,
    PackageResolutionEnvironmentV1,
    ResolvedPackageRequirementV1,
    VerifiedClosurePlanNodeV2,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_journal import (
    PackageClosureResolutionBasisV1,
    PackageClosureResolutionJournal,
    PackageClosureResolutionJournalError,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    PackageDependencySelectionRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceReceiptV1,
    PackageEpochFenceRequestV1,
    PackageEpochLeaseSnapshotV1,
    PackageEpochRuntimeAdmissionReceiptV1,
    PackageEpochRuntimeAdmissionRequestV1,
    PackageEpochRuntimeLeaseV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.owner import (
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.phase_evidence import (
    PackageArtifactEvidenceJournal,
    PackageArtifactEvidenceJournalError,
    PackageAuthenticatedSourceEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleIngressRequestV2,
    PackageLifecycleRebindRequestV1,
    PackageLifecycleRequestV2,
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageRetentionHandoffJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging import (
    PackageArtifactStagingJournal,
    PackageArtifactStagingJournalError,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinJournal,
    PackageTransactionPinJournalError,
    PackageTransactionPinReceiptV1,
    PackageTransactionPinRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    VerifiedWheelArtifactV1,
)
from loushang.harness.resources.packages.product_admission_binding import (
    PackageProductAdmissionBindingJournal,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleIntentV1,
)
from loushang.harness.resources.packages.product_lifecycle import (
    PackageProductRouteContractError,
    require_rebound_decision,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
    PackageProductLocalWheelDependencyV1,
    PackageProductLocalWheelPolicy,
    PackageProductRebindSourceError,
)
from loushang.harness.resources.packages.product_pinned_adoption_binding import (
    PackageProductPinnedAdoptionBindingJournal,
)
from loushang.harness.resources.packages.product_rebind_admission_binding import (
    PackageProductRebindAdmissionBindingJournal,
)


def _environment() -> PackageResolutionEnvironmentV1:
    return PackageResolutionEnvironmentV1.from_mapping(
        {
            "implementation_name": "cpython",
            "implementation_version": "3.11.10",
            "os_name": "posix",
            "platform_machine": "x86_64",
            "platform_python_implementation": "CPython",
            "platform_release": "fixture",
            "platform_system": "Linux",
            "platform_version": "fixture",
            "python_full_version": "3.11.10",
            "python_version": "3.11",
            "sys_platform": "linux",
        },
        supported_tags=("py3-none-any",),
    )


def _fixture(tmp_path: Path, *, original_admission_request_id: str = "f" * 64):
    source_root = tmp_path / "sources"
    source_root.mkdir(mode=0o700)
    root = source_root / "acme_plugin-1.0-py3-none-any.whl"
    dependency = source_root / "helper-2.0-py3-none-any.whl"
    root.write_bytes(b"root-wheel")
    dependency.write_bytes(b"dependency-wheel")
    environment = _environment()
    policy = PackageProductLocalWheelPolicy(
        product_id="coding",
        project_scope_id="workspace:test",
        source_root=source_root,
        bindings=(
            PackageProductLocalWheelBindingV1(
                source_identity=str(root),
                requested_package="acme-plugin==1.0",
                plugin_id="acme.plugin",
                artifact_digest=sha256(root.read_bytes()).hexdigest(),
            ),
        ),
        dependencies=(
            PackageProductLocalWheelDependencyV1(
                source_identity=str(dependency),
                project_name="helper",
                version="2.0",
                artifact_digest=sha256(dependency.read_bytes()).hexdigest(),
            ),
        ),
        policy_revision="source-policy:1",
        quota_profile_revision="quota:1",
        resolution_environment_fingerprint=environment.fingerprint,
        authority_id="source-authority:test",
    )
    lifecycle = PackageLifecycleJournal(tmp_path / "lifecycle.jsonl")
    resolution = PackageClosureResolutionJournal(tmp_path / "resolution.jsonl")
    owner = PackageLifecycleOwner(
        journal=lifecycle, classification_authority=policy, enabled=True
    )
    ingress = PackageLifecycleIngressRequestV2.bind_runtime_admission(
        policy.create(
            PackageProductLifecycleIntentV1(
                operation_id="operation:read-proof",
                action="install",
                source=str(root),
                scope="project",
            )
        ),
        runtime_admission_request_id=original_admission_request_id,
    )
    classified = owner.submit(ingress)
    return policy, owner, lifecycle, resolution, environment, classified, dependency


def _admission(runtime_id: str) -> PackageEpochRuntimeAdmissionReceiptV1:
    fence = PackageEpochFenceReceiptV1.create(
        PackageEpochFenceRequestV1.create(
            store_id="package-store:test",
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
    lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id=runtime_id,
        runtime_epoch=fence.epoch,
        store_root_identity=fence.fenced_root_identity,
        registration_receipt_id="7" * 64,
    )
    request = PackageEpochRuntimeAdmissionRequestV1.create(
        fence=fence,
        runtime_id=runtime_id,
        runtime_version="1.0.0",
        runtime_protocol_epoch=1,
        runtime_epoch=fence.epoch,
        store_root_identity=fence.fenced_root_identity,
        lease_id=lease.lease_id,
    )
    return PackageEpochRuntimeAdmissionReceiptV1.create(
        request,
        snapshot=PackageEpochLeaseSnapshotV1.create(
            store_id=fence.store_id,
            owner_revision=1,
            active_leases=(lease,),
        ),
    )


@dataclass
class _Snapshots:
    value: PackageEpochLeaseSnapshotV1

    def snapshot(self, *, store_id: str) -> PackageEpochLeaseSnapshotV1:
        assert store_id == self.value.store_id
        return self.value


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-relative proof")
def test_product_rebind_decision_prepares_replays_and_supersedes_exact_lease(
    tmp_path: Path,
) -> None:
    old = _admission("runtime:old")
    new = _admission("runtime:new")
    third = _admission("runtime:third")
    policy, owner, lifecycle, resolution, _environment, classified, _dependency = (
        _fixture(
            tmp_path,
            original_admission_request_id=old.request.admission_request_id,
        )
    )
    failed = owner.interrupt(
        classified.operation_id,
        expected_phase=classified.phase,
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
    )
    original = lifecycle.read_operation(failed.operation_id)
    assert original is not None
    assert isinstance(original[0], PackageLifecycleRequestV2)
    bindings = PackageProductAdmissionBindingJournal(tmp_path / "admissions.jsonl")
    bindings.bind(original[0], failed, old)
    proposals = PackageProductRebindAdmissionBindingJournal(
        tmp_path / "rebind-admissions.jsonl"
    )
    artifacts = PackageArtifactEvidenceJournal(tmp_path / "artifacts.jsonl")
    quarantine = PackageQuarantineStore(tmp_path / "quarantine")
    cleanup_owner = PackageQuarantineCleanupOwner(
        journal=PackageQuarantineCleanupJournal(tmp_path / "cleanup.jsonl"),
        store=quarantine,
    )
    cleanup = PackageProductRebindCleanupReader(
        lifecycle=lifecycle,
        resolution=resolution,
        artifacts=artifacts,
        cleanup=cleanup_owner,
        quarantine=quarantine,
        pins=PackageTransactionPinJournal(tmp_path / "pins.jsonl"),
        staging=PackageArtifactStagingJournal(tmp_path / "staging.jsonl"),
        committed_sets=PackageCommittedSetJournal(tmp_path / "committed-sets.jsonl"),
        handoff=PackageRetentionHandoffJournal(tmp_path / "handoff.jsonl"),
    )
    source = PackageProductRebindSourceReader(
        policy=policy, lifecycle=lifecycle, resolution=resolution
    )
    new_lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id=new.request.runtime_id,
        runtime_epoch=new.request.runtime_epoch,
        store_root_identity=new.request.store_root_identity,
        registration_receipt_id="7" * 64,
    )
    snapshots = _Snapshots(
        PackageEpochLeaseSnapshotV1.create(
            store_id=new.request.store_id,
            owner_revision=2,
            active_leases=(new_lease,),
        )
    )

    def decision_owner(
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> PackageProductRebindDecisionOwner:
        return PackageProductRebindDecisionOwner(
            lifecycle=lifecycle,
            source=source,
            lease=PackageProductRebindLeaseReader(
                lifecycle=lifecycle,
                original_bindings=bindings,
                proposed_bindings=proposals,
                snapshots=snapshots,
                current_admission_request=admission.request,
            ),
            cleanup=cleanup,
            quarantine_cleanup=cleanup_owner,
            proposals=proposals,
        )

    first = decision_owner(new).prepare(
        failed.operation_id, max_bytes=1024, admission=new
    )
    assert first.decision.new_runtime_admission_request_id == (
        new.request.admission_request_id
    )
    assert proposals.read_decision(first.decision.decision_id) is not None
    before_replay = lifecycle.path.read_bytes()
    assert (
        decision_owner(new).prepare(failed.operation_id, max_bytes=1024, admission=new)
        == first
    )
    assert lifecycle.path.read_bytes() == before_replay
    root = Path(policy.bindings[0].source_identity)
    root.write_bytes(b"changed-root-wheel")
    with pytest.raises(PackageProductRebindSourceError) as changed_source:
        decision_owner(new).prepare(failed.operation_id, max_bytes=1024, admission=new)
    assert changed_source.value.code == "package_source_digest_mismatch"
    assert lifecycle.path.read_bytes() == before_replay
    root.write_bytes(b"root-wheel")

    third_lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id=third.request.runtime_id,
        runtime_epoch=third.request.runtime_epoch,
        store_root_identity=third.request.store_root_identity,
        registration_receipt_id="7" * 64,
    )
    snapshots.value = PackageEpochLeaseSnapshotV1.create(
        store_id=third.request.store_id,
        owner_revision=3,
        active_leases=(new_lease, third_lease),
    )
    with pytest.raises(PackageProductRebindLeaseReadError) as prior_live:
        decision_owner(third).prepare(
            failed.operation_id, max_bytes=1024, admission=third
        )
    assert prior_live.value.code == "package_rebind_prior_lease_active"
    assert proposals.read_operation(failed.operation_id) == (
        proposals.read_decision(first.decision.decision_id),
    )
    snapshots.value = PackageEpochLeaseSnapshotV1.create(
        store_id=third.request.store_id,
        owner_revision=4,
        active_leases=(third_lease,),
    )
    second = decision_owner(third).prepare(
        failed.operation_id, max_bytes=1024, admission=third
    )
    assert second.record_kind == "rebind_supersession"
    assert second.supersedes_decision_id == first.decision.decision_id
    assert second.decision.source_proof_ref == first.decision.source_proof_ref
    assert second.decision.cleanup_evidence_ref == first.decision.cleanup_evidence_ref
    selected_owner = decision_owner(third)
    original_bytes = lifecycle.path.read_bytes()
    root.write_bytes(b"changed-root-wheel")
    with pytest.raises(PackageProductRebindSourceError) as changed_before_resume:
        selected_owner.resume(failed.operation_id, max_bytes=1024, admission=third)
    assert changed_before_resume.value.code == "package_source_digest_mismatch"
    assert lifecycle.path.read_bytes() == original_bytes
    root.write_bytes(b"root-wheel")
    with pytest.raises(PackageProductRebindDecisionError) as wrong_admission:
        selected_owner.resume(failed.operation_id, max_bytes=1024, admission=new)
    assert wrong_admission.value.code == "package_rebind_decision_evidence_changed"
    assert lifecycle.path.read_bytes() == original_bytes
    with pytest.raises(PackageProductRouteContractError) as unauthorized:
        selected_owner.authorize(selected_owner.route(second, third), failed)
    assert unauthorized.value.code == "package_rebind_execution_not_available"
    selected, resumed, route = selected_owner.resume(
        failed.operation_id, max_bytes=1024, admission=third
    )
    assert selected == second
    assert resumed.disposition == "active"
    assert resumed.attempt_epoch == failed.attempt_epoch + 1
    assert route == selected_owner.route(selected, third)
    selected_owner.authorize(route, resumed)
    with pytest.raises(PackageProductRouteContractError) as duplicate_authority:
        selected_owner.authorize(route, resumed)
    assert duplicate_authority.value.code == "package_rebind_execution_not_available"
    selected_owner.revoke(route, resumed)
    after_claim = lifecycle.path.read_bytes()
    fourth = _admission("runtime:fourth")
    with pytest.raises(PackageProductRebindSourceError) as no_implicit_recovery:
        decision_owner(fourth).prepare(
            failed.operation_id, max_bytes=1024, admission=fourth
        )
    assert no_implicit_recovery.value.code == "package_rebind_source_not_retryable"
    assert lifecycle.path.read_bytes() == after_claim
    fourth_lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id=fourth.request.runtime_id,
        runtime_epoch=fourth.request.runtime_epoch,
        store_root_identity=fourth.request.store_root_identity,
        registration_receipt_id="7" * 64,
    )
    snapshots.value = PackageEpochLeaseSnapshotV1.create(
        store_id=fourth.request.store_id,
        owner_revision=5,
        active_leases=(third_lease, fourth_lease),
    )
    fourth_owner = decision_owner(fourth)
    with pytest.raises(PackageProductRebindLeaseReadError) as previous_live:
        fourth_owner.recover_unstarted_claim(
            failed.operation_id, max_bytes=1024, admission=fourth
        )
    assert previous_live.value.code == "package_rebind_prior_lease_active"
    assert lifecycle.path.read_bytes() == after_claim
    snapshots.value = PackageEpochLeaseSnapshotV1.create(
        store_id=fourth.request.store_id,
        owner_revision=6,
        active_leases=(fourth_lease,),
    )
    [attempt_slot] = quarantine.observe_attempts(
        failed.operation_id, resumed.attempt_epoch, ("root",)
    )
    orphan = quarantine.root / attempt_slot.attempt_name
    orphan.mkdir(mode=0o700)
    try:
        with pytest.raises(PackageProductRebindCleanupReadError) as residue:
            fourth_owner.recover_unstarted_claim(
                failed.operation_id, max_bytes=1024, admission=fourth
            )
        assert residue.value.code == "package_rebind_claim_has_effects"
        assert lifecycle.path.read_bytes() == after_claim
    finally:
        orphan.rmdir()
    recovered = fourth_owner.recover_unstarted_claim(
        failed.operation_id, max_bytes=1024, admission=fourth
    )
    assert recovered.disposition == "retryable_failure"
    assert recovered.attempt_epoch == resumed.attempt_epoch
    next_decision = fourth_owner.prepare(
        failed.operation_id, max_bytes=1024, admission=fourth
    )
    assert next_decision.decision.expected_attempt_epoch == recovered.attempt_epoch
    _selected, next_claim, _route = fourth_owner.resume(
        failed.operation_id, max_bytes=1024, admission=fourth
    )
    acquiring = owner.advance(
        failed.operation_id,
        next_phase="acquiring",
        expected_phase=next_claim.phase,
        expected_journal_revision=next_claim.journal_revision,
        expected_attempt_epoch=next_claim.attempt_epoch,
    )
    fifth = _admission("runtime:fifth")
    fifth_lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id=fifth.request.runtime_id,
        runtime_epoch=fifth.request.runtime_epoch,
        store_root_identity=fifth.request.store_root_identity,
        registration_receipt_id="7" * 64,
    )
    snapshots.value = PackageEpochLeaseSnapshotV1.create(
        store_id=fifth.request.store_id,
        owner_revision=7,
        active_leases=(fifth_lease,),
    )
    advanced_bytes = lifecycle.path.read_bytes()
    [acquiring_slot] = quarantine.observe_attempts(
        failed.operation_id, acquiring.attempt_epoch, ("root",)
    )
    acquiring_orphan = quarantine.root / acquiring_slot.attempt_name
    acquiring_orphan.mkdir(mode=0o700)
    try:
        with pytest.raises(PackageProductRebindCleanupReadError) as residue:
            decision_owner(fifth).recover_unstarted_claim(
                failed.operation_id, max_bytes=1024, admission=fifth
            )
        assert residue.value.code == "package_rebind_claim_has_effects"
        assert lifecycle.path.read_bytes() == advanced_bytes
    finally:
        acquiring_orphan.rmdir()
    recovered_acquiring = decision_owner(fifth).recover_unstarted_claim(
        failed.operation_id, max_bytes=1024, admission=fifth
    )
    assert recovered_acquiring.disposition == "retryable_failure"
    assert recovered_acquiring.phase == "acquiring"
    assert recovered_acquiring.attempt_epoch == acquiring.attempt_epoch
    decision_owner(fifth).prepare(
        failed.operation_id, max_bytes=1024, admission=fifth
    )
    _selected, next_claim, _route = decision_owner(fifth).resume(
        failed.operation_id, max_bytes=1024, admission=fifth
    )
    assert next_claim.phase == "acquiring"
    acquisition_request = PackageAcquisitionRequestV1(
        operation_id=next_claim.operation_id,
        attempt_epoch=next_claim.attempt_epoch,
        node_id="root",
        canonical_source_identity=original[0].canonical_source_identity,
        request_fingerprint=next_claim.request_fingerprint,
        requested_locator_digest=sha256(
            original[0].canonical_source_identity.encode("utf-8")
        ).hexdigest(),
        policy_revision=original[0].policy_revision,
    )
    candidate = PackageAcquisitionOwner(
        source_authority=policy.source_authority(), quarantine_store=quarantine
    ).acquire(
        acquisition_request,
        budgets=PackageAcquisitionBudgetV1(
            max_transport_bytes=1024,
            max_requests=1,
            max_redirects=0,
            max_wall_time_ms=1000,
        ),
    )
    artifacts.append(
        request_fingerprint=next_claim.request_fingerprint,
        evidence=PackageAuthenticatedSourceEvidenceV1(
            attempt_epoch=next_claim.attempt_epoch,
            envelope=candidate.authenticated_envelope,
        ),
    )
    artifacts.append(
        request_fingerprint=next_claim.request_fingerprint,
        evidence=candidate.receipt,
    )
    candidate.suspend_for_recovery()
    next_claim = owner.advance(
        failed.operation_id,
        next_phase="acquired",
        expected_phase=next_claim.phase,
        expected_journal_revision=next_claim.journal_revision,
        expected_attempt_epoch=next_claim.attempt_epoch,
    )
    sixth = _admission("runtime:sixth")
    sixth_lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id=sixth.request.runtime_id,
        runtime_epoch=sixth.request.runtime_epoch,
        store_root_identity=sixth.request.store_root_identity,
        registration_receipt_id="7" * 64,
    )
    snapshots.value = PackageEpochLeaseSnapshotV1.create(
        store_id=sixth.request.store_id,
        owner_revision=8,
        active_leases=(sixth_lease,),
    )
    acquired_lease = PackageProductRebindLeaseReader(
        lifecycle=lifecycle,
        original_bindings=bindings,
        proposed_bindings=proposals,
        snapshots=snapshots,
        current_admission_request=sixth.request,
    ).observe_acquired_claim(failed.operation_id)
    assert acquired_lease.attempt_epoch == next_claim.attempt_epoch
    assert acquired_lease.new_admission_request_id == sixth.request.admission_request_id
    assert acquired_lease.prior_proposed_lease_id == fifth.request.lease_id
    acquired_source = source.observe_acquired_claim(
        failed.operation_id, max_bytes=1024
    )
    assert acquired_source.attempt_epoch == next_claim.attempt_epoch
    assert acquired_source.request_fingerprint == next_claim.request_fingerprint
    acquired_cleanup = cleanup.observe_acquired_claim(failed.operation_id)
    assert acquired_cleanup.status == next_claim
    assert acquired_cleanup.root_attempt.attempt_identity is not None
    assert acquired_cleanup.acquisition_receipt == candidate.receipt
    acquired_preflight = PackageProductAcquiredRebindPreflightV1(
        source=acquired_source,
        lease=acquired_lease,
        cleanup=acquired_cleanup,
    )
    assert acquired_preflight.cleanup.status == next_claim
    with pytest.raises(PackageProductAcquiredRebindPreflightError) as mixed_attempt:
        PackageProductAcquiredRebindPreflightV1(
            source=replace(acquired_source, attempt_epoch=1),
            lease=acquired_lease,
            cleanup=acquired_cleanup,
        )
    assert mixed_attempt.value.code == "package_rebind_preflight_attempt_changed"
    (quarantine.root / "unattributed").write_bytes(b"residue")
    with pytest.raises(PackageProductRebindCleanupReadError) as unknown_store:
        cleanup.observe_acquired_claim(failed.operation_id)
    assert unknown_store.value.code == "package_rebind_quarantine_not_empty"
    (quarantine.root / "unattributed").unlink()
    acquired_bytes = lifecycle.path.read_bytes()
    root.write_bytes(b"changed-root-wheel")
    with pytest.raises(PackageProductRebindSourceError) as changed_acquired_source:
        source.observe_acquired_claim(failed.operation_id, max_bytes=1024)
    assert changed_acquired_source.value.code == "package_source_digest_mismatch"
    assert lifecycle.path.read_bytes() == acquired_bytes
    root.write_bytes(b"root-wheel")
    with pytest.raises(PackageProductRebindLeaseReadError) as advanced:
        decision_owner(sixth).recover_unstarted_claim(
            failed.operation_id, max_bytes=1024, admission=sixth
        )
    assert advanced.value.code == "package_rebind_claim_not_unstarted"
    assert lifecycle.path.read_bytes() == acquired_bytes
    interrupted_acquired = lifecycle.interrupt(
        failed.operation_id,
        expected_phase=next_claim.phase,
        expected_journal_revision=next_claim.journal_revision,
        expected_attempt_epoch=next_claim.attempt_epoch,
        expected_attempt_revision=next_claim.attempt_revision,
    )
    interrupted_cleanup = cleanup.observe_interrupted_acquired_attempt(
        failed.operation_id
    )
    assert interrupted_cleanup.status == interrupted_acquired
    assert interrupted_cleanup.tombstone is None
    assert interrupted_cleanup.target.attempt_identity == (
        acquired_cleanup.root_attempt.attempt_identity
    )
    settlement = PackageQuarantineCleanupOwner(
        journal=PackageQuarantineCleanupJournal(tmp_path / "cleanup.jsonl"),
        store=quarantine,
    )
    pending = settlement.record_pending(
        interrupted_cleanup.target,
        rejection_code="package_rebind_restart",
        rejection_stage="acquired",
    )
    assert (
        cleanup.observe_interrupted_acquired_attempt(failed.operation_id).tombstone
        == pending
    )
    # Crash after exact physical removal but before the cleanup completion
    # record: replay must finish the same tombstone without a new target.
    quarantine._repair(pending.target)
    pending_after_removal = cleanup.observe_interrupted_acquired_attempt(
        failed.operation_id
    )
    assert pending_after_removal.root_attempt.attempt_identity is None
    assert pending_after_removal.tombstone == pending
    restart = decision_owner(sixth).recover_acquired_claim(
        failed.operation_id, max_bytes=1024, admission=sixth
    )
    completed = settlement.status(pending.target.cleanup_id)
    assert completed is not None
    assert completed.disposition == "cleanup_complete"
    assert cleanup.observe(failed.operation_id).cleanup_ids == (
        completed.target.cleanup_id,
    )
    assert restart.status.phase == "classified"
    assert restart.status.disposition == "retryable_failure"
    assert restart.restart.expected_phase == "acquired"
    after_restart = lifecycle.path.read_bytes()
    assert (
        decision_owner(sixth).recover_acquired_claim(
            failed.operation_id, max_bytes=1024, admission=sixth
        )
        == restart
    )
    assert lifecycle.path.read_bytes() == after_restart


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-relative proof")
def test_active_acquired_without_selected_rebind_has_no_recovery_proof(
    tmp_path: Path,
) -> None:
    policy, owner, lifecycle, resolution, _environment, status, _dependency = (
        _fixture(tmp_path)
    )
    for phase in ("acquiring", "acquired"):
        status = owner.advance(
            status.operation_id,
            next_phase=phase,
            expected_phase=status.phase,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
        )
    source = PackageProductRebindSourceReader(
        policy=policy, lifecycle=lifecycle, resolution=resolution
    )
    quarantine = PackageQuarantineStore(tmp_path / "quarantine")
    cleanup = PackageProductRebindCleanupReader(
        lifecycle=lifecycle,
        resolution=resolution,
        artifacts=PackageArtifactEvidenceJournal(tmp_path / "artifacts.jsonl"),
        cleanup=PackageQuarantineCleanupOwner(
            journal=PackageQuarantineCleanupJournal(tmp_path / "cleanup.jsonl"),
            store=quarantine,
        ),
        quarantine=quarantine,
        pins=PackageTransactionPinJournal(tmp_path / "pins.jsonl"),
        staging=PackageArtifactStagingJournal(tmp_path / "staging.jsonl"),
        committed_sets=PackageCommittedSetJournal(tmp_path / "committed-sets.jsonl"),
        handoff=PackageRetentionHandoffJournal(tmp_path / "handoff.jsonl"),
    )
    admission = _admission("runtime:new")
    current_lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id=admission.request.runtime_id,
        runtime_epoch=admission.request.runtime_epoch,
        store_root_identity=admission.request.store_root_identity,
        registration_receipt_id="7" * 64,
    )
    lease = PackageProductRebindLeaseReader(
        lifecycle=lifecycle,
        original_bindings=PackageProductAdmissionBindingJournal(
            tmp_path / "admissions.jsonl"
        ),
        snapshots=_Snapshots(
            PackageEpochLeaseSnapshotV1.create(
                store_id=admission.request.store_id,
                owner_revision=1,
                active_leases=(current_lease,),
            )
        ),
        current_admission_request=admission.request,
    )
    before = lifecycle.path.read_bytes()
    with pytest.raises(PackageProductRebindSourceReadError) as missing_source:
        source.observe_acquired_claim(status.operation_id, max_bytes=1024)
    assert missing_source.value.code == "package_rebind_claim_not_acquired"
    with pytest.raises(PackageProductRebindCleanupReadError) as missing_cleanup:
        cleanup.observe_acquired_claim(status.operation_id)
    assert missing_cleanup.value.code == "package_rebind_claim_not_acquired"
    with pytest.raises(PackageProductRebindLeaseReadError) as missing_lease:
        lease.observe_acquired_claim(status.operation_id)
    assert missing_lease.value.code == "package_rebind_claim_not_acquired"
    assert lifecycle.path.read_bytes() == before


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-relative proof")
@pytest.mark.parametrize(
    "claim_phase",
    [
        "acquired",
        "inspecting",
        "inspecting_verified",
        "extracted",
        "extracted_missing_verified",
        "resolving_root",
        "resolving_selected",
        "resolving_source",
        "resolving_acquired",
        "resolving_verified",
        "resolving_unattributed",
        "resolving_wrong_source",
        "resolving_interrupted",
        "resolving_source_interrupted",
        "resolving_foreign_tombstone",
        "resolving_owner_selected",
        "resolving_owner_source_only",
        "resolving_owner_acquired",
        "resolving_owner_crash_after_dependency",
        "resolving_owner_replaced_slot",
        "resolving_verified_plan",
        "resolving_verified_plan_mismatch",
        "resolving_verified_plan_missing",
        "resolving_verified_plan_crash",
        "resolving_verified_plan_dependency",
        "resolving_verified_plan_pinned",
        "resolving_verified_plan_pinned_released",
        "resolving_verified_plan_pinned_missing",
    ],
)
def test_product_selected_claim_evidence_and_root_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, claim_phase: str,
) -> None:
    old = _admission("runtime:old")
    second = _admission("runtime:second")
    third = _admission("runtime:third")
    policy, kernel, lifecycle, resolution, environment, classified, dependency = (
        _fixture(
            tmp_path,
            original_admission_request_id=old.request.admission_request_id,
        )
    )
    failed = kernel.interrupt(
        classified.operation_id,
        expected_phase=classified.phase,
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
    )
    original = lifecycle.read_operation(failed.operation_id)
    assert original is not None
    assert isinstance(original[0], PackageLifecycleRequestV2)
    bindings = PackageProductAdmissionBindingJournal(tmp_path / "admissions.jsonl")
    bindings.bind(original[0], failed, old)
    proposals = PackageProductRebindAdmissionBindingJournal(
        tmp_path / "rebind-admissions.jsonl"
    )
    artifacts = PackageArtifactEvidenceJournal(tmp_path / "artifacts.jsonl")
    quarantine = PackageQuarantineStore(tmp_path / "quarantine")
    cleanup_owner = PackageQuarantineCleanupOwner(
        journal=PackageQuarantineCleanupJournal(tmp_path / "cleanup.jsonl"),
        store=quarantine,
    )
    cleanup = PackageProductRebindCleanupReader(
        lifecycle=lifecycle,
        resolution=resolution,
        artifacts=artifacts,
        cleanup=cleanup_owner,
        quarantine=quarantine,
        pins=PackageTransactionPinJournal(tmp_path / "pins.jsonl"),
        staging=PackageArtifactStagingJournal(tmp_path / "staging.jsonl"),
        committed_sets=PackageCommittedSetJournal(tmp_path / "committed-sets.jsonl"),
        handoff=PackageRetentionHandoffJournal(tmp_path / "handoff.jsonl"),
        pin_recovery_identity="recovery:test",
    )
    source = PackageProductRebindSourceReader(
        policy=policy, lifecycle=lifecycle, resolution=resolution
    )

    def runtime_lease(
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> PackageEpochRuntimeLeaseV1:
        return PackageEpochRuntimeLeaseV1.create(
            runtime_id=admission.request.runtime_id,
            runtime_epoch=admission.request.runtime_epoch,
            store_root_identity=admission.request.store_root_identity,
            registration_receipt_id="7" * 64,
        )

    second_lease = runtime_lease(second)
    third_lease = runtime_lease(third)
    snapshots = _Snapshots(
        PackageEpochLeaseSnapshotV1.create(
            store_id=second.request.store_id,
            owner_revision=2,
            active_leases=(second_lease,),
        )
    )

    def decision(
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> PackageProductRebindDecisionOwner:
        return PackageProductRebindDecisionOwner(
            lifecycle=lifecycle,
            source=source,
            lease=PackageProductRebindLeaseReader(
                lifecycle=lifecycle,
                original_bindings=bindings,
                proposed_bindings=proposals,
                snapshots=snapshots,
                current_admission_request=admission.request,
            ),
            cleanup=cleanup,
            quarantine_cleanup=cleanup_owner,
            proposals=proposals,
        )

    decision(second).prepare(failed.operation_id, max_bytes=1024, admission=second)
    _selected, claim, _route = decision(second).resume(
        failed.operation_id, max_bytes=1024, admission=second
    )
    claim = kernel.advance(
        claim.operation_id,
        next_phase="acquiring",
        expected_phase=claim.phase,
        expected_journal_revision=claim.journal_revision,
        expected_attempt_epoch=claim.attempt_epoch,
    )
    source_identity = original[0].canonical_source_identity
    candidate = PackageAcquisitionOwner(
        source_authority=policy.source_authority(), quarantine_store=quarantine
    ).acquire(
        PackageAcquisitionRequestV1(
            operation_id=claim.operation_id,
            attempt_epoch=claim.attempt_epoch,
            node_id="root",
            canonical_source_identity=source_identity,
            request_fingerprint=claim.request_fingerprint,
            requested_locator_digest=sha256(source_identity.encode()).hexdigest(),
            policy_revision=original[0].policy_revision,
        ),
        budgets=PackageAcquisitionBudgetV1(
            max_transport_bytes=1024,
            max_requests=1,
            max_redirects=0,
            max_wall_time_ms=1000,
        ),
    )
    artifacts.append(
        request_fingerprint=claim.request_fingerprint,
        evidence=PackageAuthenticatedSourceEvidenceV1(
            attempt_epoch=claim.attempt_epoch,
            envelope=candidate.authenticated_envelope,
        ),
    )
    artifacts.append(
        request_fingerprint=claim.request_fingerprint,
        evidence=candidate.receipt,
    )
    candidate.suspend_for_recovery()
    acquired = kernel.advance(
        claim.operation_id,
        next_phase="acquired",
        expected_phase=claim.phase,
        expected_journal_revision=claim.journal_revision,
        expected_attempt_epoch=claim.attempt_epoch,
    )
    if claim_phase.startswith(("inspecting", "extracted", "resolving")):
        acquired = kernel.advance(
            acquired.operation_id,
            next_phase="inspecting",
            expected_phase=acquired.phase,
            expected_journal_revision=acquired.journal_revision,
            expected_attempt_epoch=acquired.attempt_epoch,
        )
    if claim_phase in {"inspecting_verified", "extracted"} or claim_phase.startswith(
        "resolving"
    ):
        artifacts.append(
            request_fingerprint=claim.request_fingerprint,
            evidence=VerifiedWheelArtifactV1(
                operation_id=claim.operation_id,
                attempt_epoch=claim.attempt_epoch,
                node_id="root",
                distribution="root",
                version="1.0",
                wheel_filename="root-1.0-py3-none-any.whl",
                compatible_tags=("py3-none-any",),
                artifact_digest=candidate.receipt.actual_byte_digest,
                artifact_size=candidate.receipt.actual_byte_count,
                wheel_metadata_digest="d" * 64,
                package_metadata_digest="e" * 64,
                record_digest="f" * 64,
                record_verified=True,
                entry_count=1,
                expanded_byte_count=1,
                extraction_tree_digest="1" * 64,
            ),
        )
    if claim_phase.startswith(("extracted", "resolving")):
        acquired = kernel.advance(
            acquired.operation_id,
            next_phase="extracted",
            expected_phase=acquired.phase,
            expected_journal_revision=acquired.journal_revision,
            expected_attempt_epoch=acquired.attempt_epoch,
        )
    if claim_phase.startswith("resolving"):
        acquired = kernel.advance(
            acquired.operation_id,
            next_phase="resolving_closure",
            expected_phase=acquired.phase,
            expected_journal_revision=acquired.journal_revision,
            expected_attempt_epoch=acquired.attempt_epoch,
        )
        resolution.bind_basis(
            PackageClosureResolutionBasisV1(
                operation_id=acquired.operation_id,
                attempt_epoch=acquired.attempt_epoch,
                request_fingerprint=acquired.request_fingerprint,
                policy_revision=policy.policy_revision,
                quota_profile_revision=policy.quota_profile_revision,
                resolution_environment=environment,
                budgets=PackageClosureBudgetV1(),
            )
        )
        selected_node = None
        if claim_phase != "resolving_root" and (
            not claim_phase.startswith("resolving_verified_plan")
            or claim_phase == "resolving_verified_plan_dependency"
        ):
            selection_request = PackageDependencySelectionRequestV1(
                operation_id=acquired.operation_id,
                attempt_epoch=acquired.attempt_epoch,
                parent_node_id="root",
                request_fingerprint=acquired.request_fingerprint,
                resolution_environment_fingerprint=environment.fingerprint,
                requirement=NormalizedPackageRequirementV1.parse("helper==2.0"),
            )
            selected_node = policy.resolve(selection_request)
            resolution.append_selection(selection_request, selected_node)
        if claim_phase in {
            "resolving_source",
            "resolving_acquired",
            "resolving_verified",
            "resolving_unattributed",
            "resolving_wrong_source",
            "resolving_interrupted",
            "resolving_source_interrupted",
            "resolving_foreign_tombstone",
            "resolving_owner_source_only",
            "resolving_owner_acquired",
            "resolving_owner_crash_after_dependency",
            "resolving_owner_replaced_slot",
            "resolving_verified_plan_dependency",
        }:
            assert selected_node is not None
            dependency_candidate = PackageAcquisitionOwner(
                source_authority=policy.source_authority(),
                quarantine_store=quarantine,
            ).acquire(
                PackageAcquisitionRequestV1(
                    operation_id=acquired.operation_id,
                    attempt_epoch=acquired.attempt_epoch,
                    node_id=selected_node.node_id,
                    canonical_source_identity=str(dependency),
                    request_fingerprint=acquired.request_fingerprint,
                    requested_locator_digest=sha256(str(dependency).encode()).hexdigest(),
                    policy_revision=policy.policy_revision,
                ),
                budgets=PackageAcquisitionBudgetV1(
                    max_transport_bytes=1024,
                    max_requests=1,
                    max_redirects=0,
                    max_wall_time_ms=1000,
                ),
            )
            if claim_phase != "resolving_unattributed":
                envelope = dependency_candidate.authenticated_envelope
                if claim_phase == "resolving_wrong_source":
                    envelope = replace(
                        envelope,
                        canonical_source_identity=source_identity,
                        requested_locator_digest=sha256(
                            source_identity.encode()
                        ).hexdigest(),
                        expected_artifact_digest=policy.bindings[0].artifact_digest,
                    )
                artifacts.append(
                    request_fingerprint=acquired.request_fingerprint,
                    evidence=PackageAuthenticatedSourceEvidenceV1(
                        attempt_epoch=acquired.attempt_epoch,
                        envelope=envelope,
                    ),
                )
            if claim_phase in {
                "resolving_acquired",
                "resolving_verified",
                "resolving_interrupted",
                "resolving_foreign_tombstone",
                "resolving_owner_acquired",
                "resolving_owner_crash_after_dependency",
                "resolving_verified_plan_dependency",
            }:
                artifacts.append(
                    request_fingerprint=acquired.request_fingerprint,
                    evidence=dependency_candidate.receipt,
                )
            if claim_phase in {
                "resolving_verified", "resolving_verified_plan_dependency"
            }:
                artifacts.append(
                    request_fingerprint=acquired.request_fingerprint,
                    evidence=VerifiedWheelArtifactV1(
                        operation_id=acquired.operation_id,
                        attempt_epoch=acquired.attempt_epoch,
                        node_id=selected_node.node_id,
                        distribution="helper",
                        version="2.0",
                        wheel_filename="helper-2.0-py3-none-any.whl",
                        compatible_tags=("py3-none-any",),
                        artifact_digest=dependency_candidate.receipt.actual_byte_digest,
                        artifact_size=dependency_candidate.receipt.actual_byte_count,
                        wheel_metadata_digest="d" * 64,
                        package_metadata_digest="e" * 64,
                        record_digest="f" * 64,
                        record_verified=True,
                        entry_count=1,
                        expanded_byte_count=1,
                        extraction_tree_digest="1" * 64,
                    ),
                )
            dependency_candidate.suspend_for_recovery()
        if claim_phase.startswith("resolving_verified_plan"):
            records = artifacts.read_attempt_evidence(
                operation_id=acquired.operation_id,
                attempt_epoch=acquired.attempt_epoch,
            )
            source_evidence = records[0].evidence
            receipt_evidence = records[1].evidence
            wheel_evidence = records[2].evidence
            assert isinstance(source_evidence, PackageAuthenticatedSourceEvidenceV1)
            assert isinstance(receipt_evidence, BoundedAcquisitionReceiptV1)
            assert isinstance(wheel_evidence, VerifiedWheelArtifactV1)
            dependency_plan_node = None
            resolved_requirements: tuple[ResolvedPackageRequirementV1, ...] = ()
            selected_edges: tuple[str, ...] = ()
            if claim_phase == "resolving_verified_plan_dependency":
                assert selected_node is not None
                dependency_records = tuple(
                    record.evidence
                    for record in records
                    if record.node_id == selected_node.node_id
                )
                assert len(dependency_records) == 3
                dependency_source, dependency_receipt, dependency_wheel = (
                    dependency_records
                )
                assert isinstance(
                    dependency_source, PackageAuthenticatedSourceEvidenceV1
                )
                assert isinstance(dependency_receipt, BoundedAcquisitionReceiptV1)
                assert isinstance(dependency_wheel, VerifiedWheelArtifactV1)
                dependency_plan_node = VerifiedClosurePlanNodeV2(
                    node_id=selected_node.node_id,
                    role="dependency",
                    distribution=dependency_wheel.distribution,
                    version=dependency_wheel.version,
                    canonical_source_identity=selected_node.canonical_source_identity,
                    source_envelope_fingerprint=(
                        dependency_source.envelope.fingerprint
                    ),
                    acquisition_receipt_fingerprint=dependency_receipt.fingerprint,
                    wheel_evidence_fingerprint=dependency_wheel.fingerprint,
                    artifact_digest=dependency_wheel.artifact_digest,
                    extraction_tree_digest=dependency_wheel.extraction_tree_digest,
                    selected_extras=(),
                    requirements=(),
                    selected_edges=(),
                )
                resolved_requirements = (
                    ResolvedPackageRequirementV1(
                        requirement=NormalizedPackageRequirementV1.parse(
                            "helper==2.0"
                        ),
                        marker_applies=True,
                        selected_node_id=selected_node.node_id,
                        expected_source_identity=(
                            selected_node.canonical_source_identity
                        ),
                        expected_artifact_digest=selected_node.expected_artifact_digest,
                    ),
                )
                selected_edges = (selected_node.node_id,)
            node = VerifiedClosurePlanNodeV2(
                node_id="root",
                role="root",
                distribution=wheel_evidence.distribution,
                version=wheel_evidence.version,
                canonical_source_identity=source_identity,
                source_envelope_fingerprint=source_evidence.envelope.fingerprint,
                acquisition_receipt_fingerprint=receipt_evidence.fingerprint,
                wheel_evidence_fingerprint=(
                    "a" * 64
                    if claim_phase == "resolving_verified_plan_mismatch"
                    else wheel_evidence.fingerprint
                ),
                artifact_digest=wheel_evidence.artifact_digest,
                extraction_tree_digest=wheel_evidence.extraction_tree_digest,
                selected_extras=(),
                requirements=resolved_requirements,
                selected_edges=selected_edges,
            )
            plan = VerifiedClosurePlanV2.create(
                operation_id=acquired.operation_id,
                attempt_epoch=acquired.attempt_epoch,
                root_node_id="root",
                resolution_environment_fingerprint=environment.fingerprint,
                nodes=(
                    (node, dependency_plan_node)
                    if dependency_plan_node is not None
                    else (node,)
                ),
                max_depth=1 if dependency_plan_node is not None else 0,
            )
            if claim_phase != "resolving_verified_plan_missing":
                resolution.append_plan(
                    request_fingerprint=acquired.request_fingerprint, plan=plan
                )
            acquired = kernel.advance(
                acquired.operation_id,
                next_phase="closure_verified",
                expected_phase=acquired.phase,
                expected_journal_revision=acquired.journal_revision,
                expected_attempt_epoch=acquired.attempt_epoch,
            )
            if claim_phase in {
                "resolving_verified_plan_pinned",
                "resolving_verified_plan_pinned_released",
                "resolving_verified_plan_pinned_missing",
            }:
                acquired = kernel.advance(
                    acquired.operation_id,
                    next_phase="transaction_pinned",
                    expected_phase=acquired.phase,
                    expected_journal_revision=acquired.journal_revision,
                    expected_attempt_epoch=acquired.attempt_epoch,
                )
                assert acquired.classification is not None
                pin_request = PackageTransactionPinRequestV1.create(
                    plan,
                    request_fingerprint=acquired.request_fingerprint,
                    classification_fingerprint=acquired.classification.evidence_ref,
                    recovery_identity="recovery:test",
                )
                pin = PackageTransactionPinReceiptV1.acquire(
                    pin_request,
                    pin_id="a" * 64,
                    owner_identity="package-transaction-retention",
                    owner_revision=1,
                    lease_id="lease:test",
                    lease_revision=1,
                )
                pin_journal = PackageTransactionPinJournal(tmp_path / "pins.jsonl")
                if claim_phase != "resolving_verified_plan_pinned_missing":
                    pin_journal.append(pin)
                if claim_phase == "resolving_verified_plan_pinned_released":
                    pin_journal.append(
                        PackageTransactionPinReceiptV1.transition(
                            pin,
                            state="released",
                            owner_revision=2,
                            lease_revision=2,
                            transition_evidence_ref="b" * 64,
                        )
                    )
            snapshots.value = PackageEpochLeaseSnapshotV1.create(
                store_id=third.request.store_id,
                owner_revision=4,
                active_leases=(third_lease,),
            )
            if claim_phase in {
                "resolving_verified_plan_pinned",
                "resolving_verified_plan_pinned_released",
                "resolving_verified_plan_pinned_missing",
            }:
                before = lifecycle.path.read_bytes()
                if claim_phase in {
                    "resolving_verified_plan_pinned_released",
                    "resolving_verified_plan_pinned_missing",
                }:
                    with pytest.raises(PackageProductRebindCleanupReadError) as invalid:
                        cleanup.observe_pinned_claim(acquired.operation_id)
                    assert invalid.value.code == "package_rebind_pin_evidence_changed"
                else:
                    pinned = PackageProductPinnedRebindPreflightV1(
                        source=source.observe_pinned_claim(
                            acquired.operation_id, max_bytes=1024
                        ),
                        lease=PackageProductRebindLeaseReader(
                            lifecycle=lifecycle,
                            original_bindings=bindings,
                            proposed_bindings=proposals,
                            snapshots=snapshots,
                            current_admission_request=third.request,
                        ).observe_pinned_claim(acquired.operation_id),
                        cleanup=cleanup.observe_pinned_claim(acquired.operation_id),
                    )
                    assert pinned.cleanup.pin == pin
                    assert pinned.cleanup.closure.status == acquired
                    assert lifecycle.path.read_bytes() == before
                    pinned_bindings = PackageProductPinnedAdoptionBindingJournal(
                        tmp_path / "pinned-admissions.jsonl"
                    )
                    current_admission = PackageEpochRuntimeAdmissionReceiptV1.create(
                        third.request, snapshot=snapshots.value
                    )
                    pinned_owner = PackageProductPinnedAdoptionOwner(
                        lifecycle=lifecycle,
                        source=source,
                        lease=PackageProductRebindLeaseReader(
                            lifecycle=lifecycle,
                            original_bindings=bindings,
                            proposed_bindings=proposals,
                            pinned_bindings=pinned_bindings,
                            snapshots=snapshots,
                            current_admission_request=third.request,
                        ),
                        cleanup=cleanup,
                        resolution=resolution,
                        proposals=pinned_bindings,
                    )
                    selected = pinned_owner.prepare(
                        acquired.operation_id,
                        max_bytes=1024,
                        admission=current_admission,
                    )
                    assert selected.status.attempt_epoch == acquired.attempt_epoch
                    assert selected.status.phase == "transaction_pinned"
                    assert selected.decision.pin_receipt_id == pin.receipt_id
                    before_replay = lifecycle.path.read_bytes()
                    assert pinned_owner.prepare(
                        acquired.operation_id,
                        max_bytes=1024,
                        admission=current_admission,
                    ) == selected
                    assert lifecycle.latest_pinned_adoption(
                        acquired.operation_id
                    ) == selected
                    assert lifecycle.path.read_bytes() == before_replay
                    fourth = _admission("runtime:fourth")
                    fourth_lease = runtime_lease(fourth)
                    snapshots.value = PackageEpochLeaseSnapshotV1.create(
                        store_id=fourth.request.store_id,
                        owner_revision=5,
                        active_leases=(third_lease, fourth_lease),
                    )

                    def fourth_owner() -> PackageProductPinnedAdoptionOwner:
                        return PackageProductPinnedAdoptionOwner(
                            lifecycle=lifecycle,
                            source=source,
                            lease=PackageProductRebindLeaseReader(
                                lifecycle=lifecycle,
                                original_bindings=bindings,
                                proposed_bindings=proposals,
                                pinned_bindings=pinned_bindings,
                                snapshots=snapshots,
                                current_admission_request=fourth.request,
                            ),
                            cleanup=cleanup,
                            resolution=resolution,
                            proposals=pinned_bindings,
                        )

                    with pytest.raises(PackageProductRebindLeaseReadError) as live:
                        fourth_owner().prepare(
                            acquired.operation_id,
                            max_bytes=1024,
                            admission=PackageEpochRuntimeAdmissionReceiptV1.create(
                                fourth.request, snapshot=snapshots.value
                            ),
                        )
                    assert live.value.code == (
                        "package_pinned_adoption_prior_lease_active"
                    )
                    assert lifecycle.path.read_bytes() == before_replay
                    snapshots.value = PackageEpochLeaseSnapshotV1.create(
                        store_id=fourth.request.store_id,
                        owner_revision=6,
                        active_leases=(fourth_lease,),
                    )
                    fourth_admission = PackageEpochRuntimeAdmissionReceiptV1.create(
                        fourth.request, snapshot=snapshots.value
                    )
                    superseded = fourth_owner().prepare(
                        acquired.operation_id,
                        max_bytes=1024,
                        admission=fourth_admission,
                    )
                    assert superseded.record_kind == (
                        "pinned_adoption_supersession"
                    )
                    assert superseded.supersedes_decision_id == (
                        selected.decision.decision_id
                    )
                    assert superseded.status.attempt_epoch == (
                        selected.status.attempt_epoch
                    )
                    assert superseded.decision.pin_receipt_id == pin.receipt_id
                    with pytest.raises(PackageProductRouteContractError) as stale:
                        require_rebound_decision(
                            pinned_owner.route(selected, current_admission),
                            superseded.status,
                            lifecycle,
                        )
                    assert stale.value.code == (
                        "package_pinned_adoption_execution_not_available"
                    )
                    before = lifecycle.path.read_bytes()
                    assert fourth_owner().prepare(
                        acquired.operation_id,
                        max_bytes=1024,
                        admission=fourth_admission,
                    ) == superseded
                    assert lifecycle.path.read_bytes() == before
                    executor = fourth_owner()
                    claimed, current, route = executor.claim(
                        acquired.operation_id,
                        max_bytes=1024,
                        admission=fourth_admission,
                    )
                    assert claimed == superseded
                    assert current == superseded.status
                    with pytest.raises(PackageProductRouteContractError) as unissued:
                        fourth_owner().authorize(route, current)
                    assert unissued.value.code == (
                        "package_pinned_adoption_execution_not_available"
                    )
                    with pytest.raises(PackageProductRouteContractError) as changed:
                        executor.authorize(
                            replace(route, entrypoint="cli"), current
                        )
                    assert changed.value.code == (
                        "package_pinned_adoption_execution_not_available"
                    )
                    executor.authorize(route, current)
                    with pytest.raises(PackageProductRouteContractError) as reused:
                        executor.authorize(route, current)
                    assert reused.value.code == (
                        "package_pinned_adoption_execution_not_available"
                    )
                assert lifecycle.path.read_bytes() == before
                assert cleanup_owner.read_operation_tombstones(acquired.operation_id) == ()
                return
            if claim_phase in {
                "resolving_verified_plan_mismatch",
                "resolving_verified_plan_missing",
            }:
                before = lifecycle.path.read_bytes()
                with pytest.raises(PackageProductRebindCleanupReadError) as invalid:
                    cleanup.observe_verified_claim(acquired.operation_id)
                assert invalid.value.code == (
                    "package_rebind_verified_closure_changed"
                    if claim_phase == "resolving_verified_plan_mismatch"
                    else "package_rebind_resolving_evidence_changed"
                )
                assert lifecycle.path.read_bytes() == before
                assert cleanup_owner.read_operation_tombstones(acquired.operation_id) == ()
                return
            verified = PackageProductResolvingRebindPreflightV1(
                source=source.observe_verified_claim(
                    acquired.operation_id, max_bytes=1024
                ),
                lease=PackageProductRebindLeaseReader(
                    lifecycle=lifecycle,
                    original_bindings=bindings,
                    proposed_bindings=proposals,
                    snapshots=snapshots,
                    current_admission_request=third.request,
                ).observe_verified_claim(acquired.operation_id),
                cleanup=cleanup.observe_verified_claim(acquired.operation_id),
            )
            assert verified.cleanup.status == acquired
            assert {node.attempt.node_id for node in verified.cleanup.nodes} == (
                {"root", selected_node.node_id}
                if selected_node is not None
                else {"root"}
            )
            before = lifecycle.path.read_bytes()
            Path(source_identity).write_bytes(b"changed-root-wheel")
            try:
                with pytest.raises(PackageProductRebindSourceError) as drift:
                    decision(third).recover_verified_claim(
                        acquired.operation_id, max_bytes=1024, admission=third
                    )
                assert drift.value.code == "package_source_digest_mismatch"
                assert lifecycle.path.read_bytes() == before
                assert cleanup_owner.read_operation_tombstones(acquired.operation_id) == ()
            finally:
                Path(source_identity).write_bytes(b"root-wheel")
            if claim_phase == "resolving_verified_plan_crash":
                record_pending = cleanup_owner.record_pending

                def crash_before_tombstone(
                    *_args: object, **_kwargs: object
                ) -> None:
                    raise RuntimeError("crash before verified cleanup tombstone")

                monkeypatch.setattr(cleanup_owner, "record_pending", crash_before_tombstone)
                with pytest.raises(RuntimeError, match="verified cleanup tombstone"):
                    decision(third).recover_verified_claim(
                        acquired.operation_id, max_bytes=1024, admission=third
                    )
                monkeypatch.setattr(cleanup_owner, "record_pending", record_pending)
                interrupted = lifecycle.read_operation(acquired.operation_id)
                assert interrupted is not None
                assert interrupted[1].phase == "closure_verified"
                assert interrupted[1].disposition == "retryable_failure"
                assert cleanup_owner.read_operation_tombstones(acquired.operation_id) == ()
            restarted = decision(third).recover_verified_claim(
                acquired.operation_id, max_bytes=1024, admission=third
            )
            assert restarted.restart.expected_phase == "closure_verified"
            assert restarted.status.phase == "classified"
            assert quarantine.attempt_names() == ()
            assert (
                decision(third).recover_verified_claim(
                    acquired.operation_id, max_bytes=1024, admission=third
                )
                == restarted
            )
            return
        before = (lifecycle.path.read_bytes(), resolution.path.read_bytes())
        if claim_phase in {"resolving_unattributed", "resolving_wrong_source"}:
            with pytest.raises(PackageProductRebindCleanupReadError) as invalid:
                cleanup.observe_resolving_claim(acquired.operation_id)
            assert invalid.value.code == "package_rebind_resolving_evidence_changed"
            assert (lifecycle.path.read_bytes(), resolution.path.read_bytes()) == before
            assert cleanup_owner.read_operation_tombstones(acquired.operation_id) == ()
            return
        observation = cleanup.observe_resolving_claim(acquired.operation_id)
        assert observation.status == acquired
        assert tuple(node.attempt.node_id for node in observation.nodes) == (
            ("root",) if selected_node is None else (selected_node.node_id, "root")
        )
        if selected_node is not None:
            selected_observation = observation.nodes[0]
            assert selected_observation.source_recorded == (
                claim_phase not in {"resolving_selected", "resolving_owner_selected"}
            )
            assert (selected_observation.acquisition_receipt is not None) == (
                claim_phase in {
                    "resolving_acquired",
                    "resolving_verified",
                    "resolving_interrupted",
                    "resolving_foreign_tombstone",
                    "resolving_owner_acquired",
                    "resolving_owner_crash_after_dependency",
                }
            )
            assert selected_observation.verified_recorded == (
                claim_phase == "resolving_verified"
            )
        assert (lifecycle.path.read_bytes(), resolution.path.read_bytes()) == before
        snapshots.value = PackageEpochLeaseSnapshotV1.create(
            store_id=third.request.store_id,
            owner_revision=4,
            active_leases=(third_lease,),
        )
        joined = PackageProductResolvingRebindPreflightV1(
            source=source.observe_resolving_claim(
                acquired.operation_id, max_bytes=1024
            ),
            lease=PackageProductRebindLeaseReader(
                lifecycle=lifecycle,
                original_bindings=bindings,
                proposed_bindings=proposals,
                snapshots=snapshots,
                current_admission_request=third.request,
            ).observe_resolving_claim(acquired.operation_id),
            cleanup=observation,
        )
        assert joined.cleanup == observation
        if claim_phase == "resolving_acquired":
            unchanged = lifecycle.path.read_bytes()
            dependency.write_bytes(b"changed-dependency")
            try:
                with pytest.raises(PackageProductRebindSourceError) as drift:
                    decision(third).recover_resolving_claim(
                        acquired.operation_id, max_bytes=1024, admission=third
                    )
                assert drift.value.code == "package_source_digest_mismatch"
                assert lifecycle.path.read_bytes() == unchanged
                assert cleanup_owner.read_operation_tombstones(acquired.operation_id) == ()
            finally:
                dependency.write_bytes(b"dependency-wheel")
        if claim_phase.startswith("resolving_owner"):
            if claim_phase == "resolving_owner_replaced_slot":
                interrupt = lifecycle.interrupt

                def replace_after_interrupt(*args: object, **kwargs: object) -> object:
                    interrupted_status = interrupt(*args, **kwargs)
                    assert selected_node is not None
                    [slot] = quarantine.observe_attempts(
                        acquired.operation_id,
                        acquired.attempt_epoch,
                        (selected_node.node_id,),
                    )
                    path = quarantine.root / slot.attempt_name
                    path.rename(tmp_path / "old-dependency-attempt")
                    path.mkdir(mode=0o700)
                    return interrupted_status

                monkeypatch.setattr(lifecycle, "interrupt", replace_after_interrupt)
                with pytest.raises(PackageProductRebindDecisionError) as replaced:
                    decision(third).recover_resolving_claim(
                        acquired.operation_id, max_bytes=1024, admission=third
                    )
                assert replaced.value.code == "package_rebind_claim_evidence_changed"
                assert cleanup_owner.read_operation_tombstones(acquired.operation_id) == ()
                return
            if claim_phase == "resolving_owner_crash_after_dependency":
                record_pending = cleanup_owner.record_pending

                def crash_before_root_tombstone(
                    target: PackageQuarantineCleanupTargetV1,
                    **kwargs: object,
                ) -> object:
                    if target.node_id == "root":
                        raise RuntimeError("crash before root cleanup tombstone")
                    return record_pending(target, **kwargs)

                monkeypatch.setattr(
                    cleanup_owner, "record_pending", crash_before_root_tombstone
                )
                with pytest.raises(RuntimeError, match="crash before root"):
                    decision(third).recover_resolving_claim(
                        acquired.operation_id, max_bytes=1024, admission=third
                    )
                monkeypatch.setattr(cleanup_owner, "record_pending", record_pending)
                interrupted_state = lifecycle.read_operation(acquired.operation_id)
                assert interrupted_state is not None
                assert interrupted_state[1].phase == "resolving_closure"
                assert interrupted_state[1].disposition == "retryable_failure"
                [dependency_tombstone] = cleanup_owner.read_operation_tombstones(
                    acquired.operation_id
                )
                assert dependency_tombstone.target.node_id != "root"
                assert dependency_tombstone.disposition == "cleanup_complete"
            restarted = decision(third).recover_resolving_claim(
                acquired.operation_id, max_bytes=1024, admission=third
            )
            assert restarted.restart.expected_phase == "resolving_closure"
            assert restarted.status.phase == "classified"
            assert restarted.status.disposition == "retryable_failure"
            assert quarantine.attempt_names() == ()
            assert (
                decision(third).recover_resolving_claim(
                    acquired.operation_id, max_bytes=1024, admission=third
                )
                == restarted
            )
            with pytest.raises(PackageProductRebindCleanupReadError) as wrong_route:
                decision(third).recover_acquired_claim(
                    acquired.operation_id, max_bytes=1024, admission=third
                )
            assert wrong_route.value.code == "package_rebind_claim_not_acquired"
            return
        if claim_phase in {
            "resolving_interrupted",
            "resolving_source_interrupted",
            "resolving_foreign_tombstone",
        }:
            interrupted_status = lifecycle.interrupt(
                acquired.operation_id,
                expected_phase=acquired.phase,
                expected_journal_revision=acquired.journal_revision,
                expected_attempt_epoch=acquired.attempt_epoch,
                expected_attempt_revision=acquired.attempt_revision,
            )
            interrupted = cleanup.observe_interrupted_resolving_attempt(
                acquired.operation_id
            )
            assert interrupted.status == interrupted_status
            assert all(node.target is not None for node in interrupted.nodes)
            dependency_target = interrupted.nodes[0].target
            root_target = interrupted.nodes[1].target
            assert dependency_target is not None
            assert root_target is not None
            if claim_phase == "resolving_foreign_tombstone":
                cleanup_owner.record_pending(
                    dependency_target,
                    rejection_code="package_closure_conflict",
                    rejection_stage="resolving_closure",
                )
                with pytest.raises(PackageProductRebindCleanupReadError) as foreign:
                    cleanup.observe_interrupted_resolving_attempt(
                        acquired.operation_id
                    )
                assert foreign.value.code == "package_rebind_cleanup_pending"
                return
            dependency_tombstone = cleanup_owner.record_pending(
                dependency_target,
                rejection_code="package_rebind_restart",
                rejection_stage="resolving_closure",
            )
            pending = cleanup.observe_interrupted_resolving_attempt(
                acquired.operation_id
            )
            assert pending.nodes[0].tombstone == dependency_tombstone
            assert pending.nodes[1].tombstone is None
            dependency_slot = quarantine.root / pending.nodes[0].node.attempt.attempt_name
            moved_slot = quarantine.root / "moved-dependency-attempt"
            dependency_slot.rename(moved_slot)
            try:
                with pytest.raises(PackageProductRebindCleanupReadError) as moved:
                    cleanup.observe_interrupted_resolving_attempt(
                        acquired.operation_id
                    )
                assert moved.value.code == "package_rebind_quarantine_not_empty"
            finally:
                moved_slot.rename(dependency_slot)
            quarantine._repair(dependency_target)
            pending_after_removal = cleanup.observe_interrupted_resolving_attempt(
                acquired.operation_id
            )
            assert pending_after_removal.nodes[0].node.attempt.attempt_identity is None
            assert pending_after_removal.nodes[0].tombstone == dependency_tombstone
            cleanup_owner.repair(
                dependency_target.cleanup_id,
                expected_cleanup_revision=dependency_tombstone.cleanup_revision,
            )
            halfway = cleanup.observe_interrupted_resolving_attempt(
                acquired.operation_id
            )
            assert halfway.nodes[0].node.attempt.attempt_identity is None
            assert halfway.nodes[0].target == dependency_target
            root_tombstone = cleanup_owner.record_pending(
                root_target,
                rejection_code="package_rebind_restart",
                rejection_stage="resolving_closure",
            )
            cleanup_owner.repair(
                root_target.cleanup_id,
                expected_cleanup_revision=root_tombstone.cleanup_revision,
            )
            settled = cleanup.observe_interrupted_resolving_attempt(
                acquired.operation_id
            )
            assert all(node.node.attempt.attempt_identity is None for node in settled.nodes)
            assert all(
                node.tombstone is not None
                and node.tombstone.disposition == "cleanup_complete"
                for node in settled.nodes
            )
            restarted = decision(third).recover_resolving_claim(
                acquired.operation_id, max_bytes=1024, admission=third
            )
            assert restarted.restart.expected_phase == "resolving_closure"
            assert restarted.status.phase == "classified"
        return
    snapshots.value = PackageEpochLeaseSnapshotV1.create(
        store_id=third.request.store_id,
        owner_revision=3,
        active_leases=(second_lease, third_lease),
    )
    if claim_phase == "extracted_missing_verified":
        snapshots.value = PackageEpochLeaseSnapshotV1.create(
            store_id=third.request.store_id,
            owner_revision=4,
            active_leases=(third_lease,),
        )
        before = lifecycle.path.read_bytes()
        with pytest.raises(PackageProductRebindCleanupReadError) as missing:
            decision(third).recover_acquired_claim(
                acquired.operation_id, max_bytes=1024, admission=third
            )
        assert missing.value.code == "package_rebind_acquired_evidence_changed"
        assert lifecycle.path.read_bytes() == before
        assert cleanup_owner.read_operation_tombstones(acquired.operation_id) == ()
        return
    before = lifecycle.path.read_bytes()
    with pytest.raises(PackageProductRebindLeaseReadError) as old_live:
        decision(third).recover_acquired_claim(
            acquired.operation_id, max_bytes=1024, admission=third
        )
    assert old_live.value.code == "package_rebind_prior_lease_active"
    assert lifecycle.path.read_bytes() == before
    snapshots.value = PackageEpochLeaseSnapshotV1.create(
        store_id=third.request.store_id,
        owner_revision=4,
        active_leases=(third_lease,),
    )
    root = Path(source_identity)
    root.write_bytes(b"changed-root-wheel")
    with pytest.raises(PackageProductRebindSourceError) as changed_source:
        decision(third).recover_acquired_claim(
            acquired.operation_id, max_bytes=1024, admission=third
        )
    assert changed_source.value.code == "package_source_digest_mismatch"
    assert lifecycle.path.read_bytes() == before
    root.write_bytes(b"root-wheel")

    record_pending = cleanup_owner.record_pending

    def crash_before_tombstone(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("crash before cleanup tombstone")

    monkeypatch.setattr(cleanup_owner, "record_pending", crash_before_tombstone)
    with pytest.raises(RuntimeError, match="crash before cleanup tombstone"):
        decision(third).recover_acquired_claim(
            acquired.operation_id, max_bytes=1024, admission=third
        )
    interrupted = lifecycle.read_operation(acquired.operation_id)
    assert interrupted is not None
    assert interrupted[1].disposition == "retryable_failure"
    assert interrupted[1].phase == acquired.phase
    assert cleanup_owner.read_operation_tombstones(acquired.operation_id) == ()
    assert quarantine.attempt_names()
    monkeypatch.setattr(cleanup_owner, "record_pending", record_pending)

    repair = cleanup_owner.repair

    def crash_before_repair(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("crash after cleanup tombstone")

    monkeypatch.setattr(cleanup_owner, "repair", crash_before_repair)
    with pytest.raises(RuntimeError, match="crash after cleanup tombstone"):
        decision(third).recover_acquired_claim(
            acquired.operation_id, max_bytes=1024, admission=third
        )
    assert cleanup_owner.read_operation_tombstones(acquired.operation_id)[
        0
    ].disposition == "cleanup_retryable"
    assert quarantine.attempt_names()
    monkeypatch.setattr(cleanup_owner, "repair", repair)
    [root_slot] = quarantine.observe_attempts(
        acquired.operation_id, acquired.attempt_epoch, ("root",)
    )
    root_attempt_path = quarantine.root / root_slot.attempt_name
    moved_attempt_path = quarantine.root / "moved-attempt"
    root_attempt_path.rename(moved_attempt_path)
    try:
        with pytest.raises(PackageProductRebindCleanupReadError) as moved:
            decision(third).recover_acquired_claim(
                acquired.operation_id, max_bytes=1024, admission=third
            )
        assert moved.value.code == "package_rebind_quarantine_not_empty"
        assert cleanup_owner.read_operation_tombstones(acquired.operation_id)[
            0
        ].disposition == "cleanup_retryable"
    finally:
        moved_attempt_path.rename(root_attempt_path)

    restart_after_cleanup = lifecycle.restart_after_cleanup

    def crash_before_restart(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("crash after cleanup completion")

    monkeypatch.setattr(lifecycle, "restart_after_cleanup", crash_before_restart)
    with pytest.raises(RuntimeError, match="crash after cleanup completion"):
        decision(third).recover_acquired_claim(
            acquired.operation_id, max_bytes=1024, admission=third
        )
    assert cleanup_owner.read_operation_tombstones(acquired.operation_id)[
        0
    ].disposition == "cleanup_complete"
    assert quarantine.attempt_names() == ()
    still_failed = lifecycle.read_operation(acquired.operation_id)
    assert still_failed is not None
    assert still_failed[1].phase == acquired.phase
    monkeypatch.setattr(lifecycle, "restart_after_cleanup", restart_after_cleanup)

    restarted = decision(third).recover_acquired_claim(
        acquired.operation_id, max_bytes=1024, admission=third
    )
    assert restarted.restart.expected_attempt_epoch == acquired.attempt_epoch
    assert restarted.status.phase == "classified"
    assert restarted.status.disposition == "retryable_failure"
    assert quarantine.attempt_names() == ()
    tombstones = cleanup_owner.read_operation_tombstones(acquired.operation_id)
    assert len(tombstones) == 1
    assert tombstones[0].disposition == "cleanup_complete"
    after = lifecycle.path.read_bytes()
    assert (
        decision(third).recover_acquired_claim(
            acquired.operation_id, max_bytes=1024, admission=third
        )
        == restarted
    )
    with pytest.raises(PackageProductRebindCleanupReadError) as wrong_route:
        decision(third).recover_resolving_claim(
            acquired.operation_id, max_bytes=1024, admission=third
        )
    assert wrong_route.value.code == "package_rebind_claim_not_resolving"
    assert lifecycle.path.read_bytes() == after
    selected = decision(third).prepare(
        acquired.operation_id, max_bytes=1024, admission=third
    )
    assert selected.decision.source_proof_ref == restarted.restart.source_proof_ref
    assert (
        selected.decision.cleanup_evidence_ref
        == restarted.restart.cleanup_evidence_ref
    )
    _selected, fresh_claim, _route = decision(third).resume(
        acquired.operation_id, max_bytes=1024, admission=third
    )
    assert fresh_claim.phase == "classified"
    assert fresh_claim.attempt_epoch == acquired.attempt_epoch + 1


def test_product_source_reader_binds_exact_owner_selection_and_bytes(
    tmp_path: Path,
) -> None:
    policy, owner, lifecycle, resolution, environment, status, dependency = _fixture(
        tmp_path
    )
    for next_phase in (
        "acquiring",
        "acquired",
        "inspecting",
        "extracted",
        "resolving_closure",
    ):
        status = owner.advance(
            status.operation_id,
            next_phase=next_phase,
            expected_phase=status.phase,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
        )
    failed = owner.interrupt(
        status.operation_id,
        expected_phase=status.phase,
        expected_journal_revision=status.journal_revision,
        expected_attempt_epoch=status.attempt_epoch,
    )
    selection_request = PackageDependencySelectionRequestV1(
        operation_id=failed.operation_id,
        attempt_epoch=failed.attempt_epoch,
        parent_node_id="root",
        request_fingerprint=failed.request_fingerprint,
        resolution_environment_fingerprint=environment.fingerprint,
        requirement=NormalizedPackageRequirementV1.parse("helper==2.0"),
    )
    resolution.bind_basis(
        PackageClosureResolutionBasisV1(
            operation_id=failed.operation_id,
            attempt_epoch=failed.attempt_epoch,
            request_fingerprint=failed.request_fingerprint,
            policy_revision=policy.policy_revision,
            quota_profile_revision=policy.quota_profile_revision,
            resolution_environment=environment,
            budgets=PackageClosureBudgetV1(),
        )
    )
    selection = policy.resolve(selection_request)
    resolution.append_selection(selection_request, selection)
    reader = PackageProductRebindSourceReader(
        policy=policy, lifecycle=lifecycle, resolution=resolution
    )
    before = (lifecycle.path.read_bytes(), resolution.path.read_bytes())

    observation = reader.observe(failed.operation_id, max_bytes=1024)
    assert observation.request_fingerprint == failed.request_fingerprint
    assert observation.attempt_revision == failed.attempt_revision
    assert observation.artifact_digests == (
        policy.bindings[0].artifact_digest,
        policy.dependencies[0].artifact_digest,
    )
    assert len(observation.source_proof_ref) == 64
    assert reader.observe(failed.operation_id, max_bytes=1024) == observation
    assert (lifecycle.path.read_bytes(), resolution.path.read_bytes()) == before

    second_request = replace(selection_request, parent_node_id="second-parent")
    resolution.append_selection(second_request, policy.resolve(second_request))
    later = reader.observe(failed.operation_id, max_bytes=1024)
    assert later.artifact_digests == observation.artifact_digests
    assert later.source_proof_ref != observation.source_proof_ref

    dependency.write_bytes(b"changed-dependency")
    with pytest.raises(PackageProductRebindSourceError) as changed:
        reader.observe(failed.operation_id, max_bytes=1024)
    assert changed.value.code == "package_source_digest_mismatch"

    dependency.write_bytes(b"dependency-wheel")
    changed_policy = replace(policy, policy_revision="source-policy:2")
    with pytest.raises(PackageProductRebindSourceError):
        PackageProductRebindSourceReader(
            policy=changed_policy, lifecycle=lifecycle, resolution=resolution
        ).observe(failed.operation_id, max_bytes=1024)

    with resolution.path.open("ab") as output:
        output.write(b'{"partial":')
    corrupted = resolution.path.read_bytes()
    with pytest.raises(PackageClosureResolutionJournalError):
        reader.observe(failed.operation_id, max_bytes=1024)
    assert resolution.path.read_bytes() == corrupted


def test_product_source_reader_refuses_missing_resolution_basis(
    tmp_path: Path,
) -> None:
    policy, owner, lifecycle, resolution, _environment, status, _dependency = _fixture(
        tmp_path
    )
    for next_phase in (
        "acquiring",
        "acquired",
        "inspecting",
        "extracted",
        "resolving_closure",
    ):
        status = owner.advance(
            status.operation_id,
            next_phase=next_phase,
            expected_phase=status.phase,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
        )
    failed = owner.interrupt(
        status.operation_id,
        expected_phase=status.phase,
        expected_journal_revision=status.journal_revision,
        expected_attempt_epoch=status.attempt_epoch,
    )
    reader = PackageProductRebindSourceReader(
        policy=policy, lifecycle=lifecycle, resolution=resolution
    )
    with pytest.raises(PackageProductRebindSourceReadError) as missing:
        reader.observe(failed.operation_id, max_bytes=1024)
    assert missing.value.code == "package_rebind_resolution_basis_missing"
    assert not resolution.path.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-relative proof")
def test_product_rebind_proofs_survive_pending_decision_revisions(
    tmp_path: Path,
) -> None:
    policy, owner, lifecycle, resolution, _environment, status, _dependency = _fixture(
        tmp_path
    )
    failed = owner.interrupt(
        status.operation_id,
        expected_phase=status.phase,
        expected_journal_revision=status.journal_revision,
        expected_attempt_epoch=status.attempt_epoch,
    )
    source = PackageProductRebindSourceReader(
        policy=policy, lifecycle=lifecycle, resolution=resolution
    )
    quarantine = PackageQuarantineStore(tmp_path / "quarantine")
    cleanup = PackageProductRebindCleanupReader(
        lifecycle=lifecycle,
        resolution=resolution,
        artifacts=PackageArtifactEvidenceJournal(tmp_path / "artifacts.jsonl"),
        cleanup=PackageQuarantineCleanupOwner(
            journal=PackageQuarantineCleanupJournal(tmp_path / "cleanup.jsonl"),
            store=quarantine,
        ),
        quarantine=quarantine,
        pins=PackageTransactionPinJournal(tmp_path / "pins.jsonl"),
        staging=PackageArtifactStagingJournal(tmp_path / "staging.jsonl"),
        committed_sets=PackageCommittedSetJournal(tmp_path / "committed-sets.jsonl"),
        handoff=PackageRetentionHandoffJournal(tmp_path / "handoff.jsonl"),
    )
    initial_source = source.observe(failed.operation_id, max_bytes=1024)
    initial_cleanup = cleanup.observe(failed.operation_id)
    first = PackageLifecycleRebindRequestV1(
        operation_id=failed.operation_id,
        request_fingerprint=failed.request_fingerprint,
        expected_attempt_epoch=failed.attempt_epoch,
        expected_attempt_revision=failed.attempt_revision,
        new_runtime_admission_request_id="1" * 64,
        source_proof_ref=initial_source.source_proof_ref,
        cleanup_evidence_ref=initial_cleanup.known_cleanup_ref,
        lease_snapshot_id="2" * 64,
    )
    first_record = lifecycle.record_rebind(first)
    pending_source = source.observe(failed.operation_id, max_bytes=1024)
    pending_cleanup = cleanup.observe(failed.operation_id)
    assert pending_source.attempt_revision == first_record.record_revision
    assert pending_cleanup.attempt_revision == first_record.record_revision
    assert pending_source.source_proof_ref == initial_source.source_proof_ref
    assert pending_cleanup.known_cleanup_ref == initial_cleanup.known_cleanup_ref

    second = replace(
        first,
        expected_attempt_revision=first_record.record_revision,
        new_runtime_admission_request_id="3" * 64,
    )
    lifecycle.supersede_rebind(
        second,
        supersedes_decision_id=first.decision_id,
        expected_prior_rebind_record_revision=first_record.record_revision,
    )
    assert source.observe(failed.operation_id, max_bytes=1024).source_proof_ref == (
        first.source_proof_ref
    )
    assert cleanup.observe(failed.operation_id).known_cleanup_ref == (
        first.cleanup_evidence_ref
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-relative proof")
def test_quarantine_known_entry_observation_refuses_unattributed_or_moved_entry(
    tmp_path: Path,
) -> None:
    quarantine = PackageQuarantineStore(tmp_path / "quarantine")
    attempt_name = "attempt-" + "a" * 64
    attempt = quarantine.root / attempt_name
    attempt.mkdir(mode=0o700)
    stat_result = attempt.stat()
    known = ((attempt_name, (stat_result.st_dev, stat_result.st_ino)),)
    assert quarantine.observe_known_entries(known) == quarantine._root_identity

    (quarantine.root / "unknown").write_bytes(b"residue")
    with pytest.raises(OSError, match="unattributed"):
        quarantine.observe_known_entries(known)
    (quarantine.root / "unknown").unlink()

    attempt.rename(quarantine.root / "moved")
    with pytest.raises(OSError, match="unattributed"):
        quarantine.observe_known_entries(known)
    (quarantine.root / "moved").rename(attempt)
    assert quarantine.observe_known_entries(known) == quarantine._root_identity
    attempt.rename(quarantine.root / "moved")
    attempt.symlink_to(quarantine.root / "moved", target_is_directory=True)
    with pytest.raises(OSError):
        quarantine.observe_known_entries(known)


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-relative proof")
def test_product_cleanup_reader_observes_known_slots_without_mutation(
    tmp_path: Path,
) -> None:
    _policy, owner, lifecycle, resolution, _environment, status, _dependency = _fixture(
        tmp_path
    )
    failed = owner.interrupt(
        status.operation_id,
        expected_phase=status.phase,
        expected_journal_revision=status.journal_revision,
        expected_attempt_epoch=status.attempt_epoch,
    )
    artifacts = PackageArtifactEvidenceJournal(tmp_path / "artifact-evidence.jsonl")
    quarantine = PackageQuarantineStore(tmp_path / "quarantine")
    cleanup = PackageQuarantineCleanupOwner(
        journal=PackageQuarantineCleanupJournal(tmp_path / "cleanup.jsonl"),
        store=quarantine,
    )
    reader = PackageProductRebindCleanupReader(
        lifecycle=lifecycle,
        resolution=resolution,
        artifacts=artifacts,
        cleanup=cleanup,
        quarantine=quarantine,
        pins=PackageTransactionPinJournal(tmp_path / "pins.jsonl"),
        staging=PackageArtifactStagingJournal(tmp_path / "staging.jsonl"),
        committed_sets=PackageCommittedSetJournal(tmp_path / "committed-sets.jsonl"),
        handoff=PackageRetentionHandoffJournal(tmp_path / "handoff.jsonl"),
    )
    before = tuple(sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")))

    observation = reader.observe(failed.operation_id)

    assert observation.attempt_revision == failed.attempt_revision
    assert tuple(item.node_id for item in observation.known_attempts) == ("root",)
    assert observation.known_attempts[0].attempt_identity is None
    assert observation.store_identity == quarantine._root_identity
    assert len(observation.known_cleanup_ref) == 64
    assert (
        tuple(sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")))
        == before
    )

    (quarantine.root / observation.known_attempts[0].attempt_name).mkdir(mode=0o700)
    with pytest.raises(PackageProductRebindCleanupReadError) as residue:
        reader.observe(failed.operation_id)
    assert residue.value.code == "package_rebind_quarantine_residue"

    [present] = quarantine.observe_attempts(failed.operation_id, 1, ("root",))
    assert present.attempt_identity is not None
    target_fields = {
        "attemptEpoch": 1,
        "attemptIdentity": list(present.attempt_identity),
        "attemptName": present.attempt_name,
        "nodeId": "root",
        "operationId": failed.operation_id,
        "storeIdentity": list(present.store_identity),
    }
    target = PackageQuarantineCleanupTargetV1(
        operation_id=failed.operation_id,
        attempt_epoch=1,
        node_id="root",
        store_identity=present.store_identity,
        attempt_identity=present.attempt_identity,
        attempt_name=present.attempt_name,
        cleanup_id=sha256(canonical_json_bytes(target_fields)).hexdigest(),
    )
    pending = cleanup.record_pending(
        target, rejection_code="package_source_unavailable", rejection_stage="acquiring"
    )
    with pytest.raises(PackageProductRebindCleanupReadError) as debt:
        reader.observe(failed.operation_id)
    assert debt.value.code == "package_rebind_cleanup_pending"
    cleanup.repair(
        target.cleanup_id, expected_cleanup_revision=pending.cleanup_revision
    )
    settled = reader.observe(failed.operation_id)
    assert settled.cleanup_ids == (target.cleanup_id,)
    assert settled.known_cleanup_ref != observation.known_cleanup_ref

    (quarantine.root / "unattributed-residue").write_bytes(b"debt")
    with pytest.raises(PackageProductRebindCleanupReadError) as unattributed:
        reader.observe(failed.operation_id)
    assert unattributed.value.code == "package_rebind_quarantine_not_empty"
    (quarantine.root / "unattributed-residue").unlink()

    wrong_slot_fields = {
        **target_fields,
        "attemptIdentity": [0, 0],
        "attemptName": "attempt-" + "0" * 64,
    }
    wrong_slot = PackageQuarantineCleanupTargetV1(
        operation_id=failed.operation_id,
        attempt_epoch=1,
        node_id="root",
        store_identity=present.store_identity,
        attempt_identity=(0, 0),
        attempt_name=wrong_slot_fields["attemptName"],
        cleanup_id=sha256(canonical_json_bytes(wrong_slot_fields)).hexdigest(),
    )
    wrong_pending = cleanup.record_pending(
        wrong_slot,
        rejection_code="package_source_unavailable",
        rejection_stage="acquiring",
    )
    cleanup.repair(
        wrong_slot.cleanup_id,
        expected_cleanup_revision=wrong_pending.cleanup_revision,
    )
    with pytest.raises(PackageProductRebindCleanupReadError) as changed:
        reader.observe(failed.operation_id)
    assert changed.value.code == "package_rebind_cleanup_target_changed"

    with artifacts.path.open("ab") as output:
        output.write(b'{"partial":')
    with journal_file_lock(artifacts.path, "exclusive"):
        pass
    corrupt = artifacts.path.read_bytes()
    with pytest.raises(PackageArtifactEvidenceJournalError):
        reader.observe(failed.operation_id)
    assert artifacts.path.read_bytes() == corrupt


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-relative proof")
def test_product_rebind_cleanup_refuses_incomplete_pin_evidence(
    tmp_path: Path,
) -> None:
    _policy, owner, lifecycle, resolution, _environment, status, _dependency = (
        _fixture(tmp_path)
    )
    failed = owner.interrupt(
        status.operation_id,
        expected_phase=status.phase,
        expected_journal_revision=status.journal_revision,
        expected_attempt_epoch=status.attempt_epoch,
    )
    quarantine = PackageQuarantineStore(tmp_path / "quarantine")
    pins = PackageTransactionPinJournal(tmp_path / "pins.jsonl")
    reader = PackageProductRebindCleanupReader(
        lifecycle=lifecycle,
        resolution=resolution,
        artifacts=PackageArtifactEvidenceJournal(tmp_path / "artifacts.jsonl"),
        cleanup=PackageQuarantineCleanupOwner(
            journal=PackageQuarantineCleanupJournal(tmp_path / "cleanup.jsonl"),
            store=quarantine,
        ),
        quarantine=quarantine,
        pins=pins,
        staging=PackageArtifactStagingJournal(tmp_path / "staging.jsonl"),
        committed_sets=PackageCommittedSetJournal(tmp_path / "committed-sets.jsonl"),
        handoff=PackageRetentionHandoffJournal(tmp_path / "handoff.jsonl"),
    )
    assert reader.observe(failed.operation_id).attempt_epoch == failed.attempt_epoch
    pins.path.write_bytes(b'{"partial":')
    with journal_file_lock(pins.path, "exclusive"):
        pass
    before = pins.path.read_bytes()
    with pytest.raises(PackageTransactionPinJournalError):
        reader.observe(failed.operation_id)
    assert pins.path.read_bytes() == before


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-relative proof")
def test_product_rebind_cleanup_refuses_incomplete_staging_evidence(
    tmp_path: Path,
) -> None:
    _policy, owner, lifecycle, resolution, _environment, status, _dependency = (
        _fixture(tmp_path)
    )
    failed = owner.interrupt(
        status.operation_id,
        expected_phase=status.phase,
        expected_journal_revision=status.journal_revision,
        expected_attempt_epoch=status.attempt_epoch,
    )
    quarantine = PackageQuarantineStore(tmp_path / "quarantine")
    staging = PackageArtifactStagingJournal(tmp_path / "staging.jsonl")
    reader = PackageProductRebindCleanupReader(
        lifecycle=lifecycle,
        resolution=resolution,
        artifacts=PackageArtifactEvidenceJournal(tmp_path / "artifacts.jsonl"),
        cleanup=PackageQuarantineCleanupOwner(
            journal=PackageQuarantineCleanupJournal(tmp_path / "cleanup.jsonl"),
            store=quarantine,
        ),
        quarantine=quarantine,
        pins=PackageTransactionPinJournal(tmp_path / "pins.jsonl"),
        staging=staging,
        committed_sets=PackageCommittedSetJournal(tmp_path / "committed-sets.jsonl"),
        handoff=PackageRetentionHandoffJournal(tmp_path / "handoff.jsonl"),
    )
    assert reader.observe(failed.operation_id).attempt_epoch == failed.attempt_epoch
    staging.path.write_bytes(b'{"partial":')
    with journal_file_lock(staging.path, "exclusive"):
        pass
    before = staging.path.read_bytes()
    with pytest.raises(PackageArtifactStagingJournalError):
        reader.observe(failed.operation_id)
    assert staging.path.read_bytes() == before


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-relative proof")
def test_product_rebind_cleanup_refuses_current_attempt_pin_history(
    tmp_path: Path,
) -> None:
    _policy, owner, lifecycle, resolution, environment, status, _dependency = (
        _fixture(tmp_path)
    )
    failed = owner.interrupt(
        status.operation_id,
        expected_phase=status.phase,
        expected_journal_revision=status.journal_revision,
        expected_attempt_epoch=status.attempt_epoch,
    )
    quarantine = PackageQuarantineStore(tmp_path / "quarantine")
    pins = PackageTransactionPinJournal(tmp_path / "pins.jsonl")
    reader = PackageProductRebindCleanupReader(
        lifecycle=lifecycle,
        resolution=resolution,
        artifacts=PackageArtifactEvidenceJournal(tmp_path / "artifacts.jsonl"),
        cleanup=PackageQuarantineCleanupOwner(
            journal=PackageQuarantineCleanupJournal(tmp_path / "cleanup.jsonl"),
            store=quarantine,
        ),
        quarantine=quarantine,
        pins=pins,
        staging=PackageArtifactStagingJournal(tmp_path / "staging.jsonl"),
        committed_sets=PackageCommittedSetJournal(tmp_path / "committed-sets.jsonl"),
        handoff=PackageRetentionHandoffJournal(tmp_path / "handoff.jsonl"),
    )
    assert reader.observe(failed.operation_id).attempt_epoch == failed.attempt_epoch
    node = VerifiedClosurePlanNodeV2(
        node_id="root",
        role="root",
        distribution="acme-plugin",
        version="1.0",
        canonical_source_identity="source:root",
        source_envelope_fingerprint="a" * 64,
        acquisition_receipt_fingerprint="b" * 64,
        wheel_evidence_fingerprint="c" * 64,
        artifact_digest="d" * 64,
        extraction_tree_digest="e" * 64,
        selected_extras=(),
        requirements=(),
        selected_edges=(),
    )
    plan = VerifiedClosurePlanV2.create(
        operation_id=failed.operation_id,
        attempt_epoch=failed.attempt_epoch,
        root_node_id=node.node_id,
        resolution_environment_fingerprint=environment.fingerprint,
        nodes=(node,),
        max_depth=0,
    )
    request = PackageTransactionPinRequestV1.create(
        plan,
        request_fingerprint=failed.request_fingerprint,
        classification_fingerprint="f" * 64,
        recovery_identity="recovery:test",
    )
    acquired = PackageTransactionPinReceiptV1.acquire(
        request,
        pin_id="1" * 64,
        owner_identity="retention-owner",
        owner_revision=1,
        lease_id="lease:test",
        lease_revision=1,
    )
    pins.append(acquired)
    with pytest.raises(PackageProductRebindCleanupReadError) as pinned:
        reader.observe(failed.operation_id)
    assert pinned.value.code == "package_rebind_pin_effects"
    released = PackageTransactionPinReceiptV1.transition(
        acquired,
        state="released",
        owner_revision=2,
        lease_revision=2,
        transition_evidence_ref="2" * 64,
    )
    pins.append(released)
    with pytest.raises(PackageProductRebindCleanupReadError) as released_history:
        reader.observe(failed.operation_id)
    assert released_history.value.code == "package_rebind_pin_effects"
