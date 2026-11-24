"""Borrow existing Product authority through the narrow Worker history ports."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path

from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsEpochRuntimeLeaseRegistry,
    PackageWindowsRuntimeQuiescenceV1,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    has_worker_candidate_binding,
)

from .product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
    WindowsLocalWheelProductSessionOwner,
)


@contextmanager
def windows_product_worker_quiescence(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    active_message: str,
    active_error: type[Exception] = ValueError,
) -> Iterator[tuple[PackageWindowsEpochRuntimeLeaseRegistry, PackageWindowsRuntimeQuiescenceV1]]:
    """Pin the existing offline lease view before a caller takes its GC guard."""
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(store_id=registry.store_id) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise active_error(active_message)
        yield registry, quiescence


def is_posix_worker_candidate_product(
    product: object, *, product_id: str
) -> bool:
    """Check eligibility to open a candidate decision or approval journal."""
    return (
        isinstance(product, PosixLocalWheelProductSessionOwner)
        and product.policy.product_id == product_id
        and has_worker_candidate_binding(product.policy)
    )


def require_current_worker_activation_product(
    product: PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner,
    *,
    product_id: str,
    candidate_required: str,
) -> None:
    """Recheck the fenced root before reading the C5 activation policy."""
    product.assert_root_gc_authority_current()
    policy = product.policy
    if policy.product_id != product_id or not has_worker_candidate_binding(policy):
        raise ValueError(candidate_required)


@dataclass(frozen=True, slots=True)
class PosixProductWorkerHistoryAccess:
    _product: PosixLocalWheelProductSessionOwner

    @property
    def scope_id(self) -> str:
        return self._product.policy.project_scope_id

    @property
    def store_id(self) -> str:
        return self._product.epoch_runtime.registry.store_id

    def guard(self, *, require_write: bool) -> AbstractContextManager[object]:
        return self._product.gc_gate.guard(require_write=require_write)

    def assert_current(self) -> None:
        self._product.assert_root_gc_authority_current()

    @property
    def state_root(self) -> Path:
        return self._product.state_root

    def pin_state_read(self) -> AbstractContextManager[int]:
        return self._product.pinned_state_root_gc_read()


@dataclass(frozen=True, slots=True)
class WindowsProductWorkerHistoryAccess:
    _product: WindowsLocalWheelProductSessionOwner

    def guard(self, *, require_write: bool = False) -> AbstractContextManager[object]:
        if require_write:
            return self._product.gc_gate.guard(require_write=True)
        return self._product.gc_gate.guard()

    def assert_current(self) -> None:
        self._product.assert_root_gc_authority_current()

    def borrow_state_root(self) -> AbstractContextManager[int]:
        return self._product.epoch_runtime.borrow_product_state_root_descriptor()

    @contextmanager
    def decision_root(self, *, require_write: bool = False) -> Iterator[int]:
        """Hold Product GC admission while reading or settling private decisions."""
        with self.guard(require_write=require_write):
            self.assert_current()
            with self.borrow_state_root() as root:
                yield root
            self.assert_current()
