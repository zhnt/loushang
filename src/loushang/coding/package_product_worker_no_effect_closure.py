"""Read-only join for a Product Worker settled before native effect."""

from __future__ import annotations

from loushang.harness.worker.journal import WorkerAttemptRecordV1

from .package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from .package_product_worker_receipt import CodingWorkerReceiptRecordV1
from .package_product_worker_start_gate_journal import CodingWorkerStartGateRecordV1


def is_coding_worker_no_effect_closure(
    *,
    gate: CodingWorkerStartGateRecordV1,
    activation: CodingProductWorkerRetainedAttemptV1 | None,
    supervisor: WorkerAttemptRecordV1 | None,
    receipt: CodingWorkerReceiptRecordV1 | None,
) -> bool:
    """Recognize only the C5 proof minted by the no-effect transition.

    Product C5 history replay rejects a no-effect marker after effect start.
    The unreleased gate and absent Supervisor record independently prove that
    native launch did not begin. This projection never settles an attempt.
    """

    if activation is None or receipt is None:
        return False
    policy = receipt.receipt.policy
    return bool(
        activation.phase == "settled"
        and activation.no_effect
        and activation.cleanup_contract_version == 1
        and activation.attempt_id == gate.attempt_id
        and activation.receipt_fingerprint == gate.receipt_fingerprint
        and activation.policy_fingerprint == gate.policy_fingerprint
        and activation.owner_generation == policy.owner_selection_generation
        and gate.phase == "intent"
        and gate.identity is None
        and supervisor is None
        and receipt.receipt.fingerprint == gate.receipt_fingerprint
        and policy.product_id == "coding"
        and policy.product_scope_id == gate.scope_id
        and policy.fingerprint == gate.policy_fingerprint
    )


__all__ = ["is_coding_worker_no_effect_closure"]
