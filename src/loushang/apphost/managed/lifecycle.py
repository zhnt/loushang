"""Durable instance generations under one stable service lifecycle fence.

These records coordinate trusted owners. They neither discover live processes
nor confer permission to kill one. A child-side owner alone proposes commit;
the eventual Hosting integration supplies native identity and settlement facts.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from secrets import token_hex

from ._files import ManagedStorageError, PrivateManagedDirectory
from .contracts import (
    _HEX32,
    ManagedContractError,
    ManagedHandoffPhaseV1,
    ManagedHandoffV1,
    ManagedInstanceRefV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
    ManagedStopEvidenceV1,
    _match,
)
from .registry import ManagedRegistryV1

_MAX_REVISION = 2**63 - 1


@dataclass(frozen=True, slots=True)
class ManagedServiceStateV1:
    """Last durable observation; not an assertion that an instance is alive."""

    revision: int
    handoff: ManagedHandoffV1
    evidence: ManagedStopEvidenceV1

    def __post_init__(self) -> None:
        if (
            type(self.revision) is not int or not 1 <= self.revision <= _MAX_REVISION
            or type(self.handoff) is not ManagedHandoffV1
            or type(self.evidence) is not ManagedStopEvidenceV1
            or self.handoff.instance != self.evidence.instance
        ):
            raise ManagedContractError()
        if (
            not self.handoff.stop_requested
            and self.handoff.phase is not ManagedHandoffPhaseV1.ABORTING
            and (self.evidence.process_exited or self.evidence.application_cleanup_completed
                 or self.evidence.process_scope_settled)
        ):
            raise ManagedContractError()

    @property
    def cleanly_stopped(self) -> bool:
        return self.evidence.cleanly_stopped


class ManagedServiceJournalV1:
    """Borrow a registry; own only the injected per-service fence directory.

    Lock order is service fence, then short registry transaction. No network IO,
    process wait or caller callback is performed while either lock is held.
    This slice permits only clean reuse. Unclean retirement/recovery admission
    still needs a separate native proof; never invent application cleanup facts.
    """

    def __init__(
        self, registry: ManagedRegistryV1, namespace: ManagedNamespaceV1,
        service: ManagedServiceKeyV1, lifecycle_root: Path, *, create: bool = False,
    ) -> None:
        if (type(registry) is not ManagedRegistryV1 or type(namespace) is not ManagedNamespaceV1
                or type(service) is not ManagedServiceKeyV1):
            raise ManagedContractError()
        self._database = registry._database
        if self._database._namespace != namespace.namespace_key:
            raise ManagedContractError()
        self._namespace, self._service = namespace, service
        self._fence = PrivateManagedDirectory(lifecycle_root, create=create)
        try:
            if create:
                with self._fence.lock("lifecycle.lock", create=True):
                    pass
        except BaseException as error:
            try:
                self._fence.close()
            except BaseException:
                error.add_note("managed_lifecycle_cleanup_incomplete")
            raise

    def close(self) -> None:
        self._fence.close()

    def read(self) -> ManagedServiceStateV1 | None:
        with self._fence.lock("lifecycle.lock"), self._database.transaction() as connection:
            result = self._read(connection)
            self._fence._check()
            return result

    def prepare(
        self, attempt_id: str, *, expected: ManagedServiceStateV1 | None,
    ) -> ManagedServiceStateV1:
        """Reserve a fresh generation, never infer absence from socket/PID loss.

        An uncertain result is resolved by read(), not by repeating process spawn.
        Existing generations require all three matching stop facts before reuse.
        """
        _match(attempt_id, _HEX32)
        if expected is not None and type(expected) is not ManagedServiceStateV1:
            raise ManagedContractError()
        with self._fence.lock("lifecycle.lock"), self._database.transaction(write=True) as connection:
            current = self._read(connection)
            if current != expected:
                raise ManagedStorageError("conflict")
            if current is not None:
                if not current.cleanly_stopped:
                    raise ManagedStorageError("busy")
                if attempt_id == current.handoff.attempt_id:
                    raise ManagedStorageError("conflict")
            self._database.admit_growth(connection)
            instance_id = token_hex(16)
            if current is not None and instance_id == current.handoff.instance.instance_id:
                raise ManagedStorageError("conflict")
            instance = ManagedInstanceRefV1(self._namespace.namespace_key,
                                            self._service.service_id, instance_id)
            state = ManagedServiceStateV1(
                _next_revision(current), ManagedHandoffV1(instance, attempt_id),
                ManagedStopEvidenceV1(instance, False, False, False),
            )
            self._save(connection, state, insert=current is None)
            self._fence._check()
            return state

    def commit(self, instance: ManagedInstanceRefV1, attempt_id: str) -> ManagedServiceStateV1:
        """Persist the child's proposal; a stop fence or abort wins by refusing it."""
        _match(attempt_id, _HEX32)

        def update(current: ManagedServiceStateV1) -> ManagedServiceStateV1:
            if current.handoff.attempt_id != attempt_id:
                raise ManagedStorageError("conflict")
            return replace(current, handoff=current.handoff.commit())

        return self._update(instance, update)

    def abort(self, instance: ManagedInstanceRefV1, attempt_id: str) -> ManagedServiceStateV1:
        _match(attempt_id, _HEX32)

        def update(current: ManagedServiceStateV1) -> ManagedServiceStateV1:
            if current.handoff.attempt_id != attempt_id:
                raise ManagedStorageError("conflict")
            return replace(current, handoff=current.handoff.abort())

        return self._update(instance, update)

    def request_stop(self, instance: ManagedInstanceRefV1) -> ManagedServiceStateV1:
        return self._update(instance, lambda current: replace(
            current, handoff=current.handoff.request_stop(),
        ))

    def record_stop_evidence(self, evidence: ManagedStopEvidenceV1) -> ManagedServiceStateV1:
        """Join monotonic facts from the trusted native/application observers."""
        if type(evidence) is not ManagedStopEvidenceV1:
            raise ManagedContractError()

        def update(current: ManagedServiceStateV1) -> ManagedServiceStateV1:
            if not current.handoff.stop_requested and current.handoff.phase is not ManagedHandoffPhaseV1.ABORTING:
                raise ManagedStorageError("conflict")
            prior = current.evidence
            joined = ManagedStopEvidenceV1(
                evidence.instance, prior.process_exited or evidence.process_exited,
                prior.application_cleanup_completed or evidence.application_cleanup_completed,
                prior.process_scope_settled or evidence.process_scope_settled,
            )
            return replace(current, evidence=joined)

        return self._update(evidence.instance, update)

    def _update(
        self, instance: ManagedInstanceRefV1,
        update: Callable[[ManagedServiceStateV1], ManagedServiceStateV1],
    ) -> ManagedServiceStateV1:
        self._require_instance(instance)
        with self._fence.lock("lifecycle.lock"), self._database.transaction(write=True) as connection:
            current = self._read(connection)
            if current is None or current.handoff.instance != instance:
                raise ManagedStorageError("conflict")
            try:
                proposed = update(current)
            except ManagedContractError:
                raise ManagedStorageError("conflict") from None
            if proposed == current:
                self._fence._check()
                return current
            self._database.admit_control(connection)
            proposed = replace(proposed, revision=_next_revision(current))
            self._save(connection, proposed, insert=False)
            self._fence._check()
            return proposed

    def _require_instance(self, instance: ManagedInstanceRefV1) -> None:
        if (type(instance) is not ManagedInstanceRefV1
                or instance.namespace_key != self._namespace.namespace_key
                or instance.service_id != self._service.service_id):
            raise ManagedContractError()

    def _read(self, connection: sqlite3.Connection) -> ManagedServiceStateV1 | None:
        service = self._service
        key = connection.execute("SELECT product, workspace, profile FROM services WHERE service_id=?",
                                 (service.service_id,)).fetchone()
        if key != (service.product_id, service.workspace, service.profile):
            raise ManagedStorageError("conflict")
        row = connection.execute("SELECT revision, instance_id, attempt_id, phase, stop_requested, "
                                 "process_exited, application_cleanup_completed, process_scope_settled "
                                 "FROM instances WHERE service_id=?", (service.service_id,)).fetchone()
        if row is None:
            return None
        try:
            if any(type(value) is not int or value not in (0, 1) for value in row[4:]):
                raise ManagedContractError()
            instance = ManagedInstanceRefV1(self._namespace.namespace_key, service.service_id, row[1])
            handoff = ManagedHandoffV1(instance, row[2], ManagedHandoffPhaseV1(row[3]), bool(row[4]))
            return ManagedServiceStateV1(row[0], handoff, ManagedStopEvidenceV1(
                instance, bool(row[5]), bool(row[6]), bool(row[7]),
            ))
        except (ManagedContractError, ValueError, TypeError):
            raise ManagedStorageError("invalid_record") from None

    def _save(self, connection: sqlite3.Connection, state: ManagedServiceStateV1, *, insert: bool) -> None:
        handoff, evidence = state.handoff, state.evidence
        values = (state.revision, handoff.instance.instance_id, handoff.attempt_id, handoff.phase.value,
                  int(handoff.stop_requested), int(evidence.process_exited),
                  int(evidence.application_cleanup_completed), int(evidence.process_scope_settled),
                  self._service.service_id)
        if insert:
            connection.execute("INSERT INTO instances (revision, instance_id, attempt_id, phase, "
                               "stop_requested, process_exited, application_cleanup_completed, "
                               "process_scope_settled, service_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
        else:
            connection.execute("UPDATE instances SET revision=?, instance_id=?, attempt_id=?, phase=?, "
                               "stop_requested=?, process_exited=?, application_cleanup_completed=?, "
                               "process_scope_settled=? WHERE service_id=?", values)


def _next_revision(current: ManagedServiceStateV1 | None) -> int:
    revision = 1 if current is None else current.revision + 1
    if revision > _MAX_REVISION:
        raise ManagedStorageError("capacity")
    return revision
