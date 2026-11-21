"""Retained Windows Worker facts and pure identity proofs; no native authority."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Generic, Protocol, Self, TypeVar, cast

from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeLeaseV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
    PackageEpochRuntimeLeaseRecordV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsRuntimeQuiescenceV1,
)

from .._native_profile_bridge import _WindowsNativeContainmentSettlementWitness
from .._windows_provisioning_journal import WindowsWorkerProvisioningAttemptV1
from ..journal import WorkerAttemptPhase, WorkerAttemptRecordV1
from ..product_activation import ProductWorkerActivationReceiptV1
from ._activation import _RetainedAttemptFields
from ._base_codec import _BaseWireMethods
from ._opt_in import _OptInDecisionMethods
from ._receipts import _ReceiptRecordMethods

_FINGERPRINT = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class WindowsRecoveryAttemptV1:
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

        return self.supervisor_phase == "stopped" and self._retained_native_exit_settled

    @property
    def fenced_exit_settled(self) -> bool:
        """Require the same cleanup after a fenced process was physically reaped."""

        return (
            self.supervisor_phase == "process_settled"
            and self._retained_native_exit_settled
        )

    @property
    def _retained_native_exit_settled(self) -> bool:

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


_CRASH_PHASES = frozenset(
    {
        "profile_effect",
        "profile_created",
        "grant_effect",
        "grants_applied",
        "verified",
        "active",
        "debt",
        "cleaning",
        "revoke_effect",
        "grants_revoked",
        "delete_effect",
        "profile_deleted",
    }
)
_TRANSITIONS: dict[str, frozenset[str]] = {
    "reserved": frozenset({"profile_effect", "settled"}),
    "profile_effect": frozenset({"profile_created", "debt", "cleaning", "settled"}),
    "profile_created": frozenset({"grant_effect", "debt", "cleaning"}),
    "grant_effect": frozenset({"grants_applied", "debt", "cleaning"}),
    "grants_applied": frozenset({"verified", "debt", "cleaning"}),
    "verified": frozenset({"active", "debt", "cleaning"}),
    "active": frozenset({"debt", "cleaning"}),
    "debt": frozenset({"cleaning"}),
    "cleaning": frozenset({"revoke_effect", "debt"}),
    "revoke_effect": frozenset({"grants_revoked", "debt", "cleaning"}),
    "grants_revoked": frozenset({"delete_effect", "debt"}),
    "delete_effect": frozenset({"profile_deleted", "debt"}),
    "profile_deleted": frozenset({"settled", "debt"}),
    "settled": frozenset(),
}


def _valid_crash_effect_history(
    attempt: WindowsRecoveryAttemptV1, *, settled: bool
) -> bool:
    phases = attempt.native_phase_history
    witnesses = attempt.native_witness_present_history
    ending = "settled" if settled else attempt.native_phase
    if (
        phases is None
        or witnesses is None
        or not phases
        or phases[0] != "reserved"
        or (phases[-1] != "settled" if settled else phases[-1] not in _CRASH_PHASES)
        or phases[-1] != ending
        or len(phases) != len(witnesses)
        or len(phases) != attempt.native_revision
    ):
        return False
    if settled and (
        attempt.native_witness_state != "SETTLED"
        or phases[-6:]
        != (
            "cleaning",
            "revoke_effect",
            "grants_revoked",
            "delete_effect",
            "profile_deleted",
            "settled",
        )
    ):
        return False
    for index, phase in enumerate(phases):
        if phase not in _TRANSITIONS:
            return False
        if index and phase not in _TRANSITIONS[phases[index - 1]]:
            return False
        if witnesses[index] != (phase not in {"reserved", "profile_effect"}):
            return False
    return True


_AttemptT = TypeVar("_AttemptT", bound=WindowsRecoveryAttemptV1)


@dataclass(frozen=True, slots=True)
class WindowsRecoveryAdmission(Generic[_AttemptT]):
    attempt_type: type[_AttemptT]
    error_type: type[RuntimeError]
    required_code: str

    def require_current(
        self,
        inventory: tuple[_AttemptT, ...],
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
            or type(inventory[0]) is not self.attempt_type
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
                            inventory[0].launch_request_fingerprint
                            != request_fingerprint
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
            raise self.error_type(self.required_code)

    def require_native_release(
        self,
        inventory: tuple[_AttemptT, ...],
        *,
        attempt_id: str,
        payload_directory_identity: tuple[int, int],
        request_fingerprint: str,
        receipt_fingerprint: str,
        identity_fingerprint: str,
    ) -> str:
        """Identify an exact retained attempt in a terminal Supervisor phase.

        Hosting reaps the process tree before it closes native preparation. The
        Supervisor records process settlement only after that close completes, so
        native release must be allowed to finish while its terminal phase is fenced.
        This check does not certify physical settlement, C5 cleanup, or Package GC.
        """

        if (
            type(inventory) is not tuple
            or type(attempt_id) is not str
            or type(payload_directory_identity) is not tuple
            or len(payload_directory_identity) != 2
            or any(
                type(value) is not int or value < 1
                for value in payload_directory_identity
            )
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
        if len(inventory) != 1 or type(inventory[0]) is not self.attempt_type:
            raise self.error_type(self.required_code)
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
            or attempt.supervisor_phase
            not in {"stopped", "failed", "fenced", "process_settled"}
            or attempt.supervisor_identity_fingerprint != identity_fingerprint
        ):
            raise self.error_type(self.required_code)
        return attempt.native_job_name

    def require_terminal_cleanup(
        self,
        inventory: tuple[_AttemptT, ...],
        *,
        attempt_id: str,
        payload_directory_identity: tuple[int, int],
        request_fingerprint: str,
        receipt_fingerprint: str,
        identity_fingerprint: str,
    ) -> str:
        """Return the exact Job name only after this attempt's process settled."""

        job_name = self.require_native_release(
            inventory,
            attempt_id=attempt_id,
            payload_directory_identity=payload_directory_identity,
            request_fingerprint=request_fingerprint,
            receipt_fingerprint=receipt_fingerprint,
            identity_fingerprint=identity_fingerprint,
        )
        attempt = inventory[0]
        if (
            attempt.supervisor_phase not in {"stopped", "process_settled"}
            or attempt.supervisor_process_settled is not True
        ):
            raise self.error_type(self.required_code)
        return job_name


_PAYLOAD = (("payload_directory_identity", "directory_identity"),)
_NATIVE = (
    ("native_phase", "phase"),
    ("native_revision", "state_revision"),
    ("native_phase_history", "phase_history"),
    ("native_witness_present_history", "witness_present_history"),
    ("native_witness_state", "last_witness_state"),
)
_NATIVE_IDENTITY = (
    ("native_worker_request_fingerprint", "workerRequestFingerprint"),
    ("native_receipt_fingerprint", "receiptFingerprint"),
    ("native_job_name", "jobObjectName"),
)
_SUPERVISOR = (
    ("supervisor_phase", "phase"),
    ("supervisor_revision", "record_revision"),
    ("supervisor_process_settled", "process_settled"),
    ("supervisor_identity_fingerprint", "identity_fingerprint"),
)
_INTENT = (
    ("launch_request_fingerprint", "request_fingerprint"),
    ("launch_receipt_fingerprint", "receipt_fingerprint"),
    ("launch_identity_fingerprint", "identity_fingerprint"),
    ("launch_stage_identity", "stage_identity"),
)


def _project(
    source: object | None, fields: tuple[tuple[str, str], ...]
) -> dict[str, object]:
    return {
        target: None if source is None else getattr(source, attribute)
        for target, attribute in fields
    }


def project_windows_recovery_attempts(
    payloads: Mapping[str, object],
    intents: Mapping[str, object],
    native: Mapping[str, object],
    supervisor: Mapping[str, object],
    retirement_attempts: frozenset[str],
    *,
    record_type: type[_AttemptT],
) -> tuple[_AttemptT, ...]:
    result = []
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
        facts = _project(payload, _PAYLOAD)
        facts.update(_project(provisioned, _NATIVE))
        facts.update(
            {
                target: None
                if provisioned is None
                else getattr(provisioned, "identity")[key]
                for target, key in _NATIVE_IDENTITY
            }
        )
        facts.update(_project(supervised, _SUPERVISOR))
        facts.update(_project(intent, _INTENT))
        result.append(
            cast(Callable[..., _AttemptT], record_type)(attempt_id=attempt_id, **facts)
        )
    return tuple(result)


class _WindowsOfflineRecoveryMethods:
    __slots__ = ()
    opt_in_decisions: tuple[_OptInDecisionMethods, ...]
    receipt_records: tuple[_ReceiptRecordMethods, ...]
    supervisor_records: tuple[WorkerAttemptRecordV1, ...]

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


def require_windows_worker_c5_gc_history(
    state: Mapping[str, object] | None,
    retained: tuple[_RetainedAttemptFields, ...],
    inventory: tuple[WindowsRecoveryAttemptV1, ...],
    receipt_policies: Mapping[str, tuple[str, int]],
    native_job_absence: Mapping[str, bool | None],
) -> None:
    """Join settled C5 attempts to exact launched attempts and Product receipts."""

    if state is None:
        raise ValueError("Windows Worker GC C5 owner is incomplete")
    active = cast(dict[str, dict[str, object]], state["attempts"])
    publications = cast(dict[str, object], state["publications"])
    if publications or any(
        attempt["phase"] != "settled" for attempt in active.values()
    ):
        raise ValueError("Windows Worker GC C5 activation remains active")
    by_id = {item.attempt_id: item for item in retained}
    launched = {
        item.attempt_id: item
        for item in inventory
        if item.launch_request_fingerprint is not None
        or item.native_phase is not None
        or item.supervisor_phase is not None
    }
    if len(by_id) != len(retained) or set(by_id) != set(launched):
        raise ValueError("Windows Worker GC C5 attempt history is incomplete")
    for attempt_id, item in by_id.items():
        observed = launched[attempt_id]
        if (
            item.phase != "settled"
            or item.cleanup_contract_version != 2
            or observed.launch_receipt_fingerprint != item.receipt_fingerprint
            or receipt_policies.get(item.receipt_fingerprint)
            != (item.policy_fingerprint, item.owner_generation)
            or native_job_absence.get(attempt_id) is not True
        ):
            raise ValueError("Windows Worker GC C5 attempt history is incomplete")


_ReferenceT = TypeVar("_ReferenceT")


def project_windows_worker_attempt_references(
    attempts: tuple[WindowsRecoveryAttemptV1, ...],
    receipts: tuple[_ReceiptRecordMethods, ...],
    *,
    reference_type: Callable[..., _ReferenceT],
    product_id: str,
    error_type: type[RuntimeError],
    error_prefix: str,
) -> tuple[_ReferenceT, ...]:
    receipt_by_fingerprint = {record.receipt.fingerprint: record for record in receipts}
    if len(receipt_by_fingerprint) != len(receipts):
        raise error_type(error_prefix + "receipt_conflict")
    references: list[_ReferenceT] = []
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
                raise error_type(error_prefix + "intent_absent")
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
            or receipt.receipt.policy.product_id != product_id
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
            raise error_type(error_prefix + "binding_changed")
        policy = receipt.receipt.policy
        references.append(
            reference_type(
                attempt_id=attempt.attempt_id,
                plugin_id=policy.plugin_id,
                receipt_fingerprint=receipt_fingerprint,
                selected_package_revision_digest=policy.plugin_revision_digest,
                selected_locator_revision=policy.selected_locator_revision,
                native_platform="windows",
                launch_request_fingerprint=request_fingerprint,
            )
        )
    return tuple(references)


class _WindowsOrphanRuntimeReviewMethods:
    __slots__ = ()
    attempt_id: str
    attempt: WindowsRecoveryAttemptV1 | None
    receipt_record: _ReceiptRecordMethods | None
    orphan_leases: tuple[PackageEpochRuntimeLeaseV1, ...]
    runtime_epoch: int
    store_root_identity: str
    native_job_absent: bool | None

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
            or self.orphan_leases[0].store_root_identity != self.store_root_identity
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


def windows_worker_crash_cleanup_history_matches(
    review: _WindowsOrphanRuntimeReviewMethods,
) -> bool:
    attempt = review.attempt
    expected_debts = (
        ("payload_retained", "launch_intent_retained", "native_unsettled"),
        (
            "payload_retained",
            "launch_intent_retained",
            "native_unsettled",
            "supervisor_unsettled",
        ),
        (
            "payload_retained",
            "launch_intent_retained",
            "native_unsettled",
            "supervisor_history_missing",
        ),
    )
    return (
        not review.missing_proofs
        and attempt is not None
        and review.receipt_record is not None
        and attempt.observed_debts in expected_debts
        and _valid_crash_effect_history(attempt, settled=False)
        and attempt.payload_directory_identity is not None
        and attempt.native_revision is not None
    )


def windows_worker_crash_settled_history_matches(
    review: _WindowsOrphanRuntimeReviewMethods,
    *,
    repaired_lease: bool = False,
) -> bool:
    attempt = review.attempt
    return (
        review.missing_proofs == (("orphan_lease_absent",) if repaired_lease else ())
        and attempt is not None
        and review.receipt_record is not None
        and attempt.observed_debts
        in (
            ("payload_retained", "launch_intent_retained"),
            (
                "payload_retained",
                "launch_intent_retained",
                "supervisor_history_missing",
            ),
        )
        and (
            (attempt.supervisor_phase is None)
            or (
                attempt.supervisor_phase == "process_settled"
                and attempt.supervisor_process_settled is True
            )
        )
        and _valid_crash_effect_history(attempt, settled=True)
        and attempt.payload_directory_identity is not None
        and attempt.native_revision is not None
    )


def require_windows_worker_repair_record(
    quiescence: PackageWindowsRuntimeQuiescenceV1,
    *,
    runtime_id: str,
    expected: tuple[str, int] | None = None,
) -> PackageEpochRuntimeLeaseRecordV1:
    repaired = tuple(
        record
        for record in quiescence.repaired_runtime_records
        if record.lease.runtime_id == runtime_id
    )
    if len(repaired) != 1:
        raise ValueError("Windows Worker crash lease repair is unverified")
    [record] = repaired
    if record.record_revision >= quiescence.owner_revision or (
        expected is not None
        and (record.lease.lease_id, record.record_revision) != expected
    ):
        raise ValueError("Windows Worker crash lease repair revision changed")
    return record


WINDOWS_STAGE_RETIREMENT_RECEIPT_MAX_BYTES = 1024


class _WindowsStageRetirementReceiptMethods(_BaseWireMethods):
    __slots__ = ()
    attempt_id: str
    review_fingerprint: str
    stage_identity: tuple[int, int]
    receipt_version: int

    @classmethod
    def _wire_maximum(cls) -> int:
        return WINDOWS_STAGE_RETIREMENT_RECEIPT_MAX_BYTES

    def __post_init__(self) -> None:
        if (
            type(self.attempt_id) is not str
            or _WINDOWS_RETIREMENT_ATTEMPT.fullmatch(self.attempt_id) is None
            or type(self.review_fingerprint) is not str
            or _FINGERPRINT.fullmatch(self.review_fingerprint) is None
            or type(self.stage_identity) is not tuple
            or len(self.stage_identity) != 2
            or any(type(value) is not int or value < 0 for value in self.stage_identity)
            or self.stage_identity[1] == 0
            or type(self.receipt_version) is not int
            or self.receipt_version != 1
        ):
            raise ValueError("Windows Worker stage retirement receipt is invalid")

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self._wire_schema.encode(self))


_WINDOWS_RETIREMENT_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")


class WindowsLiveCleanupReview(Protocol):
    @property
    def runtime(self) -> _WindowsOrphanRuntimeReviewMethods: ...
    @property
    def native(self) -> WindowsWorkerProvisioningAttemptV1 | None: ...
    @property
    def activation(self) -> _RetainedAttemptFields | None: ...


_LiveReviewT = TypeVar("_LiveReviewT", bound=WindowsLiveCleanupReview)


class WindowsWorkerCleanupEvidence(ABC, Generic[_LiveReviewT]):
    """Exact read-only receipt/native/Supervisor/C5 join; no repair authority."""

    __slots__ = ()
    _review_type: type[_LiveReviewT]
    _product: object
    _receipt: ProductWorkerActivationReceiptV1
    _attempt_id: str
    _owner_generation: int
    _request_fingerprint: str
    _identity_fingerprint: str
    _mode: str
    authority_id: str
    authority_fingerprint: str

    @property
    @abstractmethod
    def host_identity(self) -> str: ...

    @property
    @abstractmethod
    def boot_identity(self) -> str: ...

    @abstractmethod
    def current_tree_witness(self, *, attempt_id: str) -> _LiveReviewT: ...

    @classmethod
    def _from_crash_recovery(
        cls,
        *,
        product: object,
        receipt: ProductWorkerActivationReceiptV1,
        attempt_id: str,
        review_runtime: Callable[..., _WindowsOrphanRuntimeReviewMethods],
    ) -> Self:
        """Bind a dead Session only from its persisted recovery join."""
        review = review_runtime(product, attempt_id=attempt_id)
        attempt = review.attempt
        if (
            attempt is None
            or review.receipt_record is None
            or review.receipt_record.receipt != receipt
            or attempt.launch_request_fingerprint is None
            or attempt.launch_identity_fingerprint is None
            or attempt.supervisor_process_settled is not True
            or attempt.supervisor_phase != "process_settled"
            or attempt.payload_directory_identity is not None
        ):
            raise ValueError("Windows C5 crash recovery history is incomplete")
        authority = cls.__new__(cls)
        setattr(authority, "_product", product)
        setattr(authority, "_receipt", receipt)
        setattr(authority, "_attempt_id", attempt_id)
        setattr(
            authority, "_owner_generation", receipt.policy.owner_selection_generation
        )
        setattr(authority, "_request_fingerprint", attempt.launch_request_fingerprint)
        setattr(authority, "_identity_fingerprint", attempt.launch_identity_fingerprint)
        setattr(authority, "_mode", "crash")
        return authority

    def _current_review_matches(
        self, *, witness: object, attempt_id: str
    ) -> _LiveReviewT | None:
        if type(witness) is not self._review_type:
            return None
        try:
            fresh = self.current_tree_witness(attempt_id=attempt_id)
        except (OSError, RuntimeError, ValueError):
            return None
        if fresh != witness:
            return None
        return fresh if self._review_matches(fresh) else None

    def _review_matches(self, fresh: _LiveReviewT) -> bool:
        runtime = fresh.runtime
        attempt = runtime.attempt
        record = runtime.receipt_record
        native = fresh.native
        activation = fresh.activation
        if (
            attempt is None
            or record is None
            or native is None
            or (activation is None)
            or runtime.orphan_leases
            or (runtime.native_job_absent is not True)
            or (
                not (
                    attempt.clean_exit_settled or attempt.fenced_exit_settled
                    if self._mode == "normal"
                    else attempt.supervisor_process_settled is True
                    and attempt.supervisor_phase == "process_settled"
                    and (attempt.payload_directory_identity is None)
                    and (
                        attempt.observed_debts
                        == ("payload_missing", "launch_intent_retained")
                    )
                    and _valid_crash_effect_history(attempt, settled=True)
                )
            )
            or (attempt.attempt_id != self._attempt_id)
            or (attempt.launch_request_fingerprint != self._request_fingerprint)
            or (attempt.launch_identity_fingerprint != self._identity_fingerprint)
            or (attempt.supervisor_identity_fingerprint != self._identity_fingerprint)
            or (attempt.launch_receipt_fingerprint != self._receipt.fingerprint)
            or (attempt.native_worker_request_fingerprint != self._request_fingerprint)
            or (attempt.native_receipt_fingerprint != self._receipt.fingerprint)
            or (record.receipt != self._receipt)
            or (native.phase != "settled")
            or (native.last_witness_state != "SETTLED")
            or (native.settlement_fingerprint is None)
            or (native.phase_history != attempt.native_phase_history)
            or (
                native.witness_present_history != attempt.native_witness_present_history
            )
            or (native.state_revision != attempt.native_revision)
            or (native.identity.get("receiptFingerprint") != self._receipt.fingerprint)
            or (
                native.identity.get("workerRequestFingerprint")
                != self._request_fingerprint
            )
            or (native.identity.get("ownerGeneration") != self._owner_generation)
            or (native.identity.get("jobObjectName") != attempt.native_job_name)
            or (activation.phase != "retired")
            or (activation.cleanup_contract_version != 2)
            or (activation.receipt_fingerprint != self._receipt.fingerprint)
            or (activation.policy_fingerprint != self._receipt.policy.fingerprint)
            or (activation.owner_generation != self._owner_generation)
            or (activation.host_identity != self.host_identity)
            or (activation.boot_identity != self.boot_identity)
        ):
            return False
        return True

    def verify_tree_settlement(
        self,
        *,
        receipt_fingerprint: str,
        attempt_id: str,
        owner_generation: int,
        host_identity: str,
        boot_identity: str,
        witness: object,
        evidence_authority_id: str,
        evidence_authority_fingerprint: str,
    ) -> bool:
        if not self._identity_matches(
            receipt_fingerprint=receipt_fingerprint,
            attempt_id=attempt_id,
            owner_generation=owner_generation,
            host_identity=host_identity,
            boot_identity=boot_identity,
            evidence_authority_id=evidence_authority_id,
            evidence_authority_fingerprint=evidence_authority_fingerprint,
        ):
            return False
        return (
            self._current_review_matches(witness=witness, attempt_id=attempt_id)
            is not None
        )

    def verify_native_containment_settlement(
        self,
        *,
        receipt_fingerprint: str,
        attempt_id: str,
        owner_generation: int,
        host_identity: str,
        boot_identity: str,
        witness: object,
        evidence_authority_id: str,
        evidence_authority_fingerprint: str,
    ) -> bool:
        if (
            not self._identity_matches(
                receipt_fingerprint=receipt_fingerprint,
                attempt_id=attempt_id,
                owner_generation=owner_generation,
                host_identity=host_identity,
                boot_identity=boot_identity,
                evidence_authority_id=evidence_authority_id,
                evidence_authority_fingerprint=evidence_authority_fingerprint,
            )
            or type(witness) is not _WindowsNativeContainmentSettlementWitness
        ):
            return False
        try:
            fresh = self.current_tree_witness(attempt_id=attempt_id)
        except (OSError, RuntimeError, ValueError):
            return False
        native = fresh.native
        native_witness = cast(_WindowsNativeContainmentSettlementWitness, witness)
        return bool(
            native is not None
            and self._review_matches(fresh)
            and (native_witness.receipt_fingerprint == self._receipt.fingerprint)
            and (native_witness.worker_request_fingerprint == self._request_fingerprint)
            and (native_witness.attempt_id == attempt_id)
            and (native_witness.owner_generation == owner_generation)
            and (native_witness.journal_fingerprint == native.settlement_fingerprint)
        )

    def current_native_witness(self) -> _WindowsNativeContainmentSettlementWitness:
        """Derive the exact native witness from settled, rechecked Product bytes."""
        review = self.current_tree_witness(attempt_id=self._attempt_id)
        if not self._review_matches(review) or review.native is None:
            raise ValueError("Windows C5 native settlement is unproven")
        fingerprint = review.native.settlement_fingerprint
        assert fingerprint is not None
        return _WindowsNativeContainmentSettlementWitness(
            receipt_fingerprint=self._receipt.fingerprint,
            worker_request_fingerprint=self._request_fingerprint,
            attempt_id=self._attempt_id,
            owner_generation=self._owner_generation,
            journal_fingerprint=fingerprint,
        )

    def _identity_matches(
        self,
        *,
        receipt_fingerprint: str,
        attempt_id: str,
        owner_generation: int,
        host_identity: str,
        boot_identity: str,
        evidence_authority_id: str,
        evidence_authority_fingerprint: str,
    ) -> bool:
        return (
            receipt_fingerprint == self._receipt.fingerprint
            and attempt_id == self._attempt_id
            and (owner_generation == self._owner_generation)
            and (host_identity == self.host_identity)
            and (boot_identity == self.boot_identity)
            and (evidence_authority_id == self.authority_id)
            and (evidence_authority_fingerprint == self.authority_fingerprint)
        )
