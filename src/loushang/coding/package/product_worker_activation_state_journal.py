"""Coding-compatible entry point for shared segmented C5 state storage."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from loushang.harness.worker.activation_state_journal import (
    _CODEC as _CODEC,
)
from loushang.harness.worker.activation_state_journal import (
    _FORMAT as _FORMAT,
)
from loushang.harness.worker.activation_state_journal import (
    _MAX_JOURNAL_BYTES as _DEFAULT_MAX_BYTES,
)
from loushang.harness.worker.activation_state_journal import (
    _MAX_REVISIONS as _DEFAULT_MAX_REVISIONS,
)
from loushang.harness.worker.history._activation_store import SegmentedActivationJournal

from .product_worker_activation_history import CodingProductWorkerRetainedAttemptV1

_MAX_BYTES = _DEFAULT_MAX_BYTES
_MAX_REVISIONS = _DEFAULT_MAX_REVISIONS


class CodingProductWorkerActivationStateJournal(SegmentedActivationJournal):
    def __init__(
        self, path: Path, *, scope_id: str | None = None, store_id: str | None = None
    ) -> None:
        from .product_worker_history_read_v2 import _HISTORY_READER

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

    def _max_history_bytes(self) -> int:
        return _MAX_BYTES

    def _max_history_records(self) -> int:
        return _MAX_REVISIONS


__all__ = [
    "CodingProductWorkerActivationStateJournal",
    "CodingProductWorkerRetainedAttemptV1",
]
