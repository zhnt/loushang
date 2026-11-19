"""Product custody for one durable, identity-bound Linux Worker start gate.

The caller must keep this owner alive until Hosting returns an exact gated
child lease. A failed release closes the gate and leaves a conservative debt.
"""

from __future__ import annotations

from typing import cast

from loushang.harness.package_product._worker_product_authority import (
    PosixProductWorkerStartGate,
)
from loushang.harness.worker.contracts import ManagedWorkerLaunchRequestV1
from loushang.harness.worker.product_activation import ProductWorkerActivationReceiptV1

from .product_worker_receipt import CodingWorkerProductReceiptOwner
from .product_worker_start_gate_journal import CodingWorkerStartGateJournal


class CodingWorkerStartGateError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CodingProductWorkerStartGate(PosixProductWorkerStartGate):
    """Single-use Product-held write authority for an exact gated H6 child."""

    _error_type = CodingWorkerStartGateError
    _error_prefix = "coding_worker_start_gate"
    _journal_type = staticmethod(CodingWorkerStartGateJournal)

    def __init__(
        self,
        *,
        receipt_owner: CodingWorkerProductReceiptOwner,
        receipt: ProductWorkerActivationReceiptV1,
        worker_request: ManagedWorkerLaunchRequestV1,
        attempt_id: str,
    ) -> None:
        if not isinstance(receipt_owner, CodingWorkerProductReceiptOwner):
            raise TypeError("Coding Worker receipt owner is required")
        self._initialize(
            receipt_owner=receipt_owner,
            receipt=receipt,
            worker_request=worker_request,
            attempt_id=attempt_id,
        )

    @property
    def receipt_owner(self) -> CodingWorkerProductReceiptOwner:
        return cast(CodingWorkerProductReceiptOwner, self._receipt_owner)


__all__ = ["CodingProductWorkerStartGate", "CodingWorkerStartGateError"]
