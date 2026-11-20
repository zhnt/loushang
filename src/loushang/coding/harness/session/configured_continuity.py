"""Manage configured continuity startup and transfer the recovered publication."""

from __future__ import annotations

from pathlib import Path

from loushang.coding.composition import continuity as _binding
from loushang.harness.continuity.plugin_declaration import (
    CONTINUITY_PROVIDER_CONTRIBUTION_KIND,
)
from loushang.harness.plugin_management import (
    PluginInstallationKeyV1,
    PluginInstallationStateV1,
    PluginPackageRevisionRefV1,
    plugin_enablement_legacy_input_fingerprint,
)
from loushang.harness.resources.packages.materializer import (
    PackageMaterializer,
    plugin_source_identity,
)
from loushang.harness.resources.plugins import (
    InstalledPlugin,
    PluginInspection,
    PluginInstanceRevisionRef,
    PluginResolutionAuthority,
    PluginRuntimeResolution,
    PluginSource,
    PluginSourceBinding,
    PublishedPluginPackage,
    ResolvedPluginPackage,
    is_remote_plugin_source,
)


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

    runtime_resolution: PluginRuntimeResolution | None = None
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
        replayed_runtime, inspections = _continuity_runtime_inputs(
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

        resolution_authority = PluginResolutionAuthority()
        runtime_resolution = _publish_continuity_runtime(
            replayed_runtime,
            inspections=inspections,
            authority=resolution_authority,
            materializer=resolved_materializer,
        )
        instance_refs = _reconcile_enabled_instances(
            runtime_resolution,
            lifecycle,
            layout=layout,
            legacy_disabled_plugin_ids=disabled_plugins,
        )
        if compatibility is not None:
            compatibility.reconcile()
        runtime_resolution = _retain_enabled_runtime(
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


def _continuity_runtime_inputs(
    sources: tuple[str, ...],
    *,
    materializer: PackageMaterializer,
    lifecycle: _binding._InstalledLifecycle,
    layout: _binding.CodingContinuityStateLayout,
) -> tuple[PluginRuntimeResolution, tuple[PluginInspection, ...]]:
    """Resolve seen sources from desired exact revisions; inspect only unseen ones."""

    authority = PluginResolutionAuthority()
    desired_by_source = _desired_installations_by_source(lifecycle, layout=layout)
    replayed_packages: list[PublishedPluginPackage] = []
    replayed_bindings: list[PluginSourceBinding] = []
    replayed_plugins: list[InstalledPlugin] = []
    inspections: list[PluginInspection] = []
    plugin_ids: set[str] = set()
    try:
        for source in sources:
            desired = desired_by_source.get(plugin_source_identity(source))
            if desired is not None and desired.selection.desired_state == "absent":
                # A remove tombstone is authoritative.  Do not inspect or
                # republish the mutable Source merely because the selected
                # Package reference was intentionally cleared.
                continue
            if desired is not None and desired.selection.package_revision is not None:
                plugin_id = desired.installation_key.plugin_id
                if plugin_id in plugin_ids:
                    raise _binding._continuity_lifecycle_error(
                        "plugin_identity_ambiguous",
                        retryable=False,
                    )
                plugin_ids.add(plugin_id)
                selected_revision = desired.selection.package_revision
                assert selected_revision is not None
                replay_binding = materializer.get_plugin_binding_by_revision(
                    selected_revision.package_source_identity,
                    content_digest=selected_revision.package_content_digest,
                    dependency_lock_digest=(selected_revision.dependency_lock_digest),
                )
                if replay_binding is None:
                    raise _binding._continuity_lifecycle_error(
                        "binding_replay_unavailable",
                        retryable=False,
                    )
                package = materializer.reopen_plugin_package(replay_binding)
                actual_revision = PluginPackageRevisionRefV1.from_published_package(
                    package, source_identity=replay_binding.source_identity
                )
                if (
                    actual_revision != selected_revision
                    or not _has_continuity_contribution(package)
                ):
                    package.revision_handle.close()
                    raise _binding._continuity_lifecycle_error(
                        "selected_revision_invalid",
                        retryable=False,
                    )
                replayed_packages.append(package)
                replayed_bindings.append(replay_binding)
                replayed_plugins.append(authority.project_package(package))
                continue

            inspection = _inspect_continuity_source(
                source,
                authority=authority,
                materializer=materializer,
            )
            if inspection is None:
                continue
            inspected_package = inspection.package
            assert inspected_package is not None
            plugin_id = inspected_package.manifest.name
            if plugin_id in plugin_ids:
                raise _binding._continuity_lifecycle_error(
                    "plugin_identity_ambiguous",
                    retryable=False,
                )
            plugin_ids.add(plugin_id)
            inspections.append(inspection)
    except BaseException:
        for package in replayed_packages:
            package.revision_handle.close()
        raise
    return (
        PluginRuntimeResolution(
            packages=tuple(replayed_packages),
            plugins=tuple(replayed_plugins),
            bindings=tuple(replayed_bindings),
        ),
        tuple(inspections),
    )


def _inspect_continuity_source(
    source: str,
    *,
    authority: PluginResolutionAuthority,
    materializer: PackageMaterializer,
) -> PluginInspection | None:
    plugin_source: PluginSource
    if is_remote_plugin_source(source):
        record = materializer.get_record(source)
        if record is None or record.lifecycle != "installed":
            return None
        plugin_source = PluginSource(
            path=record.target_path,
            url=source,
            kind="remote",
        )
    else:
        plugin_source = PluginSource(path=Path(source).expanduser())
    inspection = authority.inspect(plugin_source)
    inspection.raise_for_error()
    package = inspection.package
    if (
        package is None
        or inspection.plugin is None
        or not _has_continuity_contribution(package)
    ):
        return None
    return inspection


def _has_continuity_contribution(
    package: PublishedPluginPackage | ResolvedPluginPackage,
) -> bool:
    return any(
        item.kind == CONTINUITY_PROVIDER_CONTRIBUTION_KIND
        for item in package.contribution_index.items
    )


def _desired_installations_by_source(
    lifecycle: _binding._InstalledLifecycle,
    *,
    layout: _binding.CodingContinuityStateLayout,
) -> dict[str, PluginInstallationStateV1]:
    snapshot = lifecycle.desired.snapshot()
    states = {
        item.installation_key: item
        for item in snapshot.installations
        if item.installation_key.product_id == _binding.CODING_EXPERIENCE_ID
        and item.installation_key.scope_id == layout.scope_id
    }
    source_keys: dict[str, set[PluginInstallationKeyV1]] = {}
    historical_states = [
        state
        for transition in lifecycle.desired.transitions()
        for state in (transition.previous_state, transition.committed_state)
    ]
    for state in (*states.values(), *historical_states):
        key = state.installation_key
        package = state.selection.package_revision
        if (
            key.product_id != _binding.CODING_EXPERIENCE_ID
            or key.scope_id != layout.scope_id
            or package is None
        ):
            continue
        source_keys.setdefault(package.package_source_identity, set()).add(key)
    ambiguous = tuple(
        source_identity
        for source_identity, keys in source_keys.items()
        if len(keys) != 1
    )
    if ambiguous:
        raise _binding._continuity_lifecycle_error(
            "source_identity_ambiguous",
            retryable=False,
        )
    return {
        source_identity: states[next(iter(keys))]
        for source_identity, keys in source_keys.items()
    }


def _publish_continuity_runtime(
    replayed: PluginRuntimeResolution,
    *,
    inspections: tuple[PluginInspection, ...],
    authority: PluginResolutionAuthority,
    materializer: PackageMaterializer,
) -> PluginRuntimeResolution:
    published = PluginRuntimeResolution(packages=(), plugins=(), bindings=())
    try:
        if inspections:
            published = authority.publish_runtime(
                inspections,
                binding_store=materializer,
            )
        packages = (*replayed.packages, *published.packages)
        bindings = {
            item.plugin_id: item for item in (*replayed.bindings, *published.bindings)
        }
        plugins = {
            item.manifest.name: item for item in (*replayed.plugins, *published.plugins)
        }
        if len(packages) != len(bindings) or len(packages) != len(plugins):
            raise _binding._continuity_lifecycle_error(
                "plugin_identity_ambiguous",
                retryable=False,
            )
        ordered = tuple(sorted(packages, key=lambda item: item.manifest.name))
        return PluginRuntimeResolution(
            packages=ordered,
            plugins=tuple(plugins[item.manifest.name] for item in ordered),
            bindings=tuple(bindings[item.manifest.name] for item in ordered),
        )
    except BaseException:
        replayed.close()
        published.close()
        raise


def _reconcile_enabled_instances(
    runtime: PluginRuntimeResolution,
    lifecycle: _binding._InstalledLifecycle,
    *,
    layout: _binding.CodingContinuityStateLayout,
    legacy_disabled_plugin_ids: frozenset[str],
) -> tuple[PluginInstanceRevisionRef, ...]:
    refs: list[PluginInstanceRevisionRef] = []
    bindings = {item.plugin_id: item for item in runtime.bindings}
    for package in sorted(runtime.packages, key=lambda item: item.manifest.name):
        plugin_id = package.manifest.name
        binding = bindings[plugin_id]
        key = PluginInstallationKeyV1(
            product_id=_binding.CODING_EXPERIENCE_ID,
            installation_scope=_binding._CONTINUITY_INSTALLATION_SCOPE,
            scope_id=layout.scope_id,
            plugin_id=plugin_id,
        )
        package_revision = PluginPackageRevisionRefV1.from_published_package(
            package, source_identity=binding.source_identity
        )
        snapshot = lifecycle.desired.snapshot()
        state = snapshot.installation(key)
        unseen = not any(
            item.installation_key == key for item in snapshot.installations
        )
        legacy_disabled = plugin_id in legacy_disabled_plugin_ids
        manifest_default = package.manifest.enabled
        if (
            unseen
            or lifecycle.common.enablement_migrations.journal.snapshot(key) is None
        ):
            lifecycle.common.migrate_legacy_enablement(
                key,
                package_revision,
                legacy_disabled=legacy_disabled,
                manifest_enabled_default=manifest_default,
                legacy_input_fingerprint=(
                    plugin_enablement_legacy_input_fingerprint(
                        key,
                        legacy_disabled=legacy_disabled,
                        manifest_enabled_default=manifest_default,
                    )
                ),
            )
            state = lifecycle.desired.snapshot().installation(key)
        if state.selection.desired_state == "absent":
            continue
        current_package = state.selection.package_revision
        if current_package != package_revision:
            raise _binding._continuity_lifecycle_error(
                "plugin_revision_not_selected",
                retryable=False,
            )
        if state.selection.desired_state != "installed_enabled":
            continue
        ref = state.selection.instance_revision_ref
        if ref is None:
            raise _binding._continuity_lifecycle_error(
                "plugin_not_enabled"
            )
        instance = lifecycle.instances.snapshot().instance(ref)
        if instance is None:
            activation_id = (
                f"{_binding._CONTINUITY_ACTIVATION_ID_PREFIX}:{ref.instance_id}:{ref.revision}"
            )
            instance = lifecycle.instances.activate_current(
                key,
                operation_id=activation_id,
                idempotency_key=activation_id,
                direct_host_reference=_binding._continuity_host_reference(layout.scope_id),
            )
        if instance.state != "ACTIVE" or instance.instance_revision_ref != ref:
            raise _binding._continuity_lifecycle_error(
                "plugin_instance_not_active"
            )
        refs.append(ref)
    return tuple(sorted(refs, key=lambda item: (item.plugin_id, item.instance_id)))


def _retain_enabled_runtime(
    runtime: PluginRuntimeResolution,
    *,
    enabled_plugin_ids: frozenset[str],
) -> PluginRuntimeResolution:
    for package in runtime.packages:
        if package.manifest.name not in enabled_plugin_ids:
            package.revision_handle.close()
    return PluginRuntimeResolution(
        packages=tuple(
            item
            for item in runtime.packages
            if item.manifest.name in enabled_plugin_ids
        ),
        plugins=tuple(
            item for item in runtime.plugins if item.manifest.name in enabled_plugin_ids
        ),
        bindings=tuple(
            item for item in runtime.bindings if item.plugin_id in enabled_plugin_ids
        ),
    )
