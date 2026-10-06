"""Read-only Linux Worker history proof for Product Package GC.

This authorizes only Package root deletion after complete attempt settlement.
It keeps every Worker journal and grants no history pruning authority.
"""

from __future__ import annotations

import os
import sys
from typing import cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.worker.gated_start import (
    worker_native_group_status_after_restart,
)

from .package_product_worker_activation_state_journal import (
    CodingProductWorkerActivationStateJournal,
)
from .package_product_worker_payload import (
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
)


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
                if any(
                    lowered.startswith(stem) or lowered.startswith("." + stem)
                    for stem in _HISTORY_STEMS
                ) and not any(
                    name.startswith(stem + ".") or name.startswith("." + stem + ".")
                    for stem in _HISTORY_STEMS
                ):
                    raise ValueError("Linux Worker GC history name is invalid")

            gates = CodingWorkerStartGateJournal(product).attempts()
            supervisor = open_coding_product_worker_supervisor_journal(product)
            attempts = supervisor.attempts()
            receipts = read_coding_product_worker_receipt_records(product)
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
            receipt_by_fingerprint = {
                item.receipt.fingerprint: item for item in receipts
            }
            if set(gate_by_id) != set(attempt_by_id):
                raise ValueError("Linux Worker GC attempt history is incomplete")
            for activation_attempt in retained_activation_attempts:
                gate = gate_by_id.get(activation_attempt.attempt_id)
                if (
                    activation_attempt.phase != "settled"
                    or gate is None
                    or activation_attempt.attempt_id not in attempt_by_id
                    or gate.receipt_fingerprint
                    != activation_attempt.receipt_fingerprint
                    or gate.policy_fingerprint
                    != activation_attempt.policy_fingerprint
                ):
                    raise ValueError("Linux Worker GC C5 attempt history is incomplete")
            for gate in gates:
                attempt = attempt_by_id[gate.attempt_id]
                receipt = receipt_by_fingerprint.get(gate.receipt_fingerprint)
                if (
                    gate.phase != "bound"
                    or gate.identity is None
                    or not attempt.process_settled
                    or attempt.identity_fingerprint
                    != gate.worker_identity_fingerprint
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
