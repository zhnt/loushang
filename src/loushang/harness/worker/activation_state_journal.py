"""Durable CAS state store for the C5 Product Worker activation coordinator.

The caller owns the Product root and supplies its fixed path. This store
persists the complete validated state at each revision; it never infers
process settlement or chooses an activation policy.
"""

from __future__ import annotations

import os
import stat
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

from loushang.foundation.json import dump_json_value
from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalLoadPolicy,
    append_jsonl_record,
    decode_jsonl,
)
from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO

from .product_activation import _validate_state

_MAX_JOURNAL_BYTES = 32 * 1024 * 1024
_MAX_REVISIONS = 4096
_LOCK_WAIT_SECONDS = 5.0
_LOCK_RETRY_SECONDS = 0.01
_RECORD_VERSION = 1
_FORMAT = replace(SORTED_UNICODE_JSONL_FORMAT, separators=(",", ":"))


def _canonical_json_bytes(value: object) -> bytes:
    return dump_json_value(
        value,
        name="worker_activation_record",
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class WorkerActivationStateJournalError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class _StateRecord:
    journal_revision: int
    document: dict[str, object]
    document_digest: str

    @classmethod
    def create(cls, document: Mapping[str, object]) -> _StateRecord:
        validated = _validate_state(dict(document))
        revision = validated["stateRevision"]
        assert type(revision) is int
        return cls(
            journal_revision=revision,
            document=validated,
            document_digest=sha256(_canonical_json_bytes(validated)).hexdigest(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "document": self.document,
            "documentDigest": self.document_digest,
            "journalRevision": self.journal_revision,
            "recordVersion": _RECORD_VERSION,
        }

    @classmethod
    def from_dict(cls, value: object) -> _StateRecord:
        if type(value) is not dict or set(value) != {
            "document",
            "documentDigest",
            "journalRevision",
            "recordVersion",
        }:
            raise ValueError("Worker activation state record fields are invalid")
        if value["recordVersion"] != _RECORD_VERSION:
            raise ValueError("Worker activation state record version is invalid")
        document = _validate_state(value["document"])
        revision = value["journalRevision"]
        digest = value["documentDigest"]
        if (
            type(revision) is not int
            or revision < 1
            or document["stateRevision"] != revision
            or type(digest) is not str
            or digest != sha256(_canonical_json_bytes(value["document"])).hexdigest()
        ):
            raise ValueError("Worker activation state record changed")
        return cls(revision, document, digest)


def _decode_record(value: object) -> _StateRecord:
    try:
        return _StateRecord.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Worker activation state record is invalid",
            code="invalid_worker_activation_state_record",
        ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=_StateRecord.to_dict,
    decoder=_decode_record,
)


class WorkerActivationStateJournal:
    """One private append-only state history with cross-process revision CAS."""

    def __init__(self, path: Path) -> None:
        if (
            not isinstance(path, Path)
            or not path.is_absolute()
            or path.name != ("worker-activation-state.jsonl")
        ):
            raise ValueError("Worker activation state path is invalid")
        self._path = path
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="raise", create_lock=False)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> Mapping[str, object] | None:
        with self._bound_journal() as rooted:
            _, records = self._load(rooted)
            return None if not records else dict(records[-1].document)

    def load_read_only(self) -> Mapping[str, object] | None:
        """Read validated state without creating a lock or repairing history."""

        with self._bound_journal_read_only() as rooted:
            _, records = self._load(rooted)
            return None if not records else dict(records[-1].document)

    def compare_and_swap(
        self, *, expected_revision: int, document: Mapping[str, object]
    ) -> bool:
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("Worker activation expected revision is invalid")
        record = _StateRecord.create(document)
        if record.journal_revision != expected_revision + 1:
            raise ValueError("Worker activation state revision must advance by one")
        line = _canonical_json_bytes(record.to_dict()) + b"\n"
        with self._bound_journal() as rooted:
            raw, records = self._load(rooted)
            current_revision = 0 if not records else records[-1].journal_revision
            if current_revision != expected_revision:
                return False
            if (
                len(records) >= _MAX_REVISIONS
                or len(raw) + len(line) > _MAX_JOURNAL_BYTES
            ):
                raise WorkerActivationStateJournalError(
                    "worker_activation_state_capacity"
                )
            append_jsonl_record(
                self._path,
                record,
                record_codec=_CODEC,
                format_profile=_FORMAT,
                durability=self._durability,
                bound_file=rooted,
            )
            return True

    @contextmanager
    def _bound_journal(self) -> Iterator[RootedFile]:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        deadline = time.monotonic() + _LOCK_WAIT_SECONDS
        while True:
            try:
                parent_fd = os.open(self._path.parent, flags)
            except OSError as exc:
                raise WorkerActivationStateJournalError(
                    "worker_activation_state_root_unsafe"
                ) from exc
            acquired = False
            busy_error: BlockingIOError | None = None
            try:
                opened = os.fstat(parent_fd)
                visible = self._path.parent.lstat()
                if (
                    not stat.S_ISDIR(opened.st_mode)
                    or opened.st_uid != os.geteuid()
                    or stat.S_IMODE(opened.st_mode) & 0o077
                    or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
                ):
                    raise WorkerActivationStateJournalError(
                        "worker_activation_state_root_unsafe"
                    )
                file_io = RootedFileIO(self._path.parent, parent_fd)
                try:
                    with file_io.bind(self._path, durable=True) as rooted:
                        try:
                            rooted.acquire_lock(exclusive=True, suffix=".lock")
                        except BlockingIOError as exc:
                            busy_error = exc
                        else:
                            acquired = True
                            yield rooted
                finally:
                    file_io.cleanup()
                after = self._path.parent.lstat()
                if (opened.st_dev, opened.st_ino) != (after.st_dev, after.st_ino):
                    raise WorkerActivationStateJournalError(
                        "worker_activation_state_root_changed"
                    )
            finally:
                os.close(parent_fd)
            if acquired:
                return
            if time.monotonic() >= deadline:
                raise WorkerActivationStateJournalError(
                    "worker_activation_state_busy"
                ) from busy_error
            # Rooted operations and descriptors are gone before retrying.
            time.sleep(_LOCK_RETRY_SECONDS)

    @contextmanager
    def _bound_journal_read_only(self) -> Iterator[RootedFile]:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            parent_fd = os.open(self._path.parent, flags)
        except OSError as exc:
            raise WorkerActivationStateJournalError(
                "worker_activation_state_root_unsafe"
            ) from exc
        try:
            opened = os.fstat(parent_fd)
            visible = self._path.parent.lstat()
            if (
                not stat.S_ISDIR(opened.st_mode)
                or opened.st_uid != os.geteuid()
                or stat.S_IMODE(opened.st_mode) & 0o077
                or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
            ):
                raise WorkerActivationStateJournalError(
                    "worker_activation_state_root_unsafe"
                )
            file_io = RootedFileIO(self._path.parent, parent_fd)
            try:
                with file_io.bind(self._path, durable=True) as rooted:
                    try:
                        rooted.stat()
                    except FileNotFoundError:
                        try:
                            rooted.sibling(self._path.name + ".lock").stat()
                        except FileNotFoundError:
                            pass
                        else:
                            raise WorkerActivationStateJournalError(
                                "worker_activation_state_orphan_lock"
                            ) from None
                    else:
                        try:
                            rooted.acquire_lock(
                                exclusive=False, suffix=".lock", create=False
                            )
                        except FileNotFoundError as exc:
                            raise WorkerActivationStateJournalError(
                                "worker_activation_state_lock_missing"
                            ) from exc
                        except BlockingIOError as exc:
                            raise WorkerActivationStateJournalError(
                                "worker_activation_state_busy"
                            ) from exc
                    yield rooted
            finally:
                file_io.cleanup()
            after = self._path.parent.lstat()
            if (opened.st_dev, opened.st_ino) != (after.st_dev, after.st_ino):
                raise WorkerActivationStateJournalError(
                    "worker_activation_state_root_changed"
                )
        finally:
            os.close(parent_fd)

    def _load(self, rooted: RootedFile) -> tuple[bytes, tuple[_StateRecord, ...]]:
        try:
            raw = rooted.read_bytes(max_bytes=_MAX_JOURNAL_BYTES)
        except FileNotFoundError:
            return b"", ()
        try:
            records: tuple[_StateRecord, ...] = decode_jsonl(
                raw.decode("utf-8"),
                target=self._path,
                record_codec=_CODEC,
                load_policy=self._load_policy,
            ).records
            if (
                len(records) > _MAX_REVISIONS
                or len(raw.splitlines(keepends=True)) != len(records)
                or any(
                    record.journal_revision != ordinal
                    or line != _canonical_json_bytes(record.to_dict()) + b"\n"
                    for ordinal, (record, line) in enumerate(
                        zip(records, raw.splitlines(keepends=True), strict=True), 1
                    )
                )
            ):
                raise ValueError("Worker activation state history changed")
            return raw, records
        except (JournalCodecError, UnicodeError, ValueError) as exc:
            raise WorkerActivationStateJournalError(
                "worker_activation_state_corrupt"
            ) from exc


__all__ = ["WorkerActivationStateJournal", "WorkerActivationStateJournalError"]
