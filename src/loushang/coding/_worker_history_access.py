"""Coding Product binding for the existing narrow Worker history access port."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
    WindowsLocalWheelProductSessionOwner,
)


@dataclass(frozen=True, slots=True)
class _CodingHistoryAccess:
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
class _CodingWindowsHistoryAccess:
    _product: WindowsLocalWheelProductSessionOwner

    def guard(self, *, require_write: bool = False) -> AbstractContextManager[object]:
        if require_write:
            return self._product.gc_gate.guard(require_write=True)
        return self._product.gc_gate.guard()

    def assert_current(self) -> None:
        self._product.assert_root_gc_authority_current()

    def borrow_state_root(self) -> AbstractContextManager[int]:
        return self._product.epoch_runtime.borrow_product_state_root_descriptor()
