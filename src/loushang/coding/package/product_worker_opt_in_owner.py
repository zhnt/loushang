"""Product-owned, default-dark opt-in for one selected local Worker candidate."""

from __future__ import annotations

from loushang.harness.package_product._worker_product_authority import (
    _PosixWorkerProductOptInAuthority,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)

from .product_worker_installed_native import (
    open_coding_product_installed_worker_release_reader,
)
from .product_worker_opt_in import (
    CodingWorkerOptInDecisionV1,
    CodingWorkerOptInJournal,
    CodingWorkerOptInRetentionProjectionV1,
)
from .product_worker_policy import CodingWorkerNativeClosureV1, CodingWorkerOptInV1


class CodingWorkerProductOptInError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CodingWorkerProductOptInOwner(
    _PosixWorkerProductOptInAuthority[
        CodingWorkerOptInDecisionV1,
        CodingWorkerOptInRetentionProjectionV1,
        CodingWorkerOptInV1,
    ]
):
    """Derive an operator decision from current Product facts, without launching."""

    _opt_in_error = CodingWorkerProductOptInError
    _error_prefix = "coding_worker_"
    _product_id = "coding"
    _requiredness_error = "Coding Worker requiredness must be boolean"
    _selection_error_prefix = "coding_worker"
    _opt_in_type = CodingWorkerOptInV1

    def _current_native_closure(self) -> CodingWorkerNativeClosureV1:
        return open_coding_product_installed_worker_release_reader(
            self._product
        ).current_closure()

    def __init__(self, product_owner: PosixLocalWheelProductSessionOwner) -> None:
        if (
            not isinstance(product_owner, PosixLocalWheelProductSessionOwner)
            or product_owner.policy.product_id != "coding"
            or not any(
                binding.source_trust_class == "local-worker-candidate"
                for binding in product_owner.policy.bindings
            )
        ):
            raise ValueError("Coding Worker candidate Product owner is required")
        self._product = product_owner
        self._journal = CodingWorkerOptInJournal(
            product_owner.state_root / "worker-opt-in.jsonl",
            scope_id=product_owner.policy.project_scope_id,
            gc_gate=product_owner.gc_gate,
            store_id=product_owner.epoch_runtime.registry.store_id,
        )


__all__ = ["CodingWorkerProductOptInError", "CodingWorkerProductOptInOwner"]
