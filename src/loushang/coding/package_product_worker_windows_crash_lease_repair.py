"""Repair a crashed Windows Worker lease after both native and process settlement."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeLeaseV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    windows_stat_at,
)
from loushang.harness.worker._native_profile_bridge import (
    _rebuild_windows_lpac_cleanup_spec,
)
from loushang.hosting import observe_windows_worker_job_absent
from loushang.hosting.windows_backend_material import WINDOWS_LPAC_PLATFORM_IMPORTS

from .package_product_worker_windows_crash_cleanup_review import (
    _crash_settled_history_matches,
)
from .package_product_worker_windows_orphan_review import (
    CodingWindowsWorkerOrphanRuntimeReviewV1,
    _review_under_gc_guard,
)
from .package_product_worker_windows_provisioning import (
    inspect_coding_windows_product_worker_provisioning_attempts,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerCrashLeaseRepairReviewV1:
    """Time-bound evidence; Package rechecks it before appending repair."""

    orphan_review: CodingWindowsWorkerOrphanRuntimeReviewV1
    native_revision: int
    native_spec_fingerprint: str
    payload_directory_identity: tuple[int, int]


@contextmanager
def _guard_settled_review(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    orphans: tuple[PackageEpochRuntimeLeaseV1, ...],
) -> Iterator[CodingWindowsWorkerCrashLeaseRepairReviewV1]:
    """Caller holds GC gate; pin retained stage across an optional Package append."""

    review = _review_under_gc_guard(product, attempt_id=attempt_id, orphans=orphans)
    if not _crash_settled_history_matches(review):
        raise ValueError("Windows Worker crash settlement history is unverified")
    attempt = review.attempt
    receipt = review.receipt_record
    assert attempt is not None and receipt is not None
    assert attempt.native_revision is not None
    assert attempt.payload_directory_identity is not None
    native = tuple(
        item
        for item in inspect_coding_windows_product_worker_provisioning_attempts(product)
        if item.attempt_id == attempt_id
    )
    if len(native) != 1:
        raise ValueError("Windows Worker native settlement identity is unverified")
    [provisioned] = native
    identity = provisioned.identity
    if (
        provisioned.phase != "settled"
        or provisioned.state_revision != attempt.native_revision
        or provisioned.phase_history != attempt.native_phase_history
        or provisioned.witness_present_history != attempt.native_witness_present_history
        or identity["workerRequestFingerprint"] != attempt.launch_request_fingerprint
        or identity["receiptFingerprint"] != receipt.receipt.fingerprint
        or identity["jobObjectName"] != attempt.native_job_name
        or identity["nativeProfileId"] != receipt.receipt.policy.native_profile_id
        or identity["nativeProfileCatalogRevision"]
        != receipt.receipt.policy.native_profile_catalog_revision
    ):
        raise ValueError("Windows Worker native settlement identity changed")
    stage_name = f"worker-payload-{attempt_id}"
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        stage = open_windows_directory(
            stage_name,
            dir_fd=root,
            share_delete=False,
            writable=False,
            read_control=True,
        )
        try:
            observed = os.fstat(stage)
            visible = windows_stat_at(root, stage_name)
            if (
                observed.st_dev,
                observed.st_ino,
            ) != attempt.payload_directory_identity or not os.path.samestat(
                observed, visible
            ):
                raise ValueError("Windows Worker crash payload stage changed")
            _rebuild_windows_lpac_cleanup_spec(
                identity=identity,
                runtime_root=product.state_root / stage_name,
                platform_imports=WINDOWS_LPAC_PLATFORM_IMPORTS,
                owner_private_ancestors=True,
            )
            if (
                observe_windows_worker_job_absent(cast(str, identity["jobObjectName"]))
                is not True
            ):
                raise ValueError("Windows Worker crash Job is still present")
            product.assert_root_gc_authority_current()
            yield CodingWindowsWorkerCrashLeaseRepairReviewV1(
                orphan_review=review,
                native_revision=attempt.native_revision,
                native_spec_fingerprint=cast(str, identity["specFingerprint"]),
                payload_directory_identity=attempt.payload_directory_identity,
            )
            product.assert_root_gc_authority_current()
        finally:
            os.close(stage)


def review_coding_windows_product_worker_crash_lease_repair(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWindowsWorkerCrashLeaseRepairReviewV1:
    """Observe an orphan with complete native and Supervisor settlement."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(attempt_id) is not str
        or _ATTEMPT.fullmatch(attempt_id) is None
    ):
        raise ValueError("Windows Worker crash lease review requires exact Product")
    registry = product.epoch_runtime.registry
    orphans = registry.review_orphans(store_id=registry.store_id)
    with product.gc_gate.read_guard():
        with _guard_settled_review(
            product, attempt_id=attempt_id, orphans=orphans
        ) as review:
            return review


def repair_coding_windows_product_worker_crash_orphan_runtime(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWindowsWorkerCrashLeaseRepairReviewV1,
) -> PackageEpochRuntimeLeaseV1:
    """Recheck settlement under Package→Product locks before lease repair."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(expected_review) is not CodingWindowsWorkerCrashLeaseRepairReviewV1
        or len(expected_review.orphan_review.orphan_leases) != 1
    ):
        raise ValueError(
            "Windows Worker crash lease repair requires exact Product proof"
        )
    [expected_lease] = expected_review.orphan_review.orphan_leases
    registry = product.epoch_runtime.registry

    @contextmanager
    def validate_while_locked(lease: PackageEpochRuntimeLeaseV1) -> Iterator[None]:
        if lease != expected_lease:
            raise ValueError("Windows Worker crash orphan lease changed")
        with product.gc_gate.guard(require_write=True):
            with _guard_settled_review(
                product,
                attempt_id=expected_review.orphan_review.attempt_id,
                orphans=(lease,),
            ) as current:
                if current != expected_review:
                    raise ValueError("Windows Worker crash lease review is stale")
                yield

    registry.repair_orphan(
        expected_lease.lease_id, validation_guard=validate_while_locked
    )
    return expected_lease


__all__ = [
    "CodingWindowsWorkerCrashLeaseRepairReviewV1",
    "repair_coding_windows_product_worker_crash_orphan_runtime",
    "review_coding_windows_product_worker_crash_lease_repair",
]
