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
    load_jsonl,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleFailureV1,
    PackageLifecycleJournalRecordV1,
    PackageLifecyclePhase,
    PackageLifecycleRequestV1,
    PackageLifecycleStatusV1,
    PluginBoundPackageClassificationV1,
)


class PackageLifecycleJournalError(RuntimeError):
    """Fail-closed journal, CAS, replay, or operation identity error."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


def _encode_record(record: PackageLifecycleJournalRecordV1) -> dict[str, object]:
    if not isinstance(record, PackageLifecycleJournalRecordV1):
        raise TypeError("Package lifecycle journal record is required")
    return record.to_dict()


def _decode_record(value: object) -> PackageLifecycleJournalRecordV1:
    try:
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
                disposition=(
                    "committed" if next_phase == "committed" else "active"
                ),
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
                if current.request_fingerprint != requests[
                    failure.operation_id
                ].request_fingerprint:
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
    ) -> PackageLifecycleStatusV1:
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

    def records(self) -> tuple[PackageLifecycleJournalRecordV1, ...]:
        with self._exclusive():
            return self._load_unlocked()

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

    def _append_unlocked(self, record: PackageLifecycleJournalRecordV1) -> None:
        append_jsonl_record(
            self._path,
            record,
            record_codec=PACKAGE_LIFECYCLE_JOURNAL_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._unlocked_durability,
        )

    def _load_unlocked(self) -> tuple[PackageLifecycleJournalRecordV1, ...]:
        if not self._path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[None, PackageLifecycleJournalRecordV1] = (
                load_jsonl(
                    self._path,
                    record_codec=PACKAGE_LIFECYCLE_JOURNAL_CODEC,
                    format_profile=SORTED_UNICODE_JSONL_FORMAT,
                    durability=self._unlocked_durability,
                    load_policy=self._load_policy,
                )
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
    records: tuple[PackageLifecycleJournalRecordV1, ...],
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
    records: tuple[PackageLifecycleJournalRecordV1, ...],
) -> tuple[
    dict[str, PackageLifecycleRequestV1],
    dict[str, PackageLifecycleStatusV1],
]:
    requests: dict[str, PackageLifecycleRequestV1] = {}
    statuses: dict[str, PackageLifecycleStatusV1] = {}
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
        if record.record_kind == "operation":
            _validate_operation_record(current, record.status)
        else:
            _validate_attempt_record(current, record.status)
        statuses[operation_id] = record.status
    return requests, statuses


def _validate_accept_record(record: PackageLifecycleJournalRecordV1) -> None:
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


def _next_phase(phase: PackageLifecyclePhase) -> PackageLifecyclePhase | None:
    try:
        index = _PHASE_SEQUENCE.index(phase)
    except ValueError:
        return None
    if index + 1 == len(_PHASE_SEQUENCE):
        return None
    return _PHASE_SEQUENCE[index + 1]


def _last_operation_record(
    records: tuple[PackageLifecycleJournalRecordV1, ...],
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
