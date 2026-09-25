"""Coding Session selection over an already fenced Package Product."""

from __future__ import annotations

import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductHostInputs,
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
from .package_builtin_wheel import (
    coding_base_product_local_wheel_policy,
    prepare_posix_coding_base_product_wheel,
)
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
    desired = PluginDesiredStateLedger(state_root / "desired-state.jsonl", gc_gate=gate)
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


def open_coding_base_product_runtime_owner(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    state: CodingPackageProductStateOwners,
    *,
    workspace: Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
) -> CodingPosixLocalWheelProductRuntimeOwner:
    """Compose the installed base Plugin from one fenced Product authority."""

    if not isinstance(lifecycle, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding Package lifecycle layout is required")
    if not isinstance(epoch_runtime, PackageProductPosixFencedRuntimeOwner):
        raise TypeError("Coding Package Product epoch owner is required")
    if not isinstance(state, CodingPackageProductStateOwners):
        raise TypeError("Coding Package Product state owners are required")
    if (
        not isinstance(workspace, Path)
        or not workspace.is_absolute()
        or ".." in workspace.parts
        or workspace != workspace.resolve(strict=True)
    ):
        raise ValueError("Coding Product workspace is not canonical")
    scope_id = (
        "workspace:"
        + sha256(
            b"loushang.coding-continuity-workspace/v1\0" + os.fsencode(str(workspace))
        ).hexdigest()
    )
    if lifecycle.scope_id != scope_id:
        raise ValueError("Coding Product workspace scope changed")
    if not isinstance(runtime_version, str) or not runtime_version:
        raise ValueError("Coding Product runtime version is required")
    if type(runtime_protocol_epoch) is not int or runtime_protocol_epoch < 1:
        raise ValueError("Coding Product runtime protocol epoch is invalid")
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if (
        epoch_runtime.registry.store_id != epoch.store_id
        or epoch_runtime.control_root != epoch.control_root
    ):
        raise ValueError("Coding Package Product workspace authority changed")
    state_root = epoch_runtime.prepare_product_state_root()
    if (
        state.state_root != state_root
        or state.gc_gate.path != state_root / "gc-reservations.jsonl"
        or state.desired_state.path != state_root / "desired-state.jsonl"
        or state.management.operation_journal_path
        != state_root / "management-operations.jsonl"
        or state.management.retirement_intent_journal_path
        != state_root / "management-operations.jsonl.retirement-intents"
        or state.management.retirement_set_journal_path
        != state_root / "management-operations.jsonl.retirement-sets"
        or state.gc_bindings.path != state_root / "gc-bindings.jsonl"
    ):
        raise ValueError("Coding Package Product state authority changed")
    switch = epoch_runtime.cutover_result.switch_receipt
    if switch is None:
        raise ValueError("Coding Package Product root is not fenced")
    source_root = epoch_runtime.prepare_product_source_root()
    artifact = prepare_posix_coding_base_product_wheel(source_root)
    host_inputs = PosixLocalWheelProductHostInputs.current_host(
        max_transport_bytes=2 * 1024 * 1024
    )
    policy = coding_base_product_local_wheel_policy(
        artifact,
        project_scope_id=scope_id,
        resolution_environment_fingerprint=host_inputs.environment.fingerprint,
        policy_revision="coding-product-package-policy:1",
        quota_profile_revision="coding-product-package-quota:1",
        authority_id="coding-product-local-source",
    )
    return CodingPosixLocalWheelProductRuntimeOwner(
        product_owner=PosixLocalWheelProductSessionOwner(
            workspace=workspace,
            state_root=state.state_root,
            plugin_store_root=epoch.epoch_root(switch.namespace_id),
            policy=policy,
            environment=host_inputs.environment,
            acquisition_budgets=host_inputs.acquisition_budgets,
            inspection_budgets=host_inputs.inspection_budgets,
            closure_budgets=host_inputs.closure_budgets,
            root_store_identity=f"coding-product-root-store:{epoch.store_id}",
            dependency_store_identity=f"coding-product-dependency-store:{epoch.store_id}",
            epoch_runtime=epoch_runtime,
            management=state.management,
            desired_state=state.desired_state,
            gc_bindings=state.gc_bindings,
            gc_gate=state.gc_gate,
            actor_id="product:coding",
            desired_policy_revision="coding-product-desired-policy:1",
            recovery_identity=f"coding-product-recovery:{epoch.store_id}",
            runtime_version=runtime_version,
            runtime_protocol_epoch=runtime_protocol_epoch,
        )
    )


__all__ = [
    "CodingPackageProductStateOwners",
    "CodingPosixLocalWheelProductRuntimeOwner",
    "open_coding_base_product_runtime_owner",
    "open_coding_package_product_state",
]
