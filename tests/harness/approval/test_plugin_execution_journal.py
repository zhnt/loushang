from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.harness.approval.plugin_execution import (
    PluginApprovalAuthorizationV1,
    PluginExecutionDecisionJournal,
    PluginExecutionJournalError,
    PluginImportRealmRefV1,
)
from loushang.harness.resources.plugins.selection import (
    PluginExecutionApprovalSubject,
    PluginExecutionDecisionCurrent,
    PluginExecutionDecisionMissing,
    PluginInstanceRevisionRef,
)


def test_approved_decision_is_durable_and_projects_the_strict_v2_view(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    subject = _subject()

    issued = journal.issue_execution_decision(
        subject,
        disposition="approved",
        authorization=PluginApprovalAuthorizationV1.direct(
            actor_id="operator:alice",
            source="coding.settings",
        ),
        revocation_epoch=7,
        issued_at_unix_ms=1_000,
        expires_at_unix_ms=3_000,
        expected_journal_revision=0,
    )

    current = journal.lookup_execution_decision(subject)
    assert isinstance(current, PluginExecutionDecisionCurrent)
    assert current.decision.to_dict() == {
        "decisionId": "1" * 48,
        "decisionRecordVersion": 2,
        "disposition": "approved",
        "policyRevision": "policy-1",
        "subjectDigest": subject.digest,
        "subjectSchemaVersion": 2,
    }
    assert issued.decision_id == current.decision.decision_id
    assert issued.consumption_state == "AVAILABLE"

    recovered = _journal(tmp_path).snapshot()
    assert recovered.journal_revision == 1
    assert recovered.decisions == (issued,)
    assert recovered.execution_uses == ()


def test_denied_decision_projects_denied_but_cannot_be_consumed(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    subject = _subject()
    journal.issue_execution_decision(
        subject,
        disposition="denied",
        authorization=PluginApprovalAuthorizationV1.direct(
            actor_id="policy:root",
            source="headless-policy",
        ),
        revocation_epoch=0,
        issued_at_unix_ms=1_000,
        expires_at_unix_ms=3_000,
        expected_journal_revision=0,
    )

    current = journal.lookup_execution_decision(subject)
    assert isinstance(current, PluginExecutionDecisionCurrent)
    assert current.decision.disposition == "denied"

    with pytest.raises(PluginExecutionJournalError) as caught:
        _consume(journal, subject, expected_journal_revision=1)
    assert caught.value.code == "plugin_execution_decision_denied"
    assert journal.snapshot().execution_uses == ()


def test_issue_rejects_a_second_live_decision_for_the_same_subject(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    subject = _subject()
    _issue(journal, subject)

    with pytest.raises(PluginExecutionJournalError) as caught:
        _issue(journal, subject, expected_journal_revision=1)

    assert caught.value.code == "plugin_execution_subject_decision_active"
    assert journal.snapshot().journal_revision == 1


@pytest.mark.parametrize(
    ("change", "expected_code"),
    [
        (
            {"configuration_map_fingerprint": "9" * 64},
            "plugin_execution_decision_subject_mismatch",
        ),
        (
            {"scope_id": "other-workspace"},
            "plugin_execution_decision_scope_mismatch",
        ),
    ],
)
def test_consumption_rejects_wrong_digest_or_scope_before_creating_a_use(
    tmp_path: Path,
    change: dict[str, object],
    expected_code: str,
) -> None:
    journal = _journal(tmp_path)
    subject = _subject()
    issued = _issue(journal, subject)
    changed = replace(subject, **change)

    with pytest.raises(PluginExecutionJournalError) as caught:
        _consume(
            journal,
            changed,
            decision_id=issued.decision_id,
            expected_journal_revision=1,
        )

    assert caught.value.code == expected_code
    assert journal.snapshot().execution_uses == ()


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [
        (
            {"current_policy_revision": "policy-2"},
            "plugin_execution_decision_policy_stale",
        ),
        (
            {"current_source_trust_policy_revision": "trust-2"},
            "plugin_execution_decision_trust_stale",
        ),
        (
            {"expected_revocation_epoch": 8},
            "plugin_execution_decision_revocation_stale",
        ),
    ],
)
def test_consumption_revalidates_policy_trust_and_revocation_epoch(
    tmp_path: Path,
    overrides: dict[str, object],
    expected_code: str,
) -> None:
    journal = _journal(tmp_path)
    subject = _subject()
    issued = _issue(journal, subject, revocation_epoch=7)
    consumption = {
        "expected_revocation_epoch": 7,
        **overrides,
    }

    with pytest.raises(PluginExecutionJournalError) as caught:
        _consume(
            journal,
            subject,
            decision_id=issued.decision_id,
            expected_journal_revision=1,
            **consumption,
        )

    assert caught.value.code == expected_code
    assert journal.snapshot().execution_uses == ()


def test_expired_decision_is_not_projected_or_consumed(tmp_path: Path) -> None:
    journal = _journal(tmp_path, now=4_000)
    subject = _subject()
    issued = _issue(journal, subject)

    assert isinstance(
        journal.lookup_execution_decision(subject),
        PluginExecutionDecisionMissing,
    )
    with pytest.raises(PluginExecutionJournalError) as caught:
        _consume(
            journal,
            subject,
            decision_id=issued.decision_id,
            expected_journal_revision=1,
        )
    assert caught.value.code == "plugin_execution_decision_expired"


def test_atomic_consumption_persists_one_shot_use_and_replays_together(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    subject = _subject()
    issued = _issue(journal, subject, revocation_epoch=7)

    reservation = _consume(
        journal,
        subject,
        decision_id=issued.decision_id,
        expected_journal_revision=1,
        expected_revocation_epoch=7,
    )

    assert reservation.to_dict() == {
        "decisionId": issued.decision_id,
        "executionUseId": "2" * 48,
        "executionUseVersion": 1,
        "hostBootId": "3" * 32,
        "importRealmId": "4" * 32,
        "instanceRevisionRef": subject.instance_revision_ref.to_dict(),
        "policyRevision": "policy-1",
        "preflightUseId": "5" * 48,
        "revocationEpoch": 7,
        "sourceGroupId": "6" * 64,
        "sourceTrustPolicyRevision": "trust-1",
        "state": "CONSUMED_NOT_STARTED",
        "subjectDigest": subject.digest,
    }
    recovered = _journal(tmp_path).snapshot()
    assert recovered.journal_revision == 2
    assert recovered.execution_uses == (reservation,)
    assert recovered.decisions[0].consumption_state == "CONSUMED"
    assert (
        recovered.decisions[0].consumed_execution_use_id == reservation.execution_use_id
    )
    records = [
        json.loads(line)
        for line in journal.path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 2
    assert records[1]["expectedJournalRevision"] == 1
    assert records[1]["journalRevision"] == 2
    assert records[1]["eventKind"] == "execution_consumed"
    assert set(records[1]["payload"]) == {
        "consumedAtUnixMs",
        "decision",
        "expectedDecisionRevision",
        "reservation",
    }

    with pytest.raises(PluginExecutionJournalError) as caught:
        _consume(
            _journal(tmp_path),
            subject,
            decision_id=issued.decision_id,
            expected_journal_revision=2,
            expected_revocation_epoch=7,
        )
    assert caught.value.code == "plugin_execution_decision_consumed"


def test_execution_use_transitions_to_evaluated_and_projects_exact_receipt(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    subject = _subject()
    issued = _issue(journal, subject, revocation_epoch=7)
    reservation = _consume(
        journal,
        subject,
        decision_id=issued.decision_id,
        expected_journal_revision=1,
        expected_revocation_epoch=7,
    )

    starting = _transition(
        journal,
        reservation.execution_use_id,
        expected_state="CONSUMED_NOT_STARTED",
        target_state="STARTING",
        expected_journal_revision=2,
    )
    evaluated = _transition(
        journal,
        reservation.execution_use_id,
        expected_state="STARTING",
        target_state="EVALUATED",
        expected_journal_revision=3,
    )
    receipt = journal.execution_consumption_receipt(
        reservation.execution_use_id,
        current_host_boot_id="3" * 32,
        current_import_realm_id="4" * 32,
    )

    assert starting.state == "STARTING"
    assert evaluated.state == "EVALUATED"
    assert receipt.to_dict() == {
        "decisionId": issued.decision_id,
        "executionUseId": reservation.execution_use_id,
        "hostBootId": "3" * 32,
        "importRealmId": "4" * 32,
        "instanceRevisionRef": subject.instance_revision_ref.to_dict(),
        "policyRevision": "policy-1",
        "preflightUseId": "5" * 48,
        "receiptVersion": 1,
        "revocationEpoch": 7,
        "sourceGroupId": "6" * 64,
        "sourceTrustPolicyRevision": "trust-1",
        "state": "EVALUATED",
        "subjectDigest": subject.digest,
    }
    recovered = _journal(tmp_path).snapshot()
    assert recovered.journal_revision == 4
    assert recovered.execution_uses == (evaluated,)


@pytest.mark.parametrize(
    ("expected_state", "target_state", "host_boot_id", "import_realm_id", "code"),
    [
        (
            "CONSUMED_NOT_STARTED",
            "EVALUATED",
            "3" * 32,
            "4" * 32,
            "plugin_execution_use_transition_invalid",
        ),
        (
            "STARTING",
            "FAILED_AFTER_START",
            "3" * 32,
            "4" * 32,
            "plugin_execution_use_state_conflict",
        ),
        (
            "CONSUMED_NOT_STARTED",
            "STARTING",
            "7" * 32,
            "4" * 32,
            "plugin_execution_import_realm_mismatch",
        ),
        (
            "CONSUMED_NOT_STARTED",
            "STARTING",
            "3" * 32,
            "8" * 32,
            "plugin_execution_import_realm_mismatch",
        ),
    ],
)
def test_execution_use_transition_fails_closed_without_append(
    tmp_path: Path,
    expected_state: str,
    target_state: str,
    host_boot_id: str,
    import_realm_id: str,
    code: str,
) -> None:
    journal = _journal(tmp_path)
    subject = _subject()
    _issue(journal, subject)
    reservation = _consume(journal, subject, expected_journal_revision=1)

    with pytest.raises(PluginExecutionJournalError) as caught:
        journal.transition_execution_use(
            reservation.execution_use_id,
            expected_state=expected_state,
            target_state=target_state,
            host_boot_id=host_boot_id,
            import_realm_id=import_realm_id,
            transitioned_at_unix_ms=2_100,
            expected_journal_revision=2,
        )

    assert caught.value.code == code
    assert journal.snapshot().journal_revision == 2


def test_failed_after_start_marks_import_realm_polluted_and_has_no_receipt(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    subject = _subject()
    _issue(journal, subject)
    reservation = _consume(journal, subject, expected_journal_revision=1)
    _transition(
        journal,
        reservation.execution_use_id,
        expected_state="CONSUMED_NOT_STARTED",
        target_state="STARTING",
        expected_journal_revision=2,
    )
    failed = _transition(
        journal,
        reservation.execution_use_id,
        expected_state="STARTING",
        target_state="FAILED_AFTER_START",
        expected_journal_revision=3,
    )

    recovery = journal.recover_execution_uses(
        current_host_boot_id="7" * 32,
        recovered_at_unix_ms=2_300,
        expected_journal_revision=4,
    )

    assert failed.state == "FAILED_AFTER_START"
    assert recovery.journal_revision == 4
    assert recovery.cancelled_before_start == ()
    assert recovery.polluted_import_realms == (
        PluginImportRealmRefV1(
            host_boot_id="3" * 32,
            import_realm_id="4" * 32,
        ),
    )
    with pytest.raises(PluginExecutionJournalError) as caught:
        journal.execution_consumption_receipt(
            reservation.execution_use_id,
            current_host_boot_id="3" * 32,
            current_import_realm_id="4" * 32,
        )
    assert caught.value.code == "plugin_execution_receipt_unavailable"


def test_external_boot_not_started_use_is_cancelled_once_during_recovery(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    subject = _subject()
    _issue(journal, subject)
    _consume(journal, subject, expected_journal_revision=1)

    recovered = journal.recover_execution_uses(
        current_host_boot_id="7" * 32,
        recovered_at_unix_ms=2_200,
        expected_journal_revision=2,
    )
    repeated = journal.recover_execution_uses(
        current_host_boot_id="7" * 32,
        recovered_at_unix_ms=2_300,
        expected_journal_revision=3,
    )

    assert recovered.journal_revision == 3
    assert len(recovered.cancelled_before_start) == 1
    assert recovered.cancelled_before_start[0].state == "CANCELLED_BEFORE_START"
    assert recovered.polluted_import_realms == ()
    assert repeated.journal_revision == 3
    assert repeated.cancelled_before_start == ()
    assert repeated.polluted_import_realms == ()
    assert _journal(tmp_path).snapshot().execution_uses[0].state == (
        "CANCELLED_BEFORE_START"
    )


def test_recovery_cancels_multiple_external_uses_in_one_durable_event(
    tmp_path: Path,
) -> None:
    decision_ids = iter(("1" * 48, "8" * 48))
    execution_use_ids = iter(("2" * 48, "9" * 48))
    journal = PluginExecutionDecisionJournal(
        tmp_path / "plugin-execution-decisions.jsonl",
        scope_kind="workspace",
        scope_id="workspace",
        decision_id_factory=lambda: next(decision_ids),
        execution_use_id_factory=lambda: next(execution_use_ids),
        clock=lambda: 2_500,
    )
    first_subject = _subject()
    second_subject = replace(
        first_subject,
        configuration_map_fingerprint="7" * 64,
    )
    first_decision = _issue(journal, first_subject)
    first_use = _consume(
        journal,
        first_subject,
        decision_id=first_decision.decision_id,
        expected_journal_revision=1,
    )
    second_decision = _issue(
        journal,
        second_subject,
        expected_journal_revision=2,
    )
    second_use = _consume(
        journal,
        second_subject,
        decision_id=second_decision.decision_id,
        expected_journal_revision=3,
    )

    recovered = journal.recover_execution_uses(
        current_host_boot_id="7" * 32,
        recovered_at_unix_ms=2_200,
        expected_journal_revision=4,
    )

    assert recovered.journal_revision == 5
    assert tuple(
        item.execution_use_id for item in recovered.cancelled_before_start
    ) == (first_use.execution_use_id, second_use.execution_use_id)
    records = [
        json.loads(line)
        for line in journal.path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 5
    assert records[-1]["eventKind"] == "execution_uses_recovered"
    assert len(records[-1]["payload"]["reservations"]) == 2


def test_current_boot_not_started_use_is_not_cancelled_by_recovery(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    subject = _subject()
    _issue(journal, subject)
    reservation = _consume(journal, subject, expected_journal_revision=1)

    recovered = journal.recover_execution_uses(
        current_host_boot_id="3" * 32,
        recovered_at_unix_ms=2_100,
        expected_journal_revision=2,
    )

    assert recovered.journal_revision == 2
    assert recovered.cancelled_before_start == ()
    assert recovered.polluted_import_realms == ()
    assert journal.snapshot().execution_uses == (reservation,)


def test_evaluated_receipt_is_current_boot_and_realm_bound(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    subject = _subject()
    _issue(journal, subject)
    reservation = _consume(journal, subject, expected_journal_revision=1)
    _transition(
        journal,
        reservation.execution_use_id,
        expected_state="CONSUMED_NOT_STARTED",
        target_state="STARTING",
        expected_journal_revision=2,
    )
    _transition(
        journal,
        reservation.execution_use_id,
        expected_state="STARTING",
        target_state="EVALUATED",
        expected_journal_revision=3,
    )

    with pytest.raises(PluginExecutionJournalError) as wrong_boot:
        journal.execution_consumption_receipt(
            reservation.execution_use_id,
            current_host_boot_id="7" * 32,
            current_import_realm_id="4" * 32,
        )
    assert wrong_boot.value.code == "plugin_execution_import_realm_mismatch"
    with pytest.raises(PluginExecutionJournalError) as wrong_realm:
        journal.execution_consumption_receipt(
            reservation.execution_use_id,
            current_host_boot_id="3" * 32,
            current_import_realm_id="8" * 32,
        )
    assert wrong_realm.value.code == "plugin_execution_import_realm_mismatch"


def test_retained_authority_must_still_be_live_at_consumption(tmp_path: Path) -> None:
    subject = _subject()
    journal = _journal(tmp_path, retained_authority_live=False)
    issued = journal.issue_execution_decision(
        subject,
        disposition="approved",
        authorization=PluginApprovalAuthorizationV1.policy_rule(
            actor_id="operator:alice",
            source="coding.settings",
            authority_id="rule-7",
        ),
        revocation_epoch=0,
        issued_at_unix_ms=1_000,
        expires_at_unix_ms=3_000,
        expected_journal_revision=0,
    )

    with pytest.raises(PluginExecutionJournalError) as caught:
        _consume(
            journal,
            subject,
            decision_id=issued.decision_id,
            expected_journal_revision=1,
        )
    assert caught.value.code == "plugin_execution_authorization_stale"


def test_revoke_is_durable_and_makes_the_selection_view_missing(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    subject = _subject()
    issued = _issue(journal, subject, revocation_epoch=7)

    revoked = journal.revoke_execution_decision(
        issued.decision_id,
        revocation_epoch=8,
        actor_id="operator:bob",
        source="security-response",
        revoked_at_unix_ms=1_600,
        expected_journal_revision=1,
    )

    assert revoked.consumption_state == "REVOKED"
    assert revoked.revocation_epoch == 8
    assert isinstance(
        journal.lookup_execution_decision(subject),
        PluginExecutionDecisionMissing,
    )
    with pytest.raises(PluginExecutionJournalError) as caught:
        _consume(
            _journal(tmp_path),
            subject,
            decision_id=issued.decision_id,
            expected_journal_revision=2,
            expected_revocation_epoch=8,
        )
    assert caught.value.code == "plugin_execution_decision_revoked"


def test_consume_and_revoke_have_one_file_lock_linearization(tmp_path: Path) -> None:
    subject = _subject()
    issued = _issue(_journal(tmp_path), subject, revocation_epoch=7)

    def consume() -> str:
        try:
            _consume(
                _journal(tmp_path),
                subject,
                decision_id=issued.decision_id,
                expected_journal_revision=1,
                expected_revocation_epoch=7,
            )
        except PluginExecutionJournalError as exc:
            return exc.code
        return "consumed"

    def revoke() -> str:
        try:
            _journal(tmp_path).revoke_execution_decision(
                issued.decision_id,
                revocation_epoch=8,
                actor_id="security",
                source="policy-reload",
                revoked_at_unix_ms=1_700,
                expected_journal_revision=1,
            )
        except PluginExecutionJournalError as exc:
            return exc.code
        return "revoked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        consume_future = pool.submit(consume)
        revoke_future = pool.submit(revoke)
        outcomes = {consume_future.result(), revoke_future.result()}

    assert outcomes in (
        {"consumed", "plugin_execution_journal_revision_conflict"},
        {"revoked", "plugin_execution_journal_revision_conflict"},
    )
    snapshot = _journal(tmp_path).snapshot()
    assert snapshot.journal_revision == 2
    assert (len(snapshot.execution_uses), snapshot.decisions[0].consumption_state) in {
        (1, "CONSUMED"),
        (0, "REVOKED"),
    }


def test_expected_revision_conflict_writes_nothing(tmp_path: Path) -> None:
    journal = _journal(tmp_path)

    with pytest.raises(PluginExecutionJournalError) as caught:
        _issue(journal, _subject(), expected_journal_revision=1)

    assert caught.value.code == "plugin_execution_journal_revision_conflict"
    assert journal.snapshot().journal_revision == 0


def test_recovery_rejects_a_journal_opened_as_another_scope_kind(
    tmp_path: Path,
) -> None:
    subject = _subject()
    _issue(_journal(tmp_path), subject)
    installation = PluginExecutionDecisionJournal(
        tmp_path / "plugin-execution-decisions.jsonl",
        scope_kind="installation",
        scope_id="workspace",
    )

    with pytest.raises(PluginExecutionJournalError) as caught:
        installation.snapshot()

    assert caught.value.code == "plugin_execution_journal_corrupt"


def test_recovery_repairs_only_a_partial_final_event(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    issued = _issue(journal, _subject())
    with journal.path.open("a", encoding="utf-8") as handle:
        handle.write('{"eventKind":"execution_consumed"')

    recovered = _journal(tmp_path).snapshot()

    assert recovered.journal_revision == 1
    assert recovered.decisions == (issued,)
    assert len(journal.path.read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda record: {**record, "eventVersion": 2},
            "unsupported_plugin_execution_journal_record_version",
        ),
        (
            lambda record: {
                key: value for key, value in record.items() if key != "payload"
            },
            "invalid_plugin_execution_journal_record",
        ),
    ],
)
def test_recovery_fails_closed_on_a_complete_invalid_event(
    tmp_path: Path,
    mutate,
    expected_code: str,
) -> None:
    journal = _journal(tmp_path)
    _issue(journal, _subject())
    record = json.loads(journal.path.read_text(encoding="utf-8"))
    journal.path.write_text(
        json.dumps(mutate(record), separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PluginExecutionJournalError) as caught:
        _journal(tmp_path).snapshot()

    assert caught.value.code == expected_code


def _journal(
    tmp_path: Path,
    *,
    now: int = 2_500,
    retained_authority_live: bool = True,
) -> PluginExecutionDecisionJournal:
    return PluginExecutionDecisionJournal(
        tmp_path / "plugin-execution-decisions.jsonl",
        scope_kind="workspace",
        scope_id="workspace",
        decision_id_factory=lambda: "1" * 48,
        execution_use_id_factory=lambda: "2" * 48,
        clock=lambda: now,
        retained_authority_validator=lambda _authorization: retained_authority_live,
    )


def _issue(
    journal: PluginExecutionDecisionJournal,
    subject: PluginExecutionApprovalSubject,
    *,
    revocation_epoch: int = 0,
    expected_journal_revision: int = 0,
):
    return journal.issue_execution_decision(
        subject,
        disposition="approved",
        authorization=PluginApprovalAuthorizationV1.direct(
            actor_id="operator:alice",
            source="coding.settings",
        ),
        revocation_epoch=revocation_epoch,
        issued_at_unix_ms=1_000,
        expires_at_unix_ms=3_000,
        expected_journal_revision=expected_journal_revision,
    )


def _consume(
    journal: PluginExecutionDecisionJournal,
    subject: PluginExecutionApprovalSubject,
    *,
    decision_id: str = "1" * 48,
    expected_journal_revision: int,
    expected_revocation_epoch: int = 0,
    current_policy_revision: str = "policy-1",
    current_source_trust_policy_revision: str = "trust-1",
):
    return journal.consume_execution_decision(
        subject,
        decision_id=decision_id,
        preflight_use_id="5" * 48,
        source_group_id="6" * 64,
        host_boot_id="3" * 32,
        import_realm_id="4" * 32,
        expected_revocation_epoch=expected_revocation_epoch,
        current_policy_revision=current_policy_revision,
        current_source_trust_policy_revision=(current_source_trust_policy_revision),
        expected_journal_revision=expected_journal_revision,
    )


def _transition(
    journal: PluginExecutionDecisionJournal,
    execution_use_id: str,
    *,
    expected_state: str,
    target_state: str,
    expected_journal_revision: int,
):
    return journal.transition_execution_use(
        execution_use_id,
        expected_state=expected_state,
        target_state=target_state,
        host_boot_id="3" * 32,
        import_realm_id="4" * 32,
        transitioned_at_unix_ms=2_100 + expected_journal_revision,
        expected_journal_revision=expected_journal_revision,
    )


def _subject() -> PluginExecutionApprovalSubject:
    return PluginExecutionApprovalSubject(
        plugin_id="coding.lsp",
        package_content_digest="3" * 64,
        dependency_lock_digest="2" * 64,
        entrypoint="definition.py:define",
        package_source_identity="registry:example",
        source_trust_class="registry_signed",
        source_trust_policy_revision="trust-1",
        product_id="coding",
        scope_id="workspace",
        policy_revision="policy-1",
        ambient_host_authority=True,
        configuration_map_fingerprint="1" * 64,
        requested_authorities=("process.launch",),
        allowed_authority_ceiling=("process.launch",),
        reservation_closure_fingerprint="4" * 64,
        source_descriptor_fingerprint=(
            "c24ebbab018030bda115eee4257003ef8ac86423faa480fe158bce31fc0377b7"
        ),
        instance_revision_ref=PluginInstanceRevisionRef(
            instance_id="coding.lsp@product",
            plugin_id="coding.lsp",
            revision=1,
        ),
    )
