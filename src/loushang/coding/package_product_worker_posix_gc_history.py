"""Read-only Linux Worker history proof for Product Package GC.

This authorizes only Package root deletion after complete attempt settlement.
It keeps every Worker journal and grants no history pruning authority.
"""

from __future__ import annotations

import os
import sys
from hashlib import sha256
from pathlib import Path
from typing import cast

from loushang.harness.journal._rooted_io import RootedFileIO
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.gated_start import (
    worker_native_group_status_after_restart,
)

from .package_product_worker_activation_state_journal import (
    CodingProductWorkerActivationStateJournal,
)
from .package_product_worker_history_checkpoint import (
    read_coding_product_worker_history_checkpoints_under_gc_guard,
)
from .package_product_worker_history_read_v2 import (
    read_coding_worker_v2_retained_history,
)
from .package_product_worker_history_retention import (
    _PAYLOAD_REPAIR,
    _known_worker_state_name,
)
from .package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
)
from .package_product_worker_history_v2_names import (
    DELETION_LEDGER_NAME,
    PREPARATION_STATE_NAMES,
    PRODUCT_OWNER_INDEX_NAME,
)
from .package_product_worker_no_effect_closure import (
    is_coding_worker_no_effect_closure,
)
from .package_product_worker_opt_in import CodingWorkerOptInJournal
from .package_product_worker_payload import (
    _read_complete_repair_intent,
    _read_empty_repair_intent,
    _read_unmarked_repair_intent,
    _stage_exists,
    open_coding_product_worker_supervisor_journal,
)
from .package_product_worker_receipt import (
    read_coding_product_worker_receipt_records,
)
from .package_product_worker_start_gate_journal import (
    CodingWorkerStartGateJournal,
)

_HISTORY_STEMS = (
    "worker-activation-receipts",
    "worker-activation-state",
    "worker-start-gates",
    "worker-supervisor",
    "worker-history-checkpoints",
)


def _require_committed_v2_history(*, state_root: Path, root_fd: int) -> None:
    """Prove the committed Product owner and all five retained streams."""

    file_io = RootedFileIO(state_root, root_fd)
    try:
        with file_io.bind(
            state_root / PRODUCT_OWNER_INDEX_NAME, durable=False
        ) as rooted:
            for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
                read_coding_worker_v2_retained_history(rooted, stem=stem)
    finally:
        file_io.cleanup()


class CodingPosixWorkerGcHistoryAuthority:
    """Join all retained Product attempts under the GC owner's existing guard."""

    def __init__(self, product: PosixLocalWheelProductSessionOwner) -> None:
        if (
            not sys.platform.startswith("linux")
            or type(product) is not PosixLocalWheelProductSessionOwner
            or product.policy.product_id != "coding"
        ):
            raise ValueError("Coding Linux Worker GC requires its Product owner")
        self._product = product

    @property
    def product_owner(self) -> PosixLocalWheelProductSessionOwner:
        return self._product

    def require_settled(self, *, observed_names: tuple[str, ...]) -> None:
        """Reject incomplete, orphaned, or changed Worker history without writes."""

        if type(observed_names) is not tuple or any(
            type(name) is not str for name in observed_names
        ):
            raise ValueError("Linux Worker GC inventory is invalid")
        product = self._product
        product.assert_root_gc_authority_current()
        with product.pinned_state_root_gc_read() as root_fd:
            if set(os.listdir(root_fd)) != set(observed_names):
                raise ValueError("Linux Worker GC inventory changed")
            for name in observed_names:
                lowered = name.casefold()
                if lowered.startswith(
                    ("worker-", ".worker-")
                ) and not _known_worker_state_name(name):
                    raise ValueError("Linux Worker GC reference owner is unrecognized")
                if any(
                    lowered.startswith(stem) or lowered.startswith("." + stem)
                    for stem in _HISTORY_STEMS
                ) and not any(
                    name.startswith(stem + ".") or name.startswith("." + stem + ".")
                    for stem in _HISTORY_STEMS
                ):
                    raise ValueError("Linux Worker GC history name is invalid")

            if PRODUCT_OWNER_INDEX_NAME in observed_names:
                _require_committed_v2_history(
                    state_root=product.state_root, root_fd=root_fd
                )
            elif any(
                name in (*PREPARATION_STATE_NAMES, DELETION_LEDGER_NAME)
                for name in observed_names
            ):
                raise ValueError("Linux Worker GC V2 preparation remains open")

            if any(
                name.startswith("worker-history-checkpoints.")
                or name == "worker-history-checkpoint-owner.json"
                for name in observed_names
            ):
                read_coding_product_worker_history_checkpoints_under_gc_guard(product)

            gates = CodingWorkerStartGateJournal(product).attempts()
            supervisor = open_coding_product_worker_supervisor_journal(product)
            attempts = supervisor.attempts()
            receipts = read_coding_product_worker_receipt_records(
                product, retained_only=True
            )
            opt_in_projection = CodingWorkerOptInJournal(
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
                (decision := opt_in_by_digest.get(record.opt_in_decision_digest))
                is None
                or decision.action != "allow"
                or decision.plugin_id != record.receipt.policy.plugin_id
                or decision.scope_id != record.scope_id
                or decision.generation
                != record.receipt.policy.owner_selection_generation
                or decision.kill_switch_generation
                != record.receipt.policy.kill_switch_generation
                for record in receipts
            ):
                raise ValueError("Linux Worker GC opt-in history is incomplete")
            activation_journal = CodingProductWorkerActivationStateJournal(
                product.state_root / "worker-activation-state.jsonl"
            )
            activation = activation_journal.load_read_only()
            retained_activation_attempts = (
                activation_journal.retained_attempts_read_only()
            )
            if activation is not None:
                active = cast(dict[str, dict[str, object]], activation["attempts"])
                publications = cast(dict[str, object], activation["publications"])
                if publications or any(
                    item["phase"] != "settled" for item in active.values()
                ):
                    raise ValueError("Linux Worker GC activation remains active")

            gate_by_id = {item.attempt_id: item for item in gates}
            attempt_by_id = {item.attempt_id: item for item in attempts}
            for name in observed_names:
                repair = _PAYLOAD_REPAIR.fullmatch(name)
                if repair is None:
                    continue
                attempt_id = repair.group("attempt")
                if _stage_exists(root_fd, attempt_id):
                    raise ValueError("Linux Worker GC payload repair is incomplete")
                record = attempt_by_id.get(attempt_id)
                kind = repair.group("kind")
                if kind == "empty":
                    valid = (
                        _read_empty_repair_intent(root_fd, attempt_id) is not None
                        and record is None
                    )
                elif kind == "unmarked":
                    valid = (
                        _read_unmarked_repair_intent(root_fd, attempt_id) is not None
                        and record is None
                    )
                else:
                    complete = _read_complete_repair_intent(root_fd, attempt_id)
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
            receipt_by_fingerprint = {
                item.receipt.fingerprint: item for item in receipts
            }
            activation_by_id = {
                item.attempt_id: item for item in retained_activation_attempts
            }
            no_effect_ids = {
                gate.attempt_id
                for gate in gates
                if is_coding_worker_no_effect_closure(
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
                    or gate.receipt_fingerprint
                    != activation_attempt.receipt_fingerprint
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
                    or receipt.receipt.policy.product_id != "coding"
                    or receipt.receipt.policy.product_scope_id != gate.scope_id
                    or receipt.receipt.policy.fingerprint != gate.policy_fingerprint
                    or worker_native_group_status_after_restart(gate.identity)
                    not in {"absent", "prior_boot_absent"}
                ):
                    raise ValueError("Linux Worker GC attempt is unsettled")
            if set(os.listdir(root_fd)) != set(observed_names):
                raise ValueError("Linux Worker GC inventory changed")
        product.assert_root_gc_authority_current()


__all__ = ["CodingPosixWorkerGcHistoryAuthority"]
