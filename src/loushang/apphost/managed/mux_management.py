"""Purpose-specific managed Mux permits and the original service fence.

Registry transactions end before RPC. Only the server-side admission retains
the service lock across the *local* AppService continuity commit. All native
entry/exit runs on the same event-loop thread; never split this RLock context
across to_thread jobs. This module neither launches nor stops a service.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from hmac import compare_digest
from secrets import token_hex
from threading import get_ident
from time import monotonic

from loushang.appserver.managed_mux import ManagedMuxCreatedV1, ManagedMuxCreateV1
from loushang.appserver.managed_mux_close import (
    ManagedMuxClosePhaseV1,
    ManagedMuxCloseStateV1,
    ManagedMuxCloseV1,
)
from loushang.appservice.continuity import (
    MANAGED_CLOSE_CONTINUITY_VERSION,
    MANAGED_CONTINUITY_VERSION,
    ApplicationContinuityRecordV1,
    require_application_id,
)
from loushang.appservice.managed_mux import ManagedMuxServiceBindingV1
from loushang.appservice.managed_mux_close import (
    ManagedMuxCloseBindingV1,
    ManagedMuxCloseRecoveryBindingV1,
    ManagedMuxCloseUseV1,
)
from loushang.hosting.service import LinuxServiceIdentityV1

from ._files import ManagedStorageError, _check_deadline
from .contracts import (
    _HEX32,
    _HEX64,
    ManagedContractError,
    ManagedHandoffPhaseV1,
    ManagedInstanceRefV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
    _match,
)
from .lifecycle import ManagedServiceJournalV1, ManagedServiceTransitionV1
from .registry import MAX_MUXES, ManagedMuxReservationV1, ManagedRegistryV1, _decode


@dataclass(frozen=True, slots=True)
class _Permit:
    instance_id: str
    origin_instance_id: str
    authority: str = field(repr=False)
    created: ManagedMuxCreatedV1 | None = None


@dataclass(frozen=True, slots=True)
class _ClosePermit:
    instance_id: str
    origin_instance_id: str
    authority: str = field(repr=False)
    creation: ManagedMuxCreatedV1
    result: ManagedMuxCloseStateV1 | None


@dataclass(frozen=True, slots=True)
class ManagedMuxInspectionV1:
    """Frozen historical facts, not liveness or authority to retarget a name.

    The optional request retains its originally issued instance and token.
    Inspection never renews permission; consumers must not serialize it into
    diagnostics. A closed result does not describe today's same-name Mux.
    """

    creation: ManagedMuxCreatedV1
    close_request: ManagedMuxCloseV1 | None = field(default=None, repr=False)
    close_result: ManagedMuxCloseStateV1 | None = None

    def __post_init__(self) -> None:
        creation, request, result = self.creation, self.close_request, self.close_result
        if type(creation) is not ManagedMuxCreatedV1:
            raise ManagedContractError()
        target = (creation.operation_id, creation.name, creation.mux_space_id)
        if request is not None and (type(request) is not ManagedMuxCloseV1 or
                (request.creation_operation_id, request.name, request.mux_space_id) != target):
            raise ManagedContractError()
        if result is not None and (type(result) is not ManagedMuxCloseStateV1 or request is None or
                (result.operation_id, result.creation_operation_id, result.name, result.mux_space_id)
                != (request.operation_id, *target)):
            raise ManagedContractError()


class ManagedMuxManagerV1:
    """Borrow admitted storage, issue permits and reconcile trusted responses.

    record_created consumes a result from the caller's exact authenticated
    service connection, not arbitrary peer input. A result's original instance
    can differ after recovery; the current permit still fences old callers.
    Token rows are private registry state, never discovery/diagnostic output.
    """

    def __init__(
        self, registry: ManagedRegistryV1, journal: ManagedServiceJournalV1,
        namespace: ManagedNamespaceV1, service: ManagedServiceKeyV1,
        instance: ManagedInstanceRefV1, *, application_id: str,
        startup_attempt_id: str | None = None,
        startup_native_identity: LinuxServiceIdentityV1 | None = None,
    ) -> None:
        require_application_id(application_id)
        if (
            type(registry) is not ManagedRegistryV1
            or type(journal) is not ManagedServiceJournalV1
            or type(namespace) is not ManagedNamespaceV1
            or type(service) is not ManagedServiceKeyV1
            or type(instance) is not ManagedInstanceRefV1
            or namespace.user_id != os.geteuid()
            or journal._database is not registry._database
            or journal._namespace != namespace or journal._service != service
            or instance.namespace_key != namespace.namespace_key
            or instance.service_id != service.service_id
        ):
            raise ManagedContractError()
        self._registry, self._journal = registry, journal
        self._service, self._instance = service, instance
        self._application_id = application_id
        if (startup_attempt_id is None) != (startup_native_identity is None):
            raise ManagedContractError()
        if startup_attempt_id is not None:
            _match(startup_attempt_id, _HEX32)
            if (type(startup_native_identity) is not LinuxServiceIdentityV1
                    or startup_native_identity.user_id != namespace.user_id):
                raise ManagedContractError()
        self._startup_attempt, self._startup_native = startup_attempt_id, startup_native_identity
        self._recovery_admitted = False
        self._recovery_record: ApplicationContinuityRecordV1 | None = None
        self._recovery_transition: ManagedServiceTransitionV1 | None = None
        # Data on this original manager, not another cleanup owner. Never
        # evict: after restart old pending must use startup recovery instead.
        self._continued_closures: dict[str, ManagedMuxCloseStateV1] = {}

    def binding(self) -> ManagedMuxServiceBindingV1:
        return ManagedMuxServiceBindingV1(
            self._application_id, self._service.service_id, self._instance.instance_id,
            self.prepare, closing=None if self._startup_attempt is None else self.closing_binding(),
        )

    def closing_binding(self) -> ManagedMuxCloseBindingV1:
        """Recovery activates only with the original bootstrap startup identity."""
        return ManagedMuxCloseBindingV1(self.prepare_close, recovery=(
            None if self._startup_attempt is None else ManagedMuxCloseRecoveryBindingV1(self.prepare_recovery)
        ))

    def prepare_recovery(
        self, record: ApplicationContinuityRecordV1 | None, use: ManagedMuxCloseUseV1,
    ) -> ManagedMuxRecoveryAdmission:
        if (self._startup_attempt is None or type(use) is not ManagedMuxCloseUseV1
                or use not in (ManagedMuxCloseUseV1.ADMIT, ManagedMuxCloseUseV1.SETTLE)):
            raise ManagedStorageError("conflict")
        if record is not None and (type(record) is not ApplicationContinuityRecordV1
                or record.application_id != self._application_id or record.product_id != self._service.product_id
                or record.managed_service_id != self._service.service_id
                or record.contract_version not in (MANAGED_CONTINUITY_VERSION, MANAGED_CLOSE_CONTINUITY_VERSION)):
            raise ManagedStorageError("conflict")
        return ManagedMuxRecoveryAdmission(self, record, use)

    def _recovery_history(self, connection: sqlite3.Connection, record: ApplicationContinuityRecordV1 | None) -> None:
        creations = {} if record is None else {item.operation_id: item for item in record.managed_creations}
        closures = {} if record is None else {item.operation_id: item for item in record.managed_closures}
        confirmed = connection.execute(
            "SELECT a.operation_id FROM mux_authorities a JOIN mux_intents m USING(operation_id) "
            "WHERE m.service_id=? AND a.created_instance_id IS NOT NULL", (self._service.service_id,),
        )
        if any(row[0] not in creations for row in confirmed):
            raise ManagedStorageError("conflict")
        confirmed = connection.execute(
            "SELECT c.operation_id FROM mux_close_authorities c JOIN mux_intents m "
            "ON c.creation_operation_id=m.operation_id WHERE m.service_id=? AND c.phase IS NOT NULL",
            (self._service.service_id,),
        )
        if any(row[0] not in closures for row in confirmed):
            raise ManagedStorageError("conflict")
        for item in creations.values():
            row = connection.execute(
                "SELECT name, service_id FROM mux_intents WHERE operation_id=?", (item.operation_id,),
            ).fetchone()
            permit = self._permit(connection, item.name, item.operation_id)
            if (row != (item.name, self._service.service_id) or permit is None
                    or permit.origin_instance_id != item.instance_id
                    or permit.created is not None and permit.created != item):
                raise ManagedStorageError("conflict")
        for closure in closures.values():
            close = self._close_permit(connection, closure.operation_id)
            if (close is None or close.origin_instance_id != closure.instance_id
                    or close.creation != creations[closure.creation_operation_id]
                    or close.result is not None and close.result.phase is ManagedMuxClosePhaseV1.CLOSED
                    and close.result != closure):
                raise ManagedStorageError("conflict")
        if record is not None:
            by_mux = {item.mux_space_id: item for item in creations.values()}
            for mux in record.mux_spaces:
                self._reservation(connection, mux.name, by_mux[mux.mux_space_id].operation_id)

    def _current(self, connection: sqlite3.Connection, *, stopped: bool = False) -> None:
        journal = self._journal
        journal._require_open()
        state = journal._read(connection)
        if (
            state is None or state.handoff.instance != self._instance
            or state.handoff.phase is not ManagedHandoffPhaseV1.COMMITTED
            or (state.handoff.stop_requested and not stopped)
        ):
            raise ManagedStorageError("conflict")

    def _reservation(self, connection: sqlite3.Connection, name: str, operation: str) -> None:
        row = connection.execute(
            "SELECT m.name, s.product, s.workspace, s.profile, m.operation_id, s.service_id "
            "FROM muxes m JOIN services s USING(service_id) WHERE m.name=?", (name,),
        ).fetchone()
        if row is None or _decode(row) != ManagedMuxReservationV1(name, self._service, operation):
            raise ManagedStorageError("conflict")

    @staticmethod
    def _permit(connection: sqlite3.Connection, name: str, operation: str) -> _Permit | None:
        row = connection.execute(
            "SELECT instance_id, origin_instance_id, authority, created_instance_id, mux_space_id "
            "FROM mux_authorities WHERE operation_id=?", (operation,),
        ).fetchone()
        if row is None:
            return None
        try:
            _match(row[0], _HEX32)
            _match(row[1], _HEX32)
            _match(row[2], _HEX64)
            if (row[3] is None) != (row[4] is None):
                raise ManagedContractError()
            created = None if row[3] is None else ManagedMuxCreatedV1(operation, row[3], name, row[4])
            if created is not None and created.instance_id != row[1]:
                raise ManagedContractError()
            return _Permit(row[0], row[1], row[2], created)
        except (ValueError, TypeError):
            raise ManagedStorageError("invalid_record") from None

    def _request(self, request: ManagedMuxCreateV1) -> None:
        if type(request) is not ManagedMuxCreateV1 or (
            request.service_id != self._service.service_id
            or request.instance_id != self._instance.instance_id
        ):
            raise ManagedStorageError("conflict")

    def _authorized(self, connection: sqlite3.Connection, request: ManagedMuxCreateV1) -> _Permit:
        self._request(request)
        self._reservation(connection, request.name, request.operation_id)
        permit = self._permit(connection, request.name, request.operation_id)
        if (permit is None or permit.instance_id != request.instance_id
                or not compare_digest(permit.authority, request.authority)):
            raise ManagedStorageError("conflict")
        return permit

    def issue_create(self, reservation: ManagedMuxReservationV1, *, deadline: float) -> ManagedMuxCreateV1:
        """Reserve one opaque current-instance permit, idempotent on lost reply.

        Does not reserve a name or start the service implicitly. Reauthorization
        replaces only current permission, never the immutable historical result.
        """
        if type(reservation) is not ManagedMuxReservationV1 or reservation.service != self._service:
            raise ManagedContractError()
        journal = self._journal
        journal._require_open()
        with journal._fence.lock("lifecycle.lock", deadline=deadline):
            with journal._database.transaction(write=True, deadline=deadline) as connection:
                self._current(connection)
                self._reservation(connection, reservation.name, reservation.operation_id)
                previous = self._permit(connection, reservation.name, reservation.operation_id)
                if previous is not None and previous.instance_id == self._instance.instance_id:
                    authority = previous.authority
                else:
                    if previous is None and connection.execute(
                        "SELECT count(*) FROM mux_authorities",
                    ).fetchone()[0] >= MAX_MUXES:
                        raise ManagedStorageError("capacity")
                    if previous is None:
                        journal._database.admit_growth(connection)
                    else:
                        journal._database.admit_control(connection)
                    authority = token_hex(32)
                    connection.execute(
                        "INSERT INTO mux_authorities VALUES (?, ?, ?, ?, NULL, NULL) "
                        "ON CONFLICT(operation_id) DO UPDATE SET instance_id=excluded.instance_id, "
                        "authority=excluded.authority",
                        (reservation.operation_id, self._instance.instance_id,
                         self._instance.instance_id, authority),
                    )
                result = ManagedMuxCreateV1(self._service.service_id, self._instance.instance_id,
                                            reservation.operation_id, reservation.name, authority)
                journal._fence._check()
        return result

    def prepare(self, request: ManagedMuxCreateV1) -> ManagedMuxAdmission:
        """Pure factory: AppService retains this exact owner before acquire."""
        self._request(request)
        return ManagedMuxAdmission(self, request)

    def read_created(self, request: ManagedMuxCreateV1, *, deadline: float) -> ManagedMuxCreatedV1 | None:
        self._request(request)
        journal = self._journal
        journal._require_open()
        with journal._fence.lock("lifecycle.lock", deadline=deadline):
            with journal._database.transaction(deadline=deadline) as connection:
                self._current(connection, stopped=True)
                result = self._authorized(connection, request).created
                journal._fence._check()
        return result

    def record_created(
        self, request: ManagedMuxCreateV1, result: ManagedMuxCreatedV1, *, deadline: float,
    ) -> ManagedMuxCreatedV1:
        self._request(request)
        if type(result) is not ManagedMuxCreatedV1 or (
            result.name != request.name or result.operation_id != request.operation_id
        ):
            raise ManagedStorageError("conflict")
        journal = self._journal
        journal._require_open()
        with journal._fence.lock("lifecycle.lock", deadline=deadline):
            with journal._database.transaction(write=True, deadline=deadline) as connection:
                self._current(connection, stopped=True)
                permit = self._authorized(connection, request)
                if result.instance_id != permit.origin_instance_id:
                    raise ManagedStorageError("conflict")
                previous = permit.created
                if previous is not None:
                    if previous != result:
                        raise ManagedStorageError("conflict")
                else:
                    journal._database.admit_control(connection)
                    connection.execute(
                        "UPDATE mux_authorities SET created_instance_id=?, mux_space_id=? "
                        "WHERE operation_id=?", (result.instance_id, result.mux_space_id, result.operation_id),
                    )
                journal._fence._check()
        return result


    def _close_request(self, request: ManagedMuxCloseV1) -> None:
        if type(request) is not ManagedMuxCloseV1 or (
            request.service_id != self._service.service_id
            or request.instance_id != self._instance.instance_id
        ):
            raise ManagedStorageError("conflict")

    def _admit_unaccepted_closure(self, creation: ManagedMuxCreatedV1, pending: ManagedMuxCloseStateV1) -> None:
        """Called only under the original live ADMIT fence, after full checks.

        The immutable operation origin can precede its first actual execution.
        Only the original startup snapshot can prove this older intent was
        still an active, unclosed target; a later load or rotated token cannot.
        """
        record = self._recovery_record
        if (not self._recovery_admitted or record is None
                or creation not in record.managed_creations
                or not any(mux.mux_space_id == creation.mux_space_id and mux.name == creation.name
                           for mux in record.mux_spaces)
                or any(item.creation_operation_id == creation.operation_id or item.mux_space_id == creation.mux_space_id
                       for item in record.managed_closures)):
            raise ManagedStorageError("conflict")
        previous = self._continued_closures.get(pending.operation_id)
        if previous is not None and previous != pending:
            raise ManagedStorageError("conflict")
        if previous is None and len(self._continued_closures) >= MAX_MUXES:
            raise ManagedStorageError("capacity")
        self._continued_closures[pending.operation_id] = pending

    def _historical_creation(self, connection: sqlite3.Connection, reservation: ManagedMuxReservationV1) -> ManagedMuxCreatedV1:
        row = connection.execute(
            "SELECT m.name, s.product, s.workspace, s.profile, m.operation_id, s.service_id "
            "FROM mux_intents m JOIN services s USING(service_id) WHERE m.operation_id=?",
            (reservation.operation_id,),
        ).fetchone()
        if row is None or _decode(row) != reservation:
            raise ManagedStorageError("conflict")
        permit = self._permit(connection, reservation.name, reservation.operation_id)
        if permit is None or permit.created is None:
            raise ManagedStorageError("conflict")
        return permit.created

    def _close_permit(self, connection: sqlite3.Connection, operation: str) -> _ClosePermit | None:
        row = connection.execute(
            "SELECT c.instance_id, c.origin_instance_id, c.authority, c.creation_operation_id, "
            "c.phase, m.name, m.service_id FROM mux_close_authorities c "
            "JOIN mux_intents m ON m.operation_id=c.creation_operation_id WHERE c.operation_id=?",
            (operation,),
        ).fetchone()
        if row is None:
            return None
        if row[6] != self._service.service_id:
            raise ManagedStorageError("conflict")
        try:
            _match(row[0], _HEX32)
            _match(row[1], _HEX32)
            _match(row[2], _HEX64)
            creation = self._historical_creation(connection, ManagedMuxReservationV1(row[5], self._service, row[3]))
            result = None if row[4] is None else ManagedMuxCloseStateV1(
                operation, row[1], creation.operation_id, creation.name, creation.mux_space_id,
                ManagedMuxClosePhaseV1(row[4]),
            )
            return _ClosePermit(row[0], row[1], row[2], creation, result)
        except (ValueError, TypeError):
            raise ManagedStorageError("invalid_record") from None

    def _close_authorized(self, connection: sqlite3.Connection, request: ManagedMuxCloseV1) -> _ClosePermit:
        self._close_request(request)
        permit = self._close_permit(connection, request.operation_id)
        if (permit is None or permit.instance_id != request.instance_id
                or not compare_digest(permit.authority, request.authority)
                or (permit.creation.operation_id, permit.creation.name, permit.creation.mux_space_id)
                != (request.creation_operation_id, request.name, request.mux_space_id)):
            raise ManagedStorageError("conflict")
        if permit.result is None or permit.result.phase is not ManagedMuxClosePhaseV1.CLOSED:
            self._reservation(connection, request.name, request.creation_operation_id)
        return permit

    def _inspect_close(self, connection: sqlite3.Connection, operation: str) -> ManagedMuxInspectionV1:
        permit = self._close_permit(connection, operation)
        if permit is None:
            raise ManagedStorageError("not_found")
        creation = permit.creation
        request = ManagedMuxCloseV1(self._service.service_id, permit.instance_id, operation,
                                    creation.operation_id, creation.name, creation.mux_space_id, permit.authority)
        return ManagedMuxInspectionV1(creation, request, permit.result)

    def inspect_mux(
        self, reservation: ManagedMuxReservationV1, *, deadline: float, wait_for_lock: bool = False,
    ) -> ManagedMuxInspectionV1:
        """Freeze a confirmed active identity without issuing any permission.

        Default fail-fast; synchronous/off-loop callers may opt into bounded
        waiting. The original journal and registry remain borrowed throughout.
        """
        if type(reservation) is not ManagedMuxReservationV1 or reservation.service != self._service:
            raise ManagedContractError()
        journal = self._journal
        journal._require_open()
        with journal._fence.lock("lifecycle.lock", deadline=deadline, wait_for_lock=wait_for_lock):
            with journal._database.transaction(deadline=deadline, wait_for_lock=wait_for_lock) as connection:
                self._current(connection, stopped=True)
                self._reservation(connection, reservation.name, reservation.operation_id)
                creation = self._historical_creation(connection, reservation)
                row = connection.execute("SELECT operation_id FROM mux_close_authorities WHERE creation_operation_id=?",
                                          (reservation.operation_id,)).fetchone()
                result = ManagedMuxInspectionV1(creation) if row is None else self._inspect_close(connection, row[0])
                journal._fence._check()
        return result

    def inspect_close_operation(
        self, operation_id: str, *, deadline: float, wait_for_lock: bool = False,
    ) -> ManagedMuxInspectionV1:
        """Observe exact history, including after stop or same-name reuse.

        Validate the original paired journal but do not require current serving
        authority. A request from an older instance is returned unchanged.
        """
        _match(operation_id, _HEX32)
        journal = self._journal
        journal._require_open()
        with journal._fence.lock("lifecycle.lock", deadline=deadline, wait_for_lock=wait_for_lock):
            with journal._database.transaction(deadline=deadline, wait_for_lock=wait_for_lock) as connection:
                journal._read(connection)
                result = self._inspect_close(connection, operation_id)
                journal._fence._check()
        return result

    def issue_close(
        self, reservation: ManagedMuxReservationV1, *, operation_id: str, deadline: float, wait_for_lock: bool = False,
    ) -> ManagedMuxCloseV1:
        if type(reservation) is not ManagedMuxReservationV1 or reservation.service != self._service:
            raise ManagedContractError()
        _match(operation_id, _HEX32)
        journal = self._journal
        journal._require_open()
        with journal._fence.lock("lifecycle.lock", deadline=deadline, wait_for_lock=wait_for_lock):
            with journal._database.transaction(write=True, deadline=deadline, wait_for_lock=wait_for_lock) as connection:
                self._current(connection)
                if connection.execute("SELECT 1 FROM mux_intents WHERE operation_id=?", (operation_id,)).fetchone():
                    raise ManagedStorageError("conflict")
                creation = self._historical_creation(connection, reservation)
                previous = self._close_permit(connection, operation_id)
                if previous is not None and previous.creation != creation:
                    raise ManagedStorageError("conflict")
                if previous is None and connection.execute(
                    "SELECT 1 FROM mux_close_authorities WHERE creation_operation_id=?", (creation.operation_id,),
                ).fetchone():
                    raise ManagedStorageError("conflict")
                if previous is None or previous.result is None or previous.result.phase is not ManagedMuxClosePhaseV1.CLOSED:
                    self._reservation(connection, reservation.name, reservation.operation_id)
                if previous is not None and previous.instance_id == self._instance.instance_id:
                    authority = previous.authority
                else:
                    journal._database.admit_control(connection)
                    authority = token_hex(32)
                    connection.execute(
                        "INSERT INTO mux_close_authorities VALUES (?, ?, ?, ?, ?, NULL) "
                        "ON CONFLICT(operation_id) DO UPDATE SET instance_id=excluded.instance_id, authority=excluded.authority",
                        (operation_id, creation.operation_id, self._instance.instance_id, self._instance.instance_id, authority),
                    )
                result = ManagedMuxCloseV1(self._service.service_id, self._instance.instance_id, operation_id,
                                          creation.operation_id, creation.name, creation.mux_space_id, authority)
                journal._fence._check()
        return result

    def prepare_close(self, request: ManagedMuxCloseV1, use: ManagedMuxCloseUseV1) -> ManagedMuxCloseAdmission:
        self._close_request(request)
        if type(use) is not ManagedMuxCloseUseV1:
            raise ManagedContractError()
        return ManagedMuxCloseAdmission(self, request, use)

    def read_close(self, request: ManagedMuxCloseV1, *, deadline: float) -> ManagedMuxCloseStateV1 | None:
        self._close_request(request)
        journal = self._journal
        journal._require_open()
        with journal._fence.lock("lifecycle.lock", deadline=deadline):
            with journal._database.transaction(deadline=deadline) as connection:
                self._current(connection, stopped=True)
                result = self._close_authorized(connection, request).result
                journal._fence._check()
        return result

    def record_close(
        self, request: ManagedMuxCloseV1, result: ManagedMuxCloseStateV1, *, deadline: float, wait_for_lock: bool = False,
    ) -> ManagedMuxCloseStateV1:
        """Consume only an exact authenticated service result, never raw peer input."""
        self._close_request(request)
        if type(result) is not ManagedMuxCloseStateV1:
            raise ManagedStorageError("conflict")
        journal = self._journal
        journal._require_open()
        with journal._fence.lock("lifecycle.lock", deadline=deadline, wait_for_lock=wait_for_lock):
            with journal._database.transaction(write=True, deadline=deadline, wait_for_lock=wait_for_lock) as connection:
                self._current(connection, stopped=True)
                permit = self._close_authorized(connection, request)
                self._check_close_result(permit, request, result)
                if result != permit.result:
                    journal._database.admit_control(connection)
                    connection.execute("UPDATE mux_close_authorities SET phase=? WHERE operation_id=?",
                                       (result.phase.value, request.operation_id))
                    if result.phase is ManagedMuxClosePhaseV1.CLOSED:
                        deleted = connection.execute(
                            "DELETE FROM muxes WHERE name=? AND service_id=? AND operation_id=?",
                            (request.name, self._service.service_id, request.creation_operation_id),
                        )
                        if deleted.rowcount != 1:
                            raise ManagedStorageError("conflict")
                journal._fence._check()
        return result

    @staticmethod
    def _check_close_result(permit: _ClosePermit, request: ManagedMuxCloseV1, result: ManagedMuxCloseStateV1) -> None:
        expected = ManagedMuxCloseStateV1(request.operation_id, permit.origin_instance_id,
            request.creation_operation_id, request.name, request.mux_space_id, result.phase)
        if result != expected or (permit.result is not None and permit.result.phase is ManagedMuxClosePhaseV1.CLOSED
                                  and result != permit.result):
            raise ManagedStorageError("conflict")

    def verify_close_result(
        self, request: ManagedMuxCloseV1, result: ManagedMuxCloseStateV1, *, deadline: float, wait_for_lock: bool = False,
    ) -> ManagedMuxCloseStateV1:
        """Read-only historical origin/monotonicity check before presenting a reply.

        Transport validates correlation and target, not the registry's origin.
        Verification grants no reconciliation, token renewal or name release.
        """
        self._close_request(request)
        if type(result) is not ManagedMuxCloseStateV1:
            raise ManagedStorageError("conflict")
        journal = self._journal
        journal._require_open()
        with journal._fence.lock("lifecycle.lock", deadline=deadline, wait_for_lock=wait_for_lock):
            with journal._database.transaction(deadline=deadline, wait_for_lock=wait_for_lock) as connection:
                self._current(connection, stopped=True)
                permit = self._close_authorized(connection, request)
                self._check_close_result(permit, request, result)
                journal._fence._check()
        return result


class _ManagedMuxFence:
    """One loop/thread-bound original native context, never a copied lock.

    An uncertain __exit__ is not retried on an exhausted generator, nor counted
    as release success. The borrowed native owner keeps its original close debt.
    """

    def __init__(self, manager: ManagedMuxManagerV1) -> None:
        self._manager = manager
        self._context: AbstractContextManager[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: int | None = None
        self._fence_entry_busy = False
        self._attempted = self._entered = self._exit_attempted = self._closed = False

    def _bind(self) -> None:
        loop = asyncio.get_running_loop()
        thread = get_ident()
        if self._loop is None:
            self._loop, self._thread = loop, thread
        elif self._loop is not loop or self._thread != thread:
            raise ManagedStorageError("conflict")

    async def acquire(self) -> None:
        self._bind()
        if self._closed or self._attempted:
            raise ManagedStorageError("conflict")
        self._attempted = True
        await self._acquire_permission(monotonic() + 5.0)

    async def _acquire_permission(self, deadline: float) -> None:
        journal = self._manager._journal
        while True:
            if self._closed or self._exit_attempted:
                raise ManagedStorageError("closed")
            _check_deadline(deadline)
            try:
                await self._read_once(deadline)
                return
            except ManagedStorageError as error:
                cleanup_pending = journal._fence.cleanup_pending or (
                    not self._fence_entry_busy and journal._database.cleanup_pending
                )
                if (error.code != "busy" or self._exit_attempted
                        or cleanup_pending):
                    raise
                # No check_*/ADMIT/CAS/Session effect has occurred. Release
                # this exact read context; never retry an uncertain release.
                if self._entered:
                    assert self._context is not None
                    self._exit_attempted = True
                    self._context.__exit__(None, None, None)
                    self._entered = False
                cleanup_pending = journal._fence.cleanup_pending or (
                    not self._fence_entry_busy and journal._database.cleanup_pending
                )
                if cleanup_pending:
                    raise ManagedStorageError("unavailable") from None
                self._context = None
                self._discard_permission()
                self._exit_attempted = False  # Prior read's release is confirmed.
                _check_deadline(deadline)
                await asyncio.sleep(min(0.01, max(0.0, deadline - monotonic())))

    async def _read_once(self, deadline: float) -> None:
        journal = self._manager._journal
        journal._require_open()
        self._fence_entry_busy = False
        self._context = journal._fence.lock("lifecycle.lock", deadline=deadline)
        try:
            self._context.__enter__()
        except ManagedStorageError as error:
            if error.code == "busy":
                self._fence_entry_busy = True
            raise
        self._entered = True
        with journal._database.transaction(deadline=deadline) as connection:
            self._read_permission(connection)
            journal._fence._check()
        _check_deadline(deadline)

    def _read_permission(self, connection: sqlite3.Connection) -> None:
        raise NotImplementedError

    def _discard_permission(self) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        self._bind()
        if self._closed:
            return
        if self._exit_attempted:
            raise ManagedStorageError("unavailable")
        if self._entered:
            assert self._context is not None
            self._exit_attempted = True
            self._context.__exit__(None, None, None)
            self._entered = False
        if self._manager._journal._fence.cleanup_pending:
            raise ManagedStorageError("unavailable")
        self._context = None
        self._closed = True


class ManagedMuxRecoveryAdmission(_ManagedMuxFence):
    """Borrow the startup fence; no Session IO or native recapture occurs here."""

    def __init__(
        self, manager: ManagedMuxManagerV1, record: ApplicationContinuityRecordV1 | None,
        use: ManagedMuxCloseUseV1,
    ) -> None:
        super().__init__(manager)
        self._record, self._use = record, use
        self._transition: ManagedServiceTransitionV1 | None = None

    def _discard_permission(self) -> None:
        self._transition = None

    def _read_permission(self, connection: sqlite3.Connection) -> None:
        manager = self._manager
        state = manager._journal._read_state(connection)
        transition = manager._journal._read_transition(connection, state)
        if (state is None or transition is None or state.handoff.instance != manager._instance
                or state.handoff.attempt_id != manager._startup_attempt
                or state.native_identity != manager._startup_native
                or state.handoff.phase not in (ManagedHandoffPhaseV1.PROVISIONAL, ManagedHandoffPhaseV1.ABORTING)
                or self._record is not None and transition.previous is None):
            raise ManagedStorageError("conflict")
        if self._use is ManagedMuxCloseUseV1.ADMIT:
            if state.handoff.stop_requested or state.handoff.phase is not ManagedHandoffPhaseV1.PROVISIONAL:
                raise ManagedStorageError("conflict")
        elif not manager._recovery_admitted:
            raise ManagedStorageError("conflict")
        if manager._recovery_admitted and (
            manager._recovery_record != self._record or manager._recovery_transition != transition
        ):
            raise ManagedStorageError("conflict")
        manager._recovery_history(connection, self._record)
        self._transition = transition

    def check_record(self, record: ApplicationContinuityRecordV1 | None) -> None:
        self._bind()
        if (not self._entered or self._exit_attempted or self._transition is None or record != self._record):
            raise ManagedStorageError("conflict")
        if self._use is ManagedMuxCloseUseV1.ADMIT:
            manager = self._manager
            manager._recovery_record, manager._recovery_transition = record, self._transition
            manager._recovery_admitted = True


class ManagedMuxAdmission(_ManagedMuxFence):
    def __init__(self, manager: ManagedMuxManagerV1, request: ManagedMuxCreateV1) -> None:
        super().__init__(manager)
        self._request = request
        self._permit: _Permit | None = None

    def _discard_permission(self) -> None:
        self._permit = None

    def _read_permission(self, connection: sqlite3.Connection) -> None:
        self._manager._current(connection)
        self._permit = self._manager._authorized(connection, self._request)

    def check_creation(self, previous: ManagedMuxCreatedV1 | None) -> None:
        self._bind()
        permit = self._permit
        if not self._entered or self._exit_attempted or permit is None:
            raise ManagedStorageError("conflict")
        if (
            (permit.created is not None and permit.created != previous)
            or (previous is not None and previous.instance_id != permit.origin_instance_id)
            or (previous is None and permit.origin_instance_id != self._request.instance_id)
        ):
            # Missing history of an old issued operation is not freshness.
            raise ManagedStorageError("conflict")


class ManagedMuxCloseAdmission(_ManagedMuxFence):
    def __init__(self, manager: ManagedMuxManagerV1, request: ManagedMuxCloseV1, use: ManagedMuxCloseUseV1) -> None:
        super().__init__(manager)
        self._request, self._use = request, use
        self._permit: _ClosePermit | None = None

    def _discard_permission(self) -> None:
        self._permit = None

    def _read_permission(self, connection: sqlite3.Connection) -> None:
        self._manager._current(connection, stopped=self._use is not ManagedMuxCloseUseV1.ADMIT)
        self._permit = self._manager._close_authorized(connection, self._request)

    def check_closure(self, creation: ManagedMuxCreatedV1, previous: ManagedMuxCloseStateV1 | None) -> str:
        self._bind()
        permit, request = self._permit, self._request
        if (not self._entered or self._exit_attempted or permit is None or creation != permit.creation):
            raise ManagedStorageError("conflict")
        if previous is None:
            if permit.result is not None or self._use is ManagedMuxCloseUseV1.SETTLE:
                raise ManagedStorageError("conflict")
            if self._use is ManagedMuxCloseUseV1.ADMIT and permit.origin_instance_id != request.instance_id:
                pending = ManagedMuxCloseStateV1(request.operation_id, permit.origin_instance_id,
                    creation.operation_id, creation.name, creation.mux_space_id, ManagedMuxClosePhaseV1.CLEANUP_PENDING)
                self._manager._admit_unaccepted_closure(creation, pending)
            return permit.origin_instance_id
        if type(previous) is not ManagedMuxCloseStateV1 or previous != ManagedMuxCloseStateV1(
            request.operation_id, permit.origin_instance_id, creation.operation_id,
            creation.name, creation.mux_space_id, previous.phase,
        ):
            raise ManagedStorageError("conflict")
        if (permit.result is not None and permit.result.phase is ManagedMuxClosePhaseV1.CLOSED and previous != permit.result
                or self._use is ManagedMuxCloseUseV1.SETTLE and previous.phase is not ManagedMuxClosePhaseV1.CLEANUP_PENDING
                or previous.phase is ManagedMuxClosePhaseV1.CLEANUP_PENDING
                and self._use is not ManagedMuxCloseUseV1.OBSERVE and previous.instance_id != request.instance_id
                and self._manager._continued_closures.get(request.operation_id) != previous):
            # Cross-generation pending must pass the separate recovery barrier,
            # not obtain live ADMIT/SETTLE just by rotating its private token.
            raise ManagedStorageError("conflict")
        return permit.origin_instance_id
