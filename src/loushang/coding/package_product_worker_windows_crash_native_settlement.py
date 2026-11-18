"""Product-guarded native cleanup for one orphaned Windows Worker attempt.

This settles only LPAC profile and grant debt. Supervisor, Package lease and
payload retirement remain separate Product decisions and cannot be inferred
from this native settlement alone.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from loushang.harness.package_product._worker_windows_attempt import (
    settle_windows_product_worker_native_cleanup,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from .package_product_worker_windows_crash_cleanup_review import (
    CodingWindowsWorkerCrashCleanupReviewV1,
    _crash_cleanup_history_matches,
)
from .package_product_worker_windows_installed_backend import (
    read_coding_windows_worker_installed_backend_release,
)
from .package_product_worker_windows_orphan_review import _review_under_gc_guard
from .package_product_worker_windows_provisioning import (
    inspect_coding_windows_product_worker_provisioning_attempts,
)


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerCrashNativeSettlementV1:
    attempt_id: str
    native_revision: int
    spec_fingerprint: str


def settle_coding_windows_product_worker_crash_native(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWindowsWorkerCrashCleanupReviewV1,
) -> CodingWindowsWorkerCrashNativeSettlementV1:
    """Recheck exact Product evidence under Package→GC locks before effects."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(expected_review) is not CodingWindowsWorkerCrashCleanupReviewV1
        or len(expected_review.orphan_review.orphan_leases) != 1
    ):
        raise ValueError("Windows Worker crash settlement requires exact Product proof")
    expected_orphan = expected_review.orphan_review
    [expected_lease] = expected_orphan.orphan_leases
    attempt_id = expected_orphan.attempt_id
    registry = product.epoch_runtime.registry
    with registry.guard_orphan_recovery(
        store_id=registry.store_id, lease_id=expected_lease.lease_id
    ) as lease:
        if lease != expected_lease:
            raise ValueError("Windows Worker crash lease changed")
        with product.gc_gate.guard(require_write=True):
            current = _review_under_gc_guard(
                product, attempt_id=attempt_id, orphans=(lease,)
            )
            if current != expected_orphan or not _crash_cleanup_history_matches(current):
                raise ValueError("Windows Worker crash cleanup review is stale")
            attempt = current.attempt
            assert attempt is not None and current.receipt_record is not None
            if (
                attempt.supervisor_phase is not None
                and attempt.supervisor_process_settled is not True
            ):
                raise ValueError("Windows Worker crash Supervisor is unsettled")
            native = tuple(
                item
                for item in inspect_coding_windows_product_worker_provisioning_attempts(
                    product
                )
                if item.attempt_id == attempt_id
            )
            if len(native) != 1:
                raise ValueError("Windows Worker native cleanup history changed")
            [provisioned] = native
            identity = provisioned.identity
            if (
                provisioned.phase != attempt.native_phase
                or provisioned.phase_history != attempt.native_phase_history
                or provisioned.witness_present_history
                != attempt.native_witness_present_history
                or provisioned.state_revision != expected_review.native_revision
                or identity["specFingerprint"]
                != expected_review.native_spec_fingerprint
                or attempt.payload_directory_identity
                != expected_review.payload_directory_identity
                or identity["receiptFingerprint"]
                != current.receipt_record.receipt.fingerprint
                or identity["workerRequestFingerprint"]
                != attempt.launch_request_fingerprint
                or identity["jobObjectName"] != attempt.native_job_name
                or identity["nativeProfileId"]
                != current.receipt_record.receipt.policy.native_profile_id
                or identity["nativeProfileCatalogRevision"]
                != current.receipt_record.receipt.policy.native_profile_catalog_revision
            ):
                raise ValueError("Windows Worker native cleanup identity changed")
            stage_name = f"worker-payload-{attempt_id}"
            material = read_coding_windows_worker_installed_backend_release(product)
            return settle_windows_product_worker_native_cleanup(
                product,
                stage_name=stage_name,
                attempt_id=attempt_id,
                identity=identity,
                expected_stage_identity=expected_review.payload_directory_identity,
                material_expectation=material.expectation,
                settlement_type=CodingWindowsWorkerCrashNativeSettlementV1,
            )


__all__ = [
    "CodingWindowsWorkerCrashNativeSettlementV1",
    "settle_coding_windows_product_worker_crash_native",
]
