"""Immutable Product custody linking a Windows Worker launch across owners.

The intent precedes native provisioning and process effects. It records only
pathless identities; a retained or unpublished intent is recovery debt, never
permission to launch or delete a payload.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    windows_listdir_at,
)
from loushang.harness.worker.contracts import ManagedWorkerLaunchRequestV1
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationReceiptV1,
)

from .package_legacy_windows_receipt import (
    read_windows_private_receipt,
    write_windows_private_receipt,
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
class CodingWindowsWorkerLaunchIntentV1:
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

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWindowsWorkerLaunchIntentV1:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_BYTES:
            raise CodingWindowsWorkerLaunchIntentError(
                "coding_worker_launch_intent_invalid"
            )
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "attemptId",
                    "identityFingerprint",
                    "intentVersion",
                    "ownerId",
                    "payloadDigest",
                    "receiptFingerprint",
                    "requestFingerprint",
                    "runtimeFingerprint",
                    "stageIdentity",
                    "supervisorEpoch",
                }
                or type(value["stageIdentity"]) is not list
            ):
                raise ValueError("Windows Worker launch intent fields changed")
            intent = cls(
                attempt_id=value["attemptId"],
                stage_identity=tuple(value["stageIdentity"]),
                receipt_fingerprint=value["receiptFingerprint"],
                request_fingerprint=value["requestFingerprint"],
                identity_fingerprint=value["identityFingerprint"],
                runtime_fingerprint=value["runtimeFingerprint"],
                payload_digest=value["payloadDigest"],
                owner_id=value["ownerId"],
                supervisor_epoch=value["supervisorEpoch"],
                intent_version=value["intentVersion"],
            )
            if intent.to_bytes() != raw:
                raise ValueError("Windows Worker launch intent encoding changed")
            return intent
        except (TypeError, ValueError, UnicodeError, KeyError) as exc:
            raise CodingWindowsWorkerLaunchIntentError(
                "coding_worker_launch_intent_invalid"
            ) from exc


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
        or type(request) is not ManagedWorkerLaunchRequestV1
        or type(payload_lease) is not CodingWindowsWorkerPayloadLeaseV1
        or request.identity.product_id != "coding"
        or receipt.policy.product_id != "coding"
        or request.identity.scope_id != receipt.policy.product_scope_id
        or request.identity.plugin_id != receipt.policy.plugin_id
        or request.identity.plugin_revision_digest
        != receipt.policy.plugin_revision_digest
        or request.identity.contribution_id != receipt.policy.contribution_id
        or request.identity.owner_generation
        != receipt.policy.owner_selection_generation
        or request.identity.declaration_fingerprint
        != receipt.policy.declaration_fingerprint
        or request.identity.worker_configuration_fingerprint
        != receipt.policy.worker_configuration_fingerprint
        or request.identity.attempt_id != payload_lease.attempt_id
        or request.identity.owner_id != payload_lease.owner_id
        or request.runtime != payload_lease.runtime
        or receipt.fingerprint != payload_lease.receipt_fingerprint
        or request.runtime.executable_digest != payload_lease.payload_digest
        or (request.runtime.cwd_device, request.runtime.cwd_inode)
        != payload_lease.stage_identity
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
    with product.gc_gate.guard(require_write=True):
        product.assert_root_gc_authority_current()
        _require_coding_windows_product_bound_request(
            receipt_owner=receipt_owner,
            receipt=receipt,
            payload_lease=payload_lease,
            request=request,
        )
        selected = receipt_owner.current_selected_payload(receipt)
        owner_id = receipt_owner.current_worker_owner_id(receipt)
        if (
            selected.digest != payload_lease.payload_digest
            or selected.configuration.fingerprint
            != request.runtime.worker_configuration_fingerprint
            or len(selected.body) != request.runtime.executable_size
            or owner_id != payload_lease.owner_id
        ):
            raise CodingWindowsWorkerLaunchIntentError(
                "coding_worker_launch_intent_selection_stale"
            )
        _verify_stage_marker(
            receipt_owner=receipt_owner,
            receipt=receipt,
            payload_lease=payload_lease,
            entrypoint=selected.configuration.entrypoint,
            initial=True,
        )
        request.runtime.verify()
        request.validate_current()
        existing = _read_intent_under_gc_guard(
            product, intent.attempt_id, allow_unpublished_stage=True
        )
        if existing is not None:
            raise CodingWindowsWorkerLaunchIntentError(
                "coding_worker_launch_intent_attempt_reused"
            )
        with product.epoch_runtime.borrow_product_state_root_descriptor():
            write_windows_private_receipt(
                _path(product, intent.attempt_id), intent.to_bytes()
            )
            if _read_intent_under_gc_guard(product, intent.attempt_id) != intent:
                raise CodingWindowsWorkerLaunchIntentError(
                    "coding_worker_launch_intent_publication_changed"
                )
        product.assert_root_gc_authority_current()
        return intent


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
    product.assert_root_gc_authority_current()
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        names = windows_listdir_at(root)
        prefixed = {name for name in names if name.casefold().startswith(_PREFIX)}
        histories = {name for name in prefixed if _NAME.fullmatch(name)}
        if prefixed != histories or len(histories) > _MAX_ATTEMPTS:
            raise CodingWindowsWorkerLaunchIntentError(
                "coding_worker_launch_intent_inventory_unsafe"
            )
        intents = []
        for name in sorted(histories):
            match = _NAME.fullmatch(name)
            assert match is not None
            intent = _read_intent_under_gc_guard(product, match.group(1))
            if intent is None:
                raise CodingWindowsWorkerLaunchIntentError(
                    "coding_worker_launch_intent_inventory_unsafe"
                )
            intents.append(intent)
        if set(windows_listdir_at(root)) != set(names):
            raise CodingWindowsWorkerLaunchIntentError(
                "coding_worker_launch_intent_inventory_changed"
            )
    product.assert_root_gc_authority_current()
    return tuple(intents)


def _read_intent_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    attempt_id: str,
    *,
    allow_unpublished_stage: bool = False,
) -> CodingWindowsWorkerLaunchIntentV1 | None:
    product.assert_root_gc_authority_current()
    with product.epoch_runtime.borrow_product_state_root_descriptor():
        raw = read_windows_private_receipt(
            _path(product, attempt_id),
            maximum_bytes=_MAX_BYTES,
            allow_unpublished_stage=allow_unpublished_stage,
        )
    intent = None if raw is None else CodingWindowsWorkerLaunchIntentV1.from_bytes(raw)
    if intent is not None and intent.attempt_id != attempt_id:
        raise CodingWindowsWorkerLaunchIntentError(
            "coding_worker_launch_intent_invalid"
        )
    product.assert_root_gc_authority_current()
    return intent


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
