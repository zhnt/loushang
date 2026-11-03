"""Product-owned PLC9A2 runtime activation at the Session bootstrap boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Protocol

from loushang.harness.package_product.product_rebind_preflight import (
    PackageProductAcquiredRebindPreflightV1,
    PackageProductPinnedRebindPreflightV1,
    PackageProductPublishedSetPreflightV1,
    PackageProductRebindPreflightV1,
    PackageProductResolvingRebindPreflightV1,
    PackageProductStagingRebindPreflightV1,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredState,
    PluginInstallationKeyV1,
)
from loushang.harness.resources.packages.product_activation import (
    PackageProductExactHandoffRecoveryV1,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleInventoryPort,
    PackageProductLifecycleMode,
    PackageProductLifecycleOperationPort,
)

if TYPE_CHECKING:
    from loushang.harness.package_product.product_local_wheel_runtime import (
        PackageProductSelectedPluginManifestV1,
    )
    from loushang.harness.package_product.product_pinned_adoption import (
        PackageProductPinnedAdoptionOwner,
    )
    from loushang.harness.package_product.product_rebind_cleanup import (
        PackageProductAcquiredCleanupObservationV1,
        PackageProductPinnedCleanupObservationV1,
        PackageProductRebindCleanupObservationV1,
        PackageProductResolvingCleanupObservationV1,
    )
    from loushang.harness.package_product.product_rebind_decision import (
        PackageProductRebindDecisionOwner,
    )
    from loushang.harness.package_product.product_rebind_lease import (
        PackageProductRebindLeaseObservationV1,
    )
    from loushang.harness.package_product.product_rebind_source import (
        PackageProductRebindSourceObservationV1,
    )
    from loushang.harness.package_product.product_staging_adoption import (
        PackageProductStagingAdoptionOwner,
    )
    from loushang.harness.plugin_management.package_product import (
        PackageProductSelectedDependencyClosureSnapshotV1,
        PackageProductSelectedDependencySnapshotV1,
        PackageProductSelectedRootSnapshotV1,
    )
    from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
        PackageEpochRuntimeAdmissionReceiptV1,
    )
    from loushang.harness.resources.packages.plugin_lifecycle.records import (
        PackageLifecyclePinnedAdoptionRecordV1,
        PackageLifecycleRebindRecordV1,
        PackageLifecycleRestartRecordV1,
        PackageLifecycleStagingAdoptionRecordV1,
        PackageLifecycleStatusV1,
    )
    from loushang.harness.resources.packages.plugin_lifecycle.staging_set_runtime import (
        PackagePublishedSetCheckpointV1,
        PackageStagingCheckpointV1,
    )
    from loushang.harness.resources.packages.product_lifecycle import (
        PackageProductPinnedAdoptedRouteRequestV1,
        PackageProductReboundRouteRequestV1,
        PackageProductStagingAdoptedRouteRequestV1,
    )

PACKAGE_PRODUCT_RUNTIME_REQUEST_VERSION = 1
PACKAGE_PRODUCT_RUNTIME_BINDING_VERSION = 1


class PackageProductRuntimeActivationError(RuntimeError):
    """Stable refusal raised before the standard Session activation graph."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PackageProductPluginDesiredSelectionV1:
    """Current state plus whether this Installation has a durable Desired row."""

    installation_key: PluginInstallationKeyV1
    inventory_revision: int
    desired_state: PluginDesiredState
    recorded: bool

    def __post_init__(self) -> None:
        if not isinstance(self.installation_key, PluginInstallationKeyV1):
            raise TypeError("Product Plugin selection key is required")
        if type(self.inventory_revision) is not int or self.inventory_revision < 0:
            raise ValueError("Product Plugin selection revision is invalid")
        if self.desired_state not in {
            "absent",
            "installed_disabled",
            "installed_enabled",
        }:
            raise ValueError("Product Plugin selection state is invalid")
        if type(self.recorded) is not bool:
            raise ValueError("Product Plugin selection history flag is invalid")
        if self.desired_state != "absent" and not self.recorded:
            raise ValueError("Installed Product Plugin selection must be recorded")


class PackageProductSelectedRootReadPort(Protocol):
    """Read one selected Plugin member without granting a pathname or execution."""

    def read_selected_file(
        self,
        installation_key: PluginInstallationKeyV1,
        logical_path: str,
        *,
        max_bytes: int,
    ) -> bytes: ...

    def read_selected_files(
        self,
        installation_key: PluginInstallationKeyV1,
        logical_paths: tuple[str, ...],
        *,
        max_total_bytes: int,
    ) -> tuple[bytes, ...]: ...

    def capture_selected_root(
        self,
        installation_key: PluginInstallationKeyV1,
        *,
        max_files: int,
        max_total_bytes: int,
    ) -> PackageProductSelectedRootSnapshotV1: ...


class PackageProductSelectedManifestReadPort(Protocol):
    def capture_plugin_desired_selection_for(
        self, plugin_id: str
    ) -> PackageProductPluginDesiredSelectionV1: ...

    def selected_external_data_plugin_ids(self) -> tuple[str, ...]: ...

    def assert_selected_manifest_current(
        self, selected: PackageProductSelectedPluginManifestV1
    ) -> None: ...

    def capture_selected_manifest(
        self,
        installation_key: PluginInstallationKeyV1,
        *,
        max_files: int,
        max_total_bytes: int,
    ) -> PackageProductSelectedPluginManifestV1: ...

    def capture_selected_manifest_for_plugin(
        self,
        plugin_id: str,
        *,
        max_files: int,
        max_total_bytes: int,
    ) -> PackageProductSelectedPluginManifestV1: ...


class PackageProductSelectedDependencyReadPort(Protocol):
    def capture_selected_dependency_closure_for_plugin(
        self,
        plugin_id: str,
        *,
        max_dependencies: int,
        max_files_per_dependency: int,
        max_total_bytes: int,
    ) -> PackageProductSelectedDependencyClosureSnapshotV1: ...

    def assert_selected_dependency_closure_current(
        self, snapshot: PackageProductSelectedDependencyClosureSnapshotV1
    ) -> None: ...

    def capture_selected_dependency_for_plugin(
        self,
        plugin_id: str,
        *,
        max_files: int,
        max_total_bytes: int,
    ) -> PackageProductSelectedDependencySnapshotV1: ...

    def assert_selected_dependency_current(
        self, snapshot: PackageProductSelectedDependencySnapshotV1
    ) -> None: ...


class PackageProductRebindSourceReadPort(Protocol):
    def observe(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductRebindSourceObservationV1: ...

    def observe_acquired_claim(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductRebindSourceObservationV1: ...

    def observe_resolving_claim(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductRebindSourceObservationV1: ...

    def observe_verified_claim(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductRebindSourceObservationV1: ...

    def observe_pinned_claim(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductRebindSourceObservationV1: ...

    def observe_published_claim(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductRebindSourceObservationV1: ...


class PackageProductRebindLeaseReadPort(Protocol):
    def observe(self, operation_id: str) -> PackageProductRebindLeaseObservationV1: ...

    def observe_acquired_claim(
        self, operation_id: str
    ) -> PackageProductRebindLeaseObservationV1: ...

    def observe_resolving_claim(
        self, operation_id: str
    ) -> PackageProductRebindLeaseObservationV1: ...

    def observe_verified_claim(
        self, operation_id: str
    ) -> PackageProductRebindLeaseObservationV1: ...

    def observe_pinned_claim(
        self, operation_id: str
    ) -> PackageProductRebindLeaseObservationV1: ...

    def observe_published_claim(
        self, operation_id: str
    ) -> PackageProductRebindLeaseObservationV1: ...


class PackageProductRebindCleanupReadPort(Protocol):
    def observe(
        self, operation_id: str
    ) -> PackageProductRebindCleanupObservationV1: ...

    def observe_acquired_claim(
        self, operation_id: str
    ) -> PackageProductAcquiredCleanupObservationV1: ...

    def observe_resolving_claim(
        self, operation_id: str
    ) -> PackageProductResolvingCleanupObservationV1: ...

    def observe_verified_claim(
        self, operation_id: str
    ) -> PackageProductResolvingCleanupObservationV1: ...

    def observe_pinned_claim(
        self, operation_id: str
    ) -> PackageProductPinnedCleanupObservationV1: ...


class PackageStagingCheckpointReadPort(Protocol):
    def inspect_checkpoint(self, operation_id: str) -> PackageStagingCheckpointV1: ...

    def inspect_published_checkpoint(
        self, operation_id: str
    ) -> PackagePublishedSetCheckpointV1: ...


@dataclass(frozen=True, slots=True)
class PackageProductRuntimeRequestV1:
    """Identity-only request used by a Product to select its runtime owners."""

    product_id: str
    session_id: str
    cwd: str
    request_version: int = PACKAGE_PRODUCT_RUNTIME_REQUEST_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.product_id, "Package Product id"),
            (self.session_id, "Package Product Session id"),
            (self.cwd, "Package Product cwd"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty")
        cwd = Path(self.cwd)
        if not cwd.is_absolute():
            raise ValueError("Package Product cwd must be absolute")
        object.__setattr__(self, "cwd", str(cwd.resolve(strict=False)))
        if self.request_version != PACKAGE_PRODUCT_RUNTIME_REQUEST_VERSION:
            raise ValueError("Unsupported Package Product runtime request")


@dataclass(frozen=True, slots=True)
class PackageProductRuntimeBindingV1:
    """One aggregate binding for lifecycle, inventory, and rollout policy."""

    product_id: str
    lifecycle: PackageProductLifecycleOperationPort
    inventory: PackageProductLifecycleInventoryPort
    mode: PackageProductLifecycleMode
    binding_version: int = PACKAGE_PRODUCT_RUNTIME_BINDING_VERSION
    session_id: str | None = field(default=None, kw_only=True)
    product_runtime_id: str | None = field(default=None, kw_only=True)
    _selected_root_reader: PackageProductSelectedRootReadPort | None = field(
        default=None, kw_only=True, repr=False, compare=False
    )
    _selected_manifest_reader: PackageProductSelectedManifestReadPort | None = field(
        default=None, kw_only=True, repr=False, compare=False
    )
    _selected_dependency_reader: PackageProductSelectedDependencyReadPort | None = field(
        default=None, kw_only=True, repr=False, compare=False
    )
    _rebind_source_reader: PackageProductRebindSourceReadPort | None = field(
        default=None, kw_only=True, repr=False, compare=False
    )
    _rebind_lease_reader: PackageProductRebindLeaseReadPort | None = field(
        default=None, kw_only=True, repr=False, compare=False
    )
    _rebind_cleanup_reader: PackageProductRebindCleanupReadPort | None = field(
        default=None, kw_only=True, repr=False, compare=False
    )
    _rebind_decision_owner: PackageProductRebindDecisionOwner | None = field(
        default=None, kw_only=True, repr=False, compare=False
    )
    _pinned_adoption_owner: PackageProductPinnedAdoptionOwner | None = field(
        default=None, kw_only=True, repr=False, compare=False
    )
    _staging_adoption_owner: PackageProductStagingAdoptionOwner | None = field(
        default=None, kw_only=True, repr=False, compare=False
    )
    _staging_checkpoint_reader: PackageStagingCheckpointReadPort | None = field(
        default=None, kw_only=True, repr=False, compare=False
    )
    on_dispose: Callable[[], None] | None = field(
        default=None, kw_only=True, repr=False, compare=False
    )
    _dispose_lock: Lock = field(
        default_factory=Lock, init=False, repr=False, compare=False
    )
    _disposed: bool = field(default=False, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.product_id, str) or not self.product_id:
            raise ValueError("Package Product runtime id must be non-empty")
        if self.mode not in {"dark", "enforced"}:
            raise ValueError("Activated Package Product runtime cannot use legacy mode")
        if not callable(getattr(self.lifecycle, "activate", None)):
            raise TypeError("Package Product lifecycle activation is required")
        lifecycle_binding = getattr(self.lifecycle, "binding_id", None)
        inventory_binding = getattr(self.inventory, "binding_id", None)
        if (
            not isinstance(lifecycle_binding, str)
            or not lifecycle_binding
            or inventory_binding != lifecycle_binding
        ):
            raise ValueError("Package Product runtime owners changed binding")
        if self.binding_version != PACKAGE_PRODUCT_RUNTIME_BINDING_VERSION:
            raise ValueError("Unsupported Package Product runtime binding")
        if (self.session_id is None) != (self.product_runtime_id is None):
            raise ValueError("Package Product Session binding is incomplete")
        if self.session_id is not None and (
            not isinstance(self.session_id, str)
            or not self.session_id
            or not isinstance(self.product_runtime_id, str)
            or not self.product_runtime_id
        ):
            raise ValueError("Package Product Session binding is invalid")
        if self.on_dispose is not None and not callable(self.on_dispose):
            raise TypeError("Package Product runtime disposal must be callable")
        if self._selected_root_reader is not None and not callable(
            getattr(self._selected_root_reader, "read_selected_file", None)
        ):
            raise TypeError("Package Product selected-root reader is invalid")
        if self._selected_root_reader is not None and not callable(
            getattr(self._selected_root_reader, "read_selected_files", None)
        ):
            raise TypeError("Package Product selected-root batch reader is invalid")
        if self._selected_root_reader is not None and not callable(
            getattr(self._selected_root_reader, "capture_selected_root", None)
        ):
            raise TypeError("Package Product selected-root capture is invalid")
        if self._selected_manifest_reader is not None and not callable(
            getattr(self._selected_manifest_reader, "capture_selected_manifest", None)
        ):
            raise TypeError("Package Product selected-manifest reader is invalid")
        if self._selected_dependency_reader is not None and not callable(
            getattr(
                self._selected_dependency_reader,
                "capture_selected_dependency_for_plugin",
                None,
            )
        ):
            raise TypeError("Package Product selected-dependency reader is invalid")
        if self._selected_dependency_reader is not None and not callable(
            getattr(
                self._selected_dependency_reader,
                "assert_selected_dependency_current",
                None,
            )
        ):
            raise TypeError("Package Product selected-dependency recheck is invalid")
        if self._selected_dependency_reader is not None and not callable(
            getattr(
                self._selected_dependency_reader,
                "capture_selected_dependency_closure_for_plugin",
                None,
            )
        ):
            raise TypeError("Package Product dependency-closure reader is invalid")
        if self._selected_dependency_reader is not None and not callable(
            getattr(
                self._selected_dependency_reader,
                "assert_selected_dependency_closure_current",
                None,
            )
        ):
            raise TypeError("Package Product dependency-closure recheck is invalid")
        if self._selected_manifest_reader is not None and not callable(
            getattr(
                self._selected_manifest_reader,
                "capture_plugin_desired_selection_for",
                None,
            )
        ):
            raise TypeError("Package Product desired-selection reader is invalid")
        if self._selected_manifest_reader is not None and not callable(
            getattr(
                self._selected_manifest_reader,
                "capture_selected_manifest_for_plugin",
                None,
            )
        ):
            raise TypeError("Package Product Plugin selection reader is invalid")
        if self._selected_manifest_reader is not None and not callable(
            getattr(
                self._selected_manifest_reader,
                "assert_selected_manifest_current",
                None,
            )
        ):
            raise TypeError("Package Product selection recheck is invalid")
        if self._rebind_source_reader is not None and not callable(
            getattr(self._rebind_source_reader, "observe", None)
        ):
            raise TypeError("Package Product rebind Source reader is invalid")
        if self._rebind_source_reader is not None and not callable(
            getattr(self._rebind_source_reader, "observe_acquired_claim", None)
        ):
            raise TypeError("Package Product acquired Source reader is invalid")
        if self._rebind_lease_reader is not None and not callable(
            getattr(self._rebind_lease_reader, "observe", None)
        ):
            raise TypeError("Package Product rebind lease reader is invalid")
        if self._rebind_lease_reader is not None and not callable(
            getattr(self._rebind_lease_reader, "observe_acquired_claim", None)
        ):
            raise TypeError("Package Product acquired lease reader is invalid")
        if self._rebind_cleanup_reader is not None and not callable(
            getattr(self._rebind_cleanup_reader, "observe", None)
        ):
            raise TypeError("Package Product rebind cleanup reader is invalid")
        if self._rebind_cleanup_reader is not None and not callable(
            getattr(self._rebind_cleanup_reader, "observe_acquired_claim", None)
        ):
            raise TypeError("Package Product acquired cleanup reader is invalid")
        if self._rebind_decision_owner is not None and any(
            not callable(getattr(self._rebind_decision_owner, method, None))
            for method in (
                "prepare",
                "resume",
                "route",
                "authorize",
                "revoke",
                "recover_unstarted_claim",
                "recover_acquired_claim",
            )
        ):
            raise TypeError("Package Product rebind decision owner is invalid")
        if self._pinned_adoption_owner is not None and any(
            not callable(getattr(self._pinned_adoption_owner, method, None))
            for method in ("prepare", "claim", "authorize", "revoke", "route")
        ):
            raise TypeError("Package Product pinned adoption owner is invalid")
        if self._staging_adoption_owner is not None and not callable(
            getattr(self._staging_adoption_owner, "prepare", None)
        ):
            raise TypeError("Package Product staging adoption owner is invalid")
        if self._staging_checkpoint_reader is not None and not callable(
            getattr(self._staging_checkpoint_reader, "inspect_checkpoint", None)
        ):
            raise TypeError("Package Product staging checkpoint reader is invalid")

    @property
    def binding_id(self) -> str:
        return self.lifecycle.binding_id

    async def inspect_rebind_source(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductRebindSourceObservationV1:
        """Read A2 Source evidence under the admitted Product epoch guard."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            reader = self._rebind_source_reader
            if reader is None:
                raise PackageProductRuntimeActivationError(
                    "Package Product rebind Source reader is unavailable",
                    code="package_product_rebind_source_reader_unavailable",
                )

        async def read_guarded() -> PackageProductRebindSourceObservationV1:
            return reader.observe(operation_id, max_bytes=max_bytes)

        return await self.lifecycle.execute_guarded_query(read_guarded)

    async def inspect_rebind_lease(
        self, operation_id: str
    ) -> PackageProductRebindLeaseObservationV1:
        """Read complete lease evidence under the admitted Product epoch guard."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            reader = self._rebind_lease_reader
            if reader is None:
                raise PackageProductRuntimeActivationError(
                    "Package Product rebind lease reader is unavailable",
                    code="package_product_rebind_lease_reader_unavailable",
                )

        async def read_guarded() -> PackageProductRebindLeaseObservationV1:
            return reader.observe(operation_id)

        return await self.lifecycle.execute_guarded_query(read_guarded)

    async def inspect_rebind_cleanup(
        self, operation_id: str
    ) -> PackageProductRebindCleanupObservationV1:
        """Read known cleanup and quarantine facts under the Product epoch guard."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            reader = self._rebind_cleanup_reader
            if reader is None:
                raise PackageProductRuntimeActivationError(
                    "Package Product rebind cleanup reader is unavailable",
                    code="package_product_rebind_cleanup_reader_unavailable",
                )

        async def read_guarded() -> PackageProductRebindCleanupObservationV1:
            return reader.observe(operation_id)

        return await self.lifecycle.execute_guarded_query(read_guarded)

    async def inspect_rebind_preflight(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductRebindPreflightV1:
        """Join Source, lease and known cleanup facts under one epoch guard."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            source = self._rebind_source_reader
            lease = self._rebind_lease_reader
            cleanup = self._rebind_cleanup_reader
            if source is None or lease is None or cleanup is None:
                raise PackageProductRuntimeActivationError(
                    "Package Product rebind preflight is unavailable",
                    code="package_product_rebind_preflight_unavailable",
                )

        async def read_guarded() -> PackageProductRebindPreflightV1:
            return PackageProductRebindPreflightV1(
                source=source.observe(operation_id, max_bytes=max_bytes),
                lease=lease.observe(operation_id),
                cleanup=cleanup.observe(operation_id),
            )

        return await self.lifecycle.execute_guarded_query(read_guarded)

    async def inspect_acquired_rebind_claim(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductAcquiredRebindPreflightV1:
        """Join selected root-stage facts under one Product epoch guard."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            source = self._rebind_source_reader
            lease = self._rebind_lease_reader
            cleanup = self._rebind_cleanup_reader
            if source is None or lease is None or cleanup is None:
                raise PackageProductRuntimeActivationError(
                    "Package Product acquired rebind preflight is unavailable",
                    code="package_product_rebind_preflight_unavailable",
                )

        async def read_guarded() -> PackageProductAcquiredRebindPreflightV1:
            return PackageProductAcquiredRebindPreflightV1(
                source=source.observe_acquired_claim(operation_id, max_bytes=max_bytes),
                lease=lease.observe_acquired_claim(operation_id),
                cleanup=cleanup.observe_acquired_claim(operation_id),
            )

        return await self.lifecycle.execute_guarded_query(read_guarded)

    async def inspect_resolving_rebind_claim(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductResolvingRebindPreflightV1:
        """Join selected closure node, Source, and lease facts under one guard."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            source = self._rebind_source_reader
            lease = self._rebind_lease_reader
            cleanup = self._rebind_cleanup_reader
            if (
                source is None
                or lease is None
                or cleanup is None
                or not callable(getattr(source, "observe_resolving_claim", None))
                or not callable(getattr(lease, "observe_resolving_claim", None))
                or not callable(getattr(cleanup, "observe_resolving_claim", None))
            ):
                raise PackageProductRuntimeActivationError(
                    "Package Product resolving preflight is unavailable",
                    code="package_product_rebind_preflight_unavailable",
                )

        async def read_guarded() -> PackageProductResolvingRebindPreflightV1:
            return PackageProductResolvingRebindPreflightV1(
                source=source.observe_resolving_claim(
                    operation_id, max_bytes=max_bytes
                ),
                lease=lease.observe_resolving_claim(operation_id),
                cleanup=cleanup.observe_resolving_claim(operation_id),
            )

        return await self.lifecycle.execute_guarded_query(read_guarded)

    async def inspect_verified_rebind_claim(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductResolvingRebindPreflightV1:
        """Join selected verified-closure, Source, and lease facts under one guard."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            source = self._rebind_source_reader
            lease = self._rebind_lease_reader
            cleanup = self._rebind_cleanup_reader
            if (
                source is None
                or lease is None
                or cleanup is None
                or not callable(getattr(source, "observe_verified_claim", None))
                or not callable(getattr(lease, "observe_verified_claim", None))
                or not callable(getattr(cleanup, "observe_verified_claim", None))
            ):
                raise PackageProductRuntimeActivationError(
                    "Package Product verified preflight is unavailable",
                    code="package_product_rebind_preflight_unavailable",
                )

        async def read_guarded() -> PackageProductResolvingRebindPreflightV1:
            return PackageProductResolvingRebindPreflightV1(
                source=source.observe_verified_claim(operation_id, max_bytes=max_bytes),
                lease=lease.observe_verified_claim(operation_id),
                cleanup=cleanup.observe_verified_claim(operation_id),
            )

        return await self.lifecycle.execute_guarded_query(read_guarded)

    async def inspect_pinned_rebind_claim(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductPinnedRebindPreflightV1:
        """Observe a selected acquired pin without releasing or changing it."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            source = self._rebind_source_reader
            lease = self._rebind_lease_reader
            cleanup = self._rebind_cleanup_reader
            if (
                source is None
                or lease is None
                or cleanup is None
                or not callable(getattr(source, "observe_pinned_claim", None))
                or not callable(getattr(lease, "observe_pinned_claim", None))
                or not callable(getattr(cleanup, "observe_pinned_claim", None))
            ):
                raise PackageProductRuntimeActivationError(
                    "Package Product pinned preflight is unavailable",
                    code="package_product_rebind_preflight_unavailable",
                )

        async def read_guarded() -> PackageProductPinnedRebindPreflightV1:
            return PackageProductPinnedRebindPreflightV1(
                source=source.observe_pinned_claim(operation_id, max_bytes=max_bytes),
                lease=lease.observe_pinned_claim(operation_id),
                cleanup=cleanup.observe_pinned_claim(operation_id),
            )

        return await self.lifecycle.execute_guarded_query(read_guarded)

    async def inspect_staging_checkpoint(
        self, operation_id: str
    ) -> PackageStagingCheckpointV1:
        """Read a physical staging prefix under this Product's epoch guard."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            reader = self._staging_checkpoint_reader
            if reader is None:
                raise PackageProductRuntimeActivationError(
                    "Package Product staging checkpoint is unavailable",
                    code="package_product_staging_checkpoint_unavailable",
                )

        async def read_guarded() -> PackageStagingCheckpointV1:
            return reader.inspect_checkpoint(operation_id)

        return await self.lifecycle.execute_guarded_query(read_guarded)

    async def inspect_staging_rebind_claim(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductStagingRebindPreflightV1:
        """Join a staged prefix to selected Source and exited leases."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            source = self._rebind_source_reader
            lease = self._rebind_lease_reader
            checkpoint = self._staging_checkpoint_reader
            if source is None or lease is None or checkpoint is None:
                raise PackageProductRuntimeActivationError(
                    "Package Product staging preflight is unavailable",
                    code="package_product_staging_preflight_unavailable",
                )

        async def read_guarded() -> PackageProductStagingRebindPreflightV1:
            return PackageProductStagingRebindPreflightV1(
                source=source.observe_pinned_claim(operation_id, max_bytes=max_bytes),
                lease=lease.observe_pinned_claim(operation_id),
                checkpoint=checkpoint.inspect_checkpoint(operation_id),
            )

        return await self.lifecycle.execute_guarded_query(read_guarded)

    async def inspect_published_set_rebind_claim(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductPublishedSetPreflightV1:
        """Join a complete published set to current Source and exited leases."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            source = self._rebind_source_reader
            lease = self._rebind_lease_reader
            checkpoint = self._staging_checkpoint_reader
            if source is None or lease is None or checkpoint is None:
                raise PackageProductRuntimeActivationError(
                    "Package Product published-set preflight is unavailable",
                    code="package_product_published_preflight_unavailable",
                )

        async def read_guarded() -> PackageProductPublishedSetPreflightV1:
            return PackageProductPublishedSetPreflightV1(
                source=source.observe_published_claim(
                    operation_id, max_bytes=max_bytes
                ),
                lease=lease.observe_published_claim(operation_id),
                checkpoint=checkpoint.inspect_published_checkpoint(operation_id),
            )

        return await self.lifecycle.execute_guarded_query(read_guarded)

    def prepare_rebind_decision(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageLifecycleRebindRecordV1:
        """Prepare an inert decision through the admitted Product mutation guard."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            owner = self._rebind_decision_owner
            guarded = getattr(self.lifecycle, "execute_guarded_mutation", None)
            if owner is None or not callable(guarded):
                raise PackageProductRuntimeActivationError(
                    "Package Product rebind decision owner is unavailable",
                    code="package_product_rebind_decision_unavailable",
                )
        return guarded(
            lambda receipt: owner.prepare(
                operation_id, max_bytes=max_bytes, admission=receipt
            )
        )

    def prepare_pinned_adoption(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageLifecyclePinnedAdoptionRecordV1:
        """Select one inert pinned admission under Product mutation guard."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            owner = self._pinned_adoption_owner
            guarded = getattr(self.lifecycle, "execute_guarded_mutation", None)
            if owner is None or not callable(guarded):
                raise PackageProductRuntimeActivationError(
                    "Package Product pinned admission adoption is unavailable",
                    code="package_product_pinned_adoption_unavailable",
                )
        return guarded(
            lambda receipt: owner.prepare(
                operation_id, max_bytes=max_bytes, admission=receipt
            )
        )

    def prepare_staging_adoption(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageLifecycleStagingAdoptionRecordV1:
        """Select one inert staging admission under Product mutation guard."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            owner = self._staging_adoption_owner
            guarded = getattr(self.lifecycle, "execute_guarded_mutation", None)
            if owner is None or not callable(guarded):
                raise PackageProductRuntimeActivationError(
                    "Package Product staging admission adoption is unavailable",
                    code="package_product_staging_adoption_unavailable",
                )
        return guarded(
            lambda receipt: owner.prepare(
                operation_id, max_bytes=max_bytes, admission=receipt
            )
        )

    def execute_pinned_adoption(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageLifecycleStatusV1:
        """Run the exact selected pinned admission under one Product guard."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            owner = self._pinned_adoption_owner
            guarded = getattr(self.lifecycle, "execute_guarded_pinned_adoption", None)
            if owner is None or not callable(guarded):
                raise PackageProductRuntimeActivationError(
                    "Pinned Package Product execution is unavailable",
                    code="package_product_pinned_execution_unavailable",
                )

        claimed: (
            tuple[PackageProductPinnedAdoptedRouteRequestV1, PackageLifecycleStatusV1]
            | None
        ) = None

        def prepare(
            receipt: PackageEpochRuntimeAdmissionReceiptV1,
        ) -> tuple[PackageProductPinnedAdoptedRouteRequestV1, PackageLifecycleStatusV1]:
            nonlocal claimed
            _record, current, route = owner.claim(
                operation_id, max_bytes=max_bytes, admission=receipt
            )
            claimed = route, current
            return claimed

        try:
            return guarded(prepare)
        finally:
            if claimed is not None:
                owner.revoke(*claimed)

    def execute_staging_adoption(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageLifecycleStatusV1:
        """Resume a complete selected staged set under one Product guard."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            owner = self._staging_adoption_owner
            guarded = getattr(self.lifecycle, "execute_guarded_staging_adoption", None)
            if owner is None or not callable(guarded):
                raise PackageProductRuntimeActivationError(
                    "Staging Package Product execution is unavailable",
                    code="package_product_staging_execution_unavailable",
                )

        claimed: (
            tuple[PackageProductStagingAdoptedRouteRequestV1, PackageLifecycleStatusV1]
            | None
        ) = None

        def prepare(
            receipt: PackageEpochRuntimeAdmissionReceiptV1,
        ) -> tuple[
            PackageProductStagingAdoptedRouteRequestV1, PackageLifecycleStatusV1
        ]:
            nonlocal claimed
            _record, current, route = owner.claim(
                operation_id, max_bytes=max_bytes, admission=receipt
            )
            claimed = route, current
            return claimed

        try:
            return guarded(prepare)
        finally:
            if claimed is not None:
                owner.revoke(*claimed)

    def execute_rebind_decision(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageLifecycleStatusV1:
        """Resume and route one selected decision under the Product epoch guard."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            owner = self._rebind_decision_owner
            guarded = getattr(self.lifecycle, "execute_guarded_rebound", None)
            if owner is None or not callable(guarded):
                raise PackageProductRuntimeActivationError(
                    "Package Product rebound execution is unavailable",
                    code="package_product_rebound_execution_unavailable",
                )

        claimed: (
            tuple[PackageProductReboundRouteRequestV1, PackageLifecycleStatusV1] | None
        ) = None

        def prepare(
            receipt: PackageEpochRuntimeAdmissionReceiptV1,
        ) -> tuple[PackageProductReboundRouteRequestV1, PackageLifecycleStatusV1]:
            nonlocal claimed
            _record, resumed, route = owner.resume(
                operation_id, max_bytes=max_bytes, admission=receipt
            )
            claimed = route, resumed
            return claimed

        try:
            return guarded(prepare)
        finally:
            if claimed is not None:
                owner.revoke(*claimed)

    def recover_unstarted_rebind(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageLifecycleStatusV1:
        """Recover a prior effect-free claim after its admission lease exits."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            owner = self._rebind_decision_owner
            guarded = getattr(self.lifecycle, "execute_guarded_mutation", None)
            if owner is None or not callable(guarded):
                raise PackageProductRuntimeActivationError(
                    "Package Product rebind recovery is unavailable",
                    code="package_product_rebind_recovery_unavailable",
                )
        return guarded(
            lambda receipt: owner.recover_unstarted_claim(
                operation_id, max_bytes=max_bytes, admission=receipt
            )
        )

    def recover_acquired_rebind(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageLifecycleRestartRecordV1:
        """Replay selected root-stage cleanup under the Product guard."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            owner = self._rebind_decision_owner
            guarded = getattr(self.lifecycle, "execute_guarded_mutation", None)
            if owner is None or not callable(guarded):
                raise PackageProductRuntimeActivationError(
                    "Package Product acquired rebind recovery is unavailable",
                    code="package_product_rebind_recovery_unavailable",
                )
        return guarded(
            lambda receipt: owner.recover_acquired_claim(
                operation_id, max_bytes=max_bytes, admission=receipt
            )
        )

    def recover_resolving_rebind(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageLifecycleRestartRecordV1:
        """Replay selected closure-node cleanup under the Product guard."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            owner = self._rebind_decision_owner
            guarded = getattr(self.lifecycle, "execute_guarded_mutation", None)
            if (
                owner is None
                or not callable(guarded)
                or not callable(getattr(owner, "recover_resolving_claim", None))
            ):
                raise PackageProductRuntimeActivationError(
                    "Package Product resolving rebind recovery is unavailable",
                    code="package_product_rebind_recovery_unavailable",
                )
        return guarded(
            lambda receipt: owner.recover_resolving_claim(
                operation_id, max_bytes=max_bytes, admission=receipt
            )
        )

    def recover_verified_rebind(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageLifecycleRestartRecordV1:
        """Replay verified-closure cleanup under the Product guard."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            owner = self._rebind_decision_owner
            guarded = getattr(self.lifecycle, "execute_guarded_mutation", None)
            if (
                owner is None
                or not callable(guarded)
                or not callable(getattr(owner, "recover_verified_claim", None))
            ):
                raise PackageProductRuntimeActivationError(
                    "Package Product verified rebind recovery is unavailable",
                    code="package_product_rebind_recovery_unavailable",
                )
        return guarded(
            lambda receipt: owner.recover_verified_claim(
                operation_id, max_bytes=max_bytes, admission=receipt
            )
        )

    def read_selected_plugin_file(
        self,
        installation_key: PluginInstallationKeyV1,
        logical_path: str,
        *,
        max_bytes: int,
    ) -> bytes:
        """Read data only while this activated Session binding remains live."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            if self._selected_root_reader is None:
                raise PackageProductRuntimeActivationError(
                    "Package Product selected-root reader is unavailable",
                    code="package_product_root_reader_unavailable",
                )
            return self._selected_root_reader.read_selected_file(
                installation_key, logical_path, max_bytes=max_bytes
            )

    def read_selected_plugin_files(
        self,
        installation_key: PluginInstallationKeyV1,
        logical_paths: tuple[str, ...],
        *,
        max_total_bytes: int,
    ) -> tuple[bytes, ...]:
        """Capture a bounded file set while this Session binding is active."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            if self._selected_root_reader is None:
                raise PackageProductRuntimeActivationError(
                    "Package Product selected-root reader is unavailable",
                    code="package_product_root_reader_unavailable",
                )
            return self._selected_root_reader.read_selected_files(
                installation_key, logical_paths, max_total_bytes=max_total_bytes
            )

    def capture_selected_plugin_root(
        self,
        installation_key: PluginInstallationKeyV1,
        *,
        max_files: int,
        max_total_bytes: int,
    ) -> PackageProductSelectedRootSnapshotV1:
        """Capture one complete inert root before runtime package assembly."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            if self._selected_root_reader is None:
                raise PackageProductRuntimeActivationError(
                    "Package Product selected-root reader is unavailable",
                    code="package_product_root_reader_unavailable",
                )
            return self._selected_root_reader.capture_selected_root(
                installation_key,
                max_files=max_files,
                max_total_bytes=max_total_bytes,
            )

    def capture_selected_plugin_manifest(
        self,
        installation_key: PluginInstallationKeyV1,
        *,
        max_files: int,
        max_total_bytes: int,
    ) -> PackageProductSelectedPluginManifestV1:
        """Parse only the manifest bound to this Product's pinned root policy."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            if self._selected_manifest_reader is None:
                raise PackageProductRuntimeActivationError(
                    "Package Product selected-manifest reader is unavailable",
                    code="package_product_manifest_reader_unavailable",
                )
            return self._selected_manifest_reader.capture_selected_manifest(
                installation_key,
                max_files=max_files,
                max_total_bytes=max_total_bytes,
            )

    def capture_selected_plugin_manifest_for(
        self,
        plugin_id: str,
        *,
        max_files: int,
        max_total_bytes: int,
    ) -> PackageProductSelectedPluginManifestV1:
        """Select an installed Plugin through the active Product policy."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            if self._selected_manifest_reader is None:
                raise PackageProductRuntimeActivationError(
                    "Package Product selected-manifest reader is unavailable",
                    code="package_product_manifest_reader_unavailable",
                )
            return self._selected_manifest_reader.capture_selected_manifest_for_plugin(
                plugin_id,
                max_files=max_files,
                max_total_bytes=max_total_bytes,
            )

    def capture_selected_dependency_for_plugin(
        self,
        plugin_id: str,
        *,
        max_files: int,
        max_total_bytes: int,
    ) -> PackageProductSelectedDependencySnapshotV1:
        """Capture bounded, selected dependency bytes as inert Product data."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            if self._selected_dependency_reader is None:
                raise PackageProductRuntimeActivationError(
                    "Package Product selected-dependency reader is unavailable",
                    code="package_product_dependency_reader_unavailable",
                )
            return self._selected_dependency_reader.capture_selected_dependency_for_plugin(
                plugin_id,
                max_files=max_files,
                max_total_bytes=max_total_bytes,
            )

    def assert_selected_dependency_current(
        self, snapshot: PackageProductSelectedDependencySnapshotV1
    ) -> None:
        """Recheck an inert selected dependency snapshot before later use."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            if self._selected_dependency_reader is None:
                raise PackageProductRuntimeActivationError(
                    "Package Product selected-dependency reader is unavailable",
                    code="package_product_dependency_reader_unavailable",
                )
            self._selected_dependency_reader.assert_selected_dependency_current(
                snapshot
            )

    def capture_selected_dependency_closure_for_plugin(
        self,
        plugin_id: str,
        *,
        max_dependencies: int,
        max_files_per_dependency: int,
        max_total_bytes: int,
    ) -> PackageProductSelectedDependencyClosureSnapshotV1:
        """Capture every selected dependency under one Product GC read guard."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            if self._selected_dependency_reader is None:
                raise PackageProductRuntimeActivationError(
                    "Package Product selected-dependency reader is unavailable",
                    code="package_product_dependency_reader_unavailable",
                )
            return self._selected_dependency_reader.capture_selected_dependency_closure_for_plugin(
                plugin_id,
                max_dependencies=max_dependencies,
                max_files_per_dependency=max_files_per_dependency,
                max_total_bytes=max_total_bytes,
            )

    def assert_selected_dependency_closure_current(
        self, snapshot: PackageProductSelectedDependencyClosureSnapshotV1
    ) -> None:
        """Recheck the entire selected closure without granting a runtime lease."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            if self._selected_dependency_reader is None:
                raise PackageProductRuntimeActivationError(
                    "Package Product selected-dependency reader is unavailable",
                    code="package_product_dependency_reader_unavailable",
                )
            self._selected_dependency_reader.assert_selected_dependency_closure_current(
                snapshot
            )

    def capture_plugin_desired_selection_for(
        self, plugin_id: str
    ) -> PackageProductPluginDesiredSelectionV1:
        """Capture one Product-owned Desired selection without Source fallback."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            if self._selected_manifest_reader is None:
                raise PackageProductRuntimeActivationError(
                    "Package Product desired-selection reader is unavailable",
                    code="package_product_manifest_reader_unavailable",
                )
            return self._selected_manifest_reader.capture_plugin_desired_selection_for(
                plugin_id
            )

    def assert_plugin_desired_selection_current(
        self, selected: PackageProductPluginDesiredSelectionV1
    ) -> None:
        if not isinstance(selected, PackageProductPluginDesiredSelectionV1):
            raise TypeError("Product Plugin desired selection is required")
        current = self.capture_plugin_desired_selection_for(
            selected.installation_key.plugin_id
        )
        if current != selected:
            raise PackageProductRuntimeActivationError(
                "Package Product desired selection changed",
                code="package_product_desired_selection_changed",
            )

    def selected_external_data_plugin_ids(self) -> tuple[str, ...]:
        """List enabled, Product-bound local data roots for Session capture."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            if self._selected_manifest_reader is None:
                raise PackageProductRuntimeActivationError(
                    "Package Product selected-manifest reader is unavailable",
                    code="package_product_manifest_reader_unavailable",
                )
            return self._selected_manifest_reader.selected_external_data_plugin_ids()

    def assert_selected_plugin_manifest_current(
        self, selected: PackageProductSelectedPluginManifestV1
    ) -> None:
        """Fail closed when a Session's pinned Product selection has changed."""

        with self._dispose_lock:
            if self._disposed or not self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Package Product runtime is inactive",
                    code="package_product_runtime_inactive",
                )
            if self._selected_manifest_reader is None:
                raise PackageProductRuntimeActivationError(
                    "Package Product selected-manifest reader is unavailable",
                    code="package_product_manifest_reader_unavailable",
                )
            self._selected_manifest_reader.assert_selected_manifest_current(selected)

    def dispose_runtime(self) -> None:
        """Release the Product-owned runtime authority at most once."""

        with self._dispose_lock:
            if self._disposed:
                return
            if self.on_dispose is not None:
                self.on_dispose()
            object.__setattr__(self, "_disposed", True)

    def recover_committed_handoff_exact(
        self, operation_id: str
    ) -> PackageProductExactHandoffRecoveryV1:
        """Recover one Package handoff before ordinary runtime activation."""

        if type(operation_id) is not str or not operation_id:
            raise ValueError("Exact Package handoff operation ID is required")
        with self._dispose_lock:
            if self._disposed or self.lifecycle.active:
                raise PackageProductRuntimeActivationError(
                    "Exact Package handoff requires an unused runtime",
                    code="package_product_exact_recovery_runtime_unavailable",
                )
            recover = getattr(self.lifecycle, "recover_handoff_exact", None)
            if not callable(recover):
                raise PackageProductRuntimeActivationError(
                    "Exact Package handoff recovery is unavailable",
                    code="package_product_exact_recovery_unavailable",
                )
        result = recover(operation_id)
        if (
            type(result) is not PackageProductExactHandoffRecoveryV1
            or result.operation_id != operation_id
        ):
            raise PackageProductRuntimeActivationError(
                "Exact Package handoff recovery changed operation",
                code="package_product_exact_recovery_invalid",
            )
        return result

    def activate(self) -> PackageProductRuntimeBindingV1:
        """Activate recovery/admission and re-attest the aggregate afterwards."""

        try:
            self.lifecycle.activate()
            active = self.lifecycle.active
            lifecycle_binding = self.lifecycle.binding_id
            inventory_binding = self.inventory.binding_id
        except BaseException as error:
            raise PackageProductRuntimeActivationError(
                "Package Product runtime activation failed",
                code="package_product_runtime_activation_failed",
            ) from error
        if not active:
            raise PackageProductRuntimeActivationError(
                "Package Product lifecycle did not become active",
                code="package_product_runtime_activation_incomplete",
            )
        if inventory_binding != lifecycle_binding:
            raise PackageProductRuntimeActivationError(
                "Package Product runtime owners changed binding",
                code="package_product_runtime_binding_changed",
            )
        return self


class PackageProductRuntimeFactoryPort(Protocol):
    """Product policy seam that constructs one aggregate runtime per Session."""

    def create(
        self,
        request: PackageProductRuntimeRequestV1,
    ) -> PackageProductRuntimeBindingV1: ...


def activate_package_product_runtime(
    factory: PackageProductRuntimeFactoryPort,
    request: PackageProductRuntimeRequestV1,
) -> PackageProductRuntimeBindingV1:
    """Create exactly once, validate exactly, then activate before bootstrap."""

    create = getattr(factory, "create", None)
    if not callable(create):
        raise TypeError("Package Product runtime factory is required")
    try:
        binding = create(request)
    except BaseException as error:
        failure = PackageProductRuntimeActivationError(
            "Package Product runtime factory failed",
            code="package_product_runtime_factory_failed",
        )
        _dispose_unbound_factory_after_failure(factory, failure)
        raise failure from error
    if not isinstance(binding, PackageProductRuntimeBindingV1):
        failure = PackageProductRuntimeActivationError(
            "Package Product runtime factory returned an invalid binding",
            code="package_product_runtime_binding_invalid",
        )
        _dispose_unbound_factory_after_failure(factory, failure)
        raise failure
    if binding.product_id != request.product_id:
        failure = PackageProductRuntimeActivationError(
            "Package Product runtime changed Product identity",
            code="package_product_runtime_product_changed",
        )
        _dispose_after_failure(binding, failure)
        raise failure
    try:
        return binding.activate()
    except BaseException as failure:
        _dispose_after_failure(binding, failure)
        raise


def _dispose_after_failure(
    binding: PackageProductRuntimeBindingV1, failure: BaseException
) -> None:
    try:
        binding.dispose_runtime()
    except BaseException:
        failure.add_note("Package Product runtime cleanup also failed")


def _dispose_unbound_factory_after_failure(
    factory: PackageProductRuntimeFactoryPort, failure: BaseException
) -> None:
    dispose = getattr(factory, "dispose_unbound_runtime", None)
    if callable(dispose):
        try:
            dispose()
        except BaseException:
            failure.add_note("Package Product runtime cleanup also failed")


__all__ = [
    "PACKAGE_PRODUCT_RUNTIME_BINDING_VERSION",
    "PACKAGE_PRODUCT_RUNTIME_REQUEST_VERSION",
    "PackageProductRuntimeActivationError",
    "PackageProductRuntimeBindingV1",
    "PackageProductRuntimeFactoryPort",
    "PackageProductRuntimeRequestV1",
    "PackageProductPluginDesiredSelectionV1",
    "PackageProductSelectedManifestReadPort",
    "PackageProductSelectedRootReadPort",
    "activate_package_product_runtime",
]
