"""Offline proof that a Windows Worker reservation began no native effect.

The Product reads its pinned payload, launch intent, provisioning reservation,
and absence of Supervisor history together. This review has no settlement or
cleanup authority by itself.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from loushang.harness.package_product._windows_worker_recovery import (
    review_windows_product_worker_no_effect_under_guard,
)
from loushang.harness.package_product._worker_windows_attempt import (
    capture_windows_product_worker_stage,
    review_windows_product_worker_offline,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._windows_stage_review_wire import (
    _WindowsReservedStageReviewMethods,
)

from .package_product_worker_windows_launch_intent import (
    CodingWindowsWorkerLaunchIntentV1,
    _read_intent_under_gc_guard,
)
from .package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAttemptV1,
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
)
from .package_product_worker_windows_stage_retirement import (
    _inspect_retirement_attempt_ids_under_gc_guard,
)
from .package_product_worker_windows_stage_review import (
    FileIdentity,
    _inspection,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
_MAX_REVIEW_BYTES = 32768

_RESERVED_HISTORY_ERROR = "coding_worker_reserved_history_unverified"
_UNLAUNCHED_HISTORY_ERROR = "coding_worker_unlaunched_history_unverified"


class CodingWindowsWorkerReservedReviewError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerReservedNoEffectReviewV1(_WindowsReservedStageReviewMethods):
    _fingerprint_domain = b"loushang.coding-windows-worker-reserved-review/v1\x00"
    _attempt_type = CodingWindowsWorkerRecoveryAttemptV1
    _intent_type = CodingWindowsWorkerLaunchIntentV1
    _record_kind = "reserved"
    _record_error = CodingWindowsWorkerReservedReviewError
    _record_error_code = "coding_worker_reserved_review_invalid"

    @classmethod
    def _record_maximum(cls) -> int:
        return _MAX_REVIEW_BYTES

    attempt_id: str
    intent_fingerprint: str
    lease_owner_revision: int
    native_revision: int
    stage_identity: FileIdentity
    directory_identities: tuple[tuple[str, FileIdentity], ...]
    marker_identity: FileIdentity
    executable_identity: FileIdentity
    executable_digest: str
    entrypoint: str

    @classmethod
    def _payload_maximum(cls) -> int:
        return _MAX_PAYLOAD_BYTES


def review_coding_windows_product_worker_reserved_no_effect(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWindowsWorkerReservedNoEffectReviewV1:
    """Capture one exact Product stage while all Package runtimes are closed."""

    return _review_no_effect(product, attempt_id=attempt_id, settled=False)


def review_coding_windows_product_worker_settled_unlaunched(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWindowsWorkerReservedNoEffectReviewV1:
    """Capture a settled reservation with no Supervisor or native effect."""

    return _review_no_effect(product, attempt_id=attempt_id, settled=True)


def _review_no_effect(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str, settled: bool
) -> CodingWindowsWorkerReservedNoEffectReviewV1:
    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(attempt_id) is not str
        or _ATTEMPT.fullmatch(attempt_id) is None
    ):
        role = "unlaunched" if settled else "reserved"
        raise OSError(f"Windows Worker {role} review requires a Product owner")
    return review_windows_product_worker_offline(
        product,
        active_error=lambda: CodingWindowsWorkerReservedReviewError(
            "coding_worker_unlaunched_runtime_active"
            if settled
            else "coding_worker_reserved_runtime_active"
        ),
        review=lambda quiescence: _review_no_effect_under_gc_guard(
            product,
            attempt_id=attempt_id,
            lease_owner_revision=quiescence.owner_revision,
            settled=settled,
        ),
    )


def _review_reserved_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    lease_owner_revision: int,
) -> CodingWindowsWorkerReservedNoEffectReviewV1:
    return _review_no_effect_under_gc_guard(
        product,
        attempt_id=attempt_id,
        lease_owner_revision=lease_owner_revision,
        settled=False,
    )


def _review_no_effect_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    lease_owner_revision: int,
    settled: bool,
) -> CodingWindowsWorkerReservedNoEffectReviewV1:
    return review_windows_product_worker_no_effect_under_guard(
        product,
        attempt_id=attempt_id,
        lease_owner_revision=lease_owner_revision,
        settled=settled,
        record_type=CodingWindowsWorkerReservedNoEffectReviewV1,
        inspect_inventory=_inspect_windows_worker_recovery_inventory_under_gc_guard,
        read_intent=_read_intent_under_gc_guard,
        inspect_retirements=_inspect_retirement_attempt_ids_under_gc_guard,
        capture_reserved=_capture_reserved_stage,
        history_error=_UNLAUNCHED_HISTORY_ERROR if settled else _RESERVED_HISTORY_ERROR,
    )


def _capture_reserved_stage(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    intent: CodingWindowsWorkerLaunchIntentV1,
    native_revision: int | None,
    lease_owner_revision: int,
) -> CodingWindowsWorkerReservedNoEffectReviewV1:
    if native_revision not in (1, 2):
        raise CodingWindowsWorkerReservedReviewError(
            "coding_worker_reserved_history_unverified"
        )
    return capture_windows_product_worker_stage(
        product,
        attempt_id=intent.attempt_id,
        expected_stage=intent.stage_identity,
        intent=intent,
        inspection=_inspection(),
        marker_name="worker-payload.json",
        max_marker_bytes=1024,
        max_payload_bytes=_MAX_PAYLOAD_BYTES,
        error_type=CodingWindowsWorkerReservedReviewError,
        error_prefix="coding_worker_reserved",
        result_factory=lambda captured: CodingWindowsWorkerReservedNoEffectReviewV1(
            attempt_id=intent.attempt_id,
            intent_fingerprint=intent.fingerprint,
            lease_owner_revision=lease_owner_revision,
            native_revision=native_revision,
            stage_identity=captured.stage_identity,
            directory_identities=captured.directory_identities,
            marker_identity=captured.marker_identity,
            executable_identity=captured.executable_identity,
            executable_digest=captured.executable_digest,
            entrypoint=captured.entrypoint,
        ),
    )


__all__ = [
    "CodingWindowsWorkerReservedNoEffectReviewV1",
    "CodingWindowsWorkerReservedReviewError",
    "review_coding_windows_product_worker_reserved_no_effect",
    "review_coding_windows_product_worker_settled_unlaunched",
]


CodingWindowsWorkerReservedNoEffectReviewV1._bind_record_schema()
