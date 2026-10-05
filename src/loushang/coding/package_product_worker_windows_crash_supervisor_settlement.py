"""Settle a crashed Windows Worker Supervisor after exact Job absence proof."""

from __future__ import annotations

import os

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.worker.journal import (
    WorkerAttemptRecordV1,
    WorkerSupervisorJournal,
)
from loushang.hosting import observe_windows_worker_job_absent

from .package_product_worker_windows_crash_cleanup_review import (
    CodingWindowsWorkerCrashCleanupReviewV1,
    _crash_cleanup_history_matches,
)
from .package_product_worker_windows_launch_intent import _read_intent_under_gc_guard
from .package_product_worker_windows_orphan_review import _review_under_gc_guard
from .package_product_worker_windows_recovery_inventory import (
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
)
from .package_product_worker_windows_supervisor_journal import (
    open_coding_windows_product_worker_supervisor_journal,
)

_CRASH_FAILURE_CODE = "windows_host_crash"
_ACTIVE_PHASES = frozenset(
    {"claimed", "launching", "handshaking", "healthy", "draining"}
)


def _settle_crashed_supervisor_record(
    journal: WorkerSupervisorJournal, record: WorkerAttemptRecordV1
) -> WorkerAttemptRecordV1:
    if record.process_settled:
        return record
    if record.phase in _ACTIVE_PHASES:
        record = journal.transition(
            record.attempt_id,
            expected_phase=record.phase,
            next_phase="failed",
            expected_record_revision=record.record_revision,
            expected_supervisor_epoch=record.supervisor_epoch,
            failure_code=_CRASH_FAILURE_CODE,
        )
    if record.phase not in {"failed", "fenced"} or record.failure_code is None:
        raise ValueError("Windows Worker crashed Supervisor state is invalid")
    return journal.transition(
        record.attempt_id,
        expected_phase=record.phase,
        next_phase="process_settled",
        expected_record_revision=record.record_revision,
        expected_supervisor_epoch=record.supervisor_epoch,
        failure_code=record.failure_code,
    )


def settle_coding_windows_product_worker_crash_supervisor(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWindowsWorkerCrashCleanupReviewV1,
) -> WorkerAttemptRecordV1 | None:
    """Write only the process-side settlement under Package→Product locks."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(expected_review) is not CodingWindowsWorkerCrashCleanupReviewV1
        or len(expected_review.orphan_review.orphan_leases) != 1
    ):
        raise ValueError("Windows Worker crash Supervisor requires exact Product proof")
    expected_orphan = expected_review.orphan_review
    [expected_lease] = expected_orphan.orphan_leases
    attempt_id = expected_orphan.attempt_id
    registry = product.epoch_runtime.registry
    with registry.guard_orphan_recovery(
        store_id=registry.store_id, lease_id=expected_lease.lease_id
    ) as lease:
        if lease != expected_lease:
            raise ValueError("Windows Worker crash Supervisor lease changed")
        with product.gc_gate.guard():
            current = _review_under_gc_guard(
                product, attempt_id=attempt_id, orphans=(lease,)
            )
            if current != expected_orphan or not _crash_cleanup_history_matches(current):
                raise ValueError("Windows Worker crash Supervisor review is stale")
            attempt = current.attempt
            assert attempt is not None
            assert attempt.native_job_name is not None
            intent = _read_intent_under_gc_guard(product, attempt_id)
            if (
                intent is None
                or intent.identity_fingerprint != attempt.launch_identity_fingerprint
                or intent.stage_identity != attempt.payload_directory_identity
                or attempt.native_revision != expected_review.native_revision
                or attempt.payload_directory_identity
                != expected_review.payload_directory_identity
            ):
                raise ValueError("Windows Worker crash Supervisor identity changed")
            if observe_windows_worker_job_absent(attempt.native_job_name) is not True:
                raise ValueError("Windows Worker crash Job is still present")
            if attempt.supervisor_phase is None:
                product.assert_root_gc_authority_current()
                return None
            journal = open_coding_windows_product_worker_supervisor_journal(product)
            records = tuple(
                item
                for item in journal.inspect_records()
                if item.attempt_id == attempt_id
            )
            if not records:
                raise ValueError("Windows Worker crash Supervisor history disappeared")
            record = records[-1]
            if (
                record.phase != attempt.supervisor_phase
                or record.record_revision != attempt.supervisor_revision
                or record.identity_fingerprint != intent.identity_fingerprint
                or record.supervisor_epoch != intent.supervisor_epoch
            ):
                raise ValueError("Windows Worker crash Supervisor history changed")
            settled = _settle_crashed_supervisor_record(journal, record)
            refreshed = next(
                (
                    item
                    for item in _inspect_windows_worker_recovery_inventory_under_gc_guard(
                        product
                    )
                    if item.attempt_id == attempt_id
                ),
                None,
            )
            if (
                refreshed is None
                or refreshed.native_revision != attempt.native_revision
                or refreshed.payload_directory_identity
                != attempt.payload_directory_identity
                or refreshed.launch_identity_fingerprint
                != attempt.launch_identity_fingerprint
                or refreshed.supervisor_phase != settled.phase
                or refreshed.supervisor_revision != settled.record_revision
                or refreshed.supervisor_process_settled is not True
                or observe_windows_worker_job_absent(attempt.native_job_name)
                is not True
            ):
                raise ValueError("Windows Worker crash Supervisor settlement changed")
            product.assert_root_gc_authority_current()
            return settled


__all__ = ["settle_coding_windows_product_worker_crash_supervisor"]
