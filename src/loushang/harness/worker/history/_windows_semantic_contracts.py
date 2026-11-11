"""Borrowed immutable facts for Windows history reconstruction, without IO authority."""

from __future__ import annotations

import re
from typing import Protocol

from loushang.harness.worker._windows_provisioning_journal import (
    WindowsWorkerProvisioningAttemptV1,
)
from loushang.harness.worker.activation_state_journal import _StateRecord
from loushang.harness.worker.history._activation import _RetainedAttemptFields
from loushang.harness.worker.history._opt_in import _OptInDecisionMethods
from loushang.harness.worker.history._receipts import _ReceiptRecordMethods
from loushang.harness.worker.history._windows_recovery import WindowsRecoveryAttemptV1
from loushang.harness.worker.journal import WorkerAttemptRecordV1


class _SourceFileFacts(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def size(self) -> int: ...
    @property
    def sha256_digest(self) -> str: ...


class _SourceFacts(Protocol):
    @property
    def scope_id(self) -> str: ...
    @property
    def store_id(self) -> str: ...
    @property
    def snapshot_digest(self) -> str: ...
    @property
    def files(self) -> tuple[_SourceFileFacts, ...]: ...


class _LaunchIntentFacts(Protocol):
    @property
    def attempt_id(self) -> str: ...
    @property
    def stage_identity(self) -> tuple[int, int]: ...
    @property
    def receipt_fingerprint(self) -> str: ...
    @property
    def request_fingerprint(self) -> str: ...
    @property
    def identity_fingerprint(self) -> str: ...
    def to_dict(self) -> dict[str, object]: ...
    def to_bytes(self) -> bytes: ...


class _RecoveryFacts(Protocol):
    @property
    def attempts(self) -> tuple[WindowsRecoveryAttemptV1, ...]: ...
    @property
    def opt_in_decisions(self) -> tuple[_OptInDecisionMethods, ...]: ...
    @property
    def receipt_records(self) -> tuple[_ReceiptRecordMethods, ...]: ...
    @property
    def supervisor_records(self) -> tuple[WorkerAttemptRecordV1, ...]: ...
    @property
    def activation_state_records(self) -> tuple[_StateRecord, ...]: ...
    @property
    def activation_state_revision(self) -> int: ...
    @property
    def activation_state_owner_present(self) -> bool: ...
    @property
    def retained_activation_attempts(self) -> tuple[_RetainedAttemptFields, ...]: ...
    @property
    def launch_intents(self) -> tuple[_LaunchIntentFacts, ...]: ...
    @property
    def native_provisioning_attempts(
        self,
    ) -> tuple[WindowsWorkerProvisioningAttemptV1, ...]: ...
    @property
    def native_job_absence(self) -> tuple[tuple[str, bool | None], ...]: ...


_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")


def native_matches_intent(
    attempt: WindowsRecoveryAttemptV1, intent: _LaunchIntentFacts
) -> bool:
    if (
        attempt.native_worker_request_fingerprint != intent.request_fingerprint
        or attempt.native_receipt_fingerprint != intent.receipt_fingerprint
    ):
        return False
    return True


def launch_matches_intent(
    attempt: WindowsRecoveryAttemptV1, intent: _LaunchIntentFacts
) -> bool:
    if (
        attempt.launch_request_fingerprint != intent.request_fingerprint
        or attempt.launch_receipt_fingerprint != intent.receipt_fingerprint
        or attempt.launch_identity_fingerprint != intent.identity_fingerprint
    ):
        return False
    return True


def no_effect_history_matches(
    attempt: WindowsRecoveryAttemptV1, *, settled: bool
) -> bool:
    phases = ("reserved", "settled") if settled else ("reserved",)
    if (
        attempt.native_phase != phases[-1]
        or attempt.native_revision != len(phases)
        or attempt.native_phase_history != phases
        or attempt.native_witness_present_history != (False,) * len(phases)
        or attempt.supervisor_phase is not None
        or attempt.supervisor_revision is not None
        or attempt.supervisor_process_settled is not None
        or attempt.supervisor_identity_fingerprint is not None
    ):
        return False
    return True
