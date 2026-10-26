"""Coding's physical Goal journal binding; logical semantics live in Records."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from loushang.harness.journal import (
    FunctionalJournalHeaderCodec,
    FunctionalJournalRecordCodec,
    JournalDurabilityProfile,
    JournalLoadPolicy,
    JsonlJournal,
)
from loushang.harness.journal._directory_lease import DirectoryWriterLease
from loushang.harness.journal._rooted_io import RootedFileIO
from loushang.harnesswork.goal import GoalError, GoalHeader, GoalRecord
from loushang.harnesswork.goal.contracts import (
    GOAL_LOCK_DIRECTORY,
    GOAL_WRITER_HASH_DOMAIN,
)
from loushang.harnesswork.goal.records import (
    decode_header,
    decode_record,
    encode_header,
    encode_record,
)


class _GoalWriter(DirectoryWriterLease):
    # Physical exclusion never varies by Product identity or Goal id.
    _lock_directory = GOAL_LOCK_DIRECTORY
    _hash_domain = GOAL_WRITER_HASH_DOMAIN


def goal_journal_path(session_dir: Path, session_id: str) -> Path:
    digest = hashlib.sha256(session_id.encode()).hexdigest()
    return session_dir / f"{digest}.goal.jsonl"


class GoalJournal:
    """Retain this owner before open; close even an unsuccessful admission."""

    def __init__(
        self, session_dir: Path, header: GoalHeader, *, read_only: bool = False
    ):
        self.header = header
        self.path = goal_journal_path(session_dir, header.session_id)
        self._read_only = read_only
        self._lease = _GoalWriter(
            session_dir, "coding-goal", header.scope_id, create_lock=not read_only
        )
        self._io: RootedFileIO | None = None

    def open(self, *, create: bool = False) -> None:
        if self._read_only or not create:
            try:
                self.path.lstat()
            except FileNotFoundError:
                raise GoalError("unknown Goal: Session has no Goal journal") from None
        self._lease.acquire()
        self._io = self._lease._borrow_root_io(
            root=self.path.parent,
            owner_id="coding-goal",
            authority_id=self.header.scope_id,
        )
        with self._journal() as journal:
            try:
                assert journal.bound_file is not None
                journal.bound_file.stat()
            except FileNotFoundError:
                if not create or self._read_only:
                    raise GoalError("unknown Goal journal") from None
                journal.rewrite((), header=self.header)
            loaded = journal.load()
            if loaded.header is None:
                raise GoalError("missing Goal header")
            self._check_header(loaded.header)

    @contextmanager
    def _journal(self) -> Iterator[JsonlJournal[GoalHeader, GoalRecord]]:
        self._lease.check_binding(
            owner_id="coding-goal", authority_id=self.header.scope_id
        )
        if self._io is None:
            raise GoalError("Goal store not open")
        with self._io.bind(self.path) as bound:
            yield JsonlJournal(
                self.path,
                bound_file=bound,
                record_codec=FunctionalJournalRecordCodec(encode_record, decode_record),
                header_codec=FunctionalJournalHeaderCodec(encode_header, decode_header),
                durability=JournalDurabilityProfile(
                    locking=False, flush=True, fsync=True
                ),
                load_policy=JournalLoadPolicy(header="required", partial_tail="raise"),
            )

    def _check_header(self, actual: GoalHeader) -> None:
        if (actual.scope_id, actual.session_id) != (
            self.header.scope_id,
            self.header.session_id,
        ):
            raise GoalError("Goal scope/Session mismatch")
        if not self._read_only and actual != self.header:
            raise GoalError("unsupported bound Goal policy")

    def load(self) -> tuple[GoalHeader, tuple[GoalRecord, ...]]:
        with self._journal() as journal:
            value = journal.load()
            if value.header is None:
                raise GoalError("missing Goal header")
            self._check_header(value.header)
            return value.header, value.records

    def append(self, expected_sequence: int, record: GoalRecord) -> int:
        if self._read_only:
            raise GoalError("Goal store is read only")
        with self._journal() as journal:
            current = journal.load()
            if current.header != self.header or expected_sequence != len(
                current.records
            ):
                raise GoalError("Goal store sequence or binding changed")
            if (
                record.sequence != expected_sequence + 1
                or record.scope_id != self.header.scope_id
            ):
                raise GoalError("Goal append sequence mismatch")
            journal.append(record)
        return record.sequence

    def close(self) -> None:
        if self._io is not None:
            self._io.cleanup()
        self._lease.close()
