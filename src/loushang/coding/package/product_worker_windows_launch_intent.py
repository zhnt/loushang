"""Immutable Product custody linking a Windows Worker launch across owners.

The intent precedes native provisioning and process effects. It records only
pathless identities; a retained or unpublished intent is recovery debt, never
permission to launch or delete a payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loushang.harness.package_product._worker_windows_attempt import (
    WindowsProductWorkerIntentRecords,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.worker.contracts import ManagedWorkerLaunchRequestV1
from loushang.harness.worker.history._base_codec import _unchanged
from loushang.harness.worker.history._windows_launch_intent_base import (
    WindowsLaunchIntentMethods,
)
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationReceiptV1,
)

from .legacy_windows_receipt import _MAX_RECEIPT_BYTES, _receipt_io
from .product_worker_windows_receipt import CodingWindowsWorkerProductReceiptOwner

if TYPE_CHECKING:
    from .product_worker_windows_payload import CodingWindowsWorkerPayloadLeaseV1

_MAX_BYTES = 4096


class CodingWindowsWorkerLaunchIntentError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerLaunchIntentV1(WindowsLaunchIntentMethods):
    _wire_label = "Windows Worker launch intent"
    _wire_lists = ("stageIdentity",)
    _wire_error_type = CodingWindowsWorkerLaunchIntentError
    _wire_error_code = "coding_worker_launch_intent_invalid"

    @classmethod
    def _wire_maximum(cls) -> int:
        return _MAX_BYTES

    attempt_id: str
    stage_identity: tuple[int, int]
    receipt_fingerprint: str
    request_fingerprint: str
    identity_fingerprint: str
    runtime_fingerprint: str
    payload_digest: str
    owner_id: str
    supervisor_epoch: int
    intent_version: int = 1
    _fingerprint_domain = b"loushang.coding-windows-worker-launch-intent/v1\x00"


CodingWindowsWorkerLaunchIntentV1._wire_schema = RecordSchema.for_dataclass(
    CodingWindowsWorkerLaunchIntentV1,
    _unchanged,
    RecordField("stage_identity", decoder=tuple, encoder=list),
)


def commit_coding_windows_product_worker_launch_intent(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    receipt_owner: CodingWindowsWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    request: ManagedWorkerLaunchRequestV1,
    payload_lease: CodingWindowsWorkerPayloadLeaseV1,
) -> CodingWindowsWorkerLaunchIntentV1:
    """Publish one exact launch identity before any native or process effect."""
    from .product_worker_windows_payload import _PAYLOAD_PROGRAM

    return _INTENT_RECORDS.commit_bound(
        product,
        receipt_owner=receipt_owner,
        receipt=receipt,
        request=request,
        payload_lease=payload_lease,
        payload_program=_PAYLOAD_PROGRAM,
    )


def read_coding_windows_product_worker_launch_intent(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWindowsWorkerLaunchIntentV1 | None:
    """Read one committed intent without creating or repairing its receipt."""

    return _INTENT_RECORDS.read(product, attempt_id=attempt_id)


def inspect_coding_windows_product_worker_launch_intents(
    product: WindowsLocalWheelProductSessionOwner,
) -> tuple[CodingWindowsWorkerLaunchIntentV1, ...]:
    """Strictly inventory all committed intents and unpublished stages."""

    return _INTENT_RECORDS.inspect(product)


__all__ = [
    "CodingWindowsWorkerLaunchIntentError",
    "CodingWindowsWorkerLaunchIntentV1",
    "commit_coding_windows_product_worker_launch_intent",
    "inspect_coding_windows_product_worker_launch_intents",
    "read_coding_windows_product_worker_launch_intent",
]


_INTENT_RECORDS = WindowsProductWorkerIntentRecords(
    _product_id="coding",
    _io=_receipt_io,
    _record_type=CodingWindowsWorkerLaunchIntentV1,
    _maximum_bytes=_MAX_BYTES,
    _maximum_attempts=1024,
    _error_type=CodingWindowsWorkerLaunchIntentError,
    _error_prefix="coding_worker_launch_intent",
    _write_maximum_bytes=_MAX_RECEIPT_BYTES,
)
_inspect_intents_under_gc_guard = _INTENT_RECORDS.inspect_under_guard
_read_intent_under_gc_guard = _INTENT_RECORDS.read_under_guard
