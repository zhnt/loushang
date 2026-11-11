"""Checkpoint commands over the original bound Journal and five-stream snapshot owner."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generic, Protocol, cast

from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .._segmented_history import (
    CodingWorkerHistorySegmentError,
    CodingWorkerSegmentedHistoryV1,
    commit_coding_worker_active_segment,
    initialize_coding_worker_active_head,
    read_coding_worker_segmented_history,
    read_coding_worker_uncommitted_active_append,
    read_coding_worker_uncommitted_active_tail,
    rollback_coding_worker_uncommitted_active_tail,
    seal_coding_worker_active_segment,
)
from ._anchor import read_checkpoint_anchor, write_checkpoint_anchor
from ._checkpoint_history import _STEM, CheckpointHistory, _AnchorT, _CheckpointT
from ._receipts import _ReceiptRecordMethods
from ._snapshot import _SnapshotMethods
from ._snapshot_io import HistorySnapshotAccess, SnapshotHistory


class CheckpointCommandAccess(HistorySnapshotAccess, Protocol):
    @property
    def scope_id(self) -> str: ...

    @property
    def store_id(self) -> str: ...


class CheckpointStoreIdentity(Protocol):
    @property
    def store_id(self) -> str: ...


class _BackupRevision(Protocol):
    @property
    def owner_revision(self) -> str: ...


class CheckpointReview(Protocol):
    @property
    def receipt_record(self) -> _ReceiptRecordMethods | None: ...

    @property
    def worker_backup_references(self) -> _BackupRevision | None: ...

    @property
    def gc_reservation_revision(self) -> int: ...

    @property
    def history_stream_snapshots(self) -> tuple[_SnapshotMethods, ...]: ...

    @property
    def retained_opt_in_operation_ids(self) -> tuple[str, ...]: ...

    @property
    def retained_start_gate_attempt_ids(self) -> tuple[str, ...]: ...

    @property
    def retained_receipt_fingerprints(self) -> tuple[str, ...]: ...

    @property
    def opt_in_generation_high_water(
        self,
    ) -> tuple[tuple[str, int, int, str, str], ...]: ...

    @property
    def supervisor_epoch_high_water(self) -> tuple[tuple[str, int], ...]: ...


@dataclass(frozen=True, slots=True)
class CheckpointCommands(Generic[_CheckpointT, _AnchorT]):
    history: CheckpointHistory[_CheckpointT, _AnchorT]
    snapshots: SnapshotHistory
    max_record_bytes: int
    max_segment_bytes: int
    max_active_records: int

    def _read_records(
        self,
        rooted: RootedFile,
        *,
        scope_id: str,
        store_id: str,
        history: CodingWorkerSegmentedHistoryV1 | None = None,
    ) -> tuple[tuple[_CheckpointT, ...], CodingWorkerSegmentedHistoryV1]:
        return self.history.read_records(
            rooted,
            scope_id=scope_id,
            store_id=store_id,
            history=history,
            max_record_bytes=self.max_record_bytes,
            max_segment_bytes=self.max_segment_bytes,
            max_active_records=self.max_active_records,
        )

    def read_or_repair_empty_bootstrap(
        self, rooted: RootedFile, *, scope_id: str, store_id: str
    ) -> tuple[tuple[_CheckpointT, ...], CodingWorkerSegmentedHistoryV1]:
        """Finish only an anchored, empty first generation lacking its first head."""
        try:
            return self._read_records(rooted, scope_id=scope_id, store_id=store_id)
        except CodingWorkerHistorySegmentError as exc:
            if exc.code != "coding_worker_segment_head_missing":
                raise
            anchor = read_checkpoint_anchor(
                rooted,
                scope_id=scope_id,
                store_id=store_id,
                anchor_type=self.history.anchor_type,
                error_type=self.history.anchor_type._error_type,
            )
            if anchor is None or anchor.latest_revision != 0:
                raise
            try:
                raw = rooted.sibling(f"{_STEM}.jsonl").read_bytes(max_bytes=1)
            except FileNotFoundError:
                raise exc from None
            if raw != b"":
                raise exc
            try:
                rooted.sibling(f"{_STEM}.segments.json").stat()
            except FileNotFoundError:
                initialize_coding_worker_active_head(
                    rooted, stem=_STEM, stream_id=_STEM
                )
                return self._read_records(rooted, scope_id=scope_id, store_id=store_id)
            raise exc

    def candidate(
        self,
        access: CheckpointCommandAccess,
        *,
        attempt_id: str,
        review: CheckpointReview,
        records: tuple[_CheckpointT, ...],
    ) -> _CheckpointT:
        if review.receipt_record is None or review.worker_backup_references is None:
            raise self.history.error_type("coding_worker_checkpoint_closure_unproven")
        if records and (
            not self.snapshots.verify_extensions(
                access,
                previous=records[-1].stream_snapshots,
                current=review.history_stream_snapshots,
            )
        ):
            raise self.history.error_type("coding_worker_checkpoint_source_rewritten")
        seen_operations = {
            item for record in records for item in record.new_opt_in_operation_ids
        }
        seen_attempts = {item for record in records for item in record.new_attempt_ids}
        seen_receipts = {
            item for record in records for item in record.new_receipt_fingerprints
        }
        return self.history.record_type.create(
            journal_revision=len(records) + 1,
            scope_id=access.scope_id,
            store_id=access.store_id,
            attempt_id=attempt_id,
            receipt_fingerprint=review.receipt_record.receipt.fingerprint,
            previous_digest="" if not records else records[-1].record_digest,
            gc_reservation_revision=review.gc_reservation_revision,
            backup_topology_revision=review.worker_backup_references.owner_revision,
            stream_snapshots=review.history_stream_snapshots,
            new_opt_in_operation_ids=tuple(
                sorted(set(review.retained_opt_in_operation_ids) - seen_operations)
            ),
            new_attempt_ids=tuple(
                sorted(set(review.retained_start_gate_attempt_ids) - seen_attempts)
            ),
            new_receipt_fingerprints=tuple(
                sorted(set(review.retained_receipt_fingerprints) - seen_receipts)
            ),
            opt_in_generation_high_water=review.opt_in_generation_high_water,
            supervisor_epoch_high_water=review.supervisor_epoch_high_water,
        )

    @contextmanager
    def bound(self, access: CheckpointCommandAccess) -> Iterator[RootedFile]:
        access.assert_current()
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        root_fd = os.open(access.state_root, flags)
        try:
            opened = os.fstat(root_fd)
            visible = access.state_root.lstat()
            if (
                not stat.S_ISDIR(opened.st_mode)
                or opened.st_uid != os.geteuid()
                or stat.S_IMODE(opened.st_mode) & 63
                or ((opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino))
            ):
                raise self.history.error_type("coding_worker_checkpoint_root_changed")
            with RootedFileIO(access.state_root, root_fd) as file_io:
                with file_io.bind(
                    access.state_root / f"{_STEM}.jsonl", durable=True
                ) as rooted:
                    yield rooted
            access.assert_current()
        finally:
            os.close(root_fd)

    def read(
        self, rooted: RootedFile, *, access: CheckpointCommandAccess
    ) -> tuple[_CheckpointT, ...]:
        records, _history = self._read_records(
            rooted, scope_id=access.scope_id, store_id=access.store_id
        )
        self.history.anchor_for_records(
            rooted,
            scope_id=access.scope_id,
            store_id=access.store_id,
            records=records,
            settle_lag=False,
        )
        if records:
            current = self.snapshots.capture(access)
            if not self.snapshots.verify_extensions(
                access, previous=records[-1].stream_snapshots, current=current
            ):
                raise self.history.error_type(
                    "coding_worker_checkpoint_source_rewritten"
                )
        return records

    def publish(
        self,
        rooted: RootedFile,
        *,
        access: CheckpointCommandAccess,
        captured_store: CheckpointStoreIdentity,
        attempt_id: str,
        review: CheckpointReview,
    ) -> _CheckpointT:
        records, history = self.read_or_repair_empty_bootstrap(
            rooted, scope_id=access.scope_id, store_id=captured_store.store_id
        )
        anchor = self.history.anchor_for_records(
            rooted,
            scope_id=access.scope_id,
            store_id=captured_store.store_id,
            records=records,
            settle_lag=True,
        )
        if anchor is None:
            anchor = self.history.anchor_type.create(
                scope_id=access.scope_id,
                store_id=captured_store.store_id,
                latest_revision=0,
                latest_digest="",
            )
            write_checkpoint_anchor(
                rooted,
                expected=None,
                current=anchor,
                error_type=self.history.anchor_type._error_type,
            )
        if records:
            prior = records[-1]
            if (
                prior.attempt_id == attempt_id
                and prior.receipt_fingerprint
                == cast(
                    _ReceiptRecordMethods, review.receipt_record
                ).receipt.fingerprint
                and (prior.gc_reservation_revision == review.gc_reservation_revision)
                and (
                    prior.backup_topology_revision
                    == cast(
                        _BackupRevision, review.worker_backup_references
                    ).owner_revision
                )
                and (prior.stream_snapshots == review.history_stream_snapshots)
                and (
                    prior.opt_in_generation_high_water
                    == review.opt_in_generation_high_water
                )
                and (
                    prior.supervisor_epoch_high_water
                    == review.supervisor_epoch_high_water
                )
            ):
                return prior
        candidate = self.candidate(
            access, attempt_id=attempt_id, review=review, records=records
        )
        line = canonical_json_bytes(candidate.to_dict()) + b"\n"
        if len(line) > self.max_record_bytes:
            raise self.history.error_type("coding_worker_checkpoint_capacity")
        if not records:
            try:
                rooted.stat()
            except FileNotFoundError:
                rooted.create_new(b"")
                initialize_coding_worker_active_head(
                    rooted, stem=_STEM, stream_id=_STEM
                )
                history = read_coding_worker_segmented_history(
                    rooted,
                    stem=_STEM,
                    stream_id=_STEM,
                    max_segment_bytes=self.max_segment_bytes,
                )
        if (
            len(records) - history.last_sealed_revision >= self.max_active_records
            or len(history.active_raw) + len(line) > self.max_segment_bytes
        ):
            try:
                seal_coding_worker_active_segment(
                    rooted,
                    stem=_STEM,
                    stream_id=_STEM,
                    history=history,
                    last_revision=len(records),
                )
            except CodingWorkerHistorySegmentError as exc:
                raise self.history.error_type(exc.code) from exc
            generation = history.active_generation + 1
            previous_raw = b""
        else:
            generation = history.active_generation
            previous_raw = history.active_raw
        target = rooted.sibling(
            f"{_STEM}.jsonl" if generation == 0 else f"{_STEM}.g{generation:08d}.jsonl"
        )
        target.append_bytes(line)
        commit_coding_worker_active_segment(
            rooted,
            stem=_STEM,
            stream_id=_STEM,
            generation=generation,
            previous_raw=previous_raw,
            appended_line=line,
        )
        self.history.advance_anchor(rooted, prior=anchor, checkpoint=candidate)
        return candidate

    def repair(
        self,
        rooted: RootedFile,
        *,
        access: CheckpointCommandAccess,
        captured_store: CheckpointStoreIdentity,
        attempt_id: str,
        review: CheckpointReview,
    ) -> _CheckpointT:
        pending = read_coding_worker_uncommitted_active_append(
            rooted,
            stem=_STEM,
            stream_id=_STEM,
            max_segment_bytes=self.max_segment_bytes,
        )
        records, history = self._read_records(
            rooted,
            scope_id=access.scope_id,
            store_id=captured_store.store_id,
            history=pending.committed_history,
        )
        anchor = self.history.anchor_for_records(
            rooted,
            scope_id=access.scope_id,
            store_id=captured_store.store_id,
            records=records,
            settle_lag=True,
        )
        if anchor is None:
            raise self.history.error_type("coding_worker_checkpoint_anchor_missing")
        candidate = self.candidate(
            access, attempt_id=attempt_id, review=review, records=records
        )
        if pending.appended_line != canonical_json_bytes(candidate.to_dict()) + b"\n":
            raise self.history.error_type("coding_worker_checkpoint_repair_mismatch")
        commit_coding_worker_active_segment(
            rooted,
            stem=_STEM,
            stream_id=_STEM,
            generation=history.active_generation,
            previous_raw=history.active_raw,
            appended_line=pending.appended_line,
        )
        self.history.advance_anchor(rooted, prior=anchor, checkpoint=candidate)
        repaired, _ = self._read_records(
            rooted, scope_id=access.scope_id, store_id=captured_store.store_id
        )
        if repaired != (*records, candidate):
            raise self.history.error_type("coding_worker_checkpoint_repair_mismatch")
        return candidate

    def rollback(
        self,
        rooted: RootedFile,
        *,
        access: CheckpointCommandAccess,
        captured_store: CheckpointStoreIdentity,
    ) -> tuple[_CheckpointT, ...]:
        history, _tail = read_coding_worker_uncommitted_active_tail(
            rooted,
            stem=_STEM,
            stream_id=_STEM,
            max_segment_bytes=self.max_segment_bytes,
        )
        records, _ = self._read_records(
            rooted,
            scope_id=access.scope_id,
            store_id=captured_store.store_id,
            history=history,
        )
        anchor = self.history.anchor_for_records(
            rooted,
            scope_id=access.scope_id,
            store_id=captured_store.store_id,
            records=records,
            settle_lag=True,
        )
        if anchor is None:
            raise self.history.error_type("coding_worker_checkpoint_anchor_missing")
        if records:
            current = self.snapshots.capture(access)
            if not self.snapshots.verify_extensions(
                access, previous=records[-1].stream_snapshots, current=current
            ):
                raise self.history.error_type(
                    "coding_worker_checkpoint_source_rewritten"
                )
        rollback_coding_worker_uncommitted_active_tail(
            rooted,
            stem=_STEM,
            stream_id=_STEM,
            max_segment_bytes=self.max_segment_bytes,
        )
        reopened, _ = self._read_records(
            rooted, scope_id=access.scope_id, store_id=captured_store.store_id
        )
        if reopened != records:
            raise self.history.error_type("coding_worker_checkpoint_rollback_changed")
        return reopened
