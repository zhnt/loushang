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
from hashlib import sha256
from pathlib import Path
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
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.contracts import ManagedWorkerLaunchRequestV1
from loushang.harness.worker.history._base_codec import _BaseWireMethods, _unchanged
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationReceiptV1,
)

from .package_legacy_windows_receipt import (
    _MAX_RECEIPT_BYTES,
    _receipt_io,
)
from .package_product_worker_windows_receipt import (
    CodingWindowsWorkerProductReceiptOwner,
)

if TYPE_CHECKING:
    from .package_product_worker_windows_payload import (
        CodingWindowsWorkerPayloadLeaseV1,
    )

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
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
class CodingWindowsWorkerLaunchIntentV1(_BaseWireMethods):
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

    def __post_init__(self) -> None:
        if (
            type(self.attempt_id) is not str
            or _ATTEMPT.fullmatch(self.attempt_id) is None
            or type(self.stage_identity) is not tuple
            or len(self.stage_identity) != 2
            or any(type(value) is not int or value < 0 for value in self.stage_identity)
            or any(
                type(value) is not str or _DIGEST.fullmatch(value) is None
                for value in (
                    self.receipt_fingerprint,
                    self.request_fingerprint,
                    self.identity_fingerprint,
                    self.runtime_fingerprint,
                    self.payload_digest,
                )
            )
            or type(self.owner_id) is not str
            or not self.owner_id
            or len(self.owner_id) > 256
            or type(self.supervisor_epoch) is not int
            or self.supervisor_epoch < 1
            or type(self.intent_version) is not int
            or self.intent_version != 1
        ):
            raise ValueError("Windows Worker launch intent is invalid")

    @property
    def fingerprint(self) -> str:
        return sha256(
            b"loushang.coding-windows-worker-launch-intent/v1\0" + self.to_bytes()
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptId": self.attempt_id,
            "identityFingerprint": self.identity_fingerprint,
            "intentVersion": self.intent_version,
            "ownerId": self.owner_id,
            "payloadDigest": self.payload_digest,
            "receiptFingerprint": self.receipt_fingerprint,
            "requestFingerprint": self.request_fingerprint,
            "runtimeFingerprint": self.runtime_fingerprint,
            "stageIdentity": list(self.stage_identity),
            "supervisorEpoch": self.supervisor_epoch,
        }

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


CodingWindowsWorkerLaunchIntentV1._wire_schema = RecordSchema.for_dataclass(
    CodingWindowsWorkerLaunchIntentV1,
    _unchanged,
    RecordField("stage_identity", decoder=tuple),
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
    from .package_product_worker_windows_payload import (
        CodingWindowsWorkerPayloadLeaseV1,
        _require_coding_windows_product_bound_request,
        _verify_stage_marker,
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
        or (request.identity.scope_id != receipt.policy.product_scope_id)
        or (request.identity.plugin_id != receipt.policy.plugin_id)
        or (
            request.identity.plugin_revision_digest
            != receipt.policy.plugin_revision_digest
        )
        or (request.identity.contribution_id != receipt.policy.contribution_id)
        or (
            request.identity.owner_generation
            != receipt.policy.owner_selection_generation
        )
        or (
            request.identity.declaration_fingerprint
            != receipt.policy.declaration_fingerprint
        )
        or (
            request.identity.worker_configuration_fingerprint
            != receipt.policy.worker_configuration_fingerprint
        )
        or (request.identity.attempt_id != payload_lease.attempt_id)
        or (request.identity.owner_id != payload_lease.owner_id)
        or (request.runtime != payload_lease.runtime)
        or (receipt.fingerprint != payload_lease.receipt_fingerprint)
        or (request.runtime.executable_digest != payload_lease.payload_digest)
        or (
            (request.runtime.cwd_device, request.runtime.cwd_inode)
            != payload_lease.stage_identity
        )
    ):
        raise CodingWindowsWorkerLaunchIntentError(
            "coding_worker_launch_intent_binding_mismatch"
        )
    intent = CodingWindowsWorkerLaunchIntentV1(
        attempt_id=payload_lease.attempt_id,
        stage_identity=payload_lease.stage_identity,
        receipt_fingerprint=receipt.fingerprint,
        request_fingerprint=request.fingerprint,
        identity_fingerprint=request.identity.fingerprint,
        runtime_fingerprint=request.runtime.fingerprint,
        payload_digest=payload_lease.payload_digest,
        owner_id=payload_lease.owner_id,
        supervisor_epoch=request.identity.supervisor_epoch,
    )
    return _intent_records(product).commit(
        receipt_owner=receipt_owner,
        receipt=receipt,
        request=request,
        payload_lease=payload_lease,
        intent=intent,
        require_bound=partial(
            _require_coding_windows_product_bound_request,
            receipt_owner=receipt_owner,
            receipt=receipt,
            payload_lease=payload_lease,
            request=request,
        ),
        verify_marker=partial(
            _verify_stage_marker,
            receipt_owner=receipt_owner,
            receipt=receipt,
            payload_lease=payload_lease,
            initial=True,
        ),
    )


def read_coding_windows_product_worker_launch_intent(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWindowsWorkerLaunchIntentV1 | None:
    """Read one committed intent without creating or repairing its receipt."""

    _require_product(product)
    _require_attempt(attempt_id)
    with product.gc_gate.read_guard():
        return _read_intent_under_gc_guard(product, attempt_id)


def inspect_coding_windows_product_worker_launch_intents(
    product: WindowsLocalWheelProductSessionOwner,
) -> tuple[CodingWindowsWorkerLaunchIntentV1, ...]:
    """Strictly inventory all committed intents and unpublished stages."""

    _require_product(product)
    with product.gc_gate.read_guard():
        return _inspect_intents_under_gc_guard(product)


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
    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise OSError("Windows Worker launch intent requires a Product owner")


def _require_attempt(attempt_id: str) -> None:
    if type(attempt_id) is not str or _ATTEMPT.fullmatch(attempt_id) is None:
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
