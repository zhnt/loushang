"""Windows-native Package runtime leases under a pinned Product control root.

This is the Windows counterpart of the Linux lease registry, not a Product
runtime owner. A caller must bind its coordination lock to the epoch cutover
owner and retain the registry until all local lease handles are released.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import Lock, local
from typing import BinaryIO

from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
    JournalFileError,
    JournalLockUnavailable,
    JsonlSnapshot,
    decode_jsonl,
    journal_file_lock_at,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
    PackageEpochLeaseSnapshotV1,
    PackageEpochRuntimeLeaseV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
    PackageEpochRuntimeLeaseRecordV1,
    PackageEpochRuntimeLeaseRegistryError,
    PackageEpochRuntimeQuiescenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover import (
    _PinnedWindowsAuthority,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_regular_file_at,
    supports_windows_rooted_io,
    windows_flush_directory,
    windows_flush_file,
)

_JOURNAL_NAME = "runtime-leases.jsonl"
_COORDINATION_NAME = "coordination.lock"
_MAX_JOURNAL_BYTES = 64 * 1024 * 1024
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_RECORD_CODEC = FunctionalJournalRecordCodec(
    encoder=PackageEpochRuntimeLeaseRecordV1.to_dict,
    decoder=PackageEpochRuntimeLeaseRecordV1.from_dict,
)


def _terminal_repaired_runtime_records(
    records: tuple[PackageEpochRuntimeLeaseRecordV1, ...],
) -> tuple[PackageEpochRuntimeLeaseRecordV1, ...]:
    """A later registration or clean release supersedes an earlier repair."""

    latest_by_runtime = {record.lease.runtime_id: record for record in records}
    return tuple(
        sorted(
            (
                record
                for record in latest_by_runtime.values()
                if record.kind == "orphan_repaired"
            ),
            key=lambda record: record.record_revision,
        )
    )


@dataclass(frozen=True, slots=True)
class PackageWindowsRuntimeQuiescenceV1(PackageEpochRuntimeQuiescenceV1):
    """Pinned active set plus terminal repairs observed under the same lock."""

    repaired_runtime_records: tuple[PackageEpochRuntimeLeaseRecordV1, ...] = ()

    def __post_init__(self) -> None:
        PackageEpochRuntimeQuiescenceV1.__post_init__(self)
        if type(self.repaired_runtime_records) is not tuple or any(
            type(record) is not PackageEpochRuntimeLeaseRecordV1
            or record.kind != "orphan_repaired"
            or record.store_id != self.store_id
            for record in self.repaired_runtime_records
        ):
            raise ValueError("Package repaired runtime history is invalid")


class PackageWindowsRuntimeLeaseHandle:
    """Retain one native liveness lock until its durable release."""

    def __init__(
        self,
        *,
        registry: PackageWindowsEpochRuntimeLeaseRegistry,
        lease: PackageEpochRuntimeLeaseV1,
        lock: AbstractContextManager[BinaryIO],
    ) -> None:
        self.lease = lease
        self._registry = registry
        self._lock = lock
        self._released = False
        self._mutex = Lock()

    def release(self) -> None:
        with self._mutex:
            if not self._released:
                self._registry._release(self)

    def __enter__(self) -> PackageWindowsRuntimeLeaseHandle:
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


class PackageWindowsEpochRuntimeLeaseRegistry:
    """Durable lease history and OS liveness locks inside one rooted control."""

    def __init__(
        self,
        *,
        control_root: Path,
        fences: PackageEpochFenceJournal,
        store_id: str,
    ) -> None:
        if not supports_windows_rooted_io():
            raise self._error(
                "Windows runtime leases are unavailable",
                "package_epoch_lease_unavailable",
            )
        if (
            not isinstance(control_root, Path)
            or not control_root.is_absolute()
            or ".." in control_root.parts
            or control_root == Path(control_root.anchor)
        ):
            raise ValueError("Package runtime lease control root is invalid")
        if not isinstance(fences, PackageEpochFenceJournal):
            raise TypeError("Package epoch fence journal is required")
        if fences.path.parent != control_root:
            raise ValueError("Package epoch fence and runtime lease must share a root")
        if not isinstance(store_id, str) or _SAFE_ID.fullmatch(store_id) is None:
            raise ValueError("Package runtime lease store is invalid")
        self.control_root = control_root
        self.path = control_root / _JOURNAL_NAME
        self.fences = fences
        self.store_id = store_id
        self._root = _PinnedWindowsAuthority.open(control_root)
        self._local_lease_ids: set[str] = set()
        self._active_operations = 0
        self._closed = False
        self._mutex = Lock()
        self._runtime_transaction = local()

    def close(self) -> None:
        with self._mutex:
            if self._active_operations:
                raise self._error(
                    "Package runtime lease operation remains active",
                    "package_epoch_lease_busy",
                )
            if self._local_lease_ids:
                raise self._error(
                    "Package runtime leases remain locally active",
                    "package_epoch_lease_live",
                )
            if not self._closed:
                self._root.close()
                self._closed = True

    def register(
        self, *, runtime_id: str, runtime_protocol_epoch: int
    ) -> PackageWindowsRuntimeLeaseHandle:
        if not isinstance(runtime_id, str) or not runtime_id:
            raise ValueError("Package runtime identity is required")
        if type(runtime_protocol_epoch) is not int or runtime_protocol_epoch < 1:
            raise ValueError("Package runtime protocol epoch is invalid")
        issued: PackageWindowsRuntimeLeaseHandle | None = None
        try:
            with self._coordination():
                with self._journal(write=True) as descriptor:
                    records, active = self._load(descriptor)
                    fence = self.fences.current(self.store_id)
                    if fence is None:
                        raise self._error(
                            "Package Store has no current epoch fence",
                            "package_epoch_unfenced",
                        )
                    if runtime_protocol_epoch < fence.minimum_runtime_protocol_epoch:
                        raise self._error(
                            "Package runtime protocol is too old",
                            "package_runtime_protocol_unsupported",
                        )
                    self._require_live(active)
                    if any(
                        lease.runtime_epoch != fence.epoch
                        or lease.store_root_identity != fence.fenced_root_identity
                        for lease in active.values()
                    ):
                        raise self._error(
                            "Package Store has mixed runtime epochs",
                            "package_epoch_leases_mixed",
                        )
                    if any(lease.runtime_id == runtime_id for lease in active.values()):
                        raise self._error(
                            "Package runtime identity is already registered",
                            "package_epoch_lease_identity_conflict",
                        )
                    receipt_id = sha256(secrets.token_bytes(32)).hexdigest()
                    lease = PackageEpochRuntimeLeaseV1.create(
                        runtime_id=runtime_id,
                        runtime_epoch=fence.epoch,
                        store_root_identity=fence.fenced_root_identity,
                        registration_receipt_id=receipt_id,
                    )
                    lock = journal_file_lock_at(
                        self._root.descriptor,
                        self._lease_lock_name(lease.lease_id),
                        "exclusive",
                        blocking=False,
                        create=True,
                    )
                    try:
                        lock.__enter__()
                        if self.fences.current(self.store_id) != fence:
                            raise self._error(
                                "Package epoch advanced during registration",
                                "package_epoch_fence_stale",
                            )
                        self._append(
                            descriptor,
                            PackageEpochRuntimeLeaseRecordV1(
                                record_revision=len(records) + 1,
                                store_id=self.store_id,
                                kind="registered",
                                lease=lease,
                            ),
                        )
                        created_handle = PackageWindowsRuntimeLeaseHandle(
                            registry=self, lease=lease, lock=lock
                        )
                        with self._mutex:
                            self._local_lease_ids.add(lease.lease_id)
                        issued = created_handle
                    except BaseException:
                        lock.__exit__(None, None, None)
                        raise
        except BaseException:
            if issued is not None:
                try:
                    issued._lock.__exit__(None, None, None)
                finally:
                    with self._mutex:
                        self._local_lease_ids.discard(issued.lease.lease_id)
            raise
        assert issued is not None
        return issued

    def snapshot(self, *, store_id: str) -> PackageEpochLeaseSnapshotV1:
        if store_id != self.store_id:
            raise self._error(
                "Package runtime lease store changed",
                "package_epoch_lease_store_changed",
            )
        if getattr(self._runtime_transaction, "active", False):
            self._root.assert_visible()
            return self._snapshot_under_coordination()
        with self._coordination():
            return self._snapshot_under_coordination()

    def _snapshot_under_coordination(self) -> PackageEpochLeaseSnapshotV1:
        with self._journal(write=False) as descriptor:
            records, active = self._load(descriptor)
            self._require_live(active)
            if not active:
                raise self._error(
                    "Package Store has no active runtime", "package_epoch_lease_absent"
                )
            return PackageEpochLeaseSnapshotV1.create(
                store_id=self.store_id,
                owner_revision=len(records),
                active_leases=tuple(active.values()),
            )

    @contextmanager
    def shared_runtime(self, *, store_id: str) -> Iterator[None]:
        """Hold the native coordination lock across Product admission/effects.

        Windows journal locks are exclusive for both declared lock modes. A
        snapshot in this thread reads under the already-held lock; mutations
        must wait until the Product transaction exits.
        """

        if store_id != self.store_id:
            raise self._error(
                "Package runtime lease store changed",
                "package_epoch_lease_store_changed",
            )
        if getattr(self._runtime_transaction, "active", False):
            raise self._error(
                "Package runtime transaction is already active",
                "package_epoch_lease_busy",
            )
        with self._coordination():
            self._runtime_transaction.active = True
            try:
                yield
            finally:
                self._runtime_transaction.active = False

    @contextmanager
    def exclusive_runtime_quiescence(
        self, *, store_id: str
    ) -> Iterator[PackageWindowsRuntimeQuiescenceV1]:
        if store_id != self.store_id:
            raise self._error(
                "Package runtime lease store changed",
                "package_epoch_lease_store_changed",
            )
        with self._coordination():
            with self._journal(write=False) as descriptor:
                records, active = self._load(descriptor)
                self._require_live(active)
                yield PackageWindowsRuntimeQuiescenceV1(
                    store_id=self.store_id,
                    owner_revision=len(records) + 1,
                    active_runtime_lease_ids=tuple(sorted(active)),
                    repaired_runtime_records=_terminal_repaired_runtime_records(
                        records
                    ),
                )

    def repair_orphan(
        self,
        lease_id: str,
        *,
        validation_guard: Callable[
            [PackageEpochRuntimeLeaseV1], AbstractContextManager[None]
        ]
        | None = None,
    ) -> None:
        """Repair under the orphan lock and an optional Product proof guard."""

        if validation_guard is not None and not callable(validation_guard):
            raise TypeError("Package orphan validation guard must be callable")
        with self._coordination():
            with self._journal(write=True) as descriptor:
                records, active = self._load(descriptor)
                lease = active.get(lease_id)
                if lease is None:
                    raise self._error(
                        "Package runtime lease is not active",
                        "package_epoch_lease_absent",
                    )
                if (
                    sum(item.runtime_id == lease.runtime_id for item in active.values())
                    != 1
                ):
                    raise self._error(
                        "Package runtime lease identity is ambiguous",
                        "package_epoch_lease_journal_corrupt",
                    )
                with self._mutex:
                    if lease_id in self._local_lease_ids:
                        raise self._error(
                            "Package runtime lease remains live",
                            "package_epoch_lease_live",
                        )
                try:
                    with self._orphan_lock(lease_id):
                        with (
                            nullcontext()
                            if validation_guard is None
                            else validation_guard(lease)
                        ):
                            self._append(
                                descriptor,
                                PackageEpochRuntimeLeaseRecordV1(
                                    record_revision=len(records) + 1,
                                    store_id=self.store_id,
                                    kind="orphan_repaired",
                                    lease=lease,
                                ),
                            )
                except JournalLockUnavailable as exc:
                    raise self._error(
                        "Package runtime lease remains live", "package_epoch_lease_live"
                    ) from exc

    @contextmanager
    def guard_orphan_recovery(
        self, *, store_id: str, lease_id: str
    ) -> Iterator[PackageEpochRuntimeLeaseV1]:
        """Hold Package coordination and the exact orphan lock for Product work.

        This does not repair the lease or authorize a Product native effect.
        Product must acquire its GC gate only after entering this guard.
        """

        if store_id != self.store_id:
            raise self._error(
                "Package runtime lease store changed",
                "package_epoch_lease_store_changed",
            )
        with self._coordination():
            with self._journal(write=False) as descriptor:
                _, active = self._load(descriptor)
                lease = active.get(lease_id)
                if lease is None:
                    raise self._error(
                        "Package runtime lease is not active",
                        "package_epoch_lease_absent",
                    )
                if (
                    sum(item.runtime_id == lease.runtime_id for item in active.values())
                    != 1
                ):
                    raise self._error(
                        "Package runtime lease identity is ambiguous",
                        "package_epoch_lease_journal_corrupt",
                    )
                with self._mutex:
                    if lease_id in self._local_lease_ids:
                        raise self._error(
                            "Package runtime lease remains live",
                            "package_epoch_lease_live",
                        )
                try:
                    with self._orphan_lock(lease_id):
                        yield lease
                        self._root.assert_visible()
                except JournalLockUnavailable as exc:
                    raise self._error(
                        "Package runtime lease remains live",
                        "package_epoch_lease_live",
                    ) from exc

    def review_orphans(
        self, *, store_id: str
    ) -> tuple[PackageEpochRuntimeLeaseV1, ...]:
        """Read exact orphaned leases without changing their journal state."""

        if store_id != self.store_id:
            raise self._error(
                "Package runtime lease store changed",
                "package_epoch_lease_store_changed",
            )
        with self._coordination():
            with self._journal(write=False) as descriptor:
                _, active = self._load(descriptor)
                orphans: list[PackageEpochRuntimeLeaseV1] = []
                for lease_id, lease in sorted(active.items()):
                    with self._mutex:
                        if lease_id in self._local_lease_ids:
                            continue
                    try:
                        with self._orphan_lock(lease_id):
                            orphans.append(lease)
                    except JournalLockUnavailable:
                        continue
                return tuple(orphans)

    def _release(self, handle: PackageWindowsRuntimeLeaseHandle) -> None:
        with self._coordination():
            with self._journal(write=True) as descriptor:
                records, active = self._load(descriptor)
                if active.get(handle.lease.lease_id) != handle.lease:
                    raise self._error(
                        "Package runtime lease changed", "package_epoch_lease_stale"
                    )
                self._append(
                    descriptor,
                    PackageEpochRuntimeLeaseRecordV1(
                        record_revision=len(records) + 1,
                        store_id=self.store_id,
                        kind="released",
                        lease=handle.lease,
                    ),
                )
                try:
                    handle._lock.__exit__(None, None, None)
                finally:
                    handle._released = True
                    with self._mutex:
                        self._local_lease_ids.discard(handle.lease.lease_id)

    @contextmanager
    def _coordination(self) -> Iterator[None]:
        if getattr(self._runtime_transaction, "active", False):
            raise self._error(
                "Package runtime transaction is active", "package_epoch_lease_busy"
            )
        with self._mutex:
            if self._closed:
                raise self._error(
                    "Package runtime lease owner is closed",
                    "package_epoch_lease_closed",
                )
            self._active_operations += 1
        try:
            self._root.assert_visible()
            with journal_file_lock_at(
                self._root.descriptor, _COORDINATION_NAME, "exclusive", create=True
            ):
                self._root.assert_visible()
                yield
                self._root.assert_visible()
        finally:
            with self._mutex:
                self._active_operations -= 1
            self._root.assert_visible()

    @contextmanager
    def _journal(self, *, write: bool) -> Iterator[int | None]:
        try:
            descriptor = open_windows_regular_file_at(
                self._root.descriptor,
                _JOURNAL_NAME,
                create_new=False,
                write=write,
            )
        except FileNotFoundError:
            yield None
            return
        try:
            yield descriptor
        finally:
            os.close(descriptor)

    def _load(
        self, descriptor: int | None
    ) -> tuple[
        tuple[PackageEpochRuntimeLeaseRecordV1, ...],
        dict[str, PackageEpochRuntimeLeaseV1],
    ]:
        if descriptor is None:
            return (), {}
        try:
            metadata = os.fstat(descriptor)
            if metadata.st_size > _MAX_JOURNAL_BYTES:
                raise ValueError("Package runtime lease journal exceeds budget")
            os.lseek(descriptor, 0, os.SEEK_SET)
            raw = bytearray()
            while chunk := os.read(descriptor, 64 * 1024):
                raw.extend(chunk)
                if len(raw) > _MAX_JOURNAL_BYTES:
                    raise ValueError("Package runtime lease journal exceeds budget")
            decoded = raw.decode("utf-8")
            _assert_no_duplicate_keys(decoded)
            loaded: JsonlSnapshot[None, PackageEpochRuntimeLeaseRecordV1] = (
                decode_jsonl(
                    decoded,
                    target=self.path,
                    record_codec=_RECORD_CODEC,
                )
            )
            records = loaded.records
        except (OSError, UnicodeError, ValueError, JournalFileError) as exc:
            raise self._error(
                "Package runtime lease journal is corrupt",
                "package_epoch_lease_journal_corrupt",
            ) from exc
        active: dict[str, PackageEpochRuntimeLeaseV1] = {}
        seen: set[str] = set()
        for revision, record in enumerate(records, start=1):
            lease_id = record.lease.lease_id
            if record.record_revision != revision or record.store_id != self.store_id:
                raise self._error(
                    "Package runtime lease history changed",
                    "package_epoch_lease_journal_corrupt",
                )
            if record.kind == "registered":
                if lease_id in seen:
                    raise self._error(
                        "Package runtime lease was reused",
                        "package_epoch_lease_journal_corrupt",
                    )
                active[lease_id] = record.lease
                seen.add(lease_id)
            elif active.get(lease_id) != record.lease:
                raise self._error(
                    "Package runtime lease release changed",
                    "package_epoch_lease_journal_corrupt",
                )
            else:
                del active[lease_id]
        return records, active

    def _append(
        self, descriptor: int | None, record: PackageEpochRuntimeLeaseRecordV1
    ) -> None:
        payload = (
            json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8")
        if len(payload) > _MAX_JOURNAL_BYTES:
            raise self._error(
                "Package runtime lease journal is full",
                "package_epoch_lease_journal_full",
            )
        created = descriptor is None
        if created:
            try:
                descriptor = open_windows_regular_file_at(
                    self._root.descriptor,
                    _JOURNAL_NAME,
                    create_new=True,
                    write=True,
                )
            except OSError as exc:
                raise self._error(
                    "Package runtime lease journal first write failed",
                    "package_epoch_lease_journal_corrupt",
                ) from exc
        assert descriptor is not None
        try:
            position = os.lseek(descriptor, 0, os.SEEK_END)
            if position + len(payload) > _MAX_JOURNAL_BYTES:
                raise self._error(
                    "Package runtime lease journal is full",
                    "package_epoch_lease_journal_full",
                )
            while payload:
                written = os.write(descriptor, payload)
                if written < 1:
                    raise OSError("Package runtime lease append made no progress")
                payload = payload[written:]
            windows_flush_file(descriptor)
            if created:
                windows_flush_directory(self._root.descriptor)
        except OSError as exc:
            raise self._error(
                "Package runtime lease append failed",
                "package_epoch_lease_journal_corrupt",
            ) from exc
        finally:
            if created:
                os.close(descriptor)

    def _require_live(self, active: dict[str, PackageEpochRuntimeLeaseV1]) -> None:
        for lease_id in active:
            with self._mutex:
                if lease_id in self._local_lease_ids:
                    continue
            try:
                with self._orphan_lock(lease_id):
                    raise self._error(
                        "Package runtime lease is orphaned",
                        "package_epoch_lease_orphaned",
                    )
            except PackageEpochRuntimeLeaseRegistryError:
                raise
            except JournalLockUnavailable:
                continue

    @contextmanager
    def _orphan_lock(self, lease_id: str) -> Iterator[None]:
        try:
            with journal_file_lock_at(
                self._root.descriptor,
                self._lease_lock_name(lease_id),
                "exclusive",
                blocking=False,
                create=False,
            ):
                yield
        except JournalLockUnavailable:
            raise
        except OSError as exc:
            raise self._error(
                "Package runtime lease liveness is unknown",
                "package_epoch_lease_liveness_unknown",
            ) from exc

    @staticmethod
    def _lease_lock_name(lease_id: str) -> str:
        if (
            type(lease_id) is not str
            or len(lease_id) != 64
            or any(char not in "0123456789abcdef" for char in lease_id)
        ):
            raise ValueError("Package runtime lease identity is invalid")
        return f"runtime-leases.jsonl.{lease_id}.lease"

    @staticmethod
    def _error(message: str, code: str) -> PackageEpochRuntimeLeaseRegistryError:
        return PackageEpochRuntimeLeaseRegistryError(message, code=code)


def _assert_no_duplicate_keys(raw: str) -> None:
    def decode(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate Package runtime lease JSON key")
            result[key] = value
        return result

    for line in raw.splitlines():
        if line.strip():
            json.loads(line, object_pairs_hook=decode)


__all__ = [
    "PackageWindowsEpochRuntimeLeaseRegistry",
    "PackageWindowsRuntimeLeaseHandle",
]
