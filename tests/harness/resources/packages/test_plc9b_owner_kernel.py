from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle import (
    PackageClassificationBasisFactV1,
    PackageClassificationFactsV1,
    PackageLifecycleCancelRequestV1,
    PackageLifecycleFailureV1,
    PackageLifecycleIngressRequestV1,
    PackageLifecycleJournal,
    PackageLifecycleJournalError,
    PackageLifecycleOwner,
    PackageLifecycleRetryRequestV1,
    PackageLifecycleStatusV1,
    canonical_json_bytes,
)


@dataclass
class _ClassificationAuthority:
    facts: PackageClassificationFactsV1

    def classification_facts(
        self,
        _request: object,
    ) -> PackageClassificationFactsV1:
        return self.facts


def _fact(
    kind: str,
    *,
    present: bool,
    revision: str | None = None,
) -> PackageClassificationBasisFactV1:
    return PackageClassificationBasisFactV1(
        kind=kind,  # type: ignore[arg-type]
        present=present,
        authority_id=f"authority:{kind}",
        owner_revision=revision or f"revision:{kind}:1",
    )


def _facts(*present: str) -> PackageClassificationFactsV1:
    present_kinds = set(present)
    return PackageClassificationFactsV1(
        facts=tuple(
            _fact(kind, present=kind in present_kinds)
            for kind in (
                "explicit_plugin_intent",
                "existing_plugin_binding",
                "existing_plugin_history",
                "independent_non_plugin_authority",
            )
        ),
        policy_revision="package-classification-policy:1",
        classifier_epoch=1,
    )


def _request(
    *,
    operation_id: str = "operation-1",
    source_locator: str = "https://packages.example.test/acme.whl",
) -> PackageLifecycleIngressRequestV1:
    return PackageLifecycleIngressRequestV1(
        operation_id=operation_id,
        action="install",
        product_id="coding",
        scope_id="workspace:alpha",
        requested_package="acme==1.0",
        requested_plugin_id="acme.plugin",
        source_locator=source_locator,
        policy_revision="package-policy:1",
        quota_profile_revision="quota:1",
        resolution_environment_fingerprint="e" * 64,
    )


def _owner(
    tmp_path: Path,
    *,
    facts: PackageClassificationFactsV1,
    enabled: bool = True,
) -> tuple[PackageLifecycleOwner, PackageLifecycleJournal]:
    journal = PackageLifecycleJournal(tmp_path / "package-lifecycle.jsonl")
    return (
        PackageLifecycleOwner(
            journal=journal,
            classification_authority=_ClassificationAuthority(facts),
            enabled=enabled,
        ),
        journal,
    )


@pytest.mark.parametrize(
    ("present", "decision"),
    [
        (("explicit_plugin_intent",), "plugin_bound"),
        (("existing_plugin_binding",), "plugin_bound"),
        (("existing_plugin_history",), "plugin_bound"),
        (("independent_non_plugin_authority",), "non_plugin"),
        ((), "indeterminate"),
        (
            (
                "explicit_plugin_intent",
                "independent_non_plugin_authority",
            ),
            "plugin_bound",
        ),
    ],
)
def test_owner_classifies_only_from_owner_revisioned_facts(
    tmp_path: Path,
    present: tuple[str, ...],
    decision: str,
) -> None:
    owner, journal = _owner(tmp_path, facts=_facts(*present))

    status = owner.submit(_request())

    assert status.phase == "classified"
    assert status.classification is not None
    assert status.classification.decision == decision
    assert status.classification.request_fingerprint == status.request_fingerprint
    assert status.classification.policy_revision == (
        "package-classification-policy:1"
    )
    if decision == "indeterminate":
        assert status.disposition == "rejected"
        assert status.failure is not None
        assert status.failure.code == "package_target_classification_indeterminate"
    else:
        assert status.disposition == "active"
        assert status.failure is None
    assert journal.status("operation-1") == status


def test_transport_cannot_submit_a_classification_boolean(tmp_path: Path) -> None:
    owner, _journal = _owner(tmp_path, facts=_facts())
    values = {
        "operation_id": "operation-spoof",
        "action": "install",
        "product_id": "coding",
        "scope_id": "workspace:alpha",
        "requested_package": "acme==1.0",
        "requested_plugin_id": "acme.plugin",
        "source_locator": "https://packages.example.test/acme.whl",
        "policy_revision": "package-policy:1",
        "quota_profile_revision": "quota:1",
        "resolution_environment_fingerprint": "e" * 64,
        "plugin_bound": False,
    }

    with pytest.raises(TypeError):
        PackageLifecycleIngressRequestV1(**values)  # type: ignore[arg-type]

    status = owner.submit(
        _request(operation_id="operation-spoof")
    )
    assert status.disposition == "rejected"
    assert status.failure is not None
    assert status.failure.code == "package_target_classification_indeterminate"


def test_disabled_owner_returns_stable_refusal_without_journal_write(
    tmp_path: Path,
) -> None:
    owner, journal = _owner(
        tmp_path,
        facts=_facts("explicit_plugin_intent"),
        enabled=False,
    )

    first = owner.submit(_request())
    second = owner.submit(_request())

    assert first == second
    assert first.phase == "classified"
    assert first.disposition == "rejected"
    assert first.failure is not None
    assert first.failure.code == "package_route_unavailable"
    assert first.journal_revision == 0
    assert first.attempt_revision == 0
    assert journal.records() == ()
    assert not journal.path.exists()


def test_same_operation_fingerprint_converges_and_conflict_does_not_append(
    tmp_path: Path,
) -> None:
    owner, journal = _owner(
        tmp_path,
        facts=_facts("explicit_plugin_intent"),
    )

    first = owner.submit(_request())
    replay = owner.submit(_request())
    before_conflict = journal.records()

    assert replay == first
    conflict = owner.submit(
        _request(source_locator="https://packages.example.test/changed.whl")
    )
    assert conflict.disposition == "rejected"
    assert conflict.failure is not None
    assert conflict.failure.code == "package_operation_identity_conflict"
    assert journal.records() == before_conflict


def test_request_fingerprint_is_independent_from_operation_identity() -> None:
    facts = _facts("explicit_plugin_intent")
    first = _request(operation_id="operation-a").bind_classification_facts(facts)
    second = _request(operation_id="operation-b").bind_classification_facts(facts)

    assert first.operation_id != second.operation_id
    assert first.request_fingerprint == second.request_fingerprint


def test_concurrent_same_fingerprint_has_one_phase_sequence(tmp_path: Path) -> None:
    owner, journal = _owner(
        tmp_path,
        facts=_facts("explicit_plugin_intent"),
    )

    with ThreadPoolExecutor(max_workers=4) as executor:
        statuses = tuple(executor.map(lambda _index: owner.submit(_request()), range(8)))

    assert len(set(statuses)) == 1
    assert statuses[0].phase == "classified"
    assert len(journal.records()) == 2


@pytest.mark.parametrize("phase", ["accepted", "classified"])
def test_interruption_is_attempt_scoped_and_retry_resumes_last_proved_phase(
    tmp_path: Path,
    phase: str,
) -> None:
    owner, journal = _owner(
        tmp_path,
        facts=_facts("explicit_plugin_intent"),
    )
    accepted = owner.accept(_request())
    current = accepted if phase == "accepted" else owner.classify(
        accepted.operation_id,
        expected_journal_revision=accepted.journal_revision,
        expected_attempt_epoch=accepted.attempt_epoch,
    )

    interrupted = owner.interrupt(
        current.operation_id,
        expected_phase=current.phase,
        expected_journal_revision=current.journal_revision,
        expected_attempt_epoch=current.attempt_epoch,
    )

    assert interrupted.phase == phase
    assert interrupted.disposition == "retryable_failure"
    assert interrupted.failure is not None
    assert interrupted.failure.code == "package_operation_interrupted"
    assert interrupted.journal_revision == current.journal_revision
    assert interrupted.attempt_revision > current.attempt_revision
    resumed = owner.retry(
        PackageLifecycleRetryRequestV1(
            operation_id=current.operation_id,
            request_fingerprint=current.request_fingerprint,
            expected_attempt_epoch=current.attempt_epoch,
        )
    )
    assert resumed.phase == phase
    assert resumed.disposition == "active"
    assert resumed.attempt_epoch == current.attempt_epoch + 1
    assert resumed.request_fingerprint == current.request_fingerprint
    assert journal.status(current.operation_id) == resumed


def test_stale_attempt_cannot_append_or_cancel(tmp_path: Path) -> None:
    owner, journal = _owner(
        tmp_path,
        facts=_facts("explicit_plugin_intent"),
    )
    current = owner.submit(_request())
    interrupted = owner.interrupt(
        current.operation_id,
        expected_phase=current.phase,
        expected_journal_revision=current.journal_revision,
        expected_attempt_epoch=current.attempt_epoch,
    )
    resumed = owner.retry(
        PackageLifecycleRetryRequestV1(
            operation_id=current.operation_id,
            request_fingerprint=current.request_fingerprint,
            expected_attempt_epoch=interrupted.attempt_epoch,
        )
    )
    before_stale = journal.records()

    stale = owner.interrupt(
        current.operation_id,
        expected_phase=current.phase,
        expected_journal_revision=current.journal_revision,
        expected_attempt_epoch=current.attempt_epoch,
    )
    assert stale.failure is not None
    assert stale.failure.code == "package_attempt_stale"
    stale_cancel = owner.cancel(
        PackageLifecycleCancelRequestV1(
            operation_id=current.operation_id,
            request_fingerprint=current.request_fingerprint,
            expected_phase=current.phase,
            expected_journal_revision=current.journal_revision,
            expected_attempt_epoch=current.attempt_epoch,
        )
    )
    assert stale_cancel.failure is not None
    assert stale_cancel.failure.code == "package_attempt_stale"
    assert journal.records() == before_stale
    assert journal.status(current.operation_id) == resumed


def test_cancel_is_terminal_idempotent_and_not_retryable(tmp_path: Path) -> None:
    owner, journal = _owner(
        tmp_path,
        facts=_facts("explicit_plugin_intent"),
    )
    current = owner.submit(_request())
    request = PackageLifecycleCancelRequestV1(
        operation_id=current.operation_id,
        request_fingerprint=current.request_fingerprint,
        expected_phase=current.phase,
        expected_journal_revision=current.journal_revision,
        expected_attempt_epoch=current.attempt_epoch,
    )

    cancelled = owner.cancel(request)
    replay = owner.cancel(request)

    assert replay == cancelled
    assert cancelled.phase == "classified"
    assert cancelled.disposition == "cancelled"
    assert cancelled.failure is not None
    assert cancelled.failure.code == "package_operation_cancelled"
    before_retry = journal.records()
    with pytest.raises(PackageLifecycleJournalError) as terminal:
        owner.retry(
            PackageLifecycleRetryRequestV1(
                operation_id=current.operation_id,
                request_fingerprint=current.request_fingerprint,
                expected_attempt_epoch=current.attempt_epoch,
            )
        )
    assert terminal.value.code == "package_operation_not_retryable"
    assert journal.records() == before_retry


def test_status_and_records_replay_after_process_restart(tmp_path: Path) -> None:
    owner, journal = _owner(
        tmp_path,
        facts=_facts("explicit_plugin_intent"),
    )
    expected = owner.submit(_request())

    reopened = PackageLifecycleJournal(journal.path)

    assert reopened.status(expected.operation_id) == expected
    assert reopened.records() == journal.records()
    assert all(record.record_version == 1 for record in reopened.records())


def test_journal_codec_rejects_unknown_fields(tmp_path: Path) -> None:
    owner, journal = _owner(
        tmp_path,
        facts=_facts("explicit_plugin_intent"),
    )
    owner.submit(_request())
    lines = journal.path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0][:-1] + ',"unknown":true}'
    journal.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(PackageLifecycleJournalError) as corrupt:
        journal.records()
    assert corrupt.value.code == "package_lifecycle_journal_corrupt"


def test_journal_codec_rejects_duplicate_fields_even_when_values_match(
    tmp_path: Path,
) -> None:
    owner, journal = _owner(
        tmp_path,
        facts=_facts("explicit_plugin_intent"),
    )
    owner.submit(_request())
    lines = journal.path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace("{", '{"recordVersion":1,', 1)
    journal.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(PackageLifecycleJournalError) as corrupt:
        journal.records()
    assert corrupt.value.code == "package_lifecycle_journal_corrupt"


def test_source_credentials_query_fragment_and_tokens_never_reach_evidence(
    tmp_path: Path,
) -> None:
    owner, journal = _owner(
        tmp_path,
        facts=_facts("explicit_plugin_intent"),
    )
    secret = "super-secret-token"
    status = owner.submit(
        _request(
            source_locator=(
                f"https://user:{secret}@PACKAGES.EXAMPLE.TEST:443/acme.whl"
                f"?token={secret}#credential-{secret}"
            )
        )
    )

    assert status.classification is not None
    assert status.classification.canonical_source_identity == (
        "https://packages.example.test:443/acme.whl"
    )
    encoded_status = str(status.to_dict())
    encoded_journal = journal.path.read_text(encoding="utf-8")
    assert secret not in repr(status)
    assert secret not in encoded_status
    assert secret not in encoded_journal
    assert "user:" not in encoded_status
    assert "?token=" not in encoded_journal
    assert "#credential" not in encoded_journal


def test_status_wire_round_trip_is_strict_and_versioned(tmp_path: Path) -> None:
    owner, _journal = _owner(
        tmp_path,
        facts=_facts("explicit_plugin_intent"),
    )
    status = owner.submit(_request())

    assert PackageLifecycleStatusV1.from_dict(status.to_dict()) == status
    changed = status.to_dict()
    changed["statusVersion"] = 2
    with pytest.raises(ValueError, match="Unsupported Package lifecycle status"):
        PackageLifecycleStatusV1.from_dict(changed)

    rejected_owner, _rejected_journal = _owner(tmp_path / "rejected", facts=_facts())
    rejected = rejected_owner.submit(_request(operation_id="operation-rejected"))
    assert PackageLifecycleStatusV1.from_dict(rejected.to_dict()) == rejected


def test_conditional_retry_requires_named_evidence() -> None:
    terminal = PackageLifecycleFailureV1.for_operation(
        "package_acquisition_limit_exceeded",
        stage="acquiring",
        operation_id="operation-conditional",
        evidence_ref="e" * 64,
    )
    retryable = PackageLifecycleFailureV1.for_operation(
        "package_acquisition_limit_exceeded",
        stage="acquiring",
        operation_id="operation-conditional",
        evidence_ref="e" * 64,
        details=("condition:no_acquired_digest",),
    )

    assert (terminal.retryable, terminal.retry_domain, terminal.operator_action) == (
        False,
        "none",
        "none",
    )
    assert (
        retryable.retryable,
        retryable.retry_domain,
        retryable.operator_action,
    ) == (True, "operation", "retry")


def test_strict_status_rejects_retryable_failure_disguised_as_rejection(
    tmp_path: Path,
) -> None:
    owner, _journal = _owner(
        tmp_path,
        facts=_facts("explicit_plugin_intent"),
    )
    current = owner.submit(_request())
    interrupted = owner.interrupt(
        current.operation_id,
        expected_phase=current.phase,
        expected_journal_revision=current.journal_revision,
        expected_attempt_epoch=current.attempt_epoch,
    )
    document = interrupted.to_dict()
    document["disposition"] = "rejected"

    with pytest.raises(ValueError, match="Retryable failure requires"):
        PackageLifecycleStatusV1.from_dict(document)


def test_canonical_json_rejects_floats() -> None:
    with pytest.raises(TypeError, match="does not permit floats"):
        canonical_json_bytes({"budget": 1.0})
