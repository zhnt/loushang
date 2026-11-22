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
from typing import Literal, TypedDict, cast

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
    LegacyProductWorkspace,
    OrdinaryProductSessionOwner,
    bind_fenced_product_session_owner,
    fenced_source_catalog_scope,
    handoff_product_open,
    hold_accepted_product_adoption,
    open_fenced_product_management_state,
    prepare_product_state_for_recovery,
    product_management_paths_match,
    require_current_product_admission,
    require_product_owner_for_factory,
)
from loushang.harness.package_product._legacy_runtime import (
    inspect_fresh_product_epoch,
    matches_epoch_layout,
    open_native_fenced_product_epoch,
    read_fresh_product_source_snapshot,
)
from loushang.harness.package_product._local_source_catalog import (
    project_local_source_policy_group,
)
from loushang.harness.package_product._plugin_bootstrap import (
    _PluginBootstrapPolicy,
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
    CodingBaseProductWheelArtifactV1,
    CodingCapabilityProductWheelArtifactV1,
)
from .builtin_wheel import (
    coding_base_product_local_wheel_policy as coding_base_product_local_wheel_policy,
)
from .builtin_wheel import (
    coding_builtin_product_local_wheel_policy as coding_builtin_product_local_wheel_policy,
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
from .source_snapshot import coding_settings_have_pre_b_inputs_without_writes

CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH = 2
CODING_PACKAGE_PRODUCT_POLICY_REVISION = "coding-product-package-policy:1"

_CODING_BUILTIN_PLUGIN_IDS = (
    "coding.base",
    "coding.lsp.default",
    "coding.arch.default",
)

_CODING_BUILTIN_BOOTSTRAP_POLICY = _PluginBootstrapPolicy(
    product_id="coding",
    operation_id_prefix="coding-builtin-bootstrap:",
    enable_id_prefix="coding-builtin-bootstrap-enable:",
    error_prefix="Coding builtin Product bootstrap",
)


_RESUME_EPOCH_DOMAIN = b"loushang.coding.resume-epoch/v1\0"


_LIFECYCLE_SNAPSHOT_MAX_BYTES = 4 * 1024 * 1024


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
    state_root, gate = prepare_product_state_for_recovery(
        epoch_runtime,
        before_recovery=before_recovery,
        require_current_admission=require_current_admission,
        label="Coding Product",
    )
    ensure_coding_product_backup_types(
        state_root=state_root,
        scope_id=lifecycle.scope_id,
        epoch_runtime=epoch_runtime,
        gc_gate=gate,
        before_load=before_recovery,
        require_current_admission=require_current_admission,
    )
    desired, management, bindings = open_fenced_product_management_state(
        state_root,
        gate,
        before_recovery=before_recovery,
        require_current_admission=require_current_admission,
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
    FencedProductApplicationSelection[CodingFencedProductApplicationOwner, SettingsManager]
):
    """Preserve existing storage; select B for fresh or already fenced workspaces."""

    _application_label = "Coding"
    _resume_epoch_domain = _RESUME_EPOCH_DOMAIN

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
        self._worker_candidates = worker_candidates
        super().__init__()

    def factory_for_session(
        self,
        manager: SessionManager,
        *,
        settings_manager: SettingsManager | None = None,
    ) -> (
        PosixLocalWheelProductRuntimeFactory
        | WindowsLocalWheelProductRuntimeFactory
        | None
    ):
        if not isinstance(manager, SessionManager):
            raise TypeError("Coding Product Session manager is required")
        # A legacy Session may name a workspace that has yet to be created.
        workspace = Path(manager.get_cwd()).resolve(strict=False)
        with self._workspace_selection_scope():
            owner = self._select_workspace(
                workspace,
                settings_manager=settings_manager,
                require_current_admission=None,
            )
            return owner.factory_for_session(manager) if owner is not None else None

    def prepare_resume_epoch(
        self,
        workspace: Path,
        *,
        require_current_admission: Callable[[], None],
        settings_manager: SettingsManager | None = None,
    ) -> str:
        """Select original workspace storage before admitting a Session lease."""
        return self._prepare_resume_epoch(
            workspace,
            require_current_admission=require_current_admission,
            settings_manager=settings_manager,
        )

    def resume_worker_effect_owner(self, workspace: Path) -> CodingResumeEffectOwnerV1:
        """Freeze the selected Product's original Worker C5 obligation."""

        from .product_worker_resume import prepare_coding_worker_resume_effect_owner

        if not isinstance(workspace, Path) or not workspace.is_absolute():
            raise ValueError("Coding Resume epoch workspace must be canonical")
        if workspace != workspace.resolve(strict=True):
            raise ValueError("Coding Resume epoch workspace must be canonical")
        with self._lock:
            owner = self._owners.get(workspace)
            if self._fenced or owner is None or not self._worker_candidates:
                raise RuntimeError("Coding Worker Product selection is unavailable")
            product = owner.runtime_owner.product_owner
            product.assert_root_gc_authority_current()
            return prepare_coding_worker_resume_effect_owner(
                product_id=product.policy.product_id,
                product_scope_id=product.policy.project_scope_id,
            )

    def product_owner_for_factory(
        self,
        factory: (
            PosixLocalWheelProductRuntimeFactory
            | WindowsLocalWheelProductRuntimeFactory
        ),
    ) -> PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner:
        """Recover only the Product owner that issued this exact Session factory."""

        if not isinstance(
            factory,
            (
                PosixLocalWheelProductRuntimeFactory,
                WindowsLocalWheelProductRuntimeFactory,
            ),
        ):
            raise TypeError("Coding Worker requires a Product Session factory")
        with self._lock:
            if self._fenced or not self._worker_candidates:
                raise RuntimeError("Coding Worker Product selection is unavailable")
            return require_product_owner_for_factory(
                factory,
                (
                    (owner.runtime_owner.product_owner, owner.epoch_runtime)
                    for owner in (*self._owners.values(), *self._retained_owners)
                ),
                owner_changed="Coding Worker Product Session owner changed",
            )

    @staticmethod
    def _external_bindings_current(
        owner: CodingFencedProductApplicationOwner,
        *,
        lifecycle: CodingPluginLifecycleStateLayout,
    ) -> bool:
        product = owner.runtime_owner.product_owner
        switch = owner.epoch_runtime.cutover_result.switch_receipt
        if switch is None:
            return False
        catalog = CodingExternalDataWheelCatalog(
            product.state_root / "external-data-wheel-bindings.jsonl",
            source_root=product.policy.source_root,
            store_id=owner.epoch_runtime.registry.store_id,
            namespace_id=switch.namespace_id,
            scope_id=lifecycle.scope_id,
        )
        expected_data, observed_data = project_local_source_policy_group(
            product.policy,
            (
                record.policy_binding(catalog.source_root)
                for record in catalog.records()
            ),
            trust_classes=frozenset({"local-data-only"}),
        )
        legacy_catalog = CodingLegacyLocalBindingCatalog(
            product.state_root / "legacy-local-bindings.jsonl",
            source_root=product.policy.source_root,
            store_id=owner.epoch_runtime.registry.store_id,
            namespace_id=switch.namespace_id,
            scope_id=lifecycle.scope_id,
            policy_revision=product.policy.policy_revision,
        )
        expected_legacy, observed_legacy = project_local_source_policy_group(
            product.policy,
            (
                record.to_policy_binding(legacy_catalog.source_root)
                for record in legacy_catalog.read_records()
            ),
            trust_classes=LEGACY_LOCAL_DATA_TRUST_CLASSES,
        )
        return expected_data == observed_data and expected_legacy == observed_legacy

    def _open_workspace_selection(
        self,
        workspace: Path,
        owner: CodingFencedProductApplicationOwner | None,
        *,
        settings_manager: SettingsManager | None,
        require_current_admission: Callable[[], None] | None,
    ) -> CodingFencedProductApplicationOwner | LegacyProductWorkspace:
        if owner is not None and self._external_bindings_current(
            owner,
            lifecycle=resolve_coding_plugin_lifecycle_state_layout(workspace),
        ):
            return owner

        lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
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
                if initial:
                    require_fresh_coding_product_inputs_without_writes(
                        lifecycle, workspace=workspace, settings_manager=settings_manager
                    )
                execute = (
                    _initialize_fresh_coding_product_for_session
                    if initial else _retry_fresh_bootstrap
                )
                execute(
                    lifecycle,
                    workspace=workspace,
                    settings_manager=settings_manager,
                    windows_candidate=self._windows_candidate,
                    require_current_admission=require_current_admission,
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

    return _capture_coding_worker_source(lifecycle, source=source, admission=admission)


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
        epoch_runtime, no_namespace="Coding Package Product root is not fenced"
    ) as (namespace_id, state_root, source_root):
        return (
            CodingExternalDataWheelCatalog
            if kind == "data"
            else CodingExternalDependencyWheelCatalog
        )(
            state_root
            / (
                "external-data-wheel-bindings.jsonl"
                if kind == "data"
                else "external-dependency-wheel-bindings.jsonl"
            ),
            source_root=source_root,
            store_id=epoch.store_id,
            namespace_id=namespace_id,
            scope_id=lifecycle.scope_id,
        ).capture(source, epoch_runtime=epoch_runtime)


def _capture_coding_worker_source(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    source: Path,
    admission: PackageProductLocalWorkerAdmissionV1,
) -> CodingExternalWorkerWheelBindingV1:
    """Capture one inert Worker candidate; the normal Session route stays dark."""

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    epoch_runtime = open_native_fenced_product_epoch(**epoch.fenced_runtime_open_kwargs())
    with fenced_source_catalog_scope(
        epoch_runtime, no_namespace="Coding Package Product root is not fenced"
    ) as (namespace_id, state_root, source_root):
        if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner):
            return CodingWindowsExternalWorkerWheelCatalog(
                epoch_runtime=epoch_runtime,
                state_root=state_root,
                source_root=source_root,
                store_id=epoch.store_id,
                namespace_id=namespace_id,
                scope_id=lifecycle.scope_id,
            ).capture(source, admission=admission)
        return CodingExternalWorkerWheelCatalog(
            state_root / "external-worker-wheel-bindings.jsonl",
            source_root=source_root,
            store_id=epoch.store_id,
            namespace_id=namespace_id,
            scope_id=lifecycle.scope_id,
        ).capture(source, admission=admission, epoch_runtime=epoch_runtime)


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
            _CODING_BUILTIN_PLUGIN_IDS,
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
            _CODING_BUILTIN_PLUGIN_IDS,
            policy=_CODING_BUILTIN_BOOTSTRAP_POLICY,
            disabled_ids={item.plugin_id for item in receipt.review.disabled_plugins},
        )
        return receipt


def _coding_settings_have_legacy_product_inputs(settings_manager: SettingsManager) -> bool:
    settings = settings_manager.get_settings()
    return bool(
        settings.disabled_plugins
        or settings.plugin_sources
        or settings.resource_roots
        or settings.package_roots
        or settings.package_sources
    )


def require_fresh_coding_product_inputs(
    lifecycle: CodingPluginLifecycleStateLayout,
    settings_manager: SettingsManager,
    *,
    roots_may_be_absent: bool = False,
) -> None:
    """Refuse to treat legacy settings or state as a fresh Product default."""

    if not isinstance(settings_manager, SettingsManager):
        raise TypeError("Coding settings manager is required")
    if _coding_settings_have_legacy_product_inputs(settings_manager):
        raise RuntimeError(
            "Coding pre-B workspace is unsupported; use a fresh workspace"
        )
    if type(roots_may_be_absent) is not bool:
        raise TypeError("Coding fresh Product root policy is invalid")
    if _legacy_state_requires_migration(lifecycle, skip_missing=roots_may_be_absent):
        raise RuntimeError(
            "Coding pre-B workspace is unsupported; use a fresh workspace"
        )


def require_fresh_coding_product_inputs_without_writes(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    settings_manager: SettingsManager | None = None,
) -> None:
    """Require empty input for an explicit fresh-only Product cutover."""

    if coding_product_inputs_need_compatibility(
        lifecycle,
        workspace=workspace,
        settings_manager=settings_manager,
    ):
        raise RuntimeError(
            "Coding pre-B workspace is unsupported; use a fresh workspace"
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
    if not isinstance(workspace, Path) or not workspace.is_absolute():
        raise ValueError("Coding workspace must be absolute")
    if _coding_product_settings_need_compatibility(
        workspace=workspace, settings_manager=settings_manager
    ):
        return True
    return _legacy_state_requires_migration(lifecycle, skip_missing=True)


def require_fresh_coding_product_settings_without_writes(
    *, workspace: Path, settings_manager: SettingsManager | None = None
) -> None:
    """Require fresh settings for an explicit fresh-only Product cutover."""

    if _coding_product_settings_need_compatibility(
        workspace=workspace,
        settings_manager=settings_manager,
    ):
        raise RuntimeError(
            "Coding pre-B workspace is unsupported; use a fresh workspace"
        )


def _coding_product_settings_need_compatibility(
    *,
    workspace: Path,
    settings_manager: SettingsManager | None,
) -> bool:
    if not isinstance(workspace, Path) or not workspace.is_absolute():
        raise ValueError("Coding workspace must be absolute")
    settings_paths = [
        default_global_settings_path(),
        default_project_settings_path(workspace),
    ]
    if settings_manager is not None:
        if not isinstance(settings_manager, SettingsManager):
            raise TypeError("Coding Product settings manager is invalid")
        if _coding_settings_have_legacy_product_inputs(settings_manager):
            return True
        settings_paths.extend(
            path
            for path in (
                settings_manager.global_settings_path,
                settings_manager.project_settings_path,
            )
            if path is not None
        )
    return coding_settings_have_pre_b_inputs_without_writes(
        *dict.fromkeys(settings_paths)
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


def _native_coding_fresh_route(windows_candidate: bool) -> bool:
    return (os.name == "posix" and sys.platform.startswith("linux")) or (
        os.name == "nt" and windows_candidate
    )


def _initialize_fresh_coding_product_for_session(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    settings_manager: SettingsManager | None,
    windows_candidate: bool = False,
    require_current_admission: Callable[[], None] | None = None,
) -> None:
    """Use the Product's offline fresh cutover before ordinary Session writes."""

    if not _native_coding_fresh_route(windows_candidate):
        raise RuntimeError(
            "Coding native automatic B Session route is not yet admitted"
        )
    if not workspace.is_dir():
        raise ValueError("Coding Product workspace must be an existing directory")
    cutover_settings = _fresh_coding_bootstrap_settings(
        lifecycle, workspace, settings_manager, initial=True,
        require_current_admission=require_current_admission,
    )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    namespace_id = _fresh_coding_product_namespace_id(epoch.store_id)
    # Import here because the cutover owner uses this module's Product bootstrap.
    from loushang.coding.package.pre_b_snapshot import (
        cutover_and_bootstrap_coding_package_product,
    )

    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        cutover_settings,
        workspace=workspace,
        namespace_id=namespace_id,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        windows_candidate=windows_candidate,
        require_current_admission=require_current_admission,
    )


def _fresh_coding_product_namespace_id(store_id: str) -> str:
    return sha256(
        b"loushang.coding-fresh-product-epoch/v1\0" + store_id.encode()
    ).hexdigest()


def _fresh_coding_builtin_bootstrap_completed(
    owner: CodingFencedProductApplicationOwner,
) -> bool:
    """Recognize a completed bootstrap even after later operator changes."""
    return product_bootstrap_completed(
        owner.runtime_owner.product_owner,
        _CODING_BUILTIN_PLUGIN_IDS,
        store_id=owner.epoch_runtime.registry.store_id,
        policy=_CODING_BUILTIN_BOOTSTRAP_POLICY,
    )


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
        source_member="coding-source-configuration.json",
        maximum_bytes=_LIFECYCLE_SNAPSHOT_MAX_BYTES,
        label="Coding",
    )
    if raw is None:
        return False
    source = json.loads(raw)
    classification = classify_coding_legacy_source_configuration(source)
    if classification.disabled_plugins or classification.configured_source_keys:
        return False
    scopes = source["scopes"]
    return not any(
        any(patch.values())
        for patch in (
            scopes["global"]["sourcePatch"],
            scopes["project"]["sourcePatch"],
        )
    )


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
    if (
        not isinstance(workspace, Path)
        or not workspace.is_absolute()
        or ".." in workspace.parts
        or workspace != workspace.resolve(strict=True)
    ):
        raise ValueError("Coding Product workspace is not canonical")
    scope_id = _workspace_scope_id(workspace)
    if lifecycle.scope_id != scope_id:
        raise ValueError("Coding Product workspace scope changed")
    if not isinstance(runtime_version, str) or not runtime_version:
        raise ValueError("Coding Product runtime version is required")
    if type(runtime_protocol_epoch) is not int or runtime_protocol_epoch < 1:
        raise ValueError("Coding Product runtime protocol epoch is invalid")
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if not matches_epoch_layout(epoch_runtime, epoch):
        raise ValueError("Coding Package Product workspace authority changed")
    state_root = epoch_runtime.prepare_product_state_root()
    if (
        state.state_root != state_root
        or not product_management_paths_match(
            state_root,
            gc_gate=state.gc_gate,
            desired_state=state.desired_state,
            management=state.management,
            gc_bindings=state.gc_bindings,
        )
        or state.worker_opt_in.path != state_root / "worker-opt-in.jsonl"
        or state.private_data_confirmation.path
        != state_root / "private-data-confirmations.jsonl"
        or state.private_data_deletion.path
        != state_root / "private-data-deletions.jsonl"
    ):
        raise ValueError("Coding Package Product state authority changed")
    switch = epoch_runtime.cutover_result.switch_receipt
    if switch is None:
        raise ValueError("Coding Package Product root is not fenced")
    source_root = epoch_runtime.prepare_product_source_root()
    artifact = (
        prepare_windows_coding_base_product_wheel(source_root)
        if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner)
        else prepare_posix_coding_base_product_wheel(source_root)
    )
    host_inputs = PosixLocalWheelProductHostInputs.current_host(
        max_transport_bytes=2 * 1024 * 1024
    )
    environment_fingerprint = host_inputs.environment.fingerprint
    capabilities = None
    if include_capabilities:
        capabilities = (
            prepare_windows_coding_capability_product_wheels(source_root)
            if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner)
            else prepare_posix_coding_capability_product_wheels(source_root)
        )
    policy = _bind_coding_builtin_wheel_policy(
        artifact,
        capabilities,
        scope_id=scope_id,
        environment_fingerprint=environment_fingerprint,
    )

    policy = _extend_coding_product_source_policy(
        policy,
        lifecycle,
        epoch_runtime,
        state_root=state_root,
        source_root=source_root,
        namespace_id=switch.namespace_id,
        include_worker_candidates=include_worker_candidates,
    )
    session_owner = bind_fenced_product_session_owner(
        epoch_runtime,
        workspace=workspace,
        state_root=state.state_root,
        plugin_store_root=(
            epoch.epoch_root(switch.namespace_id)
            if isinstance(epoch_runtime, PackageProductPosixFencedRuntimeOwner)
            else None
        ),
        policy=policy,
        host_inputs=host_inputs,
        root_store_identity=f"coding-product-root-store:{epoch.store_id}",
        dependency_store_identity=f"coding-product-dependency-store:{epoch.store_id}",
        recovery_identity=f"coding-product-recovery:{epoch.store_id}",
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


def _bind_coding_builtin_wheel_policy(
    base: CodingBaseProductWheelArtifactV1,
    capabilities: tuple[CodingCapabilityProductWheelArtifactV1, ...] | None,
    *,
    scope_id: str,
    environment_fingerprint: str,
) -> PackageProductLocalWheelPolicy:
    arguments = dict(
        project_scope_id=scope_id,
        resolution_environment_fingerprint=environment_fingerprint,
        policy_revision=CODING_PACKAGE_PRODUCT_POLICY_REVISION,
        quota_profile_revision="coding-product-package-quota:1",
        authority_id="coding-product-local-source",
    )
    if capabilities is None:
        return coding_base_product_local_wheel_policy(base, **arguments)
    return coding_builtin_product_local_wheel_policy(base, capabilities, **arguments)


class _SourceCatalogBinding(TypedDict):
    source_root: Path
    store_id: str
    namespace_id: str
    scope_id: str


def _extend_coding_product_source_policy(
    policy: PackageProductLocalWheelPolicy,
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner,
    *,
    state_root: Path,
    source_root: Path,
    namespace_id: str,
    include_worker_candidates: bool,
    read_only: bool = False,
) -> PackageProductLocalWheelPolicy:
    """Bind the same approved sources for preview and live Product selection."""

    catalog_binding = _SourceCatalogBinding(
        source_root=source_root,
        store_id=epoch_runtime.registry.store_id,
        namespace_id=namespace_id,
        scope_id=lifecycle.scope_id,
    )
    policy_revision = policy.policy_revision

    def read_legacy_acceptance(plugin_id: str):
        if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner):
            return None
        return reopen_coding_legacy_installed_local_acceptance(
            lifecycle, epoch_runtime, plugin_id=plugin_id, policy_revision=policy_revision
        )

    legacy = CodingLegacyLocalBindingCatalog(
        state_root / "legacy-local-bindings.jsonl",
        **catalog_binding,
        policy_revision=policy_revision,
        acceptance_reader=read_legacy_acceptance,
    )
    policy = legacy.read_extend_policy(policy) if read_only else legacy.extend_policy(policy)
    policy = CodingExternalDataWheelCatalog(
        state_root / "external-data-wheel-bindings.jsonl",
        **catalog_binding,
        read_only=read_only,
    ).extend_policy(policy)
    if isinstance(epoch_runtime, PackageProductPosixFencedRuntimeOwner):
        policy = CodingExternalDependencyWheelCatalog(
            state_root / "external-dependency-wheel-bindings.jsonl",
            **catalog_binding,
            read_only=read_only,
        ).extend_policy(policy)
    if include_worker_candidates:
        if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner):
            return CodingWindowsExternalWorkerWheelCatalog(
                epoch_runtime=epoch_runtime, state_root=state_root, **catalog_binding
            ).extend_policy(policy)
        return CodingExternalWorkerWheelCatalog(
            state_root / "external-worker-wheel-bindings.jsonl",
            **catalog_binding,
            read_only=read_only,
        ).extend_policy(policy)
    return policy


def _legacy_state_requires_migration(
    lifecycle: CodingPluginLifecycleStateLayout, *, skip_missing: bool
) -> bool:
    """Inspect the historical roots in lifecycle-before-package order."""

    for root, resolve_members in (
        (lifecycle.root, resolve_coding_lifecycle_pre_b_members),
        (lifecycle.package_root, resolve_coding_package_pre_b_store_members),
    ):
        if skip_missing:
            try:
                root.lstat()
            except FileNotFoundError:
                continue
        if any(resolve_members(lifecycle).domain_members().values()):
            return True
    return False


def _retry_fresh_bootstrap(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    settings_manager: SettingsManager | None,
    windows_candidate: bool,
    require_current_admission: Callable[[], None] | None,
) -> None:
    """Resume only a proven fresh first-B cutover; preserve adopted B state."""

    if not _native_coding_fresh_route(windows_candidate):
        return
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    _require_current_coding_product_admission(require_current_admission)
    if not inspect_fresh_product_epoch(
        epoch.fenced_runtime_open_kwargs(),
        windows=os.name == "nt",
        verify_snapshot=partial(is_coding_fresh_first_b_snapshot, lifecycle),
    ):
        return
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        windows_candidate=windows_candidate,
        require_current_admission=require_current_admission,
    )
    with closing(owner):
        if _fresh_coding_builtin_bootstrap_completed(owner):
            return
    bootstrap_coding_builtin_product_plugins(
        lifecycle,
        _fresh_coding_bootstrap_settings(
            lifecycle, workspace, settings_manager, initial=False,
            require_current_admission=require_current_admission,
        ),
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        windows_candidate=windows_candidate,
        require_current_admission=require_current_admission,
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
