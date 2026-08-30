"""Product-owned production composition for configured Continuity Plugins.

The module is deliberately a Coding composition root.  Harness owns the
selection, approval, Instance, generation, recovery, and Hub mechanisms; this
adapter supplies Product policy, durable paths, configuration, and lifecycle
ordering.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from time import time_ns
from typing import Literal, Protocol

from loushang.coding._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    build_coding_plugin_lifecycle,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.continuity import (
    CODING_EXPERIENCE_ID,
    CodingContinuityComposition,
    CodingContinuityRuntimePort,
    bind_coding_continuity,
    bind_coding_plugin_continuity,
    get_coding_continuity_composition,
    supports_coding_continuity_secure_staging,
)
from loushang.coding.plugin_dependency_grants import (
    coding_plugin_distribution_evidence_resolver,
)
from loushang.coding.resource_runtime import CodingPackageMaterializer
from loushang.foundation.platform_paths import PlatformPaths, resolve_platform_paths
from loushang.harness.approval.plugin_activation import (
    OwnerComponentActivationApprovalSubject,
    PluginActivationDecisionJournal,
)
from loushang.harness.approval.plugin_execution import (
    PluginApprovalAuthorizationV1,
    PluginExecutionDecisionJournal,
)
from loushang.harness.capabilities.component_admission import (
    CapabilityComponentOwnerAuthority,
    CapabilityComponentOwnerPolicy,
)
from loushang.harness.capabilities.owner_component_host import (
    CapabilityOwnerComponentHost,
)
from loushang.harness.continuity.plugin_declaration import (
    CONTINUITY_PROVIDER_COMPONENT_DEFINITION,
    CONTINUITY_PROVIDER_CONTRIBUTION_KIND,
    continuity_provider_component_id,
    validate_continuity_provider_component_payload,
)
from loushang.harness.continuity.plugin_runtime import (
    ResolvedContinuityPluginSelection,
    resolve_continuity_plugin_selection,
)
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.plugin_authoring.evaluator import PluginDefinitionEvaluator
from loushang.harness.plugin_authoring.host import PluginDeclarationHost
from loushang.harness.plugin_management import (
    PluginContinuityDeletionAuthority,
    PluginContinuityDeletionJournal,
    PluginDesiredStateLedger,
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginInstanceRuntimeLedger,
    PluginManagementCommandV1,
    PluginManagementService,
    PluginPackageLifecycleLedger,
    PluginPackageRevisionRefV1,
)
from loushang.harness.plugin_management.continuity_adapter import (
    PluginInstanceLedgerContinuityFamilyAuthority,
)
from loushang.harness.resources.packages.materializer import (
    GitPackageMaterializerBackend,
    PackageMaterializer,
)
from loushang.harness.resources.plugins import (
    PluginContributionRef,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginExecutionApprovalSubject,
    PluginInspection,
    PluginInstanceRevisionRef,
    PluginPreflightContextV1,
    PluginPreflightDeniedOutcome,
    PluginPreflightPendingApprovalOutcome,
    PluginResolutionAuthority,
    PluginRuntimeResolution,
    PluginSelection,
    PluginSelectionPlanV2,
    PluginSource,
    PluginSourceBinding,
    PluginSourceTrustSnapshotV1,
    PublishedPluginPackage,
    is_remote_plugin_source,
)
from loushang.harness.resources.plugins.import_realm import PluginImportRealm

_PRODUCT_POLICY_REVISION = "coding-continuity-production-1"
_OWNER_POLICY_REVISION = "coding-continuity-owner-1"
_SOURCE_TRUST_POLICY_REVISION = "coding-continuity-source-trust-1"
_AUTHORITY_CEILING = ("continuity.delete", "network.read")
_APPROVAL_TTL_MS = 300_000
_BOOTSTRAP_STATUS_ATTRIBUTE = "_loushang_coding_continuity_bootstrap_status"
_STABLE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")


class CodingContinuitySettingsPort(Protocol):
    @property
    def global_base_dir(self) -> Path | None: ...

    @property
    def project_base_dir(self) -> Path | None: ...

    def get_settings(self) -> object: ...


class CodingContinuityBootstrapError(RuntimeError):
    """Stable, redacted failure before a configured Hub is published."""

    def __init__(self, *, code: str, retryable: bool = True) -> None:
        super().__init__(f"Coding Continuity bootstrap failed ({code}).")
        self.code = code
        self.retryable = retryable


CodingContinuityBootstrapState = Literal["idle", "ready", "failed"]


@dataclass(frozen=True, slots=True)
class CodingContinuityBootstrapStatus:
    """Finite operational projection; it intentionally contains no source path."""

    state: CodingContinuityBootstrapState = "idle"
    code: str = "coding_continuity_not_started"
    configured_source_count: int = 0
    plugin_count: int = 0
    provider_count: int = 0
    recovered_deletion_count: int = 0
    retryable: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "code": self.code,
            "configuredSourceCount": self.configured_source_count,
            "pluginCount": self.plugin_count,
            "providerCount": self.provider_count,
            "recoveredDeletionCount": self.recovered_deletion_count,
            "retryable": self.retryable,
        }


@dataclass(frozen=True, slots=True)
class CodingContinuityStateLayout:
    """Canonical durable Product paths for one workspace continuity scope."""

    root: Path
    private_state_base: Path
    package_root: Path
    private_data_base: Path
    scope_id: str
    runtime_root: Path
    temporary_base: Path
    temporary_root: Path
    desired_state: Path
    management_operations: Path
    retirement_intents: Path
    retirement_sets: Path
    instance_runtime: Path
    package_lifecycle: Path
    definition_decisions: Path
    activation_decisions: Path


@dataclass(slots=True)
class _InstalledLifecycle:
    desired: PluginDesiredStateLedger
    management: PluginManagementService
    instances: PluginInstanceRuntimeLedger
    packages: PluginPackageLifecycleLedger
    family_authority: PluginInstanceLedgerContinuityFamilyAuthority
    deletion_authority: PluginContinuityDeletionAuthority


def resolve_coding_continuity_state_layout(
    cwd: str | Path,
    *,
    platform_paths: PlatformPaths | None = None,
) -> CodingContinuityStateLayout:
    """Resolve a redacted workspace namespace under canonical machine state."""

    paths = platform_paths or resolve_platform_paths()
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(
        cwd,
        platform_paths=paths,
    )
    digest = lifecycle.scope_id.removeprefix("workspace:")
    state_root = lifecycle.root
    return CodingContinuityStateLayout(
        root=state_root,
        private_state_base=lifecycle.private_state_base,
        package_root=lifecycle.package_root,
        private_data_base=lifecycle.private_data_base,
        scope_id=lifecycle.scope_id,
        runtime_root=paths.runtime,
        temporary_base=paths.temporary,
        temporary_root=paths.temporary / "continuity-import" / digest,
        desired_state=lifecycle.desired_state,
        management_operations=lifecycle.management_operations,
        retirement_intents=lifecycle.retirement_intents,
        retirement_sets=lifecycle.retirement_sets,
        instance_runtime=lifecycle.instance_runtime,
        package_lifecycle=lifecycle.package_lifecycle,
        definition_decisions=state_root / "definition-decisions.jsonl",
        activation_decisions=state_root / "activation-decisions.jsonl",
    )


def get_coding_continuity_bootstrap_status(
    runtime: object,
) -> CodingContinuityBootstrapStatus:
    status = getattr(runtime, _BOOTSTRAP_STATUS_ATTRIBUTE, None)
    return (
        status
        if isinstance(status, CodingContinuityBootstrapStatus)
        else (CodingContinuityBootstrapStatus())
    )


def get_coding_configured_continuity_composition(
    runtime: object,
) -> CodingContinuityComposition | None:
    """Return only a composition sealed by the configured Product bootstrap."""

    composition = get_coding_continuity_composition(runtime)
    if (
        composition is None
        or composition.configured_request_fingerprint is None
    ):
        return None
    return composition


async def bind_coding_configured_continuity(
    runtime: CodingContinuityRuntimePort,
    *,
    settings_manager: CodingContinuitySettingsPort | object | None,
    session_dir: str | Path,
    cwd: str | Path,
    all_sessions: bool = False,
    diagnostics_service: DiagnosticsService | None = None,
    materializer: PackageMaterializer | None = None,
    state_layout: CodingContinuityStateLayout | None = None,
    clock: Callable[[], int] = lambda: time_ns() // 1_000_000,
    runtime_id: str | None = None,
) -> CodingContinuityComposition:
    """Bind base continuity plus all enabled configured Continuity Plugins.

    A configured source that has no Continuity contribution remains outside this
    owner.  A configured Continuity source is fail-closed: it must complete the
    full installed selection and recovery chain or no replacement Hub is
    published.  Calling this function again after a clean failure is the manual
    retry operation.
    """

    try:
        sources, disabled_plugins = _configured_sources(settings_manager, cwd=cwd)
    except BaseException as error:
        if not isinstance(error, Exception):
            raise
        stable_code = _stable_error_code(error)
        retryable = (
            error.retryable
            if isinstance(error, CodingContinuityBootstrapError)
            else True
        )
        _record_failed_status(
            runtime,
            diagnostics_service,
            code=stable_code,
            configured_source_count=0,
            retryable=retryable,
        )
        if isinstance(error, CodingContinuityBootstrapError):
            raise
        raise CodingContinuityBootstrapError(code=stable_code) from None

    request_fingerprint = _bootstrap_request_fingerprint(
        sources,
        disabled_plugins=disabled_plugins,
        cwd=cwd,
        all_sessions=all_sessions,
    )

    existing = getattr(runtime, "_loushang_coding_continuity", None)
    if isinstance(existing, CodingContinuityComposition):
        if existing.configured_request_fingerprint == request_fingerprint:
            return existing
        if (
            not sources
            and existing.plugin_publication is None
            and existing.configured_request_fingerprint is None
            and existing.binding_cwd
            == str(Path(cwd).expanduser().resolve(strict=False))
            and existing.all_sessions == all_sessions
        ):
            existing.configured_request_fingerprint = request_fingerprint
            _record_ready_status(
                runtime,
                diagnostics_service,
                configured_source_count=0,
                plugin_count=0,
                provider_count=0,
                recovered_deletion_count=0,
            )
            return existing
        composition_error = CodingContinuityBootstrapError(
            code="coding_continuity_composition_already_bound",
            retryable=False,
        )
        raise composition_error

    if not sources:
        result = bind_coding_continuity(
            runtime,
            cwd=cwd,
            all_sessions=all_sessions,
        )
        result.configured_request_fingerprint = request_fingerprint
        _record_ready_status(
            runtime,
            diagnostics_service,
            configured_source_count=0,
            plugin_count=0,
            provider_count=0,
            recovered_deletion_count=0,
        )
        return result

    runtime_resolution: PluginRuntimeResolution | None = None
    configured_count = len(sources)
    try:
        layout = state_layout or resolve_coding_continuity_state_layout(cwd)
        resolved_runtime_id = runtime_id or _new_runtime_id()
        if materializer is not None and not materializer.uses_storage_authority(
            install_root=layout.package_root / "installed",
            lockfile_path=layout.package_root / "package-lock.json",
            plugin_revision_root=layout.package_root / "plugin-revisions",
        ):
            raise CodingContinuityBootstrapError(
                code="coding_continuity_package_authority_mismatch",
                retryable=False,
            )
        resolved_materializer = materializer or _coding_continuity_materializer(
            layout
        )
        _prepare_private_state_layout(layout)
        _prepare_private_runtime_roots(layout)
        inspections = _continuity_inspections(
            sources,
            disabled_plugins=disabled_plugins,
            materializer=resolved_materializer,
        )
        if not inspections:
            result = bind_coding_continuity(
                runtime,
                cwd=cwd,
                all_sessions=all_sessions,
            )
            result.configured_request_fingerprint = request_fingerprint
            _record_ready_status(
                runtime,
                diagnostics_service,
                configured_source_count=configured_count,
                plugin_count=0,
                provider_count=0,
                recovered_deletion_count=0,
            )
            return result

        if not supports_coding_continuity_secure_staging():
            raise CodingContinuityBootstrapError(
                code="coding_continuity_secure_staging_unsupported",
                retryable=False,
            )

        resolution_authority = PluginResolutionAuthority(
            disabled_plugins=tuple(disabled_plugins)
        )
        runtime_resolution = resolution_authority.publish_runtime(
            inspections,
            binding_store=resolved_materializer,
        )
        lifecycle = _build_lifecycle(layout, runtime_id=resolved_runtime_id)
        instance_refs = _reconcile_enabled_instances(
            runtime_resolution,
            lifecycle,
            layout=layout,
        )
        lifecycle.packages.complete_startup_recovery(
            operation_id=f"continuity-bootstrap-recovery:{resolved_runtime_id}",
            idempotency_key=f"continuity-bootstrap-recovery:{resolved_runtime_id}",
            recovery_reference=f"continuity-bootstrap:{resolved_runtime_id}",
        )
        selection = _finalize_selection(
            runtime_resolution,
            instance_refs=instance_refs,
            layout=layout,
            clock=clock,
        )
        owner_authority = _owner_authority(selection)
        now = _read_clock(clock)
        resolved = resolve_continuity_plugin_selection(
            selection,
            owner_authority=owner_authority,
            issued_at=now,
            expires_at=now + _APPROVAL_TTL_MS,
            now=now,
        )
        component_host, decisions = _component_host_and_decisions(
            resolved,
            owner_authority=owner_authority,
            layout=layout,
            clock=clock,
        )
        pending_before = len(lifecycle.deletion_authority.journal.pending())
        result = await bind_coding_plugin_continuity(
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
        _record_ready_status(
            runtime,
            diagnostics_service,
            configured_source_count=configured_count,
            plugin_count=len(selection.plan.selected_plugin_ids),
            provider_count=len(resolved.candidates),
            recovered_deletion_count=pending_before,
        )
        return result
    except BaseException as error:
        if runtime_resolution is not None:
            try:
                runtime_resolution.close()
            except BaseException as cleanup_error:
                error.add_note(
                    "Coding Continuity revision cleanup failed: "
                    f"{type(cleanup_error).__name__}"
                )
        if not isinstance(error, Exception):
            raise
        stable_code = _stable_error_code(error)
        retryable = (
            error.retryable
            if isinstance(error, CodingContinuityBootstrapError)
            else True
        )
        _record_failed_status(
            runtime,
            diagnostics_service,
            code=stable_code,
            configured_source_count=configured_count,
            retryable=retryable,
        )
        if isinstance(error, CodingContinuityBootstrapError):
            raise
        raise CodingContinuityBootstrapError(code=stable_code) from None


async def retry_coding_continuity_bootstrap(
    runtime: CodingContinuityRuntimePort,
    **kwargs: object,
) -> CodingContinuityComposition:
    """Explicit retry surface after a fail-closed pre-publication failure."""

    return await bind_coding_configured_continuity(runtime, **kwargs)  # type: ignore[arg-type]


def _configured_sources(
    settings_manager: object | None,
    *,
    cwd: str | Path,
) -> tuple[tuple[str, ...], frozenset[str]]:
    get_settings = getattr(settings_manager, "get_settings", None)
    if not callable(get_settings):
        return (), frozenset()
    settings = get_settings()
    raw_sources = getattr(settings, "plugin_sources", ())
    raw_disabled = getattr(settings, "disabled_plugins", ())
    if not isinstance(raw_sources, tuple | list) or any(
        not isinstance(item, str) or not item.strip() for item in raw_sources
    ):
        raise CodingContinuityBootstrapError(
            code="coding_continuity_plugin_sources_invalid",
            retryable=False,
        )
    if not isinstance(raw_disabled, tuple | list) or any(
        not isinstance(item, str) or not item.strip() for item in raw_disabled
    ):
        raise CodingContinuityBootstrapError(
            code="coding_continuity_disabled_plugins_invalid",
            retryable=False,
        )
    sources = tuple(
        dict.fromkeys(
            _normalize_configured_source(
                item.strip(),
                settings_manager=settings_manager,
                cwd=cwd,
            )
            for item in raw_sources
        )
    )
    return sources, frozenset(item.strip() for item in raw_disabled)


def _bootstrap_request_fingerprint(
    sources: tuple[str, ...],
    *,
    disabled_plugins: frozenset[str],
    cwd: str | Path,
    all_sessions: bool,
) -> str:
    workspace = Path(cwd).expanduser().resolve(strict=False)
    digest = hashlib.sha256()
    digest.update(b"loushang.coding-continuity-bootstrap-request/v2\0")

    def update_value(label: str, value: str) -> None:
        label_bytes = label.encode("ascii")
        encoded = value.encode("utf-8", errors="surrogatepass")
        digest.update(len(label_bytes).to_bytes(4, "big"))
        digest.update(label_bytes)
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)

    update_value("policyRevision", _PRODUCT_POLICY_REVISION)
    update_value("workspace", str(workspace))
    update_value("listingScope", "all" if all_sessions else "workspace")
    update_value("sourceCount", str(len(sources)))
    for source in sources:
        update_value("source", source)
    ordered_disabled = tuple(sorted(disabled_plugins))
    update_value("disabledPluginCount", str(len(ordered_disabled)))
    for plugin_id in ordered_disabled:
        update_value("disabledPlugin", plugin_id)
    return digest.hexdigest()


def _normalize_configured_source(
    source: str,
    *,
    settings_manager: object,
    cwd: str | Path,
) -> str:
    if is_remote_plugin_source(source):
        return source
    path = Path(source).expanduser()
    if path.is_absolute():
        return str(path.resolve())
    base = _configured_source_base(source, settings_manager=settings_manager)
    return str(((base or Path(cwd)) / path).expanduser().resolve())


def _configured_source_base(
    source: str,
    *,
    settings_manager: object,
) -> Path | None:
    # Layer precedence is session > project > global.  A session-relative
    # source intentionally falls back to the requested Coding cwd.
    for getter_name, base_name in (
        ("get_session_settings", None),
        ("get_project_settings", "project_base_dir"),
        ("get_global_settings", "global_base_dir"),
    ):
        getter = getattr(settings_manager, getter_name, None)
        if not callable(getter):
            continue
        patch = getter()
        if not isinstance(patch, Mapping):
            continue
        values = patch.get("plugin_sources")
        if not isinstance(values, list | tuple) or source not in values:
            continue
        if base_name is None:
            return None
        base = getattr(settings_manager, base_name, None)
        return None if base is None else Path(base).expanduser().resolve()
    return None


def _continuity_inspections(
    sources: tuple[str, ...],
    *,
    disabled_plugins: frozenset[str],
    materializer: PackageMaterializer,
) -> tuple[PluginInspection, ...]:
    authority = PluginResolutionAuthority(disabled_plugins=tuple(disabled_plugins))
    selected: list[PluginInspection] = []
    plugin_ids: set[str] = set()
    for source in sources:
        plugin_source: PluginSource
        if is_remote_plugin_source(source):
            record = materializer.get_record(source)
            if record is None or record.lifecycle != "installed":
                continue
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
        if package is None:
            continue
        plugin_id = package.manifest.name
        if plugin_id in disabled_plugins:
            continue
        has_continuity = any(
            item.kind == CONTINUITY_PROVIDER_CONTRIBUTION_KIND
            for item in package.contribution_index.items
        )
        if not has_continuity:
            continue
        if plugin_id in plugin_ids:
            raise CodingContinuityBootstrapError(
                code="coding_continuity_plugin_identity_ambiguous",
                retryable=False,
            )
        plugin_ids.add(plugin_id)
        selected.append(inspection)
    return tuple(selected)


def _coding_continuity_materializer(
    layout: CodingContinuityStateLayout,
) -> CodingPackageMaterializer:
    return CodingPackageMaterializer(
        install_root=layout.package_root / "installed",
        lockfile_path=layout.package_root / "package-lock.json",
        plugin_revision_root=layout.package_root / "plugin-revisions",
        backend=GitPackageMaterializerBackend(),
    )


def _build_lifecycle(
    layout: CodingContinuityStateLayout,
    *,
    runtime_id: str,
) -> _InstalledLifecycle:
    common = build_coding_plugin_lifecycle(
        CodingPluginLifecycleStateLayout(
            root=layout.root,
            private_state_base=layout.private_state_base,
            package_root=layout.package_root,
            private_data_base=layout.private_data_base,
            scope_id=layout.scope_id,
            desired_state=layout.desired_state,
            management_operations=layout.management_operations,
            retirement_intents=layout.retirement_intents,
            retirement_sets=layout.retirement_sets,
            instance_runtime=layout.instance_runtime,
            package_lifecycle=layout.package_lifecycle,
        ),
        startup_id=runtime_id,
    )
    desired = common.desired
    management = common.management
    security = common.security
    instances = common.instances
    packages = common.packages
    family_authority = PluginInstanceLedgerContinuityFamilyAuthority(
        ledger=instances,
        package_lifecycle=packages,
        security_acceptance_journal=security,
    )
    deletion_journal = PluginContinuityDeletionJournal.for_instance_runtime(
        layout.instance_runtime
    )
    return _InstalledLifecycle(
        desired=desired,
        management=management,
        instances=instances,
        packages=packages,
        family_authority=family_authority,
        deletion_authority=PluginContinuityDeletionAuthority(deletion_journal),
    )


def _reconcile_enabled_instances(
    runtime: PluginRuntimeResolution,
    lifecycle: _InstalledLifecycle,
    *,
    layout: CodingContinuityStateLayout,
) -> tuple[PluginInstanceRevisionRef, ...]:
    refs: list[PluginInstanceRevisionRef] = []
    bindings = {item.plugin_id: item for item in runtime.bindings}
    for package in sorted(runtime.packages, key=lambda item: item.manifest.name):
        plugin_id = package.manifest.name
        binding = bindings[plugin_id]
        key = PluginInstallationKeyV1(
            product_id=CODING_EXPERIENCE_ID,
            installation_scope="workspace",
            scope_id=layout.scope_id,
            plugin_id=plugin_id,
        )
        package_revision = PluginPackageRevisionRefV1(
            plugin_id=plugin_id,
            plugin_version=package.manifest.version,
            package_content_digest=package.content_digest,
            dependency_lock_digest=package.dependency_lock.digest,
            package_source_identity=binding.source_identity,
        )
        snapshot = lifecycle.desired.snapshot()
        state = snapshot.installation(key)
        unseen = not any(
            item.installation_key == key for item in snapshot.installations
        )
        if unseen:
            _submit_management(
                lifecycle.management,
                lifecycle.desired,
                key,
                action="install",
                package_revision=package_revision,
            )
            state = lifecycle.desired.snapshot().installation(key)
            _submit_management(
                lifecycle.management,
                lifecycle.desired,
                key,
                action="enable",
                package_revision=None,
            )
            state = lifecycle.desired.snapshot().installation(key)
        current_package = state.selection.package_revision
        if current_package != package_revision:
            raise CodingContinuityBootstrapError(
                code="coding_continuity_plugin_revision_not_selected",
                retryable=False,
            )
        ref = state.selection.instance_revision_ref
        if state.selection.desired_state != "installed_enabled" or ref is None:
            raise CodingContinuityBootstrapError(
                code="coding_continuity_plugin_not_enabled"
            )
        instance = lifecycle.instances.snapshot().instance(ref)
        if instance is None:
            instance = lifecycle.instances.activate_current(
                key,
                operation_id=f"continuity-bootstrap-activate:{ref.instance_id}:{ref.revision}",
                idempotency_key=(
                    f"continuity-bootstrap-activate:{ref.instance_id}:{ref.revision}"
                ),
                direct_host_reference=f"coding-continuity-host:{layout.scope_id}",
            )
        if instance.state != "ACTIVE" or instance.instance_revision_ref != ref:
            raise CodingContinuityBootstrapError(
                code="coding_continuity_plugin_instance_not_active"
            )
        refs.append(ref)
    return tuple(sorted(refs, key=lambda item: (item.plugin_id, item.instance_id)))


def _submit_management(
    service: PluginManagementService,
    desired: PluginDesiredStateLedger,
    key: PluginInstallationKeyV1,
    *,
    action: Literal["install", "enable"],
    package_revision: PluginPackageRevisionRefV1 | None,
) -> None:
    revision = desired.snapshot().inventory_revision
    identity = hashlib.sha256(
        repr((key, action, package_revision)).encode("utf-8")
    ).hexdigest()
    event = service.submit(
        PluginManagementCommandV1(
            action=action,
            mutation=PluginDesiredStateMutationV1(
                operation_id=f"coding-continuity:{identity}",
                idempotency_key=f"coding-continuity:{identity}",
                expected_inventory_revision=revision,
                installation_key=key,
                desired_state=(
                    "installed_disabled" if action == "install" else "installed_enabled"
                ),
                package_revision=package_revision,
                actor_id="product:coding",
                policy_revision=_PRODUCT_POLICY_REVISION,
                approval_reference="coding-configured-plugin-source",
            ),
        )
    )
    result = getattr(event, "result", None)
    if result is None or result.disposition != "succeeded":
        raise CodingContinuityBootstrapError(
            code=getattr(result, "error_code", "coding_continuity_management_failed")
        )


def _finalize_selection(
    runtime: PluginRuntimeResolution,
    *,
    instance_refs: tuple[PluginInstanceRevisionRef, ...],
    layout: CodingContinuityStateLayout,
    clock: Callable[[], int],
) -> PluginSelection:
    bindings = {item.plugin_id: item for item in runtime.bindings}
    packages = tuple(sorted(runtime.packages, key=lambda item: item.manifest.name))
    contributions = tuple(
        sorted(
            (
                (package, item)
                for package in packages
                for item in package.contribution_index.items
                if item.kind == CONTINUITY_PROVIDER_CONTRIBUTION_KIND
            ),
            key=lambda pair: (pair[0].manifest.name, pair[1].contribution_id),
        )
    )
    plan = PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id=CODING_EXPERIENCE_ID,
            scope_id=layout.scope_id,
            policy_revision=_PRODUCT_POLICY_REVISION,
            instance_revision_refs=instance_refs,
        ),
        selected_plugin_ids=tuple(package.manifest.name for package in packages),
        selected_contributions=tuple(
            PluginContributionRef(package.manifest.name, item.contribution_id)
            for package, item in contributions
        ),
        source_trust_snapshots=tuple(
            PluginSourceTrustSnapshotV1(
                plugin_id=package.manifest.name,
                package_source_identity=bindings[package.manifest.name].source_identity,
                source_trust_class=_source_trust_class(package, bindings),
                source_trust_policy_revision=_SOURCE_TRUST_POLICY_REVISION,
                trusted=True,
            )
            for package in packages
        ),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=tuple(
                PluginEffectiveConfigurationEntry(
                    plugin_id=package.manifest.name,
                    contribution_id=item.contribution_id,
                    configuration=item.configuration,
                )
                for package, item in contributions
            )
        ),
        allowed_authority_ceiling=_AUTHORITY_CEILING,
    )
    journal = PluginExecutionDecisionJournal(
        layout.definition_decisions,
        scope_kind="workspace",
        scope_id=layout.scope_id,
        clock=clock,
    )
    host = PluginDeclarationHost(
        execution_evaluator=PluginDefinitionEvaluator(
            decision_journal=journal,
            import_realm=PluginImportRealm(),
            clock=clock,
            distribution_evidence_resolver=(
                coding_plugin_distribution_evidence_resolver()
            ),
        )
    )
    outcome = host.resolve(
        packages,
        bindings=tuple(bindings[item.manifest.name] for item in packages),
        plan=plan,
        decision_lookup=journal,
    )
    if isinstance(outcome, PluginPreflightPendingApprovalOutcome):
        for subject in outcome.subjects:
            _validate_definition_subject(subject, plan)
            now = _read_clock(clock)
            journal.issue_execution_decision(
                subject,
                disposition="approved",
                authorization=_approval_authorization(),
                revocation_epoch=0,
                issued_at_unix_ms=now,
                expires_at_unix_ms=now + _APPROVAL_TTL_MS,
                expected_journal_revision=journal.snapshot().journal_revision,
            )
        outcome = host.resolve(
            packages,
            bindings=tuple(bindings[item.manifest.name] for item in packages),
            plan=plan,
            decision_lookup=journal,
        )
    if not isinstance(outcome, PluginSelection):
        code = (
            "coding_continuity_definition_denied"
            if isinstance(outcome, PluginPreflightDeniedOutcome)
            else f"coding_continuity_definition_{outcome.disposition}"
        )
        raise CodingContinuityBootstrapError(code=code, retryable=False)
    return outcome


def _owner_authority(
    selection: PluginSelection,
) -> CapabilityComponentOwnerAuthority:
    component_ids = tuple(
        sorted(
            continuity_provider_component_id(
                candidate.package.manifest.name,
                candidate.declaration.contribution_id,
            )
            for candidate in selection.candidates
            if candidate.declaration.kind == CONTINUITY_PROVIDER_CONTRIBUTION_KIND
        )
    )
    trust_classes = tuple(
        sorted(
            {item.source_trust_class for item in selection.plan.source_trust_snapshots}
        )
    )
    return CapabilityComponentOwnerAuthority(
        CONTINUITY_PROVIDER_COMPONENT_DEFINITION,
        CapabilityComponentOwnerPolicy(
            capability_id=CONTINUITY_PROVIDER_COMPONENT_DEFINITION.capability_id,
            owner_id=CONTINUITY_PROVIDER_COMPONENT_DEFINITION.owner_id,
            component_kind=CONTINUITY_PROVIDER_COMPONENT_DEFINITION.component_kind,
            policy_revision=_OWNER_POLICY_REVISION,
            revocation_epoch=0,
            allowed_component_ids=component_ids,
            allowed_source_trust_classes=trust_classes,
            authority_ceiling=_AUTHORITY_CEILING,
        ),
    )


def _component_host_and_decisions(
    resolved: ResolvedContinuityPluginSelection,
    *,
    owner_authority: CapabilityComponentOwnerAuthority,
    layout: CodingContinuityStateLayout,
    clock: Callable[[], int],
) -> tuple[CapabilityOwnerComponentHost, dict[str, str]]:
    selection = resolved.plugin_selection
    trust_by_key = {
        (item.plugin_id, item.package_source_identity): item
        for item in selection.plan.source_trust_snapshots
    }

    def read_owner(capability_id: str, component_kind: str):
        definition = CONTINUITY_PROVIDER_COMPONENT_DEFINITION
        if (
            capability_id != definition.capability_id
            or component_kind != definition.component_kind
        ):
            raise ValueError("Continuity owner reader received another Definition")
        return owner_authority.snapshot()

    def read_trust(plugin_id: str, source_identity: str):
        return trust_by_key[(plugin_id, source_identity)]

    def read_policy(product_id: str, scope_id: str) -> str:
        if product_id != CODING_EXPERIENCE_ID or scope_id != layout.scope_id:
            raise ValueError("Continuity policy reader received another Product scope")
        return _PRODUCT_POLICY_REVISION

    journal = PluginActivationDecisionJournal(
        layout.activation_decisions,
        scope_id=layout.scope_id,
        clock=clock,
    )
    host = CapabilityOwnerComponentHost(
        decision_journal=journal,
        import_realm=PluginImportRealm(),
        host_boot_id=secrets.token_hex(16),
        clock=clock,
        owner_snapshot_reader=read_owner,
        trust_snapshot_reader=read_trust,
        product_policy_revision_reader=read_policy,
        payload_validator_reader=(
            lambda definition: (
                validate_continuity_provider_component_payload
                if definition == CONTINUITY_PROVIDER_COMPONENT_DEFINITION
                else _reject_payload_validator(definition)
            )
        ),
    )
    decision_ids: dict[str, str] = {}
    trust_by_plugin = {
        item.plugin_id: item for item in selection.plan.source_trust_snapshots
    }
    for component in resolved.resolved_set.components:
        plugin_id = component.admission.candidate.binding_spec.plugin_id
        if plugin_id is None:
            raise TypeError("Continuity component has no Plugin identity")
        trust = trust_by_plugin[plugin_id]
        subject = host.activation_subject(
            component,
            owner_snapshot=resolved.owner_snapshot,
            trust_snapshot=trust,
        )
        _validate_activation_subject(subject, layout=layout)
        now = _read_clock(clock)
        snapshot = journal.snapshot()
        decision = next(
            (
                item
                for item in snapshot.decisions
                if item.subject_digest == subject.digest
                and item.disposition == "approved"
                and item.consumption_state == "AVAILABLE"
                and now < item.expires_at_unix_ms
            ),
            None,
        )
        if decision is None:
            decision = journal.issue_activation_decision(
                subject,
                disposition="approved",
                authorization=_approval_authorization(),
                issued_at_unix_ms=now,
                expires_at_unix_ms=now + _APPROVAL_TTL_MS,
                expected_journal_revision=snapshot.journal_revision,
            )
        decision_ids[component.component_id] = decision.decision_id
    return host, decision_ids


def _validate_definition_subject(
    subject: PluginExecutionApprovalSubject,
    plan: PluginSelectionPlanV2,
) -> None:
    trust = {item.plugin_id: item for item in plan.source_trust_snapshots}
    expected = trust.get(subject.plugin_id)
    if (
        expected is None
        or subject.product_id != CODING_EXPERIENCE_ID
        or subject.scope_id != plan.context.scope_id
        or subject.policy_revision != _PRODUCT_POLICY_REVISION
        or subject.package_source_identity != expected.package_source_identity
        or subject.source_trust_class != expected.source_trust_class
        or subject.source_trust_policy_revision != _SOURCE_TRUST_POLICY_REVISION
        or not set(subject.requested_authorities).issubset(_AUTHORITY_CEILING)
        or subject.allowed_authority_ceiling != _AUTHORITY_CEILING
    ):
        raise CodingContinuityBootstrapError(
            code="coding_continuity_definition_subject_rejected",
            retryable=False,
        )


def _validate_activation_subject(
    subject: OwnerComponentActivationApprovalSubject,
    *,
    layout: CodingContinuityStateLayout,
) -> None:
    definition = CONTINUITY_PROVIDER_COMPONENT_DEFINITION
    if (
        subject.capability_id != definition.capability_id
        or subject.owner_id != definition.owner_id
        or subject.component_kind != definition.component_kind
        or subject.product_id != CODING_EXPERIENCE_ID
        or subject.scope_id != layout.scope_id
        or subject.product_policy_revision != _PRODUCT_POLICY_REVISION
        or subject.owner_policy_revision != _OWNER_POLICY_REVISION
        or subject.source_trust_policy_revision != _SOURCE_TRUST_POLICY_REVISION
        or not set(subject.effective_authorities).issubset(_AUTHORITY_CEILING)
        or subject.execution_model != "in_process"
    ):
        raise CodingContinuityBootstrapError(
            code="coding_continuity_activation_subject_rejected",
            retryable=False,
        )


def _source_trust_class(
    package: PublishedPluginPackage,
    bindings: Mapping[str, PluginSourceBinding],
) -> str:
    binding = bindings[package.manifest.name]
    return (
        "materialized-remote"
        if binding.source_identity.startswith("remote:")
        else "configured-local"
    )


def _prepare_private_directory(root: Path, *, code: str) -> None:
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        before = root.lstat()
        if (
            not stat.S_ISDIR(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or bool(getattr(before, "st_reparse_tag", 0))
        ):
            raise OSError("private root is not a direct directory")
        getuid = getattr(os, "getuid", None)
        if os.name == "posix" and callable(getuid) and before.st_uid != getuid():
            raise PermissionError("private root belongs to another user")
        if os.name == "posix":
            root.chmod(0o700)
        after = root.lstat()
        if not os.path.samestat(before, after):
            raise OSError("private root identity changed")
    except OSError:
        raise CodingContinuityBootstrapError(code=code) from None


def _prepare_private_state_root(root: Path) -> None:
    _prepare_private_directory(
        root,
        code="coding_continuity_state_permissions_failed",
    )


def _prepare_private_state_layout(layout: CodingContinuityStateLayout) -> None:
    # Keep the lexical path so every existing component is checked with lstat;
    # resolve() would follow an attacker-replaced intermediate symlink first.
    base = layout.private_state_base.expanduser().absolute()
    root = layout.root.expanduser().absolute()
    try:
        relative = root.relative_to(base)
    except ValueError:
        raise CodingContinuityBootstrapError(
            code="coding_continuity_state_permissions_failed",
            retryable=False,
        ) from None
    _prepare_private_state_root(base)
    current = base
    for part in relative.parts:
        current /= part
        _prepare_private_state_root(current)


def _prepare_private_runtime_roots(layout: CodingContinuityStateLayout) -> None:
    for root in (
        layout.runtime_root,
        layout.temporary_base,
        layout.temporary_root.parent,
        layout.temporary_root,
    ):
        _prepare_private_directory(
            root,
            code="coding_continuity_temporary_permissions_failed",
        )


def _record_ready_status(
    runtime: object,
    diagnostics: DiagnosticsService | None,
    *,
    configured_source_count: int,
    plugin_count: int,
    provider_count: int,
    recovered_deletion_count: int,
) -> None:
    status = CodingContinuityBootstrapStatus(
        state="ready",
        code="coding_continuity_ready",
        configured_source_count=configured_source_count,
        plugin_count=plugin_count,
        provider_count=provider_count,
        recovered_deletion_count=recovered_deletion_count,
    )
    with suppress(AttributeError, TypeError):
        setattr(runtime, _BOOTSTRAP_STATUS_ATTRIBUTE, status)
    capture = getattr(diagnostics, "capture_failure", None)
    if callable(capture):
        with suppress(Exception):
            capture(
                code=status.code,
                error="Coding Continuity composition is ready.",
                phase="startup",
                source="bootstrap",
                level="info",
                details=status.to_dict(),
            )


def _record_failed_status(
    runtime: object,
    diagnostics: DiagnosticsService | None,
    *,
    code: str,
    configured_source_count: int,
    retryable: bool,
) -> None:
    status = CodingContinuityBootstrapStatus(
        state="failed",
        code=code,
        configured_source_count=configured_source_count,
        retryable=retryable,
    )
    with suppress(AttributeError, TypeError):
        setattr(runtime, _BOOTSTRAP_STATUS_ATTRIBUTE, status)
    capture = getattr(diagnostics, "capture_failure", None)
    if callable(capture):
        with suppress(Exception):
            capture(
                code=code,
                error=f"Coding Continuity bootstrap failed ({code}).",
                phase="startup",
                source="bootstrap",
                details=status.to_dict(),
            )


def _stable_error_code(error: BaseException) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and _STABLE_ERROR_CODE.fullmatch(code):
        return code
    return "coding_continuity_bootstrap_failed"


def _approval_authorization() -> PluginApprovalAuthorizationV1:
    return PluginApprovalAuthorizationV1.direct(
        actor_id="product:coding",
        source="coding-configured-continuity-policy",
    )


def _reject_payload_validator(_definition: object):
    raise ValueError("Continuity Host received another component Definition")


def _read_clock(clock: Callable[[], int]) -> int:
    value = clock()
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TypeError("Coding Continuity clock must return a non-negative integer")
    return value


def _new_runtime_id() -> str:
    return f"coding-process:{os.getpid()}:{secrets.token_hex(12)}"


__all__ = [
    "CodingContinuityBootstrapError",
    "CodingContinuityBootstrapStatus",
    "CodingContinuityStateLayout",
    "bind_coding_configured_continuity",
    "get_coding_configured_continuity_composition",
    "get_coding_continuity_bootstrap_status",
    "resolve_coding_continuity_state_layout",
    "retry_coding_continuity_bootstrap",
]
