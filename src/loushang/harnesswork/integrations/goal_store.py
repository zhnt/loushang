"""Optional JSONL Goal store using the existing Journal and retained root lease."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar

from loushang.harness.journal import (
    FunctionalJournalHeaderCodec,
    FunctionalJournalRecordCodec,
    JournalDurabilityProfile,
    JournalLoadPolicy,
    JsonlJournal,
)
from loushang.harness.journal.owned import (
    DirectoryWriterLease,
    RootedFileIO,
    borrow_root_io,
)
from loushang.harness.transcript.source_reader import TranscriptSourceReader
from loushang.harnesswork.cancellation_projection import project_work_cancellations
from loushang.harnesswork.event_log import EventLogEntry, JsonlEventLogBackend
from loushang.harnesswork.goal import GoalError, GoalHeader, GoalRecord
from loushang.harnesswork.goal.contracts import (
    GOAL_LOCK_DIRECTORY,
    GOAL_WRITER_HASH_DOMAIN,
)
from loushang.harnesswork.goal.records import (
    GoalHistory,
    decode_header,
    decode_record,
    encode_header,
    encode_record,
    replay,
)
from loushang.harnesswork.integrations.transcript import (
    WorkTranscriptSource,
    project_work_transcript,
    resolve_work_transcript,
)
from loushang.harnesswork.recording import project_work_recording
from loushang.harnesswork.run_projection import project_work_runs
from loushang.harnesswork.types import WorkRun


class _GoalWriter(DirectoryWriterLease):
    # Physical exclusion never varies by Product identity or Goal id.
    _lock_directory = GOAL_LOCK_DIRECTORY
    _hash_domain = GOAL_WRITER_HASH_DOMAIN


class JsonlGoalRecordStore:
    """Retain this owner before open; close even an unsuccessful admission."""

    def __init__(
        self, path: Path, header: GoalHeader, *, owner_id: str, read_only: bool = False
    ):
        self.header = header
        self.path = path
        self._owner_id = owner_id
        self._read_only = read_only
        self._lease = _GoalWriter(
            path.parent, owner_id, header.scope_id, create_lock=not read_only
        )
        self._io: RootedFileIO | None = None

    def open(self, *, create: bool = False) -> None:
        if self._read_only or not create:
            try:
                self.path.lstat()
            except FileNotFoundError:
                raise GoalError("unknown Goal: Session has no Goal journal") from None
        self._lease.acquire()
        self._io = borrow_root_io(
            self._lease,
            root=self.path.parent,
            owner_id=self._owner_id,
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
            owner_id=self._owner_id, authority_id=self.header.scope_id
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


_GoalSourceViewT = TypeVar("_GoalSourceViewT")
_GoalSourceStoreT = TypeVar("_GoalSourceStoreT", bound=JsonlGoalRecordStore)


def _goal_work_facts(
    history: GoalHistory,
    entries: Sequence[EventLogEntry],
    session_id: str,
) -> tuple[tuple[WorkRun, ...], bool]:
    """Use the same historical association checks for business and source reads."""
    runs = tuple(project_work_runs(entries, mark_incomplete_orphaned=True))
    by_operation = {run.operation_id: run for run in runs}
    cancellations = {r.run_id: r for r in project_work_cancellations(entries)}
    unresolved = False
    for batch in history.batches:
        found = by_operation.get(batch.operation_id)
        if batch.not_submitted:
            if found is not None:
                raise GoalError("not_submitted contradicts original Work")
            continue
        if found is None:
            unresolved = True
            continue
        if found.session_id != session_id or (
            batch.run_receipt and batch.run_receipt != found.run_id
        ):
            raise GoalError("Goal/Work association mismatch")
        observation = cancellations.get(found.run_id)
        if (
            found.status == "orphaned"
            or observation is None
            or observation.status
            not in {
                "not_requested",
                "settled",
            }
        ):
            unresolved = True
    return runs, unresolved


async def _read_cold_goal_work_sources(
    *,
    store: _GoalSourceStoreT,
    session_id: str,
    goal_id: str,
    reader: TranscriptSourceReader,
    supported_headers: Callable[[], Sequence[GoalHeader]],
    work_log_path: Callable[[], Path],
    selection_decoder: Callable[[], Callable[..., object]],
    binding_namespace: str,
    view_factory: Callable[..., _GoalSourceViewT],
    cleanup_error_factory: Callable[
        [_GoalSourceStoreT, BaseException | None, BaseException], BaseException
    ],
) -> tuple[_GoalSourceViewT, ...]:
    """Read historical sources and settle this store, borrowing the reader."""
    read_error: BaseException | None = None
    try:
        store.open()
        header, records = store.load()
        if header not in supported_headers():
            raise GoalError("unsupported Goal source policy")
        history = replay(header, records)
        history.goal(goal_id)
        log = JsonlEventLogBackend(work_log_path())
        entries = log.query()
        runs, _ = _goal_work_facts(history, entries, session_id)
        by_operation = {run.operation_id: run for run in runs}
        views = []
        for batch in history.batches:
            if batch.goal_id != goal_id:
                continue
            identity = (batch.id, batch.operation_id)
            if batch.not_submitted:
                views.append(view_factory(*identity, "not_submitted"))
                continue
            run = by_operation.get(batch.operation_id)
            if run is None:
                views.append(view_factory(*identity, "unresolved"))
                continue
            recording = project_work_recording(entries, run.run_id)
            if recording is None:
                raise GoalError("Goal Work recording disappeared")
            decode_selection = selection_decoder()

            selected = decode_selection(
                batch, run, [e for e in entries if e.operation_id == batch.operation_id]
            )
            handoffs = project_work_transcript(recording, entries)
            if selected is not None and handoffs is not None:
                raise GoalError(
                    "delegated child cannot declare a parent Transcript source"
                )
            if handoffs is None:
                views.append(view_factory(*identity, "not_declared", recording))
                continue
            if handoffs.binding_id != f"{binding_namespace}:{session_id}":
                raise GoalError("Goal source binding mismatch")
            source = await WorkTranscriptSource.bind(
                reader,
                binding_id=handoffs.binding_id,
                retained_until=handoffs.retained_until,
            )
            resolved = await resolve_work_transcript(recording, entries, source=source)
            views.append(
                view_factory(
                    *identity,
                    "complete" if resolved.handoffs.complete else "incomplete",
                    recording,
                    resolved,
                )
            )
        return tuple(views)
    except BaseException as error:
        read_error = error
        raise
    finally:
        try:
            store.close()
        except BaseException as cleanup_error:
            raise cleanup_error_factory(
                store, read_error, cleanup_error
            ) from cleanup_error
