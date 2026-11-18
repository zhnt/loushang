"""Read-only, exact stage review after a Windows Worker crash lease is repaired."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from loushang.harness.package_product._windows_worker_recovery import (
    review_windows_product_worker_crash_stage_under_guard,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsRuntimeQuiescenceV1,
)
from loushang.harness.worker.history._windows_recovery import (
    require_windows_worker_repair_record,
)
from loushang.harness.worker.history._windows_stage_review_wire import (
    _WindowsCrashStageReviewMethods,
)

from .package_product_worker_windows_launch_intent import _read_intent_under_gc_guard
from .package_product_worker_windows_orphan_review import _review_under_gc_guard
from .package_product_worker_windows_provisioning import (
    inspect_coding_windows_product_worker_provisioning_attempts,
)
from .package_product_worker_windows_stage_review import (
    FileIdentity,
    _capture_stage_bytes,
)

_MAX_REVIEW_BYTES = 32768


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerCrashStageReviewV1(_WindowsCrashStageReviewMethods):
    _fingerprint_domain = b"loushang.coding-windows-worker-crash-stage-review/v1\x00"
    _record_kind = "crash"
    _record_error = ValueError
    _record_error_code = "Windows Worker crash stage review bytes are invalid"

    @classmethod
    def _record_maximum(cls) -> int:
        return _MAX_REVIEW_BYTES

    attempt_id: str
    intent_fingerprint: str
    lease_owner_revision: int
    repaired_lease_id: str
    lease_repair_revision: int
    native_revision: int
    supervisor_revision: int | None
    native_spec_fingerprint: str
    entrypoint: str
    stage_identity: FileIdentity
    directory_identities: tuple[tuple[str, FileIdentity], ...]
    marker_identity: FileIdentity
    executable_identity: FileIdentity
    executable_digest: str


def review_coding_windows_product_worker_crash_stage(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWindowsWorkerCrashStageReviewV1:
    """Capture a fully settled crash stage while Package leases are quiescent."""
    from .package_product_worker_windows_crash_recovery import _recovery_program

    return cast(
        "CodingWindowsWorkerCrashStageReviewV1",
        _recovery_program().review_stage(product, attempt_id=attempt_id),
    )


def _review_crash_stage_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    quiescence: PackageWindowsRuntimeQuiescenceV1,
) -> CodingWindowsWorkerCrashStageReviewV1:
    return review_windows_product_worker_crash_stage_under_guard(
        product,
        attempt_id=attempt_id,
        quiescence=quiescence,
        record_type=CodingWindowsWorkerCrashStageReviewV1,
        review_runtime=_review_under_gc_guard,
        inspect_native=inspect_coding_windows_product_worker_provisioning_attempts,
        read_intent=_read_intent_under_gc_guard,
        capture_stage=_capture_stage_bytes,
    )


_require_repair_record = require_windows_worker_repair_record


__all__ = [
    "CodingWindowsWorkerCrashStageReviewV1",
    "review_coding_windows_product_worker_crash_stage",
]


CodingWindowsWorkerCrashStageReviewV1._bind_record_schema()
