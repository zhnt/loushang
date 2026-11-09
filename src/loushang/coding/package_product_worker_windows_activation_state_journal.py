"""Coding admission and value bindings for shared Windows C5 custody."""

from __future__ import annotations

import os

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.worker.activation_state_journal import (
    _MAX_JOURNAL_BYTES as _MAX_BYTES,
)
from loushang.harness.worker.activation_state_journal import _MAX_REVISIONS
from loushang.harness.worker.history._windows_product_journals import (
    WindowsActivationStateJournal,
)
from loushang.harness.worker.history._windows_product_journals import (
    _head_bytes as _head_bytes,
)

from ._worker_history_access import _CodingWindowsHistoryAccess
from .package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)

_NAME = "worker-activation-state.jsonl"
_LOCK = _NAME + ".lock"
_MAX_HEAD_BYTES = 256


class CodingWindowsWorkerActivationStateJournal(
    WindowsActivationStateJournal[CodingProductWorkerRetainedAttemptV1]
):
    """Append and reopen C5 CAS revisions under the original Windows root."""

    _max_bytes = staticmethod(lambda: _MAX_BYTES)
    _max_revisions = staticmethod(lambda: _MAX_REVISIONS)
    _max_head_bytes = staticmethod(lambda: _MAX_HEAD_BYTES)
    _retained_type = CodingProductWorkerRetainedAttemptV1

    def __init__(self, product: WindowsLocalWheelProductSessionOwner) -> None:
        if (
            os.name != "nt"
            or type(product) is not WindowsLocalWheelProductSessionOwner
            or product.policy.product_id != "coding"
        ):
            raise ValueError("Windows C5 state requires its Coding Product owner")
        product.assert_root_gc_authority_current()
        super().__init__(
            product.state_root / _NAME, access=_CodingWindowsHistoryAccess(product)
        )

    def retained_attempts_read_only(
        self,
    ) -> tuple[CodingProductWorkerRetainedAttemptV1, ...]:
        return super().retained_attempts_read_only()


__all__ = ["CodingWindowsWorkerActivationStateJournal"]
