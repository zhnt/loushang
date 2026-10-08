"""Portable C5 replay rules used before a Windows Product CAS read."""

from __future__ import annotations

import pytest

from loushang.coding.package_product_worker_activation_history import (
    decode_coding_worker_activation_history,
)
from loushang.harness.worker.activation_state_journal import (
    WorkerActivationStateJournalError,
    _canonical_json_bytes,
    _StateRecord,
)
from loushang.harness.worker.product_activation import (
    WorkerCleanupSettlementV1,
    _AttemptKey,
    _initial_state,
)
from tests.coding.test_package_product_worker_activation_segments import (
    _next_state,
    _registered_attempt,
)


def _history(*states: dict[str, object]) -> bytes:
    return b"".join(
        _canonical_json_bytes(_StateRecord.create(state).to_dict()) + b"\n"
        for state in states
    )


def _decode(raw: bytes) -> tuple[_StateRecord, ...]:
    return decode_coding_worker_activation_history(
        raw, max_revisions=16, max_bytes=64 * 1024
    )


def test_activation_history_refuses_torn_or_changed_canonical_record() -> None:
    initial = _initial_state(restart_budget=3)
    second = _next_state(initial)
    raw = _history(initial, second)
    assert tuple(item.document for item in _decode(raw)) == (initial, second)
    with pytest.raises(WorkerActivationStateJournalError) as torn:
        _decode(raw[:-1])
    assert torn.value.code == "worker_activation_state_corrupt"
    with pytest.raises(WorkerActivationStateJournalError) as changed:
        _decode(raw.replace(b"{", b"{ ", 1))
    assert changed.value.code == "worker_activation_state_corrupt"


def test_activation_history_refuses_compacted_attempt_reuse() -> None:
    receipt = "a" * 64
    attempt_id = "b" * 32
    key = _AttemptKey(receipt, attempt_id, 1).encoded
    attempt = _registered_attempt(receipt=receipt, attempt_id=attempt_id)
    initial = _initial_state(restart_budget=3)
    registered = _next_state(initial)
    registered["attempts"] = {key: attempt}
    settled = _next_state(registered)
    settled_attempt = dict(attempt)
    settled_attempt.update(
        phase="settled",
        domainRetired=True,
        protocolTerminal=True,
        cleanupSettlement=WorkerCleanupSettlementV1(
            receipt_fingerprint=receipt,
            attempt_id=attempt_id,
            owner_generation=1,
            host_identity="host-a",
            boot_identity="boot-a",
            protocol_terminal=True,
            domain_retired=True,
            tree_settled=True,
        ).to_dict(),
    )
    settled["attempts"] = {key: settled_attempt}
    compacted = _next_state(settled)
    compacted["attempts"] = {}
    reused = _next_state(compacted)
    reused["attempts"] = {key: attempt}

    assert _decode(_history(initial, registered, settled, compacted))[-1].document == (
        compacted
    )
    with pytest.raises(WorkerActivationStateJournalError) as replay:
        _decode(_history(initial, registered, settled, compacted, reused))
    assert replay.value.code == "worker_activation_state_corrupt"
