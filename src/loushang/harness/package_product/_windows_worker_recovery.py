"""Read-only Windows Worker history at the existing Package Product boundary.

The fixed programs borrow the original journal, inventory, backup-policy and
retirement owners. Journal bindings are lazy constructors of those same owners;
no source fields or transaction stages are supplied through callbacks, and no
read operation acquires repair or deletion authority.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Generic, Protocol, Self, TypeVar, cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeLeaseV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsRuntimeQuiescenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    windows_listdir_at,
    windows_stat_at,
)
from loushang.harness.worker._native_profile_bridge import (
    _rebuild_windows_lpac_cleanup_spec,
)
from loushang.harness.worker._windows_provisioning_journal import (
    WindowsWorkerProvisioningAttemptV1,
    WindowsWorkerProvisioningStateJournal,
    inspect_windows_worker_provisioning_attempts,
)
from loushang.harness.worker.activation_state_journal import _StateRecord
from loushang.harness.worker.contracts import ManagedWorkerLaunchRequestV1
from loushang.harness.worker.history._activation import (
    _RetainedAttemptFields,
    project_retained_attempts,
)
from loushang.harness.worker.history._opt_in import _OptInDecisionMethods
from loushang.harness.worker.history._receipts import _ReceiptRecordMethods
from loushang.harness.worker.history._retention import (
    AttemptReference,
    gc_revision_refs,
    matching_gc_revision_refs,
)
from loushang.harness.worker.history._windows_product_journals import (
    WindowsActivationStateJournal,
    WindowsSupervisorJournal,
    settle_windows_crashed_supervisor_record,
)
from loushang.harness.worker.history._windows_recovery import (
    WindowsLiveCleanupReview,
    WindowsRecoveryAttemptV1,
    WindowsWorkerCleanupEvidence,
    _valid_crash_effect_history,
    _WindowsOrphanRuntimeReviewMethods,
    project_windows_worker_attempt_references,
    require_windows_worker_c5_gc_history,
)
from loushang.harness.worker.history._windows_recovery import (
    require_windows_worker_repair_record as _require_repair_record,
)
from loushang.harness.worker.history._windows_recovery import (
    windows_worker_crash_cleanup_history_matches as _crash_cleanup_history_matches,
)
from loushang.harness.worker.history._windows_recovery import (
    windows_worker_crash_settled_history_matches as _crash_settled_history_matches,
)
from loushang.harness.worker.history._windows_semantic_contracts import (
    _LaunchIntentFacts,
    _RecoveryFacts,
    launch_matches_intent,
)
from loushang.harness.worker.history._windows_sources import (
    WINDOWS_WORKER_BASE_STAGE_NAMES,
    windows_worker_history_names,
)
from loushang.harness.worker.history._windows_stage_review_wire import (
    _WindowsCompleteStageReviewMethods,
    _WindowsCrashStageReviewMethods,
    _WindowsPartialStageReviewMethods,
    _WindowsReservedStageReviewMethods,
    windows_worker_reserved_settled_document,
)
from loushang.harness.worker.journal import WorkerAttemptRecordV1
from loushang.harness.worker.payload._windows_stage_io import WindowsStageInspection
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationCoordinator,
    ProductWorkerActivationReceiptV1,
    WorkerCleanupSettlementV2,
    _ActivationStateStore,
)
from loushang.hosting import observe_windows_worker_job_absent
from loushang.hosting.windows_backend_material import (
    WINDOWS_LPAC_PLATFORM_IMPORTS,
    WindowsBackendMaterialExpectationV1,
)

from ._windows_worker_history import (
    ObserveWindowsWorkerBackup,
    ReadWindowsOfflineRecovery,
)
from ._worker_product_authority import (
    ClosedProductWorkerCrashRecoveryAuthority,
    _WindowsWorkerProductReceiptAuthority,
)
from ._worker_windows_attempt import (
    CapturedWindowsWorkerStage,
    _ReceiptJournalFactory,
    _RuntimeReview,
    capture_windows_product_worker_cleanup,
    require_windows_worker_retirement_root,
    review_windows_product_worker_offline,
    settle_windows_product_worker_native_cleanup,
    windows_product_worker_offline_write,
)

if TYPE_CHECKING:
    from ._windows_worker_retirement import (
        WindowsProductWorkerCrashStageRetirement,
        _RetirementLaunchIntent,
    )
from loushang.harness.worker.history._windows_recovery import (
    _WindowsStageRetirementReceiptMethods,
)

if TYPE_CHECKING:
    CrashStageRetirementProfile = WindowsProductWorkerCrashStageRetirement[
        _WindowsCrashStageReviewMethods,
        _WindowsStageRetirementReceiptMethods,
        _RetirementLaunchIntent,
    ]
    CrashEvidenceFactory = Callable[
        ..., WindowsWorkerCleanupEvidence[WindowsLiveCleanupReview]
    ]

_CRASH_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")


class _OptInHistory(Protocol):
    def history_read_only(
        self, *, directory_fd: int
    ) -> tuple[_OptInDecisionMethods, ...]: ...


class _ActivationHistory(Protocol):
    def load(self) -> Mapping[str, object] | None: ...
    def retained_attempts_read_only(self) -> tuple[_RetainedAttemptFields, ...]: ...
    def records_with_presence_read_only(
        self,
    ) -> tuple[bool, tuple[_StateRecord, ...]]: ...


@dataclass(frozen=True, slots=True)
class WindowsProductWorkerHistoryJournals:
    """The original nominal journal family, without eager reads or cached roots."""

    opt_in: Callable[..., _OptInHistory]
    receipt: _ReceiptJournalFactory[_ReceiptRecordMethods]
    activation: Callable[[WindowsLocalWheelProductSessionOwner], _ActivationHistory]
    supervisor: Callable[
        [WindowsLocalWheelProductSessionOwner], WindowsSupervisorJournal
    ]
    retained_type: type[_RetainedAttemptFields]


_AttemptT_co = TypeVar("_AttemptT_co", bound=WindowsRecoveryAttemptV1, covariant=True)
_AttemptT = TypeVar("_AttemptT", bound=WindowsRecoveryAttemptV1)
_SnapshotT = TypeVar("_SnapshotT", bound=_RecoveryFacts)
_ReferenceT = TypeVar("_ReferenceT")


class ReadWindowsRecoveryInventory(Protocol[_AttemptT_co]):
    def __call__(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        native_attempts: tuple[WindowsWorkerProvisioningAttemptV1, ...] | None = None,
    ) -> tuple[_AttemptT_co, ...]: ...


class _CurrentWindowsAttempts(Protocol[_AttemptT]):
    def __call__(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        inventory: tuple[_AttemptT, ...],
        *,
        attempt_id: str | None,
    ) -> tuple[_AttemptT, ...]: ...


def require_windows_product_worker_settled_history(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    journals: WindowsProductWorkerHistoryJournals,
    inspect_inventory: ReadWindowsRecoveryInventory[_AttemptT],
    current_attempts: _CurrentWindowsAttempts[_AttemptT],
    observe_job_absence: Callable[[str | None], bool | None],
    observed_names: tuple[str, ...],
    allow_preparation_stage: bool = False,
    allow_checkpoint_stage: bool = False,
    allow_base_stage: bool = False,
) -> None:
    if type(observed_names) is not tuple or any(
        type(name) is not str for name in observed_names
    ):
        raise ValueError("Windows Worker GC inventory is invalid")
    product.assert_root_gc_authority_current()
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        if set(windows_listdir_at(root)) != set(observed_names):
            raise ValueError("Windows Worker GC inventory changed")
        windows_worker_history_names().require_known(observed_names)
        if (
            (
                "worker-history-preparation-v1.json.stage" in observed_names
                and not allow_preparation_stage
            )
            or (
                "worker-history-checkpoint-v1.json.stage" in observed_names
                and not allow_checkpoint_stage
            )
            or (
                not allow_base_stage
                and WINDOWS_WORKER_BASE_STAGE_NAMES.intersection(observed_names)
            )
        ):
            raise ValueError("Windows Worker history preparation remains staged")

        inventory = inspect_inventory(product)
        if current_attempts(product, inventory, attempt_id=None):
            raise ValueError("Windows Worker GC attempt is unsettled")

        receipts = journals.receipt(
            product.state_root / "worker-activation-receipts.jsonl",
            scope_id=product.policy.project_scope_id,
        ).records(directory_fd=root)
        opt_in_decisions = journals.opt_in(
            product.state_root / "worker-opt-in.jsonl",
            scope_id=product.policy.project_scope_id,
        ).history_read_only(directory_fd=root)
        opt_in_by_digest = {
            decision.decision_digest: decision for decision in opt_in_decisions
        }
        if any(
            (decision := opt_in_by_digest.get(record.opt_in_decision_digest)) is None
            or decision.action != "allow"
            or decision.plugin_id != record.receipt.policy.plugin_id
            for record in receipts
        ):
            raise ValueError("Windows Worker GC opt-in history is incomplete")
        receipt_fingerprints = {record.receipt.fingerprint for record in receipts}
        if any(
            attempt.launch_receipt_fingerprint is not None
            and attempt.launch_receipt_fingerprint not in receipt_fingerprints
            for attempt in inventory
        ):
            raise ValueError("Windows Worker GC receipt history is incomplete")
        if any(name.startswith("worker-activation-state") for name in observed_names):
            journal = journals.activation(product)
            require_windows_worker_c5_gc_history(
                journal.load(),
                journal.retained_attempts_read_only(),
                inventory,
                {
                    record.receipt.fingerprint: (
                        record.receipt.policy.fingerprint,
                        record.receipt.policy.owner_selection_generation,
                    )
                    for record in receipts
                },
                {
                    attempt.attempt_id: observe_job_absence(attempt.native_job_name)
                    for attempt in inventory
                },
            )
        if set(windows_listdir_at(root)) != set(observed_names):
            raise ValueError("Windows Worker GC inventory changed")
    product.assert_root_gc_authority_current()


def capture_windows_product_worker_offline_recovery_under_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    journals: WindowsProductWorkerHistoryJournals,
    snapshot_type: Callable[..., _SnapshotT],
    inspect_native: Callable[
        [WindowsLocalWheelProductSessionOwner],
        tuple[WindowsWorkerProvisioningAttemptV1, ...],
    ],
    inspect_inventory: ReadWindowsRecoveryInventory[WindowsRecoveryAttemptV1],
    inspect_intents: Callable[
        [WindowsLocalWheelProductSessionOwner], tuple[_LaunchIntentFacts, ...]
    ],
    observe_job_absence: Callable[[str | None], bool | None],
    observe_backup: ObserveWindowsWorkerBackup,
    store_id: str,
    lease_owner_revision: int,
    gc_snapshot: PluginPackageGcReservationSnapshotV1,
) -> _SnapshotT:
    product.assert_root_gc_authority_current()
    native_provisioning_attempts = inspect_native(product)
    attempts = inspect_inventory(product, native_attempts=native_provisioning_attempts)
    launch_intents = inspect_intents(product)
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        opt_in_decisions = journals.opt_in(
            product.state_root / "worker-opt-in.jsonl",
            scope_id=product.policy.project_scope_id,
        ).history_read_only(directory_fd=root)
        receipt_records = journals.receipt(
            product.state_root / "worker-activation-receipts.jsonl",
            scope_id=product.policy.project_scope_id,
        ).records(directory_fd=root)
    supervisor_records = journals.supervisor(product).inspect_records()
    activation_journal = journals.activation(product)
    activation_owner_present, activation_state_records = (
        activation_journal.records_with_presence_read_only()
    )
    activation_state = (
        None if not activation_state_records else activation_state_records[-1].document
    )
    retained_activation_attempts = project_retained_attempts(
        activation_state_records, record_type=journals.retained_type
    )
    native_job_absence = tuple(
        (
            attempt.attempt_id,
            observe_job_absence(attempt.native_job_name),
        )
        for attempt in attempts
    )
    worker_backup_observations = tuple(
        observe_backup(product, attempt_id=attempt.attempt_id) for attempt in attempts
    )
    product.assert_root_gc_authority_current()
    return snapshot_type(
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
        gc_revision_refs=gc_revision_refs(gc_snapshot),
        worker_backup_observations=worker_backup_observations,
        activation_state_records=activation_state_records,
        launch_intents=launch_intents,
        native_provisioning_attempts=native_provisioning_attempts,
    )


def read_windows_product_worker_attempt_references_under_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    journals: WindowsProductWorkerHistoryJournals,
    inspect_inventory: ReadWindowsRecoveryInventory[WindowsRecoveryAttemptV1],
    reference_type: Callable[..., _ReferenceT],
    product_id: str,
    error_type: type[RuntimeError],
    error_prefix: str,
) -> tuple[_ReferenceT, ...]:
    product.assert_root_gc_authority_current()
    attempts = inspect_inventory(product)
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        receipts = journals.receipt(
            product.state_root / "worker-activation-receipts.jsonl",
            scope_id=product.policy.project_scope_id,
        ).records(directory_fd=root)
    references = project_windows_worker_attempt_references(
        attempts,
        receipts,
        reference_type=reference_type,
        product_id=product_id,
        error_type=error_type,
        error_prefix=error_prefix,
    )
    product.assert_root_gc_authority_current()
    return references


def read_windows_product_worker_offline_recovery(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    read_under_guard: ReadWindowsOfflineRecovery,
    active_error: type[RuntimeError],
    active_code: str,
) -> _RecoveryFacts:
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise active_error(active_code)
        with product.gc_gate.read_snapshot_guard() as gc_snapshot:
            return read_under_guard(
                product,
                store_id=registry.store_id,
                lease_owner_revision=quiescence.owner_revision,
                gc_snapshot=gc_snapshot,
            )


def current_windows_worker_attempts_after_verified_retirements(
    product: WindowsLocalWheelProductSessionOwner,
    inventory: tuple[_AttemptT, ...],
    *,
    attempt_id: str | None,
    require_partial: Callable[[WindowsLocalWheelProductSessionOwner, _AttemptT], None],
    require_crash: Callable[[WindowsLocalWheelProductSessionOwner, _AttemptT], None],
    require_unlaunched: Callable[
        [WindowsLocalWheelProductSessionOwner, _AttemptT], None
    ],
    require_complete: Callable[[WindowsLocalWheelProductSessionOwner, _AttemptT], None],
    error_type: type[RuntimeError],
    error_code: str,
) -> tuple[_AttemptT, ...]:
    """Exclude only fully proved retirements; no selection or cleanup effects.

    The adapter performs its original currentness check before cycle-breaking
    owner resolution. These are four complete historical validators, never
    stage callbacks or permission to finish a partial retirement.
    """
    current: list[_AttemptT] = []
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
                require_partial(product, attempt)
            elif (
                attempt.native_phase == "settled"
                and attempt.supervisor_phase in {None, "process_settled"}
                and _valid_crash_effect_history(attempt, settled=True)
            ):
                require_crash(product, attempt)
            elif attempt.native_phase == "settled" and attempt.supervisor_phase is None:
                require_unlaunched(product, attempt)
            else:
                require_complete(product, attempt)
        except (OSError, RuntimeError, ValueError) as exc:
            raise error_type(error_code) from exc
    product.assert_root_gc_authority_current()
    return tuple(current)


class _WindowsAttemptReferenceFacts(AttemptReference, Protocol):
    @property
    def attempt_id(self) -> str: ...


_ReferenceFactT = TypeVar("_ReferenceFactT", bound=_WindowsAttemptReferenceFacts)
_ObservationT = TypeVar("_ObservationT")


def read_windows_product_worker_attempt_gc_observations(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    read_references: Callable[
        [WindowsLocalWheelProductSessionOwner], tuple[_ReferenceFactT, ...]
    ],
    observe_backup: ObserveWindowsWorkerBackup,
    observation_type: Callable[..., _ObservationT],
) -> tuple[_ObservationT, ...]:
    with product.gc_gate.read_snapshot_guard() as gc_snapshot:
        reservations = gc_revision_refs(gc_snapshot)
        references = read_references(product)
        return tuple(
            observation_type(
                attempt_reference=reference,
                active_gc_reservation_count=len(reservations),
                gc_reservation_revision=gc_snapshot.journal_revision,
                matching_revision_refs=matching_gc_revision_refs(
                    plugin_id=reference.plugin_id,
                    package_content_digest=reference.selected_package_revision_digest,
                    reservations=reservations,
                ),
                worker_backup_references=observe_backup(
                    product, attempt_id=reference.attempt_id
                ),
            )
            for reference in references
        )


_IntentT = TypeVar("_IntentT", bound=_LaunchIntentFacts)
_IntentContra = TypeVar("_IntentContra", bound=_LaunchIntentFacts, contravariant=True)
_FullReviewT = TypeVar("_FullReviewT", bound=_WindowsCompleteStageReviewMethods)
_PartialReviewT = TypeVar("_PartialReviewT", bound=_WindowsPartialStageReviewMethods)
_PartialReviewCo = TypeVar(
    "_PartialReviewCo", bound=_WindowsPartialStageReviewMethods, covariant=True
)
_ReservedReviewT = TypeVar("_ReservedReviewT", bound=_WindowsReservedStageReviewMethods)
_ReservedReviewCo = TypeVar(
    "_ReservedReviewCo", bound=_WindowsReservedStageReviewMethods, covariant=True
)


class _CaptureCompleteStage(Protocol[_IntentContra]):
    def __call__(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        attempt_id: str,
        expected_stage: tuple[int, int],
        intent: _IntentContra,
    ) -> CapturedWindowsWorkerStage: ...


class _CapturePartialReview(Protocol[_PartialReviewCo]):
    def __call__(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        attempt_id: str,
        expected_stage: tuple[int, int] | None,
        lease_owner_revision: int,
    ) -> _PartialReviewCo: ...


class _CaptureReservedReview(Protocol[_IntentContra, _ReservedReviewCo]):
    def __call__(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        intent: _IntentContra,
        native_revision: int | None,
        lease_owner_revision: int,
    ) -> _ReservedReviewCo: ...


def review_windows_product_worker_complete_stage_under_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    lease_owner_revision: int,
    record_type: type[_FullReviewT],
    inspect_inventory: ReadWindowsRecoveryInventory[WindowsRecoveryAttemptV1],
    read_intent: Callable[[WindowsLocalWheelProductSessionOwner, str], _IntentT | None],
    capture_stage: _CaptureCompleteStage[_IntentT],
    error_prefix: str,
) -> _FullReviewT:
    product.assert_root_gc_authority_current()
    inventory = inspect_inventory(product)
    matches = tuple(item for item in inventory if item.attempt_id == attempt_id)
    if len(matches) != 1:
        raise record_type._record_error(error_prefix + "_attempt_unavailable")
    attempt = matches[0]
    if (
        attempt.observed_debts != ("payload_retained", "launch_intent_retained")
        or attempt.native_phase != "settled"
        or attempt.supervisor_phase != "stopped"
        or attempt.native_revision is None
        or attempt.supervisor_revision is None
        or attempt.payload_directory_identity is None
    ):
        raise record_type._record_error(error_prefix + "_settlement_unverified")
    intent = read_intent(product, attempt_id)
    if intent is None:
        raise record_type._record_error(error_prefix + "_intent_missing")
    captured = capture_stage(
        product,
        attempt_id=attempt_id,
        expected_stage=attempt.payload_directory_identity,
        intent=intent,
    )
    review = cast(Callable[..., _FullReviewT], record_type)(
        attempt_id=attempt_id,
        intent_fingerprint=intent.fingerprint,
        lease_owner_revision=lease_owner_revision,
        native_revision=attempt.native_revision,
        supervisor_revision=attempt.supervisor_revision,
        entrypoint=captured.entrypoint,
        stage_identity=captured.stage_identity,
        directory_identities=captured.directory_identities,
        marker_identity=captured.marker_identity,
        executable_identity=captured.executable_identity,
        executable_digest=captured.executable_digest,
    )
    product.assert_root_gc_authority_current()
    return review


def review_windows_product_worker_partial_stage(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    record_type: type[_PartialReviewT],
    inspect_inventory: ReadWindowsRecoveryInventory[WindowsRecoveryAttemptV1],
    inspect_retirements: Callable[
        [WindowsLocalWheelProductSessionOwner], frozenset[str]
    ],
    capture_partial: _CapturePartialReview[_PartialReviewT],
    partial_debts: tuple[str, ...],
    error_prefix: str,
) -> _PartialReviewT:
    def capture(quiescence: PackageWindowsRuntimeQuiescenceV1) -> _PartialReviewT:
        product.assert_root_gc_authority_current()
        inventory = inspect_inventory(product)
        matches = tuple(item for item in inventory if item.attempt_id == attempt_id)
        if (
            len(matches) != 1
            or matches[0].observed_debts != partial_debts
            or attempt_id in inspect_retirements(product)
        ):
            raise record_type._record_error(error_prefix + "_history_unverified")
        review = capture_partial(
            product,
            attempt_id=attempt_id,
            expected_stage=matches[0].payload_directory_identity,
            lease_owner_revision=quiescence.owner_revision,
        )
        product.assert_root_gc_authority_current()
        return review

    return review_windows_product_worker_offline(
        product,
        active_error=lambda: record_type._record_error(
            error_prefix + "_runtime_active"
        ),
        review=capture,
    )


def review_windows_product_worker_no_effect_under_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    lease_owner_revision: int,
    settled: bool,
    record_type: type[_ReservedReviewT],
    inspect_inventory: ReadWindowsRecoveryInventory[WindowsRecoveryAttemptV1],
    read_intent: Callable[[WindowsLocalWheelProductSessionOwner, str], _IntentT | None],
    inspect_retirements: Callable[
        [WindowsLocalWheelProductSessionOwner], frozenset[str]
    ],
    capture_reserved: _CaptureReservedReview[_IntentT, _ReservedReviewT],
    history_error: str,
) -> _ReservedReviewT:
    product.assert_root_gc_authority_current()
    inventory = inspect_inventory(product)
    matches = tuple(item for item in inventory if item.attempt_id == attempt_id)
    intent = read_intent(product, attempt_id)
    if (
        len(matches) != 1
        or intent is None
        or attempt_id in inspect_retirements(product)
    ):
        raise record_type._record_error(history_error)
    record_type._require_no_effect_candidate(
        matches[0], intent, settled=settled, history_error=history_error
    )
    review = capture_reserved(
        product,
        intent=intent,
        native_revision=matches[0].native_revision,
        lease_owner_revision=lease_owner_revision,
    )
    product.assert_root_gc_authority_current()
    return review


_OrphanReviewT = TypeVar("_OrphanReviewT", bound=_WindowsOrphanRuntimeReviewMethods)
_CrashReviewT = TypeVar("_CrashReviewT", bound=_WindowsCrashStageReviewMethods)


_CleanupReceiptOwnerT = TypeVar(
    "_CleanupReceiptOwnerT", bound=_WindowsWorkerProductReceiptAuthority
)
_LiveCleanupReviewT = TypeVar("_LiveCleanupReviewT", bound=WindowsLiveCleanupReview)
_CleanupActivationT = TypeVar("_CleanupActivationT", bound=_RetainedAttemptFields)


class WindowsProductWorkerCleanupEvidence(
    WindowsWorkerCleanupEvidence[_LiveCleanupReviewT],
    Generic[_CleanupReceiptOwnerT, _LiveCleanupReviewT, _CleanupActivationT],
):
    """Bind the existing read-only evidence owner to one Product component family.

    Normal, parent-enrollment and crash bindings keep the same authority and
    mutable instance state. Product identity domains and cleanup permission
    remain with the nominal Product subclass; no additional repair owner exists.
    """

    _product: WindowsLocalWheelProductSessionOwner
    _cleanup_product_id: str
    _cleanup_receipt_owner_type: type[_CleanupReceiptOwnerT]
    _cleanup_review_under_guard: _RuntimeReview[_WindowsOrphanRuntimeReviewMethods]
    _cleanup_inspect_native: Callable[
        [WindowsLocalWheelProductSessionOwner],
        tuple[WindowsWorkerProvisioningAttemptV1, ...],
    ]
    _cleanup_activation_journal: Callable[
        [WindowsLocalWheelProductSessionOwner],
        WindowsActivationStateJournal[_CleanupActivationT],
    ]
    _cleanup_review_runtime: Callable[..., _WindowsOrphanRuntimeReviewMethods]

    def __init__(
        self,
        *,
        receipt_owner: _CleanupReceiptOwnerT,
        receipt: ProductWorkerActivationReceiptV1,
        request: ManagedWorkerLaunchRequestV1,
    ) -> None:
        if (
            os.name != "nt"
            or type(receipt_owner) is not self._cleanup_receipt_owner_type
            or type(receipt) is not ProductWorkerActivationReceiptV1
            or type(request) is not ManagedWorkerLaunchRequestV1
            or request.identity.product_id != self._cleanup_product_id
            or request.identity.scope_id != receipt.policy.product_scope_id
            or request.identity.plugin_id != receipt.policy.plugin_id
            or request.identity.owner_generation
            != receipt.policy.owner_selection_generation
            or receipt_owner.product_owner.policy.product_id != self._cleanup_product_id
        ):
            raise ValueError("Windows C5 cleanup requires one bound Product attempt")
        receipt_owner.product_owner.assert_root_gc_authority_current()
        self._product: WindowsLocalWheelProductSessionOwner = (
            receipt_owner.product_owner
        )
        self._receipt = receipt
        self._attempt_id = request.identity.attempt_id
        self._owner_generation = request.identity.owner_generation
        self._request_fingerprint = request.fingerprint
        self._identity_fingerprint = request.identity.fingerprint
        self._mode = "normal"

    @classmethod
    def for_resume_parent_enrollment(
        cls,
        *,
        receipt_owner: _CleanupReceiptOwnerT,
        receipt: ProductWorkerActivationReceiptV1,
    ) -> Self:
        """Bind the stable evidence domain before any attempt materialization.

        This authority is used only to open C5 and enroll a Resume parent. It
        carries no attempt witness and therefore cannot settle an activation.
        """

        if (
            os.name != "nt"
            or type(receipt_owner) is not cls._cleanup_receipt_owner_type
            or type(receipt) is not ProductWorkerActivationReceiptV1
            or receipt_owner.product_owner.policy.product_id != cls._cleanup_product_id
            or receipt.policy.product_id != cls._cleanup_product_id
        ):
            raise ValueError("Windows C5 Resume enrollment requires one Product")
        receipt_owner.product_owner.assert_root_gc_authority_current()
        authority = cls.__new__(cls)
        authority._product = receipt_owner.product_owner
        authority._receipt = receipt
        authority._attempt_id = "resume-parent-enrollment"
        authority._owner_generation = receipt.policy.owner_selection_generation
        authority._request_fingerprint = "0" * 64
        authority._identity_fingerprint = "0" * 64
        authority._mode = "enrollment"
        return authority

    @classmethod
    def for_crash_recovery(
        cls,
        *,
        product: WindowsLocalWheelProductSessionOwner,
        receipt: ProductWorkerActivationReceiptV1,
        attempt_id: str,
    ) -> Self:
        """Bind a dead Session only from its persisted Product recovery join."""

        if (
            os.name != "nt"
            or type(product) is not WindowsLocalWheelProductSessionOwner
            or product.policy.product_id != cls._cleanup_product_id
            or type(receipt) is not ProductWorkerActivationReceiptV1
        ):
            raise ValueError("Windows C5 crash recovery requires an exact Product")
        return cls._from_crash_recovery(
            product=product,
            receipt=receipt,
            attempt_id=attempt_id,
            review_runtime=cls._cleanup_review_runtime,
        )

    def current_tree_witness(self, *, attempt_id: str) -> _LiveCleanupReviewT:
        if attempt_id != self._attempt_id:
            raise ValueError("Windows C5 cleanup attempt changed")
        runtime, native, activation = capture_windows_product_worker_cleanup(
            self._product,
            attempt_id=attempt_id,
            review_runtime=self._cleanup_review_under_guard,
            inspect_native=self._cleanup_inspect_native,
            activation_journal=partial(self._cleanup_activation_journal, self._product),
        )
        return cast(Callable[..., _LiveCleanupReviewT], self._review_type)(
            runtime=runtime, native=native, activation=activation
        )


def read_windows_product_worker_orphan_runtime(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    review_runtime: _RuntimeReview[_OrphanReviewT],
) -> _OrphanReviewT:
    registry = product.epoch_runtime.registry
    orphans = registry.review_orphans(store_id=registry.store_id)
    with product.gc_gate.read_guard():
        return review_runtime(product, attempt_id=attempt_id, orphans=orphans)


def repair_windows_product_worker_clean_exit_orphan(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: _WindowsOrphanRuntimeReviewMethods,
    review_runtime: _RuntimeReview[_WindowsOrphanRuntimeReviewMethods],
) -> PackageEpochRuntimeLeaseV1:
    [expected_lease] = expected_review.orphan_leases
    registry = product.epoch_runtime.registry

    @contextmanager
    def validate_while_locked(
        lease: PackageEpochRuntimeLeaseV1,
    ) -> Iterator[None]:
        if lease != expected_lease:
            raise ValueError("Windows Worker orphan lease changed")
        with product.gc_gate.guard(require_write=True):
            current = review_runtime(
                product, attempt_id=expected_review.attempt_id, orphans=(lease,)
            )
            if current != expected_review:
                raise ValueError("Windows Worker clean-exit review is stale")
            if not current.clean_exit_repair_candidate:
                raise ValueError("Windows Worker clean-exit repair is unproven")
            yield
            product.assert_root_gc_authority_current()

    registry.repair_orphan(
        expected_lease.lease_id, validation_guard=validate_while_locked
    )
    return expected_lease


def review_windows_product_worker_crash_stage_under_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    quiescence: PackageWindowsRuntimeQuiescenceV1,
    record_type: type[_CrashReviewT],
    review_runtime: _RuntimeReview[_WindowsOrphanRuntimeReviewMethods],
    inspect_native: Callable[
        [WindowsLocalWheelProductSessionOwner],
        tuple[WindowsWorkerProvisioningAttemptV1, ...],
    ],
    read_intent: Callable[[WindowsLocalWheelProductSessionOwner, str], _IntentT | None],
    capture_stage: _CaptureCompleteStage[_IntentT],
) -> _CrashReviewT:
    product.assert_root_gc_authority_current()
    joined = review_runtime(product, attempt_id=attempt_id, orphans=())
    if not _crash_settled_history_matches(joined, repaired_lease=True):
        raise ValueError("Windows Worker crash stage history is unverified")
    attempt = joined.attempt
    receipt = joined.receipt_record
    assert attempt is not None and receipt is not None
    assert attempt.native_revision is not None
    assert attempt.payload_directory_identity is not None
    repair_record = _require_repair_record(
        quiescence, runtime_id=receipt.receipt.policy.product_runtime_id
    )
    intent = read_intent(product, attempt_id)
    if intent is None or not launch_matches_intent(attempt, intent):
        raise ValueError("Windows Worker crash stage launch intent changed")
    native = tuple(
        item for item in inspect_native(product) if item.attempt_id == attempt_id
    )
    if len(native) != 1:
        raise ValueError("Windows Worker crash stage native history is unverified")
    [provisioned] = native
    identity = provisioned.identity
    if (
        provisioned.phase != "settled"
        or provisioned.state_revision != attempt.native_revision
        or provisioned.phase_history != attempt.native_phase_history
        or provisioned.witness_present_history != attempt.native_witness_present_history
        or identity["workerRequestFingerprint"] != intent.request_fingerprint
        or identity["receiptFingerprint"] != receipt.receipt.fingerprint
        or identity["jobObjectName"] != attempt.native_job_name
        or identity["nativeProfileId"] != receipt.receipt.policy.native_profile_id
        or identity["nativeProfileCatalogRevision"]
        != receipt.receipt.policy.native_profile_catalog_revision
    ):
        raise ValueError("Windows Worker crash stage native identity changed")
    _rebuild_windows_lpac_cleanup_spec(
        identity=identity,
        runtime_root=product.state_root / f"worker-payload-{attempt_id}",
        platform_imports=WINDOWS_LPAC_PLATFORM_IMPORTS,
        owner_private_ancestors=True,
    )
    captured = capture_stage(
        product,
        attempt_id=attempt_id,
        expected_stage=attempt.payload_directory_identity,
        intent=intent,
    )
    product.assert_root_gc_authority_current()
    return cast(Callable[..., _CrashReviewT], record_type)(
        attempt_id=attempt_id,
        intent_fingerprint=intent.fingerprint,
        lease_owner_revision=quiescence.owner_revision,
        repaired_lease_id=repair_record.lease.lease_id,
        lease_repair_revision=repair_record.record_revision,
        native_revision=attempt.native_revision,
        supervisor_revision=attempt.supervisor_revision,
        native_spec_fingerprint=cast(str, identity["specFingerprint"]),
        entrypoint=captured.entrypoint,
        stage_identity=captured.stage_identity,
        directory_identities=captured.directory_identities,
        marker_identity=captured.marker_identity,
        executable_identity=captured.executable_identity,
        executable_digest=captured.executable_digest,
    )


class _SupervisorLaunchIntent(_LaunchIntentFacts, Protocol):
    @property
    def supervisor_epoch(self) -> int: ...


class WindowsCrashCleanupReview(Protocol):
    @property
    def orphan_review(self) -> _WindowsOrphanRuntimeReviewMethods: ...
    @property
    def native_revision(self) -> int: ...
    @property
    def native_spec_fingerprint(self) -> str: ...
    @property
    def payload_directory_identity(self) -> tuple[int, int]: ...


class WindowsWorkerBackendRelease(Protocol):
    @property
    def expectation(self) -> WindowsBackendMaterialExpectationV1: ...


@dataclass(frozen=True, slots=True)
class WindowsProductWorkerCrashRecovery:
    """Existing lease owner expanded to the complete fixed crash recovery command.

    Original history/native/C5 programs share their actual readers and journals;
    stage proof/deletion stays with the existing retirement owner. No action
    callbacks, cached roots, durable state or parallel recovery manager are added.
    """

    product_id: str
    orphan_type: type[_WindowsOrphanRuntimeReviewMethods]
    cleanup_type: Callable[..., WindowsCrashCleanupReview]
    cleanup_error: type[RuntimeError]
    cleanup_error_prefix: str
    inspect_inventory: ReadWindowsRecoveryInventory[WindowsRecoveryAttemptV1]
    read_intent: Callable[
        [WindowsLocalWheelProductSessionOwner, str], _SupervisorLaunchIntent | None
    ]
    supervisor_journal: Callable[
        [WindowsLocalWheelProductSessionOwner], WindowsSupervisorJournal
    ]
    activation_journal: Callable[
        [WindowsLocalWheelProductSessionOwner], _ActivationHistory
    ]
    read_backend: Callable[
        [WindowsLocalWheelProductSessionOwner], WindowsWorkerBackendRelease
    ]
    settlement_type: Callable[..., object]
    evidence_factory: CrashEvidenceFactory
    state_store: Callable[[WindowsLocalWheelProductSessionOwner], _ActivationStateStore]
    evidence_authority_id: str
    evidence_authority_fingerprint: str
    host_domain: str
    boot_domain: str
    stage_retirement: CrashStageRetirementProfile
    record_type: Callable[..., WindowsCrashCleanupReview]
    review_runtime: _RuntimeReview[_WindowsOrphanRuntimeReviewMethods]
    inspect_native: Callable[
        [WindowsLocalWheelProductSessionOwner],
        tuple[WindowsWorkerProvisioningAttemptV1, ...],
    ]

    def _product_invalid(self, product: WindowsLocalWheelProductSessionOwner) -> bool:
        return (
            os.name != "nt"
            or type(product) is not WindowsLocalWheelProductSessionOwner
            or product.policy.product_id != self.product_id
        )

    @contextmanager
    def guard_settled_review(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        attempt_id: str,
        orphans: tuple[PackageEpochRuntimeLeaseV1, ...],
    ) -> Iterator[WindowsCrashCleanupReview]:
        """Caller holds GC gate; pin retained stage across an optional Package append."""
        review = self.review_runtime(product, attempt_id=attempt_id, orphans=orphans)
        if not _crash_settled_history_matches(review):
            raise ValueError("Windows Worker crash settlement history is unverified")
        attempt = review.attempt
        receipt = review.receipt_record
        assert attempt is not None and receipt is not None
        assert attempt.native_revision is not None
        assert attempt.payload_directory_identity is not None
        native = tuple(
            (
                item
                for item in self.inspect_native(product)
                if item.attempt_id == attempt_id
            )
        )
        if len(native) != 1:
            raise ValueError("Windows Worker native settlement identity is unverified")
        [provisioned] = native
        identity = provisioned.identity
        if (
            provisioned.phase != "settled"
            or provisioned.state_revision != attempt.native_revision
            or provisioned.phase_history != attempt.native_phase_history
            or (
                provisioned.witness_present_history
                != attempt.native_witness_present_history
            )
            or (
                identity["workerRequestFingerprint"]
                != attempt.launch_request_fingerprint
            )
            or (identity["receiptFingerprint"] != receipt.receipt.fingerprint)
            or (identity["jobObjectName"] != attempt.native_job_name)
            or (identity["nativeProfileId"] != receipt.receipt.policy.native_profile_id)
            or (
                identity["nativeProfileCatalogRevision"]
                != receipt.receipt.policy.native_profile_catalog_revision
            )
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
                    observe_windows_worker_job_absent(
                        cast(str, identity["jobObjectName"])
                    )
                    is not True
                ):
                    raise ValueError("Windows Worker crash Job is still present")
                product.assert_root_gc_authority_current()
                yield self.record_type(
                    orphan_review=review,
                    native_revision=attempt.native_revision,
                    native_spec_fingerprint=cast(str, identity["specFingerprint"]),
                    payload_directory_identity=attempt.payload_directory_identity,
                )
                product.assert_root_gc_authority_current()
            finally:
                os.close(stage)

    def review_lease(
        self, product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
    ) -> WindowsCrashCleanupReview:
        if (
            self._product_invalid(product)
            or type(attempt_id) is not str
            or _CRASH_ATTEMPT.fullmatch(attempt_id) is None
        ):
            raise ValueError("Windows Worker crash lease review requires exact Product")
        registry = product.epoch_runtime.registry
        orphans = registry.review_orphans(store_id=registry.store_id)
        with product.gc_gate.read_guard():
            with self.guard_settled_review(
                product, attempt_id=attempt_id, orphans=orphans
            ) as review:
                return review

    def repair_lease(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        expected_review: WindowsCrashCleanupReview,
    ) -> PackageEpochRuntimeLeaseV1:
        if (
            self._product_invalid(product)
            or type(expected_review) is not self.record_type
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
                with self.guard_settled_review(
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

    def review_cleanup(
        self, product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
    ) -> WindowsCrashCleanupReview:
        if (
            self._product_invalid(product)
            or type(attempt_id) is not str
            or _CRASH_ATTEMPT.fullmatch(attempt_id) is None
        ):
            raise ValueError("Windows Worker crash cleanup review requires a Product")
        registry = product.epoch_runtime.registry
        orphans = registry.review_orphans(store_id=registry.store_id)
        with product.gc_gate.read_guard():
            review = self.review_runtime(
                product, attempt_id=attempt_id, orphans=orphans
            )
            attempt = review.attempt
            receipt = review.receipt_record
            if not _crash_cleanup_history_matches(review):
                raise self.cleanup_error(
                    self.cleanup_error_prefix + "_history_unverified"
                )
            assert attempt is not None and receipt is not None
            assert attempt.native_revision is not None
            assert attempt.payload_directory_identity is not None
            native = tuple(
                (
                    item
                    for item in self.inspect_native(product)
                    if item.attempt_id == attempt_id
                )
            )
            if len(native) != 1:
                raise self.cleanup_error(
                    self.cleanup_error_prefix + "_native_identity_unverified"
                )
            [provisioned] = native
            identity = provisioned.identity
            if (
                provisioned.phase != attempt.native_phase
                or provisioned.state_revision != attempt.native_revision
                or provisioned.phase_history != attempt.native_phase_history
                or (
                    provisioned.witness_present_history
                    != attempt.native_witness_present_history
                )
                or (
                    identity["workerRequestFingerprint"]
                    != attempt.launch_request_fingerprint
                )
                or (identity["receiptFingerprint"] != receipt.receipt.fingerprint)
                or (identity["jobObjectName"] != attempt.native_job_name)
                or (
                    identity["nativeProfileId"]
                    != receipt.receipt.policy.native_profile_id
                )
                or (
                    identity["nativeProfileCatalogRevision"]
                    != receipt.receipt.policy.native_profile_catalog_revision
                )
            ):
                raise self.cleanup_error(
                    self.cleanup_error_prefix + "_native_identity_unverified"
                )
            stage = product.state_root / f"worker-payload-{attempt_id}"
            _rebuild_windows_lpac_cleanup_spec(
                identity=identity,
                runtime_root=stage,
                platform_imports=WINDOWS_LPAC_PLATFORM_IMPORTS,
                owner_private_ancestors=True,
            )
            product.assert_root_gc_authority_current()
            if (
                observe_windows_worker_job_absent(cast(str, identity["jobObjectName"]))
                is not True
            ):
                raise self.cleanup_error(self.cleanup_error_prefix + "_job_unverified")
            current = next(
                (
                    item
                    for item in self.inspect_inventory(product)
                    if item.attempt_id == attempt_id
                ),
                None,
            )
            if current != attempt:
                raise self.cleanup_error(self.cleanup_error_prefix + "_history_changed")
            current_native = tuple(
                (
                    item
                    for item in self.inspect_native(product)
                    if item.attempt_id == attempt_id
                )
            )
            if current_native != native:
                raise self.cleanup_error(self.cleanup_error_prefix + "_history_changed")
            product.assert_root_gc_authority_current()
            return self.cleanup_type(
                orphan_review=review,
                native_revision=attempt.native_revision,
                native_spec_fingerprint=cast(str, identity["specFingerprint"]),
                payload_directory_identity=attempt.payload_directory_identity,
            )

    def settle_supervisor(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        expected_review: WindowsCrashCleanupReview,
    ) -> WorkerAttemptRecordV1 | None:
        if (
            self._product_invalid(product)
            or type(expected_review) is not self.cleanup_type
            or len(expected_review.orphan_review.orphan_leases) != 1
        ):
            raise ValueError(
                "Windows Worker crash Supervisor requires exact Product proof"
            )
        expected_orphan = expected_review.orphan_review
        [expected_lease] = expected_orphan.orphan_leases
        attempt_id = expected_orphan.attempt_id
        registry = product.epoch_runtime.registry
        with registry.guard_orphan_recovery(
            store_id=registry.store_id, lease_id=expected_lease.lease_id
        ) as lease:
            if lease != expected_lease:
                raise ValueError("Windows Worker crash Supervisor lease changed")
            with product.gc_gate.guard(require_write=True):
                current = self.review_runtime(
                    product, attempt_id=attempt_id, orphans=(lease,)
                )
                if current != expected_orphan or not _crash_cleanup_history_matches(
                    current
                ):
                    raise ValueError("Windows Worker crash Supervisor review is stale")
                attempt = current.attempt
                assert attempt is not None
                assert attempt.native_job_name is not None
                intent = self.read_intent(product, attempt_id)
                if (
                    intent is None
                    or intent.identity_fingerprint
                    != attempt.launch_identity_fingerprint
                    or intent.stage_identity != attempt.payload_directory_identity
                    or (attempt.native_revision != expected_review.native_revision)
                    or (
                        attempt.payload_directory_identity
                        != expected_review.payload_directory_identity
                    )
                ):
                    raise ValueError("Windows Worker crash Supervisor identity changed")
                if (
                    observe_windows_worker_job_absent(attempt.native_job_name)
                    is not True
                ):
                    raise ValueError("Windows Worker crash Job is still present")
                if attempt.supervisor_phase is None:
                    product.assert_root_gc_authority_current()
                    return None
                journal = self.supervisor_journal(product)
                records = tuple(
                    (
                        item
                        for item in journal.inspect_records()
                        if item.attempt_id == attempt_id
                    )
                )
                if not records:
                    raise ValueError(
                        "Windows Worker crash Supervisor history disappeared"
                    )
                record = records[-1]
                if (
                    record.phase != attempt.supervisor_phase
                    or record.record_revision != attempt.supervisor_revision
                    or record.identity_fingerprint != intent.identity_fingerprint
                    or (record.supervisor_epoch != intent.supervisor_epoch)
                ):
                    raise ValueError("Windows Worker crash Supervisor history changed")
                settled = settle_windows_crashed_supervisor_record(journal, record)
                refreshed = next(
                    (
                        item
                        for item in self.inspect_inventory(product)
                        if item.attempt_id == attempt_id
                    ),
                    None,
                )
                if (
                    refreshed is None
                    or refreshed.native_revision != attempt.native_revision
                    or refreshed.payload_directory_identity
                    != attempt.payload_directory_identity
                    or (
                        refreshed.launch_identity_fingerprint
                        != attempt.launch_identity_fingerprint
                    )
                    or (refreshed.supervisor_phase != settled.phase)
                    or (refreshed.supervisor_revision != settled.record_revision)
                    or (refreshed.supervisor_process_settled is not True)
                    or (
                        observe_windows_worker_job_absent(attempt.native_job_name)
                        is not True
                    )
                ):
                    raise ValueError(
                        "Windows Worker crash Supervisor settlement changed"
                    )
                product.assert_root_gc_authority_current()
                return settled

    def settle_native(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        expected_review: WindowsCrashCleanupReview,
    ) -> object:
        if (
            self._product_invalid(product)
            or type(expected_review) is not self.cleanup_type
            or len(expected_review.orphan_review.orphan_leases) != 1
        ):
            raise ValueError(
                "Windows Worker crash settlement requires exact Product proof"
            )
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
                current = self.review_runtime(
                    product, attempt_id=attempt_id, orphans=(lease,)
                )
                if current != expected_orphan or not _crash_cleanup_history_matches(
                    current
                ):
                    raise ValueError("Windows Worker crash cleanup review is stale")
                attempt = current.attempt
                assert attempt is not None and current.receipt_record is not None
                if (
                    attempt.supervisor_phase is not None
                    and attempt.supervisor_process_settled is not True
                ):
                    raise ValueError("Windows Worker crash Supervisor is unsettled")
                native = tuple(
                    (
                        item
                        for item in self.inspect_native(product)
                        if item.attempt_id == attempt_id
                    )
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
                    or (provisioned.state_revision != expected_review.native_revision)
                    or (
                        identity["specFingerprint"]
                        != expected_review.native_spec_fingerprint
                    )
                    or (
                        attempt.payload_directory_identity
                        != expected_review.payload_directory_identity
                    )
                    or (
                        identity["receiptFingerprint"]
                        != current.receipt_record.receipt.fingerprint
                    )
                    or (
                        identity["workerRequestFingerprint"]
                        != attempt.launch_request_fingerprint
                    )
                    or (identity["jobObjectName"] != attempt.native_job_name)
                    or (
                        identity["nativeProfileId"]
                        != current.receipt_record.receipt.policy.native_profile_id
                    )
                    or (
                        identity["nativeProfileCatalogRevision"]
                        != current.receipt_record.receipt.policy.native_profile_catalog_revision
                    )
                ):
                    raise ValueError("Windows Worker native cleanup identity changed")
                stage_name = f"worker-payload-{attempt_id}"
                material = self.read_backend(product)
                return settle_windows_product_worker_native_cleanup(
                    product,
                    stage_name=stage_name,
                    attempt_id=attempt_id,
                    identity=identity,
                    expected_stage_identity=expected_review.payload_directory_identity,
                    material_expectation=material.expectation,
                    settlement_type=self.settlement_type,
                )

    def settle_c5(
        self, product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
    ) -> _RetainedAttemptFields:
        if self._product_invalid(product):
            raise ValueError("Windows crash C5 settlement requires its Coding Product")
        runtime = self.review_orphan(product, attempt_id=attempt_id)
        attempt = runtime.attempt
        record = runtime.receipt_record
        if (
            attempt is None
            or record is None
            or runtime.orphan_leases
            or (runtime.native_job_absent is not True)
            or (attempt.supervisor_phase != "process_settled")
            or (attempt.supervisor_process_settled is not True)
            or (attempt.native_phase != "settled")
            or (not _valid_crash_effect_history(attempt, settled=True))
            or (attempt.payload_directory_identity is not None)
            or (attempt.observed_debts != ("payload_missing", "launch_intent_retained"))
            or (attempt.launch_receipt_fingerprint != record.receipt.fingerprint)
        ):
            raise ValueError("Windows crash C5 Product recovery is incomplete")
        receipt = record.receipt
        journal = self.activation_journal(product)
        retained = tuple(
            (
                item
                for item in journal.retained_attempts_read_only()
                if item.attempt_id == attempt_id
            )
        )
        if len(retained) != 1:
            raise ValueError("Windows crash C5 attempt is missing or ambiguous")
        [c5] = retained
        if (
            c5.receipt_fingerprint != receipt.fingerprint
            or c5.policy_fingerprint != receipt.policy.fingerprint
            or c5.owner_generation != receipt.policy.owner_selection_generation
            or (c5.cleanup_contract_version != 2)
            or (not c5.current)
        ):
            raise ValueError("Windows crash C5 attempt cannot be recovered")
        evidence = self.evidence_factory(
            product=product, receipt=receipt, attempt_id=attempt_id
        )
        if (
            c5.host_identity != evidence.host_identity
            or c5.boot_identity != evidence.boot_identity
        ):
            raise ValueError("Windows crash C5 owner identity changed")
        state = journal.load()
        attempts = None if state is None else state.get("attempts")
        if not isinstance(attempts, Mapping):
            raise ValueError("Windows crash C5 owner state is unavailable")
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
            raise ValueError("Windows crash C5 evidence authority changed")
        if c5.phase == "settled":
            if exact[0].get("cleanupSettlement") is None:
                raise ValueError("Windows crash C5 settlement record is missing")
            return c5
        coordinator = ProductWorkerActivationCoordinator(
            authority=_ClosedWindowsCrashRecoveryAuthority(product),
            evidence_authority=evidence,
            trusted_evidence_authority_id=evidence.authority_id,
            trusted_evidence_authority_fingerprint=evidence.authority_fingerprint,
            state_store=self.state_store(product),
        )
        generation = receipt.policy.owner_selection_generation
        coordinator.retire_exact(
            receipt=receipt, attempt_id=attempt_id, owner_generation=generation
        )
        coordinator.record_protocol_terminal(
            receipt=receipt, attempt_id=attempt_id, owner_generation=generation
        )
        tree = evidence.current_tree_witness(attempt_id=attempt_id)
        coordinator.record_cleanup_settlement(
            WorkerCleanupSettlementV2(
                receipt_fingerprint=receipt.fingerprint,
                attempt_id=attempt_id,
                owner_generation=generation,
                host_identity=evidence.host_identity,
                boot_identity=evidence.boot_identity,
                protocol_terminal=True,
                domain_retired=True,
                tree_settled=True,
                native_containment_settled=True,
            ),
            witness=tree,
            native_containment_witness=evidence.current_native_witness(),
        )
        [settled] = (
            item
            for item in journal.retained_attempts_read_only()
            if item.attempt_id == attempt_id
        )
        if settled.phase != "settled":
            raise ValueError("Windows crash C5 settlement did not persist")
        return settled

    def review_orphan(
        self, product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
    ) -> _WindowsOrphanRuntimeReviewMethods:
        if (
            self._product_invalid(product)
            or type(attempt_id) is not str
            or _CRASH_ATTEMPT.fullmatch(attempt_id) is None
        ):
            raise ValueError("Windows Worker orphan review requires an exact Product")
        return read_windows_product_worker_orphan_runtime(
            product, attempt_id=attempt_id, review_runtime=self.review_runtime
        )

    def review_stage(
        self, product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
    ) -> _WindowsCrashStageReviewMethods:
        if (
            self._product_invalid(product)
            or type(attempt_id) is not str
            or _CRASH_ATTEMPT.fullmatch(attempt_id) is None
        ):
            raise ValueError("Windows Worker crash stage requires exact Product")
        return review_windows_product_worker_offline(
            product,
            active_error=lambda: ValueError(
                "Windows Worker crash stage has active leases"
            ),
            review=lambda quiescence: self.stage_retirement.review_stage(
                product, attempt_id=attempt_id, quiescence=quiescence
            ),
        )

    def retire_stage(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        expected_review: _WindowsCrashStageReviewMethods,
    ) -> _WindowsStageRetirementReceiptMethods:
        if (
            self._product_invalid(product)
            or type(expected_review) is not self.stage_retirement.records.review_type
        ):
            raise ValueError(
                "Windows Worker crash stage retirement requires exact Product"
            )
        return self.stage_retirement.retire(product, expected_review=expected_review)

    def recover(
        self, product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
    ) -> _RetainedAttemptFields:
        current = self.review_orphan(product, attempt_id=attempt_id)
        attempt = current.attempt
        record = current.receipt_record
        if attempt is None or record is None:
            raise ValueError("Windows Worker crash attempt is absent")
        journal = self.activation_journal(product)
        retained = tuple(
            (
                item
                for item in journal.retained_attempts_read_only()
                if item.attempt_id == attempt_id
            )
        )
        if len(retained) != 1:
            raise ValueError("Windows Worker crash C5 owner is missing or ambiguous")
        [c5] = retained
        receipt = record.receipt
        expected_host = self.host_domain + product.epoch_runtime.registry.store_id
        expected_boot = self.boot_domain + receipt.policy.product_runtime_id
        state = journal.load()
        attempts = None if state is None else state.get("attempts")
        exact = (
            ()
            if not isinstance(attempts, Mapping)
            else tuple(
                (
                    item
                    for item in attempts.values()
                    if isinstance(item, Mapping) and item.get("attemptId") == attempt_id
                )
            )
        )
        if (
            not c5.current
            or c5.phase
            not in {"effect_started", "published", "cleanup_debt", "retired", "settled"}
            or c5.receipt_fingerprint != receipt.fingerprint
            or (c5.policy_fingerprint != receipt.policy.fingerprint)
            or (c5.owner_generation != receipt.policy.owner_selection_generation)
            or (c5.cleanup_contract_version != 2)
            or (c5.host_identity != expected_host)
            or (c5.boot_identity != expected_boot)
            or (len(exact) != 1)
            or (exact[0].get("evidenceAuthorityId") != self.evidence_authority_id)
            or (
                exact[0].get("evidenceAuthorityFingerprint")
                != self.evidence_authority_fingerprint
            )
        ):
            raise ValueError("Windows Worker crash C5 owner changed")
        if attempt.supervisor_phase != "process_settled":
            review = self.review_cleanup(product, attempt_id=attempt_id)
            self.settle_supervisor(product, expected_review=review)
        current = self.review_orphan(product, attempt_id=attempt_id)
        attempt = current.attempt
        if attempt is None:
            raise ValueError("Windows Worker crash attempt disappeared")
        if attempt.native_phase != "settled":
            review = self.review_cleanup(product, attempt_id=attempt_id)
            self.settle_native(product, expected_review=review)
        current = self.review_orphan(product, attempt_id=attempt_id)
        if len(current.orphan_leases) == 1:
            lease_review = self.review_lease(product, attempt_id=attempt_id)
            self.repair_lease(product, expected_review=lease_review)
        elif current.orphan_leases:
            raise ValueError("Windows Worker crash orphan lease is ambiguous")
        current = self.review_orphan(product, attempt_id=attempt_id)
        attempt = current.attempt
        if attempt is None:
            raise ValueError("Windows Worker crash attempt disappeared")
        if attempt.payload_directory_identity is not None:
            stage_review = self.review_stage(product, attempt_id=attempt_id)
            self.retire_stage(product, expected_review=stage_review)
        return self.settle_c5(product, attempt_id=attempt_id)


class ReadWindowsOrphanRuntime(Protocol):
    def __call__(
        self, product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
    ) -> _WindowsOrphanRuntimeReviewMethods: ...


class _ClosedWindowsCrashRecoveryAuthority(
    ClosedProductWorkerCrashRecoveryAuthority[WindowsLocalWheelProductSessionOwner]
):
    _admission_error = "Windows crash recovery cannot change Worker admission"


class ReviewWindowsReservedStage(Protocol):
    def __call__(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        attempt_id: str,
        lease_owner_revision: int,
    ) -> _WindowsReservedStageReviewMethods: ...


def settle_windows_product_worker_reserved_no_effect(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: _WindowsReservedStageReviewMethods,
    review_reserved: ReviewWindowsReservedStage,
    read_intent: Callable[[WindowsLocalWheelProductSessionOwner, str], _IntentT | None],
    inspection: Callable[[], WindowsStageInspection],
    error_type: type[RuntimeError],
    error_prefix: str,
) -> None:
    history_error = error_prefix + "_history_changed"
    with windows_product_worker_offline_write(
        product,
        active_error=error_type,
        active_message=error_prefix + "_runtime_active",
    ) as quiescence:
        current_review = review_reserved(
            product,
            attempt_id=expected_review.attempt_id,
            lease_owner_revision=quiescence.owner_revision,
        )
        if current_review != expected_review:
            raise error_type(error_prefix + "_review_stale")
        intent = read_intent(product, expected_review.attempt_id)
        if intent is None or intent.fingerprint != expected_review.intent_fingerprint:
            raise error_type(error_prefix + "_intent_changed")
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            require_windows_worker_retirement_root(
                product, root, inspection, error_type, error_prefix + "_root_changed"
            )
            attempts = inspect_windows_worker_provisioning_attempts(
                product.state_root, directory_fd=root
            )
            matches = tuple(
                (
                    item
                    for item in attempts
                    if item.attempt_id == expected_review.attempt_id
                )
            )
            if (
                len(matches) != 1
                or matches[0].phase != "reserved"
                or matches[0].state_revision != 1
                or (
                    matches[0].identity["workerRequestFingerprint"]
                    != intent.request_fingerprint
                )
                or (
                    matches[0].identity["receiptFingerprint"]
                    != intent.receipt_fingerprint
                )
            ):
                raise error_type(history_error)
            journal = WindowsWorkerProvisioningStateJournal(
                product.state_root
                / f"worker-native-provisioning-{expected_review.attempt_id}.jsonl",
                identity=matches[0].identity,
            )
            current = journal.load(directory_fd=root)
            if current is None:
                raise error_type(history_error)
            settled = windows_worker_reserved_settled_document(
                current,
                expected_review=expected_review,
                error_type=error_type,
                history_error=history_error,
            )
            if not journal.compare_and_swap(
                expected_revision=1, document=settled, directory_fd=root
            ):
                raise error_type(history_error)
        product.assert_root_gc_authority_current()
