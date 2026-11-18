"""Read-only Windows Product Worker recovery inventory across retained owners.

This joins identities only. It cannot settle a Job, revoke an LPAC grant,
delete a payload, release a Package lease, or admit a fresh Worker attempt.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, cast

from loushang.harness.package_product._windows_worker_recovery import (
    WindowsProductWorkerHistoryJournals,
    capture_windows_product_worker_offline_recovery_under_guard,
    current_windows_worker_attempts_after_verified_retirements,
    read_windows_product_worker_attempt_gc_observations,
    read_windows_product_worker_attempt_references_under_guard,
    read_windows_product_worker_offline_recovery,
)
from loushang.harness.package_product._worker_windows_attempt import (
    inspect_windows_product_worker_recovery_inventory,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1,
)
from loushang.harness.plugin_management.records import PluginPackageRevisionRefV1
from loushang.harness.worker.activation_state_journal import _StateRecord
from loushang.harness.worker.history._windows_recovery import (
    WindowsRecoveryAdmission,
    WindowsRecoveryAttemptV1,
    _WindowsOfflineRecoveryMethods,
)
from loushang.harness.worker.journal import WorkerAttemptPhase as WorkerAttemptPhase
from loushang.harness.worker.journal import WorkerAttemptRecordV1
from loushang.hosting import observe_windows_worker_job_absent

from .package_product_backup_types import (
    CodingWorkerBackupReferenceObservationV1,
    observe_coding_worker_backup_references_under_gc_guard,
)
from .package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from .package_product_worker_opt_in import CodingWorkerOptInDecisionV1
from .package_product_worker_receipt import CodingWorkerReceiptRecordV1
from .package_product_worker_windows_activation_state_journal import (
    CodingWindowsWorkerActivationStateJournal,
)
from .package_product_worker_windows_launch_intent import (
    CodingWindowsWorkerLaunchIntentV1,
    _inspect_intents_under_gc_guard,
)
from .package_product_worker_windows_opt_in_journal import (
    CodingWindowsWorkerOptInJournal,
)
from .package_product_worker_windows_payload_inventory import (
    inspect_coding_windows_product_worker_payload_attempts,
)
from .package_product_worker_windows_provisioning import (
    inspect_coding_windows_product_worker_provisioning_attempts,
)
from .package_product_worker_windows_provisioning_journal import (
    WindowsWorkerProvisioningAttemptV1,
)
from .package_product_worker_windows_receipt_journal import (
    CodingWindowsWorkerReceiptJournal,
)
from .package_product_worker_windows_supervisor_journal import (
    open_coding_windows_product_worker_supervisor_journal,
)


def _observe_native_job_absence(job_name: str | None) -> bool | None:
    """Keep an unavailable native observation distinct from proven absence."""

    if job_name is None:
        return None
    try:
        return observe_windows_worker_job_absent(job_name)
    except OSError:
        return None


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerRecoveryAttemptV1(WindowsRecoveryAttemptV1):
    """Observed attempt facts; no member grants launch or cleanup authority."""


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerOfflineRecoverySnapshotV1(_WindowsOfflineRecoveryMethods):
    """One lease-quiescent, no-effect view for a later recovery decision.

    Retained histories and GC/backup observations are checkpoint inputs only.
    This view grants no receipt retirement, Package GC, or pruning authority.
    """

    store_id: str
    lease_owner_revision: int
    attempts: tuple[CodingWindowsWorkerRecoveryAttemptV1, ...]
    opt_in_decisions: tuple[CodingWorkerOptInDecisionV1, ...]
    receipt_records: tuple[CodingWorkerReceiptRecordV1, ...]
    supervisor_records: tuple[WorkerAttemptRecordV1, ...]
    activation_state_owner_present: bool
    activation_state_revision: int
    retained_activation_attempts: tuple[CodingProductWorkerRetainedAttemptV1, ...]
    native_job_absence: tuple[tuple[str, bool | None], ...]
    gc_reservation_revision: int
    gc_revision_refs: frozenset[PluginPackageRevisionRefV1]
    worker_backup_observations: tuple[CodingWorkerBackupReferenceObservationV1, ...]
    activation_state_records: tuple[_StateRecord, ...] = ()
    launch_intents: tuple[CodingWindowsWorkerLaunchIntentV1, ...] = ()
    native_provisioning_attempts: tuple[WindowsWorkerProvisioningAttemptV1, ...] = ()


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerAttemptReferenceV1:
    """One retained launch intent joined to its exact Windows Product receipt.

    This is read-only evidence. It does not certify native cleanup or permit
    receipt retirement, backup expiry, Package GC, or history pruning.
    """

    attempt_id: str
    plugin_id: str
    receipt_fingerprint: str
    selected_package_revision_digest: str
    selected_locator_revision: str
    native_platform: Literal["windows"]
    launch_request_fingerprint: str


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerAttemptGcObservationV1:
    """One attempt reference joined to the current Package GC reservations.

    The reservation journal only names Package revisions. Even an empty match
    cannot prove that backup or other Product owners released this attempt.
    """

    attempt_reference: CodingWindowsWorkerAttemptReferenceV1
    active_gc_reservation_count: int
    gc_reservation_revision: int
    matching_revision_refs: tuple[PluginPackageRevisionRefV1, ...]
    worker_backup_references: CodingWorkerBackupReferenceObservationV1


class CodingWindowsWorkerRecoveryAdmissionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _current_after_verified_retirements_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    inventory: tuple[CodingWindowsWorkerRecoveryAttemptV1, ...],
    *,
    attempt_id: str | None,
) -> tuple[CodingWindowsWorkerRecoveryAttemptV1, ...]:
    """Exclude only completed, independently checked historical attempts.

    Passing no current attempt requires every observed attempt to be retired.
    """

    product.assert_root_gc_authority_current()
    from .package_product_worker_windows_crash_stage_retirement import (
        _require_completed_crash_retirement_under_gc_guard,
    )
    from .package_product_worker_windows_partial_stage_retirement import (
        _require_completed_partial_retirement_under_gc_guard,
    )
    from .package_product_worker_windows_stage_retirement import (
        _require_completed_retirement_under_gc_guard,
    )
    from .package_product_worker_windows_unlaunched_stage_retirement import (
        _require_completed_unlaunched_retirement_under_gc_guard,
    )

    return current_windows_worker_attempts_after_verified_retirements(
        product,
        inventory,
        attempt_id=attempt_id,
        require_partial=_require_completed_partial_retirement_under_gc_guard,
        require_crash=_require_completed_crash_retirement_under_gc_guard,
        require_unlaunched=_require_completed_unlaunched_retirement_under_gc_guard,
        require_complete=_require_completed_retirement_under_gc_guard,
        error_type=CodingWindowsWorkerRecoveryAdmissionError,
        error_code="coding_worker_payload_recovery_required",
    )


def inspect_coding_windows_product_worker_recovery_inventory(
    product: WindowsLocalWheelProductSessionOwner,
) -> tuple[CodingWindowsWorkerRecoveryAttemptV1, ...]:
    """Join all observed attempt IDs under one no-create Product GC read guard."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise OSError("Windows Worker recovery inventory requires a Product owner")
    with product.gc_gate.read_guard():
        return _inspect_windows_worker_recovery_inventory_under_gc_guard(product)


def inspect_coding_windows_product_worker_attempt_references(
    product: WindowsLocalWheelProductSessionOwner,
) -> tuple[CodingWindowsWorkerAttemptReferenceV1, ...]:
    """Project every durable launch intent with its retained Product receipt.

    Partial stages without an intent remain recovery debts, not references.
    An observed native or Supervisor effect without an intent refuses the whole
    projection. No runtime quiescence or state mutation is needed for this read.
    """

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise OSError("Windows Worker attempt references require a Product owner")
    with product.gc_gate.read_guard():
        return _inspect_windows_worker_attempt_references_under_gc_guard(product)


def inspect_coding_windows_product_worker_attempt_gc_observations(
    product: WindowsLocalWheelProductSessionOwner,
) -> tuple[CodingWindowsWorkerAttemptGcObservationV1, ...]:
    """Join retained launch references to active GC reservations under one gate."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise OSError("Windows Worker GC observations require a Product owner")
    return read_windows_product_worker_attempt_gc_observations(
        product,
        read_references=_inspect_windows_worker_attempt_references_under_gc_guard,
        observe_backup=observe_coding_worker_backup_references_under_gc_guard,
        observation_type=CodingWindowsWorkerAttemptGcObservationV1,
    )


def _inspect_windows_worker_attempt_references_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
) -> tuple[CodingWindowsWorkerAttemptReferenceV1, ...]:
    return read_windows_product_worker_attempt_references_under_guard(
        product,
        journals=_windows_history_journals(),
        inspect_inventory=_inspect_windows_worker_recovery_inventory_under_gc_guard,
        reference_type=CodingWindowsWorkerAttemptReferenceV1,
        product_id="coding",
        error_type=CodingWindowsWorkerRecoveryAdmissionError,
        error_prefix="coding_worker_attempt_reference_",
    )


def inspect_coding_windows_product_worker_offline_recovery(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerOfflineRecoverySnapshotV1:
    """Hold Package runtime quiescence while joining every Product attempt."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise OSError("Windows Worker offline recovery requires a Product owner")
    return cast(
        CodingWindowsWorkerOfflineRecoverySnapshotV1,
        read_windows_product_worker_offline_recovery(
            product,
            read_under_guard=_inspect_coding_windows_product_worker_offline_recovery_under_gc_guard,
            active_error=CodingWindowsWorkerRecoveryAdmissionError,
            active_code="coding_worker_offline_recovery_runtime_active",
        ),
    )


def _inspect_coding_windows_product_worker_offline_recovery_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    store_id: str,
    lease_owner_revision: int,
    gc_snapshot: PluginPackageGcReservationSnapshotV1,
) -> CodingWindowsWorkerOfflineRecoverySnapshotV1:
    """Join semantic histories under an already held Product quiescence/gate."""

    return capture_windows_product_worker_offline_recovery_under_guard(
        product,
        journals=_windows_history_journals(),
        snapshot_type=CodingWindowsWorkerOfflineRecoverySnapshotV1,
        inspect_native=inspect_coding_windows_product_worker_provisioning_attempts,
        inspect_inventory=_inspect_windows_worker_recovery_inventory_under_gc_guard,
        inspect_intents=_inspect_intents_under_gc_guard,
        observe_job_absence=_observe_native_job_absence,
        observe_backup=observe_coding_worker_backup_references_under_gc_guard,
        store_id=store_id,
        lease_owner_revision=lease_owner_revision,
        gc_snapshot=gc_snapshot,
    )


def _inspect_windows_worker_recovery_inventory_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    native_attempts: tuple[WindowsWorkerProvisioningAttemptV1, ...] | None = None,
) -> tuple[CodingWindowsWorkerRecoveryAttemptV1, ...]:
    """Reuse one already-held Product GC gate for a pre-effect admission check."""
    if os.name != "nt" or type(product) is not WindowsLocalWheelProductSessionOwner:
        raise OSError("Windows Worker recovery inventory requires a Product owner")
    return inspect_windows_product_worker_recovery_inventory(
        product,
        inspect_retirements=_recovery_retirement_attempt_ids,
        inspect_payloads=inspect_coding_windows_product_worker_payload_attempts,
        inspect_intents=_inspect_intents_under_gc_guard,
        inspect_native=inspect_coding_windows_product_worker_provisioning_attempts,
        inspect_supervisor=lambda current: (
            open_coding_windows_product_worker_supervisor_journal(
                current
            ).inspect_records()
        ),
        record_type=CodingWindowsWorkerRecoveryAttemptV1,
        native_attempts=native_attempts,
    )


def _recovery_retirement_attempt_ids(
    product: WindowsLocalWheelProductSessionOwner,
) -> frozenset[str]:
    # Keep the original cycle-breaking import after the first currentness check.
    from .package_product_worker_windows_stage_retirement import (
        _inspect_retirement_attempt_ids_under_gc_guard,
    )

    return _inspect_retirement_attempt_ids_under_gc_guard(product)


__all__ = [
    "CodingWindowsWorkerRecoveryAdmissionError",
    "CodingWindowsWorkerAttemptGcObservationV1",
    "CodingWindowsWorkerAttemptReferenceV1",
    "CodingWindowsWorkerRecoveryAttemptV1",
    "CodingWindowsWorkerOfflineRecoverySnapshotV1",
    "inspect_coding_windows_product_worker_offline_recovery",
    "inspect_coding_windows_product_worker_attempt_references",
    "inspect_coding_windows_product_worker_attempt_gc_observations",
    "inspect_coding_windows_product_worker_recovery_inventory",
    "require_coding_windows_worker_current_attempt",
]


_RECOVERY_ADMISSION = WindowsRecoveryAdmission(
    CodingWindowsWorkerRecoveryAttemptV1,
    CodingWindowsWorkerRecoveryAdmissionError,
    "coding_worker_payload_recovery_required",
)

require_coding_windows_worker_current_attempt = _RECOVERY_ADMISSION.require_current
require_coding_windows_worker_native_release_attempt = (
    _RECOVERY_ADMISSION.require_native_release
)
require_coding_windows_worker_terminal_cleanup_attempt = (
    _RECOVERY_ADMISSION.require_terminal_cleanup
)


def _windows_history_journals() -> WindowsProductWorkerHistoryJournals:
    return WindowsProductWorkerHistoryJournals(
        opt_in=CodingWindowsWorkerOptInJournal,
        receipt=CodingWindowsWorkerReceiptJournal,
        activation=CodingWindowsWorkerActivationStateJournal,
        supervisor=open_coding_windows_product_worker_supervisor_journal,
        retained_type=CodingProductWorkerRetainedAttemptV1,
    )
