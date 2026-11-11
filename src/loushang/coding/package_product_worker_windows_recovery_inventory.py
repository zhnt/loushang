"""Read-only Windows Product Worker recovery inventory across retained owners.

This joins identities only. It cannot settle a Job, revoke an LPAC grant,
delete a payload, release a Package lease, or admit a fresh Worker attempt.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, cast

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
    _FINGERPRINT,
    WindowsRecoveryAdmission,
    WindowsRecoveryAttemptV1,
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
    project_coding_worker_retained_attempts,
)
from .package_product_worker_gc_references import (
    coding_worker_gc_revision_refs,
    matching_coding_worker_gc_revision_refs,
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
class CodingWindowsWorkerOfflineRecoverySnapshotV1:
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

    @property
    def opt_in_history_revision(self) -> int:
        return max((item.journal_revision for item in self.opt_in_decisions), default=0)

    @property
    def receipt_history_revision(self) -> int:
        return max((item.journal_revision for item in self.receipt_records), default=0)

    @property
    def supervisor_history_revision(self) -> int:
        return max(
            (item.record_revision for item in self.supervisor_records), default=0
        )

    @property
    def retained_opt_in_operation_ids(self) -> tuple[str, ...]:
        return tuple(item.operation_id for item in self.opt_in_decisions)

    @property
    def retained_supervisor_attempt_ids(self) -> tuple[str, ...]:
        return tuple(sorted({item.attempt_id for item in self.supervisor_records}))

    @property
    def retained_receipt_fingerprints(self) -> tuple[str, ...]:
        return tuple(sorted(item.receipt.fingerprint for item in self.receipt_records))

    @property
    def supervisor_epoch_high_water(self) -> tuple[tuple[str, int], ...]:
        highest: dict[str, int] = {}
        for record in self.supervisor_records:
            highest[record.supervisor_key] = max(
                highest.get(record.supervisor_key, 0), record.supervisor_epoch
            )
        return tuple(sorted(highest.items()))


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
    from .package_product_worker_windows_crash_cleanup_review import (
        _valid_crash_native_settlement_history,
    )
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

    current: list[CodingWindowsWorkerRecoveryAttemptV1] = []
    for attempt in inventory:
        if attempt.attempt_id == attempt_id:
            current.append(attempt)
            continue
        try:
            if (
                attempt.launch_request_fingerprint is None
                and attempt.native_phase is None
                and attempt.supervisor_phase is None
            ):
                _require_completed_partial_retirement_under_gc_guard(product, attempt)
            elif (
                attempt.native_phase == "settled"
                and attempt.supervisor_phase in {None, "process_settled"}
                and _valid_crash_native_settlement_history(attempt)
            ):
                _require_completed_crash_retirement_under_gc_guard(product, attempt)
            elif attempt.native_phase == "settled" and attempt.supervisor_phase is None:
                _require_completed_unlaunched_retirement_under_gc_guard(
                    product, attempt
                )
            else:
                _require_completed_retirement_under_gc_guard(product, attempt)
        except (OSError, RuntimeError, ValueError) as exc:
            raise CodingWindowsWorkerRecoveryAdmissionError(
                "coding_worker_payload_recovery_required"
            ) from exc
    product.assert_root_gc_authority_current()
    return tuple(current)


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
    with product.gc_gate.read_snapshot_guard() as gc_snapshot:
        reservations = coding_worker_gc_revision_refs(gc_snapshot)
        references = _inspect_windows_worker_attempt_references_under_gc_guard(product)
        return tuple(
            CodingWindowsWorkerAttemptGcObservationV1(
                attempt_reference=reference,
                active_gc_reservation_count=len(reservations),
                gc_reservation_revision=gc_snapshot.journal_revision,
                matching_revision_refs=matching_coding_worker_gc_revision_refs(
                    plugin_id=reference.plugin_id,
                    package_content_digest=(reference.selected_package_revision_digest),
                    reservations=reservations,
                ),
                worker_backup_references=(
                    observe_coding_worker_backup_references_under_gc_guard(
                        product, attempt_id=reference.attempt_id
                    )
                ),
            )
            for reference in references
        )


def _inspect_windows_worker_attempt_references_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
) -> tuple[CodingWindowsWorkerAttemptReferenceV1, ...]:
    from .package_product_worker_windows_receipt_journal import (
        CodingWindowsWorkerReceiptJournal,
    )

    product.assert_root_gc_authority_current()
    attempts = _inspect_windows_worker_recovery_inventory_under_gc_guard(product)
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        receipts = CodingWindowsWorkerReceiptJournal(
            product.state_root / "worker-activation-receipts.jsonl",
            scope_id=product.policy.project_scope_id,
        ).records(directory_fd=root)
    receipt_by_fingerprint = {record.receipt.fingerprint: record for record in receipts}
    if len(receipt_by_fingerprint) != len(receipts):
        raise CodingWindowsWorkerRecoveryAdmissionError(
            "coding_worker_attempt_reference_receipt_conflict"
        )
    references: list[CodingWindowsWorkerAttemptReferenceV1] = []
    for attempt in attempts:
        request_fingerprint = attempt.launch_request_fingerprint
        receipt_fingerprint = attempt.launch_receipt_fingerprint
        identity_fingerprint = attempt.launch_identity_fingerprint
        if request_fingerprint is None:
            if (
                receipt_fingerprint is not None
                or identity_fingerprint is not None
                or attempt.native_phase is not None
                or attempt.supervisor_phase is not None
            ):
                raise CodingWindowsWorkerRecoveryAdmissionError(
                    "coding_worker_attempt_reference_intent_absent"
                )
            continue
        receipt = (
            None
            if receipt_fingerprint is None
            else receipt_by_fingerprint.get(receipt_fingerprint)
        )
        if (
            receipt_fingerprint is None
            or identity_fingerprint is None
            or any(
                type(value) is not str or _FINGERPRINT.fullmatch(value) is None
                for value in (
                    request_fingerprint,
                    receipt_fingerprint,
                    identity_fingerprint,
                )
            )
            or attempt.launch_stage_identity is None
            or receipt is None
            or receipt.receipt.policy.product_id != "coding"
            or (
                attempt.native_phase is not None
                and (
                    attempt.native_worker_request_fingerprint != request_fingerprint
                    or attempt.native_receipt_fingerprint != receipt_fingerprint
                )
            )
            or (
                attempt.supervisor_phase is not None
                and attempt.supervisor_identity_fingerprint != identity_fingerprint
            )
        ):
            raise CodingWindowsWorkerRecoveryAdmissionError(
                "coding_worker_attempt_reference_binding_changed"
            )
        policy = receipt.receipt.policy
        references.append(
            CodingWindowsWorkerAttemptReferenceV1(
                attempt_id=attempt.attempt_id,
                plugin_id=policy.plugin_id,
                receipt_fingerprint=receipt_fingerprint,
                selected_package_revision_digest=policy.plugin_revision_digest,
                selected_locator_revision=policy.selected_locator_revision,
                native_platform="windows",
                launch_request_fingerprint=request_fingerprint,
            )
        )
    product.assert_root_gc_authority_current()
    return tuple(references)


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
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise CodingWindowsWorkerRecoveryAdmissionError(
                "coding_worker_offline_recovery_runtime_active"
            )
        with product.gc_gate.read_snapshot_guard() as gc_snapshot:
            return (
                _inspect_coding_windows_product_worker_offline_recovery_under_gc_guard(
                    product,
                    store_id=registry.store_id,
                    lease_owner_revision=quiescence.owner_revision,
                    gc_snapshot=gc_snapshot,
                )
            )


def _inspect_coding_windows_product_worker_offline_recovery_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    store_id: str,
    lease_owner_revision: int,
    gc_snapshot: PluginPackageGcReservationSnapshotV1,
) -> CodingWindowsWorkerOfflineRecoverySnapshotV1:
    """Join semantic histories under an already held Product quiescence/gate."""

    product.assert_root_gc_authority_current()
    native_provisioning_attempts = (
        inspect_coding_windows_product_worker_provisioning_attempts(product)
    )
    attempts = _inspect_windows_worker_recovery_inventory_under_gc_guard(
        product, native_attempts=native_provisioning_attempts
    )
    launch_intents = _inspect_intents_under_gc_guard(product)
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        opt_in_decisions = CodingWindowsWorkerOptInJournal(
            product.state_root / "worker-opt-in.jsonl",
            scope_id=product.policy.project_scope_id,
        ).history_read_only(directory_fd=root)
        receipt_records = CodingWindowsWorkerReceiptJournal(
            product.state_root / "worker-activation-receipts.jsonl",
            scope_id=product.policy.project_scope_id,
        ).records(directory_fd=root)
    supervisor_records = open_coding_windows_product_worker_supervisor_journal(
        product
    ).inspect_records()
    activation_journal = CodingWindowsWorkerActivationStateJournal(product)
    activation_owner_present, activation_state_records = (
        activation_journal.records_with_presence_read_only()
    )
    activation_state = (
        None if not activation_state_records else activation_state_records[-1].document
    )
    retained_activation_attempts = project_coding_worker_retained_attempts(
        activation_state_records
    )
    native_job_absence = tuple(
        (
            attempt.attempt_id,
            _observe_native_job_absence(attempt.native_job_name),
        )
        for attempt in attempts
    )
    worker_backup_observations = tuple(
        observe_coding_worker_backup_references_under_gc_guard(
            product, attempt_id=attempt.attempt_id
        )
        for attempt in attempts
    )
    product.assert_root_gc_authority_current()
    return CodingWindowsWorkerOfflineRecoverySnapshotV1(
        store_id=store_id,
        lease_owner_revision=lease_owner_revision,
        attempts=attempts,
        opt_in_decisions=opt_in_decisions,
        receipt_records=receipt_records,
        supervisor_records=supervisor_records,
        activation_state_owner_present=activation_owner_present,
        activation_state_revision=(
            0
            if activation_state is None
            else cast(int, activation_state["stateRevision"])
        ),
        retained_activation_attempts=retained_activation_attempts,
        native_job_absence=native_job_absence,
        gc_reservation_revision=gc_snapshot.journal_revision,
        gc_revision_refs=coding_worker_gc_revision_refs(gc_snapshot),
        worker_backup_observations=worker_backup_observations,
        activation_state_records=activation_state_records,
        launch_intents=launch_intents,
        native_provisioning_attempts=native_provisioning_attempts,
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
