"""Read-only Product proof for a retained Windows LPAC crash cleanup attempt.

This review never carries a native spec or grants a cleanup effect. A writer
must repeat every observation while holding its Package and Product locks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._windows_recovery import (
    _valid_crash_effect_history as _worker_crash_effect_history,
)
from loushang.harness.worker.history._windows_recovery import (
    windows_worker_crash_cleanup_history_matches,
    windows_worker_crash_settled_history_matches,
)

from .package_product_worker_windows_orphan_review import (
    CodingWindowsWorkerOrphanRuntimeReviewV1,
)
from .package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAttemptV1,
)


class CodingWindowsWorkerCrashCleanupReviewError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerCrashCleanupReviewV1:
    """One time-bound observation; it grants no native cleanup authority."""

    orphan_review: CodingWindowsWorkerOrphanRuntimeReviewV1
    native_revision: int
    native_spec_fingerprint: str
    payload_directory_identity: tuple[int, int]


def _valid_crash_cleanup_history(
    attempt: CodingWindowsWorkerRecoveryAttemptV1,
) -> bool:
    return _valid_crash_effect_history(attempt, settled=False)


def _valid_crash_native_settlement_history(
    attempt: CodingWindowsWorkerRecoveryAttemptV1,
) -> bool:
    return _valid_crash_effect_history(attempt, settled=True)


_valid_crash_effect_history = _worker_crash_effect_history


_crash_cleanup_history_matches = windows_worker_crash_cleanup_history_matches


_crash_settled_history_matches = windows_worker_crash_settled_history_matches


def review_coding_windows_product_worker_crash_cleanup(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWindowsWorkerCrashCleanupReviewV1:
    """Join an orphan, exact stage and current LPAC spec without an effect."""
    from .package_product_worker_windows_crash_recovery import _recovery_program

    return cast(
        "CodingWindowsWorkerCrashCleanupReviewV1",
        _recovery_program().review_cleanup(product, attempt_id=attempt_id),
    )


__all__ = [
    "CodingWindowsWorkerCrashCleanupReviewError",
    "CodingWindowsWorkerCrashCleanupReviewV1",
    "review_coding_windows_product_worker_crash_cleanup",
]
