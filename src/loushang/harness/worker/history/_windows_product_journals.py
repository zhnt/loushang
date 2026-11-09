"""Fixed Windows Supervisor and C5 programs using original Worker/Resource owners.

The access port borrows Product admission and root custody. It does not grant
authority, retain handles, repair records, or combine the two commit protocols.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from hashlib import sha256
from pathlib import Path
from typing import BinaryIO, Generic, Protocol, TypeVar

from loushang.foundation.json import _unique_json_object_hook
from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.journal import journal_file_lock_at
from loushang.harness.resources.packages._windows_journal_file import (
    WindowsJournalFileIO,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_regular_file_at,
    windows_flush_directory,
    windows_flush_file,
    windows_listdir_at,
    windows_stat_at,
)
from loushang.harness.worker.activation_state_journal import (
    WorkerActivationStateJournalError,
    _canonical_json_bytes,
    _StateRecord,
)
from loushang.harness.worker.journal import (
    WorkerAttemptRecordV1,
    WorkerSupervisorJournal,
    _validate_history,
)

from ._activation import (
    decode_activation_history,
    project_retained_attempts,
    validate_activation_attempt_history,
)

_S_NAME = "worker-supervisor.jsonl"
_S_LOCK = _S_NAME + ".lock"
_C_NAME = "worker-activation-state.jsonl"
_C_LOCK = _C_NAME + ".lock"
_HEAD = re.compile(r"worker-activation-state\.h[0-9]{8}\.json\Z")
_T = TypeVar("_T")


class WindowsHistoryAccess(Protocol):
    def guard(
        self, *, require_write: bool = False
    ) -> AbstractContextManager[object]: ...
    def assert_current(self) -> None: ...
    def borrow_state_root(self) -> AbstractContextManager[int]: ...


def _head_name(revision: int) -> str:
    return f"worker-activation-state.h{revision:08d}.json"


def _head_bytes(revision: int, raw: bytes) -> bytes:
    return canonical_json_bytes(
        {
            "byteCount": len(raw),
            "digest": sha256(raw).hexdigest(),
            "revision": revision,
            "version": 1,
        }
    )


_reject_duplicate_keys = _unique_json_object_hook(
    lambda: "Worker Supervisor JSON has duplicate fields"
)


class WindowsSupervisorJournal(WorkerSupervisorJournal):
    """Reuse the Supervisor state machine with Product-pinned native I/O."""

    _max_bytes: Callable[[], int]
    _max_records: Callable[[], int]

    def __init__(self, path: Path, *, access: WindowsHistoryAccess) -> None:
        self._path = path
        self._access = access
        self._thread_lock = threading.Lock()
        self._active_root: int | None = None
        self._active_acl: WindowsPrivateDirectoryAcl | None = None
        self._active_lock: BinaryIO | None = None
        self._active_raw: bytes | None = None
        self._file_io = WindowsJournalFileIO(
            name=_S_NAME,
            max_bytes=self._max_bytes(),
            lock_error=lambda: self._error(
                "Windows Worker Supervisor lock is invalid",
                code="worker_supervisor_journal_corrupt",
            ),
            change_error=lambda: self._error(
                "Windows Worker Supervisor history changed",
                code="worker_supervisor_journal_corrupt",
            ),
            stream_error=lambda: ValueError(
                "Windows Worker Supervisor named stream is invalid"
            ),
            lock_write_error="Windows Worker Supervisor lock write failed",
            lock_commit_error="Windows Worker Supervisor lock commit failed",
            append_error="Windows Worker Supervisor append made no progress",
        )

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        with self._access.guard(require_write=True), self._thread_lock:
            self._access.assert_current()
            with (
                WindowsPrivateDirectoryAcl() as acl,
                self._access.borrow_state_root() as root,
            ):
                self._require_root(root, acl)
                self._prepare_lock(root, acl)
                with journal_file_lock_at(root, _S_LOCK, "exclusive") as lock:
                    self._active_root = root
                    self._active_acl = acl
                    self._active_lock = lock
                    try:
                        initialized = self._file_io.validate_lock(
                            root, acl, locked_handle=lock
                        )
                        raw = self._file_io.read(root, acl)
                        self._require_lock_history(initialized, raw)
                        self._active_raw = raw
                        yield
                        self._require_root(root, acl)
                        self._access.assert_current()
                    finally:
                        self._active_root = None
                        self._active_acl = None
                        self._active_lock = None
                        self._active_raw = None

    def _load_unlocked(self) -> tuple[WorkerAttemptRecordV1, ...]:
        root, acl, lock = self._active()
        initialized = self._file_io.validate_lock(root, acl, locked_handle=lock)
        raw = self._file_io.read(root, acl)
        self._require_lock_history(initialized, raw)
        self._active_raw = raw
        return self._decode(raw)

    def _append_unlocked(self, record: WorkerAttemptRecordV1) -> None:
        if type(record) is not WorkerAttemptRecordV1:
            raise TypeError("Windows Worker Supervisor requires an exact record")
        root, acl, lock = self._active()
        expected = self._active_raw
        if expected is None and self._file_io.validate_lock(
            root, acl, locked_handle=lock
        ):
            raise self._error(
                "Windows Worker Supervisor lock is orphaned",
                code="worker_supervisor_journal_corrupt",
            )
        line = canonical_json_bytes(record.to_dict()) + b"\n"
        if (
            record.record_revision > self._max_records()
            or len(expected or b"") + len(line) > self._max_bytes()
        ):
            raise self._error(
                "Windows Worker Supervisor history capacity is exhausted",
                code="worker_supervisor_journal_capacity",
            )
        if expected is None:
            self._mark_lock_initialized(lock)
        self._file_io.append(root, acl, expected=expected, line=line)
        self._active_raw = (expected or b"") + line

    def inspect_records(self) -> tuple[WorkerAttemptRecordV1, ...]:
        """Read current Product history without creating a lock or journal."""
        with self._access.guard(), self._thread_lock:
            self._access.assert_current()
            with (
                WindowsPrivateDirectoryAcl() as acl,
                self._access.borrow_state_root() as root,
            ):
                self._require_root(root, acl)
                try:
                    windows_stat_at(root, _S_LOCK)
                except FileNotFoundError:
                    try:
                        windows_stat_at(root, _S_NAME)
                    except FileNotFoundError:
                        self._require_root(root, acl)
                        return ()
                    raise self._error(
                        "Windows Worker Supervisor lock is missing",
                        code="worker_supervisor_journal_corrupt",
                    ) from None
                with journal_file_lock_at(root, _S_LOCK, "shared") as lock:
                    initialized = self._file_io.validate_lock(
                        root, acl, locked_handle=lock
                    )
                    raw = self._file_io.read(root, acl)
                    self._require_lock_history(initialized, raw)
                    records = self._decode(raw)
                self._require_root(root, acl)
                self._access.assert_current()
                return records

    def _prepare_lock(self, root: int, acl: WindowsPrivateDirectoryAcl) -> None:
        try:
            windows_stat_at(root, _S_LOCK)
        except FileNotFoundError:
            try:
                windows_stat_at(root, _S_NAME)
            except FileNotFoundError:
                pass
            else:
                raise self._error(
                    "Windows Worker Supervisor lock is missing",
                    code="worker_supervisor_journal_corrupt",
                ) from None
        self._file_io.prepare_lock(root, acl)

    def _decode(self, raw: bytes | None) -> tuple[WorkerAttemptRecordV1, ...]:
        if raw is None:
            return ()
        if not raw or len(raw) > self._max_bytes() or (not raw.endswith(b"\n")):
            raise self._error(
                "Windows Worker Supervisor history is torn",
                code="worker_supervisor_journal_corrupt",
            )
        try:
            lines = raw.splitlines()
            if len(lines) > self._max_records():
                raise ValueError("Worker Supervisor history is over capacity")
            records = tuple(
                (
                    WorkerAttemptRecordV1.from_dict(
                        json.loads(line, object_pairs_hook=_reject_duplicate_keys)
                    )
                    for line in lines
                )
            )
            if raw != b"".join(
                (canonical_json_bytes(record.to_dict()) + b"\n" for record in records)
            ) or any(
                (
                    record.record_revision != index
                    for index, record in enumerate(records, start=1)
                )
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
        if not prefixed <= {_S_NAME, _S_LOCK}:
            raise self._error(
                "Windows Worker Supervisor Product root has foreign entries",
                code="worker_supervisor_journal_corrupt",
            )

    def _active(self) -> tuple[int, WindowsPrivateDirectoryAcl, BinaryIO]:
        root, acl, lock = (self._active_root, self._active_acl, self._active_lock)
        if root is None or acl is None or lock is None:
            raise RuntimeError("Windows Worker Supervisor lock is not held")
        return (root, acl, lock)

    def _require_lock_history(self, initialized: bool, raw: bytes | None) -> None:
        if initialized != (raw is not None):
            raise self._error(
                "Windows Worker Supervisor lock/history mismatch",
                code="worker_supervisor_journal_corrupt",
            )

    @staticmethod
    def _mark_lock_initialized(lock: BinaryIO) -> None:
        lock.seek(0)
        if lock.read(1) != b"\x00":
            raise ValueError("Windows Worker Supervisor lock state changed")
        lock.seek(0)
        if lock.write(b"\x01") != 1:
            raise OSError("Windows Worker Supervisor lock commit failed")
        lock.flush()
        windows_flush_file(lock.fileno())


class WindowsActivationStateJournal(Generic[_T]):
    """Append and reopen C5 CAS revisions under the original Windows root."""

    _max_bytes: Callable[[], int]
    _max_revisions: Callable[[], int]
    _max_head_bytes: Callable[[], int]
    _retained_type: type[_T]

    def __init__(self, path: Path, *, access: WindowsHistoryAccess) -> None:
        self._path = path
        self._access = access
        self._thread_lock = threading.Lock()
        self._file_io = WindowsJournalFileIO(
            name=_C_NAME,
            max_bytes=self._max_bytes(),
            lock_error=lambda: WorkerActivationStateJournalError(
                "worker_activation_state_corrupt"
            ),
            change_error=lambda: WorkerActivationStateJournalError(
                "worker_activation_state_corrupt"
            ),
            stream_error=lambda: WorkerActivationStateJournalError(
                "worker_activation_state_corrupt"
            ),
            lock_write_error="Windows C5 lock write made no progress",
            lock_commit_error="Windows C5 lock commit made no progress",
            append_error="Windows C5 append made no progress",
        )

    def load(self) -> Mapping[str, object] | None:
        """Read exact committed state without manufacturing a missing owner."""
        _present, records = self._read_records_with_presence()
        return None if not records else dict(records[-1].document)

    def load_with_presence_read_only(self) -> tuple[bool, Mapping[str, object] | None]:
        """Distinguish an absent owner from an uncommitted empty lock."""
        present, records = self._read_records_with_presence()
        return (present, None if not records else dict(records[-1].document))

    def retained_attempts_read_only(self) -> tuple[_T, ...]:
        """Inventory historical attempts without creating or pruning state."""
        _present, records = self._read_records_with_presence()
        return project_retained_attempts(records, record_type=self._retained_type)

    def records_with_presence_read_only(self) -> tuple[bool, tuple[_StateRecord, ...]]:
        """Expose the same validated read to guarded Product history capture."""
        return self._read_records_with_presence()

    def _read_records_with_presence(self) -> tuple[bool, tuple[_StateRecord, ...]]:
        with self._access.guard(), self._thread_lock:
            self._access.assert_current()
            with (
                WindowsPrivateDirectoryAcl() as acl,
                self._access.borrow_state_root() as root,
            ):
                self._require_root(root, acl)
                if not self._lock_exists(root):
                    self._require_no_state_entries(root)
                    self._require_root(root, acl)
                    self._access.assert_current()
                    return (False, ())
                with journal_file_lock_at(root, _C_LOCK, "shared") as lock:
                    initialized = self._file_io.validate_lock(
                        root, acl, locked_handle=lock
                    )
                    raw = self._file_io.read(root, acl)
                    records = self._decode_under_lock(
                        root, acl, initialized=initialized, raw=raw
                    )
                self._require_root(root, acl)
                self._access.assert_current()
                return (True, records)

    def compare_and_swap(
        self, *, expected_revision: int, document: Mapping[str, object]
    ) -> bool:
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("Windows C5 expected revision is invalid")
        record = _StateRecord.create(document)
        if record.journal_revision != expected_revision + 1:
            raise ValueError("Windows C5 revision must advance by one")
        line = _canonical_json_bytes(record.to_dict()) + b"\n"
        if len(line) > self._max_bytes():
            raise WorkerActivationStateJournalError("worker_activation_state_capacity")
        with self._access.guard(require_write=True), self._thread_lock:
            self._access.assert_current()
            with (
                WindowsPrivateDirectoryAcl() as acl,
                self._access.borrow_state_root() as root,
            ):
                self._require_root(root, acl)
                if expected_revision and (not self._lock_exists(root)):
                    self._require_no_state_entries(root)
                    self._require_root(root, acl)
                    self._access.assert_current()
                    return False
                self._prepare_lock(root, acl)
                with journal_file_lock_at(root, _C_LOCK, "exclusive") as lock:
                    initialized = self._file_io.validate_lock(
                        root, acl, locked_handle=lock
                    )
                    raw = self._file_io.read(root, acl)
                    records = self._decode_under_lock(
                        root, acl, initialized=initialized, raw=raw
                    )
                    current_revision = len(records)
                    if current_revision != expected_revision:
                        self._require_root(root, acl)
                        self._access.assert_current()
                        return False
                    if (
                        current_revision >= self._max_revisions()
                        or len(raw or b"") + len(line) > self._max_bytes()
                    ):
                        raise WorkerActivationStateJournalError(
                            "worker_activation_state_capacity"
                        )
                    try:
                        validate_activation_attempt_history((*records, record))
                    except ValueError as exc:
                        raise WorkerActivationStateJournalError(
                            "worker_activation_state_history_conflict"
                        ) from exc
                    if not initialized:
                        self._file_io.mark_initialized(lock)
                    committed_raw = self._append(root, acl, expected=raw, line=line)
                    self._publish_head(
                        root, acl, revision=record.journal_revision, raw=committed_raw
                    )
                self._require_root(root, acl)
                self._access.assert_current()
                return True

    def _require_root(self, root: int, acl: WindowsPrivateDirectoryAcl) -> None:
        if type(root) is not int or root < 0:
            raise WorkerActivationStateJournalError(
                "worker_activation_state_root_unsafe"
            )
        acl.validate(root)
        if not os.path.samestat(os.fstat(root), self._path.parent.lstat()):
            raise WorkerActivationStateJournalError(
                "worker_activation_state_root_changed"
            )
        names = windows_listdir_at(root)
        if any(
            (
                name.casefold().startswith(
                    ("worker-activation-state", ".worker-activation-state")
                )
                and name not in {_C_NAME, _C_LOCK}
                and (_HEAD.fullmatch(name) is None)
                for name in names
            )
        ):
            raise WorkerActivationStateJournalError("worker_activation_state_corrupt")

    @staticmethod
    def _require_no_state_entries(root: int) -> None:
        if any(
            (
                name.casefold().startswith(
                    ("worker-activation-state", ".worker-activation-state")
                )
                for name in windows_listdir_at(root)
            )
        ):
            raise WorkerActivationStateJournalError("worker_activation_state_corrupt")

    @staticmethod
    def _lock_exists(root: int) -> bool:
        try:
            windows_stat_at(root, _C_LOCK)
        except FileNotFoundError:
            return False
        return True

    def _prepare_lock(self, root: int, acl: WindowsPrivateDirectoryAcl) -> None:
        if not self._lock_exists(root):
            self._require_no_state_entries(root)
        self._file_io.prepare_lock(root, acl)

    def _decode_under_lock(
        self,
        root: int,
        acl: WindowsPrivateDirectoryAcl,
        *,
        initialized: bool,
        raw: bytes | None,
    ) -> tuple[_StateRecord, ...]:
        head_names = {
            name
            for name in windows_listdir_at(root)
            if _HEAD.fullmatch(name) is not None
        }
        if not initialized:
            if raw is not None or head_names:
                raise WorkerActivationStateJournalError(
                    "worker_activation_state_corrupt"
                )
            return ()
        if raw is None or not raw:
            raise WorkerActivationStateJournalError("worker_activation_state_corrupt")
        records = decode_activation_history(
            raw, max_revisions=self._max_revisions(), max_bytes=self._max_bytes()
        )
        if head_names != {_head_name(index) for index in range(1, len(records) + 1)}:
            raise WorkerActivationStateJournalError("worker_activation_state_corrupt")
        committed = sha256()
        byte_count = 0
        for index, line in enumerate(raw.splitlines(keepends=True), start=1):
            committed.update(line)
            byte_count += len(line)
            name = _head_name(index)
            descriptor = open_windows_regular_file_at(
                root, name, create_new=False, write=False, read_control=True
            )
            with os.fdopen(descriptor, "rb") as head:
                acl.validate(head.fileno())
                self._file_io.require_plain_stream(head.fileno())
                observed = head.read(self._max_head_bytes() + 1)
            expected = canonical_json_bytes(
                {
                    "byteCount": byte_count,
                    "digest": committed.hexdigest(),
                    "revision": index,
                    "version": 1,
                }
            )
            if observed != expected:
                raise WorkerActivationStateJournalError(
                    "worker_activation_state_corrupt"
                )
        return records

    def _append(
        self,
        root: int,
        acl: WindowsPrivateDirectoryAcl,
        *,
        expected: bytes | None,
        line: bytes,
    ) -> bytes:
        self._file_io.append(root, acl, expected=expected, line=line)
        return (expected or b"") + line

    def _publish_head(
        self, root: int, acl: WindowsPrivateDirectoryAcl, *, revision: int, raw: bytes
    ) -> None:
        name = _head_name(revision)
        descriptor = open_windows_regular_file_at(
            root,
            name,
            create_new=True,
            write=True,
            security_descriptor=acl.security_descriptor,
            read_control=True,
        )
        with os.fdopen(descriptor, "wb") as output:
            acl.validate(output.fileno())
            self._file_io.require_plain_stream(output.fileno())
            content = _head_bytes(revision, raw)
            if len(content) > self._max_head_bytes() or output.write(content) != len(
                content
            ):
                raise OSError("Windows C5 head write made no progress")
            output.flush()
            windows_flush_file(output.fileno())
        windows_flush_directory(root)
