"""Retained Linux namespace storage admission, independent of service readiness.

An explicit first-use request may initialize absent storage. Existing witnesses
are always opened without creation. Failed attempts never delete or adopt their
residue; callers retain this owner until its local cleanup has settled.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path, PurePosixPath
from secrets import token_hex
from threading import RLock
from time import monotonic

from ._files import (
    ManagedStorageError,
    PrivateManagedDirectory,
    _check_deadline,
    _check_lock_wait,
)
from .admission_record import (
    ManagedInitializationPhaseV1,
    ManagedNamespaceAdmissionRecordV1,
)
from .contracts import ManagedContractError, ManagedNamespaceV1, _path
from .paths import (
    _overlaps,
    resolve_managed_admission_root,
    resolve_managed_registry_root,
)
from .registry import ManagedRegistryV1

_LOCK = "admission.lock"
_RECORD = "admission.json"


class ManagedNamespaceAdmissionV1:
    """Own the registry and admission descriptors; create no Session or service.

    Construct before native IO and call open once. Concurrent first-use losers
    may retry with a fresh owner only after closing this one; no failed open is
    replayed on the original container. Persistent initializing requires explicit
    recovery, not an unbounded wait or automatic takeover.
    """

    def __init__(self, namespace: ManagedNamespaceV1, *, runtime_root: str,
                 create_if_missing: bool = False) -> None:
        if (type(namespace) is not ManagedNamespaceV1 or namespace.user_id != os.geteuid()
                or type(create_if_missing) is not bool):
            raise ManagedContractError()
        _path(runtime_root)
        admission = Path(resolve_managed_admission_root(namespace))
        registry = Path(resolve_managed_registry_root(namespace))
        runtime = Path(runtime_root) / "lmux" / namespace.namespace_key
        if (_overlaps(PurePosixPath(runtime), PurePosixPath(namespace.platform_home) / "lmux")
                or _overlaps(PurePosixPath(runtime), PurePosixPath(namespace.platform_home) / "state")):
            raise ManagedContractError()
        self._namespace = namespace
        self._runtime_root = runtime_root
        self._registry_root = registry
        self._create = create_if_missing
        self._record = ManagedNamespaceAdmissionRecordV1(
            namespace.namespace_key, token_hex(16), token_hex(16),
            ManagedInitializationPhaseV1.INITIALIZING,
        )
        self._existing = PrivateManagedDirectory(admission, defer_open=True)
        self._fresh = PrivateManagedDirectory(admission, create=True, create_parents=True,
                                              exclusive_create=True, defer_open=True)
        self._probes = tuple(PrivateManagedDirectory(root, defer_open=True)
                             for root in (registry.parent, runtime))
        self._directories = (self._existing, self._fresh, *self._probes)
        self._registry: ManagedRegistryV1 | None = None
        self._registry_closed = False
        self._closed: set[int] = set()
        self._attempted = self._opened = self._closing = False
        self._mutex = RLock()

    @property
    def registry(self) -> ManagedRegistryV1:
        if not self._opened or self._closing or self._registry is None:
            raise ManagedStorageError("closed")
        return self._registry

    @property
    def cleanup_pending(self) -> bool:
        return (len(self._closed) != len(self._directories)
                or (self._registry is not None and not self._registry_closed))

    def open(self, *, deadline: float, wait_for_lock: bool = False) -> ManagedRegistryV1:
        """Open original storage; not_found means witness and residue absent.

        Missing dependencies of an initialized witness are unavailable, not a
        fresh namespace. This classification never authorizes creation itself.
        """
        _check_deadline(deadline)
        _check_lock_wait(wait_for_lock, deadline)
        if not self._mutex.acquire(timeout=max(0.0, min(30.0, deadline - monotonic()))):
            raise ManagedStorageError("busy")
        try:
            if self._attempted or self._closing:
                raise ManagedStorageError("closed")
            self._attempted = True
            _check_deadline(deadline)
            try:
                self._existing.open(deadline=deadline)
            except ManagedStorageError as error:
                if error.code != "not_found":
                    raise
                if not self._create:
                    self._require_no_residue(deadline)
                    raise
                # Settle the failed path walk before claiming any creation.
                self._existing.close()
                self._closed.add(0)
                self._initialize(deadline)
            else:
                try:
                    self._reopen(deadline, wait_for_lock=wait_for_lock)
                except ManagedStorageError as error:
                    if error.code == "not_found":
                        raise ManagedStorageError("unavailable") from None
                    raise
            _check_deadline(deadline)
            self._opened = True
            return self.registry
        finally:
            self._mutex.release()

    def _require_no_residue(self, deadline: float) -> None:
        for probe in self._probes:
            try:
                probe.open(deadline=deadline)
            except ManagedStorageError as error:
                if error.code != "not_found":
                    raise
            else:
                # Even an empty surviving machine/runtime directory is residue,
                # not evidence that a lost admission witness can be recreated.
                raise ManagedStorageError("conflict")

    def _initialize(self, deadline: float) -> None:
        self._require_no_residue(deadline)
        self._fresh.open(deadline=deadline)
        with self._fresh.lock(_LOCK, create=True, exclusive_create=True, deadline=deadline):
            self._record = replace(
                self._record, admission_root_identity=self._fresh._identity,
                admission_lock_identity=self._fresh._locks[_LOCK][1],
            )
            self._fresh.write(_RECORD, self._record.to_json().encode(), expected=None)
            intent = self._fresh.read(_RECORD)
            if intent is None or intent.content != self._record.to_json().encode():
                raise ManagedStorageError("conflict")
            _check_deadline(deadline)
            self._registry = ManagedRegistryV1(
                self._registry_root, self._namespace, create=True, exclusive_create=True,
                create_parents=True, deployment_id=self._record.deployment_id, defer_open=True,
                service_admission_required=True,
            )
            self._registry.open(deadline=deadline)
            database = self._registry._database
            complete = replace(
                self._record, phase=ManagedInitializationPhaseV1.INITIALIZED,
                registry_root_identity=database._directory._identity,
                database_identity=database._file_identity,
                registry_lock_identity=database._lock_identity,
            )
            _check_deadline(deadline)
            self._fresh.write(_RECORD, complete.to_json().encode(), expected=intent)
            published = self._fresh.read(_RECORD)
            if published is None or published.content != complete.to_json().encode():
                raise ManagedStorageError("conflict")
            self._record = complete

    def _reopen(self, deadline: float, *, wait_for_lock: bool = False) -> None:
        # A new stable lock is visible before its creator can flock it. A
        # reader without any marker must not steal that first lock and make
        # both attempts fail. This negative precheck grants no authority;
        # the actual record is always read again under the admitted lock.
        if self._existing.read(_RECORD) is None:
            raise ManagedStorageError("invalid_record")
        with self._existing.lock(_LOCK, deadline=deadline, wait_for_lock=wait_for_lock):
            snapshot = self._existing.read(_RECORD)
            if snapshot is None:
                raise ManagedStorageError("invalid_record")
            try:
                record = ManagedNamespaceAdmissionRecordV1.from_json(snapshot.content.decode("utf-8"))
            except (ManagedContractError, UnicodeError):
                raise ManagedStorageError("invalid_record") from None
            if record.namespace_key != self._namespace.namespace_key:
                raise ManagedStorageError("conflict")
            if (record.admission_root_identity != self._existing._identity
                    or record.admission_lock_identity != self._existing._locks[_LOCK][1]):
                raise ManagedStorageError("conflict")
            if record.phase is not ManagedInitializationPhaseV1.INITIALIZED:
                raise ManagedStorageError("unavailable")
            self._registry = ManagedRegistryV1(
                self._registry_root, self._namespace, deployment_id=record.deployment_id, defer_open=True,
                service_admission_required=True,
            )
            self._registry.open(deadline=deadline, wait_for_lock=wait_for_lock)
            database = self._registry._database
            if (database._directory._identity != record.registry_root_identity
                    or database._file_identity != record.database_identity
                    or database._lock_identity != record.registry_lock_identity
                    or self._existing.read(_RECORD) != snapshot):
                raise ManagedStorageError("conflict")
            self._record = record

    def close(self) -> None:
        with self._mutex:
            self._closing = True
            self._opened = False
            failures: list[BaseException] = []
            if self._registry is not None and not self._registry_closed:
                try:
                    self._registry.close()
                except BaseException as error:
                    failures.append(error)
                else:
                    self._registry_closed = True
            for index, directory in enumerate(self._directories):
                if index in self._closed:
                    continue
                try:
                    directory.close()
                except BaseException as error:
                    failures.append(error)
                else:
                    self._closed.add(index)
            if failures:
                raise failures[0]


__all__ = ["ManagedNamespaceAdmissionV1"]
