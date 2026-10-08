"""Receipt-backed deletion of a fully settled Windows Worker crash stage."""

from __future__ import annotations

import os

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsRuntimeQuiescenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    windows_listdir_at,
)

from .package_legacy_windows_receipt import (
    read_windows_private_receipt,
    write_windows_private_receipt,
)
from .package_product_worker_windows_crash_cleanup_review import (
    _valid_crash_native_settlement_history,
)
from .package_product_worker_windows_crash_stage_review import (
    CodingWindowsWorkerCrashStageReviewV1,
    _require_repair_record,
    _review_crash_stage_under_gc_guard,
)
from .package_product_worker_windows_launch_intent import _read_intent_under_gc_guard
from .package_product_worker_windows_orphan_review import _review_under_gc_guard
from .package_product_worker_windows_provisioning import (
    inspect_coding_windows_product_worker_provisioning_attempts,
)
from .package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAttemptV1,
)
from .package_product_worker_windows_stage_retirement import (
    CodingWindowsWorkerStageRetirementReceiptV1,
    _remove_remaining_stage,
    _stage_exists,
)
from .package_product_worker_windows_stage_review import _require_direct

_MAX_REVIEW_BYTES = 32768
_MAX_RECEIPT_BYTES = 1024


def retire_coding_windows_product_worker_crash_stage(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWindowsWorkerCrashStageReviewV1,
) -> CodingWindowsWorkerStageRetirementReceiptV1:
    """Recheck durable crash proof, then delete only reviewed stage members."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(expected_review) is not CodingWindowsWorkerCrashStageReviewV1
    ):
        raise ValueError("Windows Worker crash stage retirement requires exact Product")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError("Windows Worker crash stage has active leases")
        with product.gc_gate.guard():
            product.assert_root_gc_authority_current()
            with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
                with WindowsPrivateDirectoryAcl() as acl:
                    _require_direct(root, acl, directory=True)
                    if not os.path.samestat(os.fstat(root), product.state_root.lstat()):
                        raise ValueError("Windows Worker crash stage root changed")
                _require_no_other_retirement(product, expected_review.attempt_id)
                start = _read_start(product, expected_review.attempt_id)
                completed = _read_receipt(product, expected_review.attempt_id)
                root_intent = _read_root_intent(product, expected_review.attempt_id)
                if start is None:
                    if completed is not None or root_intent is not None:
                        raise ValueError("Windows Worker crash stage start is missing")
                    current = _review_crash_stage_under_gc_guard(
                        product,
                        attempt_id=expected_review.attempt_id,
                        quiescence=quiescence,
                    )
                    if current != expected_review:
                        raise ValueError("Windows Worker crash stage review is stale")
                    write_windows_private_receipt(
                        _start_path(product, expected_review.attempt_id),
                        expected_review.to_bytes(),
                        maximum_bytes=_MAX_REVIEW_BYTES,
                    )
                    start = _read_start(product, expected_review.attempt_id)
                if start != expected_review:
                    raise ValueError("Windows Worker crash stage review changed")
                assert start is not None
                receipt = CodingWindowsWorkerStageRetirementReceiptV1(
                    attempt_id=start.attempt_id,
                    review_fingerprint=start.fingerprint,
                    stage_identity=start.stage_identity[:2],
                )
                if root_intent is not None and root_intent != receipt:
                    raise ValueError("Windows Worker crash stage root intent changed")
                present = _stage_exists(root, start.attempt_id)
                _require_crash_history(
                    product, start, stage_present=present, quiescence=quiescence
                )
                if completed is not None:
                    if completed != receipt or root_intent != receipt or present:
                        raise ValueError("Windows Worker crash stage receipt changed")
                    return completed
                if not present and root_intent is None:
                    raise ValueError("Windows Worker crash stage disappeared")
                intent = _read_intent_under_gc_guard(product, start.attempt_id)
                if intent is None:
                    raise ValueError(
                        "Windows Worker crash stage launch intent is missing"
                    )
                _remove_remaining_stage(
                    product,
                    root,
                    start,
                    intent,
                    receipt,
                    root_delete_intent_path=_root_intent_path(
                        product, start.attempt_id
                    ),
                    read_root_delete_intent=lambda: _read_root_intent(
                        product, start.attempt_id
                    ),
                )
                if _stage_exists(root, start.attempt_id):
                    raise ValueError("Windows Worker crash stage remains")
                write_windows_private_receipt(
                    _receipt_path(product, start.attempt_id),
                    receipt.to_bytes(),
                    maximum_bytes=_MAX_RECEIPT_BYTES,
                )
                if _read_receipt(product, start.attempt_id) != receipt:
                    raise ValueError("Windows Worker crash stage receipt changed")
                product.assert_root_gc_authority_current()
                return receipt


def _require_crash_history(
    product: WindowsLocalWheelProductSessionOwner,
    review: CodingWindowsWorkerCrashStageReviewV1,
    *,
    stage_present: bool,
    quiescence: PackageWindowsRuntimeQuiescenceV1 | None = None,
) -> None:
    joined = _review_under_gc_guard(product, attempt_id=review.attempt_id, orphans=())
    attempt = joined.attempt
    receipt = joined.receipt_record
    intent = _read_intent_under_gc_guard(product, review.attempt_id)
    expected_debts = (
        "payload_retained" if stage_present else "payload_missing",
        "launch_intent_retained",
    ) + (
        ()
        if review.supervisor_revision is not None
        else ("supervisor_history_missing",)
    )
    if (
        joined.missing_proofs != ("orphan_lease_absent",)
        or attempt is None
        or receipt is None
        or intent is None
        or attempt.observed_debts != expected_debts
        or not _valid_crash_native_settlement_history(attempt)
        or attempt.native_revision != review.native_revision
        or attempt.supervisor_revision != review.supervisor_revision
        or (
            attempt.supervisor_phase != "process_settled"
            if review.supervisor_revision is not None
            else attempt.supervisor_phase is not None
        )
        or (
            review.supervisor_revision is not None
            and attempt.supervisor_process_settled is not True
        )
        or intent.fingerprint != review.intent_fingerprint
        or attempt.launch_request_fingerprint != intent.request_fingerprint
        or attempt.launch_receipt_fingerprint != intent.receipt_fingerprint
        or attempt.launch_identity_fingerprint != intent.identity_fingerprint
        or attempt.native_worker_request_fingerprint != intent.request_fingerprint
        or attempt.native_receipt_fingerprint != intent.receipt_fingerprint
        or (
            review.supervisor_revision is not None
            and attempt.supervisor_identity_fingerprint != intent.identity_fingerprint
        )
        or (
            stage_present
            and attempt.payload_directory_identity != review.stage_identity[:2]
        )
    ):
        raise ValueError("Windows Worker crash stage history changed")
    if quiescence is not None:
        _require_repair_record(
            quiescence,
            runtime_id=receipt.receipt.policy.product_runtime_id,
            expected=(review.repaired_lease_id, review.lease_repair_revision),
        )
    native = tuple(
        item
        for item in inspect_coding_windows_product_worker_provisioning_attempts(product)
        if item.attempt_id == review.attempt_id
    )
    if len(native) != 1:
        raise ValueError("Windows Worker crash stage native history changed")
    [provisioned] = native
    identity = provisioned.identity
    if (
        provisioned.phase != "settled"
        or provisioned.state_revision != review.native_revision
        or provisioned.phase_history != attempt.native_phase_history
        or provisioned.witness_present_history != attempt.native_witness_present_history
        or identity["specFingerprint"] != review.native_spec_fingerprint
        or identity["workerRequestFingerprint"] != intent.request_fingerprint
        or identity["receiptFingerprint"] != receipt.receipt.fingerprint
        or identity["jobObjectName"] != attempt.native_job_name
        or identity["nativeProfileId"] != receipt.receipt.policy.native_profile_id
        or identity["nativeProfileCatalogRevision"]
        != receipt.receipt.policy.native_profile_catalog_revision
    ):
        raise ValueError("Windows Worker crash stage native identity changed")
    product.assert_root_gc_authority_current()


def _require_completed_crash_retirement_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    attempt: CodingWindowsWorkerRecoveryAttemptV1,
) -> None:
    review = _read_start(product, attempt.attempt_id)
    receipt = _read_receipt(product, attempt.attempt_id)
    root_intent = _read_root_intent(product, attempt.attempt_id)
    if (
        review is None
        or receipt is None
        or root_intent is None
        or receipt != root_intent
        or receipt.review_fingerprint != review.fingerprint
        or receipt.stage_identity != review.stage_identity[:2]
        or attempt.payload_directory_identity is not None
    ):
        raise ValueError("Windows Worker crash stage retirement is unverified")
    _require_no_other_retirement(product, attempt.attempt_id)
    _require_crash_history(product, review, stage_present=False)


def _require_no_other_retirement(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str
) -> None:
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        names = windows_listdir_at(root)
    if any(
        name.casefold().startswith(
            (
                f"worker-stage-retire-{attempt_id}.json",
                f"worker-stage-root-delete-{attempt_id}.json",
                f"worker-stage-retired-{attempt_id}.json",
                f"worker-partial-stage-retire-{attempt_id}.json",
                f"worker-partial-stage-root-delete-{attempt_id}.json",
                f"worker-partial-stage-retired-{attempt_id}.json",
                f"worker-unlaunched-stage-retire-{attempt_id}.json",
                f"worker-unlaunched-stage-root-delete-{attempt_id}.json",
                f"worker-unlaunched-stage-retired-{attempt_id}.json",
            )
        )
        for name in names
    ):
        raise ValueError("Windows Worker crash stage retirement conflicts")


def _read_start(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str
) -> CodingWindowsWorkerCrashStageReviewV1 | None:
    raw = read_windows_private_receipt(
        _start_path(product, attempt_id),
        maximum_bytes=_MAX_REVIEW_BYTES,
        allow_unpublished_stage=True,
    )
    review = (
        None if raw is None else CodingWindowsWorkerCrashStageReviewV1.from_bytes(raw)
    )
    if review is not None and review.attempt_id != attempt_id:
        raise ValueError("Windows Worker crash stage start changed")
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
        raise ValueError("Windows Worker crash stage receipt changed")
    return receipt


def _read_root_intent(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str
) -> CodingWindowsWorkerStageRetirementReceiptV1 | None:
    raw = read_windows_private_receipt(
        _root_intent_path(product, attempt_id),
        maximum_bytes=_MAX_RECEIPT_BYTES,
        allow_unpublished_stage=True,
    )
    receipt = (
        None
        if raw is None
        else CodingWindowsWorkerStageRetirementReceiptV1.from_bytes(raw)
    )
    if receipt is not None and receipt.attempt_id != attempt_id:
        raise ValueError("Windows Worker crash stage root intent changed")
    return receipt


def _start_path(product: WindowsLocalWheelProductSessionOwner, attempt_id: str):
    return product.state_root / f"worker-crash-stage-retire-{attempt_id}.json"


def _receipt_path(product: WindowsLocalWheelProductSessionOwner, attempt_id: str):
    return product.state_root / f"worker-crash-stage-retired-{attempt_id}.json"


def _root_intent_path(product: WindowsLocalWheelProductSessionOwner, attempt_id: str):
    return product.state_root / f"worker-crash-stage-root-delete-{attempt_id}.json"


__all__ = ["retire_coding_windows_product_worker_crash_stage"]
