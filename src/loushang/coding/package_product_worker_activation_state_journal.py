"""Coding-compatible entry point for shared segmented C5 state storage."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from loushang.harness.journal import JournalFormatProfile, JournalRecordCodec
from loushang.harness.worker._segmented_history import CodingWorkerSegmentedHistoryV1
from loushang.harness.worker.activation_state_journal import (
    _CODEC,
    _FORMAT,
    WorkerActivationStateJournalError,
    _StateRecord,
)
from loushang.harness.worker.activation_state_journal import (
    _MAX_JOURNAL_BYTES as _DEFAULT_MAX_BYTES,
)
from loushang.harness.worker.activation_state_journal import (
    _MAX_REVISIONS as _DEFAULT_MAX_REVISIONS,
)
from loushang.harness.worker.history._activation_store import SegmentedActivationJournal

from .package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)

if TYPE_CHECKING:
    from .package_product_worker_history_checkpoint import (
        CodingWorkerHistoryCheckpointV1,
    )

_MAX_BYTES = _DEFAULT_MAX_BYTES
_MAX_REVISIONS = _DEFAULT_MAX_REVISIONS


class CodingProductWorkerActivationStateJournal(SegmentedActivationJournal):
    def __init__(
        self, path: Path, *, scope_id: str | None = None, store_id: str | None = None
    ) -> None:
        from .package_product_worker_history_read_v2 import _HISTORY_READER

        super().__init__(
            path, scope_id=scope_id, store_id=store_id, history_reader=_HISTORY_READER
        )

    def retained_attempts_read_only(
        self,
    ) -> tuple[CodingProductWorkerRetainedAttemptV1, ...]:
        return cast(
            tuple[CodingProductWorkerRetainedAttemptV1, ...],
            super().retained_attempts_read_only(),
        )

    @property
    def _record_codec(self) -> JournalRecordCodec[_StateRecord]:
        return _CODEC

    @property
    def _record_format(self) -> JournalFormatProfile:
        return _FORMAT

    def _max_history_bytes(self) -> int:
        return _MAX_BYTES

    def _max_history_records(self) -> int:
        return _MAX_REVISIONS

    @staticmethod
    def _assert_checkpoint_source(
        checkpoints: tuple[CodingWorkerHistoryCheckpointV1, ...],
        history: CodingWorkerSegmentedHistoryV1,
    ) -> int:
        from .package_product_worker_history_checkpoint import _CHECKPOINT_HISTORY

        return _CHECKPOINT_HISTORY.verify_source_revision(
            checkpoints,
            history,
            stream_index=2,
            error_type=WorkerActivationStateJournalError,
            code="worker_activation_state_checkpoint_source_changed",
        )


__all__ = [
    "CodingProductWorkerActivationStateJournal",
    "CodingProductWorkerRetainedAttemptV1",
]
