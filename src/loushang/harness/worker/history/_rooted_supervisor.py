"""Rooted Supervisor storage over the original Worker state engine and journals.

The caller's access adapter owns Product/GC authority. This adapter owns only
the original operation-scoped locks, rooted files and retained-history hooks.
"""

from __future__ import annotations

import json
import os
import stat
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from dataclasses import replace
from pathlib import Path
from typing import Protocol, cast

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    JournalCodecError,
    JournalLoadPolicy,
    append_jsonl_record,
    decode_jsonl,
)
from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO

from .._segmented_history import (
    CodingWorkerHistorySegmentError,
    CodingWorkerSegmentedHistoryV1,
    append_coding_worker_active_record,
    initialize_coding_worker_active_head,
    read_coding_worker_segmented_history,
)
from ..contracts import WorkerLaunchIdentityV1
from ..journal import (
    WORKER_ATTEMPT_JOURNAL_CODEC,
    WorkerAttemptRecordV1,
    WorkerSupervisorJournal,
    _validate_history,
)
from ._checkpoint import _CheckpointMethods
from ._read_v2 import RetainedHistoryReader
from ._supervisor import _MAX_BYTES, _MAX_RECORDS, _SupervisorReplayFields
from ._v2_names import PRODUCT_OWNER_INDEX_NAME

_STEM = "worker-supervisor"
_DIR_FLAGS = (
    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    if os.name == "posix"
    else -1
)


class WorkerHistoryAccess(Protocol):
    @property
    def scope_id(self) -> str: ...
    @property
    def store_id(self) -> str: ...
    def guard(self, *, require_write: bool) -> AbstractContextManager[object]: ...
    def assert_current(self) -> None: ...


class RootedSupervisorJournal(WorkerSupervisorJournal):
    """Keep Supervisor epochs and attempt IDs across immutable generations.

    The original Worker Journal owns transitions. This adapter supplies rooted
    storage under the caller's existing custody; it neither retires generations
    nor treats a torn tail as a successful transition.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        access: WorkerHistoryAccess,
        history_reader: RetainedHistoryReader,
    ) -> None:
        super().__init__(path)
        self._access = access
        self._history_reader = history_reader
        self._thread_lock = threading.Lock()
        self._active_rooted: RootedFile | None = None
        self._active_history: CodingWorkerSegmentedHistoryV1 | None = None
        self._active_replay: _SupervisorReplayFields | None = None
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._strict_load = JournalLoadPolicy(partial_tail="raise", create_lock=False)
        self._read_only: ContextVar[bool] = ContextVar(
            "coding_worker_supervisor_read_only", default=False
        )

    @contextmanager
    def _reading(self) -> Iterator[None]:
        token = self._read_only.set(True)
        try:
            yield
        finally:
            self._read_only.reset(token)

    def status(self, attempt_id: str) -> WorkerAttemptRecordV1 | None:
        with self._reading():
            return super().status(attempt_id)

    def next_supervisor_epoch(self, identity: WorkerLaunchIdentityV1) -> int:
        with self._reading():
            return super().next_supervisor_epoch(identity)

    def incomplete(self) -> tuple[WorkerAttemptRecordV1, ...]:
        with self._reading():
            return super().incomplete()

    def attempts(self) -> tuple[WorkerAttemptRecordV1, ...]:
        """Read every retained attempt's latest record without creating state."""

        with self._reading(), self._exclusive():
            latest: dict[str, WorkerAttemptRecordV1] = {}
            for record in self._load_unlocked():
                latest[record.attempt_id] = record
            return tuple(
                sorted(latest.values(), key=lambda record: record.record_revision)
            )

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        with (
            self._access.guard(require_write=not self._read_only.get()),
            self._thread_lock,
        ):
            self._access.assert_current()
            root_fd = os.open(self.path.parent, _DIR_FLAGS)
            try:
                opened = os.fstat(root_fd)
                visible = self.path.parent.lstat()
                if (
                    not stat.S_ISDIR(opened.st_mode)
                    or opened.st_uid != os.geteuid()
                    or stat.S_IMODE(opened.st_mode) & 0o077
                    or (opened.st_dev, opened.st_ino)
                    != (visible.st_dev, visible.st_ino)
                ):
                    raise self._error(
                        "Worker Supervisor Product root is unsafe",
                        code="worker_supervisor_journal_corrupt",
                    )
                with RootedFileIO(self.path.parent, root_fd) as io:
                    with io.bind(self.path, durable=True) as rooted:
                        history_present = self._exists(rooted) or self._exists(
                            rooted.sibling(f"{_STEM}.segments.json")
                        )
                        lock_present = self._exists(
                            rooted.sibling(f"{_STEM}.jsonl.lock")
                        )
                        if (
                            self._exists(rooted.sibling(PRODUCT_OWNER_INDEX_NAME))
                            and not lock_present
                        ):
                            raise self._error(
                                "Worker Supervisor V2 lock is missing",
                                code="worker_supervisor_journal_corrupt",
                            )
                        if history_present != lock_present:
                            raise self._error(
                                "Worker Supervisor lock and history disagree",
                                code="worker_supervisor_journal_corrupt",
                            )
                        if lock_present or not self._read_only.get():
                            created = rooted.acquire_lock(
                                exclusive=True,
                                suffix=".lock",
                                create=not lock_present,
                                initialize_empty_target_if_new=not lock_present,
                            )
                            if created:
                                initialize_coding_worker_active_head(
                                    rooted, stem=_STEM, stream_id=_STEM
                                )
                        self._active_rooted = rooted
                        try:
                            yield
                            self._access.assert_current()
                        finally:
                            self._active_rooted = None
                            self._active_history = None
                            self._active_replay = None
                after = self.path.parent.lstat()
                if (opened.st_dev, opened.st_ino) != (after.st_dev, after.st_ino):
                    raise self._error(
                        "Worker Supervisor Product root changed",
                        code="worker_supervisor_journal_corrupt",
                    )
            finally:
                os.close(root_fd)

    def _load_unlocked(self) -> tuple[WorkerAttemptRecordV1, ...]:
        rooted = self._require_bound()
        if self._exists(rooted.sibling(PRODUCT_OWNER_INDEX_NAME)):
            history, replay = self._load_v2_state(rooted)
            self._active_history = history
            self._active_replay = replay
            return replay.current_attempts
        try:
            self._active_replay = None
            history = read_coding_worker_segmented_history(
                rooted,
                stem=_STEM,
                stream_id=_STEM,
                max_segment_bytes=self._max_history_bytes(),
            )
            records: list[WorkerAttemptRecordV1] = []
            for generation, raw in enumerate(history.segments):
                segment = decode_jsonl(
                    raw.decode("utf-8"),
                    target=self.path,
                    record_codec=WORKER_ATTEMPT_JOURNAL_CODEC,
                    load_policy=self._strict_load,
                ).records
                lines = raw.splitlines(keepends=True)
                if (
                    len(segment) > self._max_history_records()
                    or len(segment) != len(lines)
                    or any(
                        record.record_revision != revision
                        or line
                        != json.dumps(
                            record.to_dict(), ensure_ascii=False, sort_keys=True
                        ).encode("utf-8")
                        + b"\n"
                        for revision, (record, line) in enumerate(
                            zip(segment, lines, strict=True), len(records) + 1
                        )
                    )
                ):
                    raise ValueError("Worker Supervisor segment changed")
                records.extend(segment)
                if (
                    history.manifest is not None
                    and generation < history.active_generation
                    and len(records)
                    != history.manifest.sealed[generation].last_revision
                ):
                    raise ValueError("Worker Supervisor sealed revision changed")
            result = tuple(records)
            _validate_history(result)
            self._active_history = history
            return result
        except (
            CodingWorkerHistorySegmentError,
            JournalCodecError,
            OSError,
            RecursionError,
            TypeError,
            UnicodeError,
            ValueError,
        ) as exc:
            raise self._error(
                "Worker Supervisor segmented history is corrupt",
                code="worker_supervisor_journal_corrupt",
            ) from exc

    def _load_v2_state(
        self, rooted: RootedFile
    ) -> tuple[CodingWorkerSegmentedHistoryV1, _SupervisorReplayFields]:
        try:
            owner = (
                self._history_reader.preparation.prepared_type._index_type.from_bytes(
                    rooted.sibling(PRODUCT_OWNER_INDEX_NAME).read_bytes(max_bytes=4096)
                )
            )
            if (
                owner.scope_id != self._access.scope_id
                or owner.store_id != self._access.store_id
            ):
                raise self._error(
                    "Worker Supervisor V2 owner changed",
                    code="worker_supervisor_journal_corrupt",
                )
            retained = self._history_reader.read(rooted, stem=_STEM)
            replay = retained.replay
            if not isinstance(
                replay,
                self._history_reader.preparation.prepared_type._supervisor_type._replay_type,
            ):
                raise self._error(
                    "Worker Supervisor V2 replay changed",
                    code="worker_supervisor_journal_corrupt",
                )
            return (
                self._history_reader.history_from_retained(
                    rooted,
                    retained,
                    stem=_STEM,
                    manifest_changed=lambda: self._error(
                        "Worker Supervisor V2 manifest changed",
                        code="worker_supervisor_journal_corrupt",
                    ),
                ),
                cast(_SupervisorReplayFields, replay),
            )
        except (
            self._history_reader.error_type,
            CodingWorkerHistorySegmentError,
            OSError,
            ValueError,
        ) as exc:
            raise self._error(
                "Worker Supervisor V2 history is corrupt",
                code="worker_supervisor_journal_corrupt",
            ) from exc

    def _last_revision_unlocked(
        self, records: tuple[WorkerAttemptRecordV1, ...]
    ) -> int:
        return (
            super()._last_revision_unlocked(records)
            if self._active_replay is None
            else self._active_replay.last_revision
        )

    def _latest_for_key_unlocked(
        self, records: tuple[WorkerAttemptRecordV1, ...], key: str
    ) -> WorkerAttemptRecordV1 | None:
        if self._active_replay is None:
            return super()._latest_for_key_unlocked(records, key)
        return next(
            (
                item.last_record
                for item in self._active_replay.key_states
                if item.supervisor_key == key
            ),
            None,
        )

    def _claims_since_stop_unlocked(
        self, records: tuple[WorkerAttemptRecordV1, ...], key: str
    ) -> int:
        if self._active_replay is None:
            return super()._claims_since_stop_unlocked(records, key)
        return next(
            (
                item.claims_since_stop
                for item in self._active_replay.key_states
                if item.supervisor_key == key
            ),
            0,
        )

    def _attempt_retired_unlocked(self, attempt_id: str) -> bool:
        return (
            self._active_replay is not None
            and attempt_id in self._active_replay.retired_attempt_ids
        )

    def _append_unlocked(self, record: WorkerAttemptRecordV1) -> None:
        if type(record) is not WorkerAttemptRecordV1:
            raise TypeError("Worker Supervisor requires an exact record")
        rooted = self._require_bound()
        history = self._active_history
        if history is None or record.record_revision <= history.last_sealed_revision:
            raise self._error(
                "Worker Supervisor history was not loaded",
                code="worker_supervisor_journal_corrupt",
            )
        if (
            self._active_replay is not None
            and record.record_revision != self._active_replay.last_revision + 1
        ):
            raise self._error(
                "Worker Supervisor V2 revision changed",
                code="worker_supervisor_journal_corrupt",
            )
        checkpoints = self._checkpoint_writer_fence(rooted)
        self._assert_checkpoint_write(checkpoints, history, record)
        line = (
            json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True).encode(
                "utf-8"
            )
            + b"\n"
        )
        if len(line) > self._max_history_bytes():
            raise self._error(
                "Worker Supervisor record exceeds capacity",
                code="worker_supervisor_journal_capacity",
            )
        active_records = record.record_revision - 1 - history.last_sealed_revision

        def append(name: str) -> None:
            append_jsonl_record(
                self.path,
                record,
                record_codec=WORKER_ATTEMPT_JOURNAL_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._durability,
                bound_file=rooted.sibling(name),
            )

        append_coding_worker_active_record(
            rooted,
            stem=_STEM,
            stream_id=_STEM,
            history=history,
            last_revision=record.record_revision - 1,
            line=line,
            seal_required=active_records >= self._max_history_records()
            or len(history.active_raw) + len(line) > self._max_history_bytes(),
            seal_error=lambda exc: self._error(
                "Worker Supervisor segment could not be sealed",
                code="worker_supervisor_journal_capacity"
                if exc.code == "coding_worker_segment_capacity"
                else "worker_supervisor_journal_corrupt",
            ),
            append=append,
        )

    def _checkpoint_writer_fence(
        self, rooted: RootedFile
    ) -> tuple[_CheckpointMethods, ...]:
        with self._history_reader.checkpoints.translated_errors(
            lambda code: self._error(
                "Worker Supervisor checkpoint could not be verified", code=code
            )
        ):
            return self._history_reader.checkpoints.read_writer_fence(
                rooted, scope_id=self._access.scope_id, store_id=self._access.store_id
            )

    def _assert_checkpoint_write(
        self,
        checkpoints: tuple[_CheckpointMethods, ...],
        history: CodingWorkerSegmentedHistoryV1,
        record: WorkerAttemptRecordV1,
    ) -> None:
        if not checkpoints:
            return
        prior = checkpoints[-1].stream_snapshots[4]
        if self._active_replay is None:
            current = (
                self._history_reader.checkpoints.record_type._snapshot_type.capture(
                    stem=_STEM,
                    active_generation=history.active_generation,
                    last_sealed_revision=history.last_sealed_revision,
                    segments=history.segments,
                )
            )
            source_changed = not prior.is_exact_prefix_of(
                current, current_segments=history.segments
            )
        else:
            source_changed = prior.total_revision > self._active_replay.last_revision
        if source_changed:
            raise self._error(
                "Worker Supervisor checkpoint source changed",
                code="worker_supervisor_checkpoint_source_changed",
            )
        if record.record_revision <= prior.total_revision:
            raise self._error(
                "Worker Supervisor checkpoint revision was reused",
                code="worker_supervisor_checkpoint_revision_retired",
            )
        if record.phase != "claimed":
            return
        if any(record.attempt_id in item.new_attempt_ids for item in checkpoints):
            raise self._error(
                "Worker Supervisor checkpoint attempt ID was reused",
                code="worker_supervisor_checkpoint_attempt_retired",
            )
        epoch_high_water = max(
            (
                epoch
                for item in checkpoints
                for key, epoch in item.supervisor_epoch_high_water
                if key == record.supervisor_key
            ),
            default=0,
        )
        if record.supervisor_epoch <= epoch_high_water:
            raise self._error(
                "Worker Supervisor checkpoint epoch was reused",
                code="worker_supervisor_checkpoint_epoch_retired",
            )

    def _require_bound(self) -> RootedFile:
        if self._active_rooted is None:
            raise self._error(
                "Worker Supervisor journal is not bound",
                code="worker_supervisor_journal_corrupt",
            )
        return self._active_rooted

    @staticmethod
    def _exists(rooted: RootedFile) -> bool:
        try:
            rooted.stat()
        except FileNotFoundError:
            return False
        return True

    def _max_history_bytes(self) -> int:
        return _MAX_BYTES

    def _max_history_records(self) -> int:
        return _MAX_RECORDS
