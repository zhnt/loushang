from __future__ import annotations

from dataclasses import replace

import pytest

from loushang.coding.package_product_worker_resume import (
    CodingWorkerResumeParentError,
    CodingWorkerResumeSettlementBinding,
    enroll_coding_worker_resume_parent,
    prepare_coding_worker_resume_effect_owner,
    seal_coding_worker_resume_parent,
)
from loushang.coding.resume_activation_attempt import CodingResumeRecoveryRequired
from loushang.coding.resume_activation_attempt_v2 import CodingActivationAttemptV2
from loushang.harness.worker import activation_state_journal as journal_module
from tests.harness.worker.test_product_activation import _ATTEMPT_A, _coordinator
from tests.harness.worker.test_resume_parent_context import _fixture, _lease


def _attempt_and_context(receipt):
    owner = prepare_coding_worker_resume_effect_owner(
        product_id=receipt.policy.product_id,
        product_scope_id=receipt.policy.product_scope_id,
    )
    attempt = CodingActivationAttemptV2(
        attempt_id="intent-1",
        request_id="request-1",
        session_id=receipt.policy.session_id,
        original_leaf_id=None,
        ancestry_digest="a" * 64,
        plan_fingerprint="b" * 64,
        epoch_fingerprint="c" * 64,
        subject_digest="d" * 64,
        effect_owners=(owner,),
    )
    return attempt, attempt.parent_context(owner)


def test_coding_worker_parent_enrollment_is_idempotent_and_seals_native_membership(
    tmp_path,
):
    journal, receipt, coordinator, context = _fixture(tmp_path)

    enrolled = enroll_coding_worker_resume_parent(
        coordinator=coordinator,
        receipt=receipt,
        context=context,
    )
    committed = journal.path.read_bytes()
    recovered = enroll_coding_worker_resume_parent(
        coordinator=coordinator,
        receipt=receipt,
        context=context,
    )

    assert enrolled == recovered
    assert journal.path.read_bytes() == committed
    with _lease(coordinator, receipt, context) as admission:
        admission.begin_effect()
    coordinator.publish(
        receipt=receipt,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
        realized_native_policy_closure_fingerprint=(
            receipt.policy.expected_native_policy_closure_fingerprint
        ),
        native_profile_catalog_revision=receipt.policy.native_profile_catalog_revision,
        native_profile_id=receipt.policy.native_profile_id,
    )
    sealed = seal_coding_worker_resume_parent(
        coordinator=coordinator,
        context=context,
    )
    assert sealed is not None
    assert sealed["sealed"] is True
    assert len(sealed["nativeAttempts"]) == 1
    assert next(iter(sealed["nativeAttempts"].values()))["phase"] == "published"
    assert sealed["membershipDigest"] is not None


def test_coding_worker_parent_recovers_lost_enrollment_ack(tmp_path, monkeypatch):
    journal, receipt, coordinator, context = _fixture(tmp_path)
    append = journal_module.append_jsonl_record
    fail_once = [True]

    def lost_ack(*args, **kwargs):
        append(*args, **kwargs)
        if fail_once[0]:
            fail_once[0] = False
            raise OSError("lost durable acknowledgement")

    monkeypatch.setattr(journal_module, "append_jsonl_record", lost_ack)
    snapshot = enroll_coding_worker_resume_parent(
        coordinator=coordinator,
        receipt=receipt,
        context=context,
    )

    assert snapshot is not None
    assert snapshot["parentContext"] == context.to_dict()
    assert snapshot["sealed"] is False


def test_coding_worker_parent_recovers_lost_seal_ack(tmp_path, monkeypatch):
    journal, receipt, coordinator, context = _fixture(tmp_path)
    enroll_coding_worker_resume_parent(
        coordinator=coordinator,
        receipt=receipt,
        context=context,
    )
    with _lease(coordinator, receipt, context):
        pass
    append = journal_module.append_jsonl_record
    fail_once = [True]

    def lost_ack(*args, **kwargs):
        append(*args, **kwargs)
        if fail_once[0]:
            fail_once[0] = False
            raise OSError("lost seal acknowledgement")

    with monkeypatch.context() as patch:
        patch.setattr(journal_module, "append_jsonl_record", lost_ack)
        with pytest.raises(OSError, match="acknowledgement"):
            seal_coding_worker_resume_parent(
                coordinator=coordinator,
                context=context,
            )

    recovered, _ = _coordinator(receipt=receipt, store=journal)
    sealed = seal_coding_worker_resume_parent(
        coordinator=recovered,
        context=context,
    )
    assert sealed is not None
    assert sealed["sealed"] is True
    assert len(sealed["nativeAttempts"]) == 1


def test_coding_worker_parent_rejects_scope_mismatch_without_owner_write(tmp_path):
    journal, receipt, coordinator, context = _fixture(tmp_path)
    before = journal.path.read_bytes()

    with pytest.raises(
        CodingWorkerResumeParentError,
        match="coding_worker_resume_parent_context_mismatch",
    ):
        enroll_coding_worker_resume_parent(
            coordinator=coordinator,
            receipt=receipt,
            context=replace(context, scope_digest="f" * 64),
        )

    assert journal.path.read_bytes() == before


@pytest.mark.parametrize("outcome", ["published", "no_effect"])
def test_coding_worker_settlement_accepts_exact_original_c5_outcome(
    tmp_path, outcome
):
    journal, receipt, coordinator, _unused = _fixture(tmp_path)
    attempt, context = _attempt_and_context(receipt)
    enroll_coding_worker_resume_parent(
        coordinator=coordinator,
        receipt=receipt,
        context=context,
    )
    with coordinator.admission(
        policy=receipt.policy,
        receipt=receipt,
        attempt_id=_ATTEMPT_A,
        owner_generation=receipt.policy.owner_selection_generation,
        host_identity="host-1",
        boot_identity="boot-1",
        cleanup_contract_version=2,
        parent_context=context,
    ) as admission:
        if outcome == "published":
            admission.begin_effect()
    if outcome == "published":
        coordinator.publish(
            receipt=receipt,
            attempt_id=_ATTEMPT_A,
            owner_generation=receipt.policy.owner_selection_generation,
            realized_native_policy_closure_fingerprint=(
                receipt.policy.expected_native_policy_closure_fingerprint
            ),
            native_profile_catalog_revision=(
                receipt.policy.native_profile_catalog_revision
            ),
            native_profile_id=receipt.policy.native_profile_id,
        )
    seal_coding_worker_resume_parent(coordinator=coordinator, context=context)
    settlement = CodingWorkerResumeSettlementBinding(
        receipt=receipt,
        context=context,
    )
    settlement.bind(coordinator)

    settlement.require_current(attempt)
    assert journal.path.exists()


def test_coding_worker_settlement_refuses_unsealed_original_membership(tmp_path):
    _journal, receipt, coordinator, _unused = _fixture(tmp_path)
    attempt, context = _attempt_and_context(receipt)
    enroll_coding_worker_resume_parent(
        coordinator=coordinator,
        receipt=receipt,
        context=context,
    )
    settlement = CodingWorkerResumeSettlementBinding(
        receipt=receipt,
        context=context,
    )
    settlement.bind(coordinator)

    with pytest.raises(
        CodingResumeRecoveryRequired,
        match="input.effect_settlement_unknown",
    ):
        settlement.require_current(attempt)
