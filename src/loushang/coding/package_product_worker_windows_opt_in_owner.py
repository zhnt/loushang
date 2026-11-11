"""Product-bound Windows Worker decisions from current selection and release."""

from __future__ import annotations

import os

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_worker_candidate import (
    _capture_worker_opt_in_selection,
)

from .package_product_worker_opt_in import CodingWorkerOptInDecisionV1
from .package_product_worker_opt_in_owner import (
    CodingWorkerProductOptInError,
    _plan_worker_allow,
)
from .package_product_worker_windows_installed_backend import (
    read_coding_windows_worker_installed_backend_release,
)
from .package_product_worker_windows_opt_in_journal import (
    CodingWindowsWorkerOptInJournal,
)


class CodingWindowsWorkerProductOptInOwner:
    """Derive, read, and revoke under current Product GC and state-root owners."""

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

    def current(self, plugin_id: str) -> CodingWorkerOptInDecisionV1 | None:
        with self._product.gc_gate.guard():
            self._product.assert_root_gc_authority_current()
            with (
                self._product.epoch_runtime.borrow_product_state_root_descriptor() as root
            ):
                decision = self._journal.current(plugin_id, directory_fd=root)
            self._product.assert_root_gc_authority_current()
            return decision

    def allow(
        self,
        *,
        plugin_id: str,
        operation_id: str,
        expected_generation: int,
        require_worker: bool,
    ) -> CodingWorkerOptInDecisionV1:
        """Record only the selected candidate with an approved installed backend."""

        if type(require_worker) is not bool:
            raise TypeError("Coding Worker requiredness must be boolean")
        with self._product.gc_gate.guard(require_write=True):
            binding, admission = _capture_worker_opt_in_selection(
                self._product,
                plugin_id,
                product_id="coding",
                error_type=CodingWorkerProductOptInError,
                error_prefix="coding_worker",
            )
            closure = read_coding_windows_worker_installed_backend_release(
                self._product
            ).native_closure()
            if closure.native_platform != admission.native_platform:
                raise CodingWorkerProductOptInError(
                    "coding_worker_opt_in_native_platform_changed"
                )
            with (
                self._product.epoch_runtime.borrow_product_state_root_descriptor() as root
            ):
                previous = self._journal.current(plugin_id, directory_fd=root)
                opt_in = _plan_worker_allow(
                    previous,
                    binding=binding,
                    admission=admission,
                    plugin_id=plugin_id,
                    operation_id=operation_id,
                    expected_generation=expected_generation,
                    require_worker=require_worker,
                )
                return self._journal.change(
                    directory_fd=root,
                    plugin_id=plugin_id,
                    operation_id=operation_id,
                    expected_generation=expected_generation,
                    action="allow",
                    opt_in=opt_in,
                )

    def revoke(
        self,
        *,
        plugin_id: str,
        operation_id: str,
        expected_generation: int,
    ) -> CodingWorkerOptInDecisionV1:
        """Persist a kill generation even if the release has disappeared."""

        with self._product.gc_gate.guard(require_write=True):
            self._product.assert_root_gc_authority_current()
            with (
                self._product.epoch_runtime.borrow_product_state_root_descriptor() as root
            ):
                decision = self._journal.change(
                    directory_fd=root,
                    plugin_id=plugin_id,
                    operation_id=operation_id,
                    expected_generation=expected_generation,
                    action="revoke",
                    opt_in=None,
                )
            self._product.assert_root_gc_authority_current()
            return decision


__all__ = ["CodingWindowsWorkerProductOptInOwner"]
