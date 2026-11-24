"""Coding Session selection over compatible and fenced Plugin storage owners."""

from __future__ import annotations

import json as json
import os as os
import sys as sys
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from functools import partial
from hashlib import sha256
from importlib.metadata import version as version
from pathlib import Path
from threading import Lock
from typing import Literal, cast

from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycleStateLayout,
)
from loushang.coding.plugin_manager.lifecycle import (
    _workspace_scope_id as _workspace_scope_id,
)
from loushang.coding.plugin_manager.lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout as resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.resume.activation_attempt_v2 import CodingResumeEffectOwnerV1
from loushang.coding.session.manager import SessionManager
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product._application_runtime import (
    FencedOrdinaryProductApplication,
    FencedProductApplicationSelection,
    FencedSourceCatalogRoots,
    LegacyProductWorkspace,
    OrdinaryProductSessionOwner,
    bind_fenced_product_session_owner,
    fenced_source_catalog_scope,
    handoff_product_open,
    hold_accepted_product_adoption,
    open_fenced_product_management_state,
    require_current_product_admission,
)
from loushang.harness.package_product._legacy_runtime import (
    legacy_product_state_has_inputs,
    matches_epoch_layout,
    open_native_fenced_product_epoch,
    read_fresh_product_source_snapshot,
)
from loushang.harness.package_product._plugin_bootstrap import (
    _PluginBootstrapPolicy,
    bootstrap_fresh_product_session,
    bootstrap_product_plugin,
    bootstrap_product_plugins,
    product_bootstrap_completed,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductHostInputs as PosixLocalWheelProductHostInputs,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductRuntimeFactory,
    PosixLocalWheelProductSessionOwner,
    WindowsLocalWheelProductRuntimeFactory,
    WindowsLocalWheelProductSessionOwner,
    _ApplicationWorkerProductRuntimeFactory,
    _SessionOwnedProductRuntimeFactory,
    _SessionProductRuntimeRelease,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.package_gc_binding import (
    PluginPackageGcBindingJournal,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.private_data_confirmation import (
    PluginPrivateDataConfirmationJournal,
)
from loushang.harness.plugin_management.service import PluginManagementService
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal as PackageEpochFenceJournal,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelPolicy,
    PackageProductLocalWorkerAdmissionV1,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
)

from ..control.settings_store import (
    default_global_settings_path,
    default_project_settings_path,
)
from .builtin_wheel import (
    coding_base_product_local_wheel_policy as coding_base_product_local_wheel_policy,
)
from .builtin_wheel import (
    coding_builtin_product_local_wheel_policy as coding_builtin_product_local_wheel_policy,
)
from .builtin_wheel import (
    inspect_posix_coding_base_product_wheel,
    inspect_posix_coding_capability_product_wheels,
)
from .builtin_wheel import (
    prepare_posix_coding_base_product_wheel as prepare_posix_coding_base_product_wheel,
)
from .builtin_wheel import (
    prepare_posix_coding_capability_product_wheels as prepare_posix_coding_capability_product_wheels,
)
from .builtin_wheel import (
    prepare_windows_coding_base_product_wheel as prepare_windows_coding_base_product_wheel,
)
from .builtin_wheel import (
    prepare_windows_coding_capability_product_wheels as prepare_windows_coding_capability_product_wheels,
)
from .epoch_layout import (
    resolve_coding_lifecycle_pre_b_members,
    resolve_coding_package_pre_b_store_members,
)
from .epoch_layout import (
    resolve_coding_package_epoch_layout as resolve_coding_package_epoch_layout,
)
from .external_data_wheel import (
    CodingExternalDataWheelBindingV1,
)
from .external_data_wheel import (
    CodingExternalDataWheelCatalog as CodingExternalDataWheelCatalog,
)
from .external_dependency_wheel import (
    CodingExternalDependencyWheelBindingV1,
)
from .external_dependency_wheel import (
    CodingExternalDependencyWheelCatalog as CodingExternalDependencyWheelCatalog,
)
from .external_worker_wheel import (
    CodingExternalWorkerWheelBindingV1,
)
from .external_worker_wheel import (
    CodingExternalWorkerWheelCatalog as CodingExternalWorkerWheelCatalog,
)
from .external_worker_wheel import (
    CodingWindowsExternalWorkerWheelCatalog as CodingWindowsExternalWorkerWheelCatalog,
)
from .legacy_binding_catalog import (
    CodingLegacyLocalBindingCatalog as CodingLegacyLocalBindingCatalog,
)
from .legacy_classification import (
    classify_coding_legacy_source_configuration as classify_coding_legacy_source_configuration,
)
from .legacy_data_trust import (
    LEGACY_LOCAL_DATA_TRUST_CLASSES as LEGACY_LOCAL_DATA_TRUST_CLASSES,
)
from .legacy_disabled_acceptance import (
    CodingLegacyDisabledOnlyAcceptanceV1,
)
from .legacy_disabled_acceptance import (
    accept_coding_first_b_disabled_only as accept_coding_first_b_disabled_only,
)
from .legacy_local_acceptance import (
    reopen_coding_legacy_installed_local_acceptance as reopen_coding_legacy_installed_local_acceptance,
)
from .legacy_snapshot_member import _snapshot_reader
from .legacy_snapshot_member import (
    list_coding_first_b_snapshot_domain_members as list_coding_first_b_snapshot_domain_members,
)
from .legacy_snapshot_member import (
    read_coding_first_b_snapshot_member as read_coding_first_b_snapshot_member,
)
from .private_data_deletion_journal import CodingArchPrivateDataDeletionJournal
from .product_backup_types import (
    ensure_coding_product_backup_types as ensure_coding_product_backup_types,
)
from .product_worker_opt_in import CodingWorkerOptInJournal
from .source_snapshot import _source_projection

CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH = 2
CODING_PACKAGE_PRODUCT_POLICY_REVISION = "coding-product-package-policy:1"

_CODING_BUILTIN_BOOTSTRAP_POLICY = _PluginBootstrapPolicy(
    product_id="coding",
    operation_id_prefix="coding-builtin-bootstrap:",
    enable_id_prefix="coding-builtin-bootstrap-enable:",
    error_prefix="Coding builtin Product bootstrap",
    plugin_ids=("coding.base", "coding.lsp.default", "coding.arch.default"),
)

_fresh_coding_builtin_bootstrap_completed = partial(
    product_bootstrap_completed,
    policy=_CODING_BUILTIN_BOOTSTRAP_POLICY,
)


_RESUME_EPOCH_DOMAIN = b"loushang.coding.resume-epoch/v1\0"


@dataclass(frozen=True, slots=True)
class CodingPackageProductStateOwners:
    """Fresh B-only management journals, separate from pre-B replay state."""

    state_root: Path
    gc_gate: PluginPackageGcReservationJournal
    desired_state: PluginDesiredStateLedger
    management: PluginManagementService
    gc_bindings: PluginPackageGcBindingJournal
    worker_opt_in: CodingWorkerOptInJournal
    private_data_confirmation: PluginPrivateDataConfirmationJournal
    private_data_deletion: CodingArchPrivateDataDeletionJournal


def _require_current_coding_product_admission(check: Callable[[], None] | None) -> None:
    """Validate one native formal check without changing existing-store policy."""

    require_current_product_admission(check, label="Coding Product")


def _require_runtime_owner(lifecycle: object, epoch_runtime: object) -> None:
    if not isinstance(lifecycle, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding Package lifecycle layout is required")
    if not isinstance(
        epoch_runtime,
        (
            PackageProductPosixFencedRuntimeOwner,
            PackageProductWindowsFencedRuntimeOwner,
        ),
    ):
        raise TypeError("Coding Package Product epoch owner is required")


def open_coding_package_product_state(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: (
        PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner
    ),
    *,
    before_recovery: Callable[[], None] | None = None,
    require_current_admission: Callable[[], None] | None = None,
) -> CodingPackageProductStateOwners:
    """Open durable Product owners only for this workspace's fenced Store."""

    _require_runtime_owner(lifecycle, epoch_runtime)
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if not matches_epoch_layout(epoch_runtime, epoch):
        raise ValueError("Coding Package Product workspace authority changed")
    state_root, gate, desired, management, bindings = open_fenced_product_management_state(
        epoch_runtime,
        validate_topology=partial(
            ensure_coding_product_backup_types,
            scope_id=lifecycle.scope_id,
            epoch_runtime=epoch_runtime,
            before_load=before_recovery,
            require_current_admission=require_current_admission,
        ),
        before_recovery=before_recovery,
        require_current_admission=require_current_admission,
        label="Coding Product",
    )
    worker_opt_in = CodingWorkerOptInJournal(
        state_root / "worker-opt-in.jsonl",
        scope_id=lifecycle.scope_id,
        gc_gate=gate,
        store_id=epoch_runtime.registry.store_id,
    )
    private_data_confirmation = PluginPrivateDataConfirmationJournal(
        state_root / "private-data-confirmations.jsonl"
    )
    private_data_deletion = CodingArchPrivateDataDeletionJournal(state_root)
    epoch_runtime.assert_current()
    return CodingPackageProductStateOwners(
        state_root=state_root,
        gc_gate=gate,
        desired_state=desired,
        management=management,
        gc_bindings=bindings,
        worker_opt_in=worker_opt_in,
        private_data_confirmation=private_data_confirmation,
        private_data_deletion=private_data_deletion,
    )


_CODING_SESSION_RUNTIME_ID_PREFIX = "coding-session:"


@dataclass(frozen=True, slots=True)
class CodingPosixLocalWheelProductRuntimeOwner(OrdinaryProductSessionOwner[SessionManager]):
    """Select the exact Coding Session for a fenced Product owner."""

    product_owner: (
        PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner
    )

    _product_id = "coding"
    _label = "Coding"
    _runtime_id_prefix = _CODING_SESSION_RUNTIME_ID_PREFIX
    _session_manager_type = SessionManager

    def _session_workspace(self, manager: SessionManager) -> Path:
        return manager.package_product_workspace()


@dataclass(frozen=True, slots=True)
class CodingFencedProductApplicationOwner(FencedOrdinaryProductApplication[SessionManager]):
    """Retain one B epoch owner for the lifetime of a Coding application."""

    epoch_runtime: (
        PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner
    )
    runtime_owner: CodingPosixLocalWheelProductRuntimeOwner

    _label = "Coding"
    _runtime_id_prefix = _CODING_SESSION_RUNTIME_ID_PREFIX


class CodingFencedProductApplicationSelection(
    FencedProductApplicationSelection[SessionManager, SettingsManager]
):
    """Preserve existing storage; select B for fresh or already fenced workspaces."""

    _application_label = "Coding"
    _resume_epoch_domain = _RESUME_EPOCH_DOMAIN
    _session_manager_type = SessionManager

    def __init__(
        self,
        *,
        windows_candidate: bool = False,
        worker_candidates: bool = False,
    ) -> None:
        if type(windows_candidate) is not bool:
            raise TypeError(
                "Coding Windows Product candidate selection must be explicit"
            )
        if type(worker_candidates) is not bool:
            raise TypeError("Coding Worker candidate selection must be explicit")
        self._windows_candidate = windows_candidate
        super().__init__(worker_candidates=worker_candidates)

    def _session_workspace(self, manager: SessionManager) -> Path:
        return manager.package_product_workspace()

    def _historical_workspace(self, manager: SessionManager) -> Path | None:
        return manager.legacy_plugin_workspace()

    def resume_worker_effect_owner(self, workspace: Path) -> CodingResumeEffectOwnerV1:
        """Freeze the selected Product's original Worker C5 obligation."""

        from .product_worker_resume import prepare_coding_worker_resume_effect_owner

        with self._hold_selected_worker_product(workspace) as product:
            return prepare_coding_worker_resume_effect_owner(
                product_id=product.policy.product_id,
                product_scope_id=product.policy.project_scope_id,
            )

    @staticmethod
    def _external_bindings_current(
        owner: FencedOrdinaryProductApplication[SessionManager],
        *,
        lifecycle: CodingPluginLifecycleStateLayout,
    ) -> bool:
        roots = owner.selected_source_catalog_roots(lifecycle.scope_id)
        if roots is None:
            return False
        policy = owner.runtime_owner.product_owner.policy
        expected_data, observed_data = (
            CodingExternalDataWheelCatalog.for_roots(roots).project_policy_group(
                policy, trust_class="local-data-only"
            )
        )
        expected_legacy, observed_legacy = CodingLegacyLocalBindingCatalog.for_roots(
            roots, policy_revision=policy.policy_revision
        ).project_policy_group(policy, trust_classes=LEGACY_LOCAL_DATA_TRUST_CLASSES)
        return expected_data == observed_data and expected_legacy == observed_legacy

    def _open_workspace_selection(
        self,
        workspace: Path,
        owner: FencedOrdinaryProductApplication[SessionManager] | None,
        *,
        settings_manager: SettingsManager | None,
        require_current_admission: Callable[[], None] | None,
        historical_origin: Path | None = None,
    ) -> FencedOrdinaryProductApplication[SessionManager] | LegacyProductWorkspace:
        lifecycle = resolve_coding_plugin_lifecycle_state_layout(
            workspace, historical_origin=historical_origin,
        )
        if owner is not None and self._external_bindings_current(owner, lifecycle=lifecycle):
            return owner
        if owner is None:
            epoch = resolve_coding_package_epoch_layout(lifecycle)
            native_blocked = (
                os.name == "posix" and not sys.platform.startswith("linux")
            ) or (os.name == "nt" and not self._windows_candidate)
            workspace_inputs = partial(
                coding_product_inputs_need_compatibility,
                lifecycle,
                workspace=workspace,
                settings_manager=settings_manager,
            )

            def bootstrap(initial: bool) -> None:
                _bootstrap_coding_product_for_session(
                    lifecycle,
                    workspace=workspace,
                    settings_manager=settings_manager,
                    windows_candidate=self._windows_candidate,
                    require_current_admission=require_current_admission,
                    initial=initial,
                )

            legacy = self._prepare_workspace_storage(
                LegacyProductWorkspace(epoch.control_root, lifecycle.root, lifecycle.package_root),
                store_id=epoch.store_id,
                native_blocked=native_blocked,
                require_current_admission=require_current_admission,
                needs_legacy=workspace_inputs,
                bootstrap=bootstrap,
            )
            if legacy is not None:
                return legacy

        return open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
            worker_candidates=self._worker_candidates,
            windows_candidate=self._windows_candidate,
            require_current_admission=require_current_admission,
        )


@dataclass(slots=True)
class _CodingSessionProductRuntimeRelease(_SessionProductRuntimeRelease):
    """Keep the original lease identity visible through Session disposal."""

    release: Callable[[], None]
    selection: CodingFencedProductApplicationSelection


@dataclass(slots=True)
class CodingSessionOwnedProductRuntimeFactory(_SessionOwnedProductRuntimeFactory):
    """Transfer a one-Session Product owner to the runtime binding's disposal."""

    _product_label = "Coding"

    factory: (
        PosixLocalWheelProductRuntimeFactory | WindowsLocalWheelProductRuntimeFactory
    )
    selection: CodingFencedProductApplicationSelection
    _binding_issued: bool = False
    _lock: Lock = field(default_factory=Lock, repr=False)

    def _dispose_binding(self, release: Callable[[], None]) -> Callable[[], None]:
        return _CodingSessionProductRuntimeRelease(release, self.selection).dispose


@dataclass(frozen=True, slots=True)
class CodingApplicationWorkerProductRuntimeFactory(
    _ApplicationWorkerProductRuntimeFactory
):
    """Expose one app-owned Product factory to an explicit Worker Session."""

    _product_label = "Coding"

    factory: (
        PosixLocalWheelProductRuntimeFactory | WindowsLocalWheelProductRuntimeFactory
    )
    selection: CodingFencedProductApplicationSelection


@dataclass(frozen=True, slots=True)
class CodingProductWorkspaceWitnessV1:
    """A Session's original Product workspace, checked by its admitting factory."""

    session_id: str
    workspace: Path
    _assert_current: Callable[[], None] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.session_id, str)
            or not self.session_id
            or not isinstance(self.workspace, Path)
            or not self.workspace.is_absolute()
            or not callable(self._assert_current)
        ):
            raise ValueError("Coding Product workspace witness is invalid")

    def assert_current(self) -> None:
        self._assert_current()


def bind_coding_product_workspace_witness(
    factory: object, *, session_id: str
) -> CodingProductWorkspaceWitnessV1 | None:
    """Carry the Product factory's admission identity into its Session."""

    if isinstance(factory, CodingSessionOwnedProductRuntimeFactory):
        factory = factory.factory
    if isinstance(factory, CodingApplicationWorkerProductRuntimeFactory):
        factory = factory.factory
    if not isinstance(
        factory,
        (PosixLocalWheelProductRuntimeFactory, WindowsLocalWheelProductRuntimeFactory),
    ):
        return None
    if factory.expected_session_id != session_id:
        raise ValueError("Coding Product Session workspace witness changed Session")
    factory.assert_workspace_current()
    return CodingProductWorkspaceWitnessV1(
        session_id=session_id,
        workspace=factory.expected_cwd,
        _assert_current=factory.assert_workspace_current,
    )


def open_coding_fenced_product_application_owner(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
    worker_candidates: bool = False,
    windows_candidate: bool = False,
    require_current_admission: Callable[[], None] | None = None,
) -> CodingFencedProductApplicationOwner:
    """Reopen the exact B fence and bind all first-party Coding Packages."""

    if type(worker_candidates) is not bool:
        raise TypeError("Coding Worker candidate selection must be explicit")
    if type(windows_candidate) is not bool:
        raise TypeError("Coding Windows Product candidate selection must be explicit")
    if os.name == "nt" and not windows_candidate:
        raise RuntimeError("Coding Windows Product Session route is not yet admitted")
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    _require_current_coding_product_admission(require_current_admission)
    epoch_runtime = open_native_fenced_product_epoch(**epoch.fenced_runtime_open_kwargs())
    with handoff_product_open(
        epoch_runtime, cleanup_note="Coding Product epoch cleanup also failed"
    ):
        state = open_coding_package_product_state(
            lifecycle,
            epoch_runtime,
            require_current_admission=require_current_admission,
        )
        _require_current_coding_product_admission(require_current_admission)
        runtime_owner = open_coding_builtin_product_runtime_owner(
            lifecycle,
            epoch_runtime,
            state,
            workspace=workspace,
            runtime_version=runtime_version,
            runtime_protocol_epoch=runtime_protocol_epoch,
            worker_candidates=worker_candidates,
        )
        return CodingFencedProductApplicationOwner(epoch_runtime, runtime_owner)


def admit_coding_external_data_wheel(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    source: Path,
) -> CodingExternalDataWheelBindingV1:
    """Capture one local data Wheel under the current fenced Product Source root."""

    return cast(
        "CodingExternalDataWheelBindingV1",
        _capture_coding_inert_source(lifecycle, source=source, kind="data"),
    )


def admit_coding_external_dependency_wheel(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    source: Path,
) -> CodingExternalDependencyWheelBindingV1:
    """Pin inert dependency bytes; no Coding Plugin profile may use them yet."""

    return cast(
        "CodingExternalDependencyWheelBindingV1",
        _capture_coding_inert_source(lifecycle, source=source, kind="dependency"),
    )


def admit_coding_external_worker_wheel(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    source: Path,
    admission: PackageProductLocalWorkerAdmissionV1,
) -> CodingExternalWorkerWheelBindingV1:
    """Capture one inert Worker candidate; the normal Session route stays dark."""

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    epoch_runtime = open_native_fenced_product_epoch(**epoch.fenced_runtime_open_kwargs())
    with fenced_source_catalog_scope(
        epoch_runtime,
        scope_id=lifecycle.scope_id,
        no_namespace="Coding Package Product root is not fenced",
    ) as roots:
        if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner):
            return CodingWindowsExternalWorkerWheelCatalog(
                epoch_runtime=epoch_runtime, state_root=roots.state_root, **roots.identity
            ).capture(source, admission=admission)
        return CodingExternalWorkerWheelCatalog(
            roots.state_root / "external-worker-wheel-bindings.jsonl",
            **roots.identity,
        ).capture(source, admission=admission, epoch_runtime=epoch_runtime)


def _capture_coding_inert_source(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    source: Path,
    kind: Literal["data", "dependency"],
) -> CodingExternalDataWheelBindingV1 | CodingExternalDependencyWheelBindingV1:
    """Capture one inert source through the original epoch and catalog owners."""
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    epoch_runtime = PackageProductPosixFencedRuntimeOwner.open(
        **epoch.fenced_runtime_open_kwargs()
    )
    with fenced_source_catalog_scope(
        epoch_runtime,
        scope_id=lifecycle.scope_id,
        no_namespace="Coding Package Product root is not fenced",
    ) as roots:
        catalog = (
            CodingExternalDataWheelCatalog.for_roots(roots)
            if kind == "data"
            else CodingExternalDependencyWheelCatalog(
                roots.state_root / "external-dependency-wheel-bindings.jsonl",
                **roots.identity,
            )
        )
        return catalog.capture(source, epoch_runtime=epoch_runtime)


def bootstrap_coding_builtin_product_plugins(
    lifecycle: CodingPluginLifecycleStateLayout,
    settings_manager: SettingsManager,
    *,
    workspace: Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
    windows_candidate: bool = False,
    require_current_admission: Callable[[], None] | None = None,
) -> bool:
    """Install and enable unseen first-party Plugins through the fenced Product.

    Only a disabled selection committed by this exact bootstrap installation
    may finish an interrupted enable. A later operator disable or remove is
    never converted back into a default install.
    """

    require_fresh_coding_product_inputs(lifecycle, settings_manager)
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        windows_candidate=windows_candidate,
        require_current_admission=require_current_admission,
    )
    with closing(owner):
        return bootstrap_product_plugins(
            owner.runtime_owner.product_owner,
            policy=_CODING_BUILTIN_BOOTSTRAP_POLICY,
            require_current_admission=partial(
                _require_current_coding_product_admission, require_current_admission
            ),
        )


def bootstrap_coding_accepted_disabled_only_product_plugins(
    lifecycle: CodingPluginLifecycleStateLayout,
    settings_manager: SettingsManager,
    *,
    workspace: Path,
    accepted_review_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
) -> CodingLegacyDisabledOnlyAcceptanceV1:
    """Install builtins from an explicitly accepted, fenced Source snapshot."""

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    with hold_accepted_product_adoption(
        open_epoch=lambda: PackageProductPosixFencedRuntimeOwner.open(
            **epoch.fenced_runtime_open_kwargs()
        ),
        accept_review=lambda epoch_runtime: accept_coding_first_b_disabled_only(
            lifecycle,
            epoch_runtime,
            settings_manager=settings_manager,
            accepted_review_id=accepted_review_id,
        ),
        open_application=lambda: open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version=runtime_version,
            runtime_protocol_epoch=runtime_protocol_epoch,
        ),
    ) as (receipt, owner):
        bootstrap_product_plugins(
            owner.runtime_owner.product_owner,
            policy=_CODING_BUILTIN_BOOTSTRAP_POLICY,
            disabled_ids={item.plugin_id for item in receipt.review.disabled_plugins},
        )
        return receipt


def require_fresh_coding_product_inputs(
    lifecycle: CodingPluginLifecycleStateLayout,
    settings_manager: SettingsManager,
    *,
    roots_may_be_absent: bool = False,
) -> None:
    """Refuse to treat legacy settings or state as a fresh Product default."""

    if not isinstance(settings_manager, SettingsManager):
        raise TypeError("Coding settings manager is required")
    _source_projection.require_fresh_inputs(
        _source_projection.has_loaded_pre_fence_inputs(settings_manager),
    )
    if type(roots_may_be_absent) is not bool:
        raise TypeError("Coding fresh Product root policy is invalid")
    _source_projection.require_fresh_inputs(
        _legacy_state_requires_migration(lifecycle, skip_missing=roots_may_be_absent),
    )


def require_fresh_coding_product_inputs_without_writes(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    settings_manager: SettingsManager | None = None,
) -> None:
    """Require empty input for an explicit fresh-only Product cutover."""

    _source_projection.require_fresh_inputs(
        coding_product_inputs_need_compatibility(
            lifecycle, workspace=workspace, settings_manager=settings_manager
        ),
    )


def coding_product_inputs_need_compatibility(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    settings_manager: SettingsManager | None = None,
) -> bool:
    """Inspect existing inputs without writing or changing their authority."""

    if not isinstance(lifecycle, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding Plugin lifecycle layout is required")
    if _coding_product_settings_need_compatibility(
        workspace=workspace, settings_manager=settings_manager
    ):
        return True
    return _legacy_state_requires_migration(lifecycle, skip_missing=True)


def require_fresh_coding_product_settings_without_writes(
    *, workspace: Path, settings_manager: SettingsManager | None = None
) -> None:
    """Require fresh settings for an explicit fresh-only Product cutover."""

    _source_projection.require_fresh_inputs(
        _coding_product_settings_need_compatibility(
            workspace=workspace, settings_manager=settings_manager
        ),
    )


def _coding_product_settings_need_compatibility(
    *,
    workspace: Path,
    settings_manager: SettingsManager | None,
) -> bool:
    if not isinstance(workspace, Path) or not workspace.is_absolute():
        raise ValueError("Coding workspace must be absolute")
    return _source_projection.workspace_has_pre_fence_inputs(
        (default_global_settings_path(), default_project_settings_path(workspace)),
        settings_manager,
    )


def _fresh_coding_bootstrap_settings(
    lifecycle: CodingPluginLifecycleStateLayout,
    workspace: Path,
    settings_manager: SettingsManager | None,
    *,
    initial: bool,
    require_current_admission: Callable[[], None] | None,
) -> SettingsManager:
    global_path = default_global_settings_path()
    project_path = default_project_settings_path(workspace)
    if settings_manager is not None:
        if initial:
            require_fresh_coding_product_inputs(
                lifecycle, settings_manager, roots_may_be_absent=True
            )
        global_path = settings_manager.global_settings_path or global_path
        project_path = settings_manager.project_settings_path or project_path
    _require_current_coding_product_admission(require_current_admission)
    return SettingsManager(
        global_settings_path=global_path, project_settings_path=project_path
    )


def _bootstrap_coding_product_for_session(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    settings_manager: SettingsManager | None,
    windows_candidate: bool,
    require_current_admission: Callable[[], None] | None,
    initial: bool,
) -> None:
    """Bind Coding's inputs and default packages to the shared startup route."""

    def bootstrap() -> None:
        settings = _fresh_coding_bootstrap_settings(
            lifecycle, workspace, settings_manager,
            initial=initial, require_current_admission=require_current_admission,
        )
        install: Callable[..., object] = bootstrap_coding_builtin_product_plugins
        if initial:
            epoch = resolve_coding_package_epoch_layout(lifecycle)
            namespace_id = _fresh_coding_product_namespace_id(epoch.store_id)
            from loushang.coding.package.pre_b_snapshot import (
                cutover_and_bootstrap_coding_package_product,
            )

            install = partial(cutover_and_bootstrap_coding_package_product, namespace_id=namespace_id)
        install(
            lifecycle, settings, workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
            windows_candidate=windows_candidate,
            require_current_admission=require_current_admission,
        )

    bootstrap_fresh_product_session(
        workspace,
        initial=initial,
        windows_candidate=windows_candidate,
        product_label="Coding",
        require_fresh_inputs=partial(
            require_fresh_coding_product_inputs_without_writes,
            lifecycle, workspace=workspace, settings_manager=settings_manager,
        ),
        resolve_roots=lambda: resolve_coding_package_epoch_layout(lifecycle).fenced_runtime_open_kwargs(),
        verify_snapshot=partial(is_coding_fresh_first_b_snapshot, lifecycle),
        open_application=lambda: open_coding_fenced_product_application_owner(
            lifecycle, workspace=workspace, runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
            windows_candidate=windows_candidate,
            require_current_admission=require_current_admission,
        ),
        require_current_admission=require_current_admission,
        policy=_CODING_BUILTIN_BOOTSTRAP_POLICY,
        bootstrap=bootstrap,
    )


def _fresh_coding_product_namespace_id(store_id: str) -> str:
    return sha256(
        b"loushang.coding-fresh-product-epoch/v1\0" + store_id.encode()
    ).hexdigest()


def is_coding_fresh_first_b_snapshot(
    lifecycle: CodingPluginLifecycleStateLayout,
    runtime: PackageProductPosixFencedRuntimeOwner
    | PackageProductWindowsFencedRuntimeOwner,
) -> bool:
    """Read the fenced first-B snapshot before retrying fresh builtin defaults."""

    if not isinstance(lifecycle, CodingPluginLifecycleStateLayout) or not isinstance(
        runtime,
        (
            PackageProductPosixFencedRuntimeOwner,
            PackageProductWindowsFencedRuntimeOwner,
        ),
    ):
        raise TypeError("Coding fresh Product snapshot owner is invalid")
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if not matches_epoch_layout(runtime, epoch):
        raise ValueError("Coding Package Product workspace authority changed")
    raw = read_fresh_product_source_snapshot(
        _snapshot_reader(lifecycle, runtime),
        namespace_id=_fresh_coding_product_namespace_id(epoch.store_id),
        source_member=_source_projection.projection_name,
        maximum_bytes=_source_projection.maximum_bytes,
        label="Coding",
    )
    if raw is None:
        return False
    classification = classify_coding_legacy_source_configuration(json.loads(raw))
    return not (classification.disabled_plugins or classification.configured_source_keys)


def _bootstrap_coding_builtin_plugin(
    owner: CodingFencedProductApplicationOwner,
    plugin_id: str,
    *,
    enable: bool = True,
) -> bool:
    return bootstrap_product_plugin(
        owner.runtime_owner.product_owner,
        plugin_id,
        store_id=owner.epoch_runtime.registry.store_id,
        policy=_CODING_BUILTIN_BOOTSTRAP_POLICY,
        enable=enable,
    )


def open_coding_base_product_runtime_owner(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: (
        PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner
    ),
    state: CodingPackageProductStateOwners,
    *,
    workspace: Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
) -> CodingPosixLocalWheelProductRuntimeOwner:
    """Compose the installed base Plugin from one fenced Product authority."""

    return _open_coding_product_runtime(
        lifecycle,
        epoch_runtime,
        state,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        include_capabilities=False,
        include_worker_candidates=False,
    )


def open_coding_builtin_product_runtime_owner(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: (
        PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner
    ),
    state: CodingPackageProductStateOwners,
    *,
    workspace: Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
    worker_candidates: bool = False,
) -> CodingPosixLocalWheelProductRuntimeOwner:
    """Compose all three first-party Packages without granting execution."""

    return _open_coding_product_runtime(
        lifecycle,
        epoch_runtime,
        state,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        include_capabilities=True,
        include_worker_candidates=worker_candidates,
    )


def _open_coding_product_runtime(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner
    | PackageProductWindowsFencedRuntimeOwner,
    state: CodingPackageProductStateOwners,
    *,
    workspace: Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
    include_capabilities: bool,
    include_worker_candidates: bool,
) -> CodingPosixLocalWheelProductRuntimeOwner:
    _require_runtime_owner(lifecycle, epoch_runtime)
    if not isinstance(state, CodingPackageProductStateOwners):
        raise TypeError("Coding Package Product state owners are required")
    session_owner = bind_fenced_product_session_owner(
        epoch_runtime,
        workspace=workspace,
        state_root=state.state_root,
        scope_id=lifecycle.scope_id,
        workspace_scope=lambda path: _workspace_scope_id(lifecycle.historical_origin or path),
        resolve_epoch=partial(resolve_coding_package_epoch_layout, lifecycle),
        additional_state_paths=(
            (journal.path, name)
            for journal, name in (
                (state.worker_opt_in, "worker-opt-in.jsonl"),
                (state.private_data_confirmation, "private-data-confirmations.jsonl"),
                (state.private_data_deletion, "private-data-deletions.jsonl"),
            )
        ),
        compose_sources=partial(
            _compose_coding_product_source_policy,
            lifecycle,
            epoch_runtime,
            include_capabilities=include_capabilities,
            include_worker_candidates=include_worker_candidates,
        ),
        identity_prefix="coding-product",
        product_label="Coding",
        management=state.management,
        desired_state=state.desired_state,
        gc_bindings=state.gc_bindings,
        gc_gate=state.gc_gate,
        actor_id="product:coding",
        desired_policy_revision="coding-product-desired-policy:1",
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )
    return CodingPosixLocalWheelProductRuntimeOwner(product_owner=session_owner)


def _compose_coding_product_source_policy(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner,
    roots: FencedSourceCatalogRoots,
    *,
    include_capabilities: bool = True,
    include_worker_candidates: bool,
    read_only: bool = False,
) -> tuple[PackageProductLocalWheelPolicy, PosixLocalWheelProductHostInputs]:
    """Assemble the same first-party Sources without promoting a read to a writer."""
    source_root = roots.identity["source_root"]
    windows = isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner)
    capabilities = None
    if read_only:
        base = inspect_posix_coding_base_product_wheel(source_root)
        if include_capabilities:
            capabilities = inspect_posix_coding_capability_product_wheels(source_root)
    else:
        base = (
            prepare_windows_coding_base_product_wheel(source_root)
            if windows
            else prepare_posix_coding_base_product_wheel(source_root)
        )
    host = PosixLocalWheelProductHostInputs.current_host(
        max_transport_bytes=2 * 1024 * 1024
    )
    environment_fingerprint = host.environment.fingerprint
    if not read_only and include_capabilities:
        capabilities = (
            prepare_windows_coding_capability_product_wheels(source_root)
            if windows
            else prepare_posix_coding_capability_product_wheels(source_root)
        )
    policy_options = dict(
        project_scope_id=roots.identity["scope_id"],
        resolution_environment_fingerprint=environment_fingerprint,
        policy_revision=CODING_PACKAGE_PRODUCT_POLICY_REVISION,
        quota_profile_revision="coding-product-package-quota:1",
        authority_id="coding-product-local-source",
    )
    policy = (
        coding_base_product_local_wheel_policy(base, **policy_options)
        if capabilities is None
        else coding_builtin_product_local_wheel_policy(base, capabilities, **policy_options)
    )
    state_root = roots.state_root
    policy_revision = policy.policy_revision

    def read_legacy_acceptance(plugin_id: str):
        if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner):
            return None
        return reopen_coding_legacy_installed_local_acceptance(
            lifecycle, epoch_runtime, plugin_id=plugin_id, policy_revision=policy_revision
        )

    legacy = CodingLegacyLocalBindingCatalog.for_roots(
        roots,
        policy_revision=policy_revision,
        acceptance_reader=read_legacy_acceptance,
    )
    policy = legacy.read_extend_policy(policy) if read_only else legacy.extend_policy(policy)
    policy = CodingExternalDataWheelCatalog.for_roots(
        roots, read_only=read_only
    ).extend_policy(policy)
    if isinstance(epoch_runtime, PackageProductPosixFencedRuntimeOwner):
        policy = CodingExternalDependencyWheelCatalog(
            state_root / "external-dependency-wheel-bindings.jsonl",
            **roots.identity,
            read_only=read_only,
        ).extend_policy(policy)
    if include_worker_candidates:
        worker_catalog = (
            CodingWindowsExternalWorkerWheelCatalog(
                epoch_runtime=epoch_runtime, state_root=state_root, **roots.identity
            )
            if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner)
            else CodingExternalWorkerWheelCatalog(
                state_root / "external-worker-wheel-bindings.jsonl",
                **roots.identity,
                read_only=read_only,
            )
        )
        policy = worker_catalog.extend_policy(policy)
    return policy, host


def _legacy_state_requires_migration(
    lifecycle: CodingPluginLifecycleStateLayout, *, skip_missing: bool
) -> bool:
    """Inspect the historical roots in lifecycle-before-package order."""

    return legacy_product_state_has_inputs(
        (
            (lifecycle.root, lambda: resolve_coding_lifecycle_pre_b_members(lifecycle).domain_members()),
            (lifecycle.package_root, lambda: resolve_coding_package_pre_b_store_members(lifecycle).domain_members()),
        ),
        skip_missing=skip_missing,
    )


__all__ = [
    "admit_coding_external_data_wheel",
    "admit_coding_external_dependency_wheel",
    "admit_coding_external_worker_wheel",
    "CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH",
    "CODING_PACKAGE_PRODUCT_POLICY_REVISION",
    "CodingFencedProductApplicationSelection",
    "CodingFencedProductApplicationOwner",
    "CodingSessionOwnedProductRuntimeFactory",
    "CodingProductWorkspaceWitnessV1",
    "bind_coding_product_workspace_witness",
    "CodingPackageProductStateOwners",
    "CodingPosixLocalWheelProductRuntimeOwner",
    "bootstrap_coding_builtin_product_plugins",
    "bootstrap_coding_accepted_disabled_only_product_plugins",
    "require_fresh_coding_product_inputs",
    "open_coding_fenced_product_application_owner",
    "open_coding_base_product_runtime_owner",
    "open_coding_builtin_product_runtime_owner",
    "open_coding_package_product_state",
]
