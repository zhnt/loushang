"""Append-only phase-CAS journal for the dark PLC9B owner kernel."""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from dataclasses import replace
from pathlib import Path

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
    JournalLoadPolicy,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    journal_file_read_lock,
    load_jsonl,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleFailureV1,
    PackageLifecycleJournalRecordV1,
    PackageLifecyclePhase,
    PackageLifecyclePinnedAdoptionRecordV1,
    PackageLifecyclePinnedAdoptionRequestV1,
    PackageLifecycleRebindRecordV1,
    PackageLifecycleRebindRequestV1,
    PackageLifecycleRequestV1,
    PackageLifecycleRequestV2,
    PackageLifecycleRestartRecordV1,
    PackageLifecycleRestartRequestV1,
    PackageLifecycleStagingAdoptionRecordV1,
    PackageLifecycleStagingAdoptionRequestV1,
    PackageLifecycleStatusV1,
    PluginBoundPackageClassificationV1,
)

PackageLifecycleRecord = (
    PackageLifecycleJournalRecordV1
    | PackageLifecycleRebindRecordV1
    | PackageLifecyclePinnedAdoptionRecordV1
    | PackageLifecycleStagingAdoptionRecordV1
    | PackageLifecycleRestartRecordV1
)


class PackageLifecycleJournalError(RuntimeError):
    """Fail-closed journal, CAS, replay, or operation identity error."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


def _encode_record(record: PackageLifecycleRecord) -> dict[str, object]:
    if not isinstance(
        record,
        (
            PackageLifecycleJournalRecordV1,
            PackageLifecycleRebindRecordV1,
            PackageLifecyclePinnedAdoptionRecordV1,
            PackageLifecycleStagingAdoptionRecordV1,
            PackageLifecycleRestartRecordV1,
        ),
    ):
        raise TypeError("Package lifecycle journal record is required")
    return record.to_dict()


def _decode_record(value: object) -> PackageLifecycleRecord:
    try:
        if isinstance(value, dict) and value.get("recordKind") == "staging_adoption":
            return PackageLifecycleStagingAdoptionRecordV1.from_dict(value)
        if isinstance(value, dict) and value.get("recordKind") in {
            "pinned_adoption", "pinned_adoption_supersession",
        }:
            return PackageLifecyclePinnedAdoptionRecordV1.from_dict(value)
        if isinstance(value, dict) and value.get("recordKind") in {
            "rebind",
            "rebind_supersession",
        }:
            return PackageLifecycleRebindRecordV1.from_dict(value)
        if isinstance(value, dict) and value.get("recordKind") == "restart":
            return PackageLifecycleRestartRecordV1.from_dict(value)
        return PackageLifecycleJournalRecordV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Package lifecycle journal record is invalid",
            code="invalid_package_lifecycle_record",
        ) from exc


PACKAGE_LIFECYCLE_JOURNAL_CODEC = FunctionalJournalRecordCodec(
    encoder=_encode_record,
    decoder=_decode_record,
)

_PHASE_SEQUENCE: tuple[PackageLifecyclePhase, ...] = (
    "accepted",
    "classified",
    "acquiring",
    "acquired",
    "inspecting",
    "extracted",
    "resolving_closure",
    "closure_verified",
    "transaction_pinned",
    "staging",
    "set_published",
    "committed",
)
_READ_ONLY_LOAD_POLICY = JournalLoadPolicy(partial_tail="raise", create_lock=False)


class PackageLifecycleJournal:
    """Single-owner durable operation and attempt CAS domains."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def accept(self, request: PackageLifecycleRequestV1) -> PackageLifecycleStatusV1:
        if not isinstance(request, PackageLifecycleRequestV1):
            raise TypeError("Package lifecycle request is required")
        with self._exclusive():
            records = self._load_unlocked()
            statuses = _project_records(records)
            existing = statuses.get(request.operation_id)
            if existing is not None:
                if existing.request_fingerprint != request.request_fingerprint:
                    raise self._error(
                        "Package operation identity was reused for changed input",
                        code="package_operation_identity_conflict",
                    )
                return existing
            revision = len(records) + 1
            status = PackageLifecycleStatusV1(
                operation_id=request.operation_id,
                request_fingerprint=request.request_fingerprint,
                phase="accepted",
                disposition="active",
                attempt_epoch=1,
                journal_revision=revision,
                attempt_revision=0,
            )
            self._append_unlocked(
                PackageLifecycleJournalRecordV1(
                    record_kind="operation",
                    record_revision=revision,
                    prior_operation_revision=0,
                    prior_attempt_revision=0,
                    request=request,
                    status=status,
                )
            )
            return status

    def classify(
        self,
        operation_id: str,
        classification: PluginBoundPackageClassificationV1,
        *,
        expected_journal_revision: int,
        expected_attempt_epoch: int,
    ) -> PackageLifecycleStatusV1:
        if not isinstance(classification, PluginBoundPackageClassificationV1):
            raise TypeError("Package classification evidence is required")
        with self._exclusive():
            records = self._load_unlocked()
            requests, statuses = _project_state(records)
            current = self._current(statuses, operation_id)
            if current.phase == "classified":
                if current.classification != classification:
                    raise self._error(
                        "Package classification changed after the classified edge",
                        code="package_target_classification_changed",
                    )
                return current
            self._require_active_cas(
                current,
                expected_phase="accepted",
                expected_journal_revision=expected_journal_revision,
                expected_attempt_epoch=expected_attempt_epoch,
            )
            if classification.request_fingerprint != current.request_fingerprint:
                raise self._error(
                    "Package classification does not match the accepted request",
                    code="package_operation_identity_conflict",
                )
            revision = len(records) + 1
            failure = None
            disposition = "active"
            if classification.decision == "indeterminate":
                disposition = "rejected"
                failure = PackageLifecycleFailureV1.for_operation(
                    "package_target_classification_indeterminate",
                    stage="classified",
                    operation_id=operation_id,
                    evidence_ref=classification.evidence_ref,
                )
            status = PackageLifecycleStatusV1(
                operation_id=operation_id,
                request_fingerprint=current.request_fingerprint,
                phase="classified",
                disposition=disposition,  # type: ignore[arg-type]
                attempt_epoch=current.attempt_epoch,
                journal_revision=revision,
                attempt_revision=current.attempt_revision,
                classification=classification,
                failure=failure,
            )
            self._append_unlocked(
                PackageLifecycleJournalRecordV1(
                    record_kind="operation",
                    record_revision=revision,
                    prior_operation_revision=current.journal_revision,
                    prior_attempt_revision=current.attempt_revision,
                    request=requests[operation_id],
                    status=status,
                )
            )
            return status

    def advance(
        self,
        operation_id: str,
        *,
        next_phase: PackageLifecyclePhase,
        expected_phase: PackageLifecyclePhase,
        expected_journal_revision: int,
        expected_attempt_epoch: int,
    ) -> PackageLifecycleStatusV1:
        """Commit one adjacent proved phase under operation CAS."""

        if _next_phase(expected_phase) != next_phase:
            raise self._error(
                "Package operation phase transition is not adjacent",
                code="package_operation_phase_transition_invalid",
            )
        with self._exclusive():
            records = self._load_unlocked()
            requests, statuses = _project_state(records)
            current = self._current(statuses, operation_id)
            expected_disposition = (
                "committed" if next_phase == "committed" else "active"
            )
            if (
                current.phase == next_phase
                and current.disposition == expected_disposition
            ):
                if current.attempt_epoch != expected_attempt_epoch:
                    raise self._stale_attempt()
                last = _last_operation_record(records, operation_id)
                if (
                    last.prior_operation_revision == expected_journal_revision
                    and last.status == current
                ):
                    return current
                raise self._error(
                    "Package operation phase compare-and-swap failed",
                    code="package_operation_phase_conflict",
                )
            self._require_active_cas(
                current,
                expected_phase=expected_phase,
                expected_journal_revision=expected_journal_revision,
                expected_attempt_epoch=expected_attempt_epoch,
            )
            revision = len(records) + 1
            status = replace(
                current,
                phase=next_phase,
                disposition=("committed" if next_phase == "committed" else "active"),
                journal_revision=revision,
            )
            self._append_unlocked(
                PackageLifecycleJournalRecordV1(
                    record_kind="operation",
                    record_revision=revision,
                    prior_operation_revision=current.journal_revision,
                    prior_attempt_revision=current.attempt_revision,
                    request=requests[operation_id],
                    status=status,
                )
            )
            return status

    def record_failure(
        self,
        failure: PackageLifecycleFailureV1,
        *,
        expected_phase: PackageLifecyclePhase,
        expected_journal_revision: int,
        expected_attempt_epoch: int,
    ) -> PackageLifecycleStatusV1:
        """Record one typed failure in its policy-owned CAS domain."""

        if not isinstance(failure, PackageLifecycleFailureV1):
            raise TypeError("Package lifecycle failure is required")
        if failure.subject_kind != "operation":
            raise TypeError("Operation journal accepts only operation failures")
        with self._exclusive():
            records = self._load_unlocked()
            requests, statuses = _project_state(records)
            current = self._current(statuses, failure.operation_id)
            if current.failure == failure:
                if current.attempt_epoch != expected_attempt_epoch:
                    raise self._stale_attempt()
                if (
                    current.request_fingerprint
                    != requests[failure.operation_id].request_fingerprint
                ):
                    raise self._error(
                        "Package operation request fingerprint changed",
                        code="package_operation_identity_conflict",
                    )
                return current
            self._require_active_cas(
                current,
                expected_phase=expected_phase,
                expected_journal_revision=expected_journal_revision,
                expected_attempt_epoch=expected_attempt_epoch,
            )
            if failure.operation_id != current.operation_id:
                raise self._error(
                    "Package failure operation identity changed",
                    code="package_operation_identity_conflict",
                )
            if failure.retryable:
                if (
                    failure.retry_domain != "operation"
                    or failure.stage != current.phase
                ):
                    raise self._error(
                        "Package retryable failure selected the wrong CAS domain",
                        code="package_operation_failure_domain_invalid",
                    )
                record_kind = "attempt"
                phase = current.phase
            else:
                if failure.stage not in {
                    current.phase,
                    _next_phase(current.phase),
                }:
                    raise self._error(
                        "Package failure stage is not current or adjacent",
                        code="package_operation_phase_transition_invalid",
                    )
                record_kind = "operation"
                phase = failure.stage
            revision = len(records) + 1
            if record_kind == "attempt":
                status = replace(
                    current,
                    phase=phase,
                    disposition="retryable_failure",
                    attempt_revision=revision,
                    failure=failure,
                )
            else:
                status = replace(
                    current,
                    phase=phase,
                    disposition="rejected",
                    journal_revision=revision,
                    failure=failure,
                )
            self._append_unlocked(
                PackageLifecycleJournalRecordV1(
                    record_kind=record_kind,  # type: ignore[arg-type]
                    record_revision=revision,
                    prior_operation_revision=current.journal_revision,
                    prior_attempt_revision=current.attempt_revision,
                    request=requests[failure.operation_id],
                    status=status,
                )
            )
            return status

    def interrupt(
        self,
        operation_id: str,
        *,
        expected_phase: PackageLifecyclePhase,
        expected_journal_revision: int,
        expected_attempt_epoch: int,
        expected_attempt_revision: int | None = None,
    ) -> PackageLifecycleStatusV1:
        if expected_attempt_revision is not None and (
            type(expected_attempt_revision) is not int or expected_attempt_revision < 0
        ):
            raise ValueError("Package expected attempt revision is invalid")
        with self._exclusive():
            records = self._load_unlocked()
            requests, statuses = _project_state(records)
            current = self._current(statuses, operation_id)
            if (
                current.disposition == "retryable_failure"
                and current.phase == expected_phase
                and current.journal_revision == expected_journal_revision
                and current.attempt_epoch == expected_attempt_epoch
                and current.failure is not None
                and current.failure.code == "package_operation_interrupted"
            ):
                return current
            self._require_active_cas(
                current,
                expected_phase=expected_phase,
                expected_journal_revision=expected_journal_revision,
                expected_attempt_epoch=expected_attempt_epoch,
            )
            if (
                expected_attempt_revision is not None
                and current.attempt_revision != expected_attempt_revision
            ):
                raise self._stale_attempt()
            revision = len(records) + 1
            failure = PackageLifecycleFailureV1.for_operation(
                "package_operation_interrupted",
                stage=current.phase,
                operation_id=operation_id,
                evidence_ref=current.request_fingerprint,
            )
            status = replace(
                current,
                disposition="retryable_failure",
                attempt_revision=revision,
                failure=failure,
            )
            self._append_unlocked(
                PackageLifecycleJournalRecordV1(
                    record_kind="attempt",
                    record_revision=revision,
                    prior_operation_revision=current.journal_revision,
                    prior_attempt_revision=current.attempt_revision,
                    request=requests[operation_id],
                    status=status,
                )
            )
            return status

    def retry(
        self,
        operation_id: str,
        *,
        request_fingerprint: str,
        expected_attempt_epoch: int,
    ) -> PackageLifecycleStatusV1:
        with self._exclusive():
            records = self._load_unlocked()
            requests, statuses = _project_state(records)
            current = self._current(statuses, operation_id)
            self._require_fingerprint(current, request_fingerprint)
            if (
                current.disposition == "active"
                and current.attempt_epoch == expected_attempt_epoch + 1
            ):
                return current
            if current.terminal or current.disposition != "retryable_failure":
                raise self._error(
                    "Package operation is not retryable",
                    code="package_operation_not_retryable",
                )
            if current.attempt_epoch != expected_attempt_epoch:
                raise self._stale_attempt()
            if any(
                isinstance(record, PackageLifecycleRebindRecordV1)
                and record.status.operation_id == operation_id
                and record.status == current
                for record in reversed(records)
            ):
                raise self._error(
                    "Package rebind has no authorized execution route",
                    code="package_rebind_execution_not_available",
                )
            revision = len(records) + 1
            status = replace(
                current,
                disposition="active",
                attempt_epoch=current.attempt_epoch + 1,
                attempt_revision=revision,
                failure=None,
            )
            self._append_unlocked(
                PackageLifecycleJournalRecordV1(
                    record_kind="attempt",
                    record_revision=revision,
                    prior_operation_revision=current.journal_revision,
                    prior_attempt_revision=current.attempt_revision,
                    request=requests[operation_id],
                    status=status,
                )
            )
            return status

    def record_pinned_adoption(
        self, decision: PackageLifecyclePinnedAdoptionRequestV1
    ) -> PackageLifecyclePinnedAdoptionRecordV1:
        """Select an inert same-attempt admission proposal under exact pin CAS."""

        return self._record_pinned_adoption(decision, supersedes=None)

    def supersede_pinned_adoption(
        self,
        decision: PackageLifecyclePinnedAdoptionRequestV1,
        *,
        supersedes_decision_id: str,
        expected_prior_record_revision: int,
    ) -> PackageLifecyclePinnedAdoptionRecordV1:
        """Replace one still-selected proposal after Product proves lease exit."""

        if (
            not isinstance(supersedes_decision_id, str)
            or len(supersedes_decision_id) != 64
            or type(expected_prior_record_revision) is not int
            or expected_prior_record_revision < 1
        ):
            raise ValueError("Prior pinned adoption identity is invalid")
        return self._record_pinned_adoption(
            decision,
            supersedes=(supersedes_decision_id, expected_prior_record_revision),
        )

    def _record_pinned_adoption(
        self,
        decision: PackageLifecyclePinnedAdoptionRequestV1,
        *,
        supersedes: tuple[str, int] | None,
    ) -> PackageLifecyclePinnedAdoptionRecordV1:
        if not isinstance(decision, PackageLifecyclePinnedAdoptionRequestV1):
            raise TypeError("Pinned adoption decision is required")
        with self._exclusive():
            records = self._load_unlocked()
            requests, statuses = _project_state(records)
            current = self._current(statuses, decision.operation_id)
            prior = next(
                (
                    record for record in reversed(records)
                    if isinstance(record, PackageLifecyclePinnedAdoptionRecordV1)
                    and record.status.operation_id == decision.operation_id
                ),
                None,
            )
            if prior is not None and prior.status == current:
                if supersedes is None and prior.decision == decision:
                    return prior
                if (
                    supersedes is not None
                    and prior.record_kind == "pinned_adoption_supersession"
                    and prior.supersedes_decision_id == supersedes[0]
                    and prior.prior_attempt_revision == supersedes[1]
                    and prior.decision == decision
                ):
                    return prior
            if (
                current.phase != "transaction_pinned"
                or current.disposition != "active"
                or current.journal_revision != decision.expected_journal_revision
                or current.attempt_epoch != decision.expected_attempt_epoch
                or current.attempt_revision != decision.expected_attempt_revision
                or current.request_fingerprint != decision.request_fingerprint
                or (supersedes is None and prior is not None and prior.status == current)
                or (
                    supersedes is not None
                    and (
                        prior is None
                        or prior.status != current
                        or prior.record_revision != supersedes[1]
                        or prior.decision.decision_id != supersedes[0]
                        or prior.decision.new_runtime_admission_request_id
                        == decision.new_runtime_admission_request_id
                    )
                )
            ):
                raise self._error(
                    "Pinned admission adoption changed selected attempt",
                    code="package_pinned_adoption_attempt_conflict",
                )
            original = requests[decision.operation_id]
            if (
                not isinstance(original, PackageLifecycleRequestV2)
                or original.runtime_admission_request_id
                == decision.new_runtime_admission_request_id
            ):
                raise self._error(
                    "Pinned adoption requires a distinct original admission",
                    code="package_pinned_adoption_not_permitted",
                )
            revision = len(records) + 1
            record = PackageLifecyclePinnedAdoptionRecordV1(
                record_revision=revision,
                prior_operation_revision=current.journal_revision,
                prior_attempt_revision=current.attempt_revision,
                request=original,
                status=replace(current, attempt_revision=revision),
                decision=decision,
                record_kind=(
                    "pinned_adoption" if supersedes is None
                    else "pinned_adoption_supersession"
                ),
                supersedes_decision_id=(None if supersedes is None else supersedes[0]),
            )
            self._append_unlocked(record)
            return record

    def latest_pinned_adoption(
        self, operation_id: str
    ) -> PackageLifecyclePinnedAdoptionRecordV1 | None:
        """Read the selected proposal without creating locks or repairing tails."""

        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Package operation id is required")
        with journal_file_read_lock(
            self._path, "shared",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            create_lock=False,
        ):
            records = self._load_unlocked(load_policy=_READ_ONLY_LOAD_POLICY)
        return next(
            (
                record for record in reversed(records)
                if isinstance(record, PackageLifecyclePinnedAdoptionRecordV1)
                and record.status.operation_id == operation_id
            ),
            None,
        )

    def read_pinned_adoption_history(
        self, operation_id: str
    ) -> tuple[PackageLifecyclePinnedAdoptionRecordV1, ...]:
        """Read every selected proposal for strict Product lease lineage."""

        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Package operation id is required")
        with journal_file_read_lock(
            self._path, "shared",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            create_lock=False,
        ):
            records = self._load_unlocked(load_policy=_READ_ONLY_LOAD_POLICY)
        return tuple(
            record for record in records
            if isinstance(record, PackageLifecyclePinnedAdoptionRecordV1)
            and record.status.operation_id == operation_id
        )

    def record_staging_adoption(
        self, decision: PackageLifecycleStagingAdoptionRequestV1
    ) -> PackageLifecycleStagingAdoptionRecordV1:
        """Select an inert admission for one unchanged staging checkpoint."""

        if not isinstance(decision, PackageLifecycleStagingAdoptionRequestV1):
            raise TypeError("Staging adoption decision is required")
        with self._exclusive():
            records = self._load_unlocked()
            requests, statuses = _project_state(records)
            current = self._current(statuses, decision.operation_id)
            selected = next(
                (
                    record
                    for record in reversed(records)
                    if isinstance(
                        record,
                        PackageLifecycleStagingAdoptionRecordV1
                        | PackageLifecyclePinnedAdoptionRecordV1,
                    )
                    and record.status.operation_id == decision.operation_id
                ),
                None,
            )
            if (
                current.phase == "set_published"
                and selected is not None
                and selected.status.phase != "set_published"
            ):
                # A prior pin/staging selection already produced the published
                # set. Its active proposal ended when the phase advanced.
                selected = None
            if (
                isinstance(selected, PackageLifecycleStagingAdoptionRecordV1)
                and selected.status == current
                and selected.decision == decision
            ):
                return selected
            prior_decision = None if selected is None else selected.decision
            if (
                current.phase not in {"transaction_pinned", "set_published"}
                or current.disposition != "active"
                or current.journal_revision != decision.expected_journal_revision
                or current.attempt_epoch != decision.expected_attempt_epoch
                or current.attempt_revision != decision.expected_attempt_revision
                or current.request_fingerprint != decision.request_fingerprint
                or (selected is not None and selected.status != current)
                or decision.previous_selected_decision_id
                != (
                    None if prior_decision is None else prior_decision.decision_id
                )
                or (
                    prior_decision is not None
                    and prior_decision.new_runtime_admission_request_id
                    == decision.new_runtime_admission_request_id
                )
            ):
                raise self._error(
                    "Staging adoption changed selected checkpoint attempt",
                    code="package_staging_adoption_attempt_conflict",
                )
            original = requests[decision.operation_id]
            if (
                not isinstance(original, PackageLifecycleRequestV2)
                or original.runtime_admission_request_id
                == decision.new_runtime_admission_request_id
            ):
                raise self._error(
                    "Staging adoption requires a distinct original admission",
                    code="package_staging_adoption_not_permitted",
                )
            revision = len(records) + 1
            record = PackageLifecycleStagingAdoptionRecordV1(
                record_revision=revision,
                prior_operation_revision=current.journal_revision,
                prior_attempt_revision=current.attempt_revision,
                request=original,
                status=replace(current, attempt_revision=revision),
                decision=decision,
            )
            self._append_unlocked(record)
            return record

    def latest_staging_adoption(
        self, operation_id: str
    ) -> PackageLifecycleStagingAdoptionRecordV1 | None:
        """Read the newest staged selection without repair or lock creation."""

        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Package operation id is required")
        with journal_file_read_lock(
            self._path, "shared",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            create_lock=False,
        ):
            records = self._load_unlocked(load_policy=_READ_ONLY_LOAD_POLICY)
        return next(
            (
                record for record in reversed(records)
                if isinstance(record, PackageLifecycleStagingAdoptionRecordV1)
                and record.status.operation_id == operation_id
            ),
            None,
        )

    def read_staging_adoption_history(
        self, operation_id: str
    ) -> tuple[PackageLifecycleStagingAdoptionRecordV1, ...]:
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Package operation id is required")
        with journal_file_read_lock(
            self._path, "shared",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            create_lock=False,
        ):
            records = self._load_unlocked(load_policy=_READ_ONLY_LOAD_POLICY)
        return tuple(
            record for record in records
            if isinstance(record, PackageLifecycleStagingAdoptionRecordV1)
            and record.status.operation_id == operation_id
        )

    def record_rebind(
        self, decision: PackageLifecycleRebindRequestV1
    ) -> PackageLifecycleRebindRecordV1:
        """Persist a reviewed rebind CAS; this does not resume or execute A2."""

        if not isinstance(decision, PackageLifecycleRebindRequestV1):
            raise TypeError("Package rebind decision is required")
        with self._exclusive():
            records = self._load_unlocked()
            requests, statuses = _project_state(records)
            current = self._current(statuses, decision.operation_id)
            previous = next(
                (
                    record
                    for record in reversed(records)
                    if isinstance(record, PackageLifecycleRebindRecordV1)
                    and record.status.operation_id == decision.operation_id
                ),
                None,
            )
            if previous is not None and previous.status == current:
                if previous.decision == decision:
                    return previous
                raise self._error(
                    "Package rebind decision is already fixed for this attempt",
                    code="package_rebind_attempt_conflict",
                )
            if current.attempt_revision != decision.expected_attempt_revision:
                raise self._error(
                    "Package rebind attempt changed",
                    code="package_rebind_attempt_conflict",
                )
            original = requests[decision.operation_id]
            if (
                not isinstance(original, PackageLifecycleRequestV2)
                or current.request_fingerprint != decision.request_fingerprint
                or current.attempt_epoch != decision.expected_attempt_epoch
                or current.disposition != "retryable_failure"
                or current.failure is None
                or current.failure.operator_action != "retry"
                or current.classification is None
                or current.classification.decision != "plugin_bound"
                or original.runtime_admission_request_id
                == decision.new_runtime_admission_request_id
            ):
                raise self._error(
                    "Package operation cannot record a runtime rebind",
                    code="package_rebind_not_permitted",
                )
            if not _restart_refs_match(records, current, decision):
                raise self._error(
                    "Package rebind changed cleanup-bound restart evidence",
                    code="package_rebind_restart_evidence_changed",
                )
            revision = len(records) + 1
            record = PackageLifecycleRebindRecordV1(
                record_revision=revision,
                prior_operation_revision=current.journal_revision,
                prior_attempt_revision=current.attempt_revision,
                request=original,
                status=replace(current, attempt_revision=revision),
                decision=decision,
            )
            self._append_unlocked(record)
            return record

    def latest_rebind(self, operation_id: str) -> PackageLifecycleRebindRecordV1 | None:
        """Read the latest exact rebind decision without creating owner state."""

        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Package operation id is required")
        with journal_file_read_lock(
            self._path,
            "shared",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            create_lock=False,
        ):
            records = self._load_unlocked(load_policy=_READ_ONLY_LOAD_POLICY)
        return next(
            (
                record
                for record in reversed(records)
                if isinstance(record, PackageLifecycleRebindRecordV1)
                and record.status.operation_id == operation_id
            ),
            None,
        )

    def restart_after_cleanup(
        self, restart: PackageLifecycleRestartRequestV1
    ) -> PackageLifecycleRestartRecordV1:
        """Reset a failed phase under exact CAS after Product proves cleanup.

        This journal primitive does not verify the supplied Source, cleanup, or
        lease proof references and grants no Product execution authority.
        """

        if not isinstance(restart, PackageLifecycleRestartRequestV1):
            raise TypeError("Package restart request is required")
        with self._exclusive():
            records = self._load_unlocked()
            requests, statuses = _project_state(records)
            current = self._current(statuses, restart.operation_id)
            previous = next(
                (
                    record
                    for record in reversed(records)
                    if isinstance(record, PackageLifecycleRestartRecordV1)
                    and record.status.operation_id == restart.operation_id
                ),
                None,
            )
            if previous is not None and previous.status == current:
                if previous.restart == restart:
                    return previous
                raise self._error(
                    "Package restart is already fixed for this attempt",
                    code="package_restart_attempt_conflict",
                )
            original = requests[restart.operation_id]
            if (
                not isinstance(original, PackageLifecycleRequestV2)
                or current.request_fingerprint != restart.request_fingerprint
                or current.phase != restart.expected_phase
                or current.journal_revision != restart.expected_journal_revision
                or current.attempt_epoch != restart.expected_attempt_epoch
                or current.attempt_revision != restart.expected_attempt_revision
                or current.disposition != "retryable_failure"
                or current.failure is None
                or current.failure.operator_action != "retry"
                or current.classification is None
                or current.classification.decision != "plugin_bound"
                or any(
                    isinstance(record, PackageLifecycleRebindRecordV1)
                    and record.status == current
                    for record in records
                )
            ):
                raise self._error(
                    "Package failed attempt cannot restart after cleanup",
                    code="package_restart_attempt_conflict",
                )
            revision = len(records) + 1
            status = replace(
                current,
                phase="classified",
                attempt_revision=revision,
                failure=PackageLifecycleFailureV1.for_operation(
                    "package_operation_interrupted",
                    stage="classified",
                    operation_id=restart.operation_id,
                    evidence_ref=restart.restart_id,
                ),
            )
            record = PackageLifecycleRestartRecordV1(
                record_revision=revision,
                prior_operation_revision=current.journal_revision,
                prior_attempt_revision=current.attempt_revision,
                request=original,
                status=status,
                restart=restart,
            )
            self._append_unlocked(record)
            return record

    def latest_restart(
        self, operation_id: str
    ) -> PackageLifecycleRestartRecordV1 | None:
        """Read the latest cleanup-bound restart without mutating owner state."""

        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Package operation id is required")
        with journal_file_read_lock(
            self._path,
            "shared",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            create_lock=False,
        ):
            records = self._load_unlocked(load_policy=_READ_ONLY_LOAD_POLICY)
        return next(
            (
                record
                for record in reversed(records)
                if isinstance(record, PackageLifecycleRestartRecordV1)
                and record.status.operation_id == operation_id
            ),
            None,
        )

    def read_rebind_history(
        self, operation_id: str
    ) -> tuple[PackageLifecycleRebindRecordV1, ...]:
        """Read the exact accepted decision chain without owner mutation."""

        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Package operation id is required")
        with journal_file_read_lock(
            self._path,
            "shared",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            create_lock=False,
        ):
            records = self._load_unlocked(load_policy=_READ_ONLY_LOAD_POLICY)
        return tuple(
            record
            for record in records
            if isinstance(record, PackageLifecycleRebindRecordV1)
            and record.status.operation_id == operation_id
        )

    def supersede_rebind(
        self,
        decision: PackageLifecycleRebindRequestV1,
        *,
        supersedes_decision_id: str,
        expected_prior_rebind_record_revision: int,
    ) -> PackageLifecycleRebindRecordV1:
        """Persist a reviewed replacement of one still-pending decision.

        Product must first prove the old proposed lease exited and bind the new
        admitted lease. The journal enforces only exact decision lineage/CAS.
        """

        if not isinstance(decision, PackageLifecycleRebindRequestV1):
            raise TypeError("Package rebind supersession decision is required")
        if (
            type(expected_prior_rebind_record_revision) is not int
            or expected_prior_rebind_record_revision < 1
        ):
            raise ValueError("Prior Package rebind revision is invalid")
        with self._exclusive():
            records = self._load_unlocked()
            requests, statuses = _project_state(records)
            current = self._current(statuses, decision.operation_id)
            prior = next(
                (
                    record
                    for record in reversed(records)
                    if isinstance(record, PackageLifecycleRebindRecordV1)
                    and record.status.operation_id == decision.operation_id
                ),
                None,
            )
            if (
                prior is not None
                and prior.record_kind == "rebind_supersession"
                and prior.supersedes_decision_id == supersedes_decision_id
                and prior.prior_attempt_revision
                == expected_prior_rebind_record_revision
                and prior.decision == decision
            ):
                return prior
            if (
                prior is None
                or prior.status != current
                or prior.record_revision != expected_prior_rebind_record_revision
                or prior.decision.decision_id != supersedes_decision_id
                or prior.decision.new_runtime_admission_request_id
                == decision.new_runtime_admission_request_id
            ):
                raise self._error(
                    "Package rebind supersession changed pending decision",
                    code="package_rebind_supersession_conflict",
                )
            original = requests[decision.operation_id]
            if not isinstance(original, PackageLifecycleRequestV2):
                raise self._error(
                    "Package rebind requires an original runtime request",
                    code="package_rebind_not_permitted",
                )
            if not _restart_refs_match(records, current, decision):
                raise self._error(
                    "Package rebind changed cleanup-bound restart evidence",
                    code="package_rebind_restart_evidence_changed",
                )
            revision = len(records) + 1
            record = PackageLifecycleRebindRecordV1(
                record_revision=revision,
                prior_operation_revision=current.journal_revision,
                prior_attempt_revision=current.attempt_revision,
                request=original,
                status=replace(current, attempt_revision=revision),
                decision=decision,
                record_kind="rebind_supersession",
                supersedes_decision_id=supersedes_decision_id,
            )
            try:
                _validate_rebind_record(current, record)
            except ValueError as exc:
                raise self._error(
                    "Package rebind supersession changed failed attempt",
                    code="package_rebind_supersession_conflict",
                ) from exc
            self._append_unlocked(record)
            return record

    def resume_rebind(
        self,
        decision: PackageLifecycleRebindRequestV1,
        *,
        expected_rebind_record_revision: int,
    ) -> PackageLifecycleStatusV1:
        """Claim the next attempt only from one exact durable rebind decision.

        Product must recheck admission and all referenced owner evidence before
        calling this journal primitive. This method grants no route authority.
        """

        if not isinstance(decision, PackageLifecycleRebindRequestV1):
            raise TypeError("Package rebind decision is required")
        if (
            type(expected_rebind_record_revision) is not int
            or expected_rebind_record_revision < 1
        ):
            raise ValueError("Package rebind record revision is invalid")
        with self._exclusive():
            records = self._load_unlocked()
            requests, statuses = _project_state(records)
            current = self._current(statuses, decision.operation_id)
            rebind = next(
                (
                    record
                    for record in reversed(records)
                    if isinstance(record, PackageLifecycleRebindRecordV1)
                    and record.status.operation_id == decision.operation_id
                ),
                None,
            )
            if (
                rebind is None
                or rebind.record_revision != expected_rebind_record_revision
                or rebind.decision != decision
                or requests[decision.operation_id] != rebind.request
            ):
                raise self._error(
                    "Package rebind decision changed before resume",
                    code="package_rebind_decision_conflict",
                )
            if (
                current.attempt_epoch == decision.expected_attempt_epoch + 1
                and current.request_fingerprint == decision.request_fingerprint
            ):
                return current
            if current != rebind.status:
                raise self._error(
                    "Package rebind attempt changed before resume",
                    code="package_rebind_attempt_conflict",
                )
            revision = len(records) + 1
            resumed = replace(
                current,
                disposition="active",
                attempt_epoch=current.attempt_epoch + 1,
                attempt_revision=revision,
                failure=None,
            )
            self._append_unlocked(
                PackageLifecycleJournalRecordV1(
                    record_kind="attempt",
                    record_revision=revision,
                    prior_operation_revision=current.journal_revision,
                    prior_attempt_revision=current.attempt_revision,
                    request=rebind.request,
                    status=resumed,
                )
            )
            return resumed

    def cancel(
        self,
        operation_id: str,
        *,
        request_fingerprint: str,
        expected_phase: PackageLifecyclePhase,
        expected_journal_revision: int,
        expected_attempt_epoch: int,
    ) -> PackageLifecycleStatusV1:
        with self._exclusive():
            records = self._load_unlocked()
            requests, statuses = _project_state(records)
            current = self._current(statuses, operation_id)
            self._require_fingerprint(current, request_fingerprint)
            if current.disposition == "cancelled":
                return current
            if current.terminal:
                raise self._error(
                    "Terminal Package operation cannot be cancelled",
                    code="package_operation_not_cancellable",
                )
            self._require_cas(
                current,
                expected_phase=expected_phase,
                expected_journal_revision=expected_journal_revision,
                expected_attempt_epoch=expected_attempt_epoch,
            )
            revision = len(records) + 1
            failure = PackageLifecycleFailureV1.for_operation(
                "package_operation_cancelled",
                stage=current.phase,
                operation_id=operation_id,
                evidence_ref=current.request_fingerprint,
            )
            status = replace(
                current,
                disposition="cancelled",
                journal_revision=revision,
                failure=failure,
            )
            self._append_unlocked(
                PackageLifecycleJournalRecordV1(
                    record_kind="operation",
                    record_revision=revision,
                    prior_operation_revision=current.journal_revision,
                    prior_attempt_revision=current.attempt_revision,
                    request=requests[operation_id],
                    status=status,
                )
            )
            return status

    def status(self, operation_id: str) -> PackageLifecycleStatusV1 | None:
        with self._exclusive():
            return _project_records(self._load_unlocked()).get(operation_id)

    def request(self, operation_id: str) -> PackageLifecycleRequestV1 | None:
        with self._exclusive():
            requests, _statuses = _project_state(self._load_unlocked())
            return requests.get(operation_id)

    def records(self) -> tuple[PackageLifecycleRecord, ...]:
        with self._exclusive():
            return self._load_unlocked()

    def read_operations(
        self,
    ) -> tuple[tuple[PackageLifecycleRequestV1, PackageLifecycleStatusV1], ...]:
        """Project all operations from strict, non-mutating owner reads."""

        with journal_file_read_lock(
            self._path,
            "shared",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            create_lock=False,
        ):
            requests, statuses = _project_state(
                self._load_unlocked(load_policy=_READ_ONLY_LOAD_POLICY)
            )
        return tuple(
            (request, statuses[operation_id])
            for operation_id, request in sorted(requests.items())
        )

    def read_operation(
        self, operation_id: str
    ) -> tuple[PackageLifecycleRequestV1, PackageLifecycleStatusV1] | None:
        """Read exact A2 request/status without creating or repairing journals."""

        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Package operation id is required")
        with journal_file_read_lock(
            self._path,
            "shared",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            create_lock=False,
        ):
            requests, statuses = _project_state(
                self._load_unlocked(load_policy=_READ_ONLY_LOAD_POLICY)
            )
        request = requests.get(operation_id)
        status = statuses.get(operation_id)
        if request is None or status is None:
            return None
        return request, status

    def _require_active_cas(
        self,
        current: PackageLifecycleStatusV1,
        *,
        expected_phase: PackageLifecyclePhase,
        expected_journal_revision: int,
        expected_attempt_epoch: int,
    ) -> None:
        if current.disposition != "active":
            raise self._error(
                "Package operation is not active",
                code="package_operation_not_active",
            )
        self._require_cas(
            current,
            expected_phase=expected_phase,
            expected_journal_revision=expected_journal_revision,
            expected_attempt_epoch=expected_attempt_epoch,
        )

    def _require_cas(
        self,
        current: PackageLifecycleStatusV1,
        *,
        expected_phase: PackageLifecyclePhase,
        expected_journal_revision: int,
        expected_attempt_epoch: int,
    ) -> None:
        if current.attempt_epoch != expected_attempt_epoch:
            raise self._stale_attempt()
        if (
            current.phase != expected_phase
            or current.journal_revision != expected_journal_revision
        ):
            raise self._error(
                "Package operation phase compare-and-swap failed",
                code="package_operation_phase_conflict",
            )

    def _require_fingerprint(
        self,
        current: PackageLifecycleStatusV1,
        request_fingerprint: str,
    ) -> None:
        if current.request_fingerprint != request_fingerprint:
            raise self._error(
                "Package operation request fingerprint changed",
                code="package_operation_identity_conflict",
            )

    def _current(
        self,
        statuses: dict[str, PackageLifecycleStatusV1],
        operation_id: str,
    ) -> PackageLifecycleStatusV1:
        try:
            return statuses[operation_id]
        except KeyError as exc:
            raise self._error(
                "Package operation does not exist",
                code="package_operation_not_found",
            ) from exc

    def _stale_attempt(self) -> PackageLifecycleJournalError:
        return self._error(
            "Stale Package attempt cannot mutate the winning operation",
            code="package_attempt_stale",
        )

    def _exclusive(self) -> AbstractContextManager[None]:
        return journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        )

    def _append_unlocked(self, record: PackageLifecycleRecord) -> None:
        append_jsonl_record(
            self._path,
            record,
            record_codec=PACKAGE_LIFECYCLE_JOURNAL_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._unlocked_durability,
        )

    def _load_unlocked(
        self, *, load_policy: JournalLoadPolicy | None = None
    ) -> tuple[PackageLifecycleRecord, ...]:
        if not self._path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[None, PackageLifecycleRecord] = load_jsonl(
                self._path,
                record_codec=PACKAGE_LIFECYCLE_JOURNAL_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=load_policy or self._load_policy,
            )
            records = snapshot.records
            _assert_no_duplicate_json_keys(self._path)
            if any(
                record.record_revision != index
                for index, record in enumerate(records, start=1)
            ):
                raise ValueError("Package journal revisions are not contiguous")
            _project_records(records)
            return records
        except (JournalCodecError, JournalFileError, TypeError, ValueError) as exc:
            raise self._error(
                "Package lifecycle journal is corrupt",
                code="package_lifecycle_journal_corrupt",
            ) from exc

    def _error(self, message: str, *, code: str) -> PackageLifecycleJournalError:
        return PackageLifecycleJournalError(message, code=code, path=self._path)


def _project_records(
    records: tuple[PackageLifecycleRecord, ...],
) -> dict[str, PackageLifecycleStatusV1]:
    _requests, statuses = _project_state(records)
    return statuses


def _assert_no_duplicate_json_keys(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        json.loads(line, object_pairs_hook=_unique_json_object)


def _unique_json_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("Package lifecycle journal contains duplicate JSON keys")
        document[key] = value
    return document


def _project_state(
    records: tuple[PackageLifecycleRecord, ...],
) -> tuple[
    dict[str, PackageLifecycleRequestV1],
    dict[str, PackageLifecycleStatusV1],
]:
    requests: dict[str, PackageLifecycleRequestV1] = {}
    statuses: dict[str, PackageLifecycleStatusV1] = {}
    pending_rebinds: dict[str, PackageLifecycleRebindRecordV1] = {}
    pending_pinned_adoptions: dict[str, PackageLifecyclePinnedAdoptionRecordV1] = {}
    pending_staging_adoptions: dict[str, PackageLifecycleStagingAdoptionRecordV1] = {}
    latest_restarts: dict[str, PackageLifecycleRestartRecordV1] = {}
    for record in records:
        operation_id = record.status.operation_id
        current = statuses.get(operation_id)
        if current is None:
            _validate_accept_record(record)
            requests[operation_id] = record.request
            statuses[operation_id] = record.status
            continue
        if requests[operation_id] != record.request:
            raise ValueError("Package journal request changed after acceptance")
        if record.prior_operation_revision != current.journal_revision:
            raise ValueError("Package journal operation CAS predecessor is invalid")
        if record.prior_attempt_revision != current.attempt_revision:
            raise ValueError("Package journal attempt CAS predecessor is invalid")
        if current.terminal:
            raise ValueError("Terminal Package journal operation has later records")
        if isinstance(record, PackageLifecycleStagingAdoptionRecordV1):
            prior_staging = pending_staging_adoptions.get(operation_id)
            prior_pinned = pending_pinned_adoptions.get(operation_id)
            prior_decision = (
                prior_staging.decision
                if prior_staging is not None
                else prior_pinned.decision
                if prior_pinned is not None
                else None
            )
            if record.decision.previous_selected_decision_id != (
                None if prior_decision is None else prior_decision.decision_id
            ) or (
                prior_decision is not None
                and prior_decision.new_runtime_admission_request_id
                == record.decision.new_runtime_admission_request_id
            ):
                raise ValueError("Staging adoption changed selected lineage")
            _validate_staging_adoption_record(current, record)
            pending_pinned_adoptions.pop(operation_id, None)
            pending_staging_adoptions[operation_id] = record
        elif isinstance(record, PackageLifecyclePinnedAdoptionRecordV1):
            if operation_id in pending_staging_adoptions:
                raise ValueError("Pinned adoption resumed after staging selection")
            prior = pending_pinned_adoptions.get(operation_id)
            if record.record_kind == "pinned_adoption":
                if prior is not None:
                    raise ValueError("Pinned adoption changed before Product execution")
            elif (
                prior is None
                or record.supersedes_decision_id != prior.decision.decision_id
                or record.decision.new_runtime_admission_request_id
                == prior.decision.new_runtime_admission_request_id
            ):
                raise ValueError("Pinned adoption supersession changed lineage")
            _validate_pinned_adoption_record(current, record)
            pending_pinned_adoptions[operation_id] = record
        elif isinstance(record, PackageLifecycleRebindRecordV1):
            if operation_id in pending_staging_adoptions:
                raise ValueError("Package rebind changed staged selection")
            restart = latest_restarts.get(operation_id)
            if restart is not None and (
                restart.status.attempt_epoch == current.attempt_epoch
                and not _decision_matches_restart(record.decision, restart)
            ):
                raise ValueError("Package rebind changed restart evidence")
            pending = pending_rebinds.get(operation_id)
            if record.record_kind == "rebind":
                if pending is not None:
                    raise ValueError("Package rebind decision changed before resume")
            elif (
                pending is None
                or record.supersedes_decision_id != pending.decision.decision_id
                or record.decision.new_runtime_admission_request_id
                == pending.decision.new_runtime_admission_request_id
            ):
                raise ValueError("Package rebind supersession changed lineage")
            _validate_rebind_record(current, record)
            pending_rebinds[operation_id] = record
        elif isinstance(record, PackageLifecycleRestartRecordV1):
            if operation_id in pending_rebinds:
                raise ValueError("Package restart changed a pending rebind")
            _validate_restart_record(current, record)
            latest_restarts[operation_id] = record
        elif record.record_kind == "operation":
            if operation_id in pending_pinned_adoptions:
                pending_pinned_adoptions.pop(operation_id)
            pending_staging_adoptions.pop(operation_id, None)
            _validate_operation_record(current, record.status)
        else:
            if operation_id in pending_staging_adoptions:
                raise ValueError("Package attempt changed staged selection")
            pending = pending_rebinds.pop(operation_id, None)
            if pending is not None and (
                record.status.attempt_epoch
                != pending.decision.expected_attempt_epoch + 1
                or record.status.disposition != "active"
            ):
                raise ValueError("Package rebind resumed an unexpected attempt")
            _validate_attempt_record(current, record.status)
        statuses[operation_id] = record.status
    return requests, statuses


def _validate_accept_record(record: PackageLifecycleRecord) -> None:
    status = record.status
    if (
        record.record_kind != "operation"
        or record.prior_operation_revision != 0
        or record.prior_attempt_revision != 0
        or status.phase != "accepted"
        or status.disposition != "active"
        or status.attempt_epoch != 1
        or status.attempt_revision != 0
    ):
        raise ValueError("First Package operation record must be accepted")


def _validate_operation_record(
    current: PackageLifecycleStatusV1,
    following: PackageLifecycleStatusV1,
) -> None:
    if following.attempt_epoch != current.attempt_epoch:
        raise ValueError("Operation record cannot change Package attempt epoch")
    if following.attempt_revision != current.attempt_revision:
        raise ValueError("Operation record cannot change attempt revision")
    if following.request_fingerprint != current.request_fingerprint:
        raise ValueError("Operation record changed request fingerprint")
    if following.disposition == "cancelled":
        if following.phase != current.phase:
            raise ValueError("Cancellation must preserve the last proved phase")
        return
    if current.disposition != "active":
        raise ValueError("Unsupported PLC9B1 operation phase transition")
    next_phase = _next_phase(current.phase)
    if following.disposition == "active" and following.phase == next_phase:
        return
    if (
        following.disposition == "committed"
        and following.phase == "committed"
        and next_phase == "committed"
    ):
        return
    if following.disposition == "rejected" and following.phase in {
        current.phase,
        next_phase,
    }:
        return
    raise ValueError("Unsupported Package operation phase transition")


def _validate_attempt_record(
    current: PackageLifecycleStatusV1,
    following: PackageLifecycleStatusV1,
) -> None:
    if following.phase != current.phase:
        raise ValueError("Attempt record cannot change the proved operation phase")
    if following.journal_revision != current.journal_revision:
        raise ValueError("Attempt record cannot change operation revision")
    if following.request_fingerprint != current.request_fingerprint:
        raise ValueError("Attempt record changed request fingerprint")
    if following.disposition == "retryable_failure":
        if current.disposition != "active":
            raise ValueError("Only an active attempt may record interruption")
        if following.attempt_epoch != current.attempt_epoch:
            raise ValueError("Interrupted attempt cannot change attempt epoch")
        return
    if following.disposition == "active":
        if current.disposition != "retryable_failure":
            raise ValueError("Only a retryable failure may start the next attempt")
        if following.attempt_epoch != current.attempt_epoch + 1:
            raise ValueError("Retry must claim the next contiguous attempt epoch")
        return
    raise ValueError("Unsupported PLC9B1 attempt transition")


def _validate_rebind_record(
    current: PackageLifecycleStatusV1,
    record: PackageLifecycleRebindRecordV1,
) -> None:
    if (
        current.disposition != "retryable_failure"
        or current.failure is None
        or current.failure.operator_action != "retry"
        or current.classification is None
        or current.classification.decision != "plugin_bound"
        or record.decision.expected_attempt_epoch != current.attempt_epoch
        or record.decision.expected_attempt_revision != current.attempt_revision
        or record.status != replace(current, attempt_revision=record.record_revision)
    ):
        raise ValueError("Package rebind changed the failed attempt")


def _validate_pinned_adoption_record(
    current: PackageLifecycleStatusV1,
    record: PackageLifecyclePinnedAdoptionRecordV1,
) -> None:
    decision = record.decision
    if (
        current.phase != "transaction_pinned"
        or current.disposition != "active"
        or decision.expected_journal_revision != current.journal_revision
        or decision.expected_attempt_epoch != current.attempt_epoch
        or decision.expected_attempt_revision != current.attempt_revision
        or record.status != replace(current, attempt_revision=record.record_revision)
    ):
        raise ValueError("Pinned adoption changed the verified attempt")


def _validate_staging_adoption_record(
    current: PackageLifecycleStatusV1,
    record: PackageLifecycleStagingAdoptionRecordV1,
) -> None:
    decision = record.decision
    if (
        current.phase not in {"transaction_pinned", "set_published"}
        or current.disposition != "active"
        or decision.expected_journal_revision != current.journal_revision
        or decision.expected_attempt_epoch != current.attempt_epoch
        or decision.expected_attempt_revision != current.attempt_revision
        or record.status != replace(current, attempt_revision=record.record_revision)
    ):
        raise ValueError("Staging adoption changed the checkpoint attempt")


def _validate_restart_record(
    current: PackageLifecycleStatusV1,
    record: PackageLifecycleRestartRecordV1,
) -> None:
    restart = record.restart
    if (
        current.disposition != "retryable_failure"
        or current.failure is None
        or current.failure.operator_action != "retry"
        or current.classification is None
        or current.classification.decision != "plugin_bound"
        or current.phase != restart.expected_phase
        or current.journal_revision != restart.expected_journal_revision
        or current.attempt_epoch != restart.expected_attempt_epoch
        or current.attempt_revision != restart.expected_attempt_revision
        or record.status
        != replace(
            current,
            phase="classified",
            attempt_revision=record.record_revision,
            failure=PackageLifecycleFailureV1.for_operation(
                "package_operation_interrupted",
                stage="classified",
                operation_id=restart.operation_id,
                evidence_ref=restart.restart_id,
            ),
        )
    ):
        raise ValueError("Package restart changed the failed attempt")


def _decision_matches_restart(
    decision: PackageLifecycleRebindRequestV1,
    restart: PackageLifecycleRestartRecordV1,
) -> bool:
    return (
        decision.operation_id == restart.restart.operation_id
        and decision.request_fingerprint == restart.restart.request_fingerprint
        and decision.source_proof_ref == restart.restart.source_proof_ref
        and decision.cleanup_evidence_ref == restart.restart.cleanup_evidence_ref
    )


def _restart_refs_match(
    records: tuple[PackageLifecycleRecord, ...],
    current: PackageLifecycleStatusV1,
    decision: PackageLifecycleRebindRequestV1,
) -> bool:
    restart = next(
        (
            record
            for record in reversed(records)
            if isinstance(record, PackageLifecycleRestartRecordV1)
            and record.status.operation_id == current.operation_id
        ),
        None,
    )
    return (
        restart is None
        or restart.status.attempt_epoch != current.attempt_epoch
        or _decision_matches_restart(decision, restart)
    )


def _next_phase(phase: PackageLifecyclePhase) -> PackageLifecyclePhase | None:
    try:
        index = _PHASE_SEQUENCE.index(phase)
    except ValueError:
        return None
    if index + 1 == len(_PHASE_SEQUENCE):
        return None
    return _PHASE_SEQUENCE[index + 1]


def _last_operation_record(
    records: tuple[PackageLifecycleRecord, ...],
    operation_id: str,
) -> PackageLifecycleJournalRecordV1:
    for record in reversed(records):
        if (
            record.status.operation_id == operation_id
            and record.record_kind == "operation"
        ):
            return record
    raise ValueError("Package operation has no operation record")


__all__ = [
    "PACKAGE_LIFECYCLE_JOURNAL_CODEC",
    "PackageLifecycleJournal",
    "PackageLifecycleJournalError",
]
