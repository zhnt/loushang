"""Coding Product Profile and compatibility entry for the existing Windows recovery owner."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, cast

from loushang.coding.harness.worker.windows_admission import is_windows_product
from loushang.harness.package_product._windows_worker_recovery import (
    WindowsProductWorkerCrashRecovery,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from .product_worker_activation_history import CodingProductWorkerRetainedAttemptV1

if TYPE_CHECKING:
    from loushang.harness.package_product._windows_worker_recovery import (
        CrashEvidenceFactory,
        CrashStageRetirementProfile,
    )


def recover_coding_windows_product_worker_crash_attempt(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingProductWorkerRetainedAttemptV1:
    """Resume each completed edge without granting authority from a stale review."""
    if not is_windows_product(product, "coding", os.name):
        raise ValueError("Windows Worker crash recovery requires its Coding Product")
    return cast(
        CodingProductWorkerRetainedAttemptV1,
        _recovery_program().recover(product, attempt_id=attempt_id),
    )


def _recovery_program() -> WindowsProductWorkerCrashRecovery:
    from . import product_worker_windows_activation_state_journal as activation
    from . import product_worker_windows_cleanup_evidence as evidence
    from . import product_worker_windows_crash_cleanup_review as cleanup
    from . import product_worker_windows_crash_lease_repair as lease
    from . import product_worker_windows_crash_native_settlement as native
    from . import product_worker_windows_crash_stage_retirement as retirement
    from . import product_worker_windows_installed_backend as backend
    from . import product_worker_windows_launch_intent as intent
    from . import product_worker_windows_orphan_review as orphan
    from . import product_worker_windows_provisioning as provisioning
    from . import product_worker_windows_recovery_inventory as inventory
    from . import product_worker_windows_supervisor_journal as supervisor
    from .product_worker_activation_state import (
        open_coding_windows_product_worker_activation_state_store,
    )

    return WindowsProductWorkerCrashRecovery(
        product_id="coding",
        record_type=lease.CodingWindowsWorkerCrashLeaseRepairReviewV1,
        orphan_type=orphan.CodingWindowsWorkerOrphanRuntimeReviewV1,
        cleanup_type=cleanup.CodingWindowsWorkerCrashCleanupReviewV1,
        cleanup_error=cleanup.CodingWindowsWorkerCrashCleanupReviewError,
        cleanup_error_prefix="coding_worker_crash_cleanup",
        review_runtime=orphan._review_under_gc_guard,
        inspect_native=provisioning.inspect_coding_windows_product_worker_provisioning_attempts,
        inspect_inventory=inventory._inspect_windows_worker_recovery_inventory_under_gc_guard,
        read_intent=intent._read_intent_under_gc_guard,
        supervisor_journal=supervisor.open_coding_windows_product_worker_supervisor_journal,
        activation_journal=activation.CodingWindowsWorkerActivationStateJournal,
        read_backend=backend.read_coding_windows_worker_installed_backend_release,
        settlement_type=native.CodingWindowsWorkerCrashNativeSettlementV1,
        evidence_factory=cast(
            "CrashEvidenceFactory",
            evidence.CodingWindowsWorkerCleanupEvidenceAuthority.for_crash_recovery,
        ),
        state_store=open_coding_windows_product_worker_activation_state_store,
        evidence_authority_id=evidence.CodingWindowsWorkerCleanupEvidenceAuthority.authority_id,
        evidence_authority_fingerprint=evidence.CodingWindowsWorkerCleanupEvidenceAuthority.authority_fingerprint,
        host_domain="coding-windows-store:",
        boot_domain="coding-windows-runtime:",
        stage_retirement=cast(
            "CrashStageRetirementProfile",
            retirement._operations,
        ),
    )


__all__ = ["recover_coding_windows_product_worker_crash_attempt"]
