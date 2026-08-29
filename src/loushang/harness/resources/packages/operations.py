"""Product-bound package operation lifecycle coordination."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

from loushang.harness.resources.packages.materializer import (
    PackageMaterializationRecord,
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
PackageSourceRegistration = Callable[[str, str], None]
PackageResourceRefresh = Callable[[], object | Awaitable[object]]
PackageUpdatePreparation = Callable[[], object | Awaitable[object]]
PackageResourceRevisionProvider = Callable[[], int]


@dataclass
class PackageOperationsRuntime:
    """Coordinate package materialization and Product-bound source activation."""

    get_materializer: PackageMaterializerProvider
    add_source: PackageSourceRegistration
    remove_source: PackageSourceRegistration
    refresh_resources: PackageResourceRefresh
    prepare_updates: PackageUpdatePreparation | None = None
    get_resource_revision: PackageResourceRevisionProvider | None = None

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
        self.add_source(source, scope)
        previous_revision = self._resource_revision()
        try:
            await _resolve(self.refresh_resources())
        except BaseException:
            if not self._refresh_published_since(previous_revision):
                self.remove_source(source, scope)
            raise
        return record

    async def update(self, source: str) -> PackageMaterializationRecord:
        if not is_remote_package_source(source):
            record = await self.materialize(source)
        else:
            materializer = self._require_materializer()
            record = await materializer.update_remote_source(source)
        await _resolve(self.refresh_resources())
        return record

    async def update_all(self) -> list[PackageMaterializationRecord]:
        if self.prepare_updates is not None:
            await _resolve(self.prepare_updates())
        materializer = self._require_materializer()
        records = await materializer.update_all_remote_sources()
        await _resolve(self.refresh_resources())
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
        record = self.remove(source)
        self.remove_source(source, scope)
        previous_revision = self._resource_revision()
        try:
            await _resolve(self.refresh_resources())
        except BaseException:
            if not self._refresh_published_since(previous_revision):
                self.add_source(source, scope)
            else:
                self._forget_remote_source(source)
            raise
        self._forget_remote_source(source)
        return record

    def _resource_revision(self) -> int | None:
        provider = self.get_resource_revision
        return None if provider is None else provider()

    def _refresh_published_since(self, previous_revision: int | None) -> bool:
        provider = self.get_resource_revision
        return (
            previous_revision is not None
            and provider is not None
            and provider() != previous_revision
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


__all__ = [
    "PackageMaterializerPort",
    "PackageMaterializerProvider",
    "PackageOperationsRuntime",
    "PackageResourceRefresh",
    "PackageResourceRevisionProvider",
    "PackageSourceRegistration",
    "PackageUpdatePreparation",
]
