"""Immutable Product custody linking a Windows Worker launch across owners.

The intent precedes native provisioning and process effects. It records only
pathless identities; a retained or unpublished intent is recovery debt, never
permission to launch or delete a payload.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from loushang.harness.package_product._worker_windows_attempt import (
    WindowsProductWorkerIntentRecords,
    inspect_windows_product_worker_launch_intents,
    is_attempt_id,
    is_windows_product,
    read_windows_product_worker_launch_intent,
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

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_NAME = re.compile(r"worker-launch-intent-([0-9a-f]{32})\.json\Z")
_PREFIX = "worker-launch-intent-"
_MAX_ATTEMPTS = 1024
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
    from .product_worker_windows_payload import (
        _PAYLOAD_PROGRAM,
        CodingWindowsWorkerPayloadLeaseV1,
    )

    _require_product(product)
    if (
        type(receipt_owner) is not CodingWindowsWorkerProductReceiptOwner
        or receipt_owner.product_owner is not product
        or type(receipt) is not ProductWorkerActivationReceiptV1
        or (type(request) is not ManagedWorkerLaunchRequestV1)
        or (type(payload_lease) is not CodingWindowsWorkerPayloadLeaseV1)
        or (request.identity.product_id != "coding")
        or (receipt.policy.product_id != "coding")
    ):
        raise CodingWindowsWorkerLaunchIntentError(
            "coding_worker_launch_intent_binding_mismatch"
        )
    return _intent_records(product).commit_bound(
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

    _require_product(product)
    _require_attempt(attempt_id)
    return read_windows_product_worker_launch_intent(
        product, attempt_id=attempt_id, records=lambda: _intent_records(product)
    )


def inspect_coding_windows_product_worker_launch_intents(
    product: WindowsLocalWheelProductSessionOwner,
) -> tuple[CodingWindowsWorkerLaunchIntentV1, ...]:
    """Strictly inventory all committed intents and unpublished stages."""

    _require_product(product)
    return inspect_windows_product_worker_launch_intents(
        product, records=lambda: _intent_records(product)
    )


def _inspect_intents_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
) -> tuple[CodingWindowsWorkerLaunchIntentV1, ...]:
    return _intent_records(product).inspect()


def _read_intent_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    attempt_id: str,
    *,
    allow_unpublished_stage: bool = False,
) -> CodingWindowsWorkerLaunchIntentV1 | None:
    return _intent_records(product).read(
        attempt_id, allow_unpublished_stage=allow_unpublished_stage
    )


def _path(product: WindowsLocalWheelProductSessionOwner, attempt_id: str) -> Path:
    _require_attempt(attempt_id)
    return product.state_root / f"{_PREFIX}{attempt_id}.json"


def _require_product(product: WindowsLocalWheelProductSessionOwner) -> None:
    if not is_windows_product(product, "coding", os.name):
        raise OSError("Windows Worker launch intent requires a Product owner")


def _require_attempt(attempt_id: str) -> None:
    if not is_attempt_id(attempt_id):
        raise ValueError("Windows Worker launch intent attempt ID is invalid")


__all__ = [
    "CodingWindowsWorkerLaunchIntentError",
    "CodingWindowsWorkerLaunchIntentV1",
    "commit_coding_windows_product_worker_launch_intent",
    "inspect_coding_windows_product_worker_launch_intents",
    "read_coding_windows_product_worker_launch_intent",
]


def _intent_records(
    product: WindowsLocalWheelProductSessionOwner,
) -> WindowsProductWorkerIntentRecords[CodingWindowsWorkerLaunchIntentV1]:
    return WindowsProductWorkerIntentRecords(
        _product=product,
        _io=_receipt_io,
        _record_type=CodingWindowsWorkerLaunchIntentV1,
        _path=partial(_path, product),
        _prefix=_PREFIX,
        _name_pattern=_NAME,
        _maximum_bytes=lambda: _MAX_BYTES,
        _maximum_attempts=lambda: _MAX_ATTEMPTS,
        _error_type=CodingWindowsWorkerLaunchIntentError,
        _error_prefix="coding_worker_launch_intent",
        _write_maximum_bytes=_MAX_RECEIPT_BYTES,
    )
