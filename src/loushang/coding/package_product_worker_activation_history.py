"""Shared Product C5 replay checks for Linux and Windows Worker journals.

The platform owners still supply their own pinned-root I/O and durable commit
protocol. This module only validates complete canonical records and identities.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

from loushang.harness.worker.activation_state_journal import (
    WorkerActivationStateJournalError,
    _canonical_json_bytes,
    _StateRecord,
)
from loushang.harness.worker.product_activation import _ATTEMPT_TRANSITIONS

_IMMUTABLE_ATTEMPT_FIELDS = (
    "attemptId",
    "bootIdentity",
    "cleanupContractVersion",
    "evidenceAuthorityFingerprint",
    "evidenceAuthorityId",
    "hostIdentity",
    "owner",
    "ownerGeneration",
    "policyFingerprint",
    "receiptFingerprint",
    "required",
)


@dataclass(frozen=True, slots=True)
class CodingProductWorkerRetainedAttemptV1:
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


def project_coding_worker_retained_attempts(
    records: tuple[_StateRecord, ...],
) -> tuple[CodingProductWorkerRetainedAttemptV1, ...]:
    """Project all validated C5 attempt references from one retained history."""

    latest: dict[str, tuple[int, dict[str, object]]] = {}
    for record in records:
        attempts = cast(dict[str, dict[str, object]], record.document["attempts"])
        for attempt in attempts.values():
            latest[cast(str, attempt["attemptId"])] = (
                record.journal_revision,
                attempt,
            )
    current_ids = (
        set()
        if not records
        else {
            cast(str, attempt["attemptId"])
            for attempt in cast(
                dict[str, dict[str, object]], records[-1].document["attempts"]
            ).values()
        }
    )
    return tuple(
        CodingProductWorkerRetainedAttemptV1(
            attempt_id=attempt_id,
            receipt_fingerprint=cast(str, attempt["receiptFingerprint"]),
            policy_fingerprint=cast(str, attempt["policyFingerprint"]),
            owner_generation=cast(int, attempt["ownerGeneration"]),
            cleanup_contract_version=cast(int, attempt["cleanupContractVersion"]),
            host_identity=cast(str, attempt["hostIdentity"]),
            boot_identity=cast(str, attempt["bootIdentity"]),
            phase=cast(str, attempt["phase"]),
            last_seen_revision=revision,
            current=attempt_id in current_ids,
        )
        for attempt_id, (revision, attempt) in sorted(
            latest.items(), key=lambda item: (item[1][0], item[0])
        )
    )


def validate_coding_worker_activation_attempt_history(
    records: tuple[_StateRecord, ...],
) -> None:
    """Reject compacted ID reuse and changed identities across C5 revisions."""

    seen_attempt_ids: dict[str, str] = {}
    removed_keys: set[str] = set()
    previous: dict[str, dict[str, object]] = {}
    for record in records:
        current = cast(dict[str, dict[str, object]], record.document["attempts"])
        for key in previous.keys() - current.keys():
            if previous[key]["phase"] != "settled":
                raise ValueError("Unsettled activation attempt was removed")
            removed_keys.add(key)
        for key, attempt in current.items():
            attempt_id = cast(str, attempt["attemptId"])
            prior_key = seen_attempt_ids.get(attempt_id)
            if key in removed_keys or (prior_key is not None and prior_key != key):
                raise ValueError("Activation attempt identity was reused")
            seen_attempt_ids[attempt_id] = key
            prior_attempt = previous.get(key)
            if prior_attempt is None:
                if attempt["phase"] != "registered":
                    raise ValueError("Activation attempt appeared after registration")
            else:
                if any(
                    attempt[field] != prior_attempt[field]
                    for field in _IMMUTABLE_ATTEMPT_FIELDS
                ):
                    raise ValueError("Activation attempt identity changed")
                prior_phase = cast(str, prior_attempt["phase"])
                phase = cast(str, attempt["phase"])
                if (
                    phase != prior_phase
                    and phase not in _ATTEMPT_TRANSITIONS[prior_phase]
                ):
                    raise ValueError("Activation attempt phase regressed")
        previous = current


def decode_coding_worker_activation_history(
    raw: bytes,
    *,
    max_revisions: int,
    max_bytes: int,
) -> tuple[_StateRecord, ...]:
    """Decode one Windows-sized C5 stream before it can supply CAS authority."""

    if (
        type(raw) is not bytes
        or type(max_revisions) is not int
        or max_revisions < 1
        or type(max_bytes) is not int
        or max_bytes < 1
        or len(raw) > max_bytes
        or (raw and not raw.endswith(b"\n"))
    ):
        raise WorkerActivationStateJournalError("worker_activation_state_corrupt")
    try:
        records = tuple(
            _StateRecord.from_dict(json.loads(line.decode("utf-8")))
            for line in raw.splitlines(keepends=True)
        )
        if len(records) > max_revisions or any(
            record.journal_revision != ordinal
            or line != _canonical_json_bytes(record.to_dict()) + b"\n"
            for ordinal, (record, line) in enumerate(
                zip(records, raw.splitlines(keepends=True), strict=True), 1
            )
        ):
            raise ValueError("Worker activation state history changed")
        validate_coding_worker_activation_attempt_history(records)
        return records
    except (RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise WorkerActivationStateJournalError(
            "worker_activation_state_corrupt"
        ) from exc


__all__ = [
    "CodingProductWorkerRetainedAttemptV1",
    "decode_coding_worker_activation_history",
    "project_coding_worker_retained_attempts",
    "validate_coding_worker_activation_attempt_history",
]
