"""Complete Linux Worker history proof under existing Product/GC/root custody.

All storage, replay, native observation and cleanup remain with existing owners.
Bindings carry actual owners, lazy constructors and Product values, not stages.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Generic, Protocol, TypeVar, cast

from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.package_product._linux_worker_native_release import (
    _LinuxWorkerNativeReleaseCustody,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.gated_start import worker_native_group_status_after_restart
from loushang.harness.worker.history._activation_store import SegmentedActivationJournal
from loushang.harness.worker.history._checkpoint import _CheckpointMethods
from loushang.harness.worker.history._checkpoint_commands import (
    CheckpointCommandAccess,
    CheckpointCommands,
)
from loushang.harness.worker.history._no_effect import is_no_effect_closure
from loushang.harness.worker.history._opt_in import _OptInDecisionMethods
from loushang.harness.worker.history._opt_in_store import OptInJournal
from loushang.harness.worker.history._preparation import PreparationHistory
from loushang.harness.worker.history._prepared import _PreparedMethods
from loushang.harness.worker.history._read_v2 import RetainedHistoryReader
from loushang.harness.worker.history._receipt_store import ReceiptHistory
from loushang.harness.worker.history._retention import (
    AttemptReference,
    BackupObservation,
    GroupStatus,
    gc_revision_refs,
    matching_attempt_gc_refs,
    receipt_gate_reference_issue,
    registered_repair_matches_no_effect_closure,
)
from loushang.harness.worker.history._retention import (
    attempt_reference as make_attempt_reference,
)
from loushang.harness.worker.history._rooted_supervisor import RootedSupervisorJournal
from loushang.harness.worker.history._snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
    _SnapshotMethods,
)
from loushang.harness.worker.history._snapshot_io import SnapshotHistory
from loushang.harness.worker.history._start_gate import _StartGateRecordMethods
from loushang.harness.worker.history._start_gate_store import StartGateHistory
from loushang.harness.worker.history._v2_names import (
    DELETION_LEDGER_NAME,
    NO_EFFECT_ARCHIVE_NAME,
    PREPARATION_STATE_NAMES,
    PRODUCT_OWNER_INDEX_NAME,
)
from loushang.harness.worker.journal import WorkerAttemptRecordV1
from loushang.harness.worker.payload._repair import RepairJournal
from loushang.harness.worker.payload._storage import PayloadStorage


class GatedReview(Protocol):
    @property
    def native_closure_current(self) -> bool: ...
    @property
    def gate_record(self) -> _StartGateRecordMethods | None: ...
    @property
    def attempt_record(self) -> WorkerAttemptRecordV1 | None: ...
    @property
    def group_status(self) -> GroupStatus: ...


class CurrentOptIn(Protocol):
    def current(self, plugin_id: str) -> _OptInDecisionMethods | None: ...


ReviewT = TypeVar("ReviewT")


@dataclass(frozen=True, slots=True)
class HistoryProofBindings(Generic[ReviewT]):
    product_id: str
    product_label: str
    gates: Callable[[PosixLocalWheelProductSessionOwner], StartGateHistory]
    supervisor: Callable[[PosixLocalWheelProductSessionOwner], RootedSupervisorJournal]
    receipts: Callable[[PosixLocalWheelProductSessionOwner], ReceiptHistory]
    opt_in_type: Callable[[], Callable[..., OptInJournal]]
    admitted_opt_in: Callable[[PosixLocalWheelProductSessionOwner], CurrentOptIn]
    activation_type: Callable[[], Callable[..., SegmentedActivationJournal]]
    snapshots: Callable[[], SnapshotHistory]
    access: Callable[[PosixLocalWheelProductSessionOwner], CheckpointCommandAccess]
    reader: Callable[[], RetainedHistoryReader]
    preparation: Callable[[], PreparationHistory]
    preparation_limits: Callable[[], Mapping[str, int]]
    checkpoints: Callable[[], CheckpointCommands]
    registered: Callable[[], RepairJournal]
    payload: Callable[[], PayloadStorage]
    native_custody: Callable[[], _LinuxWorkerNativeReleaseCustody]
    native_error: Callable[[], type[Exception]]
    gated_error: Callable[[], type[Exception]]
    gated_review: Callable[[], Callable[..., GatedReview]]
    review: Callable[[], Callable[..., ReviewT]]
    reference: Callable[[], Callable[..., AttemptReference]]
    known_state_name: Callable[[str], bool]
    payload_repair: re.Pattern[str]
    registered_staging: re.Pattern[str]
    backup_attestation: Callable[..., BackupObservation]


_HISTORY_STEMS = (
    "worker-activation-receipts",
    "worker-activation-state",
    "worker-start-gates",
    "worker-supervisor",
    "worker-history-checkpoints",
)


_PUBLIC_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")


def review_history(
    bindings: HistoryProofBindings[ReviewT],
    product: PosixLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
) -> ReviewT:
    """Join fresh Product facts while runtime and GC owner locks are held."""
    if (
        not isinstance(product, PosixLocalWheelProductSessionOwner)
        or product.policy.product_id != bindings.product_id
        or type(attempt_id) is not str
        or (_PUBLIC_ATTEMPT.fullmatch(attempt_id) is None)
    ):
        raise ValueError(
            f"{bindings.product_label} Worker history review requires an exact Product attempt"
        )
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id, read_only=True
    ) as quiescence:
        with product.gc_gate.read_snapshot_guard() as gc_snapshot:
            return review_history_under_guard(
                bindings,
                product,
                attempt_id=attempt_id,
                active_runtime_lease_ids=quiescence.active_runtime_lease_ids,
                gc_snapshot=gc_snapshot,
            )


def review_gated_offline(
    bindings: HistoryProofBindings[ReviewT],
    product: PosixLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
) -> GatedReview:
    gate = bindings.gates(product).current(attempt_id)
    attempt = bindings.supervisor(product).status(attempt_id)
    if (
        gate is not None
        and attempt is not None
        and gate.worker_identity_fingerprint != attempt.identity_fingerprint
    ):
        raise bindings.gated_error()(
            f"{bindings.product_id}_worker_start_gate_supervisor_mismatch"
        )
    native_current = False
    if gate is not None:
        try:
            closure = bindings.native_custody().open_reader(product).current_closure()
        except bindings.native_error():
            pass
        else:
            native_current = (
                sha256(canonical_json_bytes(closure.to_dict())).hexdigest()
                == gate.native_closure_digest
            )
    group_status: GroupStatus = "unobserved"
    if gate is not None and gate.identity is not None:
        observed: GroupStatus = worker_native_group_status_after_restart(gate.identity)
        group_status = observed
    return bindings.gated_review()(
        attempt_id=attempt_id,
        gate_record=gate,
        attempt_record=attempt,
        native_closure_current=native_current,
        group_status=group_status,
    )


def review_history_under_guard(
    bindings: HistoryProofBindings[ReviewT],
    product: PosixLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    active_runtime_lease_ids: tuple[str, ...],
    gc_snapshot: PluginPackageGcReservationSnapshotV1,
) -> ReviewT:
    gc_reservations = gc_revision_refs(gc_snapshot)
    product.assert_root_gc_authority_current()
    with product.pinned_state_root_gc_read() as root_fd:
        v2_owner_present = PRODUCT_OWNER_INDEX_NAME in os.listdir(root_fd)
        archive = None
        if v2_owner_present:
            with RootedFileIO(product.state_root, root_fd) as file_io:
                with file_io.bind(
                    product.state_root / PRODUCT_OWNER_INDEX_NAME, durable=False
                ) as rooted:
                    archive = bindings.preparation().read_bound_archive(rooted)
    archived_proofs = (
        {} if archive is None else {item.attempt_id: item for item in archive.proofs}
    )
    gated = review_gated_offline(bindings, product, attempt_id=attempt_id)
    gate = gated.gate_record
    receipts = bindings.receipts(product).read_records(retained_only=True)
    receipt = (
        None
        if gate is None
        else next(
            (
                record
                for record in receipts
                if record.receipt.fingerprint == gate.receipt_fingerprint
            ),
            None,
        )
    )
    opt_in = (
        None
        if receipt is None
        else bindings.admitted_opt_in(product).current(receipt.receipt.policy.plugin_id)
    )
    opt_in_projection = bindings.opt_in_type()(
        product.state_root / "worker-opt-in.jsonl",
        scope_id=product.policy.project_scope_id,
        gc_gate=product.gc_gate,
        store_id=product.epoch_runtime.registry.store_id,
    ).retention_projection_under_gc_guard()
    decisions_by_digest: dict[str, list[_OptInDecisionMethods]] = {}
    for decision in opt_in_projection.reference_decisions:
        decisions_by_digest.setdefault(decision.decision_digest, []).append(decision)
    unverified_opt_in: list[tuple[str, str]] = []
    for retained_receipt in receipts:
        decisions = decisions_by_digest.get(retained_receipt.opt_in_decision_digest, [])
        policy = retained_receipt.receipt.policy
        if (
            len(decisions) != 1
            or decisions[0].action != "allow"
            or decisions[0].plugin_id != policy.plugin_id
            or decisions[0].scope_id != retained_receipt.scope_id
            or decisions[0].generation != policy.owner_selection_generation
            or decisions[0].kill_switch_generation != policy.kill_switch_generation
        ):
            unverified_opt_in.append(
                (
                    retained_receipt.receipt.fingerprint,
                    "historical_opt_in_unverified",
                )
            )
    global_unverified_opt_in = tuple(sorted(unverified_opt_in))
    historical_opt_in_verified = receipt is not None and not any(
        fingerprint == receipt.receipt.fingerprint
        for fingerprint, _ in global_unverified_opt_in
    )
    activation_journal = bindings.activation_type()(
        product.state_root / "worker-activation-state.jsonl"
    )
    activation_initialized, activation_state = (
        activation_journal.load_with_presence_read_only()
    )
    retained_activation_references = activation_journal.retained_attempts_read_only()
    active_references: tuple[tuple[str, str], ...] = ()
    if activation_state is not None:
        attempts = cast(dict[str, dict[str, object]], activation_state["attempts"])
        active_references = tuple(
            sorted(
                (
                    cast(str, item["receiptFingerprint"]),
                    cast(str, item["attemptId"]),
                )
                for item in attempts.values()
                if item["phase"] != "settled"
            )
        )
    gates = bindings.gates(product).attempts()
    gate_by_id = {item.attempt_id: item for item in gates}
    supervisor = bindings.supervisor(product)
    supervisor_by_id = {item.attempt_id: item for item in supervisor.attempts()}
    supervisor_epoch_by_key: dict[str, int] = {}
    for record in supervisor_by_id.values():
        supervisor_epoch_by_key[record.supervisor_key] = max(
            supervisor_epoch_by_key.get(record.supervisor_key, 0),
            record.supervisor_epoch,
        )
    unbound_supervisor_attempt_ids = tuple(
        sorted(supervisor_by_id.keys() - gate_by_id.keys())
    )
    unverified_activation: list[tuple[str, str]] = []
    global_unverified_activation: list[tuple[str, str]] = []
    receipt_by_fingerprint = {item.receipt.fingerprint: item for item in receipts}
    activation_by_id = {
        item.attempt_id: item for item in retained_activation_references
    }
    for reference in retained_activation_references:
        relevant = reference.attempt_id == attempt_id or (
            receipt is not None
            and reference.receipt_fingerprint == receipt.receipt.fingerprint
        )
        referenced_gate = gate_by_id.get(reference.attempt_id)
        code: str | None
        if referenced_gate is None:
            code = "activation_reference_gate_absent"
        elif (
            referenced_gate.receipt_fingerprint != reference.receipt_fingerprint
            or referenced_gate.policy_fingerprint != reference.policy_fingerprint
        ):
            code = "activation_reference_binding_changed"
        elif is_no_effect_closure(
            product_id=bindings.product_id,
            gate=referenced_gate,
            activation=reference,
            supervisor=supervisor_by_id.get(reference.attempt_id),
            receipt=receipt_by_fingerprint.get(reference.receipt_fingerprint),
        ):
            code = None
        elif referenced_gate.phase != "bound":
            code = "activation_reference_gate_unbound"
        elif reference.phase != "settled":
            code = "activation_reference_unsettled"
        else:
            status = supervisor_by_id.get(reference.attempt_id)
            code = (
                "activation_reference_supervisor_unsettled"
                if status is None
                or not status.process_settled
                or status.identity_fingerprint
                != referenced_gate.worker_identity_fingerprint
                else None
            )
            if code is None and (
                referenced_gate.identity is None
                or worker_native_group_status_after_restart(referenced_gate.identity)
                not in {"absent", "prior_boot_absent"}
            ):
                code = "activation_reference_native_absence_unverified"
        if code is not None:
            activation_issue = (reference.attempt_id, code)
            global_unverified_activation.append(activation_issue)
            if relevant:
                unverified_activation.append(activation_issue)
    receipt_gate_ids: list[str] = []
    unsettled: list[str] = []
    unverified: list[tuple[str, str]] = []
    globally_unverified: list[tuple[str, str]] = []
    for item in gates:
        selected_receipt_gate = (
            gate is not None and item.receipt_fingerprint == gate.receipt_fingerprint
        )
        if selected_receipt_gate:
            receipt_gate_ids.append(item.attempt_id)
        referenced_receipt = receipt_by_fingerprint.get(item.receipt_fingerprint)
        group_status: GroupStatus = (
            gated.group_status
            if item.attempt_id == attempt_id
            else (
                "unobserved"
                if item.identity is None or referenced_receipt is None
                else worker_native_group_status_after_restart(item.identity)
            )
        )
        issue = receipt_gate_reference_issue(
            item,
            referenced_receipt,
            supervisor_by_id.get(item.attempt_id),
            group_status,
            activation_by_id.get(item.attempt_id),
            product_id=bindings.product_id,
        )
        if issue is None:
            continue
        globally_unverified.append((item.attempt_id, issue))
        if selected_receipt_gate:
            if issue in {
                "receipt_reference_gate_unbound",
                "receipt_reference_supervisor_absent",
                "receipt_reference_supervisor_unsettled",
            }:
                unsettled.append(item.attempt_id)
            unverified.append((item.attempt_id, issue))
    receipt_gate_references = tuple(receipt_gate_ids)
    unsettled_gate_references = tuple(unsettled)
    unverified_gate_references = tuple(unverified)
    global_unverified_gate_references = tuple(sorted(globally_unverified))
    receipt_references_verified = (
        activation_initialized
        and historical_opt_in_verified
        and not global_unverified_opt_in
        and receipt is not None
        and gate is not None
        and bool(receipt_gate_references)
        and set(receipt_gate_references)
        == {
            reference.attempt_id
            for reference in retained_activation_references
            if reference.receipt_fingerprint == receipt.receipt.fingerprint
        }
        and not unverified_gate_references
        and not global_unverified_gate_references
        and not unverified_activation
        and activation_state is not None
        and not activation_state["publications"]
        and not any(
            fingerprint == receipt.receipt.fingerprint
            for fingerprint, _ in active_references
        )
    )
    with product.pinned_state_root_gc_read() as root_fd:
        state_names = tuple(os.listdir(root_fd))
        payloads = tuple(
            sorted(
                name
                for name in state_names
                if name.startswith("worker-payload-")
                or bindings.registered_staging.fullmatch(name)
            )
        )
        repair_references = tuple(
            sorted(
                name
                for name in state_names
                if bindings.payload_repair.fullmatch(name) is not None
            )
        )
        receipt_by_fingerprint = {item.receipt.fingerprint: item for item in receipts}
        registered_repair_reference_verified = bool(repair_references)
        for name in repair_references:
            match = bindings.payload_repair.fullmatch(name)
            if match is None or match.group("kind") != "registered":
                registered_repair_reference_verified = False
                break
            repair_attempt_id = match.group("attempt")
            repair_gate = gate_by_id.get(repair_attempt_id)
            repair_intent = bindings.registered().read(root_fd, repair_attempt_id)
            archived = archived_proofs.get(repair_attempt_id)
            if (
                repair_gate is None
                or repair_intent is None
                or not registered_repair_matches_no_effect_closure(
                    repair_intent,
                    product_id=bindings.product_id,
                    gate=repair_gate,
                    receipt=receipt_by_fingerprint.get(repair_gate.receipt_fingerprint),
                    activation=activation_by_id.get(repair_attempt_id),
                    supervisor=supervisor_by_id.get(repair_attempt_id),
                )
                or (
                    archived is not None
                    and sha256(
                        canonical_json_bytes(repair_intent.to_dict()) + b"\n"
                    ).hexdigest()
                    != archived.repair_intent_digest
                )
            ):
                registered_repair_reference_verified = False
                break
        unrecognized_worker_state = tuple(
            sorted(
                name
                for name in state_names
                if name.casefold().startswith(("worker-", ".worker-"))
                and not bindings.known_state_name(name)
            )
        )
    product.assert_root_gc_authority_current()
    attempt_reference = make_attempt_reference(
        gate,
        receipt,
        product_id=bindings.product_id,
        reference_type=bindings.reference(),
    )
    history_stream_snapshots = _capture_history_snapshots(bindings, product)
    receipt_history_revision = (
        next(
            snapshot.total_revision
            for snapshot in history_stream_snapshots
            if snapshot.stem == "worker-activation-receipts"
        )
        if v2_owner_present
        else len(receipts)
    )
    gate_history_revision = max((item.journal_revision for item in gates), default=0)
    supervisor_history_revision = max(
        (item.record_revision for item in supervisor_by_id.values()), default=0
    )
    if v2_owner_present:
        with product.pinned_state_root_gc_read() as root_fd:
            with RootedFileIO(product.state_root, root_fd) as file_io:
                with file_io.bind(
                    product.state_root / PRODUCT_OWNER_INDEX_NAME, durable=False
                ) as rooted:
                    gate_history_revision = (
                        bindings.reader()
                        .read(rooted, stem="worker-start-gates")
                        .last_revision
                    )
                    supervisor_history_revision = (
                        bindings.reader()
                        .read(rooted, stem="worker-supervisor")
                        .last_revision
                    )
    expected_stream_revisions = {
        "worker-opt-in": opt_in_projection.revision,
        "worker-activation-receipts": receipt_history_revision,
        "worker-activation-state": (
            0
            if activation_state is None
            else cast(int, activation_state["stateRevision"])
        ),
        "worker-start-gates": gate_history_revision,
        "worker-supervisor": supervisor_history_revision,
    }
    stream_revisions_match = all(
        snapshot.total_revision == expected_stream_revisions[snapshot.stem]
        for snapshot in history_stream_snapshots
    )
    return bindings.review()(
        attempt_id=attempt_id,
        gate_record=gate,
        attempt_record=gated.attempt_record,
        receipt_record=receipt,
        current_opt_in=opt_in,
        historical_opt_in_verified=historical_opt_in_verified,
        group_status=gated.group_status,
        opt_in_history_revision=opt_in_projection.revision,
        retained_opt_in_operation_ids=opt_in_projection.operation_ids,
        opt_in_generation_high_water=tuple(
            sorted(
                (
                    item.plugin_id,
                    item.generation,
                    item.kill_switch_generation,
                    item.action,
                    item.decision_digest,
                )
                for item in opt_in_projection.latest_decisions
            )
        ),
        start_gate_history_revision=gate_history_revision,
        supervisor_history_revision=supervisor_history_revision,
        receipt_history_revision=receipt_history_revision,
        retained_start_gate_attempt_ids=tuple(sorted(gate_by_id)),
        retained_supervisor_attempt_ids=tuple(sorted(supervisor_by_id)),
        retained_receipt_fingerprints=tuple(
            sorted(item.receipt.fingerprint for item in receipts)
        ),
        history_stream_snapshots=history_stream_snapshots,
        history_stream_revisions_match=stream_revisions_match,
        supervisor_epoch_high_water=tuple(sorted(supervisor_epoch_by_key.items())),
        unbound_supervisor_attempt_ids=unbound_supervisor_attempt_ids,
        activation_state_revision=(
            None
            if not activation_initialized
            else (
                0
                if activation_state is None
                else cast(int, activation_state["stateRevision"])
            )
        ),
        active_activation_references=active_references,
        retained_activation_references=retained_activation_references,
        global_activation_reference_ids_match=(
            len(retained_activation_references) == len(gate_by_id)
            and {item.attempt_id for item in retained_activation_references}
            == set(gate_by_id)
        ),
        unverified_activation_references=tuple(unverified_activation),
        global_unverified_activation_references=tuple(
            sorted(global_unverified_activation)
        ),
        global_unverified_opt_in_references=global_unverified_opt_in,
        receipt_gate_references=receipt_gate_references,
        unsettled_receipt_gate_references=unsettled_gate_references,
        unverified_receipt_gate_references=unverified_gate_references,
        global_unverified_receipt_gate_references=(global_unverified_gate_references),
        receipt_references_verified=receipt_references_verified,
        payload_stage_names=payloads,
        retained_payload_repair_reference_names=repair_references,
        registered_repair_reference_verified=registered_repair_reference_verified,
        unrecognized_worker_state_names=unrecognized_worker_state,
        active_runtime_lease_ids=active_runtime_lease_ids,
        active_gc_reservation_count=len(gc_reservations),
        gc_reservation_revision=gc_snapshot.journal_revision,
        gc_matching_revision_refs=matching_attempt_gc_refs(
            attempt_reference, gc_reservations
        ),
        worker_backup_references=(
            bindings.backup_attestation(product, attempt_id=attempt_id)
        ),
    )


def require_committed_v2_history(
    bindings: HistoryProofBindings[ReviewT], *, state_root: Path, root_fd: int
):
    with RootedFileIO(state_root, root_fd) as file_io:
        with file_io.bind(
            state_root / PRODUCT_OWNER_INDEX_NAME, durable=False
        ) as rooted:
            for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
                bindings.reader().read(rooted, stem=stem)

            prepared = _read_preparation(bindings, rooted)
            if prepared is None:
                raise ValueError("Linux Worker GC V2 preparation is absent")
            return prepared.no_effect_archive


def require_settled_history(
    bindings: HistoryProofBindings[ReviewT],
    product: PosixLocalWheelProductSessionOwner,
    *,
    observed_names: tuple[str, ...],
) -> None:
    if type(observed_names) is not tuple or any(
        type(name) is not str for name in observed_names
    ):
        raise ValueError("Linux Worker GC inventory is invalid")
    product.assert_root_gc_authority_current()
    with product.pinned_state_root_gc_read() as root_fd:
        if set(os.listdir(root_fd)) != set(observed_names):
            raise ValueError("Linux Worker GC inventory changed")
        for name in observed_names:
            lowered = name.casefold()
            if bindings.registered_staging.fullmatch(name):
                raise ValueError("Linux Worker GC payload repair is incomplete")
            if lowered.startswith(
                ("worker-", ".worker-")
            ) and not bindings.known_state_name(name):
                raise ValueError("Linux Worker GC reference owner is unrecognized")
            if any(
                lowered.startswith(stem) or lowered.startswith("." + stem)
                for stem in _HISTORY_STEMS
            ) and not any(
                name.startswith(stem + ".") or name.startswith("." + stem + ".")
                for stem in _HISTORY_STEMS
            ):
                raise ValueError("Linux Worker GC history name is invalid")

        archive = None
        if PRODUCT_OWNER_INDEX_NAME in observed_names:
            archive = require_committed_v2_history(
                bindings, state_root=product.state_root, root_fd=root_fd
            )
        elif any(
            name
            in (
                *PREPARATION_STATE_NAMES,
                NO_EFFECT_ARCHIVE_NAME,
                DELETION_LEDGER_NAME,
            )
            for name in observed_names
        ):
            raise ValueError("Linux Worker GC V2 preparation remains open")

        if any(
            name.startswith("worker-history-checkpoints.")
            or name == "worker-history-checkpoint-owner.json"
            for name in observed_names
        ):
            _read_checkpoints(bindings, product)

        gates = bindings.gates(product).attempts()
        supervisor = bindings.supervisor(product)
        attempts = supervisor.attempts()
        receipts = bindings.receipts(product).read_records(retained_only=True)
        opt_in_projection = bindings.opt_in_type()(
            product.state_root / "worker-opt-in.jsonl",
            scope_id=product.policy.project_scope_id,
            gc_gate=product.gc_gate,
            store_id=product.epoch_runtime.registry.store_id,
        ).retention_projection_under_gc_guard()
        opt_in_by_digest = {
            decision.decision_digest: decision
            for decision in opt_in_projection.reference_decisions
        }
        if any(
            (decision := opt_in_by_digest.get(record.opt_in_decision_digest)) is None
            or decision.action != "allow"
            or decision.plugin_id != record.receipt.policy.plugin_id
            or decision.scope_id != record.scope_id
            or decision.generation != record.receipt.policy.owner_selection_generation
            or decision.kill_switch_generation
            != record.receipt.policy.kill_switch_generation
            for record in receipts
        ):
            raise ValueError("Linux Worker GC opt-in history is incomplete")
        activation_journal = bindings.activation_type()(
            product.state_root / "worker-activation-state.jsonl"
        )
        activation = activation_journal.load_read_only()
        retained_activation_attempts = activation_journal.retained_attempts_read_only()
        if activation is not None:
            active = cast(dict[str, dict[str, object]], activation["attempts"])
            publications = cast(dict[str, object], activation["publications"])
            if publications or any(
                item["phase"] != "settled" for item in active.values()
            ):
                raise ValueError("Linux Worker GC activation remains active")

        gate_by_id = {item.attempt_id: item for item in gates}
        attempt_by_id = {item.attempt_id: item for item in attempts}
        receipt_by_fingerprint = {item.receipt.fingerprint: item for item in receipts}
        activation_by_id = {
            item.attempt_id: item for item in retained_activation_attempts
        }
        archived_proofs = (
            {}
            if archive is None
            else {item.attempt_id: item for item in archive.proofs}
        )
        for name in observed_names:
            repair = bindings.payload_repair.fullmatch(name)
            if repair is None:
                continue
            attempt_id = repair.group("attempt")
            if bindings.payload()._stage_exists(root_fd, attempt_id):
                raise ValueError("Linux Worker GC payload repair is incomplete")
            record = attempt_by_id.get(attempt_id)
            kind = repair.group("kind")
            if kind == "empty":
                valid = (
                    bindings.payload().empty.read(root_fd, attempt_id) is not None
                    and record is None
                )
            elif kind == "unmarked":
                valid = (
                    bindings.payload().unmarked.read(root_fd, attempt_id) is not None
                    and record is None
                )
            elif kind == "registered":
                registered = bindings.registered().read(root_fd, attempt_id)
                gate = gate_by_id.get(attempt_id)
                archived = archived_proofs.get(attempt_id)
                valid = bool(
                    registered is not None
                    and gate is not None
                    and registered_repair_matches_no_effect_closure(
                        registered,
                        product_id=bindings.product_id,
                        gate=gate,
                        receipt=receipt_by_fingerprint.get(gate.receipt_fingerprint),
                        activation=activation_by_id.get(attempt_id),
                        supervisor=record,
                    )
                    and (
                        archived is None
                        or sha256(
                            canonical_json_bytes(registered.to_dict()) + b"\n"
                        ).hexdigest()
                        == archived.repair_intent_digest
                    )
                )
            else:
                complete = bindings.payload().complete.read(root_fd, attempt_id)
                valid = (
                    complete is not None
                    and record is not None
                    and record.process_settled
                    and complete[1]
                    == sha256(canonical_json_bytes(record.to_dict())).hexdigest()
                )
            if not valid:
                raise ValueError(
                    "Linux Worker GC payload repair reference is unverified"
                )
        no_effect_ids = {
            gate.attempt_id
            for gate in gates
            if is_no_effect_closure(
                product_id=bindings.product_id,
                gate=gate,
                activation=activation_by_id.get(gate.attempt_id),
                supervisor=attempt_by_id.get(gate.attempt_id),
                receipt=receipt_by_fingerprint.get(gate.receipt_fingerprint),
            )
        }
        if set(gate_by_id) - no_effect_ids != set(attempt_by_id):
            raise ValueError("Linux Worker GC attempt history is incomplete")
        if set(gate_by_id) != {
            item.attempt_id for item in retained_activation_attempts
        }:
            raise ValueError("Linux Worker GC C5 attempt history is incomplete")
        for activation_attempt in retained_activation_attempts:
            gate = gate_by_id.get(activation_attempt.attempt_id)
            if (
                activation_attempt.phase != "settled"
                or gate is None
                or (
                    activation_attempt.attempt_id not in attempt_by_id
                    and activation_attempt.attempt_id not in no_effect_ids
                )
                or gate.receipt_fingerprint != activation_attempt.receipt_fingerprint
                or gate.policy_fingerprint != activation_attempt.policy_fingerprint
            ):
                raise ValueError("Linux Worker GC C5 attempt history is incomplete")
        for gate in gates:
            if gate.attempt_id in no_effect_ids:
                continue
            attempt = attempt_by_id[gate.attempt_id]
            receipt = receipt_by_fingerprint.get(gate.receipt_fingerprint)
            if (
                gate.phase != "bound"
                or gate.identity is None
                or not attempt.process_settled
                or attempt.identity_fingerprint != gate.worker_identity_fingerprint
                or receipt is None
                or receipt.receipt.policy.product_id != bindings.product_id
                or receipt.receipt.policy.product_scope_id != gate.scope_id
                or receipt.receipt.policy.fingerprint != gate.policy_fingerprint
                or worker_native_group_status_after_restart(gate.identity)
                not in {"absent", "prior_boot_absent"}
            ):
                raise ValueError("Linux Worker GC attempt is unsettled")
        if set(os.listdir(root_fd)) != set(observed_names):
            raise ValueError("Linux Worker GC inventory changed")
    product.assert_root_gc_authority_current()


def _capture_history_snapshots(
    bindings: HistoryProofBindings[ReviewT], product: PosixLocalWheelProductSessionOwner
) -> tuple[_SnapshotMethods, ...]:
    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != bindings.product_id
    ):
        raise ValueError(
            f"{bindings.product_label} Worker history streams require their Product"
        )
    return bindings.snapshots().capture(bindings.access(product))


def _read_checkpoints(
    bindings: HistoryProofBindings[ReviewT], product: PosixLocalWheelProductSessionOwner
) -> tuple[_CheckpointMethods, ...]:
    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != bindings.product_id
    ):
        raise ValueError(
            f"{bindings.product_label} Worker checkpoint requires its Product"
        )
    with bindings.checkpoints().bound(bindings.access(product)) as rooted:
        return bindings.checkpoints().read(rooted, access=bindings.access(product))


def _read_preparation(
    bindings: HistoryProofBindings[ReviewT], rooted: RootedFile
) -> _PreparedMethods | None:
    return bindings.preparation().read(rooted, **bindings.preparation_limits())
