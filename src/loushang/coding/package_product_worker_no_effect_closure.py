"""Read-only join for a Product Worker settled before native effect."""

from __future__ import annotations

from loushang.harness.worker.history._no_effect import is_no_effect_closure
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
    return is_no_effect_closure(
        gate=gate,
        activation=activation,
        supervisor=supervisor,
        receipt=receipt,
        product_id="coding",
    )


__all__ = ["is_coding_worker_no_effect_closure"]
