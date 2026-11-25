"""Optional JSONL Goal store using the existing Journal and retained root lease."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from os import stat_result
from pathlib import Path
from typing import Literal, TypeVar

from loushang.harness.journal import (
    FunctionalJournalHeaderCodec,
    FunctionalJournalRecordCodec,
    JournalDurabilityProfile,
    JournalLoadPolicy,
    JsonlJournal,
    decode_jsonl,
)
from loushang.harness.journal.owned import (
    DirectoryWriterLease,
    RootedFileIO,
    borrow_root_io,
)
from loushang.harness.transcript.jsonl_file import _read_stable_regular_file
from loushang.harness.transcript.session_catalog import (
    session_file_authority_fingerprint,
)
from loushang.harness.transcript.source_reader import TranscriptSourceReader
from loushang.harnesswork.cancellation_projection import project_work_cancellations
from loushang.harnesswork.event_log import (
    EventLogEntry,
    JsonlEventLogBackend,
    decode_detached_work_events,
)
from loushang.harnesswork.goal import GoalError, GoalHeader, GoalRecord
from loushang.harnesswork.goal.contracts import (
    GOAL_LOCK_DIRECTORY,
    GOAL_WRITER_HASH_DOMAIN,
)
from loushang.harnesswork.goal.records import (
    GoalHistory,
    GoalState,
    decode_header,
    decode_record,
    encode_header,
    encode_record,
    replay,
)
from loushang.harnesswork.goal.tasks import TASK_POLICY
from loushang.harnesswork.integrations.transcript import (
    WorkTranscriptSource,
    project_work_transcript,
    resolve_work_transcript,
)
from loushang.harnesswork.recording import _RecordingObserver, project_work_recording
from loushang.harnesswork.run_projection import project_work_runs
from loushang.harnesswork.types import WorkRun


class _GoalWriter(DirectoryWriterLease):
    # Physical exclusion never varies by Product identity or Goal id.
    _lock_directory = GOAL_LOCK_DIRECTORY
    _hash_domain = GOAL_WRITER_HASH_DOMAIN


_HEADER_CODEC = FunctionalJournalHeaderCodec(encode_header, decode_header)
_RECORD_CODEC = FunctionalJournalRecordCodec(encode_record, decode_record)


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
                record_codec=_RECORD_CODEC,
                header_codec=_HEADER_CODEC,
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

    def decode_detached(self, raw: str) -> GoalHistory:
        """Replay an authorized stable read without acquiring a Writer lease."""
        if not self._read_only:
            raise GoalError("detached Goal reads require read-only authority")
        snapshot = decode_jsonl(
            raw, target=self.path, record_codec=_RECORD_CODEC, header_codec=_HEADER_CODEC,
            load_policy=JournalLoadPolicy(header="required", collect_duplicate_keys=True),
        )
        snapshot.require_unique_keys("duplicate Goal journal fields")
        if snapshot.header is None:
            raise GoalError("missing Goal header")
        self._check_header(snapshot.header)
        return replay(snapshot.header, snapshot.records)

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
_GoalRecoveryT = TypeVar("_GoalRecoveryT")


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


@dataclass(frozen=True, slots=True)
class DetachedGoalWorkFacts:
    goal: GoalState
    batch_count: int
    run_counts: Counter[str]
    execution_unresolved: bool


def _recovery_fingerprint(path: Path) -> str | None:
    try:
        return session_file_authority_fingerprint(path)
    except FileNotFoundError:
        return None


def _read_recovery_journal(path: Path, stamp: str, *, max_bytes: int) -> str:
    return _read_stable_regular_file(
        path, max_bytes=max_bytes, expected_source_fingerprint=stamp,
    ).decode()


def _recovery_sources_current(
    directory: Path, root: stat_result, *inputs: tuple[Path, str | None],
) -> bool:
    try:
        current = directory.lstat()
        return (
            (root.st_dev, root.st_ino) == (current.st_dev, current.st_ino)
            and all(_recovery_fingerprint(path) == stamp for path, stamp in inputs)
        )
    except OSError:
        return False


def _project_recovered_goal_work(
    history: GoalHistory, session_id: str, entries: Sequence[EventLogEntry],
) -> DetachedGoalWorkFacts:
    if any(entry.session_id != session_id for entry in entries):
        raise GoalError("Work belongs to a different Session")
    runs, unresolved = _goal_work_facts(history, entries, session_id)
    attempted = {batch.operation_id for batch in history.batches if not batch.not_submitted}
    matched = tuple(run for run in runs if run.operation_id in attempted)
    recordings = _RecordingObserver(entries)
    for run in matched:
        if recordings.get(run.run_id) is None:
            raise GoalError("missing associated Work recording")
    goal, = history.goals.values()
    return DetachedGoalWorkFacts(
        goal=goal,
        batch_count=len(history.batches),
        run_counts=Counter(run.status for run in matched),
        execution_unresolved=unresolved or any(
            command.outcome == "pending" for command in history.commands.values()
        ),
    )


def observe_detached_goal_work(
    directory: Path,
    session_id: str,
    *,
    path_for: Callable[[Path, str], Path],
    owner_id: str,
    max_bytes: int,
    project: Callable[[DetachedGoalWorkFacts], _GoalRecoveryT],
) -> _GoalRecoveryT | Literal[
    "source_changed", "goal_journal_invalid", "unsupported_goal", "no_goal",
    "ambiguous_goal", "work_log_invalid",
]:
    """Observe the original interactive Goal and associated Work without opening a Writer."""
    try:
        if not directory.is_absolute() or directory.resolve(strict=True) != directory or not directory.is_dir():
            return "source_changed"
        root = directory.stat()
    except (OSError, RuntimeError):
        return "source_changed"

    path = path_for(directory, session_id)
    try:
        stamp = _recovery_fingerprint(path)
        header = GoalHeader(session_id, session_id, TASK_POLICY)
        history = None
        if stamp is not None:
            journal = JsonlGoalRecordStore(path, header, owner_id=owner_id, read_only=True)
            history = journal.decode_detached(_read_recovery_journal(path, stamp, max_bytes=max_bytes))
    except (OSError, ValueError, RuntimeError):
        return "goal_journal_invalid"

    if not _recovery_sources_current(directory, root, (path, stamp)):
        return "source_changed"
    if history is not None and history.header != header:
        return "unsupported_goal"
    if history is None or not history.goals:
        return "no_goal"
    if len(history.goals) != 1:
        return "ambiguous_goal"

    work_path = path.with_suffix(".work.jsonl")
    try:
        work_stamp = _recovery_fingerprint(work_path)
        entries = () if work_stamp is None else decode_detached_work_events(
            _read_recovery_journal(work_path, work_stamp, max_bytes=max_bytes), work_path,
        )
        result = project(_project_recovered_goal_work(history, session_id, entries))
    except (OSError, ValueError, RuntimeError):
        return "work_log_invalid"
    if not _recovery_sources_current(directory, root, (path, stamp), (work_path, work_stamp)):
        return "source_changed"
    return result


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
