"""Read-only global name selection; durable observations never imply readiness.

One borrowed registry transaction snapshots a bounded page of reservations and
their current instance references. No endpoint records, native observation,
directory creation, recovery or mutation. Consumers still PrepareConnection.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from ._files import ManagedStorageError, _check_deadline
from .contracts import (
    _HEX64,
    ManagedContractError,
    ManagedHandoffPhaseV1,
    ManagedInstanceRefV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
    _match,
    require_mux_name,
)
from .lifecycle import _decode_state
from .paths import resolve_managed_registry_root
from .registry import (
    MAX_MUXES,
    MAX_PAGE,
    MAX_SERVICES,
    ManagedMuxReservationV1,
    ManagedRegistryV1,
    _decode,
)

_SELECT = (
    "SELECT m.name, s.product, s.workspace, s.profile, m.operation_id, s.service_id, "
    "i.revision, i.instance_id, i.attempt_id, i.phase, i.stop_requested, "
    "i.process_exited, i.application_cleanup_completed, i.process_scope_settled, i.native_identity, i.trace_application "
    "FROM muxes m JOIN services s USING(service_id) "
    "LEFT JOIN instances i USING(service_id) "
)

_SERVICE_SELECT = (
    "SELECT s.service_id,s.product,s.workspace,s.profile,i.revision,i.instance_id,i.attempt_id,i.phase,"
    "i.stop_requested,i.process_exited,i.application_cleanup_completed,i.process_scope_settled,"
    "i.native_identity,i.trace_application FROM services s LEFT JOIN instances i USING(service_id) "
)


@dataclass(frozen=True, slots=True)
class ManagedMuxObservationV1:
    """Reserved name and recorded lifecycle, not proof of an existing live Mux.

    Workspace is deliberate display/selection metadata; PID, argv, credential
    and record paths are never exposed. The operation ID is correlation only.
    """

    reservation: ManagedMuxReservationV1
    instance: ManagedInstanceRefV1 | None
    revision: int | None
    recorded_phase: ManagedHandoffPhaseV1 | None
    stop_requested: bool
    cleanly_stopped: bool

    def __post_init__(self) -> None:
        if (type(self.reservation) is not ManagedMuxReservationV1
                or type(self.stop_requested) is not bool or type(self.cleanly_stopped) is not bool):
            raise ManagedContractError()
        if self.instance is None:
            if self.revision is not None or self.recorded_phase is not None or self.stop_requested or self.cleanly_stopped:
                raise ManagedContractError()
        elif (type(self.instance) is not ManagedInstanceRefV1
                or self.instance.service_id != self.reservation.service.service_id
                or type(self.revision) is not int or not 1 <= self.revision < 2**63
                or type(self.recorded_phase) is not ManagedHandoffPhaseV1
                or self.cleanly_stopped and not (self.stop_requested or self.recorded_phase is ManagedHandoffPhaseV1.ABORTING)):
            raise ManagedContractError()

    @property
    def name(self) -> str:
        return self.reservation.name

    @property
    def service(self) -> ManagedServiceKeyV1:
        return self.reservation.service


class ManagedDiscoveryV1:
    """Borrow an already open namespace registry; no additional owner to close.

    Native callers can invoke these synchronous reads directly. Async consumers
    must join the actual read before closing the borrowed registry. Pages are
    ordered by case-sensitive global name, not filtered by the client's cwd.
    Separate pages are independent snapshots, not a stable enumeration epoch.
    """

    def __init__(self, registry: ManagedRegistryV1, namespace: ManagedNamespaceV1) -> None:
        root = resolve_managed_registry_root(namespace)
        if (type(registry) is not ManagedRegistryV1 or namespace.user_id != os.geteuid()
                or registry._database._namespace != namespace.namespace_key
                or str(registry._database._directory._root) != str(root)):
            raise ManagedContractError()
        self._registry, self._namespace = registry, namespace

    def resolve(self, name: str, *, deadline: float, wait_for_lock: bool = False) -> ManagedMuxObservationV1 | None:
        require_mux_name(name)
        with self._registry._database.transaction(deadline=deadline, wait_for_lock=wait_for_lock) as connection:
            row = connection.execute(_SELECT + "WHERE m.name=?", (name,)).fetchone()
            result = None if row is None else self._project(row)
            _check_deadline(deadline)
            return result

    def resolve_service(self, service_id: str, *, deadline: float, wait_for_lock: bool = False) -> ManagedServiceKeyV1 | None:
        """Exact service lookup, including services without a registered Mux."""
        _match(service_id, _HEX64)
        with self._registry._database.transaction(deadline=deadline, wait_for_lock=wait_for_lock) as connection:
            row = connection.execute("SELECT product, workspace, profile FROM services WHERE service_id=?",
                                     (service_id,)).fetchone()
            _check_deadline(deadline)
            if row is None:
                return None
            try:
                service = ManagedServiceKeyV1(*row)
                if service.service_id != service_id:
                    raise ManagedContractError()
                return service
            except (ManagedContractError, TypeError):
                raise ManagedStorageError("invalid_record") from None

    def inspect_service(self, service_id: str, *, deadline: float,
                        wait_for_lock: bool = False) -> ManagedServiceObservationV1 | None:
        """One durable snapshot, including services with no remaining mux names."""
        _match(service_id, _HEX64)
        with self._registry._database.transaction(deadline=deadline, wait_for_lock=wait_for_lock) as connection:
            row = connection.execute(
                _SERVICE_SELECT + "WHERE s.service_id=?",
                (service_id,),
            ).fetchone()
            result = None if row is None else self._project_service(row)
        _check_deadline(deadline)
        return result

    def snapshot_namespace(self, *, deadline: float,
                           wait_for_lock: bool = False) -> ManagedDiscoverySnapshotV1:
        """Freeze bounded recorded facts in one transaction, never stop authority.

        Include services with no Mux names. Consumers must not replace confirmed
        instance references with successors, or add later services to this set.
        """
        with self._registry._database.transaction(deadline=deadline, wait_for_lock=wait_for_lock) as connection:
            service_rows = connection.execute(_SERVICE_SELECT + "ORDER BY s.service_id LIMIT ?",
                                              (MAX_SERVICES + 1,)).fetchall()
            mux_rows = connection.execute(_SELECT + "ORDER BY m.name LIMIT ?", (MAX_MUXES + 1,)).fetchall()
            if len(service_rows) > MAX_SERVICES or len(mux_rows) > MAX_MUXES:
                raise ManagedStorageError("capacity")
            try:
                result = ManagedDiscoverySnapshotV1(
                    tuple(self._project_service(row) for row in service_rows),
                    tuple(self._project(row) for row in mux_rows),
                )
            except ManagedContractError:
                raise ManagedStorageError("invalid_record") from None
        _check_deadline(deadline)
        return result

    def _project_service(self, row: tuple) -> ManagedServiceObservationV1:
        try:
            service = ManagedServiceKeyV1(*row[1:4])
            if service.service_id != row[0]:
                raise ManagedContractError()
            if row[4] is None:
                if any(value is not None for value in row[5:]):
                    raise ManagedContractError()
                return ManagedServiceObservationV1(service, None, None, None, False, False)
            state = _decode_state(self._namespace, service, row[4:])
            return ManagedServiceObservationV1(service, state.handoff.instance, state.revision,
                state.handoff.phase, state.handoff.stop_requested, state.cleanly_stopped)
        except (ManagedContractError, TypeError):
            raise ManagedStorageError("invalid_record") from None

    def list_muxes(
        self, *, deadline: float, after: str | None = None, limit: int = MAX_PAGE,
        wait_for_lock: bool = False,
    ) -> tuple[ManagedMuxObservationV1, ...]:
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE:
            raise ManagedContractError()
        if after is not None:
            require_mux_name(after)
        with self._registry._database.transaction(deadline=deadline, wait_for_lock=wait_for_lock) as connection:
            rows = connection.execute(
                _SELECT + "WHERE m.name>? ORDER BY m.name LIMIT ?", (after or "", limit),
            ).fetchall()
            result = tuple(self._project(row) for row in rows)
            _check_deadline(deadline)
            return result

    def _project(self, row: tuple) -> ManagedMuxObservationV1:
        reservation = _decode(row[:6])
        if row[6] is None:
            if any(value is not None for value in row[7:]):
                raise ManagedStorageError("invalid_record")
            return ManagedMuxObservationV1(reservation, None, None, None, False, False)
        state = _decode_state(self._namespace, reservation.service, row[6:])
        return ManagedMuxObservationV1(
            reservation, state.handoff.instance, state.revision, state.handoff.phase,
            state.handoff.stop_requested, state.cleanly_stopped,
        )


@dataclass(frozen=True, slots=True)
class ManagedServiceObservationV1:
    """Recorded service facts only; no PID, credential, endpoint or readiness."""

    service: ManagedServiceKeyV1
    instance: ManagedInstanceRefV1 | None
    revision: int | None
    recorded_phase: ManagedHandoffPhaseV1 | None
    stop_requested: bool
    cleanly_stopped: bool

    def __post_init__(self) -> None:
        if (type(self.service) is not ManagedServiceKeyV1 or type(self.stop_requested) is not bool
                or type(self.cleanly_stopped) is not bool):
            raise ManagedContractError()
        if self.instance is None:
            if self.revision is not None or self.recorded_phase is not None or self.stop_requested or self.cleanly_stopped:
                raise ManagedContractError()
        elif (type(self.instance) is not ManagedInstanceRefV1 or self.instance.service_id != self.service.service_id
              or type(self.revision) is not int or not 1 <= self.revision < 2**63
              or type(self.recorded_phase) is not ManagedHandoffPhaseV1
              or self.cleanly_stopped and not (self.stop_requested or self.recorded_phase is ManagedHandoffPhaseV1.ABORTING)):
            raise ManagedContractError()


@dataclass(frozen=True, slots=True)
class ManagedDiscoverySnapshotV1:
    """One namespace's recorded set, not liveness or permission to stop it."""

    services: tuple[ManagedServiceObservationV1, ...]
    muxes: tuple[ManagedMuxObservationV1, ...]

    def __post_init__(self) -> None:
        if (type(self.services) is not tuple or type(self.muxes) is not tuple
                or len(self.services) > MAX_SERVICES or len(self.muxes) > MAX_MUXES
                or any(type(item) is not ManagedServiceObservationV1 for item in self.services)
                or any(type(item) is not ManagedMuxObservationV1 for item in self.muxes)):
            raise ManagedContractError()
        services = {item.service.service_id: item for item in self.services}
        if len(services) != len(self.services) or len({item.name for item in self.muxes}) != len(self.muxes):
            raise ManagedContractError()
        for mux in self.muxes:
            expected = ManagedServiceObservationV1(mux.service, mux.instance, mux.revision,
                mux.recorded_phase, mux.stop_requested, mux.cleanly_stopped)
            if services.get(mux.service.service_id) != expected:
                raise ManagedContractError()


__all__ = ["ManagedDiscoveryV1", "ManagedMuxObservationV1", "ManagedServiceObservationV1",
           "ManagedDiscoverySnapshotV1"]
