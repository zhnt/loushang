"""Pinned Windows Product custody for one durable C5 activation-state stream.

Each appended revision gets an immutable committed-byte head. A complete JSONL
line without its head remains debt after an interrupted commit; replay never
interprets that line as a previous, safely absent Worker effect.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Mapping
from hashlib import sha256
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
from loushang.harness.worker.activation_state_journal import (
    _MAX_JOURNAL_BYTES as _MAX_BYTES,
)
from loushang.harness.worker.activation_state_journal import (
    _MAX_REVISIONS,
    WorkerActivationStateJournalError,
    _canonical_json_bytes,
    _StateRecord,
)

from .package_product_worker_activation_history import (
    decode_coding_worker_activation_history,
    validate_coding_worker_activation_attempt_history,
)

_NAME = "worker-activation-state.jsonl"
_LOCK = _NAME + ".lock"
_HEAD = re.compile(r"worker-activation-state\.h[0-9]{8}\.json\Z")
_MAX_HEAD_BYTES = 256


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


class CodingWindowsWorkerActivationStateJournal:
    """Append and reopen C5 CAS revisions under the original Windows root."""

    def __init__(self, product: WindowsLocalWheelProductSessionOwner) -> None:
        if (
            os.name != "nt"
            or type(product) is not WindowsLocalWheelProductSessionOwner
            or product.policy.product_id != "coding"
        ):
            raise ValueError("Windows C5 state requires its Coding Product owner")
        product.assert_root_gc_authority_current()
        self._product = product
        self._path = product.state_root / _NAME
        self._thread_lock = threading.Lock()

    def load(self) -> Mapping[str, object] | None:
        """Read exact committed state without manufacturing a missing owner."""

        with self._product.gc_gate.guard(), self._thread_lock:
            self._product.assert_root_gc_authority_current()
            with (
                WindowsPrivateDirectoryAcl() as acl,
                self._product.epoch_runtime.borrow_product_state_root_descriptor() as root,
            ):
                self._require_root(root, acl)
                if not self._lock_exists(root):
                    self._require_no_state_entries(root)
                    self._require_root(root, acl)
                    self._product.assert_root_gc_authority_current()
                    return None
                with journal_file_lock_at(root, _LOCK, "shared") as lock:
                    initialized = self._validate_lock(root, acl, lock)
                    raw = self._read_raw(root, acl)
                    records = self._decode_under_lock(
                        root, acl, initialized=initialized, raw=raw
                    )
                self._require_root(root, acl)
                self._product.assert_root_gc_authority_current()
                return None if not records else dict(records[-1].document)

    def compare_and_swap(
        self, *, expected_revision: int, document: Mapping[str, object]
    ) -> bool:
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("Windows C5 expected revision is invalid")
        record = _StateRecord.create(document)
        if record.journal_revision != expected_revision + 1:
            raise ValueError("Windows C5 revision must advance by one")
        line = _canonical_json_bytes(record.to_dict()) + b"\n"
        if len(line) > _MAX_BYTES:
            raise WorkerActivationStateJournalError("worker_activation_state_capacity")
        with self._product.gc_gate.guard(require_write=True), self._thread_lock:
            self._product.assert_root_gc_authority_current()
            with (
                WindowsPrivateDirectoryAcl() as acl,
                self._product.epoch_runtime.borrow_product_state_root_descriptor() as root,
            ):
                self._require_root(root, acl)
                self._prepare_lock(root, acl)
                with journal_file_lock_at(root, _LOCK, "exclusive") as lock:
                    initialized = self._validate_lock(root, acl, lock)
                    raw = self._read_raw(root, acl)
                    records = self._decode_under_lock(
                        root, acl, initialized=initialized, raw=raw
                    )
                    current_revision = len(records)
                    if current_revision != expected_revision:
                        self._require_root(root, acl)
                        self._product.assert_root_gc_authority_current()
                        return False
                    if (
                        current_revision >= _MAX_REVISIONS
                        or len(raw or b"") + len(line) > _MAX_BYTES
                    ):
                        raise WorkerActivationStateJournalError(
                            "worker_activation_state_capacity"
                        )
                    try:
                        validate_coding_worker_activation_attempt_history(
                            (*records, record)
                        )
                    except ValueError as exc:
                        raise WorkerActivationStateJournalError(
                            "worker_activation_state_history_conflict"
                        ) from exc
                    if not initialized:
                        self._mark_lock_initialized(lock)
                    committed_raw = self._append(root, acl, expected=raw, line=line)
                    self._publish_head(
                        root,
                        acl,
                        revision=record.journal_revision,
                        raw=committed_raw,
                    )
                self._require_root(root, acl)
                self._product.assert_root_gc_authority_current()
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
            name.casefold().startswith(
                ("worker-activation-state", ".worker-activation-state")
            )
            and name not in {_NAME, _LOCK}
            and _HEAD.fullmatch(name) is None
            for name in names
        ):
            raise WorkerActivationStateJournalError("worker_activation_state_corrupt")

    @staticmethod
    def _require_no_state_entries(root: int) -> None:
        if any(
            name.casefold().startswith(
                ("worker-activation-state", ".worker-activation-state")
            )
            for name in windows_listdir_at(root)
        ):
            raise WorkerActivationStateJournalError("worker_activation_state_corrupt")

    @staticmethod
    def _lock_exists(root: int) -> bool:
        try:
            windows_stat_at(root, _LOCK)
        except FileNotFoundError:
            return False
        return True

    def _prepare_lock(self, root: int, acl: WindowsPrivateDirectoryAcl) -> None:
        if not self._lock_exists(root):
            self._require_no_state_entries(root)
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
                    raise OSError("Windows C5 lock write made no progress")
                windows_flush_file(descriptor)
            elif os.fstat(descriptor).st_size != 1:
                raise WorkerActivationStateJournalError(
                    "worker_activation_state_corrupt"
                )
        finally:
            os.close(descriptor)
        if created:
            windows_flush_directory(root)

    def _validate_lock(
        self,
        root: int,
        acl: WindowsPrivateDirectoryAcl,
        lock: BinaryIO,
    ) -> bool:
        acl.validate(lock.fileno())
        self._require_plain_stream(lock.fileno())
        opened = os.fstat(lock.fileno())
        visible = windows_stat_at(root, _LOCK)
        if opened.st_size != 1 or (opened.st_dev, opened.st_ino) != (
            visible.st_dev,
            visible.st_ino,
        ):
            raise WorkerActivationStateJournalError("worker_activation_state_corrupt")
        lock.seek(0)
        marker = lock.read(1)
        if marker not in {b"\0", b"\1"}:
            raise WorkerActivationStateJournalError("worker_activation_state_corrupt")
        return marker == b"\1"

    @staticmethod
    def _mark_lock_initialized(lock: BinaryIO) -> None:
        lock.seek(0)
        if lock.read(1) != b"\0":
            raise WorkerActivationStateJournalError("worker_activation_state_corrupt")
        lock.seek(0)
        if lock.write(b"\1") != 1:
            raise OSError("Windows C5 lock commit made no progress")
        lock.flush()
        windows_flush_file(lock.fileno())

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
        records = decode_coding_worker_activation_history(
            raw, max_revisions=_MAX_REVISIONS, max_bytes=_MAX_BYTES
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
                self._require_plain_stream(head.fileno())
                observed = head.read(_MAX_HEAD_BYTES + 1)
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
                raise WorkerActivationStateJournalError(
                    "worker_activation_state_corrupt"
                )
            output.seek(0, os.SEEK_END)
            remaining = memoryview(line)
            while remaining:
                written = output.write(remaining)
                if written is None or written <= 0:
                    raise OSError("Windows C5 append made no progress")
                remaining = remaining[written:]
            output.flush()
            windows_flush_file(output.fileno())
        if created:
            windows_flush_directory(root)
        return (expected or b"") + line

    def _publish_head(
        self,
        root: int,
        acl: WindowsPrivateDirectoryAcl,
        *,
        revision: int,
        raw: bytes,
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
            self._require_plain_stream(output.fileno())
            content = _head_bytes(revision, raw)
            if len(content) > _MAX_HEAD_BYTES or output.write(content) != len(content):
                raise OSError("Windows C5 head write made no progress")
            output.flush()
            windows_flush_file(output.fileno())
        windows_flush_directory(root)

    @staticmethod
    def _require_plain_stream(descriptor: int) -> None:
        if windows_regular_file_stream_names(descriptor) != ("::$DATA",):
            raise WorkerActivationStateJournalError("worker_activation_state_corrupt")


__all__ = ["CodingWindowsWorkerActivationStateJournal"]
