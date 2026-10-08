from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.harness.plugin_management.package_operation_explanation import (
    PackageOperationExplanationProjector,
)
from loushang.harness.resources.packages.plugin_lifecycle import (
    PackageClassificationBasisFactV1,
    PackageClassificationFactsV1,
    PackageLifecycleIngressRequestV1,
    PackageLifecycleJournal,
    PackageLifecycleJournalError,
    PackageLifecycleOwner,
    PackageLifecycleRetryRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleFailureV1,
    PackageLifecycleIngressRequestV2,
    PackageLifecyclePhase,
    PackageLifecyclePinnedAdoptionRequestV1,
    PackageLifecycleRebindRecordV1,
    PackageLifecycleRebindRequestV1,
    PackageLifecycleRequestV2,
    PackageLifecycleRestartRequestV1,
    PackageLifecycleStagingAdoptionRequestV1,
    PackageLifecycleStatusV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging import (
    PackagePluginRootTargetV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging_set_runtime import (
    PackageStagingCheckpointV1,
)


class _Authority:
    def classification_facts(
        self, _request: PackageLifecycleIngressRequestV1
    ) -> PackageClassificationFactsV1:
        kinds = (
            "explicit_plugin_intent",
            "existing_plugin_binding",
            "existing_plugin_history",
            "independent_non_plugin_authority",
        )
        return PackageClassificationFactsV1(
            facts=tuple(
                PackageClassificationBasisFactV1(
                    kind=kind,  # type: ignore[arg-type]
                    present=kind == "explicit_plugin_intent",
                    authority_id=f"authority:{kind}",
                    owner_revision=f"revision:{kind}:1",
                )
                for kind in kinds
            ),
            policy_revision="classification-policy:1",
            classifier_epoch=1,
        )


def _owner(tmp_path: Path) -> tuple[PackageLifecycleOwner, PackageLifecycleJournal]:
    journal = PackageLifecycleJournal(tmp_path / "package-lifecycle.jsonl")
    return (
        PackageLifecycleOwner(
            journal=journal,
            classification_authority=_Authority(),
            enabled=True,
        ),
        journal,
    )


def _ingress() -> PackageLifecycleIngressRequestV1:
    return PackageLifecycleIngressRequestV1(
        operation_id="phase-operation",
        action="install",
        product_id="coding",
        scope_id="workspace:phase",
        requested_package="acme-plugin==1.0",
        requested_plugin_id="acme.plugin",
        source_locator="https://packages.example.test/acme.whl?token=secret",
        policy_revision="package-policy:1",
        quota_profile_revision="quota:1",
        resolution_environment_fingerprint="e" * 64,
    )


def test_interrupt_can_require_exact_attempt_revision(tmp_path: Path) -> None:
    owner, journal = _owner(tmp_path)
    classified = owner.submit(_ingress())
    before = journal.path.read_bytes()
    with pytest.raises(PackageLifecycleJournalError) as stale:
        journal.interrupt(
            classified.operation_id,
            expected_phase=classified.phase,
            expected_journal_revision=classified.journal_revision,
            expected_attempt_epoch=classified.attempt_epoch,
            expected_attempt_revision=classified.attempt_revision + 1,
        )
    assert stale.value.code == "package_attempt_stale"
    assert journal.path.read_bytes() == before
    interrupted = journal.interrupt(
        classified.operation_id,
        expected_phase=classified.phase,
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
        expected_attempt_revision=classified.attempt_revision,
    )
    assert interrupted.disposition == "retryable_failure"


def test_cleanup_bound_restart_rewinds_only_failed_effectful_attempt(
    tmp_path: Path,
) -> None:
    owner, journal = _owner(tmp_path)
    ingress = PackageLifecycleIngressRequestV2.bind_runtime_admission(
        _ingress(), runtime_admission_request_id="1" * 64
    )
    current = owner.submit(ingress)
    for phase in ("acquiring", "acquired"):
        current = owner.advance(
            current.operation_id,
            next_phase=phase,
            expected_phase=current.phase,
            expected_journal_revision=current.journal_revision,
            expected_attempt_epoch=current.attempt_epoch,
        )
    failed = owner.interrupt(
        current.operation_id,
        expected_phase=current.phase,
        expected_journal_revision=current.journal_revision,
        expected_attempt_epoch=current.attempt_epoch,
    )
    request = PackageLifecycleRestartRequestV1(
        operation_id=failed.operation_id,
        request_fingerprint=failed.request_fingerprint,
        expected_phase="acquired",
        expected_journal_revision=failed.journal_revision,
        expected_attempt_epoch=failed.attempt_epoch,
        expected_attempt_revision=failed.attempt_revision,
        source_proof_ref="2" * 64,
        cleanup_evidence_ref="3" * 64,
        lease_snapshot_id="4" * 64,
    )
    before_stale = journal.path.read_bytes()
    with pytest.raises(PackageLifecycleJournalError) as stale:
        journal.restart_after_cleanup(
            replace(request, expected_attempt_revision=failed.attempt_revision + 1)
        )
    assert stale.value.code == "package_restart_attempt_conflict"
    assert journal.path.read_bytes() == before_stale
    restarted = journal.restart_after_cleanup(request)
    assert restarted.restart == request
    assert restarted.status.phase == "classified"
    assert restarted.status.disposition == "retryable_failure"
    assert restarted.status.attempt_epoch == failed.attempt_epoch
    assert restarted.status.attempt_revision > failed.attempt_revision
    assert restarted.status.journal_revision == failed.journal_revision
    before_replay = journal.path.read_bytes()
    assert journal.restart_after_cleanup(request) == restarted
    assert journal.path.read_bytes() == before_replay
    reopened_journal = PackageLifecycleJournal(journal.path)
    assert reopened_journal.latest_restart(failed.operation_id) == restarted
    with pytest.raises(PackageLifecycleJournalError) as changed:
        journal.restart_after_cleanup(replace(request, cleanup_evidence_ref="5" * 64))
    assert changed.value.code == "package_restart_attempt_conflict"
    assert journal.path.read_bytes() == before_replay

    decision = PackageLifecycleRebindRequestV1(
        operation_id=failed.operation_id,
        request_fingerprint=failed.request_fingerprint,
        expected_attempt_epoch=restarted.status.attempt_epoch,
        expected_attempt_revision=restarted.status.attempt_revision,
        new_runtime_admission_request_id="6" * 64,
        source_proof_ref="2" * 64,
        cleanup_evidence_ref="3" * 64,
        lease_snapshot_id="4" * 64,
    )
    before_changed_refs = journal.path.read_bytes()
    with pytest.raises(PackageLifecycleJournalError) as changed_refs:
        reopened_journal.record_rebind(
            replace(decision, cleanup_evidence_ref="8" * 64)
        )
    assert changed_refs.value.code == "package_rebind_restart_evidence_changed"
    assert journal.path.read_bytes() == before_changed_refs
    selected = reopened_journal.record_rebind(decision)
    reopened_owner = PackageLifecycleOwner(
        journal=reopened_journal,
        classification_authority=_Authority(),
        enabled=True,
    )
    resumed = reopened_owner.resume_rebind(
        decision, expected_rebind_record_revision=selected.record_revision
    )
    assert resumed.phase == "classified"
    assert resumed.disposition == "active"
    assert resumed.attempt_epoch == failed.attempt_epoch + 1
    assert journal.request(failed.operation_id) == (
        ingress.bind_classification_facts(current.classification.basis_facts)
    )
    encoded = journal.path.read_text(encoding="utf-8").splitlines()
    restart_line = next(
        index
        for index, line in enumerate(encoded)
        if json.loads(line)["recordKind"] == "restart"
    )
    changed_record = json.loads(encoded[restart_line])
    changed_record["restart"]["cleanupEvidenceRef"] = "7" * 64
    encoded[restart_line] = json.dumps(changed_record, sort_keys=True)
    journal.path.write_text("\n".join(encoded) + "\n", encoding="utf-8")
    with pytest.raises(PackageLifecycleJournalError) as tampered:
        PackageLifecycleJournal(journal.path).read_operation(failed.operation_id)
    assert tampered.value.code == "package_lifecycle_journal_corrupt"


def test_cleanup_bound_restart_refuses_a_pending_rebind(tmp_path: Path) -> None:
    owner, journal = _owner(tmp_path)
    ingress = PackageLifecycleIngressRequestV2.bind_runtime_admission(
        _ingress(), runtime_admission_request_id="1" * 64
    )
    current = owner.submit(ingress)
    for phase in ("acquiring", "acquired"):
        current = owner.advance(
            current.operation_id,
            next_phase=phase,
            expected_phase=current.phase,
            expected_journal_revision=current.journal_revision,
            expected_attempt_epoch=current.attempt_epoch,
        )
    failed = owner.interrupt(
        current.operation_id,
        expected_phase=current.phase,
        expected_journal_revision=current.journal_revision,
        expected_attempt_epoch=current.attempt_epoch,
    )
    decision = PackageLifecycleRebindRequestV1(
        operation_id=failed.operation_id,
        request_fingerprint=failed.request_fingerprint,
        expected_attempt_epoch=failed.attempt_epoch,
        expected_attempt_revision=failed.attempt_revision,
        new_runtime_admission_request_id="2" * 64,
        source_proof_ref="3" * 64,
        cleanup_evidence_ref="4" * 64,
        lease_snapshot_id="5" * 64,
    )
    pending = journal.record_rebind(decision)
    restart = PackageLifecycleRestartRequestV1(
        operation_id=failed.operation_id,
        request_fingerprint=failed.request_fingerprint,
        expected_phase="acquired",
        expected_journal_revision=failed.journal_revision,
        expected_attempt_epoch=failed.attempt_epoch,
        expected_attempt_revision=pending.status.attempt_revision,
        source_proof_ref="3" * 64,
        cleanup_evidence_ref="4" * 64,
        lease_snapshot_id="5" * 64,
    )
    before = journal.path.read_bytes()
    with pytest.raises(PackageLifecycleJournalError) as refused:
        journal.restart_after_cleanup(restart)
    assert refused.value.code == "package_restart_attempt_conflict"
    assert journal.path.read_bytes() == before


@pytest.mark.parametrize(
    "failed_phase",
    [
        "acquiring",
        "acquired",
        "inspecting",
        "extracted",
        "resolving_closure",
        "closure_verified",
    ],
)
def test_cleanup_bound_restart_journal_phase_limit(
    tmp_path: Path, failed_phase: PackageLifecyclePhase
) -> None:
    owner, journal = _owner(tmp_path)
    ingress = PackageLifecycleIngressRequestV2.bind_runtime_admission(
        _ingress(), runtime_admission_request_id="1" * 64
    )
    current = owner.submit(ingress)
    for phase in (
        "acquiring",
        "acquired",
        "inspecting",
        "extracted",
        "resolving_closure",
        "closure_verified",
    ):
        current = owner.advance(
            current.operation_id,
            next_phase=phase,
            expected_phase=current.phase,
            expected_journal_revision=current.journal_revision,
            expected_attempt_epoch=current.attempt_epoch,
        )
        if phase == failed_phase:
            break
    failed = owner.interrupt(
        current.operation_id,
        expected_phase=current.phase,
        expected_journal_revision=current.journal_revision,
        expected_attempt_epoch=current.attempt_epoch,
    )
    restart = PackageLifecycleRestartRequestV1(
        operation_id=failed.operation_id,
        request_fingerprint=failed.request_fingerprint,
        expected_phase=failed_phase,
        expected_journal_revision=failed.journal_revision,
        expected_attempt_epoch=failed.attempt_epoch,
        expected_attempt_revision=failed.attempt_revision,
        source_proof_ref="2" * 64,
        cleanup_evidence_ref="3" * 64,
        lease_snapshot_id="4" * 64,
    )
    assert journal.restart_after_cleanup(restart).status.phase == "classified"
    assert PackageLifecycleJournal(journal.path).status(failed.operation_id).phase == (
        "classified"
    )
    with pytest.raises(ValueError, match="Unsupported Package restart phase"):
        replace(restart, expected_phase="transaction_pinned")


def test_package_operation_read_does_not_create_or_repair_owner_state(
    tmp_path: Path,
) -> None:
    owner, journal = _owner(tmp_path)
    lock = journal.path.with_name(f"{journal.path.name}.lock")
    assert journal.read_operation("missing") is None
    assert journal.latest_rebind("missing") is None
    assert journal.latest_restart("missing") is None
    unknown = PackageOperationExplanationProjector(
        journal, clock_ns=lambda: 123
    ).explain_operation("missing")
    assert unknown.status == "unknown"
    assert not journal.path.exists()
    assert not lock.exists()

    submitted = owner.submit(_ingress())
    observed = journal.read_operation(submitted.operation_id)
    assert observed is not None
    request, status = observed
    assert request.operation_id == submitted.operation_id
    assert status == submitted

    with journal.path.open("ab") as output:
        output.write(b'{"partial":')
    original = journal.path.read_bytes()
    with pytest.raises(PackageLifecycleJournalError) as invalid:
        journal.read_operation(submitted.operation_id)
    assert invalid.value.code == "package_lifecycle_journal_corrupt"
    assert journal.path.read_bytes() == original


def test_phase_cas_advances_only_one_proved_edge_and_replays_exactly_once(
    tmp_path: Path,
) -> None:
    owner, journal = _owner(tmp_path)
    classified = owner.submit(_ingress())

    acquiring = owner.advance(
        classified.operation_id,
        next_phase="acquiring",
        expected_phase="classified",
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
    )
    record_count = len(journal.records())
    replay = owner.advance(
        classified.operation_id,
        next_phase="acquiring",
        expected_phase="classified",
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
    )

    assert replay == acquiring
    assert len(journal.records()) == record_count
    assert acquiring.phase == "acquiring"
    assert acquiring.disposition == "active"
    with pytest.raises(PackageLifecycleJournalError) as skipped:
        owner.advance(
            classified.operation_id,
            next_phase="inspecting",
            expected_phase="acquiring",
            expected_journal_revision=acquiring.journal_revision,
            expected_attempt_epoch=acquiring.attempt_epoch,
        )
    assert skipped.value.code == "package_operation_phase_transition_invalid"
    assert journal.status(classified.operation_id) == acquiring


def test_retryable_acquisition_failure_uses_attempt_domain_and_fenced_retry(
    tmp_path: Path,
) -> None:
    owner, journal = _owner(tmp_path)
    classified = owner.submit(_ingress())
    acquiring = owner.advance(
        classified.operation_id,
        next_phase="acquiring",
        expected_phase="classified",
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
    )
    failure = PackageLifecycleFailureV1.for_operation(
        "package_acquisition_limit_exceeded",
        stage="acquiring",
        operation_id=acquiring.operation_id,
        evidence_ref="a" * 64,
        details=("condition:no_acquired_digest",),
    )

    failed = owner.record_failure(
        failure,
        expected_phase="acquiring",
        expected_journal_revision=acquiring.journal_revision,
        expected_attempt_epoch=acquiring.attempt_epoch,
    )
    record_count = len(journal.records())
    replay = owner.record_failure(
        failure,
        expected_phase="acquiring",
        expected_journal_revision=acquiring.journal_revision,
        expected_attempt_epoch=acquiring.attempt_epoch,
    )

    assert replay == failed
    assert len(journal.records()) == record_count
    assert failed.disposition == "retryable_failure"
    assert failed.journal_revision == acquiring.journal_revision
    assert failed.attempt_revision > acquiring.attempt_revision
    retry = owner.retry(
        PackageLifecycleRetryRequestV1(
            operation_id=failed.operation_id,
            request_fingerprint=failed.request_fingerprint,
            expected_attempt_epoch=failed.attempt_epoch,
        )
    )
    assert retry.phase == "acquiring"
    assert retry.attempt_epoch == 2
    stale_record_count = len(journal.records())
    stale = owner.record_failure(
        failure,
        expected_phase="acquiring",
        expected_journal_revision=acquiring.journal_revision,
        expected_attempt_epoch=1,
    )
    assert stale.failure is not None
    assert stale.failure.code == "package_attempt_stale"
    assert len(journal.records()) == stale_record_count


def test_terminal_failure_can_bind_the_immediate_failure_stage(tmp_path: Path) -> None:
    owner, journal = _owner(tmp_path)
    classified = owner.submit(_ingress())
    acquiring = owner.advance(
        classified.operation_id,
        next_phase="acquiring",
        expected_phase="classified",
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
    )
    failure = PackageLifecycleFailureV1.for_operation(
        "package_acquisition_digest_mismatch",
        stage="acquired",
        operation_id=acquiring.operation_id,
        evidence_ref="b" * 64,
    )

    rejected = owner.record_failure(
        failure,
        expected_phase="acquiring",
        expected_journal_revision=acquiring.journal_revision,
        expected_attempt_epoch=acquiring.attempt_epoch,
    )

    assert rejected.phase == "acquired"
    assert rejected.disposition == "rejected"
    assert rejected.failure == failure
    assert journal.status(rejected.operation_id) == rejected
    assert len(journal.records()) == 4
    explained = PackageOperationExplanationProjector(
        journal, clock_ns=lambda: 456
    ).explain_operation(rejected.operation_id)
    assert explained.product_id == "coding"
    assert explained.scope_id == "workspace:phase"
    assert explained.disposition == "rejected"
    assert explained.failure_code == "package_acquisition_digest_mismatch"
    assert explained.failure_evidence_ref == "b" * 64
    assert explained.snapshot_status == "partial_evidence"
    encoded = json.dumps(explained.to_dict())
    assert "token=secret" not in encoded
    assert "packages.example.test" not in encoded


def test_rebind_decision_is_durable_cas_on_failed_attempt_without_rewriting_request(
    tmp_path: Path,
) -> None:
    owner, journal = _owner(tmp_path)
    ingress = PackageLifecycleIngressRequestV2.bind_runtime_admission(
        _ingress(), runtime_admission_request_id="1" * 64
    )
    classified = owner.submit(ingress)
    failed = owner.interrupt(
        classified.operation_id,
        expected_phase=classified.phase,
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
    )
    original_request = journal.request(failed.operation_id)
    assert isinstance(original_request, PackageLifecycleRequestV2)
    decision = PackageLifecycleRebindRequestV1(
        operation_id=failed.operation_id,
        request_fingerprint=failed.request_fingerprint,
        expected_attempt_epoch=failed.attempt_epoch,
        expected_attempt_revision=failed.attempt_revision,
        new_runtime_admission_request_id="2" * 64,
        source_proof_ref="3" * 64,
        cleanup_evidence_ref="4" * 64,
        lease_snapshot_id="5" * 64,
    )

    rebound = journal.record_rebind(decision)
    assert rebound.record_kind == "rebind"
    assert rebound.status.disposition == "retryable_failure"
    assert rebound.status.attempt_epoch == failed.attempt_epoch
    assert rebound.status.attempt_revision > failed.attempt_revision
    assert journal.request(failed.operation_id) == original_request
    assert journal.latest_rebind(failed.operation_id) == rebound
    reopened = PackageLifecycleJournal(journal.path)
    assert reopened.latest_rebind(failed.operation_id) == rebound
    assert reopened.read_operation(failed.operation_id) == (
        original_request,
        rebound.status,
    )
    before_replay = journal.path.read_bytes()
    assert journal.record_rebind(decision) == rebound
    assert journal.path.read_bytes() == before_replay

    with pytest.raises(PackageLifecycleJournalError) as changed:
        journal.record_rebind(
            PackageLifecycleRebindRequestV1(
                operation_id=decision.operation_id,
                request_fingerprint=decision.request_fingerprint,
                expected_attempt_epoch=decision.expected_attempt_epoch,
                expected_attempt_revision=decision.expected_attempt_revision,
                new_runtime_admission_request_id="6" * 64,
                source_proof_ref=decision.source_proof_ref,
                cleanup_evidence_ref=decision.cleanup_evidence_ref,
                lease_snapshot_id=decision.lease_snapshot_id,
            )
        )
    assert changed.value.code == "package_rebind_attempt_conflict"
    with pytest.raises(PackageLifecycleJournalError) as refreshed_conflict:
        journal.record_rebind(
            PackageLifecycleRebindRequestV1(
                operation_id=decision.operation_id,
                request_fingerprint=decision.request_fingerprint,
                expected_attempt_epoch=decision.expected_attempt_epoch,
                expected_attempt_revision=rebound.status.attempt_revision,
                new_runtime_admission_request_id="6" * 64,
                source_proof_ref=decision.source_proof_ref,
                cleanup_evidence_ref=decision.cleanup_evidence_ref,
                lease_snapshot_id=decision.lease_snapshot_id,
            )
        )
    assert refreshed_conflict.value.code == "package_rebind_attempt_conflict"
    assert journal.request(failed.operation_id) == original_request
    assert journal.status(failed.operation_id) == rebound.status

    before_unbound_retry = journal.path.read_bytes()
    with pytest.raises(PackageLifecycleJournalError) as unbound:
        owner.retry(
            PackageLifecycleRetryRequestV1(
                operation_id=failed.operation_id,
                request_fingerprint=failed.request_fingerprint,
                expected_attempt_epoch=failed.attempt_epoch,
            )
        )
    assert unbound.value.code == "package_rebind_execution_not_available"
    assert journal.path.read_bytes() == before_unbound_retry

    recorded_lines = journal.path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(recorded_lines[-1])
    tampered["decision"]["sourceProofRef"] = "7" * 64
    journal.path.write_text(
        "\n".join([*recorded_lines[:-1], json.dumps(tampered)]) + "\n",
        encoding="utf-8",
    )
    corrupted_bytes = journal.path.read_bytes()
    with pytest.raises(PackageLifecycleJournalError) as corrupt:
        journal.latest_rebind(failed.operation_id)
    assert corrupt.value.code == "package_lifecycle_journal_corrupt"
    assert journal.path.read_bytes() == corrupted_bytes


def test_exact_rebind_decision_resumes_once_and_survives_owner_reopen(
    tmp_path: Path,
) -> None:
    owner, journal = _owner(tmp_path)
    ingress = PackageLifecycleIngressRequestV2.bind_runtime_admission(
        _ingress(), runtime_admission_request_id="1" * 64
    )
    classified = owner.submit(ingress)
    failed = owner.interrupt(
        classified.operation_id,
        expected_phase=classified.phase,
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
    )
    original = journal.request(failed.operation_id)
    decision = PackageLifecycleRebindRequestV1(
        operation_id=failed.operation_id,
        request_fingerprint=failed.request_fingerprint,
        expected_attempt_epoch=failed.attempt_epoch,
        expected_attempt_revision=failed.attempt_revision,
        new_runtime_admission_request_id="2" * 64,
        source_proof_ref="3" * 64,
        cleanup_evidence_ref="4" * 64,
        lease_snapshot_id="5" * 64,
    )
    record = journal.record_rebind(decision)
    with pytest.raises(PackageLifecycleJournalError) as wrong_revision:
        owner.resume_rebind(
            decision, expected_rebind_record_revision=record.record_revision + 1
        )
    assert wrong_revision.value.code == "package_rebind_decision_conflict"
    with pytest.raises(PackageLifecycleJournalError) as wrong_proof:
        owner.resume_rebind(
            replace(decision, source_proof_ref="f" * 64),
            expected_rebind_record_revision=record.record_revision,
        )
    assert wrong_proof.value.code == "package_rebind_decision_conflict"
    before = journal.path.read_bytes()
    assert journal.status(failed.operation_id) == record.status
    assert journal.path.read_bytes() == before

    resumed = owner.resume_rebind(
        decision, expected_rebind_record_revision=record.record_revision
    )
    assert resumed.disposition == "active"
    assert resumed.phase == failed.phase
    assert resumed.attempt_epoch == failed.attempt_epoch + 1
    assert resumed.request_fingerprint == failed.request_fingerprint
    assert journal.request(failed.operation_id) == original
    reopened = PackageLifecycleJournal(journal.path)
    assert reopened.read_operation(failed.operation_id) == (original, resumed)
    after = journal.path.read_bytes()
    assert (
        reopened.resume_rebind(
            decision, expected_rebind_record_revision=record.record_revision
        )
        == resumed
    )
    assert journal.path.read_bytes() == after


def test_rebind_journal_rejects_second_pending_decision_on_strict_read(
    tmp_path: Path,
) -> None:
    owner, journal = _owner(tmp_path)
    ingress = PackageLifecycleIngressRequestV2.bind_runtime_admission(
        _ingress(), runtime_admission_request_id="1" * 64
    )
    classified = owner.submit(ingress)
    failed = owner.interrupt(
        classified.operation_id,
        expected_phase=classified.phase,
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
    )
    decision = PackageLifecycleRebindRequestV1(
        operation_id=failed.operation_id,
        request_fingerprint=failed.request_fingerprint,
        expected_attempt_epoch=failed.attempt_epoch,
        expected_attempt_revision=failed.attempt_revision,
        new_runtime_admission_request_id="2" * 64,
        source_proof_ref="3" * 64,
        cleanup_evidence_ref="4" * 64,
        lease_snapshot_id="5" * 64,
    )
    first = journal.record_rebind(decision)
    second = PackageLifecycleRebindRecordV1(
        record_revision=first.record_revision + 1,
        prior_operation_revision=first.status.journal_revision,
        prior_attempt_revision=first.status.attempt_revision,
        request=first.request,
        status=replace(first.status, attempt_revision=first.record_revision + 1),
        decision=replace(
            decision,
            expected_attempt_revision=first.status.attempt_revision,
            new_runtime_admission_request_id="6" * 64,
        ),
    )
    with journal.path.open("ab") as output:
        output.write((json.dumps(second.to_dict()) + "\n").encode())
    before = journal.path.read_bytes()
    with pytest.raises(PackageLifecycleJournalError) as corrupt:
        journal.read_operation(failed.operation_id)
    assert corrupt.value.code == "package_lifecycle_journal_corrupt"
    assert journal.path.read_bytes() == before


def test_pending_rebind_supersession_is_exact_idempotent_and_resumable(
    tmp_path: Path,
) -> None:
    owner, journal = _owner(tmp_path)
    ingress = PackageLifecycleIngressRequestV2.bind_runtime_admission(
        _ingress(), runtime_admission_request_id="1" * 64
    )
    classified = owner.submit(ingress)
    failed = owner.interrupt(
        classified.operation_id,
        expected_phase=classified.phase,
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
    )
    original = journal.request(failed.operation_id)
    first_decision = PackageLifecycleRebindRequestV1(
        operation_id=failed.operation_id,
        request_fingerprint=failed.request_fingerprint,
        expected_attempt_epoch=failed.attempt_epoch,
        expected_attempt_revision=failed.attempt_revision,
        new_runtime_admission_request_id="2" * 64,
        source_proof_ref="3" * 64,
        cleanup_evidence_ref="4" * 64,
        lease_snapshot_id="5" * 64,
    )
    first = journal.record_rebind(first_decision)
    next_decision = replace(
        first_decision,
        expected_attempt_revision=first.status.attempt_revision,
        new_runtime_admission_request_id="6" * 64,
        source_proof_ref="7" * 64,
        cleanup_evidence_ref="8" * 64,
        lease_snapshot_id="9" * 64,
    )
    before = journal.path.read_bytes()
    with pytest.raises(PackageLifecycleJournalError) as stale:
        journal.supersede_rebind(
            next_decision,
            supersedes_decision_id=first_decision.decision_id,
            expected_prior_rebind_record_revision=first.record_revision + 1,
        )
    assert stale.value.code == "package_rebind_supersession_conflict"
    assert journal.path.read_bytes() == before

    second = journal.supersede_rebind(
        next_decision,
        supersedes_decision_id=first_decision.decision_id,
        expected_prior_rebind_record_revision=first.record_revision,
    )
    assert second.record_kind == "rebind_supersession"
    assert second.supersedes_decision_id == first_decision.decision_id
    assert journal.latest_rebind(failed.operation_id) == second
    assert journal.read_rebind_history(failed.operation_id) == (first, second)
    assert journal.request(failed.operation_id) == original
    reopened = PackageLifecycleJournal(journal.path)
    assert reopened.latest_rebind(failed.operation_id) == second
    after = journal.path.read_bytes()
    assert (
        reopened.supersede_rebind(
            next_decision,
            supersedes_decision_id=first_decision.decision_id,
            expected_prior_rebind_record_revision=first.record_revision,
        )
        == second
    )
    assert journal.path.read_bytes() == after
    with pytest.raises(PackageLifecycleJournalError) as old:
        owner.resume_rebind(
            first_decision, expected_rebind_record_revision=first.record_revision
        )
    assert old.value.code == "package_rebind_decision_conflict"
    resumed = owner.resume_rebind(
        next_decision, expected_rebind_record_revision=second.record_revision
    )
    assert resumed.disposition == "active"
    assert resumed.attempt_epoch == failed.attempt_epoch + 1
    assert journal.request(failed.operation_id) == original


def test_rebind_supersession_lineage_tamper_fails_strict_read(tmp_path: Path) -> None:
    owner, journal = _owner(tmp_path)
    ingress = PackageLifecycleIngressRequestV2.bind_runtime_admission(
        _ingress(), runtime_admission_request_id="1" * 64
    )
    classified = owner.submit(ingress)
    failed = owner.interrupt(
        classified.operation_id,
        expected_phase=classified.phase,
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
    )
    first_decision = PackageLifecycleRebindRequestV1(
        operation_id=failed.operation_id,
        request_fingerprint=failed.request_fingerprint,
        expected_attempt_epoch=failed.attempt_epoch,
        expected_attempt_revision=failed.attempt_revision,
        new_runtime_admission_request_id="2" * 64,
        source_proof_ref="3" * 64,
        cleanup_evidence_ref="4" * 64,
        lease_snapshot_id="5" * 64,
    )
    first = journal.record_rebind(first_decision)
    second_decision = replace(
        first_decision,
        expected_attempt_revision=first.status.attempt_revision,
        new_runtime_admission_request_id="6" * 64,
    )
    journal.supersede_rebind(
        second_decision,
        supersedes_decision_id=first_decision.decision_id,
        expected_prior_rebind_record_revision=first.record_revision,
    )
    lines = journal.path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[-1])
    tampered["supersedesDecisionId"] = "a" * 64
    journal.path.write_text(
        "\n".join([*lines[:-1], json.dumps(tampered)]) + "\n", encoding="utf-8"
    )
    before = journal.path.read_bytes()
    with pytest.raises(PackageLifecycleJournalError) as corrupt:
        journal.latest_rebind(failed.operation_id)
    assert corrupt.value.code == "package_lifecycle_journal_corrupt"
    assert journal.path.read_bytes() == before


def test_pinned_adoption_keeps_attempt_and_replays_exact_decision(
    tmp_path: Path,
) -> None:
    owner, journal = _owner(tmp_path)
    ingress = PackageLifecycleIngressRequestV2.bind_runtime_admission(
        _ingress(), runtime_admission_request_id="1" * 64
    )
    status = owner.submit(ingress)
    for phase in (
        "acquiring", "acquired", "inspecting", "extracted",
        "resolving_closure", "closure_verified", "transaction_pinned",
    ):
        status = journal.advance(
            status.operation_id,
            next_phase=phase,
            expected_phase=status.phase,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
        )
    original = journal.request(status.operation_id)
    decision = PackageLifecyclePinnedAdoptionRequestV1(
        operation_id=status.operation_id,
        request_fingerprint=status.request_fingerprint,
        expected_journal_revision=status.journal_revision,
        expected_attempt_epoch=status.attempt_epoch,
        expected_attempt_revision=status.attempt_revision,
        new_runtime_admission_request_id="2" * 64,
        source_proof_ref="3" * 64,
        closure_plan_fingerprint="4" * 64,
        pin_receipt_id="5" * 64,
        lease_snapshot_id="6" * 64,
    )
    adopted = journal.record_pinned_adoption(decision)
    assert adopted.status.phase == "transaction_pinned"
    assert adopted.status.disposition == "active"
    assert adopted.status.attempt_epoch == status.attempt_epoch
    assert adopted.status.journal_revision == status.journal_revision
    assert adopted.status.attempt_revision > status.attempt_revision
    assert journal.request(status.operation_id) == original
    reopened = PackageLifecycleJournal(journal.path)
    assert reopened.latest_pinned_adoption(status.operation_id) == adopted
    assert reopened.read_operation(status.operation_id) == (original, adopted.status)
    before_replay = journal.path.read_bytes()
    assert reopened.record_pinned_adoption(decision) == adopted
    assert journal.path.read_bytes() == before_replay
    with pytest.raises(PackageLifecycleJournalError) as changed:
        journal.record_pinned_adoption(
            replace(decision, new_runtime_admission_request_id="7" * 64)
        )
    assert changed.value.code == "package_pinned_adoption_attempt_conflict"

    replacement = replace(
        decision,
        expected_attempt_revision=adopted.status.attempt_revision,
        new_runtime_admission_request_id="8" * 64,
    )
    second = journal.supersede_pinned_adoption(
        replacement,
        supersedes_decision_id=decision.decision_id,
        expected_prior_record_revision=adopted.record_revision,
    )
    assert second.status.attempt_epoch == status.attempt_epoch
    assert reopened.latest_pinned_adoption(status.operation_id) == second
    assert reopened.read_pinned_adoption_history(status.operation_id) == (
        adopted, second
    )
    assert journal.supersede_pinned_adoption(
        replacement,
        supersedes_decision_id=decision.decision_id,
        expected_prior_record_revision=adopted.record_revision,
    ) == second

    lines = journal.path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[-1])
    tampered["supersedesDecisionId"] = "a" * 64
    journal.path.write_text(
        "\n".join([*lines[:-1], json.dumps(tampered)]) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(PackageLifecycleJournalError) as corrupt:
        reopened.latest_pinned_adoption(status.operation_id)
    assert corrupt.value.code == "package_lifecycle_journal_corrupt"


def test_pinned_adoption_refuses_unverified_phase_and_stale_cas(
    tmp_path: Path,
) -> None:
    owner, journal = _owner(tmp_path)
    ingress = PackageLifecycleIngressRequestV2.bind_runtime_admission(
        _ingress(), runtime_admission_request_id="1" * 64
    )
    status = owner.submit(ingress)
    decision = PackageLifecyclePinnedAdoptionRequestV1(
        operation_id=status.operation_id,
        request_fingerprint=status.request_fingerprint,
        expected_journal_revision=status.journal_revision,
        expected_attempt_epoch=status.attempt_epoch,
        expected_attempt_revision=status.attempt_revision,
        new_runtime_admission_request_id="2" * 64,
        source_proof_ref="3" * 64,
        closure_plan_fingerprint="4" * 64,
        pin_receipt_id="5" * 64,
        lease_snapshot_id="6" * 64,
    )
    before = journal.path.read_bytes()
    with pytest.raises(PackageLifecycleJournalError) as unverified:
        journal.record_pinned_adoption(decision)
    assert unverified.value.code == "package_pinned_adoption_attempt_conflict"
    assert journal.path.read_bytes() == before

    for phase in (
        "acquiring", "acquired", "inspecting", "extracted",
        "resolving_closure", "closure_verified", "transaction_pinned",
    ):
        status = journal.advance(
            status.operation_id,
            next_phase=phase,
            expected_phase=status.phase,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
        )
    before = journal.path.read_bytes()
    with pytest.raises(PackageLifecycleJournalError) as stale:
        journal.record_pinned_adoption(decision)
    assert stale.value.code == "package_pinned_adoption_attempt_conflict"
    assert journal.path.read_bytes() == before


def test_staging_adoption_selects_checkpoint_and_preserves_attempt(
    tmp_path: Path,
) -> None:
    owner, journal = _owner(tmp_path)
    ingress = PackageLifecycleIngressRequestV2.bind_runtime_admission(
        _ingress(), runtime_admission_request_id="1" * 64
    )
    status = owner.submit(ingress)
    for phase in (
        "acquiring", "acquired", "inspecting", "extracted",
        "resolving_closure", "closure_verified", "transaction_pinned",
    ):
        status = journal.advance(
            status.operation_id,
            next_phase=phase,
            expected_phase=status.phase,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
        )
    selected_pin = journal.record_pinned_adoption(
        PackageLifecyclePinnedAdoptionRequestV1(
            operation_id=status.operation_id,
            request_fingerprint=status.request_fingerprint,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
            expected_attempt_revision=status.attempt_revision,
            new_runtime_admission_request_id="2" * 64,
            source_proof_ref="3" * 64,
            closure_plan_fingerprint="4" * 64,
            pin_receipt_id="5" * 64,
            lease_snapshot_id="6" * 64,
        )
    )
    original = journal.request(status.operation_id)
    decision = PackageLifecycleStagingAdoptionRequestV1(
        operation_id=status.operation_id,
        request_fingerprint=status.request_fingerprint,
        expected_journal_revision=status.journal_revision,
        expected_attempt_epoch=status.attempt_epoch,
        expected_attempt_revision=selected_pin.status.attempt_revision,
        new_runtime_admission_request_id="7" * 64,
        source_proof_ref="3" * 64,
        closure_plan_fingerprint="4" * 64,
        pin_receipt_id="5" * 64,
        staging_checkpoint_id="8" * 64,
        lease_snapshot_id="9" * 64,
        previous_selected_decision_id=selected_pin.decision.decision_id,
    )
    adopted = journal.record_staging_adoption(decision)
    assert adopted.status.phase == "transaction_pinned"
    assert adopted.status.attempt_epoch == status.attempt_epoch
    assert adopted.status.journal_revision == status.journal_revision
    assert adopted.status.attempt_revision > selected_pin.status.attempt_revision
    assert journal.request(status.operation_id) == original
    reopened = PackageLifecycleJournal(journal.path)
    assert reopened.latest_staging_adoption(status.operation_id) == adopted
    assert reopened.read_operation(status.operation_id) == (original, adopted.status)
    before_replay = journal.path.read_bytes()
    assert reopened.record_staging_adoption(decision) == adopted
    assert journal.path.read_bytes() == before_replay
    with pytest.raises(PackageLifecycleJournalError) as stale:
        journal.record_staging_adoption(
            replace(decision, staging_checkpoint_id="a" * 64)
        )
    assert stale.value.code == "package_staging_adoption_attempt_conflict"
    assert journal.path.read_bytes() == before_replay

    replacement = replace(
        decision,
        expected_attempt_revision=adopted.status.attempt_revision,
        new_runtime_admission_request_id="b" * 64,
        previous_selected_decision_id=decision.decision_id,
    )
    second = journal.record_staging_adoption(replacement)
    assert second.status.attempt_epoch == status.attempt_epoch
    target = PackagePluginRootTargetV1.create(
        operation_id=status.operation_id,
        request_fingerprint=status.request_fingerprint,
        product_id="coding",
        scope_id="workspace:phase",
        installation_id="installation-phase",
        plugin_id="acme.plugin",
        authority_id="target-authority",
        authority_revision="target:1",
    )
    def checkpoint_id(selected_status: PackageLifecycleStatusV1) -> str:
        return PackageStagingCheckpointV1(
            status=selected_status,
            plan_fingerprint="4" * 64,
            pin_receipt_id="5" * 64,
            root_target=target,
            receipts=(),
            missing_node_ids=("root",),
        ).checkpoint_id

    assert checkpoint_id(selected_pin.status) == checkpoint_id(adopted.status)
    assert checkpoint_id(adopted.status) == checkpoint_id(second.status)
    assert reopened.read_staging_adoption_history(status.operation_id) == (
        adopted, second
    )
    assert journal.record_staging_adoption(replacement) == second
    with pytest.raises(PackageLifecycleJournalError) as old_admission:
        journal.record_staging_adoption(
            replace(
                replacement,
                expected_attempt_revision=second.status.attempt_revision,
                previous_selected_decision_id=replacement.decision_id,
            )
        )
    assert old_admission.value.code == "package_staging_adoption_attempt_conflict"

    lines = journal.path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[-1])
    tampered["decision"]["stagingCheckpointId"] = "c" * 64
    journal.path.write_text(
        "\n".join([*lines[:-1], json.dumps(tampered)]) + "\n", encoding="utf-8"
    )
    before_corrupt = journal.path.read_bytes()
    with pytest.raises(PackageLifecycleJournalError) as corrupt:
        reopened.latest_staging_adoption(status.operation_id)
    assert corrupt.value.code == "package_lifecycle_journal_corrupt"
    assert journal.path.read_bytes() == before_corrupt
