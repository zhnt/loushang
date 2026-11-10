"""Offline, read-only review of a cleanly stopped Windows Worker payload.

This captures exact retained bytes and identities for a later retirement
transaction. It does not claim that deletion, Job recovery, or rotation has
occurred, and it grants no filesystem mutation authority by itself.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product._worker_windows_attempt import (
    CapturedWindowsWorkerStage as _CapturedStageBytesV1,
)
from loushang.harness.package_product._worker_windows_attempt import (
    capture_windows_product_worker_stage,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.plugins.locators import (
    canonical_plugin_relative_path,
)
from loushang.harness.worker.history._windows_stage_review_wire import (
    _WindowsStageReviewWireMethods,
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
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
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
class CodingWindowsWorkerStageReviewV1(_WindowsStageReviewWireMethods):
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

    def __post_init__(self) -> None:
        try:
            path = canonical_plugin_relative_path(self.entrypoint)
        except ValueError as exc:
            raise ValueError(
                "Windows Worker stage review entrypoint is invalid"
            ) from exc
        if (
            type(self.attempt_id) is not str
            or _ATTEMPT.fullmatch(self.attempt_id) is None
            or any(
                type(value) is not str or _DIGEST.fullmatch(value) is None
                for value in (self.intent_fingerprint, self.executable_digest)
            )
            or any(
                type(value) is not int or value < 1
                for value in (
                    self.lease_owner_revision,
                    self.native_revision,
                    self.supervisor_revision,
                )
            )
            or path.as_posix() != self.entrypoint
            or not _valid_identity(self.stage_identity)
            or not _valid_identity(self.marker_identity)
            or not _valid_identity(self.executable_identity)
            or self.executable_identity[3] < 1
            or self.executable_identity[3] > _MAX_PAYLOAD_BYTES
            or type(self.directory_identities) is not tuple
            or len(self.directory_identities) != len(path.parts) - 1
            or any(
                type(item) is not tuple
                or len(item) != 2
                or item[0] != "/".join(path.parts[: index + 1])
                or not _valid_identity(item[1])
                for index, item in enumerate(self.directory_identities)
            )
        ):
            raise ValueError("Windows Worker stage review is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptId": self.attempt_id,
            "directoryIdentities": [
                [path, list(identity)] for path, identity in self.directory_identities
            ],
            "entrypoint": self.entrypoint,
            "executableDigest": self.executable_digest,
            "executableIdentity": list(self.executable_identity),
            "intentFingerprint": self.intent_fingerprint,
            "leaseOwnerRevision": self.lease_owner_revision,
            "markerIdentity": list(self.marker_identity),
            "nativeRevision": self.native_revision,
            "stageIdentity": list(self.stage_identity),
            "supervisorRevision": self.supervisor_revision,
            "version": 1,
        }

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def fingerprint(self) -> str:
        return sha256(
            b"loushang.coding-windows-worker-stage-review/v1\0" + self.to_bytes()
        ).hexdigest()


def _valid_identity(value: object) -> bool:
    return (
        type(value) is tuple
        and len(value) == 5
        and all(type(item) is int and item >= 0 for item in value)
        and value[1] > 0
        and value[2] == 1
    )


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
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise CodingWindowsWorkerStageReviewError(
                "coding_worker_stage_review_runtime_active"
            )
        with product.gc_gate.read_guard():
            return _review_complete_stage_under_gc_guard(
                product,
                attempt_id=attempt_id,
                lease_owner_revision=quiescence.owner_revision,
            )


def _review_complete_stage_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    lease_owner_revision: int,
) -> CodingWindowsWorkerStageReviewV1:
    """Reuse an already-held offline Package lease and Product GC gate."""

    product.assert_root_gc_authority_current()
    inventory = _inspect_windows_worker_recovery_inventory_under_gc_guard(product)
    matches = tuple(item for item in inventory if item.attempt_id == attempt_id)
    if len(matches) != 1:
        raise CodingWindowsWorkerStageReviewError(
            "coding_worker_stage_review_attempt_unavailable"
        )
    attempt = matches[0]
    if (
        attempt.observed_debts != ("payload_retained", "launch_intent_retained")
        or attempt.native_phase != "settled"
        or attempt.supervisor_phase != "stopped"
        or attempt.native_revision is None
        or attempt.supervisor_revision is None
        or attempt.payload_directory_identity is None
    ):
        raise CodingWindowsWorkerStageReviewError(
            "coding_worker_stage_review_settlement_unverified"
        )
    intent = _read_intent_under_gc_guard(product, attempt_id)
    if intent is None:
        raise CodingWindowsWorkerStageReviewError(
            "coding_worker_stage_review_intent_missing"
        )
    review = _review_stage_bytes(
        product,
        attempt_id=attempt_id,
        expected_stage=attempt.payload_directory_identity,
        intent=intent,
        lease_owner_revision=lease_owner_revision,
        native_revision=attempt.native_revision,
        supervisor_revision=attempt.supervisor_revision,
    )
    product.assert_root_gc_authority_current()
    return review


def _review_stage_bytes(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    expected_stage: tuple[int, int],
    intent: CodingWindowsWorkerLaunchIntentV1,
    lease_owner_revision: int,
    native_revision: int,
    supervisor_revision: int,
) -> CodingWindowsWorkerStageReviewV1:
    captured = _capture_stage_bytes(
        product,
        attempt_id=attempt_id,
        expected_stage=expected_stage,
        intent=intent,
    )
    return CodingWindowsWorkerStageReviewV1(
        attempt_id=attempt_id,
        intent_fingerprint=intent.fingerprint,
        lease_owner_revision=lease_owner_revision,
        native_revision=native_revision,
        supervisor_revision=supervisor_revision,
        entrypoint=captured.entrypoint,
        stage_identity=captured.stage_identity,
        directory_identities=captured.directory_identities,
        marker_identity=captured.marker_identity,
        executable_identity=captured.executable_identity,
        executable_digest=captured.executable_digest,
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


def _require_direct(
    descriptor: int, acl: WindowsPrivateDirectoryAcl, *, directory: bool
) -> FileIdentity:
    return _inspection().require_direct(descriptor, acl, directory=directory)


CodingWindowsWorkerStageReviewV1._bind_record_schema()
