"""Coding Session selection over an already fenced Package Product."""

from __future__ import annotations

import json
import os
import secrets
import sys
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from threading import Lock

from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductHostInputs,
    PosixLocalWheelProductRuntimeFactory,
    PosixLocalWheelProductSessionOwner,
    WindowsLocalWheelProductRuntimeFactory,
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.package_gc_binding import (
    PluginPackageGcBindingJournal,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.private_data_confirmation import (
    PluginPrivateDataConfirmationJournal,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginDesiredStateTransitionV1,
    PluginInstallationKeyV1,
)
from loushang.harness.plugin_management.service import PluginManagementService
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
    PackageEpochRuntimeLeaseRegistryError,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleIntentV1,
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

from ._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from .control.settings_store import (
    default_global_settings_path,
    default_project_settings_path,
)
from .package_builtin_wheel import (
    coding_base_product_local_wheel_policy,
    coding_builtin_product_local_wheel_policy,
    prepare_posix_coding_base_product_wheel,
    prepare_posix_coding_capability_product_wheels,
    prepare_windows_coding_base_product_wheel,
    prepare_windows_coding_capability_product_wheels,
)
from .package_epoch_layout import (
    resolve_coding_lifecycle_pre_b_members,
    resolve_coding_package_epoch_layout,
    resolve_coding_package_pre_b_store_members,
)
from .package_external_data_wheel import (
    CodingExternalDataWheelBindingV1,
    CodingExternalDataWheelCatalog,
)
from .package_external_dependency_wheel import (
    CodingExternalDependencyWheelBindingV1,
    CodingExternalDependencyWheelCatalog,
)
from .package_external_worker_wheel import (
    CodingExternalWorkerWheelBindingV1,
    CodingExternalWorkerWheelCatalog,
    CodingWindowsExternalWorkerWheelCatalog,
)
from .package_legacy_binding_catalog import CodingLegacyLocalBindingCatalog
from .package_legacy_classification import classify_coding_legacy_source_configuration
from .package_legacy_data_trust import LEGACY_LOCAL_DATA_TRUST_CLASSES
from .package_legacy_disabled_acceptance import (
    CodingLegacyDisabledOnlyAcceptanceV1,
    accept_coding_first_b_disabled_only,
)
from .package_legacy_local_acceptance import (
    reopen_coding_legacy_installed_local_acceptance,
)
from .package_legacy_snapshot_member import (
    list_coding_first_b_snapshot_domain_members,
    read_coding_first_b_snapshot_member,
)
from .package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionJournal,
)
from .package_product_backup_types import ensure_coding_product_backup_types
from .package_product_worker_opt_in import CodingWorkerOptInJournal
from .package_source_snapshot import require_coding_fresh_settings_without_writes
from .session_manager import SessionManager

CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH = 2
CODING_PACKAGE_PRODUCT_POLICY_REVISION = "coding-product-package-policy:1"


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


def open_coding_package_product_state(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: (
        PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner
    ),
    *,
    before_recovery: Callable[[], None] | None = None,
) -> CodingPackageProductStateOwners:
    """Open durable Product owners only for this workspace's fenced Store."""

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
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if (
        epoch_runtime.registry.store_id != epoch.store_id
        or epoch_runtime.control_root != epoch.control_root
    ):
        raise ValueError("Coding Package Product workspace authority changed")
    if before_recovery is not None:
        before_recovery()
    state_root = epoch_runtime.prepare_product_state_root()
    if before_recovery is not None:
        before_recovery()
    state_metadata = state_root.lstat()
    epoch_runtime.assert_current()
    gate = PluginPackageGcReservationJournal(
        state_root / "gc-reservations.jsonl",
        parent_identity=(state_metadata.st_dev, state_metadata.st_ino),
    )
    ensure_coding_product_backup_types(
        state_root=state_root,
        scope_id=lifecycle.scope_id,
        epoch_runtime=epoch_runtime,
        gc_gate=gate,
    )
    desired = PluginDesiredStateLedger(state_root / "desired-state.jsonl", gc_gate=gate)
    management = PluginManagementService(
        desired_state=desired,
        operation_journal_path=state_root / "management-operations.jsonl",
    )
    management.recover(before_replay=before_recovery)
    bindings = PluginPackageGcBindingJournal(state_root / "gc-bindings.jsonl")
    worker_opt_in = CodingWorkerOptInJournal(
        state_root / "worker-opt-in.jsonl",
        scope_id=lifecycle.scope_id,
        gc_gate=gate,
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
    if not isinstance(product, PosixLocalWheelProductSessionOwner):
        raise RuntimeError("Coding ordinary orphan recovery requires POSIX Product")
    with product.gc_gate.guard():
        product.assert_root_gc_authority_current()
        root_fd = os.open(
            product.state_root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        try:
            root_stat = os.fstat(root_fd)
            product.assert_root_gc_authority_current()
            current_stat = product.state_root.stat()
            if (root_stat.st_dev, root_stat.st_ino) != (
                current_stat.st_dev,
                current_stat.st_ino,
            ):
                raise RuntimeError("Coding Product state root changed")
            if any("worker" in name.casefold() for name in os.listdir(root_fd)):
                raise RuntimeError("Coding Worker recovery requires explicit review")
        finally:
            os.close(root_fd)
        if any(
            binding.source_trust_class == "local-worker-candidate"
            for binding in product.policy.bindings
        ):
            raise RuntimeError("Coding Worker recovery requires explicit review")
        registry = owner.epoch_runtime.registry
        fence = owner.epoch_runtime.cutover_result.fence
        if fence is None:
            raise RuntimeError("Coding Product epoch fence is unavailable")
        for lease in registry.review_orphans(store_id=registry.store_id):
            if (
                not lease.runtime_id.startswith("coding-session:")
                or lease.runtime_epoch != fence.epoch
                or lease.store_root_identity != fence.fenced_root_identity
            ):
                raise RuntimeError("Coding orphan runtime requires explicit review")
            owner.epoch_runtime.assert_current()
            try:
                registry.repair_orphan(lease.lease_id)
            except PackageEpochRuntimeLeaseRegistryError as error:
                if error.code != "package_epoch_lease_absent":
                    raise
        owner.epoch_runtime.assert_current()


class CodingFencedProductApplicationSelection:
    """Select one B owner per workspace and retain it through application close."""

    def __init__(
        self,
        *,
        windows_candidate: bool = False,
        worker_candidates: bool = False,
    ) -> None:
        if type(windows_candidate) is not bool:
            raise TypeError("Coding Windows Product candidate selection must be explicit")
        if type(worker_candidates) is not bool:
            raise TypeError("Coding Worker candidate selection must be explicit")
        self._windows_candidate = windows_candidate
        self._worker_candidates = worker_candidates
        self._owners: dict[Path, CodingFencedProductApplicationOwner] = {}
        self._retained_owners: list[CodingFencedProductApplicationOwner] = []
        self._lock = Lock()
        self._fenced = False

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
        with self._lock:
            if self._fenced:
                raise RuntimeError("Coding Product application is closing")
            owner = self._owners.get(workspace)
            if owner is None:
                lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
                epoch = resolve_coding_package_epoch_layout(lifecycle)
                unadmitted_platform = (
                    os.name == "posix" and not sys.platform.startswith("linux")
                ) or (os.name == "nt" and not self._windows_candidate)
                try:
                    (epoch.control_root / "epoch.jsonl").lstat()
                except FileNotFoundError:
                    # Platforms without an admitted default Product route keep
                    # their existing Session route.
                    if unadmitted_platform:
                        require_fresh_coding_product_settings_without_writes(
                            workspace=workspace,
                            settings_manager=settings_manager,
                        )
                        return None
                    # A Linux fresh workspace enters B before any ordinary
                    # Session can prepare a legacy Plugin writer. Native
                    # cutover owns the cross-process fence.
                    require_fresh_coding_product_inputs_without_writes(
                        lifecycle,
                        workspace=workspace,
                        settings_manager=settings_manager,
                    )
                    _initialize_fresh_coding_product_for_session(
                        lifecycle,
                        workspace=workspace,
                        settings_manager=settings_manager,
                        windows_candidate=self._windows_candidate,
                    )
                else:
                    if unadmitted_platform:
                        PackageEpochFenceJournal(
                            epoch.control_root / "epoch.jsonl", read_only=True
                        ).current(epoch.store_id)
                        raise RuntimeError(
                            "Coding native B Session route is not yet admitted"
                        )
                    _retry_fresh_coding_product_bootstrap_for_session(
                        lifecycle,
                        workspace=workspace,
                        settings_manager=settings_manager,
                        windows_candidate=self._windows_candidate,
                    )
                owner = open_coding_fenced_product_application_owner(
                    lifecycle,
                    workspace=workspace,
                    runtime_version=version("loushang"),
                    runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
                    worker_candidates=self._worker_candidates,
                    windows_candidate=self._windows_candidate,
                )
                self._owners[workspace] = owner
            elif not self._external_bindings_current(
                owner, lifecycle=resolve_coding_plugin_lifecycle_state_layout(workspace)
            ):
                lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
                replacement = open_coding_fenced_product_application_owner(
                    lifecycle,
                    workspace=workspace,
                    runtime_version=version("loushang"),
                    runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
                    worker_candidates=self._worker_candidates,
                    windows_candidate=self._windows_candidate,
                )
                self._retained_owners.append(owner)
                owner = replacement
                self._owners[workspace] = owner
            return owner.factory_for_session(manager)

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
            matching: list[
                PosixLocalWheelProductSessionOwner
                | WindowsLocalWheelProductSessionOwner
            ] = []
            for application in (*self._owners.values(), *self._retained_owners):
                product = application.runtime_owner.product_owner
                if isinstance(factory, PosixLocalWheelProductRuntimeFactory):
                    if (
                        not isinstance(product, PosixLocalWheelProductSessionOwner)
                        or factory.state_root != product.state_root
                    ):
                        continue
                elif (
                    not isinstance(product, WindowsLocalWheelProductSessionOwner)
                    or factory.epoch_runtime is not product.epoch_runtime
                    or factory.policy is not product.policy
                    or factory.expected_cwd != product.workspace
                ):
                    continue
                if (
                    factory.management is product.management
                    and factory.desired_state is product.desired_state
                    and factory.gc_bindings is product.gc_bindings
                    and factory.gc_gate is product.gc_gate
                    and factory.runtime_lease.registry
                    is application.epoch_runtime.registry
                ):
                    matching.append(product)
            if len(matching) != 1:
                raise RuntimeError("Coding Worker Product Session owner changed")
            factory.assert_workspace_current()
            matching[0].assert_root_gc_authority_current()
            return matching[0]

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
        expected_data = tuple(
            sorted(
                (
                    record.policy_binding(catalog.source_root)
                    for record in catalog.records()
                ),
                key=lambda item: item.source_identity,
            )
        )
        observed_data = tuple(
            item
            for item in product.policy.bindings
            if item.source_trust_class == "local-data-only"
        )
        legacy_catalog = CodingLegacyLocalBindingCatalog(
            product.state_root / "legacy-local-bindings.jsonl",
            source_root=product.policy.source_root,
            store_id=owner.epoch_runtime.registry.store_id,
            namespace_id=switch.namespace_id,
            scope_id=lifecycle.scope_id,
            policy_revision=product.policy.policy_revision,
        )
        expected_legacy = tuple(
            sorted(
                (
                    record.to_policy_binding(legacy_catalog.source_root)
                    for record in legacy_catalog.read_records()
                ),
                key=lambda item: item.source_identity,
            )
        )
        observed_legacy = tuple(
            item
            for item in product.policy.bindings
            if item.source_trust_class in LEGACY_LOCAL_DATA_TRUST_CLASSES
        )
        return expected_data == observed_data and expected_legacy == observed_legacy

    def fence(self) -> None:
        with self._lock:
            self._fenced = True

    def close(self) -> None:
        with self._lock:
            self._fenced = True
            failures: list[BaseException] = []
            for workspace, owner in tuple(self._owners.items()):
                try:
                    owner.close()
                except BaseException as error:
                    failures.append(error)
                else:
                    del self._owners[workspace]
            for owner in tuple(self._retained_owners):
                try:
                    owner.close()
                except BaseException as error:
                    failures.append(error)
                else:
                    self._retained_owners.remove(owner)
            if failures:
                raise failures[0]


@dataclass(slots=True)
class _CodingSessionProductRuntimeRelease:
    """Keep the original lease identity visible through Session disposal."""

    release: Callable[[], None]
    selection: CodingFencedProductApplicationSelection

    @property
    def registry(self) -> object:
        lease = getattr(self.release, "__self__", None)
        return getattr(lease, "registry", None)

    def dispose(self) -> None:
        self.release()
        self.selection.close()


@dataclass(slots=True)
class CodingSessionOwnedProductRuntimeFactory:
    """Transfer a one-Session Product owner to the runtime binding's disposal."""

    factory: (
        PosixLocalWheelProductRuntimeFactory | WindowsLocalWheelProductRuntimeFactory
    )
    selection: CodingFencedProductApplicationSelection
    _binding_issued: bool = False
    _lock: Lock = field(default_factory=Lock, repr=False)

    def product_owner_for_worker(
        self,
    ) -> PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner:
        owner = self.selection.product_owner_for_factory(self.factory)
        if not isinstance(
            owner,
            (PosixLocalWheelProductSessionOwner, WindowsLocalWheelProductSessionOwner),
        ):
            raise TypeError("Coding Worker Product Session owner changed platform")
        return owner

    def create(
        self, request: PackageProductRuntimeRequestV1
    ) -> PackageProductRuntimeBindingV1:
        with self._lock:
            if self._binding_issued:
                raise ValueError("Coding Product Session factory already used")
            binding = self.factory.create(request)
            try:
                release = binding.on_dispose
                if release is None:
                    raise ValueError("Coding Product runtime release is missing")
                owned = replace(binding, on_dispose=self._dispose_binding(release))
            except BaseException as error:
                try:
                    binding.dispose_runtime()
                    self.selection.close()
                except BaseException:
                    error.add_note("Coding Product Session owner cleanup also failed")
                raise
            self._binding_issued = True
            return owned

    def dispose_unbound_runtime(self) -> None:
        with self._lock:
            if self._binding_issued:
                return
            self.factory.dispose_unbound_runtime()
            self.selection.close()

    def _dispose_binding(self, release: Callable[[], None]) -> Callable[[], None]:
        return _CodingSessionProductRuntimeRelease(release, self.selection).dispose


@dataclass(frozen=True, slots=True)
class CodingApplicationWorkerProductRuntimeFactory:
    """Expose one app-owned Product factory to an explicit Worker Session."""

    factory: (
        PosixLocalWheelProductRuntimeFactory | WindowsLocalWheelProductRuntimeFactory
    )
    selection: CodingFencedProductApplicationSelection

    def product_owner_for_worker(
        self,
    ) -> PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner:
        owner = self.selection.product_owner_for_factory(self.factory)
        if not isinstance(
            owner,
            (PosixLocalWheelProductSessionOwner, WindowsLocalWheelProductSessionOwner),
        ):
            raise TypeError("Coding Worker Product Session owner changed platform")
        return owner

    def create(
        self, request: PackageProductRuntimeRequestV1
    ) -> PackageProductRuntimeBindingV1:
        return self.factory.create(request)

    def dispose_unbound_runtime(self) -> None:
        self.factory.dispose_unbound_runtime()


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
) -> CodingFencedProductApplicationOwner:
    """Reopen the exact B fence and bind all first-party Coding Packages."""

    if type(worker_candidates) is not bool:
        raise TypeError("Coding Worker candidate selection must be explicit")
    if type(windows_candidate) is not bool:
        raise TypeError("Coding Windows Product candidate selection must be explicit")
    if os.name == "nt" and not windows_candidate:
        raise RuntimeError("Coding Windows Product Session route is not yet admitted")
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    epoch_owner_type = (
        PackageProductWindowsFencedRuntimeOwner
        if os.name == "nt"
        else PackageProductPosixFencedRuntimeOwner
    )
    epoch_runtime = epoch_owner_type.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        state = open_coding_package_product_state(lifecycle, epoch_runtime)
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
    except BaseException as error:
        try:
            epoch_runtime.close()
        except BaseException:
            error.add_note("Coding Product epoch cleanup also failed")
        raise


def admit_coding_external_data_wheel(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    source: Path,
) -> CodingExternalDataWheelBindingV1:
    """Capture one local data Wheel under the current fenced Product Source root."""

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    epoch_runtime = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        switch = epoch_runtime.cutover_result.switch_receipt
        if switch is None:
            raise ValueError("Coding Package Product root is not fenced")
        return CodingExternalDataWheelCatalog(
            epoch_runtime.prepare_product_state_root()
            / "external-data-wheel-bindings.jsonl",
            source_root=epoch_runtime.prepare_product_source_root(),
            store_id=epoch.store_id,
            namespace_id=switch.namespace_id,
            scope_id=lifecycle.scope_id,
        ).capture(source, epoch_runtime=epoch_runtime)
    finally:
        epoch_runtime.close()


def admit_coding_external_dependency_wheel(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    source: Path,
) -> CodingExternalDependencyWheelBindingV1:
    """Pin inert dependency bytes; no Coding Plugin profile may use them yet."""

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    epoch_runtime = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        switch = epoch_runtime.cutover_result.switch_receipt
        if switch is None:
            raise ValueError("Coding Package Product root is not fenced")
        return CodingExternalDependencyWheelCatalog(
            epoch_runtime.prepare_product_state_root()
            / "external-dependency-wheel-bindings.jsonl",
            source_root=epoch_runtime.prepare_product_source_root(),
            store_id=epoch.store_id,
            namespace_id=switch.namespace_id,
            scope_id=lifecycle.scope_id,
        ).capture(source, epoch_runtime=epoch_runtime)
    finally:
        epoch_runtime.close()


def admit_coding_external_worker_wheel(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    source: Path,
    admission: PackageProductLocalWorkerAdmissionV1,
) -> CodingExternalWorkerWheelBindingV1:
    """Capture one inert Worker candidate; the normal Session route stays dark."""

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    epoch_owner_type = (
        PackageProductWindowsFencedRuntimeOwner
        if os.name == "nt"
        else PackageProductPosixFencedRuntimeOwner
    )
    epoch_runtime = epoch_owner_type.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        switch = epoch_runtime.cutover_result.switch_receipt
        if switch is None:
            raise ValueError("Coding Package Product root is not fenced")
        if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner):
            return CodingWindowsExternalWorkerWheelCatalog(
                epoch_runtime=epoch_runtime,
                state_root=epoch_runtime.prepare_product_state_root(),
                source_root=epoch_runtime.prepare_product_source_root(),
                store_id=epoch.store_id,
                namespace_id=switch.namespace_id,
                scope_id=lifecycle.scope_id,
            ).capture(source, admission=admission)
        return CodingExternalWorkerWheelCatalog(
            epoch_runtime.prepare_product_state_root()
            / "external-worker-wheel-bindings.jsonl",
            source_root=epoch_runtime.prepare_product_source_root(),
            store_id=epoch.store_id,
            namespace_id=switch.namespace_id,
            scope_id=lifecycle.scope_id,
        ).capture(source, admission=admission, epoch_runtime=epoch_runtime)
    finally:
        epoch_runtime.close()


def bootstrap_coding_builtin_product_plugins(
    lifecycle: CodingPluginLifecycleStateLayout,
    settings_manager: SettingsManager,
    *,
    workspace: Path,
    runtime_version: str,
    runtime_protocol_epoch: int,
    windows_candidate: bool = False,
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
    )
    try:
        changed = False
        for plugin_id in (
            "coding.base",
            "coding.lsp.default",
            "coding.arch.default",
        ):
            changed = _bootstrap_coding_builtin_plugin(owner, plugin_id) or changed
        return changed
    finally:
        owner.close()


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
    epoch_runtime = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        receipt = accept_coding_first_b_disabled_only(
            lifecycle,
            epoch_runtime,
            settings_manager=settings_manager,
            accepted_review_id=accepted_review_id,
        )
    finally:
        epoch_runtime.close()
    disabled = {item.plugin_id for item in receipt.review.disabled_plugins}
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )
    try:
        for plugin_id in (
            "coding.base",
            "coding.lsp.default",
            "coding.arch.default",
        ):
            _bootstrap_coding_builtin_plugin(
                owner, plugin_id, enable=plugin_id not in disabled
            )
        return receipt
    finally:
        owner.close()


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
    """Reject old Plugin inputs before ordinary startup falls back unfenced."""

    if not isinstance(lifecycle, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding Plugin lifecycle layout is required")
    if not isinstance(workspace, Path) or not workspace.is_absolute():
        raise ValueError("Coding workspace must be absolute")
    require_fresh_coding_product_settings_without_writes(
        workspace=workspace, settings_manager=settings_manager
    )
    for root, resolver in (
        (lifecycle.root, resolve_coding_lifecycle_pre_b_members),
        (lifecycle.package_root, resolve_coding_package_pre_b_store_members),
    ):
        try:
            root.lstat()
        except FileNotFoundError:
            continue
        if any(resolver(lifecycle).domain_members().values()):
            raise RuntimeError(
                "Coding pre-B workspace is unsupported; use a fresh workspace"
            )


def require_fresh_coding_product_settings_without_writes(
    *, workspace: Path, settings_manager: SettingsManager | None = None
) -> None:
    """Reject legacy settings before a fresh default route is selected."""

    if not isinstance(workspace, Path) or not workspace.is_absolute():
        raise ValueError("Coding workspace must be absolute")
    settings_paths = [
        default_global_settings_path(),
        default_project_settings_path(workspace),
    ]
    if settings_manager is not None:
        if not isinstance(settings_manager, SettingsManager):
            raise TypeError("Coding Product settings manager is invalid")
        settings_paths.extend(
            path
            for path in (
                settings_manager.global_settings_path,
                settings_manager.project_settings_path,
            )
            if path is not None
        )
    require_coding_fresh_settings_without_writes(*dict.fromkeys(settings_paths))


def _initialize_fresh_coding_product_for_session(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    settings_manager: SettingsManager | None,
    windows_candidate: bool = False,
) -> None:
    """Use the Product's offline fresh cutover before ordinary Session writes."""

    if not (
        (os.name == "posix" and sys.platform.startswith("linux"))
        or (os.name == "nt" and windows_candidate)
    ):
        raise RuntimeError(
            "Coding native automatic B Session route is not yet admitted"
        )
    if not workspace.is_dir():
        raise ValueError("Coding Product workspace must be an existing directory")
    global_path = default_global_settings_path()
    project_path = default_project_settings_path(workspace)
    if settings_manager is not None:
        require_fresh_coding_product_inputs(
            lifecycle, settings_manager, roots_may_be_absent=True
        )
        global_path = settings_manager.global_settings_path or global_path
        project_path = settings_manager.project_settings_path or project_path
    cutover_settings = SettingsManager(
        global_settings_path=global_path,
        project_settings_path=project_path,
    )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    namespace_id = _fresh_coding_product_namespace_id(epoch.store_id)
    # Import here because the cutover owner uses this module's Product bootstrap.
    from .package_pre_b_snapshot import cutover_and_bootstrap_coding_package_product

    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        cutover_settings,
        workspace=workspace,
        namespace_id=namespace_id,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        windows_candidate=windows_candidate,
    )


def _fresh_coding_product_namespace_id(store_id: str) -> str:
    return sha256(
        b"loushang.coding-fresh-product-epoch/v1\0" + store_id.encode()
    ).hexdigest()


def _coding_builtin_bootstrap_operation_id(store_id: str, plugin_id: str) -> str:
    return (
        "coding-builtin-bootstrap:"
        + sha256(f"{store_id}:{plugin_id}".encode()).hexdigest()
    )


def _fresh_coding_builtin_bootstrap_completed(
    owner: CodingFencedProductApplicationOwner,
) -> bool:
    """Recognize a completed bootstrap even after later operator changes."""

    product = owner.runtime_owner.product_owner
    transitions = product.desired_state.transitions()
    for plugin_id in ("coding.base", "coding.lsp.default", "coding.arch.default"):
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=product.policy.project_scope_id,
            plugin_id=plugin_id,
        )
        history = tuple(
            item for item in transitions if item.mutation.installation_key == key
        )
        initial_command = product.settled_install_command_id(
            operation_id=_coding_builtin_bootstrap_operation_id(
                owner.epoch_runtime.registry.store_id, plugin_id
            ),
            plugin_id=plugin_id,
        )
        if (
            initial_command is None
            or len(history) < 2
            or history[0].mutation.operation_id != initial_command
            or history[0].committed_state.selection.desired_state
            != "installed_disabled"
            or not history[1].mutation.operation_id.startswith(
                "coding-builtin-bootstrap-enable:"
            )
            or not isinstance(history[1].mutation, PluginDesiredStateMutationV1)
            or history[1].mutation.actor_id != product.actor_id
            or history[1].committed_state.selection.desired_state != "installed_enabled"
            or history[1].committed_state.selection.package_revision
            != history[0].committed_state.selection.package_revision
        ):
            return False
    return True


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
    if (
        runtime.registry.store_id != epoch.store_id
        or runtime.control_root != epoch.control_root
    ):
        raise ValueError("Coding Package Product workspace authority changed")
    fence = runtime.cutover_result.fence
    if (
        fence is None
        or fence.request.namespace_id
        != _fresh_coding_product_namespace_id(epoch.store_id)
    ):
        return False
    for domain in (
        "binding_history",
        "desired_state",
        "enablement_state",
        "instance_state",
        "lock_history",
        "store_bytes",
    ):
        if list_coding_first_b_snapshot_domain_members(
            lifecycle, runtime, domain=domain
        ):
            return False
    if list_coding_first_b_snapshot_domain_members(
        lifecycle, runtime, domain="source_configuration"
    ) != ("coding-source-configuration.json",):
        raise RuntimeError("Coding fresh Product snapshot is incomplete")
    raw = read_coding_first_b_snapshot_member(
        lifecycle,
        runtime,
        domain="source_configuration",
        member_name="coding-source-configuration.json",
        maximum_bytes=4 * 1024 * 1024,
    )
    if raw is None:
        raise RuntimeError("Coding fresh Product snapshot is unavailable")
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


def _retry_fresh_coding_product_bootstrap_for_session(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    settings_manager: SettingsManager | None,
    windows_candidate: bool = False,
) -> None:
    """Resume only a proven fresh first-B cutover; preserve adopted B state."""

    if not (
        (os.name == "posix" and sys.platform.startswith("linux"))
        or (os.name == "nt" and windows_candidate)
    ):
        return
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    runtime = (
        PackageProductWindowsFencedRuntimeOwner.open(
            authority_root=epoch.authority_root,
            control_root=epoch.control_root,
            store_id=epoch.store_id,
            epochs_root_name=epoch.epochs_root_name,
        )
        if os.name == "nt"
        else PackageProductPosixFencedRuntimeOwner.open(
            authority_root=epoch.authority_root,
            control_root=epoch.control_root,
            store_id=epoch.store_id,
            epochs_root_name=epoch.epochs_root_name,
            read_only=True,
        )
    )
    try:
        if not is_coding_fresh_first_b_snapshot(lifecycle, runtime):
            return
    finally:
        runtime.close()
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        windows_candidate=windows_candidate,
    )
    try:
        if _fresh_coding_builtin_bootstrap_completed(owner):
            return
    finally:
        owner.close()
    global_path = default_global_settings_path()
    project_path = default_project_settings_path(workspace)
    if settings_manager is not None:
        global_path = settings_manager.global_settings_path or global_path
        project_path = settings_manager.project_settings_path or project_path
    bootstrap_coding_builtin_product_plugins(
        lifecycle,
        SettingsManager(
            global_settings_path=global_path,
            project_settings_path=project_path,
        ),
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        windows_candidate=windows_candidate,
    )


def _bootstrap_coding_builtin_plugin(
    owner: CodingFencedProductApplicationOwner,
    plugin_id: str,
    *,
    enable: bool = True,
) -> bool:
    product = owner.runtime_owner.product_owner
    desired = product.desired_state
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=product.policy.project_scope_id,
        plugin_id=plugin_id,
    )
    operation_id = _coding_builtin_bootstrap_operation_id(
        owner.epoch_runtime.registry.store_id, plugin_id
    )
    snapshot = desired.snapshot()
    current = snapshot.installation(key).selection.desired_state
    if current == "installed_enabled":
        return False
    if current == "installed_disabled" and enable:
        initial_command = product.settled_install_command_id(
            operation_id=operation_id,
            plugin_id=plugin_id,
        )
        history = tuple(
            item
            for item in desired.transitions()
            if item.mutation.installation_key == key
        )
        if (
            initial_command is not None
            and len(history) >= 2
            and history[0].mutation.operation_id == initial_command
            and history[0].committed_state.selection.desired_state
            == "installed_disabled"
            and history[1].mutation.operation_id.startswith(
                "coding-builtin-bootstrap-enable:"
            )
            and isinstance(history[1].mutation, PluginDesiredStateMutationV1)
            and history[1].mutation.actor_id == product.actor_id
            and history[1].committed_state.selection.desired_state
            == "installed_enabled"
            and history[1].committed_state.selection.package_revision
            == history[0].committed_state.selection.package_revision
            and snapshot.installation(key).selection.package_revision
            == history[0].committed_state.selection.package_revision
        ):
            # A later operator disable is now the current Product choice.
            raise RuntimeError("Coding builtin Product bootstrap was superseded")
    if current == "absent" and any(
        item.installation_key == key for item in snapshot.installations
    ):
        raise RuntimeError("Coding builtin Product bootstrap was removed")
    bootstrap_id = f"coding-builtin-bootstrap:{secrets.token_hex(16)}"
    factory = product.factory_for_session(
        session_id=bootstrap_id,
        cwd=product.workspace,
        runtime_id=bootstrap_id,
    )
    binding: PackageProductRuntimeBindingV1 | None = None
    try:
        binding = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding",
                session_id=bootstrap_id,
                cwd=str(product.workspace),
            )
        )
        binding.activate()
        if current == "absent":
            source = next(
                item.source_identity
                for item in product.policy.bindings
                if item.plugin_id == plugin_id
            )
            outcome = binding.lifecycle.route(
                PackageProductLifecycleIntentV1(
                    operation_id=operation_id,
                    action="install",
                    source=source,
                    scope="project",
                ),
                entrypoint="startup",
            )
            if (
                not outcome.handled
                or outcome.record is None
                or outcome.record.lifecycle != "installed"
                or outcome.evidence.operation_id != operation_id
            ):
                failure_code = (
                    outcome.record.failure_code
                    if outcome.record is not None
                    else None
                ) or "no_failure_record"
                raise RuntimeError(
                    "Coding builtin Product bootstrap install refused: "
                    f"{failure_code}"
                )
        expected_command_id = product.settled_install_command_id(
            operation_id=operation_id,
            plugin_id=plugin_id,
        )
        if expected_command_id is None:
            raise RuntimeError("Coding builtin Product bootstrap handoff is missing")
    finally:
        if binding is None:
            factory.dispose_unbound_runtime()
        else:
            binding.dispose_runtime()

    snapshot = desired.snapshot()
    selected = snapshot.installation(key)
    if selected.selection.desired_state != "installed_disabled":
        raise RuntimeError("Coding builtin Product bootstrap selection changed")
    prior = next(
        (
            transition
            for transition in reversed(desired.transitions())
            if transition.mutation.installation_key == key
        ),
        None,
    )
    if (
        not isinstance(prior, PluginDesiredStateTransitionV1)
        or prior.mutation.operation_id != expected_command_id
        or prior.mutation.actor_id != product.actor_id
        or prior.committed_state != selected
    ):
        raise RuntimeError("Coding builtin Product bootstrap was superseded")
    if not enable:
        return current == "absent"
    enable_id = (
        "coding-builtin-bootstrap-enable:"
        + sha256(f"{operation_id}:{snapshot.inventory_revision}".encode()).hexdigest()
    )
    enabled = product.management.submit(
        PluginManagementCommandV1(
            action="enable",
            mutation=PluginDesiredStateMutationV1(
                operation_id=enable_id,
                idempotency_key=enable_id,
                expected_inventory_revision=snapshot.inventory_revision,
                installation_key=key,
                desired_state="installed_enabled",
                package_revision=None,
                actor_id=product.actor_id,
                policy_revision=product.desired_policy_revision,
            ),
        )
    )
    if enabled.result is None or enabled.result.disposition != "succeeded":
        raise RuntimeError("Coding builtin Product bootstrap enable refused")
    return True


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
    if not isinstance(state, CodingPackageProductStateOwners):
        raise TypeError("Coding Package Product state owners are required")
    if (
        not isinstance(workspace, Path)
        or not workspace.is_absolute()
        or ".." in workspace.parts
        or workspace != workspace.resolve(strict=True)
    ):
        raise ValueError("Coding Product workspace is not canonical")
    scope_id = (
        "workspace:"
        + sha256(
            b"loushang.coding-continuity-workspace/v1\0" + os.fsencode(str(workspace))
        ).hexdigest()
    )
    if lifecycle.scope_id != scope_id:
        raise ValueError("Coding Product workspace scope changed")
    if not isinstance(runtime_version, str) or not runtime_version:
        raise ValueError("Coding Product runtime version is required")
    if type(runtime_protocol_epoch) is not int or runtime_protocol_epoch < 1:
        raise ValueError("Coding Product runtime protocol epoch is invalid")
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if (
        epoch_runtime.registry.store_id != epoch.store_id
        or epoch_runtime.control_root != epoch.control_root
    ):
        raise ValueError("Coding Package Product workspace authority changed")
    state_root = epoch_runtime.prepare_product_state_root()
    if (
        state.state_root != state_root
        or state.gc_gate.path != state_root / "gc-reservations.jsonl"
        or state.desired_state.path != state_root / "desired-state.jsonl"
        or state.management.operation_journal_path
        != state_root / "management-operations.jsonl"
        or state.management.retirement_intent_journal_path
        != state_root / "management-operations.jsonl.retirement-intents"
        or state.management.retirement_set_journal_path
        != state_root / "management-operations.jsonl.retirement-sets"
        or state.gc_bindings.path != state_root / "gc-bindings.jsonl"
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
    policy_arguments = dict(
        project_scope_id=scope_id,
        resolution_environment_fingerprint=host_inputs.environment.fingerprint,
        policy_revision=CODING_PACKAGE_PRODUCT_POLICY_REVISION,
        quota_profile_revision="coding-product-package-quota:1",
        authority_id="coding-product-local-source",
    )
    policy = (
        coding_builtin_product_local_wheel_policy(
            artifact,
            (
                prepare_windows_coding_capability_product_wheels(source_root)
                if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner)
                else prepare_posix_coding_capability_product_wheels(source_root)
            ),
            **policy_arguments,
        )
        if include_capabilities
        else coding_base_product_local_wheel_policy(artifact, **policy_arguments)
    )

    def read_legacy_acceptance(plugin_id: str):
        if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner):
            return None
        return reopen_coding_legacy_installed_local_acceptance(
            lifecycle,
            epoch_runtime,
            plugin_id=plugin_id,
            policy_revision=policy.policy_revision,
        )

    policy = CodingLegacyLocalBindingCatalog(
        state_root / "legacy-local-bindings.jsonl",
        source_root=source_root,
        store_id=epoch.store_id,
        namespace_id=switch.namespace_id,
        scope_id=scope_id,
        policy_revision=policy.policy_revision,
        acceptance_reader=read_legacy_acceptance,
    ).extend_policy(policy)
    policy = CodingExternalDataWheelCatalog(
        state_root / "external-data-wheel-bindings.jsonl",
        source_root=source_root,
        store_id=epoch.store_id,
        namespace_id=switch.namespace_id,
        scope_id=scope_id,
    ).extend_policy(policy)
    if isinstance(epoch_runtime, PackageProductPosixFencedRuntimeOwner):
        policy = CodingExternalDependencyWheelCatalog(
            state_root / "external-dependency-wheel-bindings.jsonl",
            source_root=source_root,
            store_id=epoch.store_id,
            namespace_id=switch.namespace_id,
            scope_id=scope_id,
        ).extend_policy(policy)
    if include_worker_candidates:
        policy = (
            CodingWindowsExternalWorkerWheelCatalog(
                epoch_runtime=epoch_runtime,
                state_root=state_root,
                source_root=source_root,
                store_id=epoch.store_id,
                namespace_id=switch.namespace_id,
                scope_id=scope_id,
            ).extend_policy(policy)
            if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner)
            else CodingExternalWorkerWheelCatalog(
                state_root / "external-worker-wheel-bindings.jsonl",
                source_root=source_root,
                store_id=epoch.store_id,
                namespace_id=switch.namespace_id,
                scope_id=scope_id,
            ).extend_policy(policy)
        )
    session_owner = (
        WindowsLocalWheelProductSessionOwner(
            workspace=workspace,
            policy=policy,
            host_inputs=host_inputs,
            root_store_identity=f"coding-product-root-store:{epoch.store_id}",
            dependency_store_identity=f"coding-product-dependency-store:{epoch.store_id}",
            epoch_runtime=epoch_runtime,
            management=state.management,
            desired_state=state.desired_state,
            gc_bindings=state.gc_bindings,
            gc_gate=state.gc_gate,
            actor_id="product:coding",
            desired_policy_revision="coding-product-desired-policy:1",
            recovery_identity=f"coding-product-recovery:{epoch.store_id}",
            runtime_version=runtime_version,
            runtime_protocol_epoch=runtime_protocol_epoch,
        )
        if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner)
        else PosixLocalWheelProductSessionOwner(
            workspace=workspace,
            state_root=state.state_root,
            plugin_store_root=epoch.epoch_root(switch.namespace_id),
            policy=policy,
            environment=host_inputs.environment,
            acquisition_budgets=host_inputs.acquisition_budgets,
            inspection_budgets=host_inputs.inspection_budgets,
            closure_budgets=host_inputs.closure_budgets,
            root_store_identity=f"coding-product-root-store:{epoch.store_id}",
            dependency_store_identity=f"coding-product-dependency-store:{epoch.store_id}",
            epoch_runtime=epoch_runtime,
            management=state.management,
            desired_state=state.desired_state,
            gc_bindings=state.gc_bindings,
            gc_gate=state.gc_gate,
            actor_id="product:coding",
            desired_policy_revision="coding-product-desired-policy:1",
            recovery_identity=f"coding-product-recovery:{epoch.store_id}",
            runtime_version=runtime_version,
            runtime_protocol_epoch=runtime_protocol_epoch,
        )
    )
    return CodingPosixLocalWheelProductRuntimeOwner(product_owner=session_owner)


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
