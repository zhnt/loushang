"""Product-owned production composition for configured Continuity Plugins.

The module is deliberately a Coding composition root.  Harness owns the
selection, approval, Instance, generation, recovery, and Hub mechanisms; this
adapter supplies Product policy, durable paths, and configuration preflight.
"""

from __future__ import annotations

import os
import re
import secrets
import sys as sys
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from time import time_ns
from typing import Literal, NoReturn, Protocol

from loushang.coding.composition.dependency_grants import (
    coding_plugin_distribution_evidence_resolver as coding_plugin_distribution_evidence_resolver,
)
from loushang.coding.plugin_manager.enablement_compatibility import (
    bind_coding_plugin_enablement_compatibility as bind_coding_plugin_enablement_compatibility,
)
from loushang.coding.plugin_manager.lifecycle import (
    CODING_PLUGIN_RUNTIME_BOOT_ID as _CODING_PLUGIN_RUNTIME_BOOT_ID,
)
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycleStateLayout,
    build_coding_plugin_lifecycle,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.plugin_manager.lifecycle import (
    hold_coding_plugin_startup_lease as _hold_process_startup_lease,
)
from loushang.coding.plugin_manager.lifecycle import (
    release_coding_plugin_startup_lease as _release_process_startup_lease,
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
from loushang.harness.approval.plugin_execution import (
    PluginApprovalAuthorizationV1,
    PluginApprovalDecisionRecordV1,
    PluginExecutionDecisionJournal,
)
from loushang.harness.continuity._binding_lifetime import (
    _ContinuityBootstrapStatus,
    configured_continuity_request_fingerprint,
)
from loushang.harness.continuity.plugin_declaration import (
    CONTINUITY_PROVIDER_COMPONENT_DEFINITION,
)
from loushang.harness.continuity.plugin_runtime import prepare_continuity_activation
from loushang.harness.continuity.plugin_runtime import (
    resolve_continuity_plugin_selection as resolve_continuity_plugin_selection,
)
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.plugin_management.configured_sources import (
    read_configured_plugin_selection,
)
from loushang.harness.resources.packages._private_directory import (
    prepare_private_directory,
    prepare_private_directory_tree,
)
from loushang.harness.resources.packages.materializer import (
    GitPackageMaterializerBackend,
    PackageMaterializer,
)
from loushang.harness.resources.plugins import (
    PluginExecutionApprovalSubject,
    PluginInstanceRevisionRef,
    PluginRuntimeResolution,
    PluginSelection,
    PluginSelectionPlanV2,
    PluginSourceBinding,
    PluginSourceTrustSnapshotV1,
    PublishedPluginPackage,
)
from loushang.harness.session.plugin_lifecycle._continuity_installed_plugins import (
    InstalledContinuityLifecycle,
    bind_installed_continuity,
    resolve_installed_continuity_definitions,
)

_PRODUCT_POLICY_REVISION = "coding-continuity-production-1"
_OWNER_POLICY_REVISION = "coding-continuity-owner-1"
_SOURCE_TRUST_POLICY_REVISION = "coding-continuity-source-trust-1"
_AUTHORITY_CEILING = ("continuity.delete", "network.read")
_CONTINUITY_REVOCATION_EPOCH = 0
_APPROVAL_TTL_MS = 300_000
_BOOTSTRAP_STATUS_ATTRIBUTE = "_loushang_coding_continuity_bootstrap_status"
_CONTINUITY_COMPOSITION_ATTRIBUTE = "_loushang_coding_continuity"
_CONTINUITY_ACTIVATION_ID_PREFIX = "continuity-bootstrap-activate"
_CONTINUITY_ALREADY_BOUND = "coding_continuity_composition_already_bound"
_REVISION_CLEANUP_NOTE = "Coding Continuity revision cleanup failed: "
_LAST_READY_STATUS_ATTRIBUTE = "_loushang_coding_continuity_bootstrap_last_ready_status"
_STABLE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_STATE_PERMISSIONS_FAILED = "coding_continuity_state_permissions_failed"


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
class CodingContinuityBootstrapStatus(_ContinuityBootstrapStatus):
    """Finite operational projection; it intentionally contains no source path."""

    _status_attribute = _BOOTSTRAP_STATUS_ATTRIBUTE
    _last_ready_attribute = _LAST_READY_STATUS_ATTRIBUTE
    _product_label = "Coding"

    state: CodingContinuityBootstrapState = "idle"
    code: str = "coding_continuity_not_started"
    configured_source_count: int = 0
    plugin_count: int = 0
    provider_count: int = 0
    recovered_deletion_count: int = 0
    retryable: bool = False


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
    status = CodingContinuityBootstrapStatus._current_status(runtime)
    return status if status is not None else CodingContinuityBootstrapStatus()


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
        _raise_bootstrap_failure(
            runtime, diagnostics_service, error, configured_source_count=0
        )

    configured_count = len(sources)
    startup_lease = ExitStack()

    def record_ready(plugin_count: int, provider_count: int, recovered_count: int) -> None:
        _record_ready_status(
            runtime,
            diagnostics_service,
            configured_source_count=configured_count,
            plugin_count=plugin_count,
            provider_count=provider_count,
            recovered_deletion_count=recovered_count,
        )

    def finish_base_binding() -> CodingContinuityComposition:
        result = bind_coding_continuity(
            runtime, cwd=cwd, all_sessions=all_sessions
        )
        result.configured_request_fingerprint = request_fingerprint
        record_ready(0, 0, 0)
        startup_lease.close()
        return result

    try:
        layout = state_layout or resolve_coding_continuity_state_layout(cwd)
        common_layout = _common_lifecycle_layout(layout)
        prior = getattr(runtime, _CONTINUITY_COMPOSITION_ATTRIBUTE, None)
        existing = (
            prior if isinstance(prior, CodingContinuityComposition) else None
        )
        if (
            not product_route
            and (sys.platform.startswith("linux") or os.name == "nt")
            and (
                sources
                or settings_manager is not None
                or (existing is not None and existing.plugin_publication is not None)
            )
            and _hold_process_startup_lease(
                common_layout, startup_id=_CODING_PLUGIN_RUNTIME_BOOT_ID
            )
            and (existing is None or existing.plugin_publication is None)
        ):
            startup_lease.callback(
                _release_process_startup_lease,
                common_layout,
                startup_id=_CODING_PLUGIN_RUNTIME_BOOT_ID,
            )
        compatibility = (
            None
            if product_route
            else bind_coding_plugin_enablement_compatibility(
                common_layout,
                settings_manager,
            )
        )
        if compatibility is not None:
            # The settings writer now owns the pre-fence registration.
            startup_lease.pop_all()
            compatibility.reconcile()
            sources, disabled_plugins = _configured_sources(
                settings_manager,
                cwd=cwd,
            )
            configured_count = len(sources)
        request_fingerprint = _bootstrap_request_fingerprint(
            sources,
            disabled_plugins=disabled_plugins,
            cwd=cwd,
            all_sessions=all_sessions,
        )

        if existing is not None:
            if existing.admit_configured_reentry(
                request_fingerprint,
                has_sources=bool(sources),
                cwd=cwd,
                all_sessions=all_sessions,
                conflict=lambda: CodingContinuityBootstrapError(
                    code=_CONTINUITY_ALREADY_BOUND, retryable=False
                ),
            ):
                _restore_ready_status(runtime, diagnostics_service)
            else:
                record_ready(0, 0, 0)
            startup_lease.close()
            return existing

        if not sources:
            return finish_base_binding()
    except BaseException as error:
        startup_lease.close()
        if (
            isinstance(error, CodingContinuityBootstrapError)
            and error.code == _CONTINUITY_ALREADY_BOUND
        ):
            # The already-published composition remains healthy.  Reject the
            # conflicting rebind without overwriting its ready status.
            raise
        _raise_bootstrap_failure(
            runtime, diagnostics_service, error, configured_source_count=configured_count
        )

    try:
        resolved_runtime_id = runtime_id or _new_runtime_id()
        if materializer is not None:
            _require_continuity_package_authority(layout, materializer)
        resolved_materializer = (
            materializer or _coding_continuity_materializer(layout)
        )
        _prepare_private_state_layout(layout)
        _prepare_private_runtime_roots(layout)
        lifecycle = _build_lifecycle(layout)
        # Installed lifecycle recovery owns the process startup lease now.
        startup_lease.pop_all()
        return await bind_installed_continuity(
            sources,
            lifecycle,
            request_fingerprint=request_fingerprint,
            materializer=resolved_materializer,
            product_id=CODING_EXPERIENCE_ID,
            scope_id=layout.scope_id,
            activation_id_prefix=_CONTINUITY_ACTIVATION_ID_PREFIX,
            direct_host_reference=f"coding-continuity-host:{layout.scope_id}",
            lifecycle_error=_continuity_lifecycle_error,
            legacy_disabled_plugin_ids=disabled_plugins,
            reconcile_compatibility=(
                compatibility.reconcile if compatibility is not None else None
            ),
            supports_secure_staging=supports_coding_continuity_secure_staging,
            cleanup_note=_REVISION_CLEANUP_NOTE,
            finalize_selection=partial(_finalize_selection, layout=layout, clock=clock),
            prepare_activation=partial(
                prepare_continuity_activation,
                owner_policy_revision=_OWNER_POLICY_REVISION,
                revocation_epoch=_CONTINUITY_REVOCATION_EPOCH,
                decision_path=layout.activation_decisions,
                approval_ttl_ms=_APPROVAL_TTL_MS,
                clock=clock,
                read_clock=partial(_read_clock, clock),
                validate_subject=partial(_validate_activation_subject, layout=layout),
                authorization=_approval_authorization,
            ),
            bind_base=finish_base_binding,
            bind_generation=partial(
                bind_coding_plugin_continuity,
                runtime,
                runtime_id=resolved_runtime_id,
                cwd=cwd,
                all_sessions=all_sessions,
                temporary_root=layout.temporary_root,
                fallback_cwd=cwd,
            ),
            record_ready=record_ready,
        )
    except BaseException as error:
        startup_lease.close()
        _raise_bootstrap_failure(
            runtime, diagnostics_service, error, configured_source_count=configured_count
        )


@dataclass(frozen=True, slots=True)
class _ContinuityDefinitionApprovalOwner:
    plan: PluginSelectionPlanV2
    clock: Callable[[], int]

    def approve_definition(
        self,
        *,
        journal: PluginExecutionDecisionJournal,
        subject: PluginExecutionApprovalSubject,
    ) -> PluginApprovalDecisionRecordV1:
        _validate_definition_subject(subject, self.plan)
        now = _read_clock(self.clock)
        return journal.issue_execution_decision(
            subject,
            disposition="approved",
            authorization=_approval_authorization(),
            revocation_epoch=_CONTINUITY_REVOCATION_EPOCH,
            issued_at_unix_ms=now,
            expires_at_unix_ms=now + _APPROVAL_TTL_MS,
            expected_journal_revision=journal.snapshot().journal_revision,
        )


def _finalize_selection(
    runtime: PluginRuntimeResolution,
    instance_refs: tuple[PluginInstanceRevisionRef, ...],
    *,
    layout: CodingContinuityStateLayout,
    clock: Callable[[], int],
) -> PluginSelection:
    return resolve_installed_continuity_definitions(
        runtime,
        instance_refs=instance_refs,
        product_id=CODING_EXPERIENCE_ID,
        scope_id=layout.scope_id,
        policy_revision=_PRODUCT_POLICY_REVISION,
        allowed_authority_ceiling=_AUTHORITY_CEILING,
        source_trust=_configured_source_trust,
        journal_path=layout.definition_decisions,
        clock=clock,
        approval_owner=lambda plan: _ContinuityDefinitionApprovalOwner(plan, clock),
        distribution_evidence_resolver=coding_plugin_distribution_evidence_resolver,
        error_code_prefix="coding_continuity",
        error_factory=lambda _message, code: CodingContinuityBootstrapError(
            code=code, retryable=False
        ),
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
    return read_configured_plugin_selection(
        settings_manager,
        cwd=cwd,
        invalid=partial(_continuity_lifecycle_error, retryable=False),
    )


def _bootstrap_request_fingerprint(
    sources: tuple[str, ...],
    *,
    disabled_plugins: frozenset[str],
    cwd: str | Path,
    all_sessions: bool,
) -> str:
    return configured_continuity_request_fingerprint(
        sources,
        disabled_plugins=disabled_plugins,
        cwd=cwd,
        all_sessions=all_sessions,
        policy_revision=_PRODUCT_POLICY_REVISION,
        digest_domain=b"loushang.coding-continuity-bootstrap-request/v2\0",
    )


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


def _build_lifecycle(layout: CodingContinuityStateLayout) -> InstalledContinuityLifecycle:
    return InstalledContinuityLifecycle.open(
        layout.instance_runtime,
        lambda security: build_coding_plugin_lifecycle(
            _common_lifecycle_layout(layout), security_acceptances=security
        ),
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


def _prepare_private_state_layout(layout: CodingContinuityStateLayout) -> None:
    prepare_private_directory_tree(
        layout.root,
        private_base=layout.private_state_base,
        outside_base_error=lambda: CodingContinuityBootstrapError(
            code=_STATE_PERMISSIONS_FAILED, retryable=False
        ),
        private_error=lambda: CodingContinuityBootstrapError(
            code=_STATE_PERMISSIONS_FAILED
        ),
    )


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
    CodingContinuityBootstrapStatus(
        state="ready",
        code="coding_continuity_ready",
        configured_source_count=configured_source_count,
        plugin_count=plugin_count,
        provider_count=provider_count,
        recovered_deletion_count=recovered_deletion_count,
    )._publish(runtime, diagnostics)


def _restore_ready_status(
    runtime: object,
    diagnostics: DiagnosticsService | None,
) -> None:
    status = CodingContinuityBootstrapStatus._previous_ready_status(runtime)
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


def _raise_bootstrap_failure(
    runtime: CodingContinuityRuntimePort,
    diagnostics_service: DiagnosticsService | None,
    error: BaseException,
    *,
    configured_source_count: int,
) -> NoReturn:
    if not isinstance(error, Exception):
        raise error
    code = _stable_error_code(error)
    CodingContinuityBootstrapStatus(
        state="failed",
        code=code,
        configured_source_count=configured_source_count,
        retryable=(
            error.retryable if isinstance(error, CodingContinuityBootstrapError) else True
        ),
    )._publish(runtime, diagnostics_service)
    if isinstance(error, CodingContinuityBootstrapError):
        raise error
    raise CodingContinuityBootstrapError(code=code) from None


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
