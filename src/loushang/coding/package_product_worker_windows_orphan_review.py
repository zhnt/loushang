"""Read-only Windows Product join for one crashed Worker runtime lease.

This review does not prove the original Job is empty or authorize a lease
repair, native cleanup, payload retirement, or another Worker launch.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeLeaseV1,
)
from loushang.hosting import observe_windows_worker_job_absent

from .package_product_worker_receipt import CodingWorkerReceiptRecordV1
from .package_product_worker_windows_receipt_journal import (
    CodingWindowsWorkerReceiptJournal,
)
from .package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAttemptV1,
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerOrphanRuntimeReviewV1:
    """Observed identities only; every writeback needs a fresh native proof."""

    attempt_id: str
    attempt: CodingWindowsWorkerRecoveryAttemptV1 | None
    receipt_record: CodingWorkerReceiptRecordV1 | None
    orphan_leases: tuple[PackageEpochRuntimeLeaseV1, ...]
    runtime_epoch: int
    store_root_identity: str
    native_job_absent: bool | None = None

    @property
    def clean_exit_repair_candidate(self) -> bool:
        """Only a fully settled, now-orphaned runtime can reach lease repair."""

        return (
            self.attempt is not None
            and self.attempt.attempt_id == self.attempt_id
            and self.attempt.clean_exit_settled
            and self.missing_proofs == ()
        )

    @property
    def missing_proofs(self) -> tuple[str, ...]:
        missing: list[str] = []
        attempt = self.attempt
        receipt = self.receipt_record
        if attempt is None:
            missing.append("attempt_history_absent")
        elif attempt.launch_receipt_fingerprint is None:
            missing.append("launch_intent_absent")
        if receipt is None:
            missing.append("activation_receipt_absent")
        elif (
            attempt is None
            or attempt.launch_receipt_fingerprint != receipt.receipt.fingerprint
            or (
                attempt.native_receipt_fingerprint is not None
                and attempt.native_receipt_fingerprint != receipt.receipt.fingerprint
            )
        ):
            missing.append("cross_owner_receipt_mismatch")
        if len(self.orphan_leases) != 1:
            missing.append(
                "orphan_lease_absent"
                if not self.orphan_leases
                else "orphan_lease_ambiguous"
            )
        elif (
            receipt is None
            or self.orphan_leases[0].runtime_id
            != receipt.receipt.policy.product_runtime_id
            or self.orphan_leases[0].runtime_epoch != self.runtime_epoch
            or self.orphan_leases[0].store_root_identity
            != self.store_root_identity
        ):
            missing.append("orphan_lease_identity_mismatch")
        if attempt is not None and attempt.native_job_name is not None:
            if self.native_job_absent is False:
                missing.append("native_job_present")
            elif self.native_job_absent is not True:
                missing.append("native_job_absence_unverified")
        else:
            missing.append("native_job_absence_unverified")
        return tuple(missing)


def review_coding_windows_product_worker_orphan_runtime(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWindowsWorkerOrphanRuntimeReviewV1:
    """Join strict persisted facts without creating or settling Worker state."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(attempt_id) is not str
        or _ATTEMPT.fullmatch(attempt_id) is None
    ):
        raise ValueError("Windows Worker orphan review requires an exact Product")
    registry = product.epoch_runtime.registry
    # Follow the Product lock order: Package registry before the GC read gate.
    orphans = registry.review_orphans(store_id=registry.store_id)
    with product.gc_gate.read_guard():
        return _review_under_gc_guard(product, attempt_id=attempt_id, orphans=orphans)


def repair_coding_windows_product_worker_clean_exit_orphan_runtime(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWindowsWorkerOrphanRuntimeReviewV1,
) -> PackageEpochRuntimeLeaseV1:
    """Repair only a fully settled Worker whose Product runtime died later."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(expected_review) is not CodingWindowsWorkerOrphanRuntimeReviewV1
    ):
        raise ValueError("Windows Worker clean-exit repair requires exact Product proof")
    if not expected_review.clean_exit_repair_candidate:
        raise ValueError("Windows Worker clean-exit repair is unproven")
    [expected_lease] = expected_review.orphan_leases
    registry = product.epoch_runtime.registry

    @contextmanager
    def validate_while_locked(
        lease: PackageEpochRuntimeLeaseV1,
    ) -> Iterator[None]:
        if lease != expected_lease:
            raise ValueError("Windows Worker orphan lease changed")
        with product.gc_gate.guard(require_write=True):
            current = _review_under_gc_guard(
                product, attempt_id=expected_review.attempt_id, orphans=(lease,)
            )
            if current != expected_review:
                raise ValueError("Windows Worker clean-exit review is stale")
            if not current.clean_exit_repair_candidate:
                raise ValueError("Windows Worker clean-exit repair is unproven")
            yield
            product.assert_root_gc_authority_current()

    registry.repair_orphan(expected_lease.lease_id, validation_guard=validate_while_locked)
    return expected_lease


def _review_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    orphans: tuple[PackageEpochRuntimeLeaseV1, ...],
) -> CodingWindowsWorkerOrphanRuntimeReviewV1:
    """Read Product facts with the caller's Package-before-GC lock order."""

    product.assert_root_gc_authority_current()
    attempts = _inspect_windows_worker_recovery_inventory_under_gc_guard(product)
    attempt = next((item for item in attempts if item.attempt_id == attempt_id), None)
    journal = CodingWindowsWorkerReceiptJournal(
        product.state_root / "worker-activation-receipts.jsonl",
        scope_id=product.policy.project_scope_id,
    )
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        receipts = journal.records(directory_fd=root)
    fingerprint = None if attempt is None else attempt.launch_receipt_fingerprint
    receipt = next(
        (
            item
            for item in receipts
            if fingerprint is not None and item.receipt.fingerprint == fingerprint
        ),
        None,
    )
    runtime_id = None if receipt is None else receipt.receipt.policy.product_runtime_id
    matching = (
        ()
        if runtime_id is None
        else tuple(item for item in orphans if item.runtime_id == runtime_id)
    )
    fence = product.epoch_runtime.cutover_result.fence
    if fence is None:
        raise ValueError("Windows Worker Product fence is unavailable")
    product.assert_root_gc_authority_current()
    return CodingWindowsWorkerOrphanRuntimeReviewV1(
        attempt_id=attempt_id,
        attempt=attempt,
        receipt_record=receipt,
        orphan_leases=matching,
        runtime_epoch=fence.epoch,
        store_root_identity=fence.fenced_root_identity,
        native_job_absent=(
            None
            if attempt is None or attempt.native_job_name is None
            else observe_windows_worker_job_absent(attempt.native_job_name)
        ),
    )


__all__ = [
    "CodingWindowsWorkerOrphanRuntimeReviewV1",
    "repair_coding_windows_product_worker_clean_exit_orphan_runtime",
    "review_coding_windows_product_worker_orphan_runtime",
]
