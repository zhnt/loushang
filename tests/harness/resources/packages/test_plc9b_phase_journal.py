from __future__ import annotations

from pathlib import Path

import pytest

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
