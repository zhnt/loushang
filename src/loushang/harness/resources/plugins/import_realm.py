"""Process-wide compatibility gate for verified in-process Plugin imports."""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, TypeVar

from loushang.harness.resources.plugins.dependencies import (
    PluginDependencyClosureLock,
    PluginPythonDistributionLock,
)

_ResultT = TypeVar("_ResultT")


class PluginImportRealmError(RuntimeError):
    """Fail-closed import-realm rejection with a stable diagnostic code."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PluginImportRealmSnapshotV1:
    import_realm_id: str
    host_boot_id: str | None
    state: Literal["clean", "polluted"]
    active_execution_use_id: str | None
    locked_distributions: tuple[PluginPythonDistributionLock, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "activeExecutionUseId": self.active_execution_use_id,
            "hostBootId": self.host_boot_id,
            "importRealmId": self.import_realm_id,
            "lockedDistributions": [
                item.to_dict() for item in self.locked_distributions
            ],
            "state": self.state,
        }


@dataclass(frozen=True, slots=True)
class _PluginImportRealmLease:
    import_realm_id: str
    host_boot_id: str
    execution_use_id: str
    dependency_lock: PluginDependencyClosureLock = field(repr=False)
    token: str = field(repr=False, compare=False)


@dataclass(slots=True)
class _ActiveImport:
    lease: _PluginImportRealmLease
    started: bool = False


class PluginImportRealm:
    """Serialize compatible imports and permanently quarantine uncertain state."""

    def __init__(
        self,
        *,
        import_realm_id_factory: Callable[[], str] = lambda: secrets.token_hex(16),
    ) -> None:
        import_realm_id = import_realm_id_factory()
        _require_hex(import_realm_id, length=32, name="import realm id")
        self._import_realm_id = import_realm_id
        self._gate = threading.RLock()
        self._host_boot_id: str | None = None
        self._state: Literal["clean", "polluted"] = "clean"
        self._active: _ActiveImport | None = None
        self._locked_distributions: dict[str, PluginPythonDistributionLock] = {}

    @property
    def import_realm_id(self) -> str:
        return self._import_realm_id

    def preflight(
        self,
        *,
        host_boot_id: str,
        dependency_lock: PluginDependencyClosureLock,
    ) -> None:
        self._validate_request(host_boot_id, dependency_lock)
        with self._gate:
            self._require_usable_locked(host_boot_id, dependency_lock)

    def reserve(
        self,
        *,
        host_boot_id: str,
        execution_use_id: str,
        dependency_lock: PluginDependencyClosureLock,
    ) -> _PluginImportRealmLease:
        self._validate_request(host_boot_id, dependency_lock)
        _require_hex(execution_use_id, length=48, name="execution use id")
        with self._gate:
            self._require_usable_locked(host_boot_id, dependency_lock)
            if self._host_boot_id is None:
                self._host_boot_id = host_boot_id
            lease = _PluginImportRealmLease(
                import_realm_id=self._import_realm_id,
                host_boot_id=host_boot_id,
                execution_use_id=execution_use_id,
                dependency_lock=dependency_lock,
                token=secrets.token_hex(24),
            )
            self._active = _ActiveImport(lease=lease)
            return lease

    def execute(
        self,
        lease: _PluginImportRealmLease,
        loader: Callable[[], _ResultT],
    ) -> _ResultT:
        if not callable(loader):
            raise TypeError("Plugin import realm loader must be callable")
        with self._gate:
            active = self._require_active_locked(lease)
            if active.started:
                raise self._error(
                    "Plugin import realm lease was already started.",
                    code="plugin_import_realm_lease_consumed",
                )
            active.started = True
        try:
            return loader()
        except BaseException:
            with self._gate:
                if self._active is active:
                    self._state = "polluted"
                    self._active = None
            raise

    def commit(self, lease: _PluginImportRealmLease) -> None:
        with self._gate:
            active = self._require_active_locked(lease)
            if not active.started:
                raise self._error(
                    "Plugin import realm lease has not started.",
                    code="plugin_import_realm_lease_not_started",
                )
            for distribution in lease.dependency_lock.python_distributions:
                self._locked_distributions[distribution.name] = distribution
            self._active = None

    def cancel(self, lease: _PluginImportRealmLease) -> None:
        with self._gate:
            active = self._require_active_locked(lease)
            if active.started:
                raise self._error(
                    "Started Plugin import realm leases cannot be cancelled.",
                    code="plugin_import_realm_lease_started",
                )
            self._active = None

    def pollute(self, lease: _PluginImportRealmLease) -> None:
        """Quarantine a realm when evaluation may have escaped durable evidence."""

        with self._gate:
            active = self._require_active_locked(lease)
            if not active.started:
                raise self._error(
                    "Unstarted Plugin import realm leases cannot pollute a realm.",
                    code="plugin_import_realm_lease_not_started",
                )
            self._state = "polluted"
            self._active = None

    def snapshot(self) -> PluginImportRealmSnapshotV1:
        with self._gate:
            return PluginImportRealmSnapshotV1(
                import_realm_id=self._import_realm_id,
                host_boot_id=self._host_boot_id,
                state=self._state,
                active_execution_use_id=(
                    self._active.lease.execution_use_id
                    if self._active is not None
                    else None
                ),
                locked_distributions=tuple(
                    self._locked_distributions[name]
                    for name in sorted(self._locked_distributions)
                ),
            )

    @staticmethod
    def _validate_request(
        host_boot_id: str,
        dependency_lock: PluginDependencyClosureLock,
    ) -> None:
        _require_hex(host_boot_id, length=32, name="host boot id")
        if not isinstance(dependency_lock, PluginDependencyClosureLock):
            raise TypeError("Plugin import realm requires a dependency closure lock")

    def _require_usable_locked(
        self,
        host_boot_id: str,
        dependency_lock: PluginDependencyClosureLock,
    ) -> None:
        if self._state == "polluted":
            raise self._error(
                "Plugin import realm is polluted.",
                code="plugin_import_realm_polluted",
            )
        if self._host_boot_id not in {None, host_boot_id}:
            raise self._error(
                "Plugin import realm belongs to another Host boot.",
                code="plugin_import_realm_host_mismatch",
            )
        if self._active is not None:
            raise self._error(
                "Plugin import realm already has an active import.",
                code="plugin_import_realm_busy",
            )
        for distribution in dependency_lock.python_distributions:
            committed = self._locked_distributions.get(distribution.name)
            if committed is not None and committed.version != distribution.version:
                raise self._error(
                    "Plugin dependency closure conflicts with the import realm.",
                    code="plugin_import_dependency_conflict",
                )

    def _require_active_locked(
        self,
        lease: _PluginImportRealmLease,
    ) -> _ActiveImport:
        if not isinstance(lease, _PluginImportRealmLease):
            raise self._error(
                "Plugin import realm lease is foreign or already consumed.",
                code="plugin_import_realm_lease_consumed",
            )
        active = self._active
        if (
            active is None
            or active.lease is not lease
            or lease.import_realm_id != self._import_realm_id
        ):
            raise self._error(
                "Plugin import realm lease is foreign or already consumed.",
                code="plugin_import_realm_lease_consumed",
            )
        return active

    @staticmethod
    def _error(message: str, *, code: str) -> PluginImportRealmError:
        return PluginImportRealmError(message, code=code)


def _require_hex(value: str, *, length: int, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be {length} lowercase hexadecimal characters")


__all__ = [
    "PluginImportRealm",
    "PluginImportRealmError",
    "PluginImportRealmSnapshotV1",
]
