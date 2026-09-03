"""Session-bound package catalog and lifecycle operations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, cast
from uuid import uuid4

from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.resources.loader import ResourceLoader
from loushang.harness.resources.packages.catalog import (
    PackageSummaryProvider,
    collect_package_catalog,
)
from loushang.harness.resources.packages.catalog_diagnostics import (
    PackageCatalogDiagnosticsRecorder,
)
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.packages.operations import (
    PackageMutationRequiresAsyncError,
    PackageOperationRecord,
    PackageOperationsRuntime,
    PackageResourceRefreshOutcome,
    PackageResourceRefreshTransactionRunner,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductEntrypoint,
    PackageProductLifecycleAction,
    PackageProductLifecycleInventoryPort,
    PackageProductLifecycleMode,
    PackageProductLifecycleOperationPort,
    PackageProductUpdateCheckRequestV1,
    PackageProductUpdateCheckV1,
    canonicalize_package_product_scope,
)
from loushang.harness.resources.packages.projection import (
    project_package_entries,
    serialize_package_operation_record,
)
from loushang.harness.resources.packages.roots import (
    ResourceRootSettingsManager,
    ResourceRootSettingsSnapshot,
    SelectedPluginPackageInput,
    configure_resource_loader_roots,
)
from loushang.harness.resources.packages.settings_mutation import (
    PackageSourceSettingsMutation,
)
from loushang.harness.resources.packages.source import PackageSourceConfig
from loushang.harness.resources.packages.source_resolver import PackageSourceResolver

SettingsScope = Literal["global", "project", "session"]


class SessionPackageSettings(ResourceRootSettingsSnapshot, Protocol):
    package_roots: tuple[str, ...]
    plugin_sources: tuple[str, ...]
    package_sources: tuple[PackageSourceConfig, ...]
    disabled_plugins: tuple[str, ...]


class SessionPackageSettingsManager(ResourceRootSettingsManager, Protocol):
    def get_settings(self) -> SessionPackageSettings: ...

    def begin_package_source_mutation(
        self,
        source: str,
        *,
        scope: SettingsScope,
        present: bool,
    ) -> PackageSourceSettingsMutation: ...


SettingsManagerProvider = Callable[[], SessionPackageSettingsManager | None]
PackageMaterializerProvider = Callable[[], PackageMaterializer | None]
ResourceLoaderProvider = Callable[[], ResourceLoader | None]
DiagnosticsServiceProvider = Callable[[], DiagnosticsService | None]
ResourceRefresh = Callable[[], object | Awaitable[object]]


@dataclass
class SessionPackageController:
    """Bind shared package operations to one Product session."""

    get_session_id: Callable[[], str]
    get_cwd: Callable[[], str]
    get_settings_manager: SettingsManagerProvider
    get_package_materializer: PackageMaterializerProvider
    get_resource_loader: ResourceLoaderProvider
    get_diagnostics_service: DiagnosticsServiceProvider
    refresh_resources: ResourceRefresh
    selected_plugin_packages: tuple[SelectedPluginPackageInput, ...] = ()
    refresh_resource_transaction: PackageResourceRefreshTransactionRunner | None = None
    summary_provider: PackageSummaryProvider | None = None
    product_lifecycle: PackageProductLifecycleOperationPort | None = None
    product_inventory: PackageProductLifecycleInventoryPort | None = None
    product_lifecycle_mode: PackageProductLifecycleMode = "legacy"
    supports_synchronous_refresh: Callable[[], bool] = lambda: True
    _operations: PackageOperationsRuntime = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.selected_plugin_packages = tuple(self.selected_plugin_packages)
        if any(
            not isinstance(item, SelectedPluginPackageInput)
            for item in self.selected_plugin_packages
        ):
            raise TypeError("Selected Plugin package inputs are invalid")
        self._operations = PackageOperationsRuntime(
            get_materializer=self.get_package_materializer,
            add_source=self._add_package_source,
            remove_source=self._remove_package_source,
            refresh_resources=self.refresh_package_resources,
            prepare_updates=self.prepare_configured_remote_package_records,
            refresh_transaction=self.refresh_resource_transaction,
            product_lifecycle=self.product_lifecycle,
            product_inventory=self.product_inventory,
            product_lifecycle_mode=self.product_lifecycle_mode,
        )

    @property
    def session_id(self) -> str:
        return self.get_session_id()

    def get_packages(
        self, *, catalog_path: str | None = None
    ) -> list[dict[str, object]]:
        settings_manager = self.get_settings_manager()
        if settings_manager is None:
            return []
        settings = settings_manager.get_settings()
        entries = collect_package_catalog(
            package_roots=tuple(settings.package_roots),
            plugin_sources=tuple(settings.plugin_sources),
            package_sources=tuple(settings.package_sources),
            disabled_plugins=tuple(settings.disabled_plugins),
            cwd=Path(self.get_cwd()),
            settings_manager=settings_manager,
            catalog_path=(
                Path(catalog_path).expanduser().resolve() if catalog_path else None
            ),
            materializer=self.get_package_materializer(),
            summary_provider=self.summary_provider,
        )
        PackageCatalogDiagnosticsRecorder(
            diagnostics_service=self.get_diagnostics_service(),
            session_id=self.session_id,
        ).record(entries)
        return project_package_entries(entries)

    async def materialize_package(self, source: str) -> dict[str, object]:
        return serialize_package_operation_record(
            await self._operations.materialize(source, entrypoint="session")
        )

    async def install_package(
        self, source: str, *, scope: str = "project"
    ) -> dict[str, object]:
        return serialize_package_operation_record(
            await self._operations.install(source, scope=scope, entrypoint="session")
        )

    async def update_package(self, source: str) -> dict[str, object]:
        return serialize_package_operation_record(
            await self._operations.update(source, entrypoint="session")
        )

    async def update_packages(
        self,
        *,
        operation_id: str | None = None,
        scope: str = "project",
    ) -> list[dict[str, object]]:
        records = await self._operations.update_all(
            entrypoint="session",
            operation_id=operation_id,
            scope=scope,
        )
        return [serialize_package_operation_record(record) for record in records]

    @property
    def package_product_binding_id(self) -> str | None:
        lifecycle = self.product_lifecycle
        return None if lifecycle is None else lifecycle.binding_id

    @property
    def package_product_lifecycle_mode(self) -> PackageProductLifecycleMode:
        return self.product_lifecycle_mode

    async def check_package_updates(
        self,
        *,
        scope: str = "project",
        operation_id: str | None = None,
        entrypoint: PackageProductEntrypoint = "session",
    ) -> list[dict[str, object]]:
        if self.product_lifecycle is not None:
            lifecycle = self.product_lifecycle
            inventory = self.product_inventory
            if inventory is None:
                raise RuntimeError("Package Product update inventory is not available")
            canonical_scope = canonicalize_package_product_scope(scope)
            request = PackageProductUpdateCheckRequestV1(
                operation_id=operation_id or uuid4().hex,
                entrypoint=entrypoint,
                scope=canonical_scope,
            )

            async def check_inventory() -> tuple[PackageProductUpdateCheckV1, ...]:
                if inventory.binding_id != lifecycle.binding_id:
                    raise RuntimeError(
                        "Package Product inventory owner changed after composition"
                    )
                product_updates = await inventory.check_updates(request=request)
                if not isinstance(product_updates, tuple) or any(
                    not isinstance(update, PackageProductUpdateCheckV1)
                    or update.scope != canonical_scope
                    for update in product_updates
                ):
                    raise RuntimeError("Package Product update checks are invalid")
                if inventory.binding_id != lifecycle.binding_id:
                    raise RuntimeError(
                        "Package Product inventory owner changed after composition"
                    )
                return product_updates

            product_updates = await lifecycle.execute_guarded_query(check_inventory)
            return [update.to_dict() for update in product_updates]
        materializer = self.get_package_materializer()
        if materializer is None:
            raise RuntimeError("Package materializer is not available.")
        await self.prepare_configured_remote_package_records()
        updates = await materializer.check_package_updates()
        self.record_package_update_check_diagnostics(updates)
        return updates

    def remove_package(self, source: str) -> dict[str, object]:
        return serialize_package_operation_record(
            self._operations.remove(source, entrypoint="session")
        )

    def uninstall_package(
        self, source: str, *, scope: str = "project"
    ) -> dict[str, object]:
        if not self.supports_synchronous_refresh():
            raise PackageMutationRequiresAsyncError(
                "Catalog-backed package uninstall requires uninstall_package_async()"
            )
        return serialize_package_operation_record(
            self._operations.uninstall_sync(
                source,
                scope=scope,
                entrypoint="session",
            )
        )

    async def uninstall_package_async(
        self, source: str, *, scope: str = "project"
    ) -> dict[str, object]:
        return serialize_package_operation_record(
            await self._operations.uninstall(
                source,
                scope=scope,
                entrypoint="session",
            )
        )

    async def execute_package_lifecycle(
        self,
        action: PackageProductLifecycleAction,
        source: str,
        *,
        entrypoint: PackageProductEntrypoint,
        operation_id: str,
        scope: str = "project",
    ) -> dict[str, object]:
        """Route one explicitly correlated transport request exactly once."""

        record: PackageOperationRecord
        if action == "materialize":
            record = await self._operations.materialize(
                source,
                entrypoint=entrypoint,
                operation_id=operation_id,
                scope=scope,
            )
        elif action == "install":
            record = await self._operations.install(
                source,
                scope=scope,
                entrypoint=entrypoint,
                operation_id=operation_id,
            )
        elif action == "update":
            record = await self._operations.update(
                source,
                entrypoint=entrypoint,
                operation_id=operation_id,
                scope=scope,
            )
        elif action == "remove":
            record = self._operations.remove(
                source,
                entrypoint=entrypoint,
                operation_id=operation_id,
                scope=scope,
            )
        elif action == "uninstall":
            record = await self._operations.uninstall(
                source,
                scope=scope,
                entrypoint=entrypoint,
                operation_id=operation_id,
            )
        else:
            raise ValueError("Unsupported Package lifecycle action")
        return serialize_package_operation_record(record)

    async def execute_package_lifecycle_collection(
        self,
        action: Literal["update", "check"],
        *,
        entrypoint: PackageProductEntrypoint,
        operation_id: str,
        scope: str = "project",
    ) -> list[dict[str, object]]:
        """Route one correlated Product bulk operation into stable child ids."""

        if action == "update":
            records = await self._operations.update_all(
                entrypoint=entrypoint,
                operation_id=operation_id,
                scope=scope,
            )
            return [serialize_package_operation_record(record) for record in records]
        if action == "check":
            return await self.check_package_updates(
                scope=scope,
                operation_id=operation_id,
                entrypoint=entrypoint,
            )
        raise ValueError("Unsupported Package lifecycle collection action")

    def _add_package_source(
        self,
        source: str,
        scope: str,
    ) -> PackageSourceSettingsMutation:
        return self._begin_package_source_mutation(
            source,
            scope=scope,
            present=True,
        )

    def _remove_package_source(
        self,
        source: str,
        scope: str,
    ) -> PackageSourceSettingsMutation:
        return self._begin_package_source_mutation(
            source,
            scope=scope,
            present=False,
        )

    def _begin_package_source_mutation(
        self,
        source: str,
        *,
        scope: str,
        present: bool,
    ) -> PackageSourceSettingsMutation:
        settings_manager = self.get_settings_manager()
        if settings_manager is None:
            return PackageSourceSettingsMutation(
                source=source,
                scope=scope,
                changed=False,
                restore=lambda: None,
            )
        if scope == "user":
            scope = "global"
        if scope not in {"global", "project", "session"}:
            raise ValueError("Unsupported Package settings scope")
        resolved_scope = cast(SettingsScope, scope)
        return settings_manager.begin_package_source_mutation(
            source,
            scope=resolved_scope,
            present=present,
        )

    def refresh_package_resources(self) -> object | Awaitable[object]:
        if self.get_resource_loader() is None:
            return PackageResourceRefreshOutcome(published=True)
        self.configure_package_resource_roots()
        return self.refresh_resources()

    async def prepare_configured_remote_package_records(self) -> None:
        settings_manager = self.get_settings_manager()
        materializer = self.get_package_materializer()
        if settings_manager is None or materializer is None:
            return
        PackageSourceResolver(
            settings_manager=settings_manager,
            materializer=materializer,
            diagnostics_service=self.get_diagnostics_service(),
            session_id=self.session_id,
        ).prepare_configured_remote_records()

    def record_package_update_check_diagnostics(
        self, updates: list[dict[str, object]]
    ) -> None:
        diagnostics_service = self.get_diagnostics_service()
        if diagnostics_service is None:
            return
        for update in updates:
            if update.get("status") != "check_failed":
                continue
            diagnostics_service.capture_failure(
                code="package_update_check_failed",
                error=str(update.get("reason") or "Package update check failed."),
                phase="runtime",
                source="package",
                level="warning",
                session_id=self.session_id,
                details={
                    "package_source": str(update.get("source") or ""),
                    "package_name": str(update.get("name") or ""),
                    "current_commit": str(update.get("currentCommit") or ""),
                    "installed_commit": str(update.get("installedCommit") or ""),
                    "resolved_commit": str(update.get("resolvedCommit") or ""),
                    "requested_ref": str(update.get("requestedRef") or ""),
                    "available_ref": str(update.get("availableRef") or ""),
                    "dirty": bool(update.get("dirty")),
                    "pinned": bool(update.get("pinned")),
                },
            )

    def configure_package_resource_roots(self) -> None:
        resource_loader = self.get_resource_loader()
        settings_manager = self.get_settings_manager()
        materializer = self.get_package_materializer()
        if resource_loader is None or settings_manager is None:
            return
        if materializer is not None:
            configure_resource_loader_roots(
                resource_loader=resource_loader,
                settings_manager=settings_manager,
                materializer=materializer,
                diagnostics_service=self.get_diagnostics_service(),
                session_id=self.session_id,
                selected_plugin_packages=self.selected_plugin_packages,
            )


__all__ = ["SessionPackageController"]
