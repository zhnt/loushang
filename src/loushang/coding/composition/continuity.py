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
import sys as sys
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from time import time_ns
from typing import Literal, Protocol

from loushang.coding.composition.dependency_grants import (
    coding_plugin_distribution_evidence_resolver as coding_plugin_distribution_evidence_resolver,
)
from loushang.coding.harness.session import configured_continuity
from loushang.coding.plugin_manager.enablement_compatibility import (
    bind_coding_plugin_enablement_compatibility as bind_coding_plugin_enablement_compatibility,
)
from loushang.coding.plugin_manager.lifecycle import (
    CODING_PLUGIN_RUNTIME_BOOT_ID as _CODING_PLUGIN_RUNTIME_BOOT_ID,  # noqa: F401
)
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycle,
    CodingPluginLifecycleStateLayout,
    build_coding_plugin_lifecycle,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.plugin_manager.lifecycle import (
    hold_coding_plugin_startup_lease as _hold_process_startup_lease,  # noqa: F401
)
from loushang.coding.plugin_manager.lifecycle import (
    release_coding_plugin_startup_lease as _release_process_startup_lease,  # noqa: F401
)
from loushang.coding.resources.runtime import CodingPackageMaterializer
from loushang.coding.session.continuity import (
    CODING_EXPERIENCE_ID,
    CodingContinuityComposition,
    CodingContinuityRuntimePort,
    get_coding_continuity_composition,
)
from loushang.coding.session.continuity import (
    bind_coding_continuity as bind_coding_continuity,
)
from loushang.coding.session.continuity import (
    bind_coding_plugin_continuity as bind_coding_plugin_continuity,
)
from loushang.coding.session.continuity import (
    supports_coding_continuity_secure_staging as supports_coding_continuity_secure_staging,
)
from loushang.foundation.platform_paths import PlatformPaths, resolve_platform_paths
from loushang.harness.approval.plugin_activation import (
    OwnerComponentActivationApprovalSubject,
)
from loushang.harness.approval.plugin_execution import PluginApprovalAuthorizationV1
from loushang.harness.capabilities.component_admission import (
    CapabilityComponentOwnerAuthority,
    CapabilityComponentOwnerPolicy,
)
from loushang.harness.continuity.plugin_declaration import (
    CONTINUITY_PROVIDER_COMPONENT_DEFINITION,
    CONTINUITY_PROVIDER_CONTRIBUTION_KIND,
    continuity_provider_component_id,
)
from loushang.harness.continuity.plugin_runtime import (
    resolve_continuity_plugin_selection as resolve_continuity_plugin_selection,
)
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.plugin_management import (
    PluginContinuityDeletionAuthority,
    PluginContinuityDeletionJournal,
    PluginDesiredStateLedger,
    PluginInstanceRuntimeLedger,
    PluginManagementService,
    PluginPackageLifecycleLedger,
)
from loushang.harness.plugin_management.continuity_adapter import (
    PluginContinuitySecurityRetirementJournal,
    PluginInstanceLedgerContinuityFamilyAuthority,
)
from loushang.harness.resources.packages._private_directory import (
    prepare_private_directory,
)
from loushang.harness.resources.packages.materializer import (
    GitPackageMaterializerBackend,
    PackageMaterializer,
)
from loushang.harness.resources.plugins import (
    PluginExecutionApprovalSubject,
    PluginSelection,
    PluginSelectionPlanV2,
    PluginSourceBinding,
    PluginSourceTrustSnapshotV1,
    PublishedPluginPackage,
    is_remote_plugin_source,
)

_PRODUCT_POLICY_REVISION = "coding-continuity-production-1"
_OWNER_POLICY_REVISION = "coding-continuity-owner-1"
_SOURCE_TRUST_POLICY_REVISION = "coding-continuity-source-trust-1"
_AUTHORITY_CEILING = ("continuity.delete", "network.read")
_CONTINUITY_REVOCATION_EPOCH = 0
_APPROVAL_TTL_MS = 300_000
_BOOTSTRAP_STATUS_ATTRIBUTE = "_loushang_coding_continuity_bootstrap_status"
_CONTINUITY_COMPOSITION_ATTRIBUTE = "_loushang_coding_continuity"
_CONTINUITY_INSTALLATION_SCOPE: Literal["workspace"] = "workspace"
_CONTINUITY_ACTIVATION_ID_PREFIX = "continuity-bootstrap-activate"
_CONTINUITY_ALREADY_BOUND = "coding_continuity_composition_already_bound"
_CONTINUITY_STAGING_UNSUPPORTED = "coding_continuity_secure_staging_unsupported"
_REVISION_CLEANUP_NOTE = "Coding Continuity revision cleanup failed: "
_LAST_READY_STATUS_ATTRIBUTE = "_loushang_coding_continuity_bootstrap_last_ready_status"
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


def _continuity_lifecycle_error(
    reason: str, *, retryable: bool = True
) -> CodingContinuityBootstrapError:
    return CodingContinuityBootstrapError(
        code=f"coding_continuity_{reason}", retryable=retryable
    )


def _continuity_host_reference(scope_id: str) -> str:
    return f"coding-continuity-host:{scope_id}"


@dataclass(slots=True)
class _InstalledLifecycle:
    common: CodingPluginLifecycle
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
    if composition is None or composition.configured_request_fingerprint is None:
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

    from loushang.coding.package.product_runtime import (
        CodingFencedProductApplicationSelection,
    )

    product_route = isinstance(
        getattr(runtime, "_product_owner_selection", None),
        CodingFencedProductApplicationSelection,
    )
    try:
        sources, disabled_plugins = _configured_sources(settings_manager, cwd=cwd)
        if product_route and (sources or disabled_plugins):
            raise CodingContinuityBootstrapError(
                code="coding_product_legacy_plugin_configuration_unsupported",
                retryable=False,
            )
    except BaseException as error:
        if not isinstance(error, Exception):
            raise
        stable_code = _record_bootstrap_failure(
            runtime, diagnostics_service, error, configured_source_count=0
        )
        if isinstance(error, CodingContinuityBootstrapError):
            raise
        raise CodingContinuityBootstrapError(code=stable_code) from None

    return await configured_continuity.bind_configured_continuity(
        runtime,
        settings_manager=settings_manager,
        cwd=cwd,
        all_sessions=all_sessions,
        diagnostics_service=diagnostics_service,
        materializer=materializer,
        state_layout=state_layout,
        clock=clock,
        runtime_id=runtime_id,
        product_route=product_route,
        sources=sources,
        disabled_plugins=disabled_plugins,
    )


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


def _require_continuity_package_authority(
    layout: CodingContinuityStateLayout, materializer: PackageMaterializer
) -> None:
    if not materializer.uses_storage_authority(
        install_root=layout.package_root / "installed",
        lockfile_path=layout.package_root / "package-lock.json",
        plugin_revision_root=layout.package_root / "plugin-revisions",
    ):
        raise CodingContinuityBootstrapError(
            code="coding_continuity_package_authority_mismatch",
            retryable=False,
        )


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
) -> _InstalledLifecycle:
    security = PluginContinuitySecurityRetirementJournal.for_instance_runtime(
        layout.instance_runtime
    )
    common = build_coding_plugin_lifecycle(
        _common_lifecycle_layout(layout),
        security_acceptances=security,
    )
    desired = common.desired
    management = common.management
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
        common=common,
        desired=desired,
        management=management,
        instances=instances,
        packages=packages,
        family_authority=family_authority,
        deletion_authority=PluginContinuityDeletionAuthority(deletion_journal),
    )


def _common_lifecycle_layout(
    layout: CodingContinuityStateLayout,
) -> CodingPluginLifecycleStateLayout:
    return CodingPluginLifecycleStateLayout(
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
    )


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
            revocation_epoch=_CONTINUITY_REVOCATION_EPOCH,
            allowed_component_ids=component_ids,
            allowed_source_trust_classes=trust_classes,
            authority_ceiling=_AUTHORITY_CEILING,
        ),
    )


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


def _configured_source_trust(
    package: PublishedPluginPackage, binding: PluginSourceBinding
) -> PluginSourceTrustSnapshotV1:
    return PluginSourceTrustSnapshotV1(
        plugin_id=package.manifest.name,
        package_source_identity=binding.source_identity,
        source_trust_class=(
            "materialized-remote"
            if binding.source_identity.startswith("remote:")
            else "configured-local"
        ),
        source_trust_policy_revision=_SOURCE_TRUST_POLICY_REVISION,
        trusted=True,
    )


def _prepare_private_directory(root: Path, *, code: str) -> None:
    try:
        prepare_private_directory(root)
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
        setattr(runtime, _LAST_READY_STATUS_ATTRIBUTE, status)
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


def _restore_ready_status(
    runtime: object,
    diagnostics: DiagnosticsService | None,
) -> None:
    status = getattr(runtime, _LAST_READY_STATUS_ATTRIBUTE, None)
    if not isinstance(status, CodingContinuityBootstrapStatus):
        current = getattr(runtime, _BOOTSTRAP_STATUS_ATTRIBUTE, None)
        status = (
            current
            if isinstance(current, CodingContinuityBootstrapStatus)
            and current.state == "ready"
            else None
        )
    if status is None:
        return
    _record_ready_status(
        runtime,
        diagnostics,
        configured_source_count=status.configured_source_count,
        plugin_count=status.plugin_count,
        provider_count=status.provider_count,
        recovered_deletion_count=status.recovered_deletion_count,
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


def _record_bootstrap_failure(
    runtime: CodingContinuityRuntimePort,
    diagnostics_service: DiagnosticsService | None,
    error: Exception,
    *,
    configured_source_count: int,
) -> str:
    code = _stable_error_code(error)
    _record_failed_status(
        runtime,
        diagnostics_service,
        code=code,
        configured_source_count=configured_source_count,
        retryable=error.retryable if isinstance(error, CodingContinuityBootstrapError) else True,
    )
    return code


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
