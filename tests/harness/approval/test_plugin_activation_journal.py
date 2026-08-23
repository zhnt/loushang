from __future__ import annotations

import json
from pathlib import Path

import pytest

from loushang.harness.approval.plugin_activation import (
    ContributionActivationApprovalSubject,
    PluginActivationDecisionJournal,
    PluginActivationJournalError,
)
from loushang.harness.approval.plugin_execution import (
    PluginApprovalAuthorizationV1,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef


def test_activation_decision_and_attempt_are_durable_one_shot_authority(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    subject = _subject()
    decision = journal.issue_activation_decision(
        subject,
        disposition="approved",
        authorization=PluginApprovalAuthorizationV1.direct(
            actor_id="operator:alice",
            source="test-policy",
        ),
        issued_at_unix_ms=1_000,
        expires_at_unix_ms=3_000,
        expected_journal_revision=0,
    )
    reservation = journal.consume_activation_decision(
        subject,
        decision_id=decision.decision_id,
        host_boot_id="3" * 32,
        import_realm_id="4" * 32,
        expected_journal_revision=1,
    )

    assert reservation.state == "CONSUMED_NOT_STARTED"
    assert reservation.activation_use_id == "2" * 48
    recovered = _journal(tmp_path).snapshot()
    assert recovered.journal_revision == 2
    assert recovered.decisions[0].consumption_state == "CONSUMED"
    assert recovered.activation_uses == (reservation,)

    with pytest.raises(PluginActivationJournalError) as consumed:
        journal.consume_activation_decision(
            subject,
            decision_id=decision.decision_id,
            host_boot_id="3" * 32,
            import_realm_id="4" * 32,
            expected_journal_revision=2,
        )
    assert consumed.value.code == "plugin_activation_decision_consumed"


def test_activation_attempt_enforces_exact_owner_transitions_and_fencing(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    decision = _issue(journal)
    reservation = _consume(journal, decision.decision_id)

    starting = journal.transition_activation_use(
        reservation.activation_use_id,
        expected_state="CONSUMED_NOT_STARTED",
        target_state="STARTING",
        host_boot_id="3" * 32,
        import_realm_id="4" * 32,
        transitioned_at_unix_ms=2_100,
        expected_journal_revision=2,
    )
    started = journal.transition_activation_use(
        starting.activation_use_id,
        expected_state="STARTING",
        target_state="STARTED",
        host_boot_id="3" * 32,
        import_realm_id="4" * 32,
        transitioned_at_unix_ms=2_200,
        expected_journal_revision=3,
    )
    committed = journal.transition_activation_use(
        started.activation_use_id,
        expected_state="STARTED",
        target_state="COMMITTED",
        host_boot_id="3" * 32,
        import_realm_id="4" * 32,
        transitioned_at_unix_ms=2_300,
        expected_journal_revision=4,
    )
    assert committed.state == "COMMITTED"

    with pytest.raises(PluginActivationJournalError) as terminal:
        journal.transition_activation_use(
            committed.activation_use_id,
            expected_state="COMMITTED",
            target_state="FAILED",
            host_boot_id="3" * 32,
            import_realm_id="4" * 32,
            transitioned_at_unix_ms=2_400,
            expected_journal_revision=5,
        )
    assert terminal.value.code == "plugin_activation_use_transition_invalid"


def test_activation_consumption_rechecks_subject_policy_trust_epoch_and_expiry(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    decision = _issue(journal)

    changed = _subject(owner_policy_revision="owner-policy-2")
    with pytest.raises(PluginActivationJournalError) as mismatch:
        journal.consume_activation_decision(
            changed,
            decision_id=decision.decision_id,
            host_boot_id="3" * 32,
            import_realm_id="4" * 32,
            expected_journal_revision=1,
        )
    assert mismatch.value.code == "plugin_activation_decision_subject_mismatch"

    expired = _journal(tmp_path, now=4_000)
    with pytest.raises(PluginActivationJournalError) as expiry:
        expired.consume_activation_decision(
            _subject(),
            decision_id=decision.decision_id,
            host_boot_id="3" * 32,
            import_realm_id="4" * 32,
            expected_journal_revision=1,
        )
    assert expiry.value.code == "plugin_activation_decision_expired"


def test_activation_decision_revocation_is_durable_and_blocks_consumption(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    decision = _issue(journal)

    revoked = journal.revoke_activation_decision(
        decision.decision_id,
        actor_id="operator:alice",
        source="test-policy",
        revoked_at_unix_ms=1_500,
        expected_journal_revision=1,
    )

    assert revoked.consumption_state == "REVOKED"
    assert _journal(tmp_path).snapshot().decisions == (revoked,)
    with pytest.raises(PluginActivationJournalError) as caught:
        journal.consume_activation_decision(
            _subject(),
            decision_id=decision.decision_id,
            host_boot_id="3" * 32,
            import_realm_id="4" * 32,
            expected_journal_revision=2,
        )
    assert caught.value.code == "plugin_activation_decision_revoked"


def test_activation_replay_rejects_immutable_reservation_identity_drift(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    _consume(journal, _issue(journal).decision_id)
    records = tuple(
        json.loads(line)
        for line in journal.path.read_text(encoding="utf-8").splitlines()
    )
    records[1]["payload"]["reservation"]["subjectDigest"] = "7" * 64
    journal.path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )

    with pytest.raises(PluginActivationJournalError) as caught:
        _journal(tmp_path).snapshot()
    assert caught.value.code == "plugin_activation_journal_corrupt"


def test_recovery_cancels_unstarted_and_fails_possibly_started_attempts(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    first = _consume(journal, _issue(journal).decision_id)
    second_subject = _subject(candidate_fingerprint="9" * 64)
    second_decision = _issue(
        journal,
        subject=second_subject,
        expected_journal_revision=2,
    )
    second = journal.consume_activation_decision(
        second_subject,
        decision_id=second_decision.decision_id,
        host_boot_id="3" * 32,
        import_realm_id="4" * 32,
        expected_journal_revision=3,
    )
    journal.transition_activation_use(
        second.activation_use_id,
        expected_state="CONSUMED_NOT_STARTED",
        target_state="STARTING",
        host_boot_id="3" * 32,
        import_realm_id="4" * 32,
        transitioned_at_unix_ms=2_100,
        expected_journal_revision=4,
    )

    recovered = journal.recover_activation_uses(
        current_host_boot_id="8" * 32,
        recovered_at_unix_ms=2_500,
        expected_journal_revision=5,
    )
    assert tuple(item.state for item in recovered) == (
        "CANCELLED_BEFORE_START",
        "FAILED",
    )
    assert {item.activation_use_id for item in recovered} == {
        first.activation_use_id,
        second.activation_use_id,
    }


def _journal(tmp_path: Path, *, now: int = 2_000) -> PluginActivationDecisionJournal:
    ids = iter(("1" * 48, "2" * 48, "5" * 48, "6" * 48))
    return PluginActivationDecisionJournal(
        tmp_path / "activation.jsonl",
        scope_id="workspace:test",
        identity_factory=lambda: next(ids),
        clock=lambda: now,
    )


def _issue(
    journal: PluginActivationDecisionJournal,
    *,
    subject: ContributionActivationApprovalSubject | None = None,
    expected_journal_revision: int = 0,
):
    return journal.issue_activation_decision(
        subject or _subject(),
        disposition="approved",
        authorization=PluginApprovalAuthorizationV1.direct(
            actor_id="operator:alice",
            source="test-policy",
        ),
        issued_at_unix_ms=1_000,
        expires_at_unix_ms=3_000,
        expected_journal_revision=expected_journal_revision,
    )


def _consume(
    journal: PluginActivationDecisionJournal,
    decision_id: str,
):
    return journal.consume_activation_decision(
        _subject(),
        decision_id=decision_id,
        host_boot_id="3" * 32,
        import_realm_id="4" * 32,
        expected_journal_revision=1,
    )


def _subject(
    *,
    candidate_fingerprint: str = "a" * 64,
    owner_policy_revision: str = "owner-policy-1",
) -> ContributionActivationApprovalSubject:
    return ContributionActivationApprovalSubject(
        candidate_fingerprint=candidate_fingerprint,
        admission_fingerprint="b" * 64,
        binding_spec_fingerprint="c" * 64,
        capability_id="synthetic.semantic",
        owner_id="synthetic",
        provider_id="org.loushang.synthetic/default",
        plugin_id="foundation-sample",
        contribution_id="semantic-provider",
        package_content_digest="d" * 64,
        dependency_lock_digest="e" * 64,
        product_id="coding",
        scope_id="workspace:test",
        instance_revision_ref=PluginInstanceRevisionRef(
            instance_id="foundation-sample@workspace:test",
            plugin_id="foundation-sample",
            revision=1,
        ),
        source_trust_class="host-equivalent-local",
        source_trust_policy_revision="trust-1",
        product_policy_revision="product-policy-1",
        owner_policy_revision=owner_policy_revision,
        revocation_epoch=3,
        effective_facets=("query",),
        effective_authorities=(),
        execution_model="in_process",
    )
