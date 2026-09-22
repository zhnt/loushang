"""Product-neutral durable name reservation; no process or connection authority.

The reservation is an intent, not proof of a running or created Mux. Downstream
coordination must reconcile the same operation, never replay an unknown create.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loushang.appserver.managed_mux import ManagedMuxCreatedV1

from ._database import ManagedDatabase
from ._files import ManagedStorageError, _check_deadline
from .contracts import (
    _HEX32,
    _HEX64,
    ManagedContractError,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
    _match,
    require_mux_name,
    require_service_alias,
)

MAX_SERVICES = 128
MAX_MUXES = 4096
MAX_PAGE = 64


@dataclass(frozen=True, slots=True)
class ManagedMuxReservationV1:
    """A persisted intent only; deliberately contains neither PID nor endpoint."""

    name: str
    service: ManagedServiceKeyV1
    operation_id: str

    def __post_init__(self) -> None:
        require_mux_name(self.name)
        if type(self.service) is not ManagedServiceKeyV1:
            raise ManagedContractError()
        _match(self.operation_id, _HEX32)


@dataclass(frozen=True, slots=True)
class ManagedServiceAliasReservationV1:
    """Immutable service label intent, not a live instance or startup permit."""

    name: str
    service: ManagedServiceKeyV1
    operation_id: str

    def __post_init__(self) -> None:
        require_service_alias(self.name)
        if type(self.service) is not ManagedServiceKeyV1:
            raise ManagedContractError()
        _match(self.operation_id, _HEX32)


@dataclass(frozen=True, slots=True)
class ManagedMuxCreationInspectionV1:
    """Read-only creation history, not authority or evidence of a live Mux."""

    reservation: ManagedMuxReservationV1
    active: bool
    created: ManagedMuxCreatedV1 | None

    def __post_init__(self) -> None:
        if type(self.reservation) is not ManagedMuxReservationV1 or type(self.active) is not bool:
            raise ManagedContractError()
        if self.created is not None and (type(self.created) is not ManagedMuxCreatedV1
                or self.created.operation_id != self.reservation.operation_id
                or self.created.name != self.reservation.name):
            raise ManagedContractError()


class ManagedRegistryV1:
    """User/machine-scoped name index, safe to reopen from any client cwd."""

    def __init__(
        self, root: Path, namespace: ManagedNamespaceV1, *, create: bool = False, defer_open: bool = False,
        exclusive_create: bool = False, create_parents: bool = False, deployment_id: str | None = None,
        service_admission_required: bool | None = None,
    ) -> None:
        if type(namespace) is not ManagedNamespaceV1 or type(defer_open) is not bool:
            raise ManagedContractError()
        self._database = ManagedDatabase(root, namespace.namespace_key, create=create, defer_open=True,
                                         exclusive_create=exclusive_create, create_parents=create_parents,
                                         deployment_id=deployment_id,
                                         service_admission_required=service_admission_required)
        if defer_open:
            return
        try:
            self.open()
        except BaseException as error:
            try:
                self.close()
            except BaseException:
                error.add_note("managed_registry_cleanup_incomplete")
            raise

    def open(self, *, deadline: float | None = None, wait_for_lock: bool = False) -> None:
        self._database.open(deadline=deadline, wait_for_lock=wait_for_lock)

    def close(self) -> None:
        self._database.close()

    @property
    def cleanup_pending(self) -> bool:
        return self._database.cleanup_pending

    def reserve_mux(
        self, reservation: ManagedMuxReservationV1, *, deadline: float | None = None,
        wait_for_lock: bool = False,
    ) -> ManagedMuxReservationV1:
        if type(reservation) is not ManagedMuxReservationV1:
            raise ManagedContractError()
        with self._database.transaction(write=True, deadline=deadline, wait_for_lock=wait_for_lock) as connection:
            if connection.execute("SELECT 1 FROM mux_close_authorities WHERE operation_id=?",
                                  (reservation.operation_id,)).fetchone() is not None:
                raise ManagedStorageError("conflict")
            # History never reactivates a released operation, even under the
            # same name. Only the exact still-active intent is an idempotent retry.
            old = connection.execute(
                "SELECT m.name, s.product, s.workspace, s.profile, m.operation_id, s.service_id "
                "FROM mux_intents m JOIN services s USING(service_id) WHERE m.operation_id=?",
                (reservation.operation_id,),
            ).fetchone()
            active = connection.execute("SELECT operation_id FROM muxes WHERE name=?",
                                        (reservation.name,)).fetchone()
            if old is not None:
                if _decode(old) == reservation and active == (reservation.operation_id,):
                    return reservation
                raise ManagedStorageError("conflict")
            if active is not None:
                raise ManagedStorageError("conflict")
            key = reservation.service
            stored = connection.execute(
                "SELECT product, workspace, profile FROM services WHERE service_id=?",
                (key.service_id,),
            ).fetchone()
            if stored is not None and stored != (key.product_id, key.workspace, key.profile):
                raise ManagedStorageError("conflict")
            if connection.execute("SELECT count(*) FROM mux_intents").fetchone()[0] >= MAX_MUXES:
                raise ManagedStorageError("capacity")
            self._database.admit_growth(connection)
            if stored is None:
                if connection.execute("SELECT count(*) FROM services").fetchone()[0] >= MAX_SERVICES:
                    raise ManagedStorageError("capacity")
                connection.execute("INSERT INTO services VALUES (?, ?, ?, ?)",
                                   (key.service_id, key.product_id, key.workspace, key.profile))
            values = (reservation.name, key.service_id, reservation.operation_id)
            connection.execute("INSERT INTO mux_intents VALUES (?, ?, ?)", values)
            connection.execute("INSERT INTO muxes VALUES (?, ?, ?)", values)
        return reservation

    def reserve_service_alias(
        self, reservation: ManagedServiceAliasReservationV1, *, deadline: float | None = None,
        wait_for_lock: bool = False,
    ) -> ManagedServiceAliasReservationV1:
        if type(reservation) is not ManagedServiceAliasReservationV1:
            raise ManagedContractError()
        key = reservation.service
        with self._database.transaction(write=True, deadline=deadline, wait_for_lock=wait_for_lock) as connection:
            rows = connection.execute(
                "SELECT a.name, s.product, s.workspace, s.profile, a.operation_id, s.service_id "
                "FROM service_aliases a JOIN services s USING(service_id) "
                "WHERE a.name=? OR a.service_id=? OR a.operation_id=?",
                (reservation.name, key.service_id, reservation.operation_id),
            ).fetchall()
            if rows:
                if len(rows) != 1 or _decode_alias(rows[0]) != reservation:
                    raise ManagedStorageError("conflict")
            else:
                stored = connection.execute(
                    "SELECT product, workspace, profile FROM services WHERE service_id=?", (key.service_id,),
                ).fetchone()
                if stored is not None and stored != (key.product_id, key.workspace, key.profile):
                    raise ManagedStorageError("conflict")
                if (connection.execute("SELECT count(*) FROM service_aliases").fetchone()[0] >= MAX_SERVICES
                        or stored is None and connection.execute("SELECT count(*) FROM services").fetchone()[0] >= MAX_SERVICES):
                    raise ManagedStorageError("capacity")
                self._database.admit_growth(connection)
                if stored is None:
                    connection.execute("INSERT INTO services VALUES (?, ?, ?, ?)",
                                       (key.service_id, key.product_id, key.workspace, key.profile))
                connection.execute("INSERT INTO service_aliases VALUES (?, ?, ?)",
                                   (reservation.name, key.service_id, reservation.operation_id))
        _check_deadline(deadline)
        return reservation

    def resolve_service_alias(
        self, name: str, *, deadline: float | None = None, wait_for_lock: bool = False,
    ) -> ManagedServiceAliasReservationV1 | None:
        require_service_alias(name)
        with self._database.transaction(deadline=deadline, wait_for_lock=wait_for_lock) as connection:
            row = connection.execute(
                "SELECT a.name, s.product, s.workspace, s.profile, a.operation_id, s.service_id "
                "FROM service_aliases a JOIN services s USING(service_id) WHERE a.name=?", (name,),
            ).fetchone()
            result = None if row is None else _decode_alias(row)
        _check_deadline(deadline)
        return result

    def resolve(self, name: str) -> ManagedMuxReservationV1 | None:
        require_mux_name(name)
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT m.name, s.product, s.workspace, s.profile, m.operation_id, s.service_id "
                "FROM muxes m JOIN services s USING(service_id) WHERE m.name=?",
                (name,),
            ).fetchone()
            return None if row is None else _decode(row)

    def inspect_mux_creation(
        self, operation_id: str, *, deadline: float | None = None, wait_for_lock: bool = False,
    ) -> ManagedMuxCreationInspectionV1 | None:
        """Read the exact intent even before service admission or after release.

        No permit is issued and no name is adopted. A missing creation receipt
        is unknown, never proof that an earlier RPC had no effect.
        """
        _match(operation_id, _HEX32)
        with self._database.transaction(deadline=deadline, wait_for_lock=wait_for_lock) as connection:
            row = connection.execute(
                "SELECT m.name, s.product, s.workspace, s.profile, m.operation_id, s.service_id "
                "FROM mux_intents m JOIN services s USING(service_id) WHERE m.operation_id=?",
                (operation_id,),
            ).fetchone()
            result = None
            if row is not None:
                reservation = _decode(row)
                active = connection.execute("SELECT name, service_id FROM muxes WHERE operation_id=?",
                                             (operation_id,)).fetchone()
                if active is not None and active != (reservation.name, reservation.service.service_id):
                    raise ManagedStorageError("invalid_record")
                permit = connection.execute(
                    "SELECT instance_id, origin_instance_id, authority, created_instance_id, mux_space_id "
                    "FROM mux_authorities WHERE operation_id=?", (operation_id,),
                ).fetchone()
                created = None
                if permit is not None:
                    try:
                        _match(permit[0], _HEX32)
                        _match(permit[1], _HEX32)
                        _match(permit[2], _HEX64)
                        if (permit[3] is None) != (permit[4] is None):
                            raise ManagedContractError()
                        if permit[3] is not None:
                            created = ManagedMuxCreatedV1(operation_id, permit[3], reservation.name, permit[4])
                            if created.instance_id != permit[1]:
                                raise ManagedContractError()
                    except (ValueError, TypeError):
                        raise ManagedStorageError("invalid_record") from None
                result = ManagedMuxCreationInspectionV1(reservation, active is not None, created)
        _check_deadline(deadline)
        return result

    def list_muxes(
        self, *, after: str | None = None, limit: int = MAX_PAGE,
    ) -> tuple[ManagedMuxReservationV1, ...]:
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE:
            raise ManagedContractError()
        if after is not None:
            require_mux_name(after)
        with self._database.transaction() as connection:
            return tuple(_decode(row) for row in connection.execute(
                "SELECT m.name, s.product, s.workspace, s.profile, m.operation_id, s.service_id "
                "FROM muxes m JOIN services s USING(service_id) "
                "WHERE m.name>? ORDER BY m.name LIMIT ?", (after or "", limit),
            ).fetchall())


def _decode(row: tuple) -> ManagedMuxReservationV1:
    try:
        key = ManagedServiceKeyV1(row[1], row[2], row[3])
        reservation = ManagedMuxReservationV1(row[0], key, row[4])
        if key.service_id != row[5]:
            raise ManagedContractError()
        return reservation
    except (ManagedContractError, IndexError, TypeError):
        raise ManagedStorageError("invalid_record") from None


def _decode_alias(row: tuple) -> ManagedServiceAliasReservationV1:
    try:
        key = ManagedServiceKeyV1(row[1], row[2], row[3])
        result = ManagedServiceAliasReservationV1(row[0], key, row[4])
        if key.service_id != row[5]:
            raise ManagedContractError()
        return result
    except (ManagedContractError, IndexError, TypeError):
        raise ManagedStorageError("invalid_record") from None
