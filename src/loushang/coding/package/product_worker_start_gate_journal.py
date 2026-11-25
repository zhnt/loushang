"""Product-fixed intent and native-identity history for gated Linux Workers.

An intent proves only that the Product reserved one attempt before spawning.
A bound record precedes release and identifies the exact Hosting child. Neither
record alone authorizes recovery cleanup or third-party Worker admission.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from loushang.coding.package.worker_history_access import _CodingHistoryAccess
from loushang.harness.journal import (
    SORTED_UNICODE_JSONL_FORMAT as SORTED_UNICODE_JSONL_FORMAT,
)
from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
    JournalRecordCodec,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    has_worker_candidate_binding,
)
from loushang.harness.worker.gated_start import WorkerNativeProcessIdentityV1
from loushang.harness.worker.history._start_gate import (
    _DIGEST as _DIGEST,
)
from loushang.harness.worker.history._start_gate import (
    _MAX_BYTES,
    _MAX_EVENTS,
    _StartGateRecordMethods,
)
from loushang.harness.worker.history._start_gate import (
    _identity_dict as _identity_dict,
)
from loushang.harness.worker.history._start_gate_store import (
    StartGateHistory,
)

from .product_worker_activation_state_journal import (
    CodingProductWorkerActivationStateJournal,
)

_FILE_NAME = "worker-start-gates.jsonl"


class CodingWorkerStartGateJournalError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerStartGateRecordV1(_StartGateRecordMethods):
    journal_revision: int
    phase: Literal["intent", "bound"]
    attempt_id: str
    worker_identity_fingerprint: str
    receipt_fingerprint: str
    policy_fingerprint: str
    scope_id: str
    native_closure_digest: str
    identity: WorkerNativeProcessIdentityV1 | None
    record_digest: str


_CODEC = FunctionalJournalRecordCodec.with_decode_error(
    encoder=CodingWorkerStartGateRecordV1.to_dict,
    decoder=lambda value: CodingWorkerStartGateRecordV1.from_dict(value),
    message="Worker start gate record is invalid",
    code="coding_worker_start_gate_record_invalid",
)


class CodingWorkerStartGateJournal(StartGateHistory[CodingWorkerStartGateRecordV1]):
    """Coding admission and activation coordination over shared gate history."""

    _activation_missing_code = "coding_worker_start_gate_activation_history_missing"

    def __init__(self, product: PosixLocalWheelProductSessionOwner) -> None:
        if (
            not isinstance(product, PosixLocalWheelProductSessionOwner)
            or product.policy.product_id != "coding"
        ):
            raise ValueError("Coding Product owner is required")
        self._product = product
        path = product.state_root / _FILE_NAME
        from .product_worker_history_read_v2 import _HISTORY_READER

        super().__init__(
            path,
            access=_CodingHistoryAccess(product),
            history_reader=_HISTORY_READER,
            error_type=CodingWorkerStartGateJournalError,
        )

    @property
    def _record_type(self) -> type[CodingWorkerStartGateRecordV1]:
        return CodingWorkerStartGateRecordV1

    @property
    def _record_codec(self) -> JournalRecordCodec[CodingWorkerStartGateRecordV1]:
        return _CODEC

    def _max_history_bytes(self) -> int:
        return _MAX_BYTES

    def _max_history_records(self) -> int:
        return _MAX_EVENTS

    def _require_append_admission(self) -> None:
        if not has_worker_candidate_binding(self._product.policy):
            raise ValueError("Coding Worker candidate Product owner is required")

    def _activation_journal(self) -> CodingProductWorkerActivationStateJournal:
        return CodingProductWorkerActivationStateJournal(
            self._product.state_root / "worker-activation-state.jsonl"
        )


__all__ = [
    "CodingWorkerStartGateJournal",
    "CodingWorkerStartGateJournalError",
    "CodingWorkerStartGateRecordV1",
]
