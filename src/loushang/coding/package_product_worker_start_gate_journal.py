"""Product-fixed intent and native-identity history for gated Linux Workers.

An intent proves only that the Product reserved one attempt before spawning.
A bound record precedes release and identifies the exact Hosting child. Neither
record alone authorizes recovery cleanup or third-party Worker admission.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal, cast

from loushang.harness.journal import (
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFormatProfile,
    JournalRecordCodec,
)
from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.worker.gated_start import WorkerNativeProcessIdentityV1
from loushang.harness.worker.history._start_gate import (
    _DIGEST as _DIGEST,
)
from loushang.harness.worker.history._start_gate import (
    _IDENTITY_FIELDS as _IDENTITY_FIELDS,
)
from loushang.harness.worker.history._start_gate import (
    _MAX_BYTES,
    _MAX_EVENTS,
    _StartGateRecordMethods,
    fold_start_gate_records,
)
from loushang.harness.worker.history._start_gate import (
    _identity_dict as _identity_dict,
)
from loushang.harness.worker.history._start_gate import (
    _identity_from_dict as _identity_from_dict,
)
from loushang.harness.worker.history._start_gate_store import (
    StartGateHistory,
    assert_checkpoint_attempt_available,
)

from ._worker_history_access import _CodingHistoryAccess
from .package_product_worker_activation_state_journal import (
    CodingProductWorkerActivationStateJournal,
)
from .package_product_worker_history_segments import (
    CodingWorkerSegmentedHistoryV1,
)

if TYPE_CHECKING:
    from .package_product_worker_history_checkpoint import (
        CodingWorkerHistoryCheckpointV1,
    )

_FILE_NAME = "worker-start-gates.jsonl"
_FORMAT = replace(SORTED_UNICODE_JSONL_FORMAT, separators=(",", ":"))


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


def _decode(value: object) -> CodingWorkerStartGateRecordV1:
    try:
        return CodingWorkerStartGateRecordV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Worker start gate record is invalid",
            code="coding_worker_start_gate_record_invalid",
        ) from exc


_CODEC: FunctionalJournalRecordCodec[CodingWorkerStartGateRecordV1] = (
    FunctionalJournalRecordCodec(
        encoder=CodingWorkerStartGateRecordV1.to_dict,
        decoder=_decode,
    )
)


_fold_start_gate_records = fold_start_gate_records


class CodingWorkerStartGateJournal(StartGateHistory[CodingWorkerStartGateRecordV1]):
    """Coding admission and activation coordination over shared gate history."""

    def __init__(self, product: PosixLocalWheelProductSessionOwner) -> None:
        if (
            not isinstance(product, PosixLocalWheelProductSessionOwner)
            or product.policy.product_id != "coding"
        ):
            raise ValueError("Coding Product owner is required")
        self._product = product
        path = product.state_root / _FILE_NAME
        from .package_product_worker_history_read_v2 import _HISTORY_READER

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
    def _record_format(self) -> JournalFormatProfile:
        return _FORMAT

    @property
    def _record_codec(self) -> JournalRecordCodec[CodingWorkerStartGateRecordV1]:
        return _CODEC

    def _max_history_bytes(self) -> int:
        return _MAX_BYTES

    def _max_history_records(self) -> int:
        return _MAX_EVENTS

    def append(
        self,
        *,
        phase: Literal["intent", "bound"],
        attempt_id: str,
        worker_identity_fingerprint: str,
        receipt_fingerprint: str,
        policy_fingerprint: str,
        scope_id: str,
        native_closure_digest: str,
        identity: WorkerNativeProcessIdentityV1 | None = None,
    ) -> CodingWorkerStartGateRecordV1:
        if not any(
            binding.source_trust_class == "local-worker-candidate"
            for binding in self._product.policy.bindings
        ):
            raise ValueError("Coding Worker candidate Product owner is required")
        with self._append_position(
            phase=phase,
            attempt_id=attempt_id,
            worker_identity_fingerprint=worker_identity_fingerprint,
            receipt_fingerprint=receipt_fingerprint,
            policy_fingerprint=policy_fingerprint,
            scope_id=scope_id,
            native_closure_digest=native_closure_digest,
        ) as position:
            activation = CodingProductWorkerActivationStateJournal(
                self._product.state_root / "worker-activation-state.jsonl"
            )
            if not activation.initialized_read_only():
                if position.has_records:
                    raise CodingWorkerStartGateJournalError(
                        "coding_worker_start_gate_activation_history_missing"
                    )
                activation.load()
            return self._append_record(
                position,
                phase=phase,
                attempt_id=attempt_id,
                worker_identity_fingerprint=worker_identity_fingerprint,
                receipt_fingerprint=receipt_fingerprint,
                policy_fingerprint=policy_fingerprint,
                scope_id=scope_id,
                native_closure_digest=native_closure_digest,
                identity=identity,
            )

    def _checkpoint_writer_fence(
        self, rooted: RootedFile
    ) -> tuple[CodingWorkerHistoryCheckpointV1, ...]:
        return cast(
            "tuple[CodingWorkerHistoryCheckpointV1, ...]",
            super()._checkpoint_writer_fence(rooted),
        )

    @staticmethod
    def _assert_checkpoint_source(
        checkpoints: tuple[CodingWorkerHistoryCheckpointV1, ...],
        history: CodingWorkerSegmentedHistoryV1,
    ) -> int:
        from .package_product_worker_history_checkpoint import _CHECKPOINT_HISTORY

        return _CHECKPOINT_HISTORY.verify_source_revision(
            checkpoints,
            history,
            stream_index=3,
            error_type=CodingWorkerStartGateJournalError,
            code="coding_worker_start_gate_checkpoint_source_changed",
        )

    @staticmethod
    def _assert_checkpoint_attempt_available(
        checkpoints: tuple[CodingWorkerHistoryCheckpointV1, ...],
        attempt_id: str,
    ) -> None:
        assert_checkpoint_attempt_available(
            checkpoints,
            attempt_id,
            error_type=CodingWorkerStartGateJournalError,
        )


__all__ = [
    "CodingWorkerStartGateJournal",
    "CodingWorkerStartGateJournalError",
    "CodingWorkerStartGateRecordV1",
]
