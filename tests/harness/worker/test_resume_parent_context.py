from __future__ import annotations

import json
import sys
from dataclasses import replace

import pytest

from loushang.harness.resume_effects import ResumeEffectParentContextV1
from loushang.harness.worker import activation_state_journal as journal_module
from loushang.harness.worker.activation_state_journal import (
    WorkerActivationStateJournal,
    WorkerActivationStateJournalError,
)
from loushang.harness.worker.product_activation import (
    _ActivationRejected,
    _compact_settled_attempts,
    _validate_resume_state_transition,
)
from tests.harness.worker.test_product_activation import (
    _ATTEMPT_A,
    _coordinator,
    _receipt,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux rooted Worker activation journal"
)


def _fixture(tmp_path):
    root = tmp_path / "product-state"
    root.mkdir(mode=0o700)
    journal = WorkerActivationStateJournal(root / "worker-activation-state.jsonl")
    receipt = _receipt()
    coordinator, _ = _coordinator(receipt=receipt, store=journal)
    context = ResumeEffectParentContextV1(
        product_id=receipt.policy.product_id,
        session_id="historical-session",
        attempt_id="intent-1",
        request_id="request-1",
        intent_digest="a" * 64,
        owner_id="harness.worker-activation",
        scope_digest=coordinator.resume_parent_scope_digest(
            product_id=receipt.policy.product_id,
            product_scope_id=receipt.policy.product_scope_id,
        ),
        contract_digest=coordinator.resume_parent_contract_digest,
    )
    return journal, receipt, coordinator, context


def _lease(coordinator, receipt, context):
    return coordinator.admission(
        policy=receipt.policy,
        receipt=receipt,
        attempt_id=_ATTEMPT_A,
        owner_generation=1,
        host_identity="host-1",
        boot_identity="boot-1",
        cleanup_contract_version=2,
        parent_context=context,
    )


def test_worker_resume_refuses_tree_only_cleanup_contract(tmp_path):
    journal, receipt, coordinator, context = _fixture(tmp_path)
    original = journal.path.read_bytes()
    with pytest.raises(ValueError, match="containment cleanup v2"):
        coordinator.admission(
            policy=receipt.policy,
            receipt=receipt,
            attempt_id=_ATTEMPT_A,
            owner_generation=1,
            host_identity="host-1",
            boot_identity="boot-1",
            parent_context=context,
            cleanup_contract_version=1,
        )
    assert journal.path.read_bytes() == original


def test_worker_registration_is_one_native_cas_with_parent(tmp_path):
    journal, receipt, coordinator, context = _fixture(tmp_path)
    coordinator.enroll_resume_parent(
        context, policy=receipt.policy, expected_state_revision=1
    )
    with _lease(coordinator, receipt, context):
        records = [json.loads(line) for line in journal.path.read_text().splitlines()]
        assert [record["recordVersion"] for record in records] == [1, 2, 2]
        document = records[-1]["document"]
        assert len(document["attempts"]) == 1
        key = next(iter(document["attempts"]))
        assert document["resumeUseParents"] == {key: context.digest}
        assert document["attempts"][key]["phase"] == "registered"
    recovered, _ = _coordinator(receipt=receipt, store=journal)
    snapshot = recovered.resume_parent_snapshot(context)
    assert len(snapshot["nativeAttempts"]) == 1
    assert next(iter(snapshot["nativeAttempts"].values()))["phase"] == "settled"


def test_worker_unknown_parent_refuses_native_attempt_registration(tmp_path):
    journal, receipt, coordinator, context = _fixture(tmp_path)
    original = journal.path.read_bytes()
    with pytest.raises(_ActivationRejected) as caught:
        with _lease(coordinator, receipt, context):
            pytest.fail("unknown parent admitted")
    assert caught.value.reason.value == "resume_parent_unknown"
    assert journal.path.read_bytes() == original


def test_worker_seal_fences_reserved_late_effect(tmp_path):
    journal, receipt, coordinator, context = _fixture(tmp_path)
    coordinator.enroll_resume_parent(
        context, policy=receipt.policy, expected_state_revision=1
    )
    other, _ = _coordinator(receipt=receipt, store=journal)
    with _lease(coordinator, receipt, context) as lease:
        other.seal_resume_parent(context, expected_state_revision=3)
        with pytest.raises(_ActivationRejected) as caught:
            lease.begin_effect()
        assert caught.value.reason.value == "resume_parent_sealed"
    assert coordinator.resume_parent_snapshot(context)["sealed"] is True


def test_worker_started_effect_remains_unknown_for_seal(tmp_path):
    journal, receipt, coordinator, context = _fixture(tmp_path)
    coordinator.enroll_resume_parent(
        context, policy=receipt.policy, expected_state_revision=1
    )
    with _lease(coordinator, receipt, context) as lease:
        lease.begin_effect()
    recovered, _ = _coordinator(receipt=receipt, store=journal)
    original = journal.path.read_bytes()
    with pytest.raises(_ActivationRejected) as caught:
        recovered.seal_resume_parent(context, expected_state_revision=4)
    assert caught.value.reason.value == "resume_start_unknown"
    assert journal.path.read_bytes() == original


def test_worker_enrollment_lost_durable_ack_remains_exact(tmp_path, monkeypatch):
    journal, receipt, coordinator, context = _fixture(tmp_path)
    append = journal_module.append_jsonl_record

    def lost_ack(*args, **kwargs):
        append(*args, **kwargs)
        raise OSError("lost durable acknowledgement")

    with monkeypatch.context() as scope:
        scope.setattr(journal_module, "append_jsonl_record", lost_ack)
        with pytest.raises(OSError, match="acknowledgement"):
            coordinator.enroll_resume_parent(
                context, policy=receipt.policy, expected_state_revision=1
            )
    recovered, _ = _coordinator(receipt=receipt, store=journal)
    assert (
        recovered.resume_parent_snapshot(context)["parentContext"] == context.to_dict()
    )
    original = journal.path.read_bytes()
    with pytest.raises(_ActivationRejected):
        recovered.enroll_resume_parent(
            replace(context, intent_digest="b" * 64),
            policy=receipt.policy,
            expected_state_revision=2,
        )
    assert journal.path.read_bytes() == original


def test_worker_registration_lost_ack_retains_native_parent_and_prevents_retry(
    tmp_path, monkeypatch
):
    journal, receipt, coordinator, context = _fixture(tmp_path)
    coordinator.enroll_resume_parent(
        context, policy=receipt.policy, expected_state_revision=1
    )
    append = journal_module.append_jsonl_record
    fail_once = [True]

    def lost_ack(*args, **kwargs):
        append(*args, **kwargs)
        if fail_once[0]:
            fail_once[0] = False
            raise OSError("lost native registration acknowledgement")

    with monkeypatch.context() as scope:
        scope.setattr(journal_module, "append_jsonl_record", lost_ack)
        with pytest.raises(OSError, match="acknowledgement"):
            with _lease(coordinator, receipt, context):
                pytest.fail("unknown registration must not enter the effect body")
    recovered, _ = _coordinator(receipt=receipt, store=journal)
    snapshot = recovered.resume_parent_snapshot(context)
    assert len(snapshot["nativeAttempts"]) == 1
    attempt = next(iter(snapshot["nativeAttempts"].values()))
    assert attempt["phase"] == "settled"
    assert attempt["cleanupSettlement"]["noEffect"] is True
    original = journal.path.read_bytes()
    with pytest.raises(_ActivationRejected):
        with _lease(recovered, receipt, context):
            pytest.fail("a registered native key cannot be consumed twice")
    assert journal.path.read_bytes() == original


def test_worker_context_linked_settlement_is_not_compacted(tmp_path, monkeypatch):
    journal, receipt, coordinator, context = _fixture(tmp_path)
    coordinator.enroll_resume_parent(
        context, policy=receipt.policy, expected_state_revision=1
    )
    with _lease(coordinator, receipt, context):
        pass
    state = dict(coordinator.snapshot())
    monkeypatch.setattr(
        "loushang.harness.worker.product_activation._MAX_DURABLE_ATTEMPTS", 1
    )
    _compact_settled_attempts(state)
    assert len(state["attempts"]) == 1
    deleted = json.loads(json.dumps(state))
    deleted["attempts"] = {}
    deleted["resumeUseParents"] = {}
    with pytest.raises(ValueError, match="disappeared"):
        _validate_resume_state_transition(state, deleted)


@pytest.mark.parametrize("mutation", ["downgrade", "delete_parent", "unseal"])
def test_worker_original_cas_rejects_resume_evidence_loss(tmp_path, mutation):
    journal, receipt, coordinator, context = _fixture(tmp_path)
    coordinator.enroll_resume_parent(
        context, policy=receipt.policy, expected_state_revision=1
    )
    coordinator.seal_resume_parent(context, expected_state_revision=2)
    state = json.loads(json.dumps(coordinator.snapshot()))
    state["stateRevision"] = 4
    if mutation == "downgrade":
        state["stateVersion"] = 2
        del state["resumeParents"]
        del state["resumeUseParents"]
    elif mutation == "delete_parent":
        state["resumeParents"] = {}
    else:
        parent = state["resumeParents"][context.digest]
        parent["sealed"] = False
        parent["nativeKeys"] = None
        parent["membershipDigest"] = None
    original = journal.path.read_bytes()
    with pytest.raises(ValueError):
        journal.compare_and_swap(expected_revision=3, document=state)
    assert journal.path.read_bytes() == original


def test_worker_history_replay_rejects_complete_downgrade_before_any_repair(tmp_path):
    journal, receipt, coordinator, context = _fixture(tmp_path)
    coordinator.enroll_resume_parent(
        context, policy=receipt.policy, expected_state_revision=1
    )
    state = json.loads(json.dumps(coordinator.snapshot()))
    state["stateRevision"] = 3
    state["stateVersion"] = 2
    del state["resumeParents"]
    del state["resumeUseParents"]
    record = journal_module._StateRecord.create(state)
    with journal.path.open("ab") as stream:
        stream.write(journal_module._canonical_json_bytes(record.to_dict()) + b"\n")
    original = journal.path.read_bytes()
    with pytest.raises(WorkerActivationStateJournalError) as caught:
        journal.load_read_only()
    assert caught.value.code == "worker_activation_state_corrupt"
    assert journal.path.read_bytes() == original
