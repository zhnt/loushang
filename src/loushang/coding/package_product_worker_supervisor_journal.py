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
from typing import TYPE_CHECKING

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
    CodingWorkerSegmentManifestV1,
    commit_coding_worker_active_segment,
    initialize_coding_worker_active_head,
    read_coding_worker_segmented_history,
    seal_coding_worker_active_segment,
)
from .package_product_worker_history_stream_snapshot import (
    CodingWorkerHistoryStreamSnapshotV1,
)
from .package_product_worker_history_v2_names import PRODUCT_OWNER_INDEX_NAME

if TYPE_CHECKING:
    from .package_product_worker_history_checkpoint import (
        CodingWorkerHistoryCheckpointV1,
    )
    from .package_product_worker_supervisor_base_v2 import (
        CodingWorkerSupervisorReplayV2,
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
        self._active_replay: CodingWorkerSupervisorReplayV2 | None = None
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
            self._product.gc_gate.guard(require_write=not self._read_only.get()),
            self._thread_lock,
        ):
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
                            self._product.assert_root_gc_authority_current()
                        finally:
                            self._active_rooted = None
                            self._active_history = None
                            self._active_replay = None
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

    def _load_v2_state(
        self, rooted: RootedFile
    ) -> tuple[CodingWorkerSegmentedHistoryV1, CodingWorkerSupervisorReplayV2]:
        from .package_product_worker_history_cutover_v2 import (
            CodingWorkerProductCutoverIndexV2,
        )
        from .package_product_worker_history_read_v2 import (
            CodingWorkerV2ReadError,
            read_coding_worker_v2_retained_history,
        )
        from .package_product_worker_supervisor_base_v2 import (
            CodingWorkerSupervisorReplayV2,
        )

        try:
            owner = CodingWorkerProductCutoverIndexV2.from_bytes(
                rooted.sibling(PRODUCT_OWNER_INDEX_NAME).read_bytes(max_bytes=4096)
            )
            if (
                owner.scope_id != self._product.policy.project_scope_id
                or owner.store_id != self._product.epoch_runtime.registry.store_id
            ):
                raise self._error(
                    "Worker Supervisor V2 owner changed",
                    code="worker_supervisor_journal_corrupt",
                )
            retained = read_coding_worker_v2_retained_history(rooted, stem=_STEM)
            replay = retained.replay
            if not isinstance(replay, CodingWorkerSupervisorReplayV2):
                raise self._error(
                    "Worker Supervisor V2 replay changed",
                    code="worker_supervisor_journal_corrupt",
                )
            manifest = CodingWorkerSegmentManifestV1.from_bytes(
                rooted.sibling(_STEM + ".segments.json").read_bytes(
                    max_bytes=1024 * 1024
                ),
                stream_id=_STEM,
            )
            if manifest.active_generation != retained.active_generation:
                raise self._error(
                    "Worker Supervisor V2 manifest changed",
                    code="worker_supervisor_journal_corrupt",
                )
            return (
                CodingWorkerSegmentedHistoryV1(
                    manifest=manifest,
                    segments=(b"",) * retained.first_retained_generation
                    + retained.segments,
                ),
                replay,
            )
        except (
            CodingWorkerV2ReadError,
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

    def _checkpoint_writer_fence(
        self, rooted: RootedFile
    ) -> tuple[CodingWorkerHistoryCheckpointV1, ...]:
        from .package_product_worker_history_checkpoint import (
            CodingWorkerHistoryCheckpointError,
            read_coding_worker_checkpoint_writer_fence,
        )
        from .package_product_worker_history_checkpoint_anchor import (
            CodingWorkerCheckpointAnchorError,
        )

        try:
            return read_coding_worker_checkpoint_writer_fence(
                rooted,
                scope_id=self._product.policy.project_scope_id,
                store_id=self._product.epoch_runtime.registry.store_id,
            )
        except (
            CodingWorkerHistoryCheckpointError,
            CodingWorkerCheckpointAnchorError,
            CodingWorkerHistorySegmentError,
        ) as exc:
            raise self._error(
                "Worker Supervisor checkpoint could not be verified", code=exc.code
            ) from exc

    def _assert_checkpoint_write(
        self,
        checkpoints: tuple[CodingWorkerHistoryCheckpointV1, ...],
        history: CodingWorkerSegmentedHistoryV1,
        record: WorkerAttemptRecordV1,
    ) -> None:
        if not checkpoints:
            return
        prior = checkpoints[-1].stream_snapshots[4]
        if self._active_replay is None:
            current = CodingWorkerHistoryStreamSnapshotV1.capture(
                stem=_STEM,
                active_generation=history.active_generation,
                last_sealed_revision=history.last_sealed_revision,
                segments=history.segments,
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


__all__ = ["CodingProductWorkerSupervisorJournal"]
