"""Settle a reviewed Windows Worker reservation before any native effect.

The native bridge commits ``profile_effect`` before it invokes profile
creation. A retained revision-one ``reserved`` record therefore proves that
no native profile operation began, provided the exact Product attempt, launch
intent, payload, and absent Supervisor history still match. This operation
only advances that native journal; payload retirement is separate.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from .package_product_worker_windows_launch_intent import _read_intent_under_gc_guard
from .package_product_worker_windows_provisioning_journal import (
    WindowsWorkerProvisioningStateJournal,
    inspect_windows_worker_provisioning_attempts,
)
from .package_product_worker_windows_reserved_review import (
    CodingWindowsWorkerReservedNoEffectReviewV1,
    _review_reserved_under_gc_guard,
)
from .package_product_worker_windows_stage_review import _require_direct


class CodingWindowsWorkerReservedSettlementError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _settled_document(
    current: Mapping[str, object],
    *,
    expected_review: CodingWindowsWorkerReservedNoEffectReviewV1,
) -> dict[str, object]:
    if (
        type(current) is not dict
        or current.get("attemptId") != expected_review.attempt_id
        or current.get("phase") != "reserved"
        or type(current.get("stateRevision")) is not int
        or current["stateRevision"] != expected_review.native_revision
        or current.get("witness") is not None
    ):
        raise CodingWindowsWorkerReservedSettlementError(
            "coding_worker_reserved_settlement_history_changed"
        )
    return {**current, "phase": "settled", "stateRevision": 2, "witness": None}


def settle_coding_windows_product_worker_reserved_no_effect(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWindowsWorkerReservedNoEffectReviewV1,
) -> None:
    """Durably close an exact no-effect reservation under Product custody."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(expected_review) is not CodingWindowsWorkerReservedNoEffectReviewV1
    ):
        raise OSError("Windows Worker reserved settlement requires a Product review")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise CodingWindowsWorkerReservedSettlementError(
                "coding_worker_reserved_settlement_runtime_active"
            )
        with product.gc_gate.guard(require_write=True):
            product.assert_root_gc_authority_current()
            current_review = _review_reserved_under_gc_guard(
                product,
                attempt_id=expected_review.attempt_id,
                lease_owner_revision=quiescence.owner_revision,
            )
            if current_review != expected_review:
                raise CodingWindowsWorkerReservedSettlementError(
                    "coding_worker_reserved_settlement_review_stale"
                )
            intent = _read_intent_under_gc_guard(product, expected_review.attempt_id)
            if (
                intent is None
                or intent.fingerprint != expected_review.intent_fingerprint
            ):
                raise CodingWindowsWorkerReservedSettlementError(
                    "coding_worker_reserved_settlement_intent_changed"
                )
            with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
                with WindowsPrivateDirectoryAcl() as acl:
                    _require_direct(root, acl, directory=True)
                    if not os.path.samestat(os.fstat(root), product.state_root.lstat()):
                        raise CodingWindowsWorkerReservedSettlementError(
                            "coding_worker_reserved_settlement_root_changed"
                        )
                attempts = inspect_windows_worker_provisioning_attempts(
                    product.state_root, directory_fd=root
                )
                matches = tuple(
                    item
                    for item in attempts
                    if item.attempt_id == expected_review.attempt_id
                )
                if (
                    len(matches) != 1
                    or matches[0].phase != "reserved"
                    or matches[0].state_revision != 1
                    or matches[0].identity["workerRequestFingerprint"]
                    != intent.request_fingerprint
                    or matches[0].identity["receiptFingerprint"]
                    != intent.receipt_fingerprint
                ):
                    raise CodingWindowsWorkerReservedSettlementError(
                        "coding_worker_reserved_settlement_history_changed"
                    )
                journal = WindowsWorkerProvisioningStateJournal(
                    product.state_root
                    / f"worker-native-provisioning-{expected_review.attempt_id}.jsonl",
                    identity=matches[0].identity,
                )
                current = journal.load(directory_fd=root)
                if current is None:
                    raise CodingWindowsWorkerReservedSettlementError(
                        "coding_worker_reserved_settlement_history_changed"
                    )
                settled = _settled_document(current, expected_review=expected_review)
                if not journal.compare_and_swap(
                    expected_revision=1, document=settled, directory_fd=root
                ):
                    raise CodingWindowsWorkerReservedSettlementError(
                        "coding_worker_reserved_settlement_history_changed"
                    )
            product.assert_root_gc_authority_current()


__all__ = [
    "CodingWindowsWorkerReservedSettlementError",
    "settle_coding_windows_product_worker_reserved_no_effect",
]
