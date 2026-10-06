"""Portable checks for the Product-owned Windows C5 cleanup evidence join."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding.package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from loushang.coding.package_product_worker_receipt import CodingWorkerReceiptRecordV1
from loushang.coding.package_product_worker_windows_cleanup_evidence import (
    CodingWindowsWorkerCleanupEvidenceAuthority,
    CodingWindowsWorkerLiveCleanupReviewV1,
)
from loushang.coding.package_product_worker_windows_orphan_review import (
    CodingWindowsWorkerOrphanRuntimeReviewV1,
)
from loushang.coding.package_product_worker_windows_provisioning_journal import (
    WindowsWorkerProvisioningAttemptV1,
)
from loushang.coding.package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAttemptV1,
)
from loushang.harness.worker._native_profile_bridge import (
    _WindowsNativeContainmentSettlementWitness,
)
from tests.harness.worker.test_native_profile_bridge import _windows_profile_context

_PHASES = (
    "reserved",
    "profile_effect",
    "profile_created",
    "grant_effect",
    "grants_applied",
    "verified",
    "active",
    "cleaning",
    "revoke_effect",
    "grants_revoked",
    "delete_effect",
    "profile_deleted",
    "settled",
)
_WITNESSES = (False, False) + (True,) * (len(_PHASES) - 2)


def _settled_review(
    tmp_path: Path,
) -> tuple[
    CodingWindowsWorkerCleanupEvidenceAuthority,
    CodingWindowsWorkerLiveCleanupReviewV1,
    _WindowsNativeContainmentSettlementWitness,
]:
    _profile, receipt, request, plan, *_ = _windows_profile_context(tmp_path)
    authority = object.__new__(CodingWindowsWorkerCleanupEvidenceAuthority)
    authority._product = SimpleNamespace(
        epoch_runtime=SimpleNamespace(registry=SimpleNamespace(store_id="a" * 64))
    )
    authority._receipt = receipt
    authority._request = request
    attempt_id = request.identity.attempt_id
    job_name = "Global\\LoushangWorker-" + plan.operation_nonce
    attempt = CodingWindowsWorkerRecoveryAttemptV1(
        attempt_id=attempt_id,
        payload_directory_identity=(1, 2),
        native_phase="settled",
        native_revision=len(_PHASES),
        supervisor_phase="stopped",
        supervisor_revision=2,
        supervisor_process_settled=True,
        native_phase_history=_PHASES,
        native_witness_present_history=_WITNESSES,
        native_witness_state="SETTLED",
        native_worker_request_fingerprint=request.fingerprint,
        native_receipt_fingerprint=receipt.fingerprint,
        native_job_name=job_name,
        supervisor_identity_fingerprint=request.identity.fingerprint,
        launch_request_fingerprint=request.fingerprint,
        launch_receipt_fingerprint=receipt.fingerprint,
        launch_identity_fingerprint=request.identity.fingerprint,
        launch_stage_identity=(1, 2),
    )
    assert attempt.clean_exit_settled
    record = CodingWorkerReceiptRecordV1.create(
        journal_revision=receipt.issue_sequence,
        scope_id=receipt.policy.product_scope_id,
        opt_in_decision_digest="e" * 64,
        receipt=receipt,
    )
    native = WindowsWorkerProvisioningAttemptV1(
        attempt_id=attempt_id,
        phase="settled",
        state_revision=len(_PHASES),
        identity={
            "receiptFingerprint": receipt.fingerprint,
            "workerRequestFingerprint": request.fingerprint,
            "ownerGeneration": request.identity.owner_generation,
            "jobObjectName": job_name,
        },
        phase_history=_PHASES,
        witness_present_history=_WITNESSES,
        last_witness_state="SETTLED",
        settlement_fingerprint="f" * 64,
    )
    activation = CodingProductWorkerRetainedAttemptV1(
        attempt_id=attempt_id,
        receipt_fingerprint=receipt.fingerprint,
        policy_fingerprint=receipt.policy.fingerprint,
        owner_generation=request.identity.owner_generation,
        cleanup_contract_version=2,
        host_identity=authority.host_identity,
        boot_identity=authority.boot_identity,
        phase="retired",
        last_seen_revision=4,
        current=True,
    )
    review = CodingWindowsWorkerLiveCleanupReviewV1(
        runtime=CodingWindowsWorkerOrphanRuntimeReviewV1(
            attempt_id=attempt_id,
            attempt=attempt,
            receipt_record=record,
            orphan_leases=(),
            runtime_epoch=1,
            store_root_identity="a" * 64,
            native_job_absent=True,
        ),
        native=native,
        activation=activation,
    )
    witness = _WindowsNativeContainmentSettlementWitness(
        receipt_fingerprint=receipt.fingerprint,
        worker_request_fingerprint=request.fingerprint,
        attempt_id=attempt_id,
        owner_generation=request.identity.owner_generation,
        journal_fingerprint="f" * 64,
    )
    return authority, review, witness


def test_windows_c5_cleanup_review_requires_exact_settled_product_join(
    tmp_path: Path,
) -> None:
    authority, review, _witness = _settled_review(tmp_path)
    assert authority._review_matches(review)
    assert not authority._review_matches(
        replace(review, runtime=replace(review.runtime, native_job_absent=None))
    )
    assert not authority._review_matches(
        replace(review, runtime=replace(review.runtime, native_job_absent=False))
    )
    assert review.activation is not None
    assert not authority._review_matches(
        replace(
            review, activation=replace(review.activation, cleanup_contract_version=1)
        )
    )
    assert not authority._review_matches(
        replace(review, activation=replace(review.activation, phase="settled"))
    )
    assert review.native is not None
    assert not authority._review_matches(
        replace(review, native=replace(review.native, settlement_fingerprint=None))
    )
    assert not authority._review_matches(
        replace(review, native=replace(review.native, last_witness_state="DEBT"))
    )


def test_windows_c5_native_witness_reopens_exact_settled_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority, review, witness = _settled_review(tmp_path)
    monkeypatch.setattr(
        CodingWindowsWorkerCleanupEvidenceAuthority,
        "current_tree_witness",
        lambda self, *, attempt_id: review,
    )
    facts = {
        "receipt_fingerprint": witness.receipt_fingerprint,
        "attempt_id": witness.attempt_id,
        "owner_generation": witness.owner_generation,
        "host_identity": authority.host_identity,
        "boot_identity": authority.boot_identity,
        "evidence_authority_id": authority.authority_id,
        "evidence_authority_fingerprint": authority.authority_fingerprint,
    }
    assert authority.verify_tree_settlement(witness=review, **facts)
    assert authority.verify_native_containment_settlement(witness=witness, **facts)
    assert not authority.verify_native_containment_settlement(
        witness=replace(witness, journal_fingerprint="0" * 64), **facts
    )
    assert not authority.verify_tree_settlement(
        witness=review, **{**facts, "boot_identity": "changed"}
    )
    assert not authority.verify_changed_boot_absence()
    assert not authority.verify_registered_lease_expired()
