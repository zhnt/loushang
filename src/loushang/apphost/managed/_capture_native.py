"""Original two-stream storage lifecycle, called by one retained native worker.

The composing lease serializes calls and retains this owner on cancellation.
Directory lifetime is borrowed; closing a capture never closes a shared root.
"""

from __future__ import annotations

from ._files import (
    MAX_RECORD_BYTES,
    ManagedDataFileSnapshot,
    ManagedStorageError,
    PrivateManagedDirectory,
    _DataRemoval,
)
from .storage_budget import (
    ManagedStorageAllocationV1,
    ManagedStorageBudgetV1,
    ManagedStorageReservationV1,
    ManagedTemporaryPairCapacityRefusedV1,
    _TemporaryCreationAttempt,
    _TemporaryRelease,
)


class NativeOutputCapture:
    def __init__(self, owner: PrivateManagedDirectory, budget: ManagedStorageBudgetV1,
                 allocations: tuple[ManagedStorageAllocationV1, ManagedStorageAllocationV1]) -> None:
        self.owner, self.budget, self.allocations = owner, budget, allocations
        self.attempt: _TemporaryCreationAttempt | None = None
        self.snapshots: list[ManagedDataFileSnapshot | None] = [None, None]
        self.releases: list[_TemporaryRelease | None] = [None, None]
        self.removals: list[_DataRemoval | None] = [None, None]
        self.released = [False, False]
        self.deleted = [False, False]
        self.started = self.ready = self.lost = self.sealed = self.closed = False
        self.write_unknown = False

    @property
    def cleanup_pending(self) -> bool:
        return self.started and not self.closed

    def prepare(self) -> bool:
        """True means both charged files; False only a known capacity refusal."""
        if self.started or self.closed:
            raise ManagedStorageError("conflict")
        self.started = True
        self.budget.prepare_temporary_creation(self.allocations, owner=self.owner, _retain_attempt=self._retain_attempt)
        assert self.attempt is not None
        result = self.budget.reserve_temporary_creation(self.attempt)
        if isinstance(result, ManagedTemporaryPairCapacityRefusedV1):
            self.lost = True
            self.close()
            return False
        assert self.attempt.creations is not None
        with self.owner.lock("capture.lock", create=True):
            for index, creation in enumerate(self.attempt.creations):
                snapshot = self.owner.create_data(creation, binding=self.attempt)
                self.snapshots[index] = snapshot
                self.budget.bind_file(result[index], snapshot.identity)
        self.ready = True
        return True

    def _retain_attempt(self, attempt: _TemporaryCreationAttempt) -> None:
        self.attempt = attempt

    def append(self, index: int, content: bytes) -> None:
        if type(index) is not int or index not in (0, 1) or type(content) is not bytes or len(content) > MAX_RECORD_BYTES:
            raise ManagedStorageError("invalid_record")
        if self.closed or self.sealed or not self.ready:
            raise ManagedStorageError("closed")
        if self.lost:
            return
        snapshot = self.snapshots[index]
        assert snapshot is not None and self.attempt is not None and self.attempt.creations is not None
        if snapshot.size + len(content) > self.allocations[index].capacity:
            self.lost = True  # Sticky across both streams; discard neither file here.
            return
        try:
            with self.owner.lock("capture.lock"):
                self.snapshots[index] = self.owner.append_data(
                    self.attempt.creations[index].name, content, expected=snapshot,
                    capacity=self.allocations[index].capacity,
                )
        except BaseException:
            self.lost = self.write_unknown = True
            raise

    def seal(self) -> tuple[ManagedDataFileSnapshot, ManagedDataFileSnapshot] | None:
        if self.closed or not self.ready:
            raise ManagedStorageError("closed")
        self.sealed = True
        if self.lost:
            return None
        first, second = self.snapshots
        assert first is not None and second is not None
        return first, second

    def read(self, index: int, *, max_bytes: int) -> bytes:
        if type(index) is not int or index not in (0, 1):
            raise ManagedStorageError("invalid_record")
        if self.closed or not self.sealed or self.lost:
            raise ManagedStorageError("closed")
        assert self.attempt is not None and self.attempt.creations is not None
        snapshot = self.snapshots[index]
        assert snapshot is not None
        with self.owner.lock("capture.lock"):
            return self.owner.read_data(self.attempt.creations[index].name, expected=snapshot,
                                        capacity=self.allocations[index].capacity, max_bytes=max_bytes)

    def close(self) -> None:
        if self.closed:
            return
        self.sealed = True
        attempt = self.attempt
        if attempt is None:
            self.closed = True  # No native registration or reservation was returned.
            return
        if attempt.phase == "unknown":
            self.budget.reconcile_temporary_creation(attempt)
        if attempt.creations is None:
            if attempt.phase != "prepared":
                raise ManagedStorageError("unavailable")
            attempt.creations = self.owner.pending_creation_pair(binding=attempt)
            if attempt.creations is None:
                self.closed = True  # Original owner confirms no enrollment; reserve never began.
                return
        for creation in attempt.creations:
            self.owner.fence_data_creation(creation, binding=attempt)
        if self.write_unknown:
            raise ManagedStorageError("unavailable")
        if attempt.phase in {"prepared", "refused", "unreserved"}:
            if any(creation.phase != "fenced" for creation in attempt.creations):
                raise ManagedStorageError("unavailable")
            self.closed = True
            return
        if attempt.phase != "reserved":
            raise ManagedStorageError("unavailable")
        for index, creation in enumerate(attempt.creations):
            if self.released[index]:
                continue
            if creation.phase == "fenced":
                self.budget.release_uncreated_temporary(attempt, index)
            elif creation.phase == "created":
                release = self.releases[index]
                if release is None:
                    snapshot = self.snapshots[index] or creation.snapshot
                    assert snapshot is not None
                    reserved = ManagedStorageReservationV1(attempt.allocation_ids[index], self.allocations[index])
                    bound = self.budget.bind_file(reserved, snapshot.identity)
                    removal = self.removals[index]
                    if removal is None:
                        removal = self.owner.prepare_data_removal(creation.name, "removed-" + creation.allocation_id,
                                                                  expected=snapshot, capacity=creation.capacity)
                        self.removals[index] = removal
                    release = self.budget.prepare_temporary_release(bound, owner=self.owner, removal=removal)
                    self.releases[index] = release
                if not self.deleted[index]:
                    with self.owner.lock("capture.lock"):
                        self.owner.remove_data(release.removal)
                    self.deleted[index] = True
                self.budget.release_temporary(release)
            else:
                raise ManagedStorageError("unavailable")
            self.released[index] = True
        self.closed = True
