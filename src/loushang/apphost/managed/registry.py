"""Product-neutral durable name reservation; no process or connection authority.

The reservation is an intent, not proof of a running or created Mux. Downstream
coordination must reconcile the same operation, never replay an unknown create.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ._database import ManagedDatabase
from ._files import ManagedStorageError
from .contracts import (
    _HEX32,
    ManagedContractError,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
    _match,
    require_mux_name,
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


class ManagedRegistryV1:
    """User/machine-scoped name index, safe to reopen from any client cwd."""

    def __init__(
        self, root: Path, namespace: ManagedNamespaceV1, *, create: bool = False,
    ) -> None:
        if type(namespace) is not ManagedNamespaceV1:
            raise ManagedContractError()
        self._database = ManagedDatabase(root, namespace.namespace_key, create=create)

    def close(self) -> None:
        self._database.close()

    @property
    def cleanup_pending(self) -> bool:
        return self._database.cleanup_pending

    def reserve_mux(self, reservation: ManagedMuxReservationV1) -> ManagedMuxReservationV1:
        if type(reservation) is not ManagedMuxReservationV1:
            raise ManagedContractError()
        with self._database.transaction(write=True) as connection:
            # Retries are identified by the full intent, not just a reused name.
            old = connection.execute(
                "SELECT m.name, s.product, s.workspace, s.profile, m.operation_id, s.service_id "
                "FROM muxes m JOIN services s USING(service_id) "
                "WHERE m.name=? OR m.operation_id=? LIMIT 2",
                (reservation.name, reservation.operation_id),
            ).fetchall()
            if old:
                if len(old) == 1 and _decode(old[0]) == reservation:
                    return reservation
                raise ManagedStorageError("conflict")
            key = reservation.service
            stored = connection.execute(
                "SELECT product, workspace, profile FROM services WHERE service_id=?",
                (key.service_id,),
            ).fetchone()
            if stored is not None and stored != (key.product_id, key.workspace, key.profile):
                raise ManagedStorageError("conflict")
            if connection.execute("SELECT count(*) FROM muxes").fetchone()[0] >= MAX_MUXES:
                raise ManagedStorageError("capacity")
            self._database.admit_growth(connection)
            if stored is None:
                if connection.execute("SELECT count(*) FROM services").fetchone()[0] >= MAX_SERVICES:
                    raise ManagedStorageError("capacity")
                connection.execute("INSERT INTO services VALUES (?, ?, ?, ?)",
                                   (key.service_id, key.product_id, key.workspace, key.profile))
            connection.execute("INSERT INTO muxes VALUES (?, ?, ?)",
                               (reservation.name, key.service_id, reservation.operation_id))
        return reservation

    def resolve(self, name: str) -> ManagedMuxReservationV1 | None:
        require_mux_name(name)
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT m.name, s.product, s.workspace, s.profile, m.operation_id, s.service_id "
                "FROM muxes m JOIN services s USING(service_id) WHERE m.name=?",
                (name,),
            ).fetchone()
            return None if row is None else _decode(row)

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
