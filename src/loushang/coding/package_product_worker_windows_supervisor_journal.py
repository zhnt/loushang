"""Product-rooted Windows custody for one Worker Supervisor history.

The generic Supervisor owns state transitions. This owner supplies a strict,
append-only Windows file under the pinned Product root. A committed lock with
missing or torn history remains debt; no read or writer repairs it implicitly.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import BinaryIO

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.journal import journal_file_lock_at
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_regular_file_at,
    windows_flush_directory,
    windows_flush_file,
    windows_listdir_at,
    windows_regular_file_stream_names,
    windows_stat_at,
)
from loushang.harness.worker.journal import (
    WorkerAttemptRecordV1,
    WorkerSupervisorJournal,
    _validate_history,
)

_NAME = "worker-supervisor.jsonl"
_LOCK = _NAME + ".lock"
_MAX_RECORDS = 4096
_MAX_BYTES = 16 * 1024 * 1024


class CodingWindowsProductWorkerSupervisorJournal(WorkerSupervisorJournal):
    """Reuse the Supervisor state machine with Product-pinned native I/O."""

    def __init__(self, product: WindowsLocalWheelProductSessionOwner) -> None:
        if (
            os.name != "nt"
            or type(product) is not WindowsLocalWheelProductSessionOwner
            or product.policy.product_id != "coding"
        ):
            raise ValueError("Windows Worker Supervisor Product owner is invalid")
        product.assert_root_gc_authority_current()
        self._path = product.state_root / _NAME
        self._product = product
        self._thread_lock = threading.Lock()
        self._active_root: int | None = None
        self._active_acl: WindowsPrivateDirectoryAcl | None = None
        self._active_lock: BinaryIO | None = None
        self._active_raw: bytes | None = None

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        # Match the recovery inventory's Product-gate-before-journal order.
        with self._product.gc_gate.guard(), self._thread_lock:
            self._product.assert_root_gc_authority_current()
            with (
                WindowsPrivateDirectoryAcl() as acl,
                self._product.epoch_runtime.borrow_product_state_root_descriptor() as root,
            ):
                self._require_root(root, acl)
                self._prepare_lock(root, acl)
                with journal_file_lock_at(root, _LOCK, "exclusive") as lock:
                    self._active_root = root
                    self._active_acl = acl
                    self._active_lock = lock
                    try:
                        initialized = self._validate_lock(root, acl)
                        raw = self._read_raw(root, acl)
                        self._require_lock_history(initialized, raw)
                        self._active_raw = raw
                        yield
                        self._require_root(root, acl)
                        self._product.assert_root_gc_authority_current()
                    finally:
                        self._active_root = None
                        self._active_acl = None
                        self._active_lock = None
                        self._active_raw = None

    def _load_unlocked(self) -> tuple[WorkerAttemptRecordV1, ...]:
        root, acl, _ = self._active()
        initialized = self._validate_lock(root, acl)
        raw = self._read_raw(root, acl)
        self._require_lock_history(initialized, raw)
        self._active_raw = raw
        return self._decode(raw)

    def _append_unlocked(self, record: WorkerAttemptRecordV1) -> None:
        if type(record) is not WorkerAttemptRecordV1:
            raise TypeError("Windows Worker Supervisor requires an exact record")
        root, acl, lock = self._active()
        expected = self._active_raw
        if expected is None and self._validate_lock(root, acl):
            raise self._error(
                "Windows Worker Supervisor lock is orphaned",
                code="worker_supervisor_journal_corrupt",
            )
        line = canonical_json_bytes(record.to_dict()) + b"\n"
        if (
            record.record_revision > _MAX_RECORDS
            or len(expected or b"") + len(line) > _MAX_BYTES
        ):
            raise self._error(
                "Windows Worker Supervisor history capacity is exhausted",
                code="worker_supervisor_journal_capacity",
            )
        if expected is None:
            self._mark_lock_initialized(lock)
        self._append(root, acl, expected=expected, line=line)
        self._active_raw = (expected or b"") + line

    def inspect_records(self) -> tuple[WorkerAttemptRecordV1, ...]:
        """Read current Product history without creating a lock or journal."""

        with self._product.gc_gate.guard(), self._thread_lock:
            self._product.assert_root_gc_authority_current()
            with (
                WindowsPrivateDirectoryAcl() as acl,
                self._product.epoch_runtime.borrow_product_state_root_descriptor() as root,
            ):
                self._require_root(root, acl)
                try:
                    initialized = self._validate_lock(root, acl)
                except FileNotFoundError:
                    try:
                        windows_stat_at(root, _NAME)
                    except FileNotFoundError:
                        self._require_root(root, acl)
                        return ()
                    raise self._error(
                        "Windows Worker Supervisor lock is missing",
                        code="worker_supervisor_journal_corrupt",
                    ) from None
                with journal_file_lock_at(root, _LOCK, "shared"):
                    initialized = self._validate_lock(root, acl)
                    raw = self._read_raw(root, acl)
                    self._require_lock_history(initialized, raw)
                    records = self._decode(raw)
                self._require_root(root, acl)
                self._product.assert_root_gc_authority_current()
                return records

    def _prepare_lock(self, root: int, acl: WindowsPrivateDirectoryAcl) -> None:
        try:
            windows_stat_at(root, _LOCK)
        except FileNotFoundError:
            try:
                windows_stat_at(root, _NAME)
            except FileNotFoundError:
                pass
            else:
                raise self._error(
                    "Windows Worker Supervisor lock is missing",
                    code="worker_supervisor_journal_corrupt",
                ) from None
        try:
            descriptor = open_windows_regular_file_at(
                root,
                _LOCK,
                create_new=True,
                write=True,
                security_descriptor=acl.security_descriptor,
                read_control=True,
            )
        except FileExistsError:
            descriptor = open_windows_regular_file_at(
                root, _LOCK, create_new=False, write=True, read_control=True
            )
            created = False
        else:
            created = True
        try:
            acl.validate(descriptor)
            self._require_plain_stream(descriptor)
            if created:
                if os.write(descriptor, b"\0") != 1:
                    raise OSError("Windows Worker Supervisor lock write failed")
                windows_flush_file(descriptor)
            elif os.fstat(descriptor).st_size != 1:
                raise self._error(
                    "Windows Worker Supervisor lock is invalid",
                    code="worker_supervisor_journal_corrupt",
                )
        finally:
            os.close(descriptor)
        if created:
            windows_flush_directory(root)

    def _validate_lock(self, root: int, acl: WindowsPrivateDirectoryAcl) -> bool:
        descriptor = open_windows_regular_file_at(
            root, _LOCK, create_new=False, write=False, read_control=True
        )
        try:
            acl.validate(descriptor)
            self._require_plain_stream(descriptor)
            if os.fstat(descriptor).st_size != 1:
                raise self._error(
                    "Windows Worker Supervisor lock is invalid",
                    code="worker_supervisor_journal_corrupt",
                )
            state = os.read(descriptor, 1)
            if state not in {b"\0", b"\1"}:
                raise self._error(
                    "Windows Worker Supervisor lock is invalid",
                    code="worker_supervisor_journal_corrupt",
                )
            return state == b"\1"
        finally:
            os.close(descriptor)

    def _read_raw(self, root: int, acl: WindowsPrivateDirectoryAcl) -> bytes | None:
        try:
            descriptor = open_windows_regular_file_at(
                root, _NAME, create_new=False, write=False, read_control=True
            )
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, "rb") as source:
            acl.validate(source.fileno())
            self._require_plain_stream(source.fileno())
            return source.read(_MAX_BYTES + 1)

    def _append(
        self,
        root: int,
        acl: WindowsPrivateDirectoryAcl,
        *,
        expected: bytes | None,
        line: bytes,
    ) -> None:
        try:
            descriptor = open_windows_regular_file_at(
                root,
                _NAME,
                create_new=True,
                write=True,
                security_descriptor=acl.security_descriptor,
                read_control=True,
            )
        except FileExistsError:
            descriptor = open_windows_regular_file_at(
                root, _NAME, create_new=False, write=True, read_control=True
            )
            created = False
        else:
            created = True
        with os.fdopen(descriptor, "r+b") as output:
            acl.validate(output.fileno())
            self._require_plain_stream(output.fileno())
            observed = output.read(_MAX_BYTES + 1)
            if (created and (expected is not None or observed)) or (
                not created and observed != expected
            ):
                raise self._error(
                    "Windows Worker Supervisor history changed",
                    code="worker_supervisor_journal_corrupt",
                )
            output.seek(0, os.SEEK_END)
            remaining = memoryview(line)
            while remaining:
                written = output.write(remaining)
                if written is None or written <= 0:
                    raise OSError("Windows Worker Supervisor append made no progress")
                remaining = remaining[written:]
            output.flush()
            windows_flush_file(output.fileno())
        if created:
            windows_flush_directory(root)

    def _decode(self, raw: bytes | None) -> tuple[WorkerAttemptRecordV1, ...]:
        if raw is None:
            return ()
        if not raw or len(raw) > _MAX_BYTES or not raw.endswith(b"\n"):
            raise self._error(
                "Windows Worker Supervisor history is torn",
                code="worker_supervisor_journal_corrupt",
            )
        try:
            lines = raw.splitlines()
            if len(lines) > _MAX_RECORDS:
                raise ValueError("Worker Supervisor history is over capacity")
            records = tuple(
                WorkerAttemptRecordV1.from_dict(
                    json.loads(line, object_pairs_hook=_reject_duplicate_keys)
                )
                for line in lines
            )
            if raw != b"".join(
                canonical_json_bytes(record.to_dict()) + b"\n" for record in records
            ) or any(
                record.record_revision != index
                for index, record in enumerate(records, start=1)
            ):
                raise ValueError("Worker Supervisor history bytes changed")
            _validate_history(records)
            return records
        except (TypeError, UnicodeError, ValueError) as exc:
            raise self._error(
                "Windows Worker Supervisor history is invalid",
                code="worker_supervisor_journal_corrupt",
            ) from exc

    def _require_root(self, root: int, acl: WindowsPrivateDirectoryAcl) -> None:
        if type(root) is not int or root < 0:
            raise ValueError("Windows Worker Supervisor root handle is invalid")
        acl.validate(root)
        if not os.path.samestat(os.fstat(root), self._path.parent.lstat()):
            raise self._error(
                "Windows Worker Supervisor Product root changed",
                code="worker_supervisor_journal_corrupt",
            )
        names = windows_listdir_at(root)
        prefixed = {
            name for name in names if name.casefold().startswith("worker-supervisor")
        }
        if not prefixed <= {_NAME, _LOCK}:
            raise self._error(
                "Windows Worker Supervisor Product root has foreign entries",
                code="worker_supervisor_journal_corrupt",
            )

    def _active(self) -> tuple[int, WindowsPrivateDirectoryAcl, BinaryIO]:
        root, acl, lock = self._active_root, self._active_acl, self._active_lock
        if root is None or acl is None or lock is None:
            raise RuntimeError("Windows Worker Supervisor lock is not held")
        return root, acl, lock

    def _require_lock_history(self, initialized: bool, raw: bytes | None) -> None:
        if initialized != (raw is not None):
            raise self._error(
                "Windows Worker Supervisor lock/history mismatch",
                code="worker_supervisor_journal_corrupt",
            )

    @staticmethod
    def _mark_lock_initialized(lock: BinaryIO) -> None:
        lock.seek(0)
        if lock.read(1) != b"\0":
            raise ValueError("Windows Worker Supervisor lock state changed")
        lock.seek(0)
        if lock.write(b"\1") != 1:
            raise OSError("Windows Worker Supervisor lock commit failed")
        lock.flush()
        windows_flush_file(lock.fileno())

    @staticmethod
    def _require_plain_stream(descriptor: int) -> None:
        if windows_regular_file_stream_names(descriptor) != ("::$DATA",):
            raise ValueError("Windows Worker Supervisor named stream is invalid")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Worker Supervisor JSON has duplicate fields")
        result[key] = value
    return result


def open_coding_windows_product_worker_supervisor_journal(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsProductWorkerSupervisorJournal:
    return CodingWindowsProductWorkerSupervisorJournal(product)


__all__ = [
    "CodingWindowsProductWorkerSupervisorJournal",
    "open_coding_windows_product_worker_supervisor_journal",
]
