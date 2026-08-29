"""Product-bound package operation lifecycle coordination."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar

from loushang.harness.resources.packages.materializer import (
    PackageMaterializationRecord,
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


PackageMaterializerProvider = Callable[[], PackageMaterializerPort | None]
PackageSourceRegistration = Callable[[str, str], PackageSourceSettingsMutation]
PackageResourceRefresh = Callable[[], object | Awaitable[object]]
PackageUpdatePreparation = Callable[[], object | Awaitable[object]]


@dataclass(frozen=True, slots=True)
class PackageResourceRefreshOutcome:
    """Per-call proof of whether this package mutation crossed publication."""

    published: bool
    error: BaseException | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.published, bool):
            raise TypeError("Package Resource refresh publication flag must be a bool")
        if self.error is not None and not isinstance(self.error, BaseException):
            raise TypeError("Package Resource refresh error is invalid")


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
    _settings_transaction_lock: asyncio.Lock = field(
        init=False,
        default_factory=asyncio.Lock,
        repr=False,
    )

    async def materialize(self, source: str) -> PackageMaterializationRecord:
        if is_remote_package_source(source):
            materializer = self._require_materializer()
            return await materializer.materialize_remote_source(source)

        path = Path(source).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Package path does not exist: {path}")
        return PackageMaterializationRecord(
            source=source,
            name=path.name,
            lifecycle="installed",
            target_path=path,
        )

    async def install(
        self,
        source: str,
        *,
        scope: str,
    ) -> PackageMaterializationRecord:
        record = await self.materialize(source)
        if record.lifecycle != "installed":
            return record
        async with self._settings_transaction_lock:
            outcome = await self._refresh_settings_mutation(
                lambda: self.add_source(source, scope)
            )
            _raise_refresh_error(outcome)
        return record

    async def update(self, source: str) -> PackageMaterializationRecord:
        if not is_remote_package_source(source):
            record = await self.materialize(source)
        else:
            materializer = self._require_materializer()
            record = await materializer.update_remote_source(source)
        _raise_refresh_error(await self._refresh_outcome())
        return record

    async def update_all(self) -> list[PackageMaterializationRecord]:
        if self.prepare_updates is not None:
            await _resolve(self.prepare_updates())
        materializer = self._require_materializer()
        records = await materializer.update_all_remote_sources()
        _raise_refresh_error(await self._refresh_outcome())
        return records

    def remove(self, source: str) -> PackageMaterializationRecord:
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
    ) -> PackageMaterializationRecord:
        async with self._settings_transaction_lock:
            outcome = await self._refresh_settings_mutation(
                lambda: self.remove_source(source, scope)
            )
            if outcome.published:
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
    ) -> PackageMaterializationRecord:
        """Preserve the legacy synchronous contract behind an explicit gate."""

        outcome = self._refresh_settings_mutation_sync(
            lambda: self.remove_source(source, scope)
        )
        if outcome.published:
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
            record = self.remove(source)
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
    "PackageOperationsRuntime",
    "PackageMutationRequiresAsyncError",
    "PackageResourceRefresh",
    "PackageResourceRefreshOutcome",
    "PackageResourceRefreshTransaction",
    "PackageResourceRefreshTransactionRunner",
    "PackageSourceRegistration",
    "PackageUpdatePreparation",
]
