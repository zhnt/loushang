"""Receipt-backed retirement of a settled, never-launched Windows Worker stage."""

from __future__ import annotations

import os
from pathlib import Path

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    windows_listdir_at,
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
from .package_product_worker_windows_reserved_review import (
    CodingWindowsWorkerReservedNoEffectReviewV1,
    _capture_reserved_stage,
)
from .package_product_worker_windows_stage_retirement import (
    CodingWindowsWorkerStageRetirementReceiptV1,
    _close_opened,
    _delete_directory_if_empty,
    _delete_file_if_present,
    _open_existing_parent,
    _require_remaining_subset,
    _stage_exists,
)
from .package_product_worker_windows_stage_review import _require_direct

_MAX_REVIEW_BYTES = 32768
_MAX_RECEIPT_BYTES = 1024
_RETIRED_DEBTS = (
    "payload_missing",
    "launch_intent_retained",
    "supervisor_history_missing",
)


class CodingWindowsWorkerUnlaunchedRetirementError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def retire_coding_windows_product_worker_settled_unlaunched_stage(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWindowsWorkerReservedNoEffectReviewV1,
) -> CodingWindowsWorkerStageRetirementReceiptV1:
    """Delete only the reviewed payload after proving no native or process effect."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(expected_review) is not CodingWindowsWorkerReservedNoEffectReviewV1
        or expected_review.native_revision != 2
    ):
        raise OSError("Windows Worker unlaunched retirement requires a Product review")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise CodingWindowsWorkerUnlaunchedRetirementError(
                "coding_worker_unlaunched_retirement_runtime_active"
            )
        with product.gc_gate.guard():
            product.assert_root_gc_authority_current()
            with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
                with WindowsPrivateDirectoryAcl() as acl:
                    _require_direct(root, acl, directory=True)
                    if not os.path.samestat(os.fstat(root), product.state_root.lstat()):
                        raise CodingWindowsWorkerUnlaunchedRetirementError(
                            "coding_worker_unlaunched_retirement_root_changed"
                        )
                start = _read_start(product, expected_review.attempt_id)
                completed = _read_receipt(product, expected_review.attempt_id)
                if start is None:
                    if (
                        completed is not None
                        or _read_root_intent(product, expected_review.attempt_id)
                        is not None
                    ):
                        raise CodingWindowsWorkerUnlaunchedRetirementError(
                            "coding_worker_unlaunched_retirement_start_missing"
                        )
                    _require_history(product, expected_review, stage_present=True)
                    intent = _require_intent(product, expected_review)
                    current = _capture_reserved_stage(
                        product,
                        intent=intent,
                        native_revision=2,
                        lease_owner_revision=quiescence.owner_revision,
                    )
                    if current != expected_review:
                        raise CodingWindowsWorkerUnlaunchedRetirementError(
                            "coding_worker_unlaunched_retirement_review_stale"
                        )
                    write_windows_private_receipt(
                        _start_path(product, start_id=expected_review.attempt_id),
                        expected_review.to_bytes(),
                        maximum_bytes=_MAX_REVIEW_BYTES,
                    )
                    start = _read_start(product, expected_review.attempt_id)
                if start != expected_review:
                    raise CodingWindowsWorkerUnlaunchedRetirementError(
                        "coding_worker_unlaunched_retirement_review_stale"
                    )
                receipt = CodingWindowsWorkerStageRetirementReceiptV1(
                    attempt_id=start.attempt_id,
                    review_fingerprint=start.fingerprint,
                    stage_identity=start.stage_identity[:2],
                )
                root_intent = _read_root_intent(product, start.attempt_id)
                if root_intent is not None and root_intent != receipt:
                    raise CodingWindowsWorkerUnlaunchedRetirementError(
                        "coding_worker_unlaunched_retirement_root_intent_changed"
                    )
                stage_present = _stage_exists(root, start.attempt_id)
                _require_history(product, start, stage_present=stage_present)
                intent = _require_intent(product, start)
                if completed is not None:
                    if completed != receipt or root_intent != receipt or stage_present:
                        raise CodingWindowsWorkerUnlaunchedRetirementError(
                            "coding_worker_unlaunched_retirement_completed_changed"
                        )
                    return completed
                if not stage_present and root_intent is None:
                    raise CodingWindowsWorkerUnlaunchedRetirementError(
                        "coding_worker_unlaunched_retirement_stage_disappeared"
                    )
                _remove_remaining_stage(product, root, start, intent, receipt)
                if _stage_exists(root, start.attempt_id):
                    raise CodingWindowsWorkerUnlaunchedRetirementError(
                        "coding_worker_unlaunched_retirement_stage_retained"
                    )
                write_windows_private_receipt(
                    _receipt_path(product, start.attempt_id),
                    receipt.to_bytes(),
                    maximum_bytes=_MAX_RECEIPT_BYTES,
                )
                if _read_receipt(product, start.attempt_id) != receipt:
                    raise CodingWindowsWorkerUnlaunchedRetirementError(
                        "coding_worker_unlaunched_retirement_publication_changed"
                    )
                product.assert_root_gc_authority_current()
                return receipt


def _require_history(
    product: WindowsLocalWheelProductSessionOwner,
    review: CodingWindowsWorkerReservedNoEffectReviewV1,
    *,
    stage_present: bool,
) -> None:
    inventory = _inspect_windows_worker_recovery_inventory_under_gc_guard(product)
    matches = tuple(item for item in inventory if item.attempt_id == review.attempt_id)
    intent = _require_intent(product, review)
    if (
        len(matches) != 1
        or matches[0].native_phase != "settled"
        or matches[0].native_revision != 2
        or matches[0].native_phase_history != ("reserved", "settled")
        or matches[0].native_witness_present_history != (False, False)
        or matches[0].supervisor_phase is not None
        or matches[0].supervisor_revision is not None
        or matches[0].supervisor_process_settled is not None
        or matches[0].supervisor_identity_fingerprint is not None
        or matches[0].observed_debts
        != (
            (
                "payload_retained",
                "launch_intent_retained",
                "supervisor_history_missing",
            )
            if stage_present
            else _RETIRED_DEBTS
        )
        or (
            stage_present
            and matches[0].payload_directory_identity != review.stage_identity[:2]
        )
        or matches[0].native_worker_request_fingerprint != intent.request_fingerprint
        or matches[0].native_receipt_fingerprint != intent.receipt_fingerprint
        or matches[0].launch_request_fingerprint != intent.request_fingerprint
        or matches[0].launch_receipt_fingerprint != intent.receipt_fingerprint
        or matches[0].launch_identity_fingerprint != intent.identity_fingerprint
        or matches[0].launch_stage_identity != intent.stage_identity
        or _other_retirement_artifact_present(product, review.attempt_id)
    ):
        raise CodingWindowsWorkerUnlaunchedRetirementError(
            "coding_worker_unlaunched_retirement_history_changed"
        )


def _require_completed_unlaunched_retirement_under_gc_guard(
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
        or attempt.native_phase != "settled"
        or attempt.native_revision != 2
        or attempt.native_phase_history != ("reserved", "settled")
        or attempt.native_witness_present_history != (False, False)
        or attempt.supervisor_phase is not None
        or attempt.supervisor_revision is not None
        or attempt.supervisor_process_settled is not None
        or attempt.supervisor_identity_fingerprint is not None
        or _other_retirement_artifact_present(product, attempt.attempt_id)
    ):
        raise CodingWindowsWorkerUnlaunchedRetirementError(
            "coding_worker_unlaunched_retirement_history_unverified"
        )
    intent = _require_intent(product, review)
    if (
        intent.stage_identity != completed.stage_identity
        or attempt.native_worker_request_fingerprint != intent.request_fingerprint
        or attempt.native_receipt_fingerprint != intent.receipt_fingerprint
        or attempt.launch_request_fingerprint != intent.request_fingerprint
        or attempt.launch_receipt_fingerprint != intent.receipt_fingerprint
        or attempt.launch_identity_fingerprint != intent.identity_fingerprint
        or attempt.launch_stage_identity != intent.stage_identity
    ):
        raise CodingWindowsWorkerUnlaunchedRetirementError(
            "coding_worker_unlaunched_retirement_history_unverified"
        )


def _require_intent(
    product: WindowsLocalWheelProductSessionOwner,
    review: CodingWindowsWorkerReservedNoEffectReviewV1,
) -> CodingWindowsWorkerLaunchIntentV1:
    intent = _read_intent_under_gc_guard(product, review.attempt_id)
    if intent is None or intent.fingerprint != review.intent_fingerprint:
        raise CodingWindowsWorkerUnlaunchedRetirementError(
            "coding_worker_unlaunched_retirement_intent_changed"
        )
    return intent


def _remove_remaining_stage(
    product: WindowsLocalWheelProductSessionOwner,
    root: int,
    review: CodingWindowsWorkerReservedNoEffectReviewV1,
    intent: CodingWindowsWorkerLaunchIntentV1,
    receipt: CodingWindowsWorkerStageRetirementReceiptV1,
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
                parent = _open_existing_parent(stage, parts[: depth - 1], review, acl)
                if parent is None:
                    continue
                descriptor, opened = parent
                try:
                    _delete_directory_if_empty(
                        descriptor,
                        parts[depth - 1],
                        review.directory_identities[depth - 1][1],
                        acl,
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
                raise CodingWindowsWorkerUnlaunchedRetirementError(
                    "coding_worker_unlaunched_retirement_extra_member"
                )
            if _read_root_intent(product, review.attempt_id) is None:
                write_windows_private_receipt(
                    _root_intent_path(product, review.attempt_id),
                    receipt.to_bytes(),
                    maximum_bytes=_MAX_RECEIPT_BYTES,
                )
            if _read_root_intent(product, review.attempt_id) != receipt:
                raise CodingWindowsWorkerUnlaunchedRetirementError(
                    "coding_worker_unlaunched_retirement_root_intent_changed"
                )
        finally:
            os.close(stage)
        _delete_directory_if_empty(root, stage_name, review.stage_identity, acl)


def _other_retirement_artifact_present(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str
) -> bool:
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        names = windows_listdir_at(root)
    return any(
        name.casefold().startswith(
            (
                f"worker-stage-retire-{attempt_id}.json",
                f"worker-stage-root-delete-{attempt_id}.json",
                f"worker-stage-retired-{attempt_id}.json",
                f"worker-partial-stage-retire-{attempt_id}.json",
                f"worker-partial-stage-root-delete-{attempt_id}.json",
                f"worker-partial-stage-retired-{attempt_id}.json",
                f"worker-crash-stage-retire-{attempt_id}.json",
                f"worker-crash-stage-root-delete-{attempt_id}.json",
                f"worker-crash-stage-retired-{attempt_id}.json",
            )
        )
        for name in names
    )


def _read_start(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str
) -> CodingWindowsWorkerReservedNoEffectReviewV1 | None:
    raw = read_windows_private_receipt(
        _start_path(product, start_id=attempt_id),
        maximum_bytes=_MAX_REVIEW_BYTES,
        allow_unpublished_stage=True,
    )
    review = (
        None
        if raw is None
        else CodingWindowsWorkerReservedNoEffectReviewV1.from_bytes(raw)
    )
    if review is not None and (
        review.attempt_id != attempt_id or review.native_revision != 2
    ):
        raise CodingWindowsWorkerUnlaunchedRetirementError(
            "coding_worker_unlaunched_retirement_start_invalid"
        )
    return review


def _read_receipt(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str
) -> CodingWindowsWorkerStageRetirementReceiptV1 | None:
    return _read_retirement_receipt(
        product, _receipt_path(product, attempt_id), attempt_id
    )


def _read_root_intent(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str
) -> CodingWindowsWorkerStageRetirementReceiptV1 | None:
    return _read_retirement_receipt(
        product, _root_intent_path(product, attempt_id), attempt_id
    )


def _read_retirement_receipt(
    product: WindowsLocalWheelProductSessionOwner,
    path: Path,
    attempt_id: str,
) -> CodingWindowsWorkerStageRetirementReceiptV1 | None:
    raw = read_windows_private_receipt(
        path, maximum_bytes=_MAX_RECEIPT_BYTES, allow_unpublished_stage=True
    )
    receipt = (
        None
        if raw is None
        else CodingWindowsWorkerStageRetirementReceiptV1.from_bytes(raw)
    )
    if receipt is not None and receipt.attempt_id != attempt_id:
        raise CodingWindowsWorkerUnlaunchedRetirementError(
            "coding_worker_unlaunched_retirement_receipt_invalid"
        )
    return receipt


def _start_path(product: WindowsLocalWheelProductSessionOwner, *, start_id: str):
    return product.state_root / f"worker-unlaunched-stage-retire-{start_id}.json"


def _receipt_path(product: WindowsLocalWheelProductSessionOwner, attempt_id: str):
    return product.state_root / f"worker-unlaunched-stage-retired-{attempt_id}.json"


def _root_intent_path(product: WindowsLocalWheelProductSessionOwner, attempt_id: str):
    return product.state_root / f"worker-unlaunched-stage-root-delete-{attempt_id}.json"


__all__ = [
    "CodingWindowsWorkerUnlaunchedRetirementError",
    "retire_coding_windows_product_worker_settled_unlaunched_stage",
]
