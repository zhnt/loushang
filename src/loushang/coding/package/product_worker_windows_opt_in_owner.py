"""Product-bound Windows Worker decisions from current selection and release."""

from __future__ import annotations

import os

from loushang.coding.harness.worker.windows_admission import is_windows_product
from loushang.harness.package_product._windows_worker_backend_release import (
    _WindowsBackendInstalledMethods,
)
from loushang.harness.package_product._worker_product_authority import (
    _WindowsWorkerProductOptInAuthority,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from .product_worker_opt_in import CodingWorkerOptInDecisionV1
from .product_worker_opt_in_owner import CodingWorkerProductOptInError
from .product_worker_policy import CodingWorkerOptInV1
from .product_worker_windows_installed_backend import (
    read_coding_windows_worker_installed_backend_release,
)
from .product_worker_windows_opt_in_journal import CodingWindowsWorkerOptInJournal


class CodingWindowsWorkerProductOptInOwner(
    _WindowsWorkerProductOptInAuthority[
        CodingWorkerOptInDecisionV1, CodingWorkerOptInV1
    ]
):
    _opt_in_type = CodingWorkerOptInV1
    _opt_in_error = CodingWorkerProductOptInError
    _error_prefix = "coding_worker_"
    _product_id = "coding"
    _requiredness_error = "Coding Worker requiredness must be boolean"
    _selection_error_prefix = "coding_worker"

    def __init__(self, product: WindowsLocalWheelProductSessionOwner) -> None:
        if not is_windows_product(product, "coding", os.name) or not any(
            binding.source_trust_class == "local-worker-candidate"
            for binding in product.policy.bindings
        ):
            raise ValueError("Windows Worker candidate Product owner is required")
        product.assert_root_gc_authority_current()
        self._product = product
        self._journal = CodingWindowsWorkerOptInJournal(
            product.state_root / "worker-opt-in.jsonl",
            scope_id=product.policy.project_scope_id,
        )

    def _read_backend(
        self, product: WindowsLocalWheelProductSessionOwner
    ) -> _WindowsBackendInstalledMethods:
        return read_coding_windows_worker_installed_backend_release(product)


__all__ = ["CodingWindowsWorkerProductOptInOwner"]
