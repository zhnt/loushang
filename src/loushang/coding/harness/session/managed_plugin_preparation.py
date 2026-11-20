"""Prepare managed package state and transfer its cleanup to Session consumers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from loushang.coding.composition import bootstrap as _binding

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
