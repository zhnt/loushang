"""Offline, receipt-backed retirement of a clean Windows Worker stage.

Only a complete stage with settled native provisioning and a clean Supervisor
stop is accepted. A durable exact review precedes every deletion. Interrupted
member deletion is resumed from that review and never broadens its file set.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from loushang.harness.package_product._worker_windows_attempt import (
    WindowsWorkerRetirementRecords,
    inspect_windows_product_worker_retirement_ids,
    list_windows_worker_state_root_names,
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
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    windows_listdir_at,
)
from loushang.harness.worker.history._base_codec import _BaseWireMethods, _unchanged
from loushang.harness.worker.history._windows_semantic_contracts import (
    launch_matches_intent,
    native_matches_intent,
)
from loushang.harness.worker.payload._windows_stage_retirement import (
    CompleteStageProof as _CompleteStageProof,
)
from loushang.harness.worker.payload._windows_stage_retirement import (
    WindowsStageRetirement,
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
    _inspection,
    _require_retirement_root,
    _review_complete_stage_under_gc_guard,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_RETIREMENT_STEMS = (
    "worker-stage",
    "worker-partial-stage",
    "worker-unlaunched-stage",
    "worker-crash-stage",
)
_RETIREMENT_NAME = re.compile(
    r"(?:worker-stage|worker-partial-stage|worker-unlaunched-stage|worker-crash-stage)-(?:retire|root-delete|retired)-"
    r"([0-9a-f]{32})\.json(?:\.stage)?\Z"
)
_RETIREMENT_NAME_PREFIXES = tuple(stem + "-" for stem in _RETIREMENT_STEMS)
_MAX_REVIEW_BYTES = 32768
_MAX_RECEIPT_BYTES = 1024
_READ_CHUNK = 1024 * 1024


class CodingWindowsWorkerStageRetirementError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerStageRetirementReceiptV1(_BaseWireMethods):
    _wire_label = "Worker stage retirement receipt"
    _wire_lists = ("stageIdentity",)
    _wire_error_type = CodingWindowsWorkerStageRetirementError
    _wire_error_code = "coding_worker_stage_retirement_receipt_invalid"
    _wire_invalid_encoding = "bytes changed"

    @classmethod
    def _wire_maximum(cls) -> int:
        return _MAX_RECEIPT_BYTES

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


CodingWindowsWorkerStageRetirementReceiptV1._wire_schema = RecordSchema.for_dataclass(
    CodingWindowsWorkerStageRetirementReceiptV1,
    _unchanged,
    RecordField("stage_identity", decoder=tuple),
)


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
        with product.gc_gate.guard(require_write=True):
            product.assert_root_gc_authority_current()
            with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
                _require_retirement_root(
                    product,
                    root,
                    CodingWindowsWorkerStageRetirementError,
                    "coding_worker_stage_retirement_root_changed",
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
                _records.publish_receipt(
                    product,
                    start,
                    receipt,
                    write=write_windows_private_receipt,
                    read=_read_receipt,
                    changed_message="coding_worker_stage_retirement_publication_changed",
                )
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
        or not launch_matches_intent(matches[0], intent)
        or not native_matches_intent(matches[0], intent)
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
        or not native_matches_intent(attempt, intent)
        or attempt.supervisor_identity_fingerprint != intent.identity_fingerprint
        or not launch_matches_intent(attempt, intent)
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
    with _retirement().complete(root, review, intent) as stage:
        if stage is None:
            return
        if windows_listdir_at(stage):
            raise CodingWindowsWorkerStageRetirementError(
                "coding_worker_stage_retirement_extra_member"
            )
        read_intent = read_root_delete_intent or (
            lambda: _read_root_delete_intent(product, review.attempt_id)
        )
        _records.ensure_root_delete_intent(
            receipt,
            path=lambda: (
                root_delete_intent_path
                or _root_delete_intent_path(product, review.attempt_id)
            ),
            read=read_intent,
            write=write_windows_private_receipt,
            changed_message="coding_worker_stage_retirement_root_intent_changed",
        )


def _stage_exists(root: int, attempt_id: str) -> bool:
    return "worker-payload-" + attempt_id in windows_listdir_at(root)


def _has_other_retirement_artifact(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str, excluded_stem: str
) -> bool:
    names = list_windows_worker_state_root_names(product)
    return any(
        name.casefold().startswith(
            tuple(
                f"{stem}-{phase}-{attempt_id}.json"
                for stem in _RETIREMENT_STEMS
                if stem != excluded_stem
                for phase in ("retire", "root-delete", "retired")
            )
        )
        for name in names
    )


def _partial_retirement_artifact_present(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str
) -> bool:
    return _has_other_retirement_artifact(product, attempt_id, "worker-stage")


def _inspect_retirement_attempt_ids_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
) -> frozenset[str]:
    return inspect_windows_product_worker_retirement_ids(
        product,
        inspect_names=_retirement_attempt_ids_from_names,
        inspection=_inspection,
        error_type=CodingWindowsWorkerStageRetirementError,
        error_prefix="coding_worker_stage_retirement",
    )


def _retirement_attempt_ids_from_names(names: tuple[str, ...]) -> frozenset[str]:
    attempts: set[str] = set()
    for name in names:
        if not name.casefold().startswith(_RETIREMENT_NAME_PREFIXES):
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


def _read_retirement_bytes(path: Path, maximum_bytes: int) -> bytes | None:
    return read_windows_private_receipt(
        path, maximum_bytes=maximum_bytes, allow_unpublished_stage=True
    )


_records = WindowsWorkerRetirementRecords(
    stem="worker-stage",
    review_type=CodingWindowsWorkerStageReviewV1,
    receipt_type=CodingWindowsWorkerStageRetirementReceiptV1,
    review_maximum_bytes=_MAX_REVIEW_BYTES,
    receipt_maximum_bytes=_MAX_RECEIPT_BYTES,
    read_bytes=_read_retirement_bytes,
    error_type=CodingWindowsWorkerStageRetirementError,
    start_invalid="coding_worker_stage_retirement_start_invalid",
    root_intent_invalid="coding_worker_stage_retirement_root_intent_invalid",
    receipt_invalid="coding_worker_stage_retirement_receipt_invalid",
)
_start_path = _records.start_path
_read_review = _records.read_start
_root_delete_intent_path = _records.root_intent_path
_read_receipt = _records.read_receipt
_read_root_delete_intent = _records.read_root_intent


__all__ = [
    "CodingWindowsWorkerStageRetirementError",
    "CodingWindowsWorkerStageRetirementReceiptV1",
    "retire_coding_windows_product_worker_complete_stage",
]


def _retirement() -> WindowsStageRetirement:
    return WindowsStageRetirement(
        _inspection(),
        CodingWindowsWorkerStageRetirementError,
        "coding_worker_stage_retirement",
    )
