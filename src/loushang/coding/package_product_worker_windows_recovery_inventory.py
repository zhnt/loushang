"""Read-only Windows Product Worker recovery inventory across retained owners.

This joins identities only. It cannot settle a Job, revoke an LPAC grant,
delete a payload, release a Package lease, or admit a fresh Worker attempt.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Literal, cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.records import PluginPackageRevisionRefV1
from loushang.harness.worker.journal import WorkerAttemptPhase

from .package_product_worker_gc_references import (
    matching_coding_worker_gc_revision_refs,
)
from .package_product_worker_windows_launch_intent import (
    _inspect_intents_under_gc_guard,
)
from .package_product_worker_windows_payload_inventory import (
    inspect_coding_windows_product_worker_payload_attempts,
)
from .package_product_worker_windows_provisioning import (
    inspect_coding_windows_product_worker_provisioning_attempts,
)
from .package_product_worker_windows_supervisor_journal import (
    open_coding_windows_product_worker_supervisor_journal,
)

_FINGERPRINT = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerRecoveryAttemptV1:
    """Observed attempt facts; no member grants launch or cleanup authority."""

    attempt_id: str
    payload_directory_identity: tuple[int, int] | None
    native_phase: str | None
    native_revision: int | None
    supervisor_phase: WorkerAttemptPhase | None
    supervisor_revision: int | None
    supervisor_process_settled: bool | None
    native_phase_history: tuple[str, ...] | None = None
    native_witness_present_history: tuple[bool, ...] | None = None
    native_witness_state: str | None = None
    native_worker_request_fingerprint: str | None = None
    native_receipt_fingerprint: str | None = None
    native_job_name: str | None = None
    supervisor_identity_fingerprint: str | None = None
    launch_request_fingerprint: str | None = None
    launch_receipt_fingerprint: str | None = None
    launch_identity_fingerprint: str | None = None
    launch_stage_identity: tuple[int, int] | None = None

    @property
    def clean_exit_settled(self) -> bool:
        """Require a launched Worker with complete native and process cleanup."""

        phases = self.native_phase_history
        witnesses = self.native_witness_present_history
        ordered = (
            "reserved",
            "profile_effect",
            "profile_created",
            "grant_effect",
            "grants_applied",
            "verified",
            "active",
            "cleaning",
            "revoke_effect",
            "grants_revoked",
            "delete_effect",
            "profile_deleted",
            "settled",
        )
        if (
            self.native_phase != "settled"
            or self.native_witness_state != "SETTLED"
            or self.supervisor_phase != "stopped"
            or self.supervisor_process_settled is not True
            or phases is None
            or witnesses is None
            or phases != ordered
            or witnesses != (False, False) + (True,) * (len(ordered) - 2)
            or self.native_revision != len(ordered)
            or self.observed_debts != ("payload_retained", "launch_intent_retained")
        ):
            return False
        return True

    @property
    def observed_debts(self) -> tuple[str, ...]:
        debts: list[str] = []
        if self.payload_directory_identity is None:
            debts.append("payload_missing")
        else:
            debts.append("payload_retained")
        if self.launch_request_fingerprint is None:
            debts.append("launch_intent_missing")
        else:
            debts.append("launch_intent_retained")
            if (
                self.payload_directory_identity is not None
                and self.launch_stage_identity != self.payload_directory_identity
            ):
                debts.append("launch_stage_mismatch")
        if self.native_phase is None:
            debts.append("native_history_missing")
        else:
            if self.native_phase != "settled":
                debts.append("native_unsettled")
            if (
                self.launch_request_fingerprint is None
                or self.native_worker_request_fingerprint
                != self.launch_request_fingerprint
                or self.native_receipt_fingerprint != self.launch_receipt_fingerprint
            ):
                debts.append("native_launch_identity_mismatch")
        if self.supervisor_phase is None:
            debts.append("supervisor_history_missing")
        else:
            if not self.supervisor_process_settled:
                debts.append("supervisor_unsettled")
            if (
                self.launch_identity_fingerprint is None
                or self.supervisor_identity_fingerprint
                != self.launch_identity_fingerprint
            ):
                debts.append("supervisor_launch_identity_mismatch")
        return tuple(debts)


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerOfflineRecoverySnapshotV1:
    """One lease-quiescent, no-effect view for a later recovery decision."""

    store_id: str
    lease_owner_revision: int
    attempts: tuple[CodingWindowsWorkerRecoveryAttemptV1, ...]


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
    matching_revision_refs: tuple[PluginPackageRevisionRefV1, ...]


class CodingWindowsWorkerRecoveryAdmissionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def require_coding_windows_worker_current_attempt(
    inventory: tuple[CodingWindowsWorkerRecoveryAttemptV1, ...],
    *,
    attempt_id: str,
    payload_directory_identity: tuple[int, int],
    initial: bool,
    request_fingerprint: str | None,
    receipt_fingerprint: str | None,
    identity_fingerprint: str | None,
) -> None:
    """Refuse replay, foreign debt, and an already-settled launch request."""

    if (
        type(inventory) is not tuple
        or type(attempt_id) is not str
        or type(payload_directory_identity) is not tuple
        or len(payload_directory_identity) != 2
        or type(initial) is not bool
        or (
            initial
            and any(
                value is not None
                for value in (
                    request_fingerprint,
                    receipt_fingerprint,
                    identity_fingerprint,
                )
            )
        )
        or (
            not initial
            and any(
                type(value) is not str or _FINGERPRINT.fullmatch(value) is None
                for value in (
                    request_fingerprint,
                    receipt_fingerprint,
                    identity_fingerprint,
                )
            )
        )
    ):
        raise TypeError("Windows Worker current-attempt input is invalid")
    if (
        len(inventory) != 1
        or type(inventory[0]) is not CodingWindowsWorkerRecoveryAttemptV1
        or inventory[0].attempt_id != attempt_id
        or inventory[0].payload_directory_identity != payload_directory_identity
        or (
            inventory[0].launch_request_fingerprint is None
            and any(
                value is not None
                for value in (
                    inventory[0].launch_receipt_fingerprint,
                    inventory[0].launch_identity_fingerprint,
                    inventory[0].launch_stage_identity,
                )
            )
        )
        or (
            inventory[0].native_phase is None
            and (
                inventory[0].native_worker_request_fingerprint is not None
                or inventory[0].native_receipt_fingerprint is not None
            )
        )
        or (
            inventory[0].supervisor_phase is None
            and inventory[0].supervisor_identity_fingerprint is not None
        )
        or (
            initial
            and (
                inventory[0].native_phase is not None
                or inventory[0].supervisor_phase is not None
                or inventory[0].launch_request_fingerprint is not None
            )
        )
        or (
            not initial
            and (
                inventory[0].native_phase == "settled"
                or inventory[0].supervisor_process_settled is True
                or (
                    inventory[0].launch_request_fingerprint is not None
                    and (
                        inventory[0].launch_request_fingerprint != request_fingerprint
                        or inventory[0].launch_receipt_fingerprint
                        != receipt_fingerprint
                        or inventory[0].launch_identity_fingerprint
                        != identity_fingerprint
                        or inventory[0].launch_stage_identity
                        != payload_directory_identity
                    )
                )
                or (
                    inventory[0].launch_request_fingerprint is None
                    and (
                        inventory[0].native_phase is not None
                        or inventory[0].supervisor_phase is not None
                    )
                )
                or (
                    inventory[0].native_phase is not None
                    and (
                        inventory[0].native_worker_request_fingerprint
                        != request_fingerprint
                        or inventory[0].native_receipt_fingerprint
                        != receipt_fingerprint
                    )
                )
                or (
                    inventory[0].supervisor_phase is not None
                    and inventory[0].supervisor_identity_fingerprint
                    != identity_fingerprint
                )
            )
        )
    ):
        raise CodingWindowsWorkerRecoveryAdmissionError(
            "coding_worker_payload_recovery_required"
        )


def require_coding_windows_worker_terminal_cleanup_attempt(
    inventory: tuple[CodingWindowsWorkerRecoveryAttemptV1, ...],
    *,
    attempt_id: str,
    payload_directory_identity: tuple[int, int],
    request_fingerprint: str,
    receipt_fingerprint: str,
    identity_fingerprint: str,
) -> str:
    """Return the exact Job name only after this attempt's process settled."""

    if (
        type(inventory) is not tuple
        or type(attempt_id) is not str
        or type(payload_directory_identity) is not tuple
        or len(payload_directory_identity) != 2
        or any(type(value) is not int or value < 1 for value in payload_directory_identity)
        or any(
            type(value) is not str or _FINGERPRINT.fullmatch(value) is None
            for value in (
                request_fingerprint,
                receipt_fingerprint,
                identity_fingerprint,
            )
        )
    ):
        raise TypeError("Windows Worker terminal cleanup input is invalid")
    if len(inventory) != 1 or type(inventory[0]) is not CodingWindowsWorkerRecoveryAttemptV1:
        raise CodingWindowsWorkerRecoveryAdmissionError(
            "coding_worker_payload_recovery_required"
        )
    attempt = inventory[0]
    if (
        attempt.attempt_id != attempt_id
        or attempt.payload_directory_identity != payload_directory_identity
        or attempt.launch_stage_identity != payload_directory_identity
        or attempt.launch_request_fingerprint != request_fingerprint
        or attempt.launch_receipt_fingerprint != receipt_fingerprint
        or attempt.launch_identity_fingerprint != identity_fingerprint
        or attempt.native_phase is None
        or attempt.native_worker_request_fingerprint != request_fingerprint
        or attempt.native_receipt_fingerprint != receipt_fingerprint
        or type(attempt.native_job_name) is not str
        or not attempt.native_job_name
        or attempt.supervisor_phase not in {"stopped", "process_settled"}
        or attempt.supervisor_process_settled is not True
        or attempt.supervisor_identity_fingerprint != identity_fingerprint
    ):
        raise CodingWindowsWorkerRecoveryAdmissionError(
            "coding_worker_payload_recovery_required"
        )
    return attempt.native_job_name


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
    with product.gc_gate.read_guard() as reservations:
        references = _inspect_windows_worker_attempt_references_under_gc_guard(
            product
        )
        return tuple(
            CodingWindowsWorkerAttemptGcObservationV1(
                attempt_reference=reference,
                active_gc_reservation_count=len(reservations),
                matching_revision_refs=matching_coding_worker_gc_revision_refs(
                    plugin_id=reference.plugin_id,
                    package_content_digest=(
                        reference.selected_package_revision_digest
                    ),
                    reservations=reservations,
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
    receipt_by_fingerprint = {
        record.receipt.fingerprint: record for record in receipts
    }
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
                type(value) is not str
                or _FINGERPRINT.fullmatch(value) is None
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
                    attempt.native_worker_request_fingerprint
                    != request_fingerprint
                    or attempt.native_receipt_fingerprint
                    != receipt_fingerprint
                )
            )
            or (
                attempt.supervisor_phase is not None
                and attempt.supervisor_identity_fingerprint
                != identity_fingerprint
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
        attempts = inspect_coding_windows_product_worker_recovery_inventory(product)
        return CodingWindowsWorkerOfflineRecoverySnapshotV1(
            store_id=registry.store_id,
            lease_owner_revision=quiescence.owner_revision,
            attempts=attempts,
        )


def _inspect_windows_worker_recovery_inventory_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
) -> tuple[CodingWindowsWorkerRecoveryAttemptV1, ...]:
    """Reuse one already-held Product GC gate for a pre-effect admission check."""

    if os.name != "nt" or type(product) is not WindowsLocalWheelProductSessionOwner:
        raise OSError("Windows Worker recovery inventory requires a Product owner")
    product.assert_root_gc_authority_current()
    from .package_product_worker_windows_stage_retirement import (
        _inspect_retirement_attempt_ids_under_gc_guard,
    )

    retirement_attempts = _inspect_retirement_attempt_ids_under_gc_guard(product)
    payloads = {
        item.attempt_id: item
        for item in inspect_coding_windows_product_worker_payload_attempts(product)
    }
    intents = {
        item.attempt_id: item for item in _inspect_intents_under_gc_guard(product)
    }
    native = {
        item.attempt_id: item
        for item in inspect_coding_windows_product_worker_provisioning_attempts(product)
    }
    supervisor_records = open_coding_windows_product_worker_supervisor_journal(
        product
    ).inspect_records()
    supervisor = {item.attempt_id: item for item in supervisor_records}
    attempts = []
    for attempt_id in sorted(
        payloads.keys()
        | intents.keys()
        | native.keys()
        | supervisor.keys()
        | retirement_attempts
    ):
        payload = payloads.get(attempt_id)
        intent = intents.get(attempt_id)
        provisioned = native.get(attempt_id)
        supervised = supervisor.get(attempt_id)
        attempts.append(
            CodingWindowsWorkerRecoveryAttemptV1(
                attempt_id=attempt_id,
                payload_directory_identity=(
                    None if payload is None else payload.directory_identity
                ),
                native_phase=(None if provisioned is None else provisioned.phase),
                native_revision=(
                    None if provisioned is None else provisioned.state_revision
                ),
                native_phase_history=(
                    None if provisioned is None else provisioned.phase_history
                ),
                native_witness_present_history=(
                    None if provisioned is None else provisioned.witness_present_history
                ),
                native_witness_state=(
                    None if provisioned is None else provisioned.last_witness_state
                ),
                native_worker_request_fingerprint=(
                    None
                    if provisioned is None
                    else cast(str, provisioned.identity["workerRequestFingerprint"])
                ),
                native_receipt_fingerprint=(
                    None
                    if provisioned is None
                    else cast(str, provisioned.identity["receiptFingerprint"])
                ),
                native_job_name=(
                    None
                    if provisioned is None
                    else cast(str, provisioned.identity["jobObjectName"])
                ),
                supervisor_phase=(None if supervised is None else supervised.phase),
                supervisor_revision=(
                    None if supervised is None else supervised.record_revision
                ),
                supervisor_process_settled=(
                    None if supervised is None else supervised.process_settled
                ),
                supervisor_identity_fingerprint=(
                    None if supervised is None else supervised.identity_fingerprint
                ),
                launch_request_fingerprint=(
                    None if intent is None else intent.request_fingerprint
                ),
                launch_receipt_fingerprint=(
                    None if intent is None else intent.receipt_fingerprint
                ),
                launch_identity_fingerprint=(
                    None if intent is None else intent.identity_fingerprint
                ),
                launch_stage_identity=(
                    None if intent is None else intent.stage_identity
                ),
            )
        )
    product.assert_root_gc_authority_current()
    return tuple(attempts)


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
