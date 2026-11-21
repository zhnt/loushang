"""Prepare managed package state and transfer its cleanup to Session consumers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from loushang.coding.composition import bootstrap as _binding

if TYPE_CHECKING:
    from loushang.coding.composition.capability_plugins import (
        CodingCapabilityPluginCompositionRequest,
    )
    from loushang.coding.composition.capability_specs import (
        CodingCapabilityPluginConfig,
    )
    from loushang.harness.capabilities.provider_binding import (
        CapabilityBundleProviderBinding,
    )
    from loushang.harness.config.agent import CapabilityMountMode

    from .catalog_preparation import _AdmissionFailure

_Cleanup = Callable[[], None]
_PreparePrimary = Callable[
    ["_binding.CodingPluginLifecycle", "_binding.PackageMaterializer", _Cleanup | None],
    "_binding.CodingBasePluginAssembly | None",
]


@dataclass(frozen=True, slots=True)
class ManagedPluginPreparation:
    lifecycle: _binding.CodingPluginLifecycle
    materializer: _binding.PackageMaterializer
    primary: _binding.CodingBasePluginAssembly | None
    eager_cleanup: _Cleanup | None
    deferred_cleanup: _Cleanup | None

    def prepare_capabilities(
        self,
        request: CodingCapabilityPluginCompositionRequest,
        configurations: Mapping[str, CodingCapabilityPluginConfig],
        *,
        session_manager: _binding.SessionManager,
        session_id: str,
        state_root: Path,
        clock: Callable[[], int],
        legacy_disabled_plugin_ids: frozenset[str],
        management_cleanup: _Cleanup | None,
        state_cleanup: _Cleanup | None,
        private_state_cleanup: _Cleanup | None = None,
        base: _binding.CodingBasePluginAssembly | None = None,
        plan_seed: _binding.ProductPluginPlanSeed | None = None,
    ) -> _binding.CodingCapabilityPluginCompositionPreparation:
        return _binding.prepare_coding_capability_plugin_composition(
            request,
            session_id=session_id,
            configurations=configurations,
            package_materializer=self.materializer,
            lifecycle=self.lifecycle,
            legacy_disabled_plugin_ids=legacy_disabled_plugin_ids,
            session_owner_id=_binding._session_manager_plugin_owner_id(session_manager),
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
    session_manager: _binding.SessionManager,
    services: _binding.BootstrapServices,
    session_id: str,
    package_materializer: _binding.PackageMaterializer | None,
    resolved_package_materializer: _binding.PackageMaterializer | None,
    ephemeral_prefix: str | None,
    prepare_primary: _PreparePrimary | None,
    needs_eager: bool,
    needs_deferred: bool,
) -> ManagedPluginPreparation:
    ephemeral_state = (
        _binding._ExplicitTemporaryDirectory(prefix=ephemeral_prefix)
        if ephemeral_prefix is not None
        else None
    )
    lifecycle = None
    materializer = None
    recorded_diagnostics: list[dict[str, object]] = []
    primary_cleanup = eager_cleanup = deferred_cleanup = None
    try:
        layout = (
            _binding.resolve_coding_plugin_lifecycle_state_layout(
                session_manager.get_cwd()
            )
            if ephemeral_state is None
            else _binding.resolve_ephemeral_coding_plugin_lifecycle_state_layout(
                ephemeral_state.name, cwd=session_manager.get_cwd()
            )
        )
        if (
            ephemeral_state is None
            and package_materializer is not None
            and not package_materializer.uses_storage_authority(
                install_root=layout.package_install_root,
                lockfile_path=layout.package_lockfile,
                plugin_revision_root=layout.plugin_revision_root,
            )
        ):
            message, code = _binding._MANAGED_PACKAGE_AUTHORITY_MISMATCH
            raise _binding.CodingBasePluginAssemblyError(message, code=code)
        lifecycle = _binding.build_coding_plugin_lifecycle(layout)
        materializer = package_materializer or _binding.PackageMaterializer(
            install_root=layout.package_install_root,
            lockfile_path=layout.package_lockfile,
            plugin_revision_root=layout.plugin_revision_root,
            backend=_binding.GitPackageMaterializerBackend(),
        )
        if materializer is not resolved_package_materializer:
            recorded_diagnostics = materializer.get_lockfile_diagnostics()
            _binding.record_package_lockfile_diagnostics(
                recorded_diagnostics,
                diagnostics_service=services.diagnostics_service,
                session_id=session_id,
            )
        if ephemeral_state is not None:
            primary_cleanup, eager_cleanup, deferred_cleanup = _cleanup_claims(
                lifecycle,
                ephemeral_state,
                prepare_primary is not None,
                needs_eager,
                needs_deferred,
            )
        lifecycle.complete_startup_recovery()
        primary = (
            prepare_primary(lifecycle, materializer, primary_cleanup)
            if prepare_primary is not None
            else None
        )
    except BaseException as error:
        if isinstance(error, _binding.CodingBasePluginAssemblyError):
            services.diagnostics_service.capture_failure(
                code=error.code,
                error=str(error),
                phase="startup",
                source="bootstrap",
                session_id=session_id,
                details={"check": _binding._MANAGED_PACKAGE_REPLAY_CHECK, "ok": False},
            )
        # Exact replay can discover additional lock corruption during preparation.
        if materializer is not None:
            _binding.record_package_lockfile_diagnostics(
                [
                    diagnostic
                    for diagnostic in materializer.get_lockfile_diagnostics()
                    if diagnostic not in recorded_diagnostics
                ],
                diagnostics_service=services.diagnostics_service,
                session_id=session_id,
            )
        for cleanup in (primary_cleanup, eager_cleanup, deferred_cleanup):
            if cleanup is not None:
                cleanup()
        if lifecycle is not None:
            lifecycle.release_owned_process_startup_lease()
        if (
            eager_cleanup is None
            and primary_cleanup is None
            and ephemeral_state is not None
        ):
            ephemeral_state.cleanup()
        raise
    return ManagedPluginPreparation(
        lifecycle, materializer, primary, eager_cleanup, deferred_cleanup
    )


def _cleanup_claims(
    lifecycle: _binding.CodingPluginLifecycle,
    ephemeral_state: _binding._ExplicitTemporaryDirectory,
    primary: bool,
    eager: bool,
    deferred: bool,
) -> tuple[_Cleanup | None, _Cleanup | None, _Cleanup | None]:
    remaining = sum((primary, eager, deferred))
    cleanup_done = False

    def create_claim() -> _Cleanup:
        released = False

        def release() -> None:
            nonlocal remaining, cleanup_done, released
            if not released:
                remaining -= 1
                released = True
            if remaining == 0 and not cleanup_done:
                lifecycle.release_owned_process_startup_lease()
                ephemeral_state.cleanup()
                cleanup_done = True

        return release

    return (
        create_claim() if primary else None,
        create_claim() if eager else None,
        create_claim() if deferred else None,
    )


def bind_deferred_plugin(
    workspace_binding: CapabilityBundleProviderBinding,
    *,
    session_manager: _binding.SessionManager,
    session_id: str,
    plugin_id: str,
    managed: ManagedPluginPreparation | None,
    runtime: _binding.PackageProductRuntimeBindingV1 | None,
    build_config: Callable[[], CodingCapabilityPluginConfig],
    temporary_prefix: str,
    persistent_root: Callable[[], Path],
    legacy_disabled_plugin_ids: frozenset[str],
    clock: Callable[[], int],
    host_boot_id: str,
    tool_modes: Mapping[str, CapabilityMountMode],
    max_manifest_files: int,
    max_manifest_bytes: int,
    admission_failure: _AdmissionFailure,
) -> tuple[_binding.CodingCapabilityPluginCompositionAssembly, _Cleanup | None]:
    """Prepare a requested generation and retain its selected Product evidence."""
    temporary_state = (
        _binding._ExplicitTemporaryDirectory(prefix=temporary_prefix)
        if not session_manager.persist
        else None
    )
    state_root = (
        Path(temporary_state.name) if temporary_state is not None else persistent_root()
    )
    preparation = None
    current_selection_check = None
    try:
        configurations = {plugin_id: build_config()}
        if runtime is not None:
            selection = runtime.capture_plugin_desired_selection_for(plugin_id)
            if selection.desired_state != "installed_enabled":
                raise admission_failure(("product_requested_capability_not_installed",))
            selected_manifest = runtime.capture_selected_plugin_manifest_for(
                plugin_id,
                max_files=max_manifest_files,
                max_total_bytes=max_manifest_bytes,
            )

            def require_current() -> None:
                runtime.assert_plugin_desired_selection_current(selection)
                runtime.assert_selected_plugin_manifest_current(selected_manifest)

            current_selection_check = require_current
            preparation = _binding.prepare_coding_product_capability_plugin_composition(
                runtime,
                session_id=session_id,
                configurations=configurations,
                state_root=state_root,
                clock=clock,
            )
            if temporary_state is not None:
                preparation.state_cleanup = temporary_state.cleanup
        else:
            assert managed is not None
            preparation = managed.prepare_capabilities(
                _binding.create_coding_capability_plugin_composition_request(
                    clock=clock, plugin_ids=frozenset({plugin_id})
                ),
                configurations,
                session_manager=session_manager,
                session_id=session_id,
                state_root=state_root,
                clock=clock,
                legacy_disabled_plugin_ids=legacy_disabled_plugin_ids,
                management_cleanup=managed.deferred_cleanup,
                state_cleanup=temporary_state.cleanup if temporary_state is not None else None,
            )
        assembly = preparation.bind_workspace(
            workspace_binding, host_boot_id=host_boot_id, tool_modes=tool_modes, clock=clock
        )
        return assembly, current_selection_check
    except BaseException:
        if preparation is not None:
            preparation.close()
        if temporary_state is not None:
            temporary_state.cleanup()
        raise
