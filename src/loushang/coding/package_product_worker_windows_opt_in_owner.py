"""Product-bound Windows Worker decisions from current selection and release."""

from __future__ import annotations

import os

from loushang.harness.package_product._windows_worker_backend_release import (
    _WindowsBackendInstalledMethods,
)
from loushang.harness.package_product._worker_product_authority import (
    _WindowsWorkerProductOptInAuthority,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from .package_product_worker_opt_in import CodingWorkerOptInDecisionV1
from .package_product_worker_opt_in_owner import (
    CodingWorkerProductOptInError,
)
from .package_product_worker_policy import CodingWorkerOptInV1
from .package_product_worker_windows_installed_backend import (
    read_coding_windows_worker_installed_backend_release,
)
from .package_product_worker_windows_opt_in_journal import (
    CodingWindowsWorkerOptInJournal,
)


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
        if (
            os.name != "nt"
            or type(product) is not WindowsLocalWheelProductSessionOwner
            or product.policy.product_id != "coding"
            or not any(
                binding.source_trust_class == "local-worker-candidate"
                for binding in product.policy.bindings
            )
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

    def current(self, plugin_id: str) -> CodingWorkerOptInDecisionV1 | None:
        return super().current(plugin_id)

    def allow(
        self,
        *,
        plugin_id: str,
        operation_id: str,
        expected_generation: int,
        require_worker: bool,
    ) -> CodingWorkerOptInDecisionV1:
        """Record only the selected candidate with an approved installed backend."""

        return super().allow(
            plugin_id=plugin_id,
            operation_id=operation_id,
            expected_generation=expected_generation,
            require_worker=require_worker,
        )

    def revoke(
        self,
        *,
        plugin_id: str,
        operation_id: str,
        expected_generation: int,
    ) -> CodingWorkerOptInDecisionV1:
        """Persist a kill generation even if the release has disappeared."""

        return super().revoke(
            plugin_id=plugin_id,
            operation_id=operation_id,
            expected_generation=expected_generation,
        )


__all__ = ["CodingWindowsWorkerProductOptInOwner"]
