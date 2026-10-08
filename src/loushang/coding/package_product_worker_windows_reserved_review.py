"""Offline proof that a Windows Worker reservation began no native effect.

The Product reads its pinned payload, launch intent, provisioning reservation,
and absence of Supervisor history together. This review has no settlement or
cleanup authority by itself.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    windows_listdir_at,
    windows_stat_at,
)
from loushang.harness.resources.plugins.locators import (
    canonical_plugin_relative_path,
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
    _identity,
    _read_checked_file,
    _require_direct,
    _valid_identity,
    _verify_marker,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
_MAX_REVIEW_BYTES = 32768
_RESERVED_DEBTS = (
    "payload_retained",
    "launch_intent_retained",
    "native_unsettled",
    "supervisor_history_missing",
)


class CodingWindowsWorkerReservedReviewError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerReservedNoEffectReviewV1:
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

    def __post_init__(self) -> None:
        try:
            path = canonical_plugin_relative_path(self.entrypoint)
        except ValueError as exc:
            raise ValueError("Windows Worker reserved entrypoint is invalid") from exc
        if (
            type(self.attempt_id) is not str
            or _ATTEMPT.fullmatch(self.attempt_id) is None
            or any(
                type(value) is not str or _DIGEST.fullmatch(value) is None
                for value in (self.intent_fingerprint, self.executable_digest)
            )
            or type(self.lease_owner_revision) is not int
            or self.lease_owner_revision < 1
            or type(self.native_revision) is not int
            or self.native_revision not in (1, 2)
            or path.as_posix() != self.entrypoint
            or not _valid_identity(self.stage_identity)
            or not _valid_identity(self.marker_identity)
            or not _valid_identity(self.executable_identity)
            or not 0 < self.executable_identity[3] <= _MAX_PAYLOAD_BYTES
            or type(self.directory_identities) is not tuple
            or len(self.directory_identities) != len(path.parts) - 1
            or any(
                type(member) is not tuple
                or len(member) != 2
                or member[0] != "/".join(path.parts[: index + 1])
                or not _valid_identity(member[1])
                for index, member in enumerate(self.directory_identities)
            )
        ):
            raise ValueError("Windows Worker reserved review is invalid")

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "attemptId": self.attempt_id,
                "directoryIdentities": [
                    [path, list(identity)]
                    for path, identity in self.directory_identities
                ],
                "entrypoint": self.entrypoint,
                "executableDigest": self.executable_digest,
                "executableIdentity": list(self.executable_identity),
                "intentFingerprint": self.intent_fingerprint,
                "leaseOwnerRevision": self.lease_owner_revision,
                "markerIdentity": list(self.marker_identity),
                "nativeRevision": self.native_revision,
                "stageIdentity": list(self.stage_identity),
                "version": 1,
            }
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWindowsWorkerReservedNoEffectReviewV1:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_REVIEW_BYTES:
            raise CodingWindowsWorkerReservedReviewError(
                "coding_worker_reserved_review_invalid"
            )
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "attemptId",
                    "directoryIdentities",
                    "entrypoint",
                    "executableDigest",
                    "executableIdentity",
                    "intentFingerprint",
                    "leaseOwnerRevision",
                    "markerIdentity",
                    "nativeRevision",
                    "stageIdentity",
                    "version",
                }
                or value["version"] != 1
            ):
                raise ValueError("Windows Worker reserved review fields changed")
            directories = value["directoryIdentities"]
            if (
                type(directories) is not list
                or any(
                    type(item) is not list
                    or len(item) != 2
                    or type(item[1]) is not list
                    for item in directories
                )
                or any(
                    type(value[name]) is not list
                    for name in (
                        "stageIdentity",
                        "markerIdentity",
                        "executableIdentity",
                    )
                )
            ):
                raise ValueError("Windows Worker reserved review identities changed")
            review = cls(
                attempt_id=value["attemptId"],
                intent_fingerprint=value["intentFingerprint"],
                lease_owner_revision=value["leaseOwnerRevision"],
                native_revision=value["nativeRevision"],
                stage_identity=tuple(value["stageIdentity"]),
                directory_identities=tuple(
                    (item[0], tuple(item[1])) for item in directories
                ),
                marker_identity=tuple(value["markerIdentity"]),
                executable_identity=tuple(value["executableIdentity"]),
                executable_digest=value["executableDigest"],
                entrypoint=value["entrypoint"],
            )
            if review.to_bytes() != raw:
                raise ValueError("Windows Worker reserved review encoding changed")
            return review
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise CodingWindowsWorkerReservedReviewError(
                "coding_worker_reserved_review_invalid"
            ) from exc

    @property
    def fingerprint(self) -> str:
        return sha256(
            b"loushang.coding-windows-worker-reserved-review/v1\0" + self.to_bytes()
        ).hexdigest()


def _require_reserved_no_effect_candidate(
    attempt: CodingWindowsWorkerRecoveryAttemptV1,
    intent: CodingWindowsWorkerLaunchIntentV1,
) -> None:
    if (
        type(attempt) is not CodingWindowsWorkerRecoveryAttemptV1
        or type(intent) is not CodingWindowsWorkerLaunchIntentV1
        or attempt.attempt_id != intent.attempt_id
        or attempt.observed_debts != _RESERVED_DEBTS
        or attempt.payload_directory_identity != intent.stage_identity
        or attempt.native_phase != "reserved"
        or attempt.native_revision != 1
        or attempt.native_phase_history != ("reserved",)
        or attempt.native_witness_present_history != (False,)
        or attempt.supervisor_phase is not None
        or attempt.supervisor_revision is not None
        or attempt.supervisor_process_settled is not None
        or attempt.supervisor_identity_fingerprint is not None
        or attempt.native_worker_request_fingerprint != intent.request_fingerprint
        or attempt.native_receipt_fingerprint != intent.receipt_fingerprint
        or attempt.launch_request_fingerprint != intent.request_fingerprint
        or attempt.launch_receipt_fingerprint != intent.receipt_fingerprint
        or attempt.launch_identity_fingerprint != intent.identity_fingerprint
        or attempt.launch_stage_identity != intent.stage_identity
    ):
        raise CodingWindowsWorkerReservedReviewError(
            "coding_worker_reserved_history_unverified"
        )


def _require_settled_no_effect_candidate(
    attempt: CodingWindowsWorkerRecoveryAttemptV1,
    intent: CodingWindowsWorkerLaunchIntentV1,
) -> None:
    if (
        type(attempt) is not CodingWindowsWorkerRecoveryAttemptV1
        or type(intent) is not CodingWindowsWorkerLaunchIntentV1
        or attempt.attempt_id != intent.attempt_id
        or attempt.observed_debts
        != ("payload_retained", "launch_intent_retained", "supervisor_history_missing")
        or attempt.payload_directory_identity != intent.stage_identity
        or attempt.native_phase != "settled"
        or attempt.native_revision != 2
        or attempt.native_phase_history != ("reserved", "settled")
        or attempt.native_witness_present_history != (False, False)
        or attempt.supervisor_phase is not None
        or attempt.supervisor_revision is not None
        or attempt.supervisor_process_settled is not None
        or attempt.supervisor_identity_fingerprint is not None
        or attempt.native_worker_request_fingerprint != intent.request_fingerprint
        or attempt.native_receipt_fingerprint != intent.receipt_fingerprint
        or attempt.launch_request_fingerprint != intent.request_fingerprint
        or attempt.launch_receipt_fingerprint != intent.receipt_fingerprint
        or attempt.launch_identity_fingerprint != intent.identity_fingerprint
        or attempt.launch_stage_identity != intent.stage_identity
    ):
        raise CodingWindowsWorkerReservedReviewError(
            "coding_worker_unlaunched_history_unverified"
        )


def review_coding_windows_product_worker_reserved_no_effect(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWindowsWorkerReservedNoEffectReviewV1:
    """Capture one exact Product stage while all Package runtimes are closed."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(attempt_id) is not str
        or _ATTEMPT.fullmatch(attempt_id) is None
    ):
        raise OSError("Windows Worker reserved review requires a Product owner")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise CodingWindowsWorkerReservedReviewError(
                "coding_worker_reserved_runtime_active"
            )
        with product.gc_gate.read_guard():
            return _review_reserved_under_gc_guard(
                product,
                attempt_id=attempt_id,
                lease_owner_revision=quiescence.owner_revision,
            )


def review_coding_windows_product_worker_settled_unlaunched(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWindowsWorkerReservedNoEffectReviewV1:
    """Capture a settled reservation with no Supervisor or native effect."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(attempt_id) is not str
        or _ATTEMPT.fullmatch(attempt_id) is None
    ):
        raise OSError("Windows Worker unlaunched review requires a Product owner")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise CodingWindowsWorkerReservedReviewError(
                "coding_worker_unlaunched_runtime_active"
            )
        with product.gc_gate.read_guard():
            return _review_settled_unlaunched_under_gc_guard(
                product,
                attempt_id=attempt_id,
                lease_owner_revision=quiescence.owner_revision,
            )


def _review_settled_unlaunched_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    lease_owner_revision: int,
) -> CodingWindowsWorkerReservedNoEffectReviewV1:
    product.assert_root_gc_authority_current()
    inventory = _inspect_windows_worker_recovery_inventory_under_gc_guard(product)
    matches = tuple(item for item in inventory if item.attempt_id == attempt_id)
    intent = _read_intent_under_gc_guard(product, attempt_id)
    if (
        len(matches) != 1
        or intent is None
        or attempt_id in _inspect_retirement_attempt_ids_under_gc_guard(product)
    ):
        raise CodingWindowsWorkerReservedReviewError(
            "coding_worker_unlaunched_history_unverified"
        )
    _require_settled_no_effect_candidate(matches[0], intent)
    review = _capture_reserved_stage(
        product,
        intent=intent,
        native_revision=matches[0].native_revision,
        lease_owner_revision=lease_owner_revision,
    )
    product.assert_root_gc_authority_current()
    return review


def _review_reserved_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    lease_owner_revision: int,
) -> CodingWindowsWorkerReservedNoEffectReviewV1:
    product.assert_root_gc_authority_current()
    inventory = _inspect_windows_worker_recovery_inventory_under_gc_guard(product)
    matches = tuple(item for item in inventory if item.attempt_id == attempt_id)
    intent = _read_intent_under_gc_guard(product, attempt_id)
    if (
        len(matches) != 1
        or intent is None
        or attempt_id in _inspect_retirement_attempt_ids_under_gc_guard(product)
    ):
        raise CodingWindowsWorkerReservedReviewError(
            "coding_worker_reserved_history_unverified"
        )
    _require_reserved_no_effect_candidate(matches[0], intent)
    review = _capture_reserved_stage(
        product,
        intent=intent,
        native_revision=matches[0].native_revision,
        lease_owner_revision=lease_owner_revision,
    )
    product.assert_root_gc_authority_current()
    return review


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
    stage_name = "worker-payload-" + intent.attempt_id
    with WindowsPrivateDirectoryAcl() as acl:
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            _require_direct(root, acl, directory=True)
            if not os.path.samestat(os.fstat(root), product.state_root.lstat()):
                raise CodingWindowsWorkerReservedReviewError(
                    "coding_worker_reserved_root_changed"
                )
            stage = open_windows_directory(
                stage_name, dir_fd=root, share_delete=False, read_control=True
            )
            try:
                stage_identity = _require_direct(stage, acl, directory=True)
                if (
                    stage_identity[:2] != intent.stage_identity
                    or _identity(windows_stat_at(root, stage_name)) != stage_identity
                ):
                    raise CodingWindowsWorkerReservedReviewError(
                        "coding_worker_reserved_stage_changed"
                    )
                raw_marker, marker_identity = _read_checked_file(
                    stage, "worker-payload.json", acl, maximum_bytes=1024
                )
                entrypoint, payload_size = _verify_marker(
                    raw_marker, intent=intent, stage_identity=intent.stage_identity
                )
                parts = entrypoint.split("/")
                if set(windows_listdir_at(stage)) != {
                    "worker-payload.json",
                    parts[0],
                }:
                    raise CodingWindowsWorkerReservedReviewError(
                        "coding_worker_reserved_tree_changed"
                    )
                current = stage
                opened: list[int] = []
                directories: list[tuple[str, FileIdentity]] = []
                try:
                    for index, name in enumerate(parts[:-1]):
                        child = open_windows_directory(
                            name,
                            dir_fd=current,
                            share_delete=False,
                            read_control=True,
                        )
                        opened.append(child)
                        identity = _require_direct(child, acl, directory=True)
                        if _identity(windows_stat_at(current, name)) != identity or set(
                            windows_listdir_at(child)
                        ) != {parts[index + 1]}:
                            raise CodingWindowsWorkerReservedReviewError(
                                "coding_worker_reserved_tree_changed"
                            )
                        directories.append(("/".join(parts[: index + 1]), identity))
                        current = child
                    executable, executable_identity = _read_checked_file(
                        current, parts[-1], acl, maximum_bytes=_MAX_PAYLOAD_BYTES
                    )
                    digest = sha256(executable).hexdigest()
                    if (
                        digest != intent.payload_digest
                        or len(executable) != payload_size
                    ):
                        raise CodingWindowsWorkerReservedReviewError(
                            "coding_worker_reserved_payload_changed"
                        )
                finally:
                    for child in reversed(opened):
                        os.close(child)
                if (
                    _identity(os.fstat(stage)) != stage_identity
                    or _identity(windows_stat_at(root, stage_name)) != stage_identity
                    or set(windows_listdir_at(stage))
                    != {"worker-payload.json", parts[0]}
                ):
                    raise CodingWindowsWorkerReservedReviewError(
                        "coding_worker_reserved_stage_changed"
                    )
                return CodingWindowsWorkerReservedNoEffectReviewV1(
                    attempt_id=intent.attempt_id,
                    intent_fingerprint=intent.fingerprint,
                    lease_owner_revision=lease_owner_revision,
                    native_revision=native_revision,
                    stage_identity=stage_identity,
                    directory_identities=tuple(directories),
                    marker_identity=marker_identity,
                    executable_identity=executable_identity,
                    executable_digest=digest,
                    entrypoint=entrypoint,
                )
            finally:
                os.close(stage)


__all__ = [
    "CodingWindowsWorkerReservedNoEffectReviewV1",
    "CodingWindowsWorkerReservedReviewError",
    "review_coding_windows_product_worker_reserved_no_effect",
    "review_coding_windows_product_worker_settled_unlaunched",
]
