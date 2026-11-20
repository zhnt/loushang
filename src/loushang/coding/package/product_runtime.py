"""Coding Session selection over compatible and fenced Plugin storage owners."""

from __future__ import annotations

import inspect
import json as json
import os as os
import sys as sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from importlib.metadata import version as version
from pathlib import Path
from threading import Lock, RLock
from typing import cast

from loushang.coding.harness.package_product import application_runtime as _programs
from loushang.coding.harness.package_product import source_admission as _source_programs
from loushang.coding.harness.package_product import startup as _lifecycle_programs
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycleStateLayout,
)
from loushang.coding.plugin_manager.lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout as resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.resume.activation_attempt_v2 import CodingResumeEffectOwnerV1
from loushang.coding.session.manager import SessionManager
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product._plugin_bootstrap import (
    _PluginBootstrapPolicy,
    bootstrap_product_plugin,
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
    _repair_ordinary_posix_runtime_leases,
    _repair_ordinary_windows_runtime_leases,
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
from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
    PackageEpochRuntimeLeaseRegistryError,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
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

_CODING_BUILTIN_BOOTSTRAP_POLICY = _PluginBootstrapPolicy(
    product_id="coding",
    operation_id_prefix="coding-builtin-bootstrap:",
    enable_id_prefix="coding-builtin-bootstrap-enable:",
    error_prefix="Coding builtin Product bootstrap",
)


_RUNTIME_PROGRAM_VALUES = {
    "value_001": "Coding Package lifecycle layout is required",
    "value_002": "Coding Package Product epoch owner is required",
    "value_003": "Coding Package Product workspace authority changed",
    "value_004": "gc-reservations.jsonl",
    "value_005": "desired-state.jsonl",
    "value_006": "gc-bindings.jsonl",
    "value_007": "worker-opt-in.jsonl",
    "value_008": "private-data-confirmations.jsonl",
    "value_009": "management-operations.jsonl",
    "value_010": "Coding Worker candidate selection must be explicit",
    "value_011": "Coding Windows Product candidate selection must be explicit",
    "value_012": "Coding Windows Product Session route is not yet admitted",
    "value_013": "Coding Product epoch cleanup also failed",
    "value_014": "coding-product-root-store:",
    "value_015": "coding-product-dependency-store:",
    "value_016": "coding-product-recovery:",
    "value_017": "Coding Package Product state owners are required",
    "value_018": "Coding Product workspace is not canonical",
    "value_019": "Coding Product workspace scope changed",
    "value_020": "Coding Product runtime version is required",
    "value_021": "Coding Product runtime protocol epoch is invalid",
    "value_022": "Coding Package Product state authority changed",
    "value_023": "Coding Package Product root is not fenced",
    "value_024": "coding-product-package-quota:1",
    "value_025": "coding-product-local-source",
    "value_026": "management-operations.jsonl.retirement-intents",
    "value_027": "management-operations.jsonl.retirement-sets",
    "value_028": "private-data-deletions.jsonl",
    "value_029": "product:coding",
    "value_030": "coding-product-desired-policy:1",
    "value_031": "legacy-local-bindings.jsonl",
    "value_032": "external-data-wheel-bindings.jsonl",
    "value_033": "external-dependency-wheel-bindings.jsonl",
    "value_034": "external-worker-wheel-bindings.jsonl",
    "value_035": "Coding Product workspace selection is in progress",
    "value_036": "Coding Product application is closing",
    "value_037": "Coding Resume requires a canonical absolute workspace",
    "value_038": "Coding Resume requires a synchronous current owner check",
    "value_039": "Coding Resume owner check must return None",
    "value_040": "Coding native B Session route is not yet admitted",
    "value_041": "epoch.jsonl",
    "value_042": "Coding Resume epoch workspace must be canonical",
    "value_043": "Coding Resume epoch is unavailable",
    "value_044": "Coding Resume epoch dependency exceeds its byte budget",
    "value_045": "Coding Resume epoch changed",
    "value_046": "Coding Resume storage epoch changed",
    "value_047": "Coding Worker requires a Product Session factory",
    "value_048": "Coding Worker Product selection is unavailable",
    "value_049": "Coding Worker Product Session owner changed",
    "distribution_name": "loushang",
}

_RUNTIME_PROGRAM_BYTES = {
    "value_001": b"loushang.coding-continuity-workspace/v1\x00",
    "value_002": b"loushang.coding.resume-epoch/v1\x00",
}


_LIFECYCLE_SNAPSHOT_MAX_BYTES = 4 * 1024 * 1024


_LIFECYCLE_PROGRAM_VALUES = {
    "value_001": "coding.base",
    "value_002": "coding.lsp.default",
    "value_003": "coding.arch.default",
    "value_004": "Coding native automatic B Session route is not yet admitted",
    "value_005": "Coding Product workspace must be an existing directory",
    "value_006": "Coding fresh Product snapshot owner is invalid",
    "value_007": "Coding Package Product workspace authority changed",
    "value_008": "coding-source-configuration.json",
    "value_009": "Coding fresh Product snapshot is incomplete",
    "value_010": "Coding fresh Product snapshot is unavailable",
    "distribution_name": "loushang",
}


_SOURCE_ADMISSION_PROGRAM_VALUES = {
    "value_001": "Coding Package Product root is not fenced",
    "value_002": "external-data-wheel-bindings.jsonl",
    "value_003": "external-dependency-wheel-bindings.jsonl",
    "value_004": "external-worker-wheel-bindings.jsonl",
}


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

    if check is None:
        return
    if not callable(check) or inspect.iscoroutinefunction(check):
        raise TypeError("Coding Product requires a synchronous current admission check")
    result = cast(Callable[[], object], check)()
    if result is not None:
        if inspect.iscoroutine(result):
            result.close()
        raise TypeError("Coding Product admission check must return None")


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

    return _programs.open_product_state(
        lifecycle,
        epoch_runtime,
        before_recovery=before_recovery,
        require_current_admission=require_current_admission,
    )


@dataclass(frozen=True, slots=True)
class CodingPosixLocalWheelProductRuntimeOwner:
    """Select the exact Coding Session for a fenced Product owner."""

    product_owner: (
        PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(
                self.product_owner,
                (
                    PosixLocalWheelProductSessionOwner,
                    WindowsLocalWheelProductSessionOwner,
                ),
            )
            or self.product_owner.policy.product_id != "coding"
        ):
            raise ValueError("Coding Package Product owner is required")

    def factory_for_session(
        self, manager: SessionManager
    ) -> PosixLocalWheelProductRuntimeFactory | WindowsLocalWheelProductRuntimeFactory:
        """Bind a live Session to one runtime lease without a legacy route."""

        if not isinstance(manager, SessionManager):
            raise TypeError("Coding Product Session manager is required")
        session_id = manager.get_header().conversation_id
        return self.product_owner.factory_for_session(
            session_id=session_id,
            cwd=Path(manager.get_cwd()),
            runtime_id="coding-session:" + sha256(session_id.encode()).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class CodingFencedProductApplicationOwner:
    """Retain one B epoch owner for the lifetime of a Coding application."""

    epoch_runtime: (
        PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner
    )
    runtime_owner: CodingPosixLocalWheelProductRuntimeOwner

    def __post_init__(self) -> None:
        if self.runtime_owner.product_owner.epoch_runtime is not self.epoch_runtime:
            raise ValueError("Coding Product application epoch owner changed")

    def factory_for_session(
        self, manager: SessionManager
    ) -> PosixLocalWheelProductRuntimeFactory | WindowsLocalWheelProductRuntimeFactory:
        try:
            return self.runtime_owner.factory_for_session(manager)
        except PackageEpochRuntimeLeaseRegistryError as error:
            if error.code != "package_epoch_lease_orphaned":
                raise
            _repair_ordinary_coding_orphan_runtime_leases(self)
            return self.runtime_owner.factory_for_session(manager)

    def close(self) -> None:
        self.epoch_runtime.close()


def _repair_ordinary_coding_orphan_runtime_leases(
    owner: CodingFencedProductApplicationOwner,
) -> None:
    """Recover dead ordinary Sessions only when no Worker authority exists."""

    product = owner.runtime_owner.product_owner
    if isinstance(product, WindowsLocalWheelProductSessionOwner):
        _repair_windows_ordinary_coding_orphan_runtime_leases(owner, product)
        return
    if not isinstance(product, PosixLocalWheelProductSessionOwner):
        raise RuntimeError("Coding ordinary orphan recovery requires POSIX Product")
    _repair_ordinary_posix_runtime_leases(
        product,
        owner.epoch_runtime,
        runtime_id_prefix="coding-session:",
        error_prefix="Coding",
    )


def _repair_windows_ordinary_coding_orphan_runtime_leases(
    owner: CodingFencedProductApplicationOwner,
    product: WindowsLocalWheelProductSessionOwner,
) -> None:
    """Recheck ordinary-only evidence under the Windows orphan and GC locks."""
    _repair_ordinary_windows_runtime_leases(
        product,
        owner.epoch_runtime,
        runtime_id_prefix="coding-session:",
        error_prefix="Coding",
    )


class CodingFencedProductApplicationSelection:
    """Preserve existing storage; select B for fresh or already fenced workspaces."""

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
        self._owners: dict[Path, CodingFencedProductApplicationOwner] = {}
        self._legacy_workspaces: dict[Path, CodingPluginLifecycleStateLayout] = {}
        self._retained_owners: list[CodingFencedProductApplicationOwner] = []
        self._lock = RLock()
        self._selection_in_progress = False
        self._fenced = False

    @contextmanager
    def _workspace_selection_scope(self) -> Iterator[None]:
        # Admission callbacks may observe this original owner while selecting.
        # Reentrant reads are safe; nested selection or disposal would change
        # the owner underneath the admitted operation.
        with _programs.workspace_selection_scope(self) as borrowed:
            yield borrowed

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
        # The legacy Session API permits a not-yet-created cwd. Use the same
        # canonical workspace identity as its lifecycle layout; a present B
        # fence still requires the Product owner to validate the real root.
        workspace = Path(manager.get_cwd()).resolve(strict=False)
        with self._workspace_selection_scope():
            owner = self._select_workspace_unlocked(
                workspace, settings_manager=settings_manager
            )
            return owner.factory_for_session(manager) if owner is not None else None

    def prepare_resume_epoch(
        self,
        workspace: Path,
        *,
        require_current_admission: Callable[[], None],
        settings_manager: SettingsManager | None = None,
    ) -> str:
        """Select original workspace storage without creating a Session lease.

        This may retain compatible storage or initialize/recover Product state.
        It is an admitted activation step, never a history read or background
        Plan operation.
        Caller authority and effect settlement remain original-owner inputs.
        """

        return _programs.prepare_resume_epoch(
            self,
            workspace,
            require_current_admission=require_current_admission,
            settings_manager=settings_manager,
        )

    def _select_workspace_unlocked(
        self,
        workspace: Path,
        *,
        settings_manager: SettingsManager | None,
        require_current_admission: Callable[[], None] | None = None,
    ) -> CodingFencedProductApplicationOwner | None:
        """Use the original selection/recovery path while its lock is held."""

        return _programs.select_workspace(
            self,
            workspace,
            settings_manager=settings_manager,
            require_current_admission=require_current_admission,
        )

    def resume_epoch_fingerprint(self, workspace: Path) -> str:
        """Observe selected native or compatible storage without activating it.

        This is a data dependency, not content proof or effect settlement. An
        unselected workspace remains unavailable rather than opening a factory.
        """

        return _programs.resume_epoch_fingerprint(self, workspace)

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

        return _programs.product_owner_for_factory(self, factory)

    @staticmethod
    def _external_bindings_current(
        owner: CodingFencedProductApplicationOwner,
        *,
        lifecycle: CodingPluginLifecycleStateLayout,
    ) -> bool:
        return _programs.external_bindings_current(owner, lifecycle=lifecycle)

    def fence(self) -> None:
        with self._lock:
            self._fenced = True

    def close(self) -> None:
        return _programs.close_selection(self)


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

    return _programs.open_application(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        worker_candidates=worker_candidates,
        windows_candidate=windows_candidate,
        require_current_admission=require_current_admission,
    )


def admit_coding_external_data_wheel(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    source: Path,
) -> CodingExternalDataWheelBindingV1:
    """Capture one local data Wheel under the current fenced Product Source root."""

    return cast(
        "CodingExternalDataWheelBindingV1",
        _source_programs.capture_inert_source(lifecycle, source=source, kind="data"),
    )


def admit_coding_external_dependency_wheel(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    source: Path,
) -> CodingExternalDependencyWheelBindingV1:
    """Pin inert dependency bytes; no Coding Plugin profile may use them yet."""

    return cast(
        "CodingExternalDependencyWheelBindingV1",
        _source_programs.capture_inert_source(
            lifecycle, source=source, kind="dependency"
        ),
    )


def admit_coding_external_worker_wheel(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    source: Path,
    admission: PackageProductLocalWorkerAdmissionV1,
) -> CodingExternalWorkerWheelBindingV1:
    """Capture one inert Worker candidate; the normal Session route stays dark."""

    return _source_programs.capture_worker_source(
        lifecycle, source=source, admission=admission
    )


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

    return _lifecycle_programs.bootstrap_builtin_plugins(
        lifecycle,
        settings_manager,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        windows_candidate=windows_candidate,
        require_current_admission=require_current_admission,
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

    return _lifecycle_programs.bootstrap_accepted_disabled_plugins(
        lifecycle,
        settings_manager,
        workspace=workspace,
        accepted_review_id=accepted_review_id,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
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
    settings = settings_manager.get_settings()
    if (
        settings.disabled_plugins
        or settings.plugin_sources
        or settings.resource_roots
        or settings.package_roots
        or settings.package_sources
    ):
        raise RuntimeError(
            "Coding pre-B workspace is unsupported; use a fresh workspace"
        )
    if type(roots_may_be_absent) is not bool:
        raise TypeError("Coding fresh Product root policy is invalid")
    for root, resolver in (
        (lifecycle.root, resolve_coding_lifecycle_pre_b_members),
        (lifecycle.package_root, resolve_coding_package_pre_b_store_members),
    ):
        if roots_may_be_absent:
            try:
                root.lstat()
            except FileNotFoundError:
                continue
        members = resolver(lifecycle)
        if any(members.domain_members().values()):
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
    for root, resolver in (
        (lifecycle.root, resolve_coding_lifecycle_pre_b_members),
        (lifecycle.package_root, resolve_coding_package_pre_b_store_members),
    ):
        try:
            root.lstat()
        except FileNotFoundError:
            continue
        if any(resolver(lifecycle).domain_members().values()):
            return True
    return False


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
        effective = settings_manager.get_settings()
        if any(
            (
                effective.disabled_plugins,
                effective.plugin_sources,
                effective.resource_roots,
                effective.package_roots,
                effective.package_sources,
            )
        ):
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


def _initialize_fresh_coding_product_for_session(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    settings_manager: SettingsManager | None,
    windows_candidate: bool = False,
    require_current_admission: Callable[[], None] | None = None,
) -> None:
    """Use the Product's offline fresh cutover before ordinary Session writes."""

    return _lifecycle_programs.initialize_fresh_product(
        lifecycle,
        workspace=workspace,
        settings_manager=settings_manager,
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
        ("coding.base", "coding.lsp.default", "coding.arch.default"),
        store_id=owner.epoch_runtime.registry.store_id,
        policy=_CODING_BUILTIN_BOOTSTRAP_POLICY,
    )


def is_coding_fresh_first_b_snapshot(
    lifecycle: CodingPluginLifecycleStateLayout,
    runtime: PackageProductPosixFencedRuntimeOwner
    | PackageProductWindowsFencedRuntimeOwner,
) -> bool:
    """Read the fenced first-B snapshot before retrying fresh builtin defaults."""

    return _lifecycle_programs.is_fresh_snapshot(lifecycle, runtime)


def _retry_fresh_coding_product_bootstrap_for_session(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    settings_manager: SettingsManager | None,
    windows_candidate: bool = False,
    require_current_admission: Callable[[], None] | None = None,
) -> None:
    """Resume only a proven fresh first-B cutover; preserve adopted B state."""

    return _lifecycle_programs.retry_fresh_bootstrap(
        lifecycle,
        workspace=workspace,
        settings_manager=settings_manager,
        windows_candidate=windows_candidate,
        require_current_admission=require_current_admission,
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

    return _open_coding_product_runtime_owner(
        lifecycle,
        epoch_runtime,
        state,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        include_capabilities=False,
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

    return _open_coding_product_runtime_owner(
        lifecycle,
        epoch_runtime,
        state,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        include_capabilities=True,
        include_worker_candidates=worker_candidates,
    )


def _open_coding_product_runtime_owner(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: (
        PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner
    ),
    state: CodingPackageProductStateOwners,
    *,
    workspace: Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
    include_capabilities: bool,
    include_worker_candidates: bool = False,
) -> CodingPosixLocalWheelProductRuntimeOwner:
    return _programs.open_runtime(
        lifecycle,
        epoch_runtime,
        state,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        include_capabilities=include_capabilities,
        include_worker_candidates=include_worker_candidates,
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
