"""Manage configured continuity startup and transfer the recovered publication."""

from __future__ import annotations

from loushang.coding.composition import continuity as _binding


async def bind_configured_continuity(
    runtime: _binding.CodingContinuityRuntimePort,
    *,
    settings_manager: _binding.CodingContinuitySettingsPort | object | None,
    cwd: str | _binding.Path,
    all_sessions: bool,
    diagnostics_service: _binding.DiagnosticsService | None,
    materializer: _binding.PackageMaterializer | None,
    state_layout: _binding.CodingContinuityStateLayout | None,
    clock: _binding.Callable[[], int],
    runtime_id: str | None,
    product_route: bool,
    sources: tuple[str, ...],
    disabled_plugins: frozenset[str],
) -> _binding.CodingContinuityComposition:
    configured_count = len(sources)
    common_layout: _binding.CodingPluginLifecycleStateLayout | None = None
    existing: _binding.CodingContinuityComposition | None = None
    compatibility = None
    owns_early_startup_lease = False

    def release_early_startup_lease() -> None:
        nonlocal owns_early_startup_lease
        if owns_early_startup_lease and common_layout is not None:
            _binding._release_process_startup_lease(
                common_layout, startup_id=_binding._CODING_PLUGIN_RUNTIME_BOOT_ID
            )
            owns_early_startup_lease = False

    def record_base_ready() -> None:
        _binding._record_ready_status(
            runtime,
            diagnostics_service,
            configured_source_count=configured_count,
            plugin_count=0,
            provider_count=0,
            recovered_deletion_count=0,
        )

    def finish_base_binding() -> _binding.CodingContinuityComposition:
        result = _binding.bind_coding_continuity(
            runtime, cwd=cwd, all_sessions=all_sessions
        )
        result.configured_request_fingerprint = request_fingerprint
        record_base_ready()
        if compatibility is None:
            release_early_startup_lease()
        return result

    try:
        layout = state_layout or _binding.resolve_coding_continuity_state_layout(cwd)
        common_layout = _binding._common_lifecycle_layout(layout)
        prior = getattr(runtime, _binding._CONTINUITY_COMPOSITION_ATTRIBUTE, None)
        existing = (
            prior if isinstance(prior, _binding.CodingContinuityComposition) else None
        )
        if (
            not product_route
            and (_binding.sys.platform.startswith("linux") or _binding.os.name == "nt")
            and (
                sources
                or settings_manager is not None
                or (existing is not None and existing.plugin_publication is not None)
            )
        ):
            owns_early_startup_lease = _binding._hold_process_startup_lease(
                common_layout, startup_id=_binding._CODING_PLUGIN_RUNTIME_BOOT_ID
            )
        compatibility = (
            None
            if product_route
            else _binding.bind_coding_plugin_enablement_compatibility(
                common_layout,
                settings_manager,
            )
        )
        if compatibility is not None:
            compatibility.reconcile()
            sources, disabled_plugins = _binding._configured_sources(
                settings_manager,
                cwd=cwd,
            )
            configured_count = len(sources)
        request_fingerprint = _binding._bootstrap_request_fingerprint(
            sources,
            disabled_plugins=disabled_plugins,
            cwd=cwd,
            all_sessions=all_sessions,
        )

        if existing is not None:
            if existing.configured_request_fingerprint == request_fingerprint:
                _binding._restore_ready_status(runtime, diagnostics_service)
                if existing.plugin_publication is None and compatibility is None:
                    release_early_startup_lease()
                return existing
            if (
                not sources
                and existing.plugin_publication is None
                and existing.configured_request_fingerprint is None
                and existing.binding_cwd
                == str(_binding.Path(cwd).expanduser().resolve(strict=False))
                and existing.all_sessions == all_sessions
            ):
                existing.configured_request_fingerprint = request_fingerprint
                record_base_ready()
                if compatibility is None:
                    release_early_startup_lease()
                return existing
            raise _binding.CodingContinuityBootstrapError(
                code=_binding._CONTINUITY_ALREADY_BOUND,
                retryable=False,
            )

        if not sources:
            return finish_base_binding()
    except BaseException as error:
        if compatibility is None and (
            existing is None or existing.plugin_publication is None
        ):
            release_early_startup_lease()
        if not isinstance(error, Exception):
            raise
        if (
            isinstance(error, _binding.CodingContinuityBootstrapError)
            and error.code == _binding._CONTINUITY_ALREADY_BOUND
        ):
            # The already-published composition remains healthy.  Reject the
            # conflicting rebind without overwriting its ready status.
            raise
        stable_code = _binding._record_bootstrap_failure(
            runtime,
            diagnostics_service,
            error,
            configured_source_count=configured_count,
        )
        if isinstance(error, _binding.CodingContinuityBootstrapError):
            raise
        raise _binding.CodingContinuityBootstrapError(code=stable_code) from None

    runtime_resolution: _binding.PluginRuntimeResolution | None = None
    lifecycle_started = False
    try:
        resolved_runtime_id = runtime_id or _binding._new_runtime_id()
        if materializer is not None:
            _binding._require_continuity_package_authority(layout, materializer)
        resolved_materializer = (
            materializer or _binding._coding_continuity_materializer(layout)
        )
        _binding._prepare_private_state_layout(layout)
        _binding._prepare_private_runtime_roots(layout)
        lifecycle = _binding._build_lifecycle(layout)
        lifecycle_started = True
        lifecycle.common.reconcile_retirements()
        replayed_runtime, inspections = _binding._continuity_runtime_inputs(
            sources,
            materializer=resolved_materializer,
            lifecycle=lifecycle,
            layout=layout,
        )
        if compatibility is not None:
            compatibility.reconcile()
        if not replayed_runtime.packages and not inspections:
            lifecycle.common.complete_startup_recovery()
            return finish_base_binding()

        if not _binding.supports_coding_continuity_secure_staging():
            replayed_runtime.close()
            raise _binding.CodingContinuityBootstrapError(
                code=_binding._CONTINUITY_STAGING_UNSUPPORTED,
                retryable=False,
            )

        resolution_authority = _binding.PluginResolutionAuthority()
        runtime_resolution = _binding._publish_continuity_runtime(
            replayed_runtime,
            inspections=inspections,
            authority=resolution_authority,
            materializer=resolved_materializer,
        )
        instance_refs = _binding._reconcile_enabled_instances(
            runtime_resolution,
            lifecycle,
            layout=layout,
            legacy_disabled_plugin_ids=disabled_plugins,
        )
        if compatibility is not None:
            compatibility.reconcile()
        runtime_resolution = _binding._retain_enabled_runtime(
            runtime_resolution,
            enabled_plugin_ids=frozenset(item.plugin_id for item in instance_refs),
        )
        lifecycle.common.complete_startup_recovery()
        if not runtime_resolution.packages:
            return finish_base_binding()
        selection = _binding._finalize_selection(
            runtime_resolution,
            instance_refs=instance_refs,
            layout=layout,
            clock=clock,
        )
        owner_authority = _binding._owner_authority(selection)
        now = _binding._read_clock(clock)
        resolved = _binding.resolve_continuity_plugin_selection(
            selection,
            owner_authority=owner_authority,
            issued_at=now,
            expires_at=now + _binding._APPROVAL_TTL_MS,
            now=now,
        )
        component_host, decisions = _binding._component_host_and_decisions(
            resolved,
            owner_authority=owner_authority,
            layout=layout,
            clock=clock,
        )
        pending_before = len(lifecycle.deletion_authority.journal.pending())
        result = await _binding.bind_coding_plugin_continuity(
            runtime,
            resolved_plugins=resolved,
            component_host=component_host,
            activation_decision_ids=decisions,
            instance_family_authority=lifecycle.family_authority,
            runtime_id=resolved_runtime_id,
            deletion_authority=lifecycle.deletion_authority,
            owned_cleanup=runtime_resolution.close,
            cwd=cwd,
            all_sessions=all_sessions,
            temporary_root=layout.temporary_root,
            fallback_cwd=cwd,
        )
        result.configured_request_fingerprint = request_fingerprint
        runtime_resolution = None  # ownership transferred to the composition
        _binding._record_ready_status(
            runtime,
            diagnostics_service,
            configured_source_count=configured_count,
            plugin_count=len(selection.plan.selected_plugin_ids),
            provider_count=len(resolved.candidates),
            recovered_deletion_count=pending_before,
        )
        return result
    except BaseException as error:
        if not lifecycle_started and compatibility is None:
            release_early_startup_lease()
        if runtime_resolution is not None:
            try:
                runtime_resolution.close()
            except BaseException as cleanup_error:
                error.add_note(
                    _binding._REVISION_CLEANUP_NOTE + type(cleanup_error).__name__
                )
        if not isinstance(error, Exception):
            raise
        stable_code = _binding._record_bootstrap_failure(
            runtime,
            diagnostics_service,
            error,
            configured_source_count=configured_count,
        )
        if isinstance(error, _binding.CodingContinuityBootstrapError):
            raise
        raise _binding.CodingContinuityBootstrapError(code=stable_code) from None
