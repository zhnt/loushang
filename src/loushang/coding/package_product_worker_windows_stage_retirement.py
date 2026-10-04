"""Offline, receipt-backed retirement of a clean Windows Worker stage.

Only a complete stage with settled native provisioning and a clean Supervisor
stop is accepted. A durable exact review precedes every deletion. Interrupted
member deletion is resumed from that review and never broadens its file set.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_deletion_entry_at,
    open_windows_directory,
    windows_delete_open_entry,
    windows_flush_directory,
    windows_listdir_at,
    windows_stat_at,
)

from .package_legacy_windows_receipt import (
    read_windows_private_receipt,
    write_windows_private_receipt,
)
from .package_product_worker_windows_launch_intent import (
    CodingWindowsWorkerLaunchIntentV1,
    _read_intent_under_gc_guard,
)
from .package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAttemptV1,
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
)
from .package_product_worker_windows_stage_review import (
    CodingWindowsWorkerStageReviewV1,
    _read_checked_file,
    _require_direct,
    _review_complete_stage_under_gc_guard,
    _verify_marker,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_RETIREMENT_NAME = re.compile(
    r"(?:worker-stage|worker-partial-stage|worker-unlaunched-stage|worker-crash-stage)-(?:retire|root-delete|retired)-"
    r"([0-9a-f]{32})\.json(?:\.stage)?\Z"
)
_MAX_REVIEW_BYTES = 32768
_MAX_RECEIPT_BYTES = 1024
_READ_CHUNK = 1024 * 1024


class CodingWindowsWorkerStageRetirementError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _CompleteStageProof(Protocol):
    @property
    def attempt_id(self) -> str: ...

    @property
    def entrypoint(self) -> str: ...

    @property
    def stage_identity(self) -> tuple[int, int, int, int, int]: ...

    @property
    def directory_identities(
        self,
    ) -> tuple[tuple[str, tuple[int, int, int, int, int]], ...]: ...

    @property
    def marker_identity(self) -> tuple[int, int, int, int, int]: ...

    @property
    def executable_identity(self) -> tuple[int, int, int, int, int]: ...

    @property
    def executable_digest(self) -> str: ...


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerStageRetirementReceiptV1:
    attempt_id: str
    review_fingerprint: str
    stage_identity: tuple[int, int]
    receipt_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.attempt_id) is not str
            or _ATTEMPT.fullmatch(self.attempt_id) is None
            or type(self.review_fingerprint) is not str
            or _DIGEST.fullmatch(self.review_fingerprint) is None
            or type(self.stage_identity) is not tuple
            or len(self.stage_identity) != 2
            or any(type(value) is not int or value < 0 for value in self.stage_identity)
            or self.stage_identity[1] == 0
            or type(self.receipt_version) is not int
            or self.receipt_version != 1
        ):
            raise ValueError("Windows Worker stage retirement receipt is invalid")

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "attemptId": self.attempt_id,
                "receiptVersion": self.receipt_version,
                "reviewFingerprint": self.review_fingerprint,
                "stageIdentity": list(self.stage_identity),
            }
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWindowsWorkerStageRetirementReceiptV1:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_RECEIPT_BYTES:
            raise CodingWindowsWorkerStageRetirementError(
                "coding_worker_stage_retirement_receipt_invalid"
            )
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "attemptId",
                    "receiptVersion",
                    "reviewFingerprint",
                    "stageIdentity",
                }
                or type(value["stageIdentity"]) is not list
            ):
                raise ValueError("Worker stage retirement receipt fields changed")
            receipt = cls(
                attempt_id=value["attemptId"],
                review_fingerprint=value["reviewFingerprint"],
                stage_identity=tuple(value["stageIdentity"]),
                receipt_version=value["receiptVersion"],
            )
            if receipt.to_bytes() != raw:
                raise ValueError("Worker stage retirement receipt bytes changed")
            return receipt
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise CodingWindowsWorkerStageRetirementError(
                "coding_worker_stage_retirement_receipt_invalid"
            ) from exc


def retire_coding_windows_product_worker_complete_stage(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWindowsWorkerStageReviewV1,
) -> CodingWindowsWorkerStageRetirementReceiptV1:
    """Retire only the reviewed stage while Package runtime remains offline."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(expected_review) is not CodingWindowsWorkerStageReviewV1
    ):
        raise OSError("Windows Worker stage retirement requires a Product review")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise CodingWindowsWorkerStageRetirementError(
                "coding_worker_stage_retirement_runtime_active"
            )
        with product.gc_gate.guard():
            product.assert_root_gc_authority_current()
            with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
                with WindowsPrivateDirectoryAcl() as acl:
                    _require_direct(root, acl, directory=True)
                    if not os.path.samestat(os.fstat(root), product.state_root.lstat()):
                        raise CodingWindowsWorkerStageRetirementError(
                            "coding_worker_stage_retirement_root_changed"
                        )
                start = _read_review(product, expected_review.attempt_id)
                completed = _read_receipt(product, expected_review.attempt_id)
                if start is None:
                    if completed is not None:
                        raise CodingWindowsWorkerStageRetirementError(
                            "coding_worker_stage_retirement_start_missing"
                        )
                    current = _review_complete_stage_under_gc_guard(
                        product,
                        attempt_id=expected_review.attempt_id,
                        lease_owner_revision=quiescence.owner_revision,
                    )
                    if current != expected_review:
                        raise CodingWindowsWorkerStageRetirementError(
                            "coding_worker_stage_retirement_review_stale"
                        )
                    write_windows_private_receipt(
                        _start_path(product, expected_review.attempt_id),
                        expected_review.to_bytes(),
                        maximum_bytes=_MAX_REVIEW_BYTES,
                    )
                    start = _read_review(product, expected_review.attempt_id)
                if start != expected_review:
                    raise CodingWindowsWorkerStageRetirementError(
                        "coding_worker_stage_retirement_review_stale"
                    )
                _require_retirement_history(product, start)
                receipt = CodingWindowsWorkerStageRetirementReceiptV1(
                    attempt_id=start.attempt_id,
                    review_fingerprint=start.fingerprint,
                    stage_identity=start.stage_identity[:2],
                )
                root_delete_intent = _read_root_delete_intent(product, start.attempt_id)
                if root_delete_intent is not None and root_delete_intent != receipt:
                    raise CodingWindowsWorkerStageRetirementError(
                        "coding_worker_stage_retirement_root_intent_changed"
                    )
                if completed is not None:
                    if (
                        completed != receipt
                        or root_delete_intent != receipt
                        or _stage_exists(root, start.attempt_id)
                    ):
                        raise CodingWindowsWorkerStageRetirementError(
                            "coding_worker_stage_retirement_completed_changed"
                        )
                    return completed
                if (
                    not _stage_exists(root, start.attempt_id)
                    and root_delete_intent is None
                ):
                    raise CodingWindowsWorkerStageRetirementError(
                        "coding_worker_stage_retirement_stage_disappeared"
                    )
                intent = _read_intent_under_gc_guard(product, start.attempt_id)
                if intent is None:
                    raise CodingWindowsWorkerStageRetirementError(
                        "coding_worker_stage_retirement_intent_missing"
                    )
                _remove_remaining_stage(product, root, start, intent, receipt)
                if _stage_exists(root, start.attempt_id):
                    raise CodingWindowsWorkerStageRetirementError(
                        "coding_worker_stage_retirement_stage_retained"
                    )
                write_windows_private_receipt(
                    _receipt_path(product, start.attempt_id),
                    receipt.to_bytes(),
                    maximum_bytes=_MAX_RECEIPT_BYTES,
                )
                if _read_receipt(product, start.attempt_id) != receipt:
                    raise CodingWindowsWorkerStageRetirementError(
                        "coding_worker_stage_retirement_publication_changed"
                    )
                product.assert_root_gc_authority_current()
                return receipt


def _require_retirement_history(
    product: WindowsLocalWheelProductSessionOwner,
    review: CodingWindowsWorkerStageReviewV1,
) -> None:
    attempts = _inspect_windows_worker_recovery_inventory_under_gc_guard(product)
    matches = tuple(item for item in attempts if item.attempt_id == review.attempt_id)
    intent = _read_intent_under_gc_guard(product, review.attempt_id)
    if (
        len(matches) != 1
        or intent is None
        or intent.fingerprint != review.intent_fingerprint
        or matches[0].native_phase != "settled"
        or matches[0].supervisor_phase != "stopped"
        or matches[0].supervisor_process_settled is not True
        or matches[0].observed_debts
        not in (
            ("payload_retained", "launch_intent_retained"),
            ("payload_missing", "launch_intent_retained"),
        )
        or matches[0].native_revision != review.native_revision
        or matches[0].supervisor_revision != review.supervisor_revision
        or matches[0].launch_request_fingerprint != intent.request_fingerprint
        or matches[0].launch_receipt_fingerprint != intent.receipt_fingerprint
        or matches[0].launch_identity_fingerprint != intent.identity_fingerprint
        or matches[0].native_worker_request_fingerprint != intent.request_fingerprint
        or matches[0].native_receipt_fingerprint != intent.receipt_fingerprint
        or matches[0].supervisor_identity_fingerprint != intent.identity_fingerprint
        or _partial_retirement_artifact_present(product, review.attempt_id)
        or (
            matches[0].payload_directory_identity is not None
            and matches[0].payload_directory_identity != review.stage_identity[:2]
        )
    ):
        raise CodingWindowsWorkerStageRetirementError(
            "coding_worker_stage_retirement_history_changed"
        )


def _require_completed_retirement_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    attempt: CodingWindowsWorkerRecoveryAttemptV1,
) -> None:
    """Verify a historical attempt before excluding it from new admission."""

    review = _read_review(product, attempt.attempt_id)
    completed = _read_receipt(product, attempt.attempt_id)
    root_delete_intent = _read_root_delete_intent(product, attempt.attempt_id)
    intent = _read_intent_under_gc_guard(product, attempt.attempt_id)
    if (
        review is None
        or completed is None
        or root_delete_intent is None
        or intent is None
        or completed != root_delete_intent
        or completed.review_fingerprint != review.fingerprint
        or completed.stage_identity != review.stage_identity[:2]
        or intent.stage_identity != completed.stage_identity
        or intent.fingerprint != review.intent_fingerprint
        or attempt.observed_debts != ("payload_missing", "launch_intent_retained")
        or attempt.native_phase != "settled"
        or attempt.supervisor_phase != "stopped"
        or attempt.supervisor_process_settled is not True
        or attempt.native_revision != review.native_revision
        or attempt.supervisor_revision != review.supervisor_revision
        or attempt.native_worker_request_fingerprint != intent.request_fingerprint
        or attempt.native_receipt_fingerprint != intent.receipt_fingerprint
        or attempt.supervisor_identity_fingerprint != intent.identity_fingerprint
        or attempt.launch_request_fingerprint != intent.request_fingerprint
        or attempt.launch_receipt_fingerprint != intent.receipt_fingerprint
        or attempt.launch_identity_fingerprint != intent.identity_fingerprint
        or attempt.launch_stage_identity != intent.stage_identity
        or _partial_retirement_artifact_present(product, attempt.attempt_id)
    ):
        raise CodingWindowsWorkerStageRetirementError(
            "coding_worker_stage_retirement_history_unverified"
        )


def _remove_remaining_stage(
    product: WindowsLocalWheelProductSessionOwner,
    root: int,
    review: _CompleteStageProof,
    intent: CodingWindowsWorkerLaunchIntentV1,
    receipt: CodingWindowsWorkerStageRetirementReceiptV1,
    *,
    root_delete_intent_path: Path | None = None,
    read_root_delete_intent: Callable[
        [], CodingWindowsWorkerStageRetirementReceiptV1 | None
    ]
    | None = None,
) -> None:
    stage_name = "worker-payload-" + review.attempt_id
    with WindowsPrivateDirectoryAcl() as acl:
        _require_direct(root, acl, directory=True)
        try:
            stage = open_windows_directory(
                stage_name, dir_fd=root, share_delete=False, read_control=True
            )
        except FileNotFoundError:
            return
        try:
            _require_remaining_subset(stage, review, intent, acl)
            parts = review.entrypoint.split("/")
            parent = _open_existing_parent(stage, parts[:-1], review, acl)
            if parent is not None:
                descriptor, opened = parent
                try:
                    _delete_file_if_present(
                        descriptor,
                        parts[-1],
                        review.executable_identity,
                        review.executable_digest,
                        acl,
                    )
                finally:
                    _close_opened(opened)
            for depth in range(len(parts) - 1, 0, -1):
                prefix = parts[: depth - 1]
                parent = _open_existing_parent(stage, prefix, review, acl)
                if parent is None:
                    continue
                descriptor, opened = parent
                try:
                    identity = review.directory_identities[depth - 1][1]
                    _delete_directory_if_empty(
                        descriptor, parts[depth - 1], identity, acl
                    )
                finally:
                    _close_opened(opened)
            _delete_file_if_present(
                stage,
                "worker-payload.json",
                review.marker_identity,
                None,
                acl,
                intent=intent,
                stage_identity=review.stage_identity[:2],
                expected_entrypoint=review.entrypoint,
                expected_payload_size=review.executable_identity[3],
            )
            if windows_listdir_at(stage):
                raise CodingWindowsWorkerStageRetirementError(
                    "coding_worker_stage_retirement_extra_member"
                )
            read_intent = read_root_delete_intent or (
                lambda: _read_root_delete_intent(product, review.attempt_id)
            )
            if read_intent() is None:
                write_windows_private_receipt(
                    root_delete_intent_path
                    or _root_delete_intent_path(product, review.attempt_id),
                    receipt.to_bytes(),
                    maximum_bytes=_MAX_RECEIPT_BYTES,
                )
            if read_intent() != receipt:
                raise CodingWindowsWorkerStageRetirementError(
                    "coding_worker_stage_retirement_root_intent_changed"
                )
        finally:
            os.close(stage)
        _delete_directory_if_empty(root, stage_name, review.stage_identity, acl)


def _require_remaining_subset(
    stage: int,
    review: _CompleteStageProof,
    intent: CodingWindowsWorkerLaunchIntentV1,
    acl: WindowsPrivateDirectoryAcl,
) -> None:
    if _require_direct(stage, acl, directory=True)[:2] != review.stage_identity[:2]:
        raise CodingWindowsWorkerStageRetirementError(
            "coding_worker_stage_retirement_stage_changed"
        )
    parts = review.entrypoint.split("/")
    if not set(windows_listdir_at(stage)) <= {"worker-payload.json", parts[0]}:
        raise CodingWindowsWorkerStageRetirementError(
            "coding_worker_stage_retirement_extra_member"
        )
    if "worker-payload.json" in windows_listdir_at(stage):
        marker, identity = _read_checked_file(
            stage, "worker-payload.json", acl, maximum_bytes=1024
        )
        marker_entrypoint, payload_size = _verify_marker(
            marker, intent=intent, stage_identity=review.stage_identity[:2]
        )
        if (
            identity != review.marker_identity
            or marker_entrypoint != review.entrypoint
            or payload_size != review.executable_identity[3]
        ):
            raise CodingWindowsWorkerStageRetirementError(
                "coding_worker_stage_retirement_marker_changed"
            )
    current = stage
    opened: list[int] = []
    try:
        for index, name in enumerate(parts[:-1]):
            if name not in windows_listdir_at(current):
                return
            child = open_windows_directory(
                name, dir_fd=current, share_delete=False, read_control=True
            )
            opened.append(child)
            if (
                _require_direct(child, acl, directory=True)[:2]
                != review.directory_identities[index][1][:2]
            ):
                raise CodingWindowsWorkerStageRetirementError(
                    "coding_worker_stage_retirement_directory_changed"
                )
            if not set(windows_listdir_at(child)) <= {parts[index + 1]}:
                raise CodingWindowsWorkerStageRetirementError(
                    "coding_worker_stage_retirement_extra_member"
                )
            current = child
        if parts[-1] in windows_listdir_at(current):
            body, identity = _read_checked_file(
                current, parts[-1], acl, maximum_bytes=16 * 1024 * 1024
            )
            if (
                identity != review.executable_identity
                or sha256(body).hexdigest() != review.executable_digest
            ):
                raise CodingWindowsWorkerStageRetirementError(
                    "coding_worker_stage_retirement_payload_changed"
                )
        elif windows_listdir_at(current):
            raise CodingWindowsWorkerStageRetirementError(
                "coding_worker_stage_retirement_extra_member"
            )
    finally:
        _close_opened(opened)


def _open_existing_parent(
    stage: int,
    parts: list[str],
    review: _CompleteStageProof,
    acl: WindowsPrivateDirectoryAcl,
) -> tuple[int, list[int]] | None:
    current = stage
    opened: list[int] = []
    try:
        for index, name in enumerate(parts):
            if name not in windows_listdir_at(current):
                _close_opened(opened)
                return None
            child = open_windows_directory(
                name, dir_fd=current, share_delete=False, read_control=True
            )
            opened.append(child)
            if (
                _require_direct(child, acl, directory=True)[:2]
                != review.directory_identities[index][1][:2]
            ):
                raise CodingWindowsWorkerStageRetirementError(
                    "coding_worker_stage_retirement_directory_changed"
                )
            current = child
        return current, opened
    except BaseException:
        _close_opened(opened)
        raise


def _delete_file_if_present(
    parent: int,
    name: str,
    expected: tuple[int, int, int, int, int],
    digest: str | None,
    acl: WindowsPrivateDirectoryAcl,
    *,
    intent: CodingWindowsWorkerLaunchIntentV1 | None = None,
    stage_identity: tuple[int, int] | None = None,
    expected_entrypoint: str | None = None,
    expected_payload_size: int | None = None,
) -> None:
    if name not in windows_listdir_at(parent):
        return
    descriptor = open_windows_deletion_entry_at(parent, name, directory=False)
    try:
        if _require_direct(descriptor, acl, directory=False) != expected:
            raise CodingWindowsWorkerStageRetirementError(
                "coding_worker_stage_retirement_file_changed"
            )
        raw = _read_exact(descriptor, expected[3])
        if digest is None:
            if intent is None or stage_identity is None:
                raise CodingWindowsWorkerStageRetirementError(
                    "coding_worker_stage_retirement_marker_unbound"
                )
            entrypoint, payload_size = _verify_marker(
                raw, intent=intent, stage_identity=stage_identity
            )
            if (
                entrypoint != expected_entrypoint
                or payload_size != expected_payload_size
            ):
                raise CodingWindowsWorkerStageRetirementError(
                    "coding_worker_stage_retirement_marker_changed"
                )
        elif sha256(raw).hexdigest() != digest:
            raise CodingWindowsWorkerStageRetirementError(
                "coding_worker_stage_retirement_payload_changed"
            )
        if (
            _require_direct(descriptor, acl, directory=False) != expected
            or _file_identity_at(parent, name) != expected
        ):
            raise CodingWindowsWorkerStageRetirementError(
                "coding_worker_stage_retirement_file_changed"
            )
        windows_delete_open_entry(
            descriptor, expected_identity=expected, directory=False
        )
    finally:
        os.close(descriptor)
    windows_flush_directory(parent)


def _delete_directory_if_empty(
    parent: int,
    name: str,
    expected: tuple[int, int, int, int, int],
    acl: WindowsPrivateDirectoryAcl,
) -> None:
    if name not in windows_listdir_at(parent):
        return
    descriptor = open_windows_deletion_entry_at(parent, name, directory=True)
    try:
        current = _require_direct(descriptor, acl, directory=True)
        if (
            current[:2] != expected[:2]
            or _file_identity_at(parent, name) != current
            or windows_listdir_at(descriptor)
        ):
            raise CodingWindowsWorkerStageRetirementError(
                "coding_worker_stage_retirement_directory_changed"
            )
        windows_delete_open_entry(descriptor, expected_identity=current, directory=True)
    finally:
        os.close(descriptor)
    windows_flush_directory(parent)


def _read_exact(descriptor: int, size: int) -> bytes:
    raw = bytearray()
    while len(raw) <= size:
        chunk = os.read(descriptor, min(_READ_CHUNK, size + 1 - len(raw)))
        if not chunk:
            break
        raw.extend(chunk)
    if len(raw) != size:
        raise CodingWindowsWorkerStageRetirementError(
            "coding_worker_stage_retirement_file_changed"
        )
    return bytes(raw)


def _file_identity_at(parent: int, name: str) -> tuple[int, int, int, int, int]:
    metadata = windows_stat_at(parent, name)
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _stage_exists(root: int, attempt_id: str) -> bool:
    return "worker-payload-" + attempt_id in windows_listdir_at(root)


def _partial_retirement_artifact_present(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str
) -> bool:
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        names = windows_listdir_at(root)
    return any(
        name.casefold().startswith(
            (
                f"worker-partial-stage-retire-{attempt_id}.json",
                f"worker-partial-stage-root-delete-{attempt_id}.json",
                f"worker-partial-stage-retired-{attempt_id}.json",
                f"worker-unlaunched-stage-retire-{attempt_id}.json",
                f"worker-unlaunched-stage-root-delete-{attempt_id}.json",
                f"worker-unlaunched-stage-retired-{attempt_id}.json",
                f"worker-crash-stage-retire-{attempt_id}.json",
                f"worker-crash-stage-root-delete-{attempt_id}.json",
                f"worker-crash-stage-retired-{attempt_id}.json",
            )
        )
        for name in names
    )


def _inspect_retirement_attempt_ids_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
) -> frozenset[str]:
    product.assert_root_gc_authority_current()
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        with WindowsPrivateDirectoryAcl() as acl:
            _require_direct(root, acl, directory=True)
            if not os.path.samestat(os.fstat(root), product.state_root.lstat()):
                raise CodingWindowsWorkerStageRetirementError(
                    "coding_worker_stage_retirement_root_changed"
                )
            attempts = _retirement_attempt_ids_from_names(windows_listdir_at(root))
    product.assert_root_gc_authority_current()
    return attempts


def _retirement_attempt_ids_from_names(names: tuple[str, ...]) -> frozenset[str]:
    attempts: set[str] = set()
    for name in names:
        if not name.casefold().startswith(
            (
                "worker-stage-",
                "worker-partial-stage-",
                "worker-unlaunched-stage-",
                "worker-crash-stage-",
            )
        ):
            continue
        match = _RETIREMENT_NAME.fullmatch(name)
        if match is None:
            raise CodingWindowsWorkerStageRetirementError(
                "coding_worker_stage_retirement_artifact_invalid"
            )
        attempts.add(match.group(1))
        if len(attempts) > 1024:
            raise CodingWindowsWorkerStageRetirementError(
                "coding_worker_stage_retirement_capacity"
            )
    return frozenset(attempts)


def _close_opened(opened: list[int]) -> None:
    for descriptor in reversed(opened):
        os.close(descriptor)


def _read_review(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str
) -> CodingWindowsWorkerStageReviewV1 | None:
    raw = read_windows_private_receipt(
        _start_path(product, attempt_id),
        maximum_bytes=_MAX_REVIEW_BYTES,
        allow_unpublished_stage=True,
    )
    review = None if raw is None else CodingWindowsWorkerStageReviewV1.from_bytes(raw)
    if review is not None and review.attempt_id != attempt_id:
        raise CodingWindowsWorkerStageRetirementError(
            "coding_worker_stage_retirement_start_invalid"
        )
    return review


def _read_receipt(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str
) -> CodingWindowsWorkerStageRetirementReceiptV1 | None:
    raw = read_windows_private_receipt(
        _receipt_path(product, attempt_id),
        maximum_bytes=_MAX_RECEIPT_BYTES,
        allow_unpublished_stage=True,
    )
    receipt = (
        None
        if raw is None
        else CodingWindowsWorkerStageRetirementReceiptV1.from_bytes(raw)
    )
    if receipt is not None and receipt.attempt_id != attempt_id:
        raise CodingWindowsWorkerStageRetirementError(
            "coding_worker_stage_retirement_receipt_invalid"
        )
    return receipt


def _read_root_delete_intent(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str
) -> CodingWindowsWorkerStageRetirementReceiptV1 | None:
    raw = read_windows_private_receipt(
        _root_delete_intent_path(product, attempt_id),
        maximum_bytes=_MAX_RECEIPT_BYTES,
        allow_unpublished_stage=True,
    )
    receipt = (
        None
        if raw is None
        else CodingWindowsWorkerStageRetirementReceiptV1.from_bytes(raw)
    )
    if receipt is not None and receipt.attempt_id != attempt_id:
        raise CodingWindowsWorkerStageRetirementError(
            "coding_worker_stage_retirement_root_intent_invalid"
        )
    return receipt


def _start_path(product: WindowsLocalWheelProductSessionOwner, attempt_id: str):
    return product.state_root / f"worker-stage-retire-{attempt_id}.json"


def _receipt_path(product: WindowsLocalWheelProductSessionOwner, attempt_id: str):
    return product.state_root / f"worker-stage-retired-{attempt_id}.json"


def _root_delete_intent_path(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str
):
    return product.state_root / f"worker-stage-root-delete-{attempt_id}.json"


__all__ = [
    "CodingWindowsWorkerStageRetirementError",
    "CodingWindowsWorkerStageRetirementReceiptV1",
    "retire_coding_windows_product_worker_complete_stage",
]
