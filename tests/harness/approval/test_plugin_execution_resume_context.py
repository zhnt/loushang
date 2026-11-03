from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from loushang.harness.approval import plugin_execution as execution
from loushang.harness.resume_effects import ResumeEffectParentContextV1
from tests.harness.approval.test_plugin_execution_journal import (
    _consume,
    _issue,
    _journal,
    _subject,
    _transition,
)


def _context(journal, **changes):
    return replace(
        ResumeEffectParentContextV1(
            product_id="coding",
            session_id="historical-session",
            attempt_id="intent-1",
            request_id="request-1",
            intent_digest="a" * 64,
            owner_id="harness.plugin-execution",
            scope_digest=journal.resume_parent_scope_digest(product_id="coding"),
            contract_digest=journal.resume_parent_contract_digest,
        ),
        **changes,
    )


def _enrolled(tmp_path):
    journal = _journal(tmp_path)
    _issue(journal, _subject())
    context = _context(journal)
    journal.enroll_resume_parent(context, expected_journal_revision=1)
    return journal, context


def test_original_consume_co_commits_exact_parent_and_one_shot_native_use(tmp_path):
    journal, context = _enrolled(tmp_path)
    use = _consume(
        journal, _subject(), expected_journal_revision=2, parent_context=context
    )
    records = [json.loads(line) for line in journal.path.read_text().splitlines()]
    assert [event["eventVersion"] for event in records] == [1, 2, 2]
    assert records[-1]["eventKind"] == "execution_consumed"
    assert records[-1]["payload"]["parentContext"] == context.to_dict()
    assert records[-1]["payload"]["reservation"] == use.to_dict()
    recovered = _journal(tmp_path).resume_parent_snapshot(context)
    assert recovered.execution_uses == (use,)
    assert not recovered.sealed
    with pytest.raises(execution.PluginExecutionJournalError) as caught:
        _consume(
            journal, _subject(), expected_journal_revision=3, parent_context=context
        )
    assert caught.value.code == "plugin_execution_decision_consumed"
    assert journal.snapshot().journal_revision == 3


def test_consume_ack_loss_recovers_original_registration_without_second_use(
    tmp_path, monkeypatch
):
    journal, context = _enrolled(tmp_path)
    append = execution.append_jsonl_record

    def lost_ack(*args, **kwargs):
        append(*args, **kwargs)
        raise OSError("lost durable acknowledgement")

    with monkeypatch.context() as scope:
        scope.setattr(execution, "append_jsonl_record", lost_ack)
        with pytest.raises(OSError, match="acknowledgement"):
            _consume(
                journal, _subject(), expected_journal_revision=2, parent_context=context
            )
    recovered = _journal(tmp_path).resume_parent_snapshot(context)
    assert len(recovered.execution_uses) == 1
    assert recovered.execution_uses[0].state == "CONSUMED_NOT_STARTED"
    original = journal.path.read_bytes()
    with pytest.raises(execution.PluginExecutionJournalError):
        _consume(
            journal, _subject(), expected_journal_revision=3, parent_context=context
        )
    assert journal.path.read_bytes() == original


@pytest.mark.parametrize(
    "field", ["owner_id", "scope_digest", "contract_digest", "product_id"]
)
def test_wrong_original_owner_contract_refuses_before_enrollment_or_consumption(
    tmp_path, field
):
    journal, context = _enrolled(tmp_path)
    invalid = replace(
        context, **{field: "other" if field in {"owner_id", "product_id"} else "b" * 64}
    )
    original = journal.path.read_bytes()
    with pytest.raises(execution.PluginExecutionJournalError) as caught:
        _consume(
            journal, _subject(), expected_journal_revision=2, parent_context=invalid
        )
    assert caught.value.code == "plugin_execution_resume_context_mismatch"
    assert journal.path.read_bytes() == original


def test_unenrolled_parent_and_missing_journal_are_unknown_not_empty_proof(tmp_path):
    journal = _journal(tmp_path)
    context = _context(journal)
    with pytest.raises(execution.PluginExecutionJournalError) as caught:
        journal.resume_parent_snapshot(context)
    assert caught.value.code == "plugin_execution_resume_parent_unknown"
    _issue(journal, _subject())
    original = journal.path.read_bytes()
    with pytest.raises(execution.PluginExecutionJournalError) as caught:
        _consume(
            journal, _subject(), expected_journal_revision=1, parent_context=context
        )
    assert caught.value.code == "plugin_execution_resume_parent_unknown"
    assert journal.path.read_bytes() == original


def test_sealed_enumeration_fences_reserved_late_starter_and_new_consumption(tmp_path):
    journal, context = _enrolled(tmp_path)
    use = _consume(
        journal, _subject(), expected_journal_revision=2, parent_context=context
    )
    sealed = journal.seal_resume_parent(context, expected_journal_revision=3)
    assert sealed.execution_uses == (use,)
    assert sealed.sealed and sealed.membership_digest
    assert _journal(tmp_path).resume_parent_snapshot(context) == sealed
    original = journal.path.read_bytes()
    with pytest.raises(execution.PluginExecutionJournalError) as caught:
        _transition(
            journal,
            use.execution_use_id,
            expected_state="CONSUMED_NOT_STARTED",
            target_state="STARTING",
            expected_journal_revision=4,
        )
    assert caught.value.code == "plugin_execution_resume_parent_sealed"
    with pytest.raises(execution.PluginExecutionJournalError) as caught:
        _consume(
            journal, _subject(), expected_journal_revision=4, parent_context=context
        )
    assert caught.value.code == "plugin_execution_resume_parent_sealed"
    assert journal.path.read_bytes() == original


def test_started_original_use_cannot_be_sealed_after_reopen_or_another_boot(tmp_path):
    journal, context = _enrolled(tmp_path)
    use = _consume(
        journal, _subject(), expected_journal_revision=2, parent_context=context
    )
    starting = _transition(
        journal,
        use.execution_use_id,
        expected_state="CONSUMED_NOT_STARTED",
        target_state="STARTING",
        expected_journal_revision=3,
    )
    journal.recover_execution_uses(
        current_host_boot_id="9" * 32,
        recovered_at_unix_ms=2500,
        expected_journal_revision=4,
    )
    original = journal.path.read_bytes()
    reopened = _journal(tmp_path)
    with pytest.raises(execution.PluginExecutionJournalError) as caught:
        reopened.seal_resume_parent(context, expected_journal_revision=4)
    assert caught.value.code == "plugin_execution_resume_start_unknown"
    assert journal.path.read_bytes() == original
    assert reopened.resume_parent_snapshot(context).execution_uses == (starting,)


def test_completed_invocation_is_retained_as_native_fact_not_external_settlement(
    tmp_path,
):
    journal, context = _enrolled(tmp_path)
    use = _consume(
        journal, _subject(), expected_journal_revision=2, parent_context=context
    )
    _transition(
        journal,
        use.execution_use_id,
        expected_state="CONSUMED_NOT_STARTED",
        target_state="STARTING",
        expected_journal_revision=3,
    )
    evaluated = _transition(
        journal,
        use.execution_use_id,
        expected_state="STARTING",
        target_state="EVALUATED",
        expected_journal_revision=4,
    )
    sealed = journal.seal_resume_parent(context, expected_journal_revision=5)
    assert sealed.execution_uses == (evaluated,)
    assert _journal(tmp_path).resume_parent_snapshot(context) == sealed
    assert sealed.execution_uses[0].host_boot_id == use.host_boot_id
    assert sealed.execution_uses[0].subject_digest == use.subject_digest


def test_consumption_and_seal_race_has_one_original_cas_winner(tmp_path):
    journal, context = _enrolled(tmp_path)

    def consume():
        try:
            _consume(
                _journal(tmp_path),
                _subject(),
                expected_journal_revision=2,
                parent_context=context,
            )
            return "consumed"
        except execution.PluginExecutionJournalError as error:
            return error.code

    def seal():
        try:
            _journal(tmp_path).seal_resume_parent(context, expected_journal_revision=2)
            return "sealed"
        except execution.PluginExecutionJournalError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(consume), pool.submit(seal)
        outcomes = {first.result(), second.result()}
    assert outcomes in (
        {"consumed", "plugin_execution_journal_revision_conflict"},
        {"sealed", "plugin_execution_journal_revision_conflict"},
        {"sealed", "plugin_execution_resume_parent_sealed"},
    )
    snapshot = journal.resume_parent_snapshot(context)
    assert snapshot.journal_revision == 3
    assert len(snapshot.execution_uses) == (0 if snapshot.sealed else 1)


def test_invalid_seal_preserves_native_journal_partial_tail(tmp_path):
    journal, context = _enrolled(tmp_path)
    _consume(journal, _subject(), expected_journal_revision=2, parent_context=context)
    journal.seal_resume_parent(context, expected_journal_revision=3)
    records = [json.loads(line) for line in journal.path.read_text().splitlines()]
    records[-1]["payload"]["membershipDigest"] = "f" * 64
    original = (
        "".join(json.dumps(record) + "\n" for record in records) + '{"eventVersion":'
    ).encode()
    journal.path.write_bytes(original)
    with pytest.raises(execution.PluginExecutionJournalError):
        _journal(tmp_path).resume_parent_snapshot(context)
    assert journal.path.read_bytes() == original


def test_one_parent_enumerates_multiple_native_uses_without_collapsing_operations(
    tmp_path,
):
    decisions = iter(("1" * 48, "3" * 48))
    uses = iter(("2" * 48, "4" * 48))
    journal = execution.PluginExecutionDecisionJournal(
        tmp_path / "plugin-execution-decisions.jsonl",
        scope_kind="workspace",
        scope_id="workspace",
        decision_id_factory=lambda: next(decisions),
        execution_use_id_factory=lambda: next(uses),
        clock=lambda: 2500,
    )
    _issue(journal, _subject())
    context = _context(journal)
    journal.enroll_resume_parent(context, expected_journal_revision=1)
    first = _consume(
        journal, _subject(), expected_journal_revision=2, parent_context=context
    )
    second_subject = replace(_subject(), configuration_map_fingerprint="9" * 64)
    decision = _issue(journal, second_subject, expected_journal_revision=3)
    second = _consume(
        journal,
        second_subject,
        decision_id=decision.decision_id,
        expected_journal_revision=4,
        parent_context=context,
    )
    sealed = journal.seal_resume_parent(context, expected_journal_revision=5)
    assert sealed.execution_uses == (first, second)
    assert _journal(tmp_path).resume_parent_snapshot(context) == sealed


def test_unknown_parent_and_unresolved_start_refuse_before_partial_tail_repair(
    tmp_path,
):
    journal, context = _enrolled(tmp_path)
    use = _consume(
        journal, _subject(), expected_journal_revision=2, parent_context=context
    )
    _transition(
        journal,
        use.execution_use_id,
        expected_state="CONSUMED_NOT_STARTED",
        target_state="STARTING",
        expected_journal_revision=3,
    )
    original = journal.path.read_bytes() + b'{"eventVersion":2'
    journal.path.write_bytes(original)
    with pytest.raises(execution.PluginExecutionJournalError) as caught:
        journal.resume_parent_snapshot(replace(context, request_id="not-enrolled"))
    assert caught.value.code == "plugin_execution_resume_parent_unknown"
    assert journal.path.read_bytes() == original
    with pytest.raises(execution.PluginExecutionJournalError) as caught:
        journal.seal_resume_parent(context, expected_journal_revision=4)
    assert caught.value.code == "plugin_execution_resume_start_unknown"
    assert journal.path.read_bytes() == original


def test_forged_late_start_is_rejected_by_original_replay_before_tail_repair(tmp_path):
    journal, context = _enrolled(tmp_path)
    use = _consume(
        journal, _subject(), expected_journal_revision=2, parent_context=context
    )
    journal.seal_resume_parent(context, expected_journal_revision=3)
    event = {
        "eventKind": "execution_use_transitioned",
        "eventVersion": 1,
        "journalRevision": 5,
        "expectedJournalRevision": 4,
        "payload": {
            "expectedState": "CONSUMED_NOT_STARTED",
            "reservation": replace(use, state="STARTING").to_dict(),
            "transitionedAtUnixMs": 2100,
        },
    }
    original = (
        journal.path.read_bytes() + json.dumps(event).encode() + b'\n{"eventVersion":'
    )
    journal.path.write_bytes(original)
    with pytest.raises(execution.PluginExecutionJournalError):
        _journal(tmp_path).resume_parent_snapshot(context)
    assert journal.path.read_bytes() == original


@pytest.mark.parametrize("field", ["intent_digest", "request_id"])
def test_enrollment_cannot_rebind_existing_attempt_to_another_intent(tmp_path, field):
    journal, context = _enrolled(tmp_path)
    conflicting = replace(
        context, **{field: "d" * 64 if field.endswith("digest") else "request-2"}
    )
    original = journal.path.read_bytes()
    with pytest.raises(execution.PluginExecutionJournalError) as caught:
        journal.enroll_resume_parent(conflicting, expected_journal_revision=2)
    assert caught.value.code == "plugin_execution_resume_parent_conflict"
    assert journal.path.read_bytes() == original


def test_empty_seal_requires_original_enrollment_and_fences_future_native_use(tmp_path):
    journal, context = _enrolled(tmp_path)
    sealed = journal.seal_resume_parent(context, expected_journal_revision=2)
    assert sealed.sealed
    assert sealed.execution_uses == ()
    assert sealed.membership_digest is not None
    assert _journal(tmp_path).resume_parent_snapshot(context) == sealed
    original = journal.path.read_bytes()
    with pytest.raises(execution.PluginExecutionJournalError) as caught:
        _consume(
            journal, _subject(), expected_journal_revision=3, parent_context=context
        )
    assert caught.value.code == "plugin_execution_resume_parent_sealed"
    assert journal.path.read_bytes() == original
