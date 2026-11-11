"""Coding public projection types; C5 history validation belongs to Worker."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.worker.activation_state_journal import _StateRecord
from loushang.harness.worker.history._activation import (
    _RetainedAttemptFields,
    fold_activation_attempt_history,
    project_retained_attempts,
)
from loushang.harness.worker.history._activation import (
    decode_activation_history as decode_coding_worker_activation_history,
)
from loushang.harness.worker.history._activation import (
    validate_activation_attempt_history as validate_coding_worker_activation_attempt_history,
)

_fold_coding_worker_activation_attempt_history = fold_activation_attempt_history


@dataclass(frozen=True, slots=True)
class CodingProductWorkerRetainedAttemptV1(_RetainedAttemptFields):
    """Last retained C5 state for an attempt, including a compacted one."""

    attempt_id: str
    receipt_fingerprint: str
    policy_fingerprint: str
    owner_generation: int
    cleanup_contract_version: int
    host_identity: str
    boot_identity: str
    phase: str
    last_seen_revision: int
    current: bool
    no_effect: bool = False


def project_coding_worker_retained_attempts(
    records: tuple[_StateRecord, ...],
) -> tuple[CodingProductWorkerRetainedAttemptV1, ...]:
    return project_retained_attempts(
        records, record_type=CodingProductWorkerRetainedAttemptV1
    )


__all__ = [
    "CodingProductWorkerRetainedAttemptV1",
    "decode_coding_worker_activation_history",
    "project_coding_worker_retained_attempts",
    "validate_coding_worker_activation_attempt_history",
]
