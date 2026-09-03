"""Product-bound package operation lifecycle coordination."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar
from uuid import uuid4

from loushang.harness.resources.packages.materializer import (
    PackageMaterializationRecord,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductEntrypoint,
    PackageProductLifecycleAction,
    PackageProductLifecycleIntentV1,
    PackageProductLifecycleOperationPort,
    PackageProductLifecycleRecordV1,
)
from loushang.harness.resources.packages.settings_mutation import (
    PackageSourceSettingsMutation,
)
from loushang.harness.resources.packages.source import is_remote_package_source

T = TypeVar("T")


class PackageMaterializerPort(Protocol):
    """Minimal materializer operations needed by the session lifecycle."""

    async def materialize_remote_source(
        self, source: str
    ) -> PackageMaterializationRecord: ...

    async def update_remote_source(
        self, source: str
    ) -> PackageMaterializationRecord: ...

    async def update_all_remote_sources(
        self,
    ) -> list[PackageMaterializationRecord]: ...

    def remove_remote_source(self, source: str) -> PackageMaterializationRecord: ...

    def forget_remote_source(self, source: str) -> None: ...

    def list_records(self) -> list[PackageMaterializationRecord]: ...


PackageMaterializerProvider = Callable[[], PackageMaterializerPort | None]
PackageSourceRegistration = Callable[[str, str], PackageSourceSettingsMutation]
PackageResourceRefresh = Callable[[], object | Awaitable[object]]
PackageUpdatePreparation = Callable[[], object | Awaitable[object]]
PackageOperationRecord = PackageMaterializationRecord | PackageProductLifecycleRecordV1


@dataclass(frozen=True, slots=True)
class PackageResourceRefreshOutcome:
    """Per-call proof of whether this package mutation crossed publication."""

    published: bool
    error: BaseException | None = None
    settled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.published, bool):
            raise TypeError("Package Resource refresh publication flag must be a bool")
        if self.error is not None and not isinstance(self.error, BaseException):
            raise TypeError("Package Resource refresh error is invalid")
        if not isinstance(self.settled, bool):
            raise TypeError("Package Resource settlement flag must be a bool")
        if not self.settled and self.error is None:
            raise ValueError(
                "Unsettled Package Resource refresh requires an error"
            )


@dataclass(frozen=True, slots=True)
class PackageResourceRefreshTransaction:
    """Package-owned mutation hooks executed by the Catalog transaction port."""

    begin: Callable[[], PackageSourceSettingsMutation]
    settle: Callable[
        [PackageSourceSettingsMutation, PackageResourceRefreshOutcome], None
    ]

    def __post_init__(self) -> None:
        if not callable(self.begin) or not callable(self.settle):
            raise TypeError("Package Resource refresh transaction hooks are invalid")


PackageResourceRefreshTransactionRunner = Callable[
    [PackageResourceRefreshTransaction], object | Awaitable[object]
]


class PackageMutationRequiresAsyncError(RuntimeError):
    """A Catalog-backed package mutation cannot publish synchronously."""


@dataclass
class PackageOperationsRuntime:
    """Coordinate package materialization and Product-bound source activation."""

    get_materializer: PackageMaterializerProvider
    add_source: PackageSourceRegistration
    remove_source: PackageSourceRegistration
    refresh_resources: PackageResourceRefresh
    prepare_updates: PackageUpdatePreparation | None = None
    refresh_transaction: PackageResourceRefreshTransactionRunner | None = None
    product_lifecycle: PackageProductLifecycleOperationPort | None = None
    _settings_transaction_lock: asyncio.Lock = field(
        init=False,
        default_factory=asyncio.Lock,
        repr=False,
    )

    async def materialize(
        self,
        source: str,
        *,
        entrypoint: PackageProductEntrypoint = "operations",
        operation_id: str | None = None,
        scope: str = "project",
    ) -> PackageOperationRecord:
        routed = self._route_product(
            action="materialize",
            source=source,
            scope=scope,
            entrypoint=entrypoint,
            operation_id=operation_id,
        )
        if routed is not None:
            return routed
        return await self._materialize_legacy(source)

    async def install(
        self,
        source: str,
        *,
        scope: str,
        entrypoint: PackageProductEntrypoint = "operations",
        operation_id: str | None = None,
    ) -> PackageOperationRecord:
        routed = self._route_product(
            action="install",
            source=source,
            scope=scope,
            entrypoint=entrypoint,
            operation_id=operation_id,
        )
        if routed is not None:
            return routed
        record = await self._materialize_legacy(source)
        if record.lifecycle != "installed":
            return record
        async with self._settings_transaction_lock:
            outcome = await self._refresh_settings_mutation(
                lambda: self.add_source(source, scope)
            )
            _raise_refresh_error(outcome)
        return record

    async def update(
        self,
        source: str,
        *,
        entrypoint: PackageProductEntrypoint = "operations",
        operation_id: str | None = None,
        scope: str = "project",
    ) -> PackageOperationRecord:
        routed = self._route_product(
            action="update",
            source=source,
            scope=scope,
            entrypoint=entrypoint,
            operation_id=operation_id,
        )
        if routed is not None:
            return routed
        if not is_remote_package_source(source):
            record = await self._materialize_legacy(source)
        else:
            materializer = self._require_materializer()
            record = await materializer.update_remote_source(source)
        _raise_refresh_error(await self._refresh_outcome())
        return record

    async def update_all(
        self,
        *,
        entrypoint: PackageProductEntrypoint = "operations",
        scope: str = "project",
    ) -> list[PackageOperationRecord]:
        if self.prepare_updates is not None:
            await _resolve(self.prepare_updates())
        materializer = self._require_materializer()
        if self.product_lifecycle is not None:
            records = materializer.list_records()
            return [
                await self.update(
                    record.source,
                    entrypoint=entrypoint,
                    scope=scope,
                )
                for record in records
                if record.lifecycle == "installed"
            ]
        legacy_records: list[PackageOperationRecord] = [
            record for record in await materializer.update_all_remote_sources()
        ]
        _raise_refresh_error(await self._refresh_outcome())
        return legacy_records

    def remove(
        self,
        source: str,
        *,
        entrypoint: PackageProductEntrypoint = "operations",
        operation_id: str | None = None,
        scope: str = "project",
    ) -> PackageOperationRecord:
        routed = self._route_product(
            action="remove",
            source=source,
            scope=scope,
            entrypoint=entrypoint,
            operation_id=operation_id,
        )
        if routed is not None:
            return routed
        return self._remove_legacy(source)

    def _remove_legacy(self, source: str) -> PackageMaterializationRecord:
        if not is_remote_package_source(source):
            path = Path(source).expanduser().resolve()
            return PackageMaterializationRecord(
                source=source,
                name=path.name,
                lifecycle="remote_registered",
                target_path=path,
            )
        return self._require_materializer().remove_remote_source(source)

    async def uninstall(
        self,
        source: str,
        *,
        scope: str,
        entrypoint: PackageProductEntrypoint = "operations",
        operation_id: str | None = None,
    ) -> PackageOperationRecord:
        routed = self._route_product(
            action="uninstall",
            source=source,
            scope=scope,
            entrypoint=entrypoint,
            operation_id=operation_id,
        )
        if routed is not None:
            return routed
        async with self._settings_transaction_lock:
            outcome = await self._refresh_settings_mutation(
                lambda: self.remove_source(source, scope)
            )
            if outcome.published and outcome.settled:
                record = self._remove_materialized_source(source, outcome=outcome)
            else:
                record = self._uninstalled_record(source)
            _raise_refresh_error(outcome)
            return record

    def uninstall_sync(
        self,
        source: str,
        *,
        scope: str,
        entrypoint: PackageProductEntrypoint = "operations",
        operation_id: str | None = None,
    ) -> PackageOperationRecord:
        """Preserve the legacy synchronous contract behind an explicit gate."""

        routed = self._route_product(
            action="uninstall",
            source=source,
            scope=scope,
            entrypoint=entrypoint,
            operation_id=operation_id,
        )
        if routed is not None:
            return routed

        outcome = self._refresh_settings_mutation_sync(
            lambda: self.remove_source(source, scope)
        )
        if outcome.published and outcome.settled:
            record = self._remove_materialized_source(source, outcome=outcome)
        else:
            record = self._uninstalled_record(source)
        _raise_refresh_error(outcome)
        return record

    async def _refresh_outcome(self) -> PackageResourceRefreshOutcome:
        try:
            refreshed = await _resolve(self.refresh_resources())
        except BaseException as error:
            return PackageResourceRefreshOutcome(published=False, error=error)
        return _coerce_refresh_outcome(refreshed)

    async def _refresh_settings_mutation(
        self,
        begin: Callable[[], PackageSourceSettingsMutation],
    ) -> PackageResourceRefreshOutcome:
        transaction_runner = self.refresh_transaction
        if transaction_runner is None:
            mutation = begin()
            outcome = await self._refresh_outcome()
            self._finish_settings_mutation(mutation, outcome=outcome)
            return outcome
        transaction = PackageResourceRefreshTransaction(
            begin=begin,
            settle=lambda mutation, outcome: self._finish_settings_mutation(
                mutation,
                outcome=outcome,
            ),
        )
        try:
            refreshed = await _resolve(transaction_runner(transaction))
        except BaseException as error:
            return PackageResourceRefreshOutcome(published=False, error=error)
        return _coerce_refresh_outcome(refreshed)

    def _refresh_settings_mutation_sync(
        self,
        begin: Callable[[], PackageSourceSettingsMutation],
    ) -> PackageResourceRefreshOutcome:
        transaction_runner = self.refresh_transaction
        if transaction_runner is None:
            mutation = begin()
            try:
                refreshed = self.refresh_resources()
            except BaseException as error:
                outcome = PackageResourceRefreshOutcome(
                    published=False,
                    error=error,
                )
            else:
                if inspect.isawaitable(refreshed):
                    if inspect.iscoroutine(refreshed):
                        refreshed.close()
                    mutation.rollback()
                    raise PackageMutationRequiresAsyncError(
                        "Catalog-backed package uninstall requires "
                        "uninstall_package_async()"
                    )
                outcome = _coerce_refresh_outcome(refreshed)
            self._finish_settings_mutation(mutation, outcome=outcome)
            return outcome

        transaction = PackageResourceRefreshTransaction(
            begin=begin,
            settle=lambda mutation, outcome: self._finish_settings_mutation(
                mutation,
                outcome=outcome,
            ),
        )
        try:
            refreshed = transaction_runner(transaction)
        except BaseException as error:
            return PackageResourceRefreshOutcome(published=False, error=error)
        if inspect.isawaitable(refreshed):
            if inspect.iscoroutine(refreshed):
                refreshed.close()
            raise PackageMutationRequiresAsyncError(
                "Catalog-backed package uninstall requires "
                "uninstall_package_async()"
            )
        return _coerce_refresh_outcome(refreshed)

    @staticmethod
    def _finish_settings_mutation(
        mutation: PackageSourceSettingsMutation,
        *,
        outcome: PackageResourceRefreshOutcome,
    ) -> None:
        if outcome.published:
            mutation.commit()
        else:
            try:
                mutation.rollback()
            except BaseException as rollback_error:
                if outcome.error is None:
                    raise
                outcome.error.add_note(
                    "Package source settings rollback also failed: "
                    f"{rollback_error!r}"
                )

    def _remove_materialized_source(
        self,
        source: str,
        *,
        outcome: PackageResourceRefreshOutcome,
    ) -> PackageMaterializationRecord:
        try:
            record = self._remove_legacy(source)
            if record.lifecycle == "failed":
                raise RuntimeError(
                    record.error_message or "Package materialization cleanup failed"
                )
            self._forget_remote_source(source)
        except BaseException as cleanup_error:
            if outcome.error is None:
                raise
            outcome.error.add_note(
                f"Published package uninstall cleanup also failed: {cleanup_error!r}"
            )
            return self._uninstalled_record(source)
        return record

    def _uninstalled_record(self, source: str) -> PackageMaterializationRecord:
        if not is_remote_package_source(source):
            path = Path(source).expanduser().resolve()
            return PackageMaterializationRecord(
                source=source,
                name=path.name,
                lifecycle="remote_registered",
                target_path=path,
            )
        materializer = self.get_materializer()
        record = (
            None
            if materializer is None
            else getattr(materializer, "get_record", lambda _source: None)(source)
        )
        if isinstance(record, PackageMaterializationRecord):
            return record.with_lifecycle("remote_registered")
        return PackageMaterializationRecord(
            source=source,
            name=Path(source.rstrip("/")).stem or "package",
            lifecycle="remote_registered",
            target_path=Path("."),
        )

    def _forget_remote_source(self, source: str) -> None:
        materializer = self.get_materializer()
        if materializer is not None:
            materializer.forget_remote_source(source)

    def _require_materializer(self) -> PackageMaterializerPort:
        materializer = self.get_materializer()
        if materializer is None:
            raise RuntimeError("Package materializer is not available.")
        return materializer

    async def _materialize_legacy(self, source: str) -> PackageMaterializationRecord:
        if is_remote_package_source(source):
            return await self._require_materializer().materialize_remote_source(source)
        path = Path(source).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Package path does not exist: {path}")
        return PackageMaterializationRecord(
            source=source,
            name=path.name,
            lifecycle="installed",
            target_path=path,
        )

    def _route_product(
        self,
        *,
        action: PackageProductLifecycleAction,
        source: str,
        scope: str,
        entrypoint: PackageProductEntrypoint,
        operation_id: str | None,
    ) -> PackageProductLifecycleRecordV1 | None:
        lifecycle = self.product_lifecycle
        if lifecycle is None:
            return None
        intent = PackageProductLifecycleIntentV1(
            operation_id=operation_id or uuid4().hex,
            action=action,
            source=source,
            scope=scope,
        )
        outcome = lifecycle.route(intent, entrypoint=entrypoint)
        if not outcome.handled:
            return None
        if outcome.record is None:
            raise RuntimeError("Plugin Package route returned no Product record")
        return outcome.record


async def _resolve(value: T | Awaitable[T]) -> T:
    if inspect.isawaitable(value):
        return await value
    return value


def _coerce_refresh_outcome(value: object) -> PackageResourceRefreshOutcome:
    if value is None:
        return PackageResourceRefreshOutcome(published=True)
    if isinstance(value, PackageResourceRefreshOutcome):
        return value
    return PackageResourceRefreshOutcome(
        published=False,
        error=TypeError("Package Resource refresh returned an invalid outcome"),
    )


def _raise_refresh_error(outcome: PackageResourceRefreshOutcome) -> None:
    if outcome.error is not None:
        raise outcome.error


__all__ = [
    "PackageMaterializerPort",
    "PackageMaterializerProvider",
    "PackageOperationRecord",
    "PackageOperationsRuntime",
    "PackageMutationRequiresAsyncError",
    "PackageResourceRefresh",
    "PackageResourceRefreshOutcome",
    "PackageResourceRefreshTransaction",
    "PackageResourceRefreshTransactionRunner",
    "PackageSourceRegistration",
    "PackageUpdatePreparation",
]
