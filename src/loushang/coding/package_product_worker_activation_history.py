"""Shared Product C5 replay checks for Linux and Windows Worker journals.

The platform owners still supply their own pinned-root I/O and durable commit
protocol. This module only validates complete canonical records and identities.
"""

from __future__ import annotations

import json
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
    "evidenceAuthorityFingerprint",
    "evidenceAuthorityId",
    "hostIdentity",
    "owner",
    "ownerGeneration",
    "policyFingerprint",
    "receiptFingerprint",
    "required",
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
            if prior_attempt is not None:
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
    "decode_coding_worker_activation_history",
    "validate_coding_worker_activation_attempt_history",
]
