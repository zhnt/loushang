"""Prepare the selected Coding plugin owners over the existing Session custody."""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from loushang.coding.composition.base_plugin import (
    CodingBasePluginAssembly,
    CodingBasePluginAssemblyError,
)
from loushang.coding.composition.capability_plugins import (
    CodingCapabilityPluginCompositionAssembly,
    CodingCapabilityPluginCompositionPreparation,
    CodingCapabilityPluginCompositionRequest,
    create_coding_capability_plugin_composition_request,
    prepare_coding_capability_plugin_composition,
)
from loushang.coding.composition.capability_specs import CodingCapabilityPluginConfig
from loushang.coding.composition.product_capability_plugins import (
    prepare_coding_product_capability_plugin_composition,
)
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycle,
    CodingPluginLifecycleStateLayout,
    build_coding_plugin_lifecycle,
    resolve_coding_plugin_lifecycle_state_layout,
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.resources.runtime import CodingPackageMaterializer
from loushang.coding.session.manager import SessionManager
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
)
from loushang.harness.config.agent import CapabilityMountMode
from loushang.harness.package_product._selected_plugin_revisions import (
    ProductAdmissionFailure,
    capture_enabled_plugin_recheck,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.session._cleanup import ExplicitTemporaryDirectory
from loushang.harness.session.bootstrap_construction import (
    PreparationRootCustody,
    prepare_managed_plugin_startup,
)
from loushang.harness.session.bootstrap_services import BootstrapServices
from loushang.harness.session.product_composition_assembly import ProductPluginPlanSeed

_MANAGED_PACKAGE_AUTHORITY_MISMATCH = (
    "Durable Coding base package storage must use the canonical workspace authority",
    "coding_base_package_authority_mismatch",
)
_MANAGED_PACKAGE_REPLAY_CHECK = "coding_base_exact_replay"

_SESSION_MANAGER_PLUGIN_OWNER_LOCK = threading.Lock()
_SESSION_MANAGER_PLUGIN_OWNER_ATTRIBUTE = "_loushang_coding_plugin_owner_id"

_Cleanup = Callable[[], None]
_PreparePrimary = Callable[
    ["CodingPluginLifecycle", "CodingPackageMaterializer", _Cleanup | None],
    "CodingBasePluginAssembly | None",
]


@dataclass(frozen=True, slots=True)
class ManagedPluginPreparation:
    lifecycle: CodingPluginLifecycle
    materializer: CodingPackageMaterializer
    primary: CodingBasePluginAssembly | None
    eager_cleanup: _Cleanup | None
    deferred_cleanup: _Cleanup | None

    def prepare_capabilities(
        self,
        request: CodingCapabilityPluginCompositionRequest,
        configurations: Mapping[str, CodingCapabilityPluginConfig],
        *,
        session_manager: SessionManager,
        session_id: str,
        state_root: Path,
        clock: Callable[[], int],
        legacy_disabled_plugin_ids: frozenset[str],
        management_cleanup: _Cleanup | None,
        state_cleanup: _Cleanup | None,
        private_state_cleanup: _Cleanup | None = None,
        base: CodingBasePluginAssembly | None = None,
        plan_seed: ProductPluginPlanSeed | None = None,
    ) -> CodingCapabilityPluginCompositionPreparation:
        return prepare_coding_capability_plugin_composition(
            request,
            session_id=session_id,
            configurations=configurations,
            package_materializer=self.materializer,
            lifecycle=self.lifecycle,
            legacy_disabled_plugin_ids=legacy_disabled_plugin_ids,
            session_owner_id=_session_manager_plugin_owner_id(session_manager),
            management_state_cleanup=management_cleanup,
            state_root=state_root,
            clock=clock,
            coding_base_plugin_assembly=base,
            coding_product_plan_seed=plan_seed,
            state_cleanup=state_cleanup,
            private_state_cleanup=private_state_cleanup,
        )


def prepare_managed_plugins(
    *,
    session_manager: SessionManager,
    services: BootstrapServices,
    session_id: str,
    package_materializer: CodingPackageMaterializer | None,
    resolved_package_materializer: CodingPackageMaterializer | None,
    ephemeral_prefix: str | None,
    prepare_primary: _PreparePrimary | None,
    needs_eager: bool,
    needs_deferred: bool,
) -> ManagedPluginPreparation:
    def resolve_layout(ephemeral: str | None) -> CodingPluginLifecycleStateLayout:
        cwd = session_manager.get_cwd()
        if ephemeral is None:
            return resolve_coding_plugin_lifecycle_state_layout(cwd)
        return resolve_ephemeral_coding_plugin_lifecycle_state_layout(ephemeral, cwd=cwd)

    def record_failure(error: BaseException) -> None:
        if isinstance(error, CodingBasePluginAssemblyError):
            services.diagnostics_service.capture_failure(
                code=error.code,
                error=str(error),
                phase="startup",
                source="bootstrap",
                session_id=session_id,
                details={"check": _MANAGED_PACKAGE_REPLAY_CHECK, "ok": False},
            )
    message, code = _MANAGED_PACKAGE_AUTHORITY_MISMATCH
    return ManagedPluginPreparation(
        *prepare_managed_plugin_startup(
            resolve_layout=resolve_layout,
            build_lifecycle=build_coding_plugin_lifecycle,
            materializer_type=CodingPackageMaterializer,
            package_materializer=package_materializer,
            resolved_package_materializer=resolved_package_materializer,
            ephemeral_prefix=ephemeral_prefix,
            prepare_primary=prepare_primary,
            needs_eager=needs_eager,
            needs_deferred=needs_deferred,
            diagnostics_service=services.diagnostics_service,
            session_id=session_id,
            authority_mismatch=partial(CodingBasePluginAssemblyError, message, code=code),
            record_failure=record_failure,
            directory_factory=ExplicitTemporaryDirectory,
        )
    )


def bind_deferred_plugin(
    workspace_binding: CapabilityBundleProviderBinding,
    *,
    session_manager: SessionManager,
    session_id: str,
    plugin_id: str,
    managed: ManagedPluginPreparation | None,
    runtime: PackageProductRuntimeBindingV1 | None,
    build_config: Callable[[], CodingCapabilityPluginConfig],
    temporary_prefix: str,
    persistent_root: Callable[[], Path],
    legacy_disabled_plugin_ids: frozenset[str],
    clock: Callable[[], int],
    host_boot_id: str,
    tool_modes: Mapping[str, CapabilityMountMode],
    max_manifest_files: int,
    max_manifest_bytes: int,
    admission_failure: ProductAdmissionFailure,
) -> tuple[CodingCapabilityPluginCompositionAssembly, _Cleanup | None]:
    """Prepare a requested generation and retain its selected Product evidence."""
    custody = PreparationRootCustody[CodingCapabilityPluginCompositionPreparation]()
    state_root = custody.prepare_roots(
        state_prefix=None if session_manager.persist else temporary_prefix,
        private_prefix=None,
        persistent_root=persistent_root,
        directory_factory=ExplicitTemporaryDirectory,
    )
    current_selection_check = None
    try:
        configurations = {plugin_id: build_config()}
        if runtime is not None:
            current_selection_check = capture_enabled_plugin_recheck(
                runtime,
                plugin_id,
                max_files=max_manifest_files,
                max_total_bytes=max_manifest_bytes,
                admission_failure=admission_failure,
            )
            custody.preparation = prepare_coding_product_capability_plugin_composition(
                runtime,
                session_id=session_id,
                configurations=configurations,
                state_root=state_root,
                clock=clock,
            )
            if custody.state_root is not None:
                custody.preparation.state_cleanup = custody.state_cleanup
        else:
            assert managed is not None
            custody.preparation = managed.prepare_capabilities(
                create_coding_capability_plugin_composition_request(
                    clock=clock, plugin_ids=frozenset({plugin_id})
                ),
                configurations,
                session_manager=session_manager,
                session_id=session_id,
                state_root=state_root,
                clock=clock,
                legacy_disabled_plugin_ids=legacy_disabled_plugin_ids,
                management_cleanup=managed.deferred_cleanup,
                state_cleanup=custody.state_cleanup,
            )
        assembly = custody.preparation.bind_workspace(
            workspace_binding, host_boot_id=host_boot_id, tool_modes=tool_modes, clock=clock
        )
        return assembly, current_selection_check
    except BaseException:
        custody.cleanup_preparation_sequentially()
        raise


def _session_manager_plugin_owner_id(session_manager: SessionManager) -> str:
    with _SESSION_MANAGER_PLUGIN_OWNER_LOCK:
        owner_id = getattr(
            session_manager,
            _SESSION_MANAGER_PLUGIN_OWNER_ATTRIBUTE,
            None,
        )
        if owner_id is None:
            owner_id = f"session-manager:{secrets.token_hex(16)}"
            setattr(
                session_manager,
                _SESSION_MANAGER_PLUGIN_OWNER_ATTRIBUTE,
                owner_id,
            )
        if not isinstance(owner_id, str) or not owner_id:
            raise RuntimeError("Coding SessionManager Plugin owner id is invalid")
        return owner_id
