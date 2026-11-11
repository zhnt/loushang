"""Offline Linux Worker recovery over the existing Product and Worker owners.

Lease repair, payload repair and C5 CAS remain independent durable operations.
Bindings contain product values, actual DTO/errors and original owner types;
all evidence reads and mutations execute here, never through Code IO callbacks.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Generic, Protocol, TypeVar, cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeLeaseV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.history._activation import _RetainedAttemptFields
from loushang.harness.worker.history._activation_store import SegmentedActivationJournal
from loushang.harness.worker.history._no_effect import is_no_effect_closure
from loushang.harness.worker.history._receipts import _ReceiptRecordMethods
from loushang.harness.worker.history._retention import (
    AttemptReference,
    RegisteredRepairReference,
    RetentionReviewMethods,
    registered_repair_matches_no_effect_closure,
)
from loushang.harness.worker.history._start_gate import _StartGateRecordMethods
from loushang.harness.worker.journal import WorkerAttemptRecordV1
from loushang.harness.worker.payload._records import PayloadPlan
from loushang.harness.worker.payload._repair import RepairJournal
from loushang.harness.worker.payload._storage import _DIR_FLAGS
from loushang.harness.worker.product_activation import (
    ActivationWitness,
    ProductWorkerActivationCoordinator,
    ProductWorkerActivationReceiptV1,
    WorkerCleanupDebtV1,
    WorkerCleanupSettlementV1,
    _CleanupDebtReason,
)
from loushang.hosting.errors import HostingError
from loushang.hosting.machine_identity import linux_machine_key
from loushang.hosting.service_group import linux_current_boot_id

from ._linux_worker_history import (
    HistoryProofBindings,
    require_settled_history,
    review_gated_offline,
    review_history,
    review_history_under_guard,
)

if TYPE_CHECKING:
    from _typeshed import DataclassInstance
HistoryReview = RetentionReviewMethods[AttemptReference]
HistoryT = TypeVar("HistoryT")
_ATTEMPT = re.compile("[0-9a-f]{32}\\Z")
_STALE_WITNESS: ActivationWitness = ("0" * 64, "0" * 64, "stale", 0, 0)


class RegisteredReview(Protocol):
    @property
    def attempt_id(self) -> str: ...

    @property
    def gate_record(self) -> _StartGateRecordMethods | None: ...

    @property
    def activation_attempt(self) -> _RetainedAttemptFields | None: ...

    @property
    def supervisor_attempt(self) -> WorkerAttemptRecordV1 | None: ...

    @property
    def receipt_record(self) -> _ReceiptRecordMethods | None: ...

    @property
    def orphan_lease(self) -> PackageEpochRuntimeLeaseV1 | None: ...

    @property
    def payload_plan(self) -> PayloadPlan | None: ...

    @property
    def host_identity(self) -> str: ...

    @property
    def current_boot_identity(self) -> str: ...

    @property
    def runtime_epoch(self) -> int: ...

    @property
    def store_root_identity(self) -> str: ...

    @property
    def unrecognized_worker_state_names(self) -> tuple[str, ...]: ...

    @property
    def repaired_orphan_lease(self) -> PackageEpochRuntimeLeaseV1 | None: ...

    @property
    def repaired_owner_revision(self) -> int | None: ...

    @property
    def registered_candidate(self) -> bool: ...

    @property
    def repair_candidate(self) -> bool: ...

    @property
    def payload_repair_candidate(self) -> bool: ...


class RegisteredIntent(RegisteredRepairReference, Protocol):
    @property
    def lease_id(self) -> str: ...


@dataclass(frozen=True, slots=True)
class RecoveryBindings(Generic[HistoryT]):
    history: HistoryProofBindings[HistoryT]
    registered_review: Callable[..., RegisteredReview]
    intent: Callable[..., RegisteredIntent]
    recovery_error: type[Exception]
    payload_error: type[Exception]
    registered_c5_error: type[Exception]
    crash_c5_error: type[Exception]
    cleanup_type: Callable[..., CleanupEvidenceAuthority[HistoryT]]
    under_guard_type: Callable[..., UnderGuardCleanupEvidenceAuthority[HistoryT]]
    registered_cleanup_type: Callable[..., RegisteredCleanupEvidenceAuthority[HistoryT]]
    state_store_type: Callable[..., ProductActivationStateStore]
    host_domain: str
    cleanup_owner_message: str


def _activation_journal(
    bindings: RecoveryBindings[HistoryT], path: Path, *, scope_id: str, store_id: str
) -> SegmentedActivationJournal:
    return bindings.history.activation_type()(
        path, scope_id=scope_id, store_id=store_id
    )


def _registered_journal(
    bindings: RecoveryBindings[HistoryT],
) -> RepairJournal[RegisteredIntent]:
    return cast(RepairJournal[RegisteredIntent], bindings.history.registered())


def _read_receipt(
    bindings: RecoveryBindings[HistoryT],
    product: PosixLocalWheelProductSessionOwner,
    *,
    receipt_fingerprint: str,
) -> _ReceiptRecordMethods | None:
    if not isinstance(product, PosixLocalWheelProductSessionOwner):
        raise TypeError(
            f"{bindings.history.product_label} Worker Product owner is required"
        )
    if (
        type(receipt_fingerprint) is not str
        or len(receipt_fingerprint) != 64
        or any((char not in "0123456789abcdef" for char in receipt_fingerprint))
    ):
        raise ValueError(
            f"{bindings.history.product_label} Worker receipt fingerprint is invalid"
        )
    return bindings.history.receipts(product).find_retained_record(receipt_fingerprint)


class CleanupEvidenceAuthority(Generic[HistoryT]):
    """Revalidate one original Linux attempt before C5 tree settlement."""

    authority_id: ClassVar[str]
    authority_fingerprint: ClassVar[str]

    def __init__(
        self,
        product: PosixLocalWheelProductSessionOwner,
        bindings: RecoveryBindings[HistoryT],
    ) -> None:
        if (
            type(product) is not PosixLocalWheelProductSessionOwner
            or product.policy.product_id != bindings.history.product_id
        ):
            raise ValueError(bindings.cleanup_owner_message)
        product.assert_root_gc_authority_current()
        self._product = product
        self._bindings = bindings

    @property
    def host_identity(self) -> str:
        return linux_machine_key(domain=self._bindings.host_domain)

    @property
    def boot_identity(self) -> str:
        return linux_current_boot_id()

    def current_tree_witness(self, *, attempt_id: str) -> HistoryT:
        """Capture a review that the verifier must reopen and match exactly."""
        return review_history(
            self._bindings.history, self._product, attempt_id=attempt_id
        )

    def _complete_repair_verified(
        self, *, review: HistoryT, receipt_fingerprint: str, attempt_id: str
    ) -> bool:
        facts = cast(HistoryReview, review)
        exact_name = f"worker-complete-repair-{attempt_id}.json"
        matching = tuple(
            (
                name
                for name in facts.retained_payload_repair_reference_names
                if name.endswith(f"-{attempt_id}.json")
            )
        )
        if not matching:
            return True
        if matching != (exact_name,) or facts.attempt_record is None:
            return False
        try:
            with self._product.pinned_state_root_gc_read() as root_fd:
                if self._bindings.history.payload()._stage_exists(root_fd, attempt_id):
                    return False
                completed = self._bindings.history.payload().complete.read(
                    root_fd, attempt_id
                )
        except (self._bindings.history.payload().error_type, OSError, ValueError):
            return False
        return bool(
            completed is not None
            and completed[0].attempt_id == attempt_id
            and (completed[0].receipt_fingerprint == receipt_fingerprint)
            and (
                completed[1]
                == sha256(
                    canonical_json_bytes(facts.attempt_record.to_dict())
                ).hexdigest()
            )
        )

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
        return self._verify_tree_review(
            receipt_fingerprint=receipt_fingerprint,
            attempt_id=attempt_id,
            owner_generation=owner_generation,
            host_identity=host_identity,
            boot_identity=boot_identity,
            witness=witness,
            evidence_authority_id=evidence_authority_id,
            evidence_authority_fingerprint=evidence_authority_fingerprint,
            group_status="absent",
            current_boot_identity=None,
        )

    def _verify_tree_review(
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
        group_status: str,
        current_boot_identity: str | None,
    ) -> bool:
        if (
            type(witness) is not self._bindings.history.review()
            or type(receipt_fingerprint) is not str
            or type(attempt_id) is not str
            or (type(owner_generation) is not int)
            or (owner_generation < 1)
            or (type(host_identity) is not str)
            or (type(boot_identity) is not str)
            or (evidence_authority_id != self.authority_id)
            or (evidence_authority_fingerprint != self.authority_fingerprint)
        ):
            return False
        try:
            if host_identity != self.host_identity:
                return False
            if current_boot_identity is None:
                if boot_identity != self.boot_identity:
                    return False
            elif (
                current_boot_identity != self.boot_identity
                or current_boot_identity == boot_identity
            ):
                return False
            fresh = cast(
                HistoryReview, self.current_tree_witness(attempt_id=attempt_id)
            )
        except (HostingError, OSError, RuntimeError, ValueError):
            return False
        if fresh != witness:
            return False
        gate = fresh.gate_record
        supervisor = fresh.attempt_record
        receipt = fresh.receipt_record
        backup = fresh.worker_backup_references
        c5_references = tuple(
            (
                item
                for item in fresh.retained_activation_references
                if item.attempt_id == attempt_id
            )
        )
        return bool(
            gate is not None
            and gate.phase == "bound"
            and (gate.identity is not None)
            and (gate.identity.boot_id == boot_identity)
            and (gate.receipt_fingerprint == receipt_fingerprint)
            and (supervisor is not None)
            and supervisor.process_settled
            and (supervisor.identity_fingerprint == gate.worker_identity_fingerprint)
            and (receipt is not None)
            and (receipt.receipt.fingerprint == receipt_fingerprint)
            and (receipt.receipt.policy.product_id == self._bindings.history.product_id)
            and (receipt.receipt.policy.product_scope_id == gate.scope_id)
            and (receipt.receipt.policy.fingerprint == gate.policy_fingerprint)
            and (fresh.group_status == group_status)
            and (
                group_status != "prior_boot_absent"
                or (
                    fresh.history_stream_revisions_match
                    and fresh.historical_opt_in_verified
                )
            )
            and (len(c5_references) == 1)
            and (c5_references[0].receipt_fingerprint == receipt_fingerprint)
            and (c5_references[0].policy_fingerprint == gate.policy_fingerprint)
            and (c5_references[0].owner_generation == owner_generation)
            and (c5_references[0].host_identity == host_identity)
            and (c5_references[0].boot_identity == boot_identity)
            and (c5_references[0].phase in {"retired", "cleanup_debt", "settled"})
            and (f"worker-payload-{attempt_id}" not in fresh.payload_stage_names)
            and self._complete_repair_verified(
                review=cast(HistoryT, fresh),
                receipt_fingerprint=receipt_fingerprint,
                attempt_id=attempt_id,
            )
            and (not fresh.unrecognized_worker_state_names)
            and (backup is not None)
            and (backup.attempt_id == attempt_id)
            and (backup.worker_backup_supported is False)
            and (not backup.references)
        )

    def verify_changed_boot_absence(
        self,
        *,
        receipt_fingerprint: str,
        attempt_id: str,
        owner_generation: int,
        host_identity: str,
        boot_identity: str,
        current_boot_identity: str,
        witness: object,
        evidence_authority_id: str,
        evidence_authority_fingerprint: str,
    ) -> bool:
        return self._verify_tree_review(
            receipt_fingerprint=receipt_fingerprint,
            attempt_id=attempt_id,
            owner_generation=owner_generation,
            host_identity=host_identity,
            boot_identity=boot_identity,
            witness=witness,
            evidence_authority_id=evidence_authority_id,
            evidence_authority_fingerprint=evidence_authority_fingerprint,
            group_status="prior_boot_absent",
            current_boot_identity=current_boot_identity,
        )

    def verify_registered_lease_expired(self, **_arguments: object) -> bool:
        return False


class ClosedLinuxCrashRecoveryAuthority:
    """Serialize C5 changes while refusing any fresh Worker admission."""

    def __init__(self, product: PosixLocalWheelProductSessionOwner) -> None:
        self._product = product

    @contextmanager
    def serialized_admission(self) -> Iterator[None]:
        with self._product.gc_gate.guard(require_write=True):
            self._product.assert_root_gc_authority_current()
            yield
            self._product.assert_root_gc_authority_current()

    def current_witness(
        self, _receipt: ProductWorkerActivationReceiptV1
    ) -> ActivationWitness:
        return _STALE_WITNESS

    def latch_kill_switch(self, *, expected_generation: int) -> int:
        raise ValueError("Linux crash recovery cannot change Worker admission")


class UnderGuardCleanupEvidenceAuthority(CleanupEvidenceAuthority[HistoryT]):
    """Read fresh C5 evidence inside the caller's runtime and GC locks."""

    def __init__(
        self,
        product: PosixLocalWheelProductSessionOwner,
        *,
        bindings: RecoveryBindings[HistoryT],
        active_runtime_lease_ids: tuple[str, ...],
        gc_snapshot: PluginPackageGcReservationSnapshotV1,
    ) -> None:
        CleanupEvidenceAuthority.__init__(self, product, bindings)
        self._active_runtime_lease_ids = active_runtime_lease_ids
        self._gc_snapshot = gc_snapshot

    def current_tree_witness(self, *, attempt_id: str) -> HistoryT:
        return review_history_under_guard(
            self._bindings.history,
            self._product,
            attempt_id=attempt_id,
            active_runtime_lease_ids=self._active_runtime_lease_ids,
            gc_snapshot=self._gc_snapshot,
        )


class RegisteredCleanupEvidenceAuthority(UnderGuardCleanupEvidenceAuthority[HistoryT]):
    def __init__(
        self,
        product: PosixLocalWheelProductSessionOwner,
        *,
        bindings: RecoveryBindings[HistoryT],
        review: RegisteredReview,
        active_runtime_lease_ids: tuple[str, ...],
        gc_snapshot: PluginPackageGcReservationSnapshotV1,
    ) -> None:
        UnderGuardCleanupEvidenceAuthority.__init__(
            self,
            product,
            bindings=bindings,
            active_runtime_lease_ids=active_runtime_lease_ids,
            gc_snapshot=gc_snapshot,
        )
        self._registered_review = review

    def _verify_registered_review(
        self,
        *,
        receipt_fingerprint: str,
        attempt_id: str,
        owner_generation: int,
        host_identity: str,
        boot_identity: str,
        current_boot_identity: str,
        witness: object,
        evidence_authority_id: str,
        evidence_authority_fingerprint: str,
    ) -> bool:
        review = self._registered_review
        c5 = review.activation_attempt
        if (
            type(witness) is not self._bindings.history.review()
            or c5 is None
            or (not review.payload_repair_candidate)
            or (attempt_id != review.attempt_id)
            or (receipt_fingerprint != c5.receipt_fingerprint)
            or (owner_generation != c5.owner_generation)
            or (host_identity != c5.host_identity)
            or (host_identity != self.host_identity)
            or (boot_identity != c5.boot_identity)
            or (current_boot_identity != review.current_boot_identity)
            or (current_boot_identity != self.boot_identity)
            or (current_boot_identity == boot_identity)
            or (evidence_authority_id != self.authority_id)
            or (evidence_authority_fingerprint != self.authority_fingerprint)
        ):
            return False
        try:
            fresh = self.current_tree_witness(attempt_id=attempt_id)
            if fresh != witness:
                return False
            _require_registered_witness(
                self._bindings, self._product, review=review, witness=fresh
            )
        except (OSError, RuntimeError, ValueError):
            return False
        return True

    def verify_registered_lease_expired(self, **arguments: object) -> bool:
        verify: Callable[..., bool] = self._verify_registered_review
        return verify(**arguments)


class ProductActivationStateStore:
    """Product epoch/GC custody around the original C5 journal, with no new state."""

    def __init__(
        self,
        product: PosixLocalWheelProductSessionOwner,
        journal: SegmentedActivationJournal,
    ) -> None:
        self._product = product
        self._journal = journal

    @property
    def path(self) -> Path:
        return self._journal.path

    def load(self) -> Mapping[str, object] | None:
        with self._product.gc_gate.guard(require_write=True):
            self._product.assert_root_gc_authority_current()
            current = self._journal.load()
            self._product.assert_root_gc_authority_current()
            return current

    def compare_and_swap(
        self, *, expected_revision: int, document: Mapping[str, object]
    ) -> bool:
        with self._product.gc_gate.guard(require_write=True):
            self._product.assert_root_gc_authority_current()
            committed = self._journal.compare_and_swap(
                expected_revision=expected_revision, document=document
            )
            self._product.assert_root_gc_authority_current()
            return committed


def review_registered_orphan(
    bindings: RecoveryBindings[HistoryT],
    product: PosixLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
) -> RegisteredReview:
    """Join exact C5, gate, payload, and orphan lease without changing them."""
    if (
        not sys.platform.startswith("linux")
        or type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != bindings.history.product_id
        or (type(attempt_id) is not str)
        or (_ATTEMPT.fullmatch(attempt_id) is None)
    ):
        raise bindings.recovery_error(
            f"{bindings.history.product_id}_worker_registered_product_unsupported"
        )
    registry = product.epoch_runtime.registry
    orphans = registry.review_orphans(store_id=registry.store_id)
    with product.gc_gate.guard():
        product.assert_root_gc_authority_current()
        gate = bindings.history.gates(product).current(attempt_id)
        supervisor = bindings.history.supervisor(product).status(attempt_id)
        journal = _activation_journal(
            bindings,
            product.state_root / "worker-activation-state.jsonl",
            scope_id=product.policy.project_scope_id,
            store_id=registry.store_id,
        )
        matching = tuple(
            (
                item
                for item in journal.retained_attempts_read_only()
                if item.attempt_id == attempt_id
            )
        )
        c5 = matching[0] if len(matching) == 1 else None
        receipt = (
            None
            if gate is None
            else _read_receipt(
                bindings, product, receipt_fingerprint=gate.receipt_fingerprint
            )
        )
        matching_orphans = (
            ()
            if receipt is None
            else tuple(
                (
                    item
                    for item in orphans
                    if item.runtime_id == receipt.receipt.policy.product_runtime_id
                )
            )
        )
        with product.pinned_state_root_gc_read() as root_fd:
            bindings.history.payload()._require_private_visible_root(
                product.state_root, root_fd
            )
            state_names = tuple(os.listdir(root_fd))
            unrecognized = tuple(
                sorted(
                    (
                        name
                        for name in state_names
                        if name.casefold().startswith(("worker-", ".worker-"))
                        and (not bindings.history.known_state_name(name))
                    )
                )
            )
            prior_repair = _registered_journal(bindings).read(root_fd, attempt_id)
            plan = (
                prior_repair.plan
                if prior_repair is not None
                else bindings.history.payload()._verify_debt(root_fd, attempt_id)
                if bindings.history.payload()._stage_exists(root_fd, attempt_id)
                else None
            )
        fence = product.epoch_runtime.cutover_result.fence
        if fence is None:
            raise bindings.recovery_error(
                f"{bindings.history.product_id}_worker_registered_fence_unavailable"
            )
        evidence = bindings.cleanup_type(product)
        product.assert_root_gc_authority_current()
        review = bindings.registered_review(
            attempt_id=attempt_id,
            gate_record=gate,
            activation_attempt=c5,
            supervisor_attempt=supervisor,
            receipt_record=receipt,
            orphan_lease=matching_orphans[0] if len(matching_orphans) == 1 else None,
            payload_plan=plan,
            host_identity=evidence.host_identity,
            current_boot_identity=evidence.boot_identity,
            runtime_epoch=fence.epoch,
            store_root_identity=fence.fenced_root_identity,
            unrecognized_worker_state_names=unrecognized,
        )
    repaired = (
        None
        if receipt is None
        else registry.repaired_orphan_for_runtime(
            store_id=registry.store_id,
            runtime_id=receipt.receipt.policy.product_runtime_id,
        )
    )
    return cast(
        RegisteredReview,
        replace(
            cast("DataclassInstance", review),
            repaired_orphan_lease=None if repaired is None else repaired[1],
            repaired_owner_revision=None if repaired is None else repaired[0],
        ),
    )


def repair_registered_orphan(
    bindings: RecoveryBindings[HistoryT],
    product: PosixLocalWheelProductSessionOwner,
    *,
    expected_review: RegisteredReview,
) -> PackageEpochRuntimeLeaseV1:
    """Repair only the dead runtime lease; payload and C5 remain separate."""
    if type(expected_review) is not bindings.registered_review:
        raise TypeError("Registered Worker orphan review must be exact")
    current = review_registered_orphan(
        bindings, product, attempt_id=expected_review.attempt_id
    )
    if current != expected_review:
        raise bindings.recovery_error(
            f"{bindings.history.product_id}_worker_registered_review_stale"
        )
    if not current.repair_candidate or current.orphan_lease is None:
        raise bindings.recovery_error(
            f"{bindings.history.product_id}_worker_registered_orphan_unproven"
        )
    product.epoch_runtime.registry.repair_orphan(
        current.orphan_lease.lease_id, require_exclusive_active=True
    )
    return current.orphan_lease


def recover_registered_no_effect(
    bindings: RecoveryBindings[HistoryT],
    product: PosixLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
) -> _RetainedAttemptFields:
    """Run exact, independently retryable lease, payload, and C5 owners."""
    review = review_registered_orphan(bindings, product, attempt_id=attempt_id)
    if review.repair_candidate:
        repair_registered_orphan(bindings, product, expected_review=review)
        review = review_registered_orphan(bindings, product, attempt_id=attempt_id)
    if review.payload_repair_candidate:
        repair_registered_payload(bindings, product, expected_review=review)
    return settle_registered_c5(bindings, product, attempt_id=attempt_id)


def _expected_intent(
    bindings: RecoveryBindings[HistoryT], review: RegisteredReview
) -> RegisteredIntent:
    if (
        not review.payload_repair_candidate
        or review.payload_plan is None
        or review.gate_record is None
        or (review.receipt_record is None)
        or (review.activation_attempt is None)
        or (review.repaired_orphan_lease is None)
    ):
        raise bindings.payload_error(
            f"{bindings.history.product_id}_worker_registered_payload_repair_unproven"
        )
    c5 = review.activation_attempt
    return bindings.intent(
        plan=review.payload_plan,
        gate_record_digest=review.gate_record.record_digest,
        receipt_record_digest=review.receipt_record.record_digest,
        policy_fingerprint=c5.policy_fingerprint,
        lease_id=review.repaired_orphan_lease.lease_id,
        host_identity=c5.host_identity,
        boot_identity=c5.boot_identity,
        owner_generation=c5.owner_generation,
    )


def read_registered_intent(
    bindings: RecoveryBindings[HistoryT],
    product: PosixLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
) -> RegisteredIntent | None:
    """Read the durable record, including during a partial stage deletion."""
    with product.gc_gate.guard():
        product.assert_root_gc_authority_current()
        with product.pinned_state_root_gc_read() as root_fd:
            bindings.history.payload()._require_private_visible_root(
                product.state_root, root_fd
            )
            return _registered_journal(bindings).read(root_fd, attempt_id)


def _require_same_registered_evidence(
    bindings: RecoveryBindings[HistoryT],
    product: PosixLocalWheelProductSessionOwner,
    review: RegisteredReview,
) -> None:
    gate = bindings.history.gates(product).current(review.attempt_id)
    supervisor = bindings.history.supervisor(product).status(review.attempt_id)
    journal = _activation_journal(
        bindings,
        product.state_root / "worker-activation-state.jsonl",
        scope_id=product.policy.project_scope_id,
        store_id=product.epoch_runtime.registry.store_id,
    )
    matching = tuple(
        (
            item
            for item in journal.retained_attempts_read_only()
            if item.attempt_id == review.attempt_id
        )
    )
    receipt = (
        None
        if gate is None
        else _read_receipt(
            bindings, product, receipt_fingerprint=gate.receipt_fingerprint
        )
    )
    evidence = bindings.cleanup_type(product)
    if (
        gate != review.gate_record
        or supervisor is not None
        or len(matching) != 1
        or (matching[0] != review.activation_attempt)
        or (receipt != review.receipt_record)
        or (evidence.host_identity != review.host_identity)
        or (evidence.boot_identity != review.current_boot_identity)
    ):
        raise bindings.payload_error(
            f"{bindings.history.product_id}_worker_registered_payload_repair_stale"
        )


def repair_registered_payload(
    bindings: RecoveryBindings[HistoryT],
    product: PosixLocalWheelProductSessionOwner,
    *,
    expected_review: RegisteredReview,
) -> RegisteredIntent:
    """Publish exact intent, then remove only the verified original stage."""
    if type(expected_review) is not bindings.registered_review:
        raise TypeError("Registered Worker payload review must be exact")
    intent = _expected_intent(bindings, expected_review)
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(store_id=registry.store_id) as quiet:
        if (
            quiet.active_runtime_lease_ids
            or quiet.owner_revision != expected_review.repaired_owner_revision
        ):
            raise bindings.payload_error(
                f"{bindings.history.product_id}_worker_registered_payload_runtime_changed"
            )
        product.assert_root_gc_authority_current()
        with product.gc_gate.guard(require_write=True):
            _require_same_registered_evidence(bindings, product, expected_review)
            with product.pinned_state_root_gc_read() as root_fd:
                bindings.history.payload()._require_private_visible_root(
                    product.state_root, root_fd
                )
                if any(
                    (
                        name.casefold().startswith(("worker-", ".worker-"))
                        and (not bindings.history.known_state_name(name))
                        for name in os.listdir(root_fd)
                    )
                ):
                    raise bindings.payload_error(
                        f"{bindings.history.product_id}_worker_registered_payload_inventory_changed"
                    )
                prior = _registered_journal(bindings).read(root_fd, intent.attempt_id)
                if prior is not None and prior != intent:
                    raise bindings.payload_error(
                        f"{bindings.history.product_id}_worker_registered_payload_repair_stale"
                    )
                if not bindings.history.payload()._stage_exists(
                    root_fd, intent.attempt_id
                ):
                    if prior is None:
                        raise bindings.payload_error(
                            f"{bindings.history.product_id}_worker_registered_payload_stage_absent"
                        )
                    _registered_journal(bindings).settle(
                        root_fd, intent.attempt_id, intent
                    )
                    return intent
                if (
                    prior is None
                    and bindings.history.payload()._verify_debt(
                        root_fd, intent.attempt_id
                    )
                    != intent.plan
                ):
                    raise bindings.payload_error(
                        f"{bindings.history.product_id}_worker_registered_payload_plan_stale"
                    )
                stage_name = f"worker-payload-{intent.attempt_id}"
                stage_fd = os.open(stage_name, _DIR_FLAGS, dir_fd=root_fd)
                try:
                    bindings.history.payload()._verify_complete_repair_remainder(
                        root_fd, stage_fd, stage_name, intent.plan
                    )
                    _registered_journal(bindings).publish(
                        root_fd, intent.attempt_id, intent
                    )
                    _require_same_registered_evidence(
                        bindings, product, expected_review
                    )
                    bindings.history.payload()._verify_complete_repair_remainder(
                        root_fd, stage_fd, stage_name, intent.plan
                    )
                    if prior is None:
                        bindings.history.payload()._remove_verified_stage(
                            root_fd, stage_fd, stage_name, intent.plan
                        )
                    else:
                        bindings.history.payload()._remove_partial_stage(
                            root_fd, stage_fd, stage_name, intent.plan.entrypoint
                        )
                finally:
                    os.close(stage_fd)
        product.assert_root_gc_authority_current()
    return intent


def _require_registered_witness(
    bindings: RecoveryBindings[HistoryT],
    product: PosixLocalWheelProductSessionOwner,
    *,
    review: RegisteredReview,
    witness: HistoryT,
) -> None:
    """Accept the one expected transient unbound-gate shape and no other debt."""
    facts = cast(HistoryReview, witness)
    gate = review.gate_record
    receipt = review.receipt_record
    c5 = review.activation_attempt
    if (
        not review.payload_repair_candidate
        or gate is None
        or receipt is None
        or (c5 is None)
        or (facts.gate_record != gate)
        or (facts.receipt_record != receipt)
        or (facts.attempt_record is not None)
        or (not facts.historical_opt_in_verified)
        or (not facts.history_stream_revisions_match)
        or (not facts.global_activation_reference_ids_match)
        or facts.global_unverified_opt_in_references
        or facts.unbound_supervisor_attempt_ids
        or facts.unrecognized_worker_state_names
        or facts.payload_stage_names
        or facts.active_runtime_lease_ids
        or (
            facts.active_activation_references
            != ((receipt.receipt.fingerprint, review.attempt_id),)
        )
        or (review.attempt_id not in facts.receipt_gate_references)
        or (facts.unsettled_receipt_gate_references != (review.attempt_id,))
        or (
            facts.global_unverified_activation_references
            != ((review.attempt_id, "activation_reference_gate_unbound"),)
        )
        or (
            facts.global_unverified_receipt_gate_references
            != ((review.attempt_id, "receipt_reference_gate_unbound"),)
        )
        or (
            tuple(
                (
                    item
                    for item in facts.retained_activation_references
                    if item.attempt_id == review.attempt_id
                )
            )
            != (c5,)
        )
        or (
            tuple(
                (
                    name
                    for name in facts.retained_payload_repair_reference_names
                    if name.endswith(f"-{review.attempt_id}.json")
                )
            )
            != (f"worker-registered-repair-{review.attempt_id}.json",)
        )
    ):
        raise bindings.registered_c5_error(
            f"{bindings.history.product_id}_worker_registered_c5_history_unverified"
        )
    backup = facts.worker_backup_references
    if (
        backup is None
        or backup.attempt_id != review.attempt_id
        or backup.worker_backup_supported is not False
        or backup.references
    ):
        raise bindings.registered_c5_error(
            f"{bindings.history.product_id}_worker_registered_c5_backup_unverified"
        )
    with product.pinned_state_root_gc_read() as root_fd:
        if bindings.history.payload()._stage_exists(
            root_fd, review.attempt_id
        ) or _registered_journal(bindings).read(
            root_fd, review.attempt_id
        ) != _expected_intent(bindings, review):
            raise bindings.registered_c5_error(
                f"{bindings.history.product_id}_worker_registered_c5_payload_unverified"
            )


def _reopen_settled_registered_c5(
    bindings: RecoveryBindings[HistoryT],
    product: PosixLocalWheelProductSessionOwner,
    review: RegisteredReview,
) -> _RetainedAttemptFields:
    c5 = review.activation_attempt
    gate = review.gate_record
    receipt = review.receipt_record
    registry = product.epoch_runtime.registry
    if (
        c5 is None
        or gate is None
        or receipt is None
        or (review.supervisor_attempt is not None)
        or (review.repaired_orphan_lease is None)
        or (review.repaired_owner_revision is None)
        or (review.orphan_lease is not None)
        or review.unrecognized_worker_state_names
        or (c5.host_identity != review.host_identity)
        or (c5.boot_identity == review.current_boot_identity)
        or (
            not is_no_effect_closure(
                gate=gate,
                activation=c5,
                supervisor=None,
                receipt=receipt,
                product_id=bindings.history.product_id,
            )
        )
    ):
        raise bindings.registered_c5_error(
            f"{bindings.history.product_id}_worker_registered_c5_recovery_incomplete"
        )
    with registry.exclusive_runtime_quiescence(store_id=registry.store_id) as quiet:
        if (
            quiet.active_runtime_lease_ids
            or quiet.owner_revision != review.repaired_owner_revision
        ):
            raise bindings.registered_c5_error(
                f"{bindings.history.product_id}_worker_registered_c5_runtime_changed"
            )
        with product.gc_gate.guard(require_write=True):
            product.assert_root_gc_authority_current()
            with product.pinned_state_root_gc_read() as root_fd:
                intent = _registered_journal(bindings).read(root_fd, review.attempt_id)
                names = tuple(os.listdir(root_fd))
                if (
                    intent is None
                    or bindings.history.payload()._stage_exists(
                        root_fd, review.attempt_id
                    )
                    or (
                        not registered_repair_matches_no_effect_closure(
                            intent,
                            gate=gate,
                            receipt=receipt,
                            activation=c5,
                            supervisor=None,
                            product_id=bindings.history.product_id,
                        )
                    )
                    or (intent.lease_id != review.repaired_orphan_lease.lease_id)
                ):
                    raise bindings.registered_c5_error(
                        f"{bindings.history.product_id}_worker_registered_c5_settlement_unverified"
                    )
            require_settled_history(bindings.history, product, observed_names=names)
            journal = _activation_journal(
                bindings,
                product.state_root / "worker-activation-state.jsonl",
                scope_id=product.policy.project_scope_id,
                store_id=registry.store_id,
            )
            if tuple(
                (
                    item
                    for item in journal.retained_attempts_read_only()
                    if item.attempt_id == review.attempt_id
                )
            ) != (c5,):
                raise bindings.registered_c5_error(
                    f"{bindings.history.product_id}_worker_registered_c5_settlement_changed"
                )
            product.assert_root_gc_authority_current()
            return c5


def settle_registered_c5(
    bindings: RecoveryBindings[HistoryT],
    product: PosixLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
) -> _RetainedAttemptFields:
    """Reopen exact no-effect evidence under runtime and GC locks, then CAS C5."""
    if (
        not sys.platform.startswith("linux")
        or type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != bindings.history.product_id
    ):
        raise bindings.registered_c5_error(
            f"{bindings.history.product_id}_worker_registered_c5_product_unsupported"
        )
    review = review_registered_orphan(bindings, product, attempt_id=attempt_id)
    if (
        review.activation_attempt is not None
        and review.activation_attempt.phase == "settled"
    ):
        return _reopen_settled_registered_c5(bindings, product, review)
    if not review.payload_repair_candidate or review.receipt_record is None:
        raise bindings.registered_c5_error(
            f"{bindings.history.product_id}_worker_registered_c5_recovery_incomplete"
        )
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(store_id=registry.store_id) as quiet:
        if (
            quiet.active_runtime_lease_ids
            or quiet.owner_revision != review.repaired_owner_revision
        ):
            raise bindings.registered_c5_error(
                f"{bindings.history.product_id}_worker_registered_c5_runtime_changed"
            )
        with product.gc_gate.guard(require_write=True):
            product.assert_root_gc_authority_current()
            evidence = bindings.registered_cleanup_type(
                product,
                review=review,
                active_runtime_lease_ids=quiet.active_runtime_lease_ids,
                gc_snapshot=product.gc_gate.snapshot(),
            )
            witness = evidence.current_tree_witness(attempt_id=attempt_id)
            _require_registered_witness(
                bindings, product, review=review, witness=witness
            )
            journal = _activation_journal(
                bindings,
                product.state_root / "worker-activation-state.jsonl",
                scope_id=product.policy.project_scope_id,
                store_id=registry.store_id,
            )
            state = journal.load()
            attempts = None if state is None else state.get("attempts")
            if not isinstance(attempts, Mapping):
                raise bindings.registered_c5_error(
                    f"{bindings.history.product_id}_worker_registered_c5_state_unavailable"
                )
            exact = tuple(
                (
                    item
                    for item in attempts.values()
                    if isinstance(item, Mapping) and item.get("attemptId") == attempt_id
                )
            )
            if (
                len(exact) != 1
                or exact[0].get("phase") != "registered"
                or exact[0].get("evidenceAuthorityId") != evidence.authority_id
                or (
                    exact[0].get("evidenceAuthorityFingerprint")
                    != evidence.authority_fingerprint
                )
            ):
                raise bindings.registered_c5_error(
                    f"{bindings.history.product_id}_worker_registered_c5_attempt_changed"
                )
            coordinator = ProductWorkerActivationCoordinator(
                authority=ClosedLinuxCrashRecoveryAuthority(product),
                evidence_authority=evidence,
                trusted_evidence_authority_id=evidence.authority_id,
                trusted_evidence_authority_fingerprint=evidence.authority_fingerprint,
                state_store=bindings.state_store_type(product),
            )
            receipt = review.receipt_record.receipt
            coordinator.recover_registered_no_effect(
                receipt=receipt,
                attempt_id=attempt_id,
                owner_generation=receipt.policy.owner_selection_generation,
                current_boot_identity=evidence.boot_identity,
                witness=witness,
            )
            retained = tuple(
                (
                    item
                    for item in journal.retained_attempts_read_only()
                    if item.attempt_id == attempt_id
                )
            )
            if (
                len(retained) != 1
                or retained[0].phase != "settled"
                or (not retained[0].no_effect)
            ):
                raise bindings.registered_c5_error(
                    f"{bindings.history.product_id}_worker_registered_c5_settlement_unverified"
                )
            product.assert_root_gc_authority_current()
            return retained[0]


def settle_crash_c5(
    bindings: RecoveryBindings[HistoryT],
    product: PosixLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
) -> _RetainedAttemptFields:
    """Retire and settle C5 under one offline runtime and GC transaction."""
    if (
        not sys.platform.startswith("linux")
        or type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != bindings.history.product_id
    ):
        raise bindings.crash_c5_error(
            f"{bindings.history.product_id}_worker_crash_c5_product_unsupported"
        )
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(store_id=registry.store_id) as quiet:
        if quiet.active_runtime_lease_ids:
            raise bindings.crash_c5_error(
                f"{bindings.history.product_id}_worker_crash_c5_runtime_active"
            )
        with product.gc_gate.guard(require_write=True):
            product.assert_root_gc_authority_current()
            result = _settle_crash_c5_under_guard(
                bindings,
                product,
                attempt_id=attempt_id,
                active_runtime_lease_ids=quiet.active_runtime_lease_ids,
                gc_snapshot=product.gc_gate.snapshot(),
            )
            product.assert_root_gc_authority_current()
            return result


def _settle_crash_c5_under_guard(
    bindings: RecoveryBindings[HistoryT],
    product: PosixLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    active_runtime_lease_ids: tuple[str, ...],
    gc_snapshot: PluginPackageGcReservationSnapshotV1,
) -> _RetainedAttemptFields:
    review = review_gated_offline(bindings.history, product, attempt_id=attempt_id)
    gate = review.gate_record
    supervisor = review.attempt_record
    if (
        gate is None
        or gate.phase != "bound"
        or gate.identity is None
        or (supervisor is None)
        or (not supervisor.process_settled)
        or (supervisor.phase != "process_settled")
        or (not review.native_closure_current)
        or (review.group_status not in {"absent", "prior_boot_absent"})
    ):
        raise bindings.crash_c5_error(
            f"{bindings.history.product_id}_worker_crash_c5_recovery_incomplete"
        )
    record = _read_receipt(
        bindings, product, receipt_fingerprint=gate.receipt_fingerprint
    )
    if (
        record is None
        or record.receipt.policy.product_id != bindings.history.product_id
        or record.receipt.policy.fingerprint != gate.policy_fingerprint
        or (record.receipt.policy.product_scope_id != gate.scope_id)
        or (supervisor.identity_fingerprint != gate.worker_identity_fingerprint)
    ):
        raise bindings.crash_c5_error(
            f"{bindings.history.product_id}_worker_crash_c5_receipt_changed"
        )
    with product.pinned_state_root_gc_read() as root_fd:
        if bindings.history.payload()._stage_exists(root_fd, attempt_id):
            raise bindings.crash_c5_error(
                f"{bindings.history.product_id}_worker_crash_c5_payload_live"
            )
        completed = bindings.history.payload().complete.read(root_fd, attempt_id)
    if (
        completed is None
        or completed[0].receipt_fingerprint != record.receipt.fingerprint
        or completed[1]
        != sha256(canonical_json_bytes(supervisor.to_dict())).hexdigest()
    ):
        raise bindings.crash_c5_error(
            f"{bindings.history.product_id}_worker_crash_c5_payload_unproven"
        )
    journal = _activation_journal(
        bindings,
        product.state_root / "worker-activation-state.jsonl",
        scope_id=product.policy.project_scope_id,
        store_id=product.epoch_runtime.registry.store_id,
    )
    retained = tuple(
        (
            item
            for item in journal.retained_attempts_read_only()
            if item.attempt_id == attempt_id
        )
    )
    if len(retained) != 1:
        raise bindings.crash_c5_error(
            f"{bindings.history.product_id}_worker_crash_c5_attempt_unavailable"
        )
    [c5] = retained
    receipt = record.receipt
    evidence = bindings.under_guard_type(
        product,
        active_runtime_lease_ids=active_runtime_lease_ids,
        gc_snapshot=gc_snapshot,
    )
    if (
        c5.receipt_fingerprint != receipt.fingerprint
        or c5.policy_fingerprint != receipt.policy.fingerprint
        or c5.owner_generation != receipt.policy.owner_selection_generation
        or (c5.cleanup_contract_version != 1)
        or (c5.host_identity != evidence.host_identity)
        or (c5.boot_identity != gate.identity.boot_id)
        or (
            review.group_status == "absent"
            and c5.boot_identity != evidence.boot_identity
        )
        or (
            review.group_status == "prior_boot_absent"
            and c5.boot_identity == evidence.boot_identity
        )
        or (not c5.current)
    ):
        raise bindings.crash_c5_error(
            f"{bindings.history.product_id}_worker_crash_c5_attempt_changed"
        )
    state = journal.load()
    attempts = None if state is None else state.get("attempts")
    if not isinstance(attempts, Mapping):
        raise bindings.crash_c5_error(
            f"{bindings.history.product_id}_worker_crash_c5_state_unavailable"
        )
    exact = tuple(
        (
            item
            for item in attempts.values()
            if isinstance(item, Mapping) and item.get("attemptId") == attempt_id
        )
    )
    if (
        len(exact) != 1
        or exact[0].get("evidenceAuthorityId") != evidence.authority_id
        or exact[0].get("evidenceAuthorityFingerprint")
        != evidence.authority_fingerprint
        or (exact[0].get("phase") != c5.phase)
    ):
        raise bindings.crash_c5_error(
            f"{bindings.history.product_id}_worker_crash_c5_evidence_changed"
        )
    if c5.phase == "settled":
        if exact[0].get("cleanupSettlement") is None:
            raise bindings.crash_c5_error(
                f"{bindings.history.product_id}_worker_crash_c5_settlement_unverified"
            )
        return c5
    coordinator = ProductWorkerActivationCoordinator(
        authority=ClosedLinuxCrashRecoveryAuthority(product),
        evidence_authority=evidence,
        trusted_evidence_authority_id=evidence.authority_id,
        trusted_evidence_authority_fingerprint=evidence.authority_fingerprint,
        state_store=bindings.state_store_type(product),
    )
    generation = receipt.policy.owner_selection_generation
    coordinator.retire_exact(
        receipt=receipt, attempt_id=attempt_id, owner_generation=generation
    )
    coordinator.record_protocol_terminal(
        receipt=receipt, attempt_id=attempt_id, owner_generation=generation
    )
    if review.group_status == "prior_boot_absent":
        if c5.phase != "cleanup_debt":
            coordinator.record_cleanup_debt(
                WorkerCleanupDebtV1(
                    receipt_fingerprint=receipt.fingerprint,
                    attempt_id=attempt_id,
                    owner_generation=generation,
                    host_identity=evidence.host_identity,
                    boot_identity=c5.boot_identity,
                    reason=_CleanupDebtReason.SAME_BOOT_UNKNOWN_TREE,
                )
            )
        witness = evidence.current_tree_witness(attempt_id=attempt_id)
        coordinator.settle_changed_boot_absence(
            receipt=receipt,
            attempt_id=attempt_id,
            owner_generation=generation,
            current_boot_identity=evidence.boot_identity,
            witness=witness,
        )
    else:
        witness = evidence.current_tree_witness(attempt_id=attempt_id)
        coordinator.record_cleanup_settlement(
            WorkerCleanupSettlementV1(
                receipt_fingerprint=receipt.fingerprint,
                attempt_id=attempt_id,
                owner_generation=generation,
                host_identity=evidence.host_identity,
                boot_identity=c5.boot_identity,
                protocol_terminal=True,
                domain_retired=True,
                tree_settled=True,
            ),
            witness=witness,
        )
    [settled] = (
        item
        for item in journal.retained_attempts_read_only()
        if item.attempt_id == attempt_id
    )
    if settled.phase != "settled":
        raise bindings.crash_c5_error(
            f"{bindings.history.product_id}_worker_crash_c5_settlement_unverified"
        )
    return settled
