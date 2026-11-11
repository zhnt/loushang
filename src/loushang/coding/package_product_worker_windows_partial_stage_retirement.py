"""Receipt-backed offline retirement for an unlaunched Windows Worker stage."""

from __future__ import annotations

import os

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    windows_listdir_at,
)
from loushang.harness.worker.payload._windows_stage_retirement import (
    PartialWindowsStageRetirement,
)

from .package_legacy_windows_receipt import (
    write_windows_private_receipt,
)
from .package_product_worker_windows_partial_stage_review import (
    _PARTIAL_DEBTS,
    CodingWindowsWorkerPartialStageReviewV1,
    _review_partial_tree,
)
from .package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAttemptV1,
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
)
from .package_product_worker_windows_stage_retirement import (
    CodingWindowsWorkerStageRetirementReceiptV1,
    WindowsWorkerRetirementRecords,
    _has_other_retirement_artifact,
    _read_retirement_bytes,
    _retirement,
    _stage_exists,
)
from .package_product_worker_windows_stage_review import (
    _require_retirement_root,
)

_MAX_REVIEW_BYTES = 32768
_MAX_RECEIPT_BYTES = 1024
_RETIRED_DEBTS = (
    "payload_missing",
    "launch_intent_missing",
    "native_history_missing",
    "supervisor_history_missing",
)


class CodingWindowsWorkerPartialStageRetirementError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def retire_coding_windows_product_worker_partial_stage(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWindowsWorkerPartialStageReviewV1,
) -> CodingWindowsWorkerStageRetirementReceiptV1:
    """Delete only saved members after verifying no launch ever committed."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(expected_review) is not CodingWindowsWorkerPartialStageReviewV1
    ):
        raise OSError("Windows Worker partial retirement requires a Product review")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise CodingWindowsWorkerPartialStageRetirementError(
                "coding_worker_partial_retirement_runtime_active"
            )
        with product.gc_gate.guard(require_write=True):
            product.assert_root_gc_authority_current()
            with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
                _require_retirement_root(
                    product,
                    root,
                    CodingWindowsWorkerPartialStageRetirementError,
                    "coding_worker_partial_retirement_root_changed",
                )
                start = _read_start(product, expected_review.attempt_id)
                completed = _read_receipt(product, expected_review.attempt_id)
                if start is None:
                    if completed is not None:
                        raise CodingWindowsWorkerPartialStageRetirementError(
                            "coding_worker_partial_retirement_start_missing"
                        )
                    _require_partial_history(
                        product, expected_review, stage_present=True
                    )
                    current = _review_partial_tree(
                        product,
                        attempt_id=expected_review.attempt_id,
                        expected_stage=expected_review.stage_identity[:2],
                        lease_owner_revision=quiescence.owner_revision,
                    )
                    if current != expected_review:
                        raise CodingWindowsWorkerPartialStageRetirementError(
                            "coding_worker_partial_retirement_review_stale"
                        )
                    write_windows_private_receipt(
                        _start_path(product, expected_review.attempt_id),
                        expected_review.to_bytes(),
                        maximum_bytes=_MAX_REVIEW_BYTES,
                    )
                    start = _read_start(product, expected_review.attempt_id)
                if start != expected_review:
                    raise CodingWindowsWorkerPartialStageRetirementError(
                        "coding_worker_partial_retirement_review_stale"
                    )
                receipt = CodingWindowsWorkerStageRetirementReceiptV1(
                    attempt_id=start.attempt_id,
                    review_fingerprint=start.fingerprint,
                    stage_identity=start.stage_identity[:2],
                )
                root_intent = _read_root_intent(product, start.attempt_id)
                if root_intent is not None and root_intent != receipt:
                    raise CodingWindowsWorkerPartialStageRetirementError(
                        "coding_worker_partial_retirement_root_intent_changed"
                    )
                stage_present = _stage_exists(root, start.attempt_id)
                _require_partial_history(product, start, stage_present=stage_present)
                if completed is not None:
                    if completed != receipt or root_intent != receipt or stage_present:
                        raise CodingWindowsWorkerPartialStageRetirementError(
                            "coding_worker_partial_retirement_completed_changed"
                        )
                    return completed
                if not stage_present and root_intent is None:
                    raise CodingWindowsWorkerPartialStageRetirementError(
                        "coding_worker_partial_retirement_stage_disappeared"
                    )
                _remove_remaining_stage(product, root, start, receipt)
                if _stage_exists(root, start.attempt_id):
                    raise CodingWindowsWorkerPartialStageRetirementError(
                        "coding_worker_partial_retirement_stage_retained"
                    )
                _records.publish_receipt(
                    product,
                    start,
                    receipt,
                    write=write_windows_private_receipt,
                    read=_read_receipt,
                    changed_message="coding_worker_partial_retirement_publication_changed",
                )
                return receipt


def _require_partial_history(
    product: WindowsLocalWheelProductSessionOwner,
    review: CodingWindowsWorkerPartialStageReviewV1,
    *,
    stage_present: bool,
) -> None:
    inventory = _inspect_windows_worker_recovery_inventory_under_gc_guard(product)
    matches = tuple(item for item in inventory if item.attempt_id == review.attempt_id)
    expected_debts = _PARTIAL_DEBTS if stage_present else _RETIRED_DEBTS
    if (
        len(matches) != 1
        or matches[0].observed_debts != expected_debts
        or (
            stage_present
            and matches[0].payload_directory_identity != review.stage_identity[:2]
        )
        or _full_retirement_artifact_present(product, review.attempt_id)
    ):
        raise CodingWindowsWorkerPartialStageRetirementError(
            "coding_worker_partial_retirement_history_changed"
        )


def _require_completed_partial_retirement_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    attempt: CodingWindowsWorkerRecoveryAttemptV1,
) -> None:
    review = _read_start(product, attempt.attempt_id)
    completed = _read_receipt(product, attempt.attempt_id)
    root_intent = _read_root_intent(product, attempt.attempt_id)
    if (
        review is None
        or completed is None
        or root_intent is None
        or completed != root_intent
        or completed.review_fingerprint != review.fingerprint
        or completed.stage_identity != review.stage_identity[:2]
        or attempt.observed_debts != _RETIRED_DEBTS
        or _full_retirement_artifact_present(product, attempt.attempt_id)
    ):
        raise CodingWindowsWorkerPartialStageRetirementError(
            "coding_worker_partial_retirement_history_unverified"
        )


def _remove_remaining_stage(
    product: WindowsLocalWheelProductSessionOwner,
    root: int,
    review: CodingWindowsWorkerPartialStageReviewV1,
    receipt: CodingWindowsWorkerStageRetirementReceiptV1,
) -> None:
    with PartialWindowsStageRetirement(
        _retirement(),
        CodingWindowsWorkerPartialStageRetirementError,
        "coding_worker_partial_retirement",
    ).partial(root, review) as stage:
        if stage is None:
            return
        if windows_listdir_at(stage):
            raise CodingWindowsWorkerPartialStageRetirementError(
                "coding_worker_partial_retirement_extra_member"
            )
        if _read_root_intent(product, review.attempt_id) is None:
            write_windows_private_receipt(
                _root_intent_path(product, review.attempt_id),
                receipt.to_bytes(),
                maximum_bytes=_MAX_RECEIPT_BYTES,
            )
        if _read_root_intent(product, review.attempt_id) != receipt:
            raise CodingWindowsWorkerPartialStageRetirementError(
                "coding_worker_partial_retirement_root_intent_changed"
            )


def _full_retirement_artifact_present(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str
) -> bool:
    return _has_other_retirement_artifact(product, attempt_id, "worker-partial-stage")


_records = WindowsWorkerRetirementRecords(
    stem="worker-partial-stage",
    review_type=CodingWindowsWorkerPartialStageReviewV1,
    receipt_type=CodingWindowsWorkerStageRetirementReceiptV1,
    review_maximum_bytes=_MAX_REVIEW_BYTES,
    receipt_maximum_bytes=_MAX_RECEIPT_BYTES,
    read_bytes=_read_retirement_bytes,
    error_type=CodingWindowsWorkerPartialStageRetirementError,
    start_invalid="coding_worker_partial_retirement_start_invalid",
    root_intent_invalid="coding_worker_partial_retirement_receipt_invalid",
    receipt_invalid="coding_worker_partial_retirement_receipt_invalid",
)
_start_path = _records.start_path
_read_start = _records.read_start
_root_intent_path = _records.root_intent_path
_read_receipt = _records.read_receipt
_read_root_intent = _records.read_root_intent


__all__ = [
    "CodingWindowsWorkerPartialStageRetirementError",
    "retire_coding_windows_product_worker_partial_stage",
]
