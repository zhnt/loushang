"""Fixed Product custody for the explicit Coding Worker activation state.

The generic C5 coordinator may use this CAS port only when the selected
Product has a Worker candidate policy. Opening it does not select a Worker or
grant process recovery authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)

from .package_product_worker_activation_state_journal import (
    CodingProductWorkerActivationStateJournal,
)


class CodingProductWorkerActivationStateStore:
    """Epoch-checked Product binding around one private durable C5 journal."""

    def __init__(self, product: PosixLocalWheelProductSessionOwner) -> None:
        if not isinstance(product, PosixLocalWheelProductSessionOwner):
            raise TypeError("Coding Worker activation state requires a Product owner")
        product.assert_root_gc_authority_current()
        if product.policy.product_id != "coding" or not any(
            binding.source_trust_class == "local-worker-candidate"
            for binding in product.policy.bindings
        ):
            raise ValueError("Coding Worker candidate owner is required")
        self._product = product
        self._journal = CodingProductWorkerActivationStateJournal(
            product.state_root / "worker-activation-state.jsonl"
        )

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


def open_coding_product_worker_activation_state_store(
    product: PosixLocalWheelProductSessionOwner,
) -> CodingProductWorkerActivationStateStore:
    """Bind one explicit Worker candidate to its Product-fixed state root."""

    return CodingProductWorkerActivationStateStore(product)


__all__ = [
    "CodingProductWorkerActivationStateStore",
    "open_coding_product_worker_activation_state_store",
]
