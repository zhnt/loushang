"""Reopen exact installed Continuity revisions and bind their existing owners."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from loushang.harness.continuity.plugin_declaration import (
    CONTINUITY_PROVIDER_CONTRIBUTION_KIND,
)
from loushang.harness.plugin_management.assembly import (
    _ManagedPluginLease,
    _ManagedPluginLifecycle,
)
from loushang.harness.plugin_management.enablement_migration import (
    plugin_enablement_legacy_input_fingerprint,
)
from loushang.harness.plugin_management.instance_runtime import (
    PluginInstanceRuntimeLedger,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1,
    PluginInstallationStateV1,
    PluginPackageRevisionRefV1,
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


class _ContinuitySelectionFailure(Protocol):
    def __call__(self, reason: str, *, retryable: bool = True) -> Exception: ...


class _InstalledContinuityLifecycle(_ManagedPluginLifecycle[_ManagedPluginLease], Protocol):
    @property
    def instances(self) -> PluginInstanceRuntimeLedger: ...
    def complete_startup_recovery(self) -> None: ...


@contextmanager
def hold_installed_continuity_runtime(
    sources: tuple[str, ...],
    lifecycle: _InstalledContinuityLifecycle,
    *,
    materializer: PackageMaterializer,
    product_id: str,
    scope_id: str,
    activation_id_prefix: str,
    direct_host_reference: str,
    legacy_disabled_plugin_ids: frozenset[str],
    reconcile_compatibility: Callable[[], None] | None,
    supports_secure_staging: Callable[[], bool],
    lifecycle_error: _ContinuitySelectionFailure,
    cleanup_note: str,
) -> Iterator[tuple[PluginRuntimeResolution, tuple[PluginInstanceRevisionRef, ...]]]:
    """Hold selected revisions through publication and transfer on success."""
    lifecycle.reconcile_retirements()
    authority = PluginResolutionAuthority()
    replayed, inspections = resolve_installed_continuity_sources(
        sources,
        authority=authority,
        materializer=materializer,
        desired_state=lifecycle.desired,
        product_id=product_id,
        scope_id=scope_id,
        lifecycle_error=lifecycle_error,
    )
    try:
        if reconcile_compatibility is not None:
            reconcile_compatibility()
        if not replayed.packages and not inspections:
            lifecycle.complete_startup_recovery()
            yield replayed, ()
            return
        staging_supported = supports_secure_staging()
    except BaseException as error:
        _close_runtime_after_failure(replayed, error, cleanup_note)
        raise
    if not staging_supported:
        replayed.close()
        raise lifecycle_error("secure_staging_unsupported", retryable=False)

    runtime = publish_continuity_runtime(
        replayed,
        inspections=inspections,
        authority=authority,
        materializer=materializer,
        lifecycle_error=lifecycle_error,
    )
    try:
        refs = reconcile_enabled_continuity_instances(
            runtime,
            lifecycle,
            activation_id_prefix=activation_id_prefix,
            direct_host_reference=direct_host_reference,
            lifecycle_error=lifecycle_error,
            legacy_disabled_plugin_ids=legacy_disabled_plugin_ids,
        )
        if reconcile_compatibility is not None:
            reconcile_compatibility()
        runtime = retain_enabled_continuity_runtime(
            runtime, enabled_plugin_ids=frozenset(item.plugin_id for item in refs)
        )
        lifecycle.complete_startup_recovery()
        yield runtime, refs
    except BaseException as error:
        _close_runtime_after_failure(runtime, error, cleanup_note)
        raise


def _close_runtime_after_failure(
    runtime: PluginRuntimeResolution, error: BaseException, cleanup_note: str
) -> None:
    try:
        runtime.close()
    except BaseException as cleanup_error:
        error.add_note(cleanup_note + type(cleanup_error).__name__)


def resolve_installed_continuity_sources(
    sources: tuple[str, ...],
    *,
    authority: PluginResolutionAuthority,
    materializer: PackageMaterializer,
    desired_state: PluginDesiredStateLedger,
    product_id: str,
    scope_id: str,
    lifecycle_error: _ContinuitySelectionFailure,
) -> tuple[PluginRuntimeResolution, tuple[PluginInspection, ...]]:
    """Resolve seen sources from desired exact revisions; inspect only unseen ones."""

    desired_by_source = _desired_installations_by_source(
        desired_state, product_id=product_id, scope_id=scope_id,
        lifecycle_error=lifecycle_error,
    )
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
                    raise lifecycle_error(
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
                    raise lifecycle_error(
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
                    raise lifecycle_error(
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
                raise lifecycle_error(
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
    desired_state: PluginDesiredStateLedger,
    *,
    product_id: str,
    scope_id: str,
    lifecycle_error: _ContinuitySelectionFailure,
) -> dict[str, PluginInstallationStateV1]:
    snapshot = desired_state.snapshot()
    states = {
        item.installation_key: item
        for item in snapshot.installations
        if item.installation_key.product_id == product_id
        and item.installation_key.scope_id == scope_id
    }
    source_keys: dict[str, set[PluginInstallationKeyV1]] = {}
    historical_states = [
        state
        for transition in desired_state.transitions()
        for state in (transition.previous_state, transition.committed_state)
    ]
    for state in (*states.values(), *historical_states):
        key = state.installation_key
        package = state.selection.package_revision
        if (
            key.product_id != product_id
            or key.scope_id != scope_id
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
        raise lifecycle_error(
            "source_identity_ambiguous",
            retryable=False,
        )
    return {
        source_identity: states[next(iter(keys))]
        for source_identity, keys in source_keys.items()
    }


def publish_continuity_runtime(
    replayed: PluginRuntimeResolution,
    *,
    inspections: tuple[PluginInspection, ...],
    authority: PluginResolutionAuthority,
    materializer: PackageMaterializer,
    lifecycle_error: _ContinuitySelectionFailure,
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
            raise lifecycle_error(
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


def reconcile_enabled_continuity_instances(
    runtime: PluginRuntimeResolution,
    lifecycle: _InstalledContinuityLifecycle,
    *,
    activation_id_prefix: str,
    direct_host_reference: str,
    lifecycle_error: _ContinuitySelectionFailure,
    legacy_disabled_plugin_ids: frozenset[str],
) -> tuple[PluginInstanceRevisionRef, ...]:
    desired_state = lifecycle.desired
    instances = lifecycle.instances
    refs: list[PluginInstanceRevisionRef] = []
    bindings = {item.plugin_id: item for item in runtime.bindings}
    for package in sorted(runtime.packages, key=lambda item: item.manifest.name):
        plugin_id = package.manifest.name
        binding = bindings[plugin_id]
        key = lifecycle.installation_key(plugin_id)
        package_revision = PluginPackageRevisionRefV1.from_published_package(
            package, source_identity=binding.source_identity
        )
        snapshot = desired_state.snapshot()
        state = snapshot.installation(key)
        unseen = not any(
            item.installation_key == key for item in snapshot.installations
        )
        legacy_disabled = plugin_id in legacy_disabled_plugin_ids
        manifest_default = package.manifest.enabled
        if (
            unseen
            or lifecycle.enablement_migrations.journal.snapshot(key) is None
        ):
            lifecycle.migrate_legacy_enablement(
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
            state = desired_state.snapshot().installation(key)
        if state.selection.desired_state == "absent":
            continue
        current_package = state.selection.package_revision
        if current_package != package_revision:
            raise lifecycle_error(
                "plugin_revision_not_selected",
                retryable=False,
            )
        if state.selection.desired_state != "installed_enabled":
            continue
        ref = state.selection.instance_revision_ref
        if ref is None:
            raise lifecycle_error(
                "plugin_not_enabled"
            )
        instance = instances.snapshot().instance(ref)
        if instance is None:
            activation_id = (
                f"{activation_id_prefix}:{ref.instance_id}:{ref.revision}"
            )
            instance = instances.activate_current(
                key,
                operation_id=activation_id,
                idempotency_key=activation_id,
                direct_host_reference=direct_host_reference,
            )
        if instance.state != "ACTIVE" or instance.instance_revision_ref != ref:
            raise lifecycle_error(
                "plugin_instance_not_active"
            )
        refs.append(ref)
    return tuple(sorted(refs, key=lambda item: (item.plugin_id, item.instance_id)))


def retain_enabled_continuity_runtime(
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
