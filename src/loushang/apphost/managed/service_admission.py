"""Service-control intent before native fence creation, without process authority."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from secrets import token_hex
from threading import RLock
from time import monotonic, sleep

from ._files import (
    ManagedStorageError,
    PrivateManagedDirectory,
    _check_deadline,
    _check_lock_wait,
)
from .admission_record import (
    ManagedInitializationPhaseV1,
    ManagedServiceAdmissionRecordV1,
)
from .contracts import ManagedContractError, ManagedServiceKeyV1
from .lifecycle import ManagedServiceJournalV1
from .namespace_admission import ManagedNamespaceAdmissionV1
from .paths import resolve_managed_service_paths
from .registry import MAX_SERVICES


class ManagedServiceAdmissionV1:
    """Borrow the original namespace; own only this service's fence and journal.

    Call open once after retaining this object. Creation requires a newly
    committed control intent, not absence of an instance. close never stops a
    service, removes its fence, or closes the borrowed namespace registry.
    """

    def __init__(self, namespace: ManagedNamespaceAdmissionV1, service: ManagedServiceKeyV1) -> None:
        if type(namespace) is not ManagedNamespaceAdmissionV1 or type(service) is not ManagedServiceKeyV1:
            raise ManagedContractError()
        registry = namespace.registry
        if not registry._database.service_admission_required:
            raise ManagedContractError()
        paths = resolve_managed_service_paths(namespace._namespace, service, runtime_root=namespace._runtime_root)
        self._namespace = namespace
        self._database = registry._database
        self._service = service
        self._intent = ManagedServiceAdmissionRecordV1(service.service_id, token_hex(16),
                                                       ManagedInitializationPhaseV1.INITIALIZING)
        self._fresh = PrivateManagedDirectory(Path(paths.lifecycle), create=True, create_parents=True,
                                              exclusive_create=True, defer_open=True)
        self._probe = PrivateManagedDirectory(Path(paths.lifecycle), defer_open=True)
        self._journal = ManagedServiceJournalV1(registry, namespace._namespace, service,
                                                Path(paths.lifecycle), defer_open=True)
        self._attempted = self._opened = self._closing = False
        self._closed: set[str] = set()
        self._mutex = RLock()

    @property
    def journal(self) -> ManagedServiceJournalV1:
        if not self._opened or self._closing:
            raise ManagedStorageError("closed")
        return self._journal

    @property
    def cleanup_pending(self) -> bool:
        return len(self._closed) != 3

    def open(self, *, deadline: float, wait_for_lock: bool = False) -> ManagedServiceJournalV1:
        _check_deadline(deadline)
        _check_lock_wait(wait_for_lock, deadline)
        if not self._mutex.acquire(timeout=max(0.0, min(30.0, deadline - monotonic()))):
            raise ManagedStorageError("busy")
        try:
            if self._attempted or self._closing:
                raise ManagedStorageError("closed")
            self._attempted = True
            _check_deadline(deadline)
            with self._database.transaction(deadline=deadline, wait_for_lock=wait_for_lock) as connection:
                row = connection.execute("SELECT record FROM service_controls WHERE service_id=?",
                                         (self._service.service_id,)).fetchone()
            if row is None:
                try:
                    self._probe.open(deadline=deadline)
                except ManagedStorageError as error:
                    if error.code != "not_found":
                        raise
                else:
                    raise ManagedStorageError("conflict")
                record, claimed = self._claim(deadline, wait_for_lock=wait_for_lock)
                if claimed:
                    self._initialize(deadline)
            else:
                record = self._decode(row)
                claimed = False
            if not claimed and record.phase is not ManagedInitializationPhaseV1.INITIALIZED:
                raise ManagedStorageError("unavailable")
            self._journal.open(deadline=deadline, wait_for_lock=wait_for_lock)
            _check_deadline(deadline)
            self._opened = True
            return self.journal
        finally:
            self._mutex.release()

    def _decode(self, row: tuple) -> ManagedServiceAdmissionRecordV1:
        try:
            record = ManagedServiceAdmissionRecordV1.from_json(row[0])
        except (ManagedContractError, IndexError):
            raise ManagedStorageError("invalid_record") from None
        if record.service_id != self._service.service_id:
            raise ManagedStorageError("conflict")
        return record

    def _claim(self, deadline: float, *, wait_for_lock: bool = False) -> tuple[ManagedServiceAdmissionRecordV1, bool]:
        service = self._service
        with self._database.transaction(write=True, deadline=deadline, wait_for_lock=wait_for_lock) as connection:
            row = connection.execute("SELECT record FROM service_controls WHERE service_id=?",
                                     (service.service_id,)).fetchone()
            if row is not None:
                return self._decode(row), False
            key = connection.execute("SELECT product, workspace, profile FROM services WHERE service_id=?",
                                     (service.service_id,)).fetchone()
            if key is not None and key != (service.product_id, service.workspace, service.profile):
                raise ManagedStorageError("conflict")
            if connection.execute("SELECT 1 FROM instances WHERE service_id=?", (service.service_id,)).fetchone():
                raise ManagedStorageError("conflict")
            self._database.admit_growth(connection)
            if key is None:
                if connection.execute("SELECT count(*) FROM services").fetchone()[0] >= MAX_SERVICES:
                    raise ManagedStorageError("capacity")
                connection.execute("INSERT INTO services VALUES (?, ?, ?, ?)",
                                   (service.service_id, service.product_id, service.workspace, service.profile))
            connection.execute("INSERT INTO service_controls VALUES (?, ?)",
                               (service.service_id, self._intent.to_json()))
        return self._intent, True

    def _initialize(self, deadline: float) -> None:
        # No registry transaction is held while admitting or locking the fence.
        self._fresh.open(deadline=deadline)
        with self._fresh.lock("lifecycle.lock", create=True, exclusive_create=True, deadline=deadline):
            lock_identity = self._fresh._locks["lifecycle.lock"][1]
            complete = replace(self._intent, phase=ManagedInitializationPhaseV1.INITIALIZED,
                               root_identity=self._fresh._identity,
                               lock_identity=lock_identity)
            self._publish(complete, lock_identity, deadline)

    def _publish(self, complete: ManagedServiceAdmissionRecordV1, lock_identity: tuple[int, int],
                 deadline: float) -> None:
        # Other services/readers may briefly hold the shared registry lock.
        # Retain the original fence and settle only this publication; never
        # turn transient contention into a replay of native creation.
        while True:
            _check_deadline(deadline)
            try:
                with self._database.transaction(write=True, deadline=deadline) as connection:
                    row = connection.execute("SELECT record FROM service_controls WHERE service_id=?",
                                             (self._service.service_id,)).fetchone()
                    if row is None:
                        raise ManagedStorageError("conflict")
                    current = self._decode(row)
                    self._fresh._check()
                    self._fresh._check_named("lifecycle.lock", lock_identity)
                    if current == complete:
                        return
                    if current != self._intent:
                        raise ManagedStorageError("conflict")
                    self._database.admit_control(connection)
                    connection.execute("UPDATE service_controls SET record=? WHERE service_id=?",
                                       (complete.to_json(), self._service.service_id))
                return
            except ManagedStorageError as error:
                if error.code != "busy":
                    raise
            _check_deadline(deadline)
            sleep(min(0.01, max(0.0, deadline - monotonic())))

    def close(self) -> None:
        with self._mutex:
            self._closing = True
            self._opened = False
            failures: list[BaseException] = []
            for name, resource in (("journal", self._journal), ("fresh", self._fresh), ("probe", self._probe)):
                if name in self._closed:
                    continue
                try:
                    resource.close()
                except BaseException as error:
                    failures.append(error)
                else:
                    self._closed.add(name)
            if failures:
                raise failures[0]


__all__ = ["ManagedServiceAdmissionV1"]
