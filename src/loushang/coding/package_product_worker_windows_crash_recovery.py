"""Resume the ordered Product recovery of one crashed Windows Worker attempt."""

from __future__ import annotations

import os
from collections.abc import Mapping

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from .package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from .package_product_worker_windows_activation_state_journal import (
    CodingWindowsWorkerActivationStateJournal,
)
from .package_product_worker_windows_cleanup_evidence import (
    CodingWindowsWorkerCleanupEvidenceAuthority,
)
from .package_product_worker_windows_crash_c5_settlement import (
    settle_coding_windows_product_worker_crash_c5,
)
from .package_product_worker_windows_crash_cleanup_review import (
    review_coding_windows_product_worker_crash_cleanup,
)
from .package_product_worker_windows_crash_lease_repair import (
    repair_coding_windows_product_worker_crash_orphan_runtime,
    review_coding_windows_product_worker_crash_lease_repair,
)
from .package_product_worker_windows_crash_native_settlement import (
    settle_coding_windows_product_worker_crash_native,
)
from .package_product_worker_windows_crash_stage_retirement import (
    retire_coding_windows_product_worker_crash_stage,
)
from .package_product_worker_windows_crash_stage_review import (
    review_coding_windows_product_worker_crash_stage,
)
from .package_product_worker_windows_crash_supervisor_settlement import (
    settle_coding_windows_product_worker_crash_supervisor,
)
from .package_product_worker_windows_orphan_review import (
    review_coding_windows_product_worker_orphan_runtime,
)


def recover_coding_windows_product_worker_crash_attempt(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingProductWorkerRetainedAttemptV1:
    """Resume each completed edge without granting authority from a stale review."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Windows Worker crash recovery requires its Coding Product")
    current = review_coding_windows_product_worker_orphan_runtime(
        product, attempt_id=attempt_id
    )
    attempt = current.attempt
    record = current.receipt_record
    if attempt is None or record is None:
        raise ValueError("Windows Worker crash attempt is absent")
    journal = CodingWindowsWorkerActivationStateJournal(product)
    retained = tuple(
        item
        for item in journal.retained_attempts_read_only()
        if item.attempt_id == attempt_id
    )
    if len(retained) != 1:
        raise ValueError("Windows Worker crash C5 owner is missing or ambiguous")
    [c5] = retained
    receipt = record.receipt
    expected_host = "coding-windows-store:" + product.epoch_runtime.registry.store_id
    expected_boot = "coding-windows-runtime:" + receipt.policy.product_runtime_id
    state = journal.load()
    attempts = None if state is None else state.get("attempts")
    exact = (
        ()
        if not isinstance(attempts, Mapping)
        else tuple(
            item
            for item in attempts.values()
            if isinstance(item, Mapping) and item.get("attemptId") == attempt_id
        )
    )
    if (
        not c5.current
        or c5.phase
        not in {"effect_started", "published", "cleanup_debt", "retired", "settled"}
        or c5.receipt_fingerprint != receipt.fingerprint
        or c5.policy_fingerprint != receipt.policy.fingerprint
        or c5.owner_generation != receipt.policy.owner_selection_generation
        or c5.cleanup_contract_version != 2
        or c5.host_identity != expected_host
        or c5.boot_identity != expected_boot
        or len(exact) != 1
        or exact[0].get("evidenceAuthorityId")
        != CodingWindowsWorkerCleanupEvidenceAuthority.authority_id
        or exact[0].get("evidenceAuthorityFingerprint")
        != CodingWindowsWorkerCleanupEvidenceAuthority.authority_fingerprint
    ):
        raise ValueError("Windows Worker crash C5 owner changed")
    if attempt.supervisor_phase != "process_settled":
        review = review_coding_windows_product_worker_crash_cleanup(
            product, attempt_id=attempt_id
        )
        settle_coding_windows_product_worker_crash_supervisor(
            product, expected_review=review
        )
    current = review_coding_windows_product_worker_orphan_runtime(
        product, attempt_id=attempt_id
    )
    attempt = current.attempt
    if attempt is None:
        raise ValueError("Windows Worker crash attempt disappeared")
    if attempt.native_phase != "settled":
        review = review_coding_windows_product_worker_crash_cleanup(
            product, attempt_id=attempt_id
        )
        settle_coding_windows_product_worker_crash_native(
            product, expected_review=review
        )
    current = review_coding_windows_product_worker_orphan_runtime(
        product, attempt_id=attempt_id
    )
    if len(current.orphan_leases) == 1:
        lease_review = review_coding_windows_product_worker_crash_lease_repair(
            product, attempt_id=attempt_id
        )
        repair_coding_windows_product_worker_crash_orphan_runtime(
            product, expected_review=lease_review
        )
    elif current.orphan_leases:
        raise ValueError("Windows Worker crash orphan lease is ambiguous")
    current = review_coding_windows_product_worker_orphan_runtime(
        product, attempt_id=attempt_id
    )
    attempt = current.attempt
    if attempt is None:
        raise ValueError("Windows Worker crash attempt disappeared")
    if attempt.payload_directory_identity is not None:
        stage_review = review_coding_windows_product_worker_crash_stage(
            product, attempt_id=attempt_id
        )
        retire_coding_windows_product_worker_crash_stage(
            product, expected_review=stage_review
        )
    return settle_coding_windows_product_worker_crash_c5(product, attempt_id=attempt_id)


__all__ = ["recover_coding_windows_product_worker_crash_attempt"]
