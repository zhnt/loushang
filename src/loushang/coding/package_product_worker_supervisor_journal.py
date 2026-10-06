"""Product-rooted, segmented Linux Supervisor history for Coding Workers."""

from __future__ import annotations

import json
import os
import stat
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    JournalCodecError,
    JournalLoadPolicy,
    append_jsonl_record,
    decode_jsonl,
)
from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.worker.contracts import WorkerLaunchIdentityV1
from loushang.harness.worker.journal import (
    WORKER_ATTEMPT_JOURNAL_CODEC,
    WorkerAttemptRecordV1,
    WorkerSupervisorJournal,
    _validate_history,
)

from .package_product_worker_history_segments import (
    CodingWorkerHistorySegmentError,
    CodingWorkerSegmentedHistoryV1,
    commit_coding_worker_active_segment,
    initialize_coding_worker_active_head,
    read_coding_worker_segmented_history,
    seal_coding_worker_active_segment,
)

_STEM = "worker-supervisor"
_MAX_RECORDS = 4096
_MAX_BYTES = 16 * 1024 * 1024
_DIR_FLAGS = (
    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    if os.name == "posix"
    else -1
)


class CodingProductWorkerSupervisorJournal(WorkerSupervisorJournal):
    """Keep Supervisor epochs and attempt IDs across immutable generations.

    The generic Supervisor owns transitions. This Product owner supplies exact
    Linux storage; it never retires old generations or treats a torn tail as a
    successful transition.
    """

    def __init__(self, product: PosixLocalWheelProductSessionOwner) -> None:
        if os.name != "posix":
            raise RuntimeError("Coding Worker POSIX Supervisor journal is unavailable")
        if (
            not isinstance(product, PosixLocalWheelProductSessionOwner)
            or product.policy.product_id != "coding"
        ):
            raise TypeError("Coding Worker Product owner is required")
        super().__init__(product.state_root / f"{_STEM}.jsonl")
        self._product = product
        self._thread_lock = threading.Lock()
        self._active_rooted: RootedFile | None = None
        self._active_history: CodingWorkerSegmentedHistoryV1 | None = None
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

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        with self._product.gc_gate.guard(), self._thread_lock:
            self._product.assert_root_gc_authority_current()
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
                io = RootedFileIO(self.path.parent, root_fd)
                try:
                    with io.bind(self.path, durable=True) as rooted:
                        history_present = self._exists(rooted) or self._exists(
                            rooted.sibling(f"{_STEM}.segments.json")
                        )
                        lock_present = self._exists(
                            rooted.sibling(f"{_STEM}.jsonl.lock")
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
                            self._product.assert_root_gc_authority_current()
                        finally:
                            self._active_rooted = None
                            self._active_history = None
                finally:
                    io.cleanup()
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
        try:
            history = read_coding_worker_segmented_history(
                rooted,
                stem=_STEM,
                stream_id=_STEM,
                max_segment_bytes=_MAX_BYTES,
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
                    len(segment) > _MAX_RECORDS
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
        line = (
            json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True).encode(
                "utf-8"
            )
            + b"\n"
        )
        if len(line) > _MAX_BYTES:
            raise self._error(
                "Worker Supervisor record exceeds capacity",
                code="worker_supervisor_journal_capacity",
            )
        active_records = record.record_revision - 1 - history.last_sealed_revision
        if (
            active_records >= _MAX_RECORDS
            or len(history.active_raw) + len(line) > _MAX_BYTES
        ):
            try:
                seal_coding_worker_active_segment(
                    rooted,
                    stem=_STEM,
                    stream_id=_STEM,
                    history=history,
                    last_revision=record.record_revision - 1,
                )
            except CodingWorkerHistorySegmentError as exc:
                raise self._error(
                    "Worker Supervisor segment could not be sealed",
                    code="worker_supervisor_journal_capacity"
                    if exc.code == "coding_worker_segment_capacity"
                    else "worker_supervisor_journal_corrupt",
                ) from exc
            generation = history.active_generation + 1
        else:
            generation = history.active_generation
        name = (
            f"{_STEM}.jsonl" if generation == 0 else f"{_STEM}.g{generation:08d}.jsonl"
        )
        append_jsonl_record(
            self.path,
            record,
            record_codec=WORKER_ATTEMPT_JOURNAL_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._durability,
            bound_file=rooted.sibling(name),
        )
        commit_coding_worker_active_segment(
            rooted,
            stem=_STEM,
            stream_id=_STEM,
            generation=generation,
            previous_raw=(
                b"" if generation != history.active_generation else history.active_raw
            ),
            appended_line=line,
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


__all__ = ["CodingProductWorkerSupervisorJournal"]
