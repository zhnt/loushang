"""Checkpoint replay and anchor mechanics on an already bound history.

The caller retains Product/root/lock custody. A writer fence never repairs;
anchor advancement is only the caller's explicit settlement operation.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from typing import Generic, Protocol, TypeVar, cast

from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .._segmented_history import (
    CodingWorkerHistorySegmentError,
    CodingWorkerSegmentedHistoryV1,
    read_coding_worker_segmented_history,
    read_coding_worker_uncommitted_active_tail,
)
from ._anchor import (
    ANCHOR_NAME,
    _AnchorMethods,
    read_checkpoint_anchor,
    write_checkpoint_anchor,
)
from ._checkpoint import _CheckpointMethods
from ._snapshot import CODING_WORKER_HISTORY_STREAM_STEMS, _SnapshotMethods

_STEM = "worker-history-checkpoints"
_MAX_RECORD_BYTES = 4 * 1024 * 1024
_MAX_SEGMENT_BYTES = 32 * 1024 * 1024
_MAX_ACTIVE_RECORDS = 4096

_CheckpointT = TypeVar("_CheckpointT", bound=_CheckpointMethods)
_AnchorT = TypeVar("_AnchorT", bound=_AnchorMethods)


class _CodedFailure(Protocol):
    code: str


def _is_empty_seal_successor(
    old: _SnapshotMethods,
    current: _SnapshotMethods,
) -> bool:
    """Recognize one exact sealed prefix with an empty active successor."""

    return (
        current.stem == old.stem
        and current.total_revision == old.total_revision
        and current.active_generation == old.active_generation + 1
        and current.last_sealed_revision == old.total_revision
        and current.segment_byte_counts == (*old.segment_byte_counts, 0)
        and current.segment_digests == (*old.segment_digests, sha256(b"").hexdigest())
    )


@dataclass(frozen=True, slots=True)
class CheckpointHistory(Generic[_CheckpointT, _AnchorT]):
    """Fixed value/error bindings, with no Product or permission callbacks."""

    record_type: type[_CheckpointT]
    anchor_type: type[_AnchorT]
    error_type: type[RuntimeError]

    @staticmethod
    def require_unowned_absence(
        rooted: RootedFile, *, error_type: Callable[[str], Exception], code: str
    ) -> None:
        """Only callers with missing owner configuration use this original scan."""
        for name in (
            ANCHOR_NAME,
            f"{_STEM}.jsonl",
            f"{_STEM}.jsonl.lock",
            f"{_STEM}.head.json",
            f"{_STEM}.segments.json",
        ):
            try:
                rooted.sibling(name).stat()
            except FileNotFoundError:
                continue
            raise error_type(code) from None

    @contextmanager
    def translated_errors(
        self, error_type: Callable[[str], Exception]
    ) -> Iterator[None]:
        """Keep caller argument evaluation inside the original exception region."""
        try:
            yield
        except (
            self.error_type,
            self.anchor_type._error_type,
            CodingWorkerHistorySegmentError,
        ) as exc:
            raise error_type(cast(_CodedFailure, exc).code) from exc

    def verify_source_revision(
        self,
        checkpoints: tuple[_CheckpointT, ...],
        history: CodingWorkerSegmentedHistoryV1,
        *,
        stream_index: int,
        error_type: Callable[[str], Exception],
        code: str,
    ) -> int:
        if not checkpoints:
            return 0
        prior = checkpoints[-1].stream_snapshots[stream_index]
        current = self.record_type._snapshot_type.capture(
            stem=CODING_WORKER_HISTORY_STREAM_STEMS[stream_index],
            active_generation=history.active_generation,
            last_sealed_revision=history.last_sealed_revision,
            segments=history.segments,
        )
        if not prior.is_exact_prefix_of(current, current_segments=history.segments):
            raise error_type(code)
        return prior.total_revision

    def read_records(
        self,
        rooted: RootedFile,
        *,
        scope_id: str,
        store_id: str,
        history: CodingWorkerSegmentedHistoryV1 | None = None,
        max_record_bytes: int = _MAX_RECORD_BYTES,
        max_segment_bytes: int = _MAX_SEGMENT_BYTES,
        max_active_records: int = _MAX_ACTIVE_RECORDS,
    ) -> tuple[tuple[_CheckpointT, ...], CodingWorkerSegmentedHistoryV1]:
        if history is None:
            history = read_coding_worker_segmented_history(
                rooted, stem=_STEM, stream_id=_STEM, max_segment_bytes=max_segment_bytes
            )
        if history.manifest is not None and any(
            (
                segment.count(b"\n") != seal.last_revision - seal.first_revision + 1
                for segment, seal in zip(
                    history.segments[:-1], history.manifest.sealed, strict=True
                )
            )
        ):
            raise self.error_type("coding_worker_checkpoint_corrupt")
        records: list[_CheckpointT] = []
        seen_operations: set[str] = set()
        seen_attempts: set[str] = set()
        seen_receipts: set[str] = set()
        for segment in history.segments:
            if segment and (not segment.endswith(b"\n")):
                raise self.error_type("coding_worker_checkpoint_corrupt")
            for line in segment.splitlines(keepends=True):
                if not line.endswith(b"\n") or len(line) > max_record_bytes:
                    raise self.error_type("coding_worker_checkpoint_corrupt")
                try:
                    value = json.loads(line)
                    record = self.record_type.from_dict(value)
                except (TypeError, ValueError, UnicodeError) as exc:
                    raise self.error_type("coding_worker_checkpoint_corrupt") from exc
                if (
                    canonical_json_bytes(record.to_dict()) + b"\n" != line
                    or record.journal_revision != len(records) + 1
                    or record.scope_id != scope_id
                    or (record.store_id != store_id)
                    or (
                        record.previous_digest
                        != ("" if not records else records[-1].record_digest)
                    )
                ):
                    raise self.error_type("coding_worker_checkpoint_corrupt")
                if (
                    seen_operations.intersection(record.new_opt_in_operation_ids)
                    or seen_attempts.intersection(record.new_attempt_ids)
                    or seen_receipts.intersection(record.new_receipt_fingerprints)
                ):
                    raise self.error_type("coding_worker_checkpoint_id_reused")
                seen_operations.update(record.new_opt_in_operation_ids)
                seen_attempts.update(record.new_attempt_ids)
                seen_receipts.update(record.new_receipt_fingerprints)
                if (
                    record.attempt_id not in seen_attempts
                    or record.receipt_fingerprint not in seen_receipts
                ):
                    raise self.error_type("coding_worker_checkpoint_reference_absent")
                if records:
                    previous = records[-1]
                    if (
                        record.gc_reservation_revision
                        < previous.gc_reservation_revision
                        or record.backup_topology_revision
                        != previous.backup_topology_revision
                        or any(
                            (
                                current.total_revision < old.total_revision
                                or current.active_generation < old.active_generation
                                or current.last_sealed_revision
                                < old.last_sealed_revision
                                or (
                                    current.total_revision == old.total_revision
                                    and current.fingerprint != old.fingerprint
                                    and (not _is_empty_seal_successor(old, current))
                                )
                                for old, current in zip(
                                    previous.stream_snapshots,
                                    record.stream_snapshots,
                                    strict=True,
                                )
                            )
                        )
                    ):
                        raise self.error_type(
                            "coding_worker_checkpoint_high_water_regressed"
                        )
                    previous_opt_in = {
                        item[0]: item for item in previous.opt_in_generation_high_water
                    }
                    current_opt_in = {
                        item[0]: item for item in record.opt_in_generation_high_water
                    }
                    if any(
                        (
                            plugin_id not in current_opt_in
                            or current_opt_in[plugin_id][1] < item[1]
                            or current_opt_in[plugin_id][2] < item[2]
                            or (
                                current_opt_in[plugin_id][1] == item[1]
                                and current_opt_in[plugin_id] != item
                            )
                            for plugin_id, item in previous_opt_in.items()
                        )
                    ):
                        raise self.error_type(
                            "coding_worker_checkpoint_opt_in_regressed"
                        )
                    previous_epochs = dict(previous.supervisor_epoch_high_water)
                    current_epochs = dict(record.supervisor_epoch_high_water)
                    if any(
                        (
                            key not in current_epochs or current_epochs[key] < epoch
                            for key, epoch in previous_epochs.items()
                        )
                    ):
                        raise self.error_type(
                            "coding_worker_checkpoint_supervisor_regressed"
                        )
                records.append(record)
        if (
            history.last_sealed_revision > len(records)
            or len(records) - history.last_sealed_revision > max_active_records
        ):
            raise self.error_type("coding_worker_checkpoint_corrupt")
        return (tuple(records), history)

    def anchor_for_records(
        self,
        rooted: RootedFile,
        *,
        scope_id: str,
        store_id: str,
        records: tuple[_CheckpointT, ...],
        settle_lag: bool,
    ) -> _AnchorT | None:
        anchor = read_checkpoint_anchor(
            rooted,
            scope_id=scope_id,
            store_id=store_id,
            anchor_type=self.anchor_type,
            error_type=self.anchor_type._error_type,
        )
        if anchor is None:
            try:
                rooted.stat()
            except FileNotFoundError:
                if records:
                    raise self.error_type(
                        "coding_worker_checkpoint_anchor_missing"
                    ) from None
                return None
            raise self.error_type("coding_worker_checkpoint_anchor_missing")
        if anchor.latest_revision > len(records) or (
            anchor.latest_revision > 0
            and records[anchor.latest_revision - 1].record_digest
            != anchor.latest_digest
        ):
            raise self.error_type("coding_worker_checkpoint_anchor_changed")
        if anchor.latest_revision < len(records):
            if not settle_lag:
                raise self.error_type("coding_worker_checkpoint_anchor_lagging")
            latest = records[-1]
            updated = self.anchor_type.create(
                scope_id=scope_id,
                store_id=store_id,
                latest_revision=latest.journal_revision,
                latest_digest=latest.record_digest,
            )
            write_checkpoint_anchor(
                rooted,
                expected=anchor,
                current=updated,
                error_type=self.anchor_type._error_type,
            )
            anchor = updated
        return anchor

    def advance_anchor(
        self, rooted: RootedFile, *, prior: _AnchorT, checkpoint: _CheckpointT
    ) -> None:
        updated = self.anchor_type.create(
            scope_id=prior.scope_id,
            store_id=prior.store_id,
            latest_revision=checkpoint.journal_revision,
            latest_digest=checkpoint.record_digest,
        )
        write_checkpoint_anchor(
            rooted,
            expected=prior,
            current=updated,
            error_type=self.anchor_type._error_type,
        )

    def read_writer_fence(
        self,
        rooted: RootedFile,
        *,
        scope_id: str,
        store_id: str,
        max_record_bytes: int = _MAX_RECORD_BYTES,
        max_segment_bytes: int = _MAX_SEGMENT_BYTES,
        max_active_records: int = _MAX_ACTIVE_RECORDS,
    ) -> tuple[_CheckpointT, ...]:
        """Read the anchored tip while the Product GC write gate excludes publishers.

        The caller owns a pinned Product state root and the GC write gate. This
        check never repairs an anchor or grants history-retirement authority.
        """
        checkpoint_rooted = rooted.sibling(f"{_STEM}.jsonl")
        try:
            records, _history = self.read_records(
                checkpoint_rooted,
                scope_id=scope_id,
                store_id=store_id,
                max_record_bytes=max_record_bytes,
                max_segment_bytes=max_segment_bytes,
                max_active_records=max_active_records,
            )
        except CodingWorkerHistorySegmentError as exc:
            if exc.code != "coding_worker_segment_head_changed":
                raise
            committed, _tail = read_coding_worker_uncommitted_active_tail(
                checkpoint_rooted,
                stem=_STEM,
                stream_id=_STEM,
                max_segment_bytes=max_segment_bytes,
            )
            records, _history = self.read_records(
                checkpoint_rooted,
                scope_id=scope_id,
                store_id=store_id,
                history=committed,
                max_record_bytes=max_record_bytes,
                max_segment_bytes=max_segment_bytes,
                max_active_records=max_active_records,
            )
        self.anchor_for_records(
            checkpoint_rooted,
            scope_id=scope_id,
            store_id=store_id,
            records=records,
            settle_lag=False,
        )
        return records
