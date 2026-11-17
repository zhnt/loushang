"""Read-only Windows Worker history at the existing Package Product boundary.

The fixed programs borrow the original journal, inventory, backup-policy and
retirement owners. Journal bindings are lazy constructors of those same owners;
no source fields or transaction stages are supplied through callbacks, and no
read operation acquires repair or deletion authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, TypeVar, cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsRuntimeQuiescenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    windows_listdir_at,
)
from loushang.harness.worker._windows_provisioning_journal import (
    WindowsWorkerProvisioningAttemptV1,
)
from loushang.harness.worker.activation_state_journal import _StateRecord
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
    WindowsSupervisorJournal,
)
from loushang.harness.worker.history._windows_recovery import (
    WindowsRecoveryAttemptV1,
    _valid_crash_effect_history,
    project_windows_worker_attempt_references,
    require_windows_worker_c5_gc_history,
)
from loushang.harness.worker.history._windows_semantic_contracts import (
    _LaunchIntentFacts,
    _RecoveryFacts,
)
from loushang.harness.worker.history._windows_sources import (
    WINDOWS_WORKER_BASE_STAGE_NAMES,
    windows_worker_history_names,
)
from loushang.harness.worker.history._windows_stage_review_wire import (
    _WindowsCompleteStageReviewMethods,
    _WindowsPartialStageReviewMethods,
    _WindowsReservedStageReviewMethods,
)

from ._windows_worker_history import (
    ObserveWindowsWorkerBackup,
    ReadWindowsOfflineRecovery,
)
from ._worker_windows_attempt import (
    CapturedWindowsWorkerStage,
    _ReceiptJournalFactory,
    review_windows_product_worker_offline,
)


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
