from __future__ import annotations

import json
from dataclasses import replace

import pytest

from loushang.harness.approval import plugin_activation as activation
from loushang.harness.approval.plugin_activation import PluginActivationJournalError
from loushang.harness.resume_effects import ResumeEffectParentContextV1
from tests.harness.approval.test_plugin_activation_journal import (
    _issue,
    _journal,
    _subject,
)


def _enrolled(tmp_path):
    journal = _journal(tmp_path)
    decision = _issue(journal)
    context = ResumeEffectParentContextV1(
        product_id="coding",
        session_id="historical-session",
        attempt_id="intent-1",
        request_id="request-1",
        intent_digest="a" * 64,
        owner_id="harness.plugin-activation",
        scope_digest=journal.resume_parent_scope_digest(product_id="coding"),
        contract_digest=journal.resume_parent_contract_digest,
    )
    journal.enroll_resume_parent(context, expected_journal_revision=1)
    use = journal.consume_activation_decision(
        _subject(),
        decision_id=decision.decision_id,
        host_boot_id="3" * 32,
        import_realm_id="4" * 32,
        expected_journal_revision=2,
        parent_context=context,
    )
    return journal, context, use


def test_original_activation_consume_registers_exact_native_use_and_parent(tmp_path):
    journal, context, use = _enrolled(tmp_path)
    records = [json.loads(line) for line in journal.path.read_text().splitlines()]
    assert [record["eventVersion"] for record in records] == [1, 2, 2]
    assert records[-1]["payload"]["parentContext"] == context.to_dict()
    assert records[-1]["payload"]["reservation"] == use.to_dict()
    sealed = journal.seal_resume_parent(context, expected_journal_revision=3)
    assert sealed.activation_uses == (use,)
    assert sealed.sealed
    assert sealed.unfenced_recovered_use_ids == ()
    with journal.path.open("ab") as stream:
        stream.write(b'{"eventVersion":')
    original = journal.path.read_bytes()
    with pytest.raises(PluginActivationJournalError) as caught:
        journal.transition_activation_use(
            use.activation_use_id,
            expected_state="CONSUMED_NOT_STARTED",
            target_state="STARTING",
            host_boot_id="3" * 32,
            import_realm_id="4" * 32,
            transitioned_at_unix_ms=2_100,
            expected_journal_revision=4,
        )
    assert caught.value.code == "plugin_activation_resume_parent_sealed"
    assert journal.path.read_bytes() == original


def test_activation_consume_lost_ack_recovers_one_registered_use(tmp_path, monkeypatch):
    journal = _journal(tmp_path)
    decision = _issue(journal)
    context = ResumeEffectParentContextV1(
        product_id="coding",
        session_id="historical-session",
        attempt_id="intent-1",
        request_id="request-1",
        intent_digest="a" * 64,
        owner_id="harness.plugin-activation",
        scope_digest=journal.resume_parent_scope_digest(product_id="coding"),
        contract_digest=journal.resume_parent_contract_digest,
    )
    journal.enroll_resume_parent(context, expected_journal_revision=1)
    append = activation.append_jsonl_record

    def lost_ack(*args, **kwargs):
        append(*args, **kwargs)
        raise OSError("lost durable acknowledgement")

    def consume(revision):
        return journal.consume_activation_decision(
            _subject(),
            decision_id=decision.decision_id,
            host_boot_id="3" * 32,
            import_realm_id="4" * 32,
            expected_journal_revision=revision,
            parent_context=context,
        )

    with monkeypatch.context() as scope:
        scope.setattr(activation, "append_jsonl_record", lost_ack)
        with pytest.raises(OSError, match="acknowledgement"):
            consume(2)
    snapshot = _journal(tmp_path).resume_parent_snapshot(context)
    assert len(snapshot.activation_uses) == 1
    original = journal.path.read_bytes()
    with pytest.raises(PluginActivationJournalError) as caught:
        consume(3)
    assert caught.value.code == "plugin_activation_decision_consumed"
    assert journal.path.read_bytes() == original


@pytest.mark.parametrize("field", ["owner_id", "scope_digest", "contract_digest"])
def test_wrong_original_activation_context_refuses_before_tail_repair(tmp_path, field):
    journal, context, _ = _enrolled(tmp_path)
    wrong = replace(context, **{field: "other" if field == "owner_id" else "b" * 64})
    with journal.path.open("ab") as stream:
        stream.write(b'{"eventVersion":')
    original = journal.path.read_bytes()
    with pytest.raises(PluginActivationJournalError) as caught:
        journal.resume_parent_snapshot(wrong)
    assert caught.value.code == "plugin_activation_resume_context_mismatch"
    assert journal.path.read_bytes() == original


def test_contextual_recovery_does_not_cancel_another_parent_native_use(tmp_path):
    journal, context, use = _enrolled(tmp_path)
    other = replace(context, attempt_id="intent-2", request_id="request-2")
    journal.enroll_resume_parent(other, expected_journal_revision=3)
    decision = _issue(journal, expected_journal_revision=4)
    other_use = journal.consume_activation_decision(
        _subject(),
        decision_id=decision.decision_id,
        host_boot_id="3" * 32,
        import_realm_id="4" * 32,
        expected_journal_revision=5,
        parent_context=other,
    )
    recovered = journal.recover_activation_uses(
        current_host_boot_id="9" * 32,
        recovered_at_unix_ms=2_300,
        expected_journal_revision=6,
        parent_context=context,
    )
    assert recovered == (replace(use, state="CANCELLED_BEFORE_START"),)
    assert journal.resume_parent_snapshot(other).activation_uses == (other_use,)


@pytest.mark.parametrize("started", [False, True])
def test_recovered_failed_factory_remains_unfenced_and_preserves_partial_tail(
    tmp_path, started
):
    journal, context, use = _enrolled(tmp_path)
    journal.transition_activation_use(
        use.activation_use_id,
        expected_state="CONSUMED_NOT_STARTED",
        target_state="STARTING",
        host_boot_id="3" * 32,
        import_realm_id="4" * 32,
        transitioned_at_unix_ms=2_100,
        expected_journal_revision=3,
    )
    revision = 4
    if started:
        journal.transition_activation_use(
            use.activation_use_id,
            expected_state="STARTING",
            target_state="STARTED",
            host_boot_id="3" * 32,
            import_realm_id="4" * 32,
            transitioned_at_unix_ms=2_200,
            expected_journal_revision=revision,
        )
        revision += 1
    journal.recover_activation_uses(
        current_host_boot_id="9" * 32,
        recovered_at_unix_ms=2_300,
        expected_journal_revision=revision,
    )
    recovered = _journal(tmp_path).resume_parent_snapshot(context)
    assert recovered.activation_uses[0].state == "FAILED"
    assert recovered.unfenced_recovered_use_ids == (use.activation_use_id,)
    with journal.path.open("ab") as stream:
        stream.write(b'{"eventVersion":')
    original = journal.path.read_bytes()
    with pytest.raises(PluginActivationJournalError) as caught:
        journal.seal_resume_parent(context, expected_journal_revision=revision + 1)
    assert caught.value.code == "plugin_activation_resume_start_unknown"
    assert journal.path.read_bytes() == original
