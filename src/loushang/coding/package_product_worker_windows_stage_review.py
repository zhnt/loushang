"""Offline, read-only review of a cleanly stopped Windows Worker payload.

This captures exact retained bytes and identities for a later retirement
transaction. It does not claim that deletion, Job recovery, or rotation has
occurred, and it grants no filesystem mutation authority by itself.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product._windows_worker_recovery import (
    review_windows_product_worker_complete_stage_under_guard,
)
from loushang.harness.package_product._worker_windows_attempt import (
    CapturedWindowsWorkerStage as _CapturedStageBytesV1,
)
from loushang.harness.package_product._worker_windows_attempt import (
    capture_windows_product_worker_stage,
    review_windows_product_worker_offline,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._windows_stage_review_wire import (
    _WindowsCompleteStageReviewMethods,
)
from loushang.harness.worker.payload._windows_stage_io import WindowsStageInspection

from .package_product_worker_windows_launch_intent import (
    CodingWindowsWorkerLaunchIntentV1,
    _read_intent_under_gc_guard,
)
from .package_product_worker_windows_recovery_inventory import (
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_MARKER = "worker-payload.json"
_MAX_MARKER_BYTES = 1024
_MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
_MAX_REVIEW_BYTES = 32768
_READ_CHUNK = 1024 * 1024
_DIRECTORY_ATTRIBUTES = 0x00000010 | 0x00000020 | 0x00002000
_FILE_ATTRIBUTES = 0x00000020 | 0x00000080 | 0x00002000

FileIdentity = tuple[int, int, int, int, int]


class CodingWindowsWorkerStageReviewError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerStageReviewV1(_WindowsCompleteStageReviewMethods):
    _fingerprint_domain = b"loushang.coding-windows-worker-stage-review/v1\x00"
    _record_kind = "full"
    _record_error = CodingWindowsWorkerStageReviewError
    _record_error_code = "coding_worker_stage_review_record_invalid"

    @classmethod
    def _record_maximum(cls) -> int:
        return _MAX_REVIEW_BYTES

    attempt_id: str
    intent_fingerprint: str
    lease_owner_revision: int
    native_revision: int
    supervisor_revision: int
    entrypoint: str
    stage_identity: FileIdentity
    directory_identities: tuple[tuple[str, FileIdentity], ...]
    marker_identity: FileIdentity
    executable_identity: FileIdentity
    executable_digest: str

    @classmethod
    def _payload_maximum(cls) -> int:
        return _MAX_PAYLOAD_BYTES


def review_coding_windows_product_worker_complete_stage(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWindowsWorkerStageReviewV1:
    """Review one retained, cleanly stopped stage under offline Product locks."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(attempt_id) is not str
        or _ATTEMPT.fullmatch(attempt_id) is None
    ):
        raise OSError("Windows Worker stage review requires a Product owner")
    return review_windows_product_worker_offline(
        product,
        active_error=lambda: CodingWindowsWorkerStageReviewError(
            "coding_worker_stage_review_runtime_active"
        ),
        review=lambda quiescence: _review_complete_stage_under_gc_guard(
            product,
            attempt_id=attempt_id,
            lease_owner_revision=quiescence.owner_revision,
        ),
    )


def _review_complete_stage_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    lease_owner_revision: int,
) -> CodingWindowsWorkerStageReviewV1:
    """Reuse an already-held offline Package lease and Product GC gate."""

    return review_windows_product_worker_complete_stage_under_guard(
        product,
        attempt_id=attempt_id,
        lease_owner_revision=lease_owner_revision,
        record_type=CodingWindowsWorkerStageReviewV1,
        inspect_inventory=_inspect_windows_worker_recovery_inventory_under_gc_guard,
        read_intent=_read_intent_under_gc_guard,
        capture_stage=_capture_stage_bytes,
        error_prefix="coding_worker_stage_review",
    )


def _capture_stage_bytes(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    expected_stage: tuple[int, int],
    intent: CodingWindowsWorkerLaunchIntentV1,
) -> _CapturedStageBytesV1:
    """Verify exact retained members without assuming a termination cause."""

    if type(intent) is not CodingWindowsWorkerLaunchIntentV1:
        raise CodingWindowsWorkerStageReviewError(
            "coding_worker_stage_review_intent_invalid"
        )

    return capture_windows_product_worker_stage(
        product,
        attempt_id=attempt_id,
        expected_stage=expected_stage,
        intent=intent,
        inspection=_inspection(),
        marker_name=_MARKER,
        max_marker_bytes=_MAX_MARKER_BYTES,
        max_payload_bytes=_MAX_PAYLOAD_BYTES,
        error_type=CodingWindowsWorkerStageReviewError,
        error_prefix="coding_worker_stage_review",
        result_factory=lambda captured: captured,
    )


__all__ = [
    "CodingWindowsWorkerStageReviewError",
    "CodingWindowsWorkerStageReviewV1",
    "review_coding_windows_product_worker_complete_stage",
]


def _inspection() -> WindowsStageInspection:
    return WindowsStageInspection(
        CodingWindowsWorkerLaunchIntentV1,
        CodingWindowsWorkerStageReviewError,
        "coding_worker_stage_review",
        _MAX_PAYLOAD_BYTES,
        _READ_CHUNK,
        _DIRECTORY_ATTRIBUTES,
        _FILE_ATTRIBUTES,
    )


def _verify_marker(
    raw: bytes,
    *,
    intent: CodingWindowsWorkerLaunchIntentV1,
    stage_identity: tuple[int, int],
) -> tuple[str, int]:
    return _inspection().verify_marker(
        raw, intent=intent, stage_identity=stage_identity
    )


def _read_checked_file(
    parent: int, name: str, acl: WindowsPrivateDirectoryAcl, *, maximum_bytes: int
) -> tuple[bytes, FileIdentity]:
    return _inspection().read_checked_file(
        parent, name, acl, maximum_bytes=maximum_bytes
    )


CodingWindowsWorkerStageReviewV1._bind_record_schema()
