"""Durable storage accounting on the original registry; never a write permit.

The native file owner must separately establish exclusive lifetime, path/file
identity, capacity and complete IO settlement. This borrowed component neither
creates files nor releases reservations based on absence or process identity.
"""

from __future__ import annotations

from _thread import LockType
from collections.abc import Callable
from dataclasses import dataclass, field
from secrets import token_hex
from threading import Lock
from typing import Literal

from ._database import _MAX_TEMPORARY_SEQUENCE, _TEMPORARY_ID_PREFIX
from ._files import (
    ManagedRemovalTarget,
    ManagedStorageError,
    PrivateManagedDirectory,
    _check_deadline,
    _DataCreation,
    _DataRemoval,
    _on_event_loop,
)
from .contracts import _HEX32, _HEX64, ManagedContractError, _match
from .registry import ManagedRegistryV1

MIB = 1024 * 1024
MAX_ALLOCATIONS = 4096
LOG_NAMESPACE_BYTES = 200 * MIB
TEMPORARY_NAMESPACE_BYTES = 512 * MIB
TEMPORARY_INSTANCE_BYTES = 128 * MIB
StorageKind = Literal["log", "trace", "temporary"]
_COLUMNS = "allocation_id,service_id,kind,scope,slot,capacity,root_key,root_device,root_inode,file_device,file_inode"


def _identity(value: tuple[int, int]) -> None:
    if (type(value) is not tuple or len(value) != 2
            or any(type(part) is not int or not 0 <= part < 2**63 for part in value)
            or value[1] == 0):
        raise ManagedContractError()


@dataclass(frozen=True, slots=True)
class ManagedStorageAllocationV1:
    """Exact accounting destination, not permission to adopt its directory."""

    service_id: str
    kind: StorageKind
    instance_id: str | None
    slot: int
    capacity: int
    root_key: str = field(repr=False)
    root_identity: tuple[int, int] = field(repr=False)

    def __post_init__(self) -> None:
        _match(self.service_id, _HEX64)
        _match(self.root_key, _HEX64)
        _identity(self.root_identity)
        if type(self.slot) is not int or type(self.capacity) is not int:
            raise ManagedContractError()
        if self.kind == "temporary":
            if not isinstance(self.instance_id, str):
                raise ManagedContractError()
            _match(self.instance_id, _HEX32)
            if not 0 <= self.slot < 256 or not 4096 <= self.capacity <= TEMPORARY_INSTANCE_BYTES or self.capacity % 4096:
                raise ManagedContractError()
        elif self.kind in ("log", "trace"):
            if self.instance_id is not None or self.capacity != 10 * MIB or not 0 <= self.slot < (5 if self.kind == "log" else 2):
                raise ManagedContractError()
        else:
            raise ManagedContractError()

    def _key(self) -> tuple[str, str, str, int]:
        return self.service_id, self.kind, self.instance_id or "", self.slot


@dataclass(frozen=True, slots=True)
class ManagedStorageReservationV1:
    """Charged capacity, with an optional one-time native identity receipt."""

    allocation_id: str
    allocation: ManagedStorageAllocationV1
    file_identity: tuple[int, int] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _match(self.allocation_id, _HEX32)
        if type(self.allocation) is not ManagedStorageAllocationV1:
            raise ManagedContractError()
        if self.file_identity is not None:
            _identity(self.file_identity)


@dataclass(frozen=True, slots=True)
class ManagedTemporaryPairCapacityRefusedV1:
    """This budget attempt allocated neither slot; not native no-effect proof."""

    allocations: tuple[ManagedStorageAllocationV1, ManagedStorageAllocationV1]
    namespace_key: str
    allocation_ids: tuple[str, str]

    def __post_init__(self) -> None:
        _temporary_pair(self.allocations)
        _match(self.namespace_key, _HEX64)
        _pair_ids(self.allocation_ids)


@dataclass(frozen=True, slots=True)
class _TemporaryRelease:
    database: object = field(repr=False)
    reservation: ManagedStorageReservationV1
    owner: PrivateManagedDirectory = field(repr=False)
    removal: _DataRemoval = field(repr=False)
    target: ManagedRemovalTarget


@dataclass(eq=False, slots=True)
class _TemporaryCreationAttempt:
    database: object = field(repr=False)
    owner: PrivateManagedDirectory = field(repr=False)
    allocations: tuple[ManagedStorageAllocationV1, ManagedStorageAllocationV1]
    allocation_ids: tuple[str, str]
    origin_id: str = field(default_factory=lambda: token_hex(16), repr=False)
    creations: tuple[_DataCreation, _DataCreation] | None = field(default=None, repr=False)
    phase: str = "prepared"
    lock: LockType = field(default_factory=Lock, repr=False)


class ManagedStorageBudgetV1:
    """Borrow the original bounded transactions, without IO/task ownership.

    reserve is idempotent for the *entire* destination, including root identity
    and size. Unknown receipts remain charged and can only be looked up using
    that same destination; a returned row alone never authorizes file creation.
    exclusive=True instead requires a new row in this transaction; an existing
    unbound allocation is never a fresh-creation receipt.
    """

    def __init__(self, registry: ManagedRegistryV1) -> None:
        if type(registry) is not ManagedRegistryV1:
            raise ManagedContractError()
        self._database = registry._database

    def next_temporary_pair_ids(self, *, deadline: float | None = None,
                                wait_for_lock: bool = False, after_id: str | None = None) -> tuple[str, str]:
        """Read candidates, not a reservation; concurrent observations can stale."""
        after = 0 if after_id is None else _temporary_sequence(after_id)
        with self._database.transaction(deadline=deadline, wait_for_lock=wait_for_lock) as connection:
            high_water = connection.execute("SELECT temporary_high_water FROM identity").fetchone()[0]
            result = _next_temporary_ids(max(high_water, after), 2)
        _check_deadline(deadline)
        return result[0], result[1]

    def prepare_temporary_creation(self, allocations: tuple[ManagedStorageAllocationV1, ManagedStorageAllocationV1], *,
                                   owner: PrivateManagedDirectory, deadline: float | None = None,
                                   wait_for_lock: bool = False,
                                   _retain_attempt: Callable[[_TemporaryCreationAttempt], None] | None = None
                                   ) -> _TemporaryCreationAttempt:
        """Retain this original attempt before reserve IO or native creation.

        This does not accept recovered reservations. Unknown reserve receipts
        remain debt; they are not converted to fresh creation/refund authority.
        """
        _temporary_pair(allocations)
        if type(owner) is not PrivateManagedDirectory or allocations[0].capacity != allocations[1].capacity:
            raise ManagedContractError()
        ids = self.next_temporary_pair_ids(deadline=deadline, wait_for_lock=wait_for_lock,
                                           after_id=owner.creation_high_water(deadline=deadline))
        attempt = _TemporaryCreationAttempt(self._database, owner, allocations, ids)
        if _retain_attempt is not None:
            _retain_attempt(attempt)
        pair = owner.prepare_data_creation_pair(ids, capacity=allocations[0].capacity, binding=attempt, deadline=deadline)
        attempt.creations = pair
        try:
            for index in (0, 1):
                self._creation_attempt_target(attempt, index, deadline=deadline)
        except BaseException:
            for creation in pair:
                owner.fence_data_creation(creation, binding=attempt)
            raise
        return attempt

    def _creation_attempt_target(self, attempt: _TemporaryCreationAttempt, index: int, *,
                                 fenced: bool = False, deadline: float | None = None) -> None:
        if (type(attempt) is not _TemporaryCreationAttempt or attempt.database is not self._database
                or attempt.creations is None or type(index) is not int or index not in (0, 1)):
            raise ManagedContractError()
        target = attempt.owner.creation_target(attempt.creations[index], binding=attempt,
                                               require_fenced=fenced, deadline=deadline)
        allocation = attempt.allocations[index]
        if (target.root_key, target.root_identity, target.allocation_id, target.capacity) != (
                allocation.root_key, allocation.root_identity, attempt.allocation_ids[index], allocation.capacity):
            raise ManagedStorageError("conflict")

    def reserve_temporary_creation(self, attempt: _TemporaryCreationAttempt, *, deadline: float | None = None,
                                   wait_for_lock: bool = False
                                   ) -> tuple[ManagedStorageReservationV1, ManagedStorageReservationV1] | ManagedTemporaryPairCapacityRefusedV1:
        if type(attempt) is not _TemporaryCreationAttempt or attempt.database is not self._database:
            raise ManagedContractError()
        _check_deadline(deadline)
        if _on_event_loop() or not attempt.lock.acquire(blocking=False):
            raise ManagedStorageError("busy")
        try:
            if attempt.phase != "prepared":
                raise ManagedStorageError("conflict")
            for index in (0, 1):
                self._creation_attempt_target(attempt, index, deadline=deadline)
            attempt.phase = "unknown"
            result = self.reserve_temporary_pair(attempt.allocations, allocation_ids=attempt.allocation_ids,
                                                 deadline=deadline, wait_for_lock=wait_for_lock,
                                                 _creation_origin=attempt.origin_id)
            attempt.phase = "refused" if type(result) is ManagedTemporaryPairCapacityRefusedV1 else "reserved"
            return result
        finally:
            attempt.lock.release()

    def reconcile_temporary_creation(self, attempt: _TemporaryCreationAttempt, *, deadline: float | None = None,
                                     wait_for_lock: bool = False
                                     ) -> tuple[ManagedStorageReservationV1, ManagedStorageReservationV1] | None:
        """Read original transaction provenance; never reconstruct an attempt."""
        if type(attempt) is not _TemporaryCreationAttempt or attempt.database is not self._database:
            raise ManagedContractError()
        _check_deadline(deadline)
        if _on_event_loop() or not attempt.lock.acquire(blocking=False):
            raise ManagedStorageError("busy")
        try:
            if attempt.phase != "unknown":
                raise ManagedStorageError("conflict")
            found: list[ManagedStorageReservationV1 | None] = []
            with self._database.transaction(deadline=deadline, wait_for_lock=wait_for_lock) as connection:
                for index in (0, 1):
                    allocation_id = attempt.allocation_ids[index]
                    row = connection.execute(f"SELECT {_COLUMNS} FROM storage_allocations WHERE allocation_id=?",
                                             (allocation_id,)).fetchone()
                    if row is None:
                        found.append(None)
                        continue
                    origin = connection.execute("SELECT origin_id FROM storage_creation_origins WHERE allocation_id=?",
                                                (allocation_id,)).fetchone()
                    expected = ManagedStorageReservationV1(allocation_id, attempt.allocations[index])
                    if origin != (attempt.origin_id,) or _decode(row, expected.allocation) != expected:
                        raise ManagedStorageError("conflict")
                    found.append(expected)
            _check_deadline(deadline)
            if found[0] is None and found[1] is None:
                attempt.phase = "unreserved"
                return None
            if found[0] is None or found[1] is None:
                raise ManagedStorageError("conflict")
            attempt.phase = "reserved"
            return found[0], found[1]
        finally:
            attempt.lock.release()

    def release_uncreated_temporary(self, attempt: _TemporaryCreationAttempt, index: int, *,
                                   deadline: float | None = None, wait_for_lock: bool = False) -> None:
        """Refund an exact successful original reserve, never a supplied row."""
        if type(attempt) is not _TemporaryCreationAttempt or attempt.database is not self._database:
            raise ManagedContractError()
        _check_deadline(deadline)
        if _on_event_loop() or not attempt.lock.acquire(blocking=False):
            raise ManagedStorageError("busy")
        try:
            if attempt.phase != "reserved":
                raise ManagedStorageError("unavailable")
            self._creation_attempt_target(attempt, index, fenced=True, deadline=deadline)
            expected = ManagedStorageReservationV1(attempt.allocation_ids[index], attempt.allocations[index])
            with self._database.transaction(write=True, deadline=deadline, wait_for_lock=wait_for_lock) as connection:
                row = connection.execute(f"SELECT {_COLUMNS} FROM storage_allocations WHERE allocation_id=?",
                                         (expected.allocation_id,)).fetchone()
                if row is not None:
                    if _decode(row, expected.allocation) != expected:
                        raise ManagedStorageError("conflict")
                    self._database.admit_growth(connection)
                    connection.execute("DELETE FROM storage_allocations WHERE allocation_id=?", (expected.allocation_id,))
            _check_deadline(deadline)
        finally:
            attempt.lock.release()

    def prepare_temporary_release(self, reservation: ManagedStorageReservationV1, *,
                                  owner: PrivateManagedDirectory, removal: _DataRemoval) -> _TemporaryRelease:
        """Bind the exact native target before removal, without database IO."""
        if (type(reservation) is not ManagedStorageReservationV1
                or reservation.allocation.kind != "temporary" or reservation.file_identity is None
                or type(owner) is not PrivateManagedDirectory):
            raise ManagedContractError()
        target = owner.removal_target(removal)
        _release_target(reservation, target)
        binding = _TemporaryRelease(self._database, reservation, owner, removal, target)
        owner.bind_data_removal(removal, binding)
        return binding

    def release_temporary(self, binding: _TemporaryRelease, *, deadline: float | None = None,
                          wait_for_lock: bool = False) -> None:
        """Release only the original charge; never delete files or choose a slot."""
        if type(binding) is not _TemporaryRelease or binding.database is not self._database:
            raise ManagedContractError()
        _check_deadline(deadline)
        target = binding.owner.completed_removal_target(binding.removal, binding, deadline=deadline)
        if target != binding.target:
            raise ManagedStorageError("conflict")
        reservation = binding.reservation
        _release_target(reservation, target)
        with self._database.transaction(write=True, deadline=deadline, wait_for_lock=wait_for_lock) as connection:
            row = connection.execute(f"SELECT {_COLUMNS} FROM storage_allocations WHERE allocation_id=?",
                                     (reservation.allocation_id,)).fetchone()
            if row is not None:
                previous = _decode(row, reservation.allocation)
                if previous != reservation:
                    raise ManagedStorageError("conflict")
                # Deletion still dirties pages and needs rollback-journal space.
                # Preserve the reserved stop/control headroom.
                self._database.admit_growth(connection)
                connection.execute("DELETE FROM storage_allocations WHERE allocation_id=?", (reservation.allocation_id,))
        _check_deadline(deadline)

    def lookup(self, allocation: ManagedStorageAllocationV1, *, deadline: float | None = None,
               wait_for_lock: bool = False) -> ManagedStorageReservationV1 | None:
        _allocation(allocation)
        with self._database.transaction(deadline=deadline, wait_for_lock=wait_for_lock) as connection:
            row = connection.execute(f"SELECT {_COLUMNS} FROM storage_allocations "
                "WHERE service_id=? AND kind=? AND scope=? AND slot=?", allocation._key()).fetchone()
            return None if row is None else _decode(row, allocation)

    def lookup_temporary_pair(self, allocations: tuple[ManagedStorageAllocationV1, ManagedStorageAllocationV1], *,
                              allocation_ids: tuple[str, str], deadline: float | None = None,
                              wait_for_lock: bool = False,
                              ) -> tuple[ManagedStorageReservationV1, ManagedStorageReservationV1] | None:
        """Observe both original IDs atomically; absence is not native proof.

        Partial, substituted or retargeted pairs conflict. This does not reserve,
        repair, bind or authorize creation, even when both original rows exist.
        """
        _temporary_pair(allocations)
        _pair_ids(allocation_ids)
        with self._database.transaction(deadline=deadline, wait_for_lock=wait_for_lock) as connection:
            found: list[ManagedStorageReservationV1 | None] = []
            for allocation, allocation_id in zip(allocations, allocation_ids, strict=True):
                rows = connection.execute(f"SELECT {_COLUMNS} FROM storage_allocations WHERE "
                    "(service_id=? AND kind=? AND scope=? AND slot=?) OR allocation_id=?",
                    (*allocation._key(), allocation_id)).fetchall()
                if not rows:
                    found.append(None)
                    continue
                if len(rows) != 1:
                    raise ManagedStorageError("conflict")
                reservation = _decode(rows[0], allocation)
                if reservation.allocation_id != allocation_id:
                    raise ManagedStorageError("conflict")
                found.append(reservation)
            if found[0] is None and found[1] is None:
                result = None
            elif found[0] is None or found[1] is None:
                raise ManagedStorageError("conflict")
            else:
                result = (found[0], found[1])
        _check_deadline(deadline)
        return result

    def reserve(self, allocation: ManagedStorageAllocationV1, *, deadline: float | None = None,
                wait_for_lock: bool = False, exclusive: bool = False) -> ManagedStorageReservationV1:
        _allocation(allocation)
        if type(exclusive) is not bool:
            raise ManagedContractError()
        with self._database.transaction(write=True, deadline=deadline, wait_for_lock=wait_for_lock) as connection:
            row = connection.execute(f"SELECT {_COLUMNS} FROM storage_allocations "
                "WHERE service_id=? AND kind=? AND scope=? AND slot=?", allocation._key()).fetchone()
            if row is not None:
                if exclusive:
                    raise ManagedStorageError("conflict")
                return _decode(row, allocation)
            if connection.execute("SELECT 1 FROM services WHERE service_id=?", (allocation.service_id,)).fetchone() is None:
                raise ManagedStorageError("not_found")
            if connection.execute("SELECT count(*) FROM storage_allocations").fetchone()[0] >= MAX_ALLOCATIONS:
                raise ManagedStorageError("capacity")
            temporary = allocation.kind == "temporary"
            used = connection.execute("SELECT coalesce(sum(capacity),0) FROM storage_allocations "
                + ("WHERE kind='temporary'" if temporary else "WHERE kind IN ('log','trace')")).fetchone()[0]
            limit = TEMPORARY_NAMESPACE_BYTES if temporary else LOG_NAMESPACE_BYTES
            if used + allocation.capacity > limit:
                raise ManagedStorageError("capacity")
            if temporary:
                used = connection.execute("SELECT coalesce(sum(capacity),0) FROM storage_allocations "
                    "WHERE service_id=? AND kind='temporary' AND scope=?",
                    (allocation.service_id, allocation.instance_id)).fetchone()[0]
                if used + allocation.capacity > TEMPORARY_INSTANCE_BYTES:
                    raise ManagedStorageError("capacity")
            self._database.admit_growth(connection)  # Never consume stop/control headroom.
            if temporary:
                high_water = connection.execute("SELECT temporary_high_water FROM identity").fetchone()[0]
                allocation_id = _next_temporary_ids(high_water, 1)[0]
                connection.execute("UPDATE identity SET temporary_high_water=?", (high_water + 1,))
            else:
                allocation_id = token_hex(16)
                if allocation_id.startswith(_TEMPORARY_ID_PREFIX):
                    raise ManagedStorageError("conflict")
            result = ManagedStorageReservationV1(allocation_id, allocation)
            connection.execute("INSERT INTO storage_allocations VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL)",
                (result.allocation_id, *allocation._key(), allocation.capacity, allocation.root_key, *allocation.root_identity))
        return result

    def reserve_temporary_pair(self, allocations: tuple[ManagedStorageAllocationV1, ManagedStorageAllocationV1], *,
                               allocation_ids: tuple[str, str],
                               deadline: float | None = None, wait_for_lock: bool = False,
                               _creation_origin: str | None = None,
                               ) -> tuple[ManagedStorageReservationV1, ManagedStorageReservationV1] | ManagedTemporaryPairCapacityRefusedV1:
        """Exclusive atomic pair, with explicit logical-capacity refusal only.

        Existing slots conflict before capacity checks. Unknown commit/close or
        native growth failures never become refusal. Reconcile the original pair
        after uncertainty; do not adopt one slot or retry with new destinations.
        """
        _temporary_pair(allocations)
        _pair_ids(allocation_ids)
        if _creation_origin is not None:
            _match(_creation_origin, _HEX32)
        first, second = allocations
        with self._database.transaction(write=True, deadline=deadline, wait_for_lock=wait_for_lock) as connection:
            high_water = connection.execute("SELECT temporary_high_water FROM identity").fetchone()[0]
            first_sequence, second_sequence = map(_temporary_sequence, allocation_ids)
            if first_sequence <= high_water or second_sequence != first_sequence + 1:
                raise ManagedStorageError("conflict")
            for allocation in allocations:
                if connection.execute("SELECT 1 FROM storage_allocations WHERE service_id=? AND kind=? AND scope=? AND slot=?",
                                      allocation._key()).fetchone() is not None:
                    raise ManagedStorageError("conflict")
            if connection.execute("SELECT 1 FROM storage_allocations WHERE allocation_id IN (?,?)",
                                  allocation_ids).fetchone() is not None:
                raise ManagedStorageError("conflict")
            if connection.execute("SELECT 1 FROM services WHERE service_id=?", (first.service_id,)).fetchone() is None:
                raise ManagedStorageError("not_found")
            rows = connection.execute("SELECT count(*) FROM storage_allocations").fetchone()[0]
            total = connection.execute("SELECT coalesce(sum(capacity),0) FROM storage_allocations "
                                       "WHERE kind='temporary'").fetchone()[0]
            instance = connection.execute("SELECT coalesce(sum(capacity),0) FROM storage_allocations "
                "WHERE service_id=? AND kind='temporary' AND scope=?", (first.service_id, first.instance_id)).fetchone()[0]
            capacity = first.capacity + second.capacity
            result: tuple[ManagedStorageReservationV1, ManagedStorageReservationV1] | ManagedTemporaryPairCapacityRefusedV1
            if (rows + 2 > MAX_ALLOCATIONS or total + capacity > TEMPORARY_NAMESPACE_BYTES
                    or instance + capacity > TEMPORARY_INSTANCE_BYTES):
                result = ManagedTemporaryPairCapacityRefusedV1(allocations, self._database._namespace, allocation_ids)
            else:
                self._database.admit_growth(connection)
                result = (ManagedStorageReservationV1(allocation_ids[0], first),
                          ManagedStorageReservationV1(allocation_ids[1], second))
                for reservation in result:
                    allocation = reservation.allocation
                    connection.execute("INSERT INTO storage_allocations VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL)",
                        (reservation.allocation_id, *allocation._key(), allocation.capacity,
                         allocation.root_key, *allocation.root_identity))
                    if _creation_origin is not None:
                        connection.execute("INSERT INTO storage_creation_origins VALUES (?,?)",
                                           (reservation.allocation_id, _creation_origin))
                connection.execute("UPDATE identity SET temporary_high_water=?", (second_sequence,))
        _check_deadline(deadline)
        return result

    def bind_file(self, reservation: ManagedStorageReservationV1, identity: tuple[int, int], *,
                  deadline: float | None = None, wait_for_lock: bool = False) -> ManagedStorageReservationV1:
        """Record the native owner's completed create, never inspect/adopt a file.

        The caller must retain its original creation owner across unknown IO.
        This cannot turn an unbound row or a missing filename into clean proof.
        """
        if type(reservation) is not ManagedStorageReservationV1:
            raise ManagedContractError()
        _identity(identity)
        with self._database.transaction(write=True, deadline=deadline, wait_for_lock=wait_for_lock) as connection:
            row = connection.execute(f"SELECT {_COLUMNS} FROM storage_allocations WHERE allocation_id=?",
                                     (reservation.allocation_id,)).fetchone()
            if row is None:
                raise ManagedStorageError("not_found")
            previous = _decode(row, reservation.allocation)
            if previous.file_identity is not None and previous.file_identity != identity:
                raise ManagedStorageError("conflict")
            if reservation.file_identity is not None and reservation.file_identity != identity:
                raise ManagedStorageError("conflict")
            if previous.file_identity is None:
                self._database.admit_growth(connection)
                connection.execute("UPDATE storage_allocations SET file_device=?,file_inode=? WHERE allocation_id=?",
                                   (*identity, reservation.allocation_id))
            result = ManagedStorageReservationV1(reservation.allocation_id, reservation.allocation, identity)
        return result


def _release_target(reservation: ManagedStorageReservationV1, target: ManagedRemovalTarget) -> None:
    allocation = reservation.allocation
    if (allocation.kind != "temporary" or reservation.file_identity is None
            or (allocation.root_key, allocation.root_identity, reservation.file_identity, allocation.capacity)
            != (target.root_key, target.root_identity, target.file_identity, target.capacity)):
        raise ManagedStorageError("conflict")


def _temporary_sequence(allocation_id: str) -> int:
    _match(allocation_id, _HEX32)
    if not allocation_id.startswith(_TEMPORARY_ID_PREFIX):
        raise ManagedStorageError("conflict")
    sequence = int(allocation_id[16:], 16)
    if not 1 <= sequence <= _MAX_TEMPORARY_SEQUENCE:
        raise ManagedStorageError("conflict")
    return sequence


def _next_temporary_ids(high_water: int, count: int) -> tuple[str, ...]:
    if type(high_water) is not int or not 0 <= high_water <= _MAX_TEMPORARY_SEQUENCE:
        raise ManagedStorageError("invalid_record")
    if high_water > _MAX_TEMPORARY_SEQUENCE - count:
        raise ManagedStorageError("capacity")
    return tuple(_TEMPORARY_ID_PREFIX + f"{value:016x}"
                 for value in range(high_water + 1, high_water + count + 1))


def _allocation(value: ManagedStorageAllocationV1) -> None:
    if type(value) is not ManagedStorageAllocationV1:
        raise ManagedContractError()


def _temporary_pair(values: tuple[ManagedStorageAllocationV1, ManagedStorageAllocationV1]) -> None:
    if type(values) is not tuple or len(values) != 2:
        raise ManagedContractError()
    for value in values:
        _allocation(value)
    first, second = values
    if (first.kind != "temporary" or second.kind != "temporary" or first.slot == second.slot
            or (first.service_id, first.instance_id, first.root_key, first.root_identity)
            != (second.service_id, second.instance_id, second.root_key, second.root_identity)):
        raise ManagedContractError()


def _pair_ids(values: tuple[str, str]) -> None:
    if type(values) is not tuple or len(values) != 2:
        raise ManagedContractError()
    for value in values:
        _match(value, _HEX32)
    if values[0] == values[1]:
        raise ManagedContractError()


def _decode(row: tuple, expected: ManagedStorageAllocationV1) -> ManagedStorageReservationV1:
    try:
        allocation = ManagedStorageAllocationV1(row[1], row[2], row[3] or None, row[4], row[5], row[6], (row[7], row[8]))
        file_identity = None if row[9] is None and row[10] is None else (row[9], row[10])
        result = ManagedStorageReservationV1(row[0], allocation, file_identity)
    except (ValueError, TypeError, IndexError):
        raise ManagedStorageError("invalid_record") from None
    if allocation != expected:
        raise ManagedStorageError("conflict")
    return result
