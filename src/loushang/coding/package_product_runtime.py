"""Coding Session selection over an already fenced Package Product."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductRuntimeFactory,
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.package_gc_binding import (
    PluginPackageGcBindingJournal,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.service import PluginManagementService
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .session_manager import SessionManager


@dataclass(frozen=True, slots=True)
class CodingPackageProductStateOwners:
    """Fresh B-only management journals, separate from pre-B replay state."""

    state_root: Path
    gc_gate: PluginPackageGcReservationJournal
    desired_state: PluginDesiredStateLedger
    management: PluginManagementService
    gc_bindings: PluginPackageGcBindingJournal


def open_coding_package_product_state(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
) -> CodingPackageProductStateOwners:
    """Open durable Product owners only for this workspace's fenced Store."""

    if not isinstance(lifecycle, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding Package lifecycle layout is required")
    if not isinstance(epoch_runtime, PackageProductPosixFencedRuntimeOwner):
        raise TypeError("Coding Package Product epoch owner is required")
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if (
        epoch_runtime.registry.store_id != epoch.store_id
        or epoch_runtime.control_root != epoch.control_root
    ):
        raise ValueError("Coding Package Product workspace authority changed")
    state_root = epoch_runtime.prepare_product_state_root()
    gate = PluginPackageGcReservationJournal(state_root / "gc-reservations.jsonl")
    desired = PluginDesiredStateLedger(
        state_root / "desired-state.jsonl", gc_gate=gate
    )
    management = PluginManagementService(
        desired_state=desired,
        operation_journal_path=state_root / "management-operations.jsonl",
    )
    management.recover()
    bindings = PluginPackageGcBindingJournal(state_root / "gc-bindings.jsonl")
    epoch_runtime.assert_current()
    return CodingPackageProductStateOwners(
        state_root=state_root,
        gc_gate=gate,
        desired_state=desired,
        management=management,
        gc_bindings=bindings,
    )


@dataclass(frozen=True, slots=True)
class CodingPosixLocalWheelProductRuntimeOwner:
    """Select the exact Coding Session for a fenced Product owner."""

    product_owner: PosixLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        if (
            not isinstance(self.product_owner, PosixLocalWheelProductSessionOwner)
            or self.product_owner.policy.product_id != "coding"
        ):
            raise ValueError("Coding Package Product owner is required")

    def factory_for_session(
        self, manager: SessionManager
    ) -> PosixLocalWheelProductRuntimeFactory:
        """Bind a live Session to one runtime lease without a legacy route."""

        if not isinstance(manager, SessionManager):
            raise TypeError("Coding Product Session manager is required")
        session_id = manager.get_header().conversation_id
        return self.product_owner.factory_for_session(
            session_id=session_id,
            cwd=Path(manager.get_cwd()),
            runtime_id="coding-session:" + sha256(session_id.encode()).hexdigest(),
        )


__all__ = [
    "CodingPackageProductStateOwners",
    "CodingPosixLocalWheelProductRuntimeOwner",
    "open_coding_package_product_state",
]
