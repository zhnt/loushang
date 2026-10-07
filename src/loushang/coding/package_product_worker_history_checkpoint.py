"""Durable Linux Product Worker history checkpoint, without pruning authority."""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_product_worker_history_retention import (
    CodingWorkerHistoryRetentionReviewV1,
    _review_coding_product_worker_history_under_guard,
)
from .package_product_worker_history_segments import (
    CodingWorkerHistorySegmentError,
    CodingWorkerSegmentedHistoryV1,
    commit_coding_worker_active_segment,
    initialize_coding_worker_active_head,
    read_coding_worker_segmented_history,
    read_coding_worker_uncommitted_active_append,
    seal_coding_worker_active_segment,
)
from .package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
    CodingWorkerHistoryStreamSnapshotV1,
)

_STEM = "worker-history-checkpoints"
_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_RECORD_BYTES = 4 * 1024 * 1024
_MAX_SEGMENT_BYTES = 32 * 1024 * 1024
_MAX_ACTIVE_RECORDS = 4096


class CodingWorkerHistoryCheckpointError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _sorted_unique(values: tuple[str, ...]) -> bool:
    return type(values) is tuple and values == tuple(sorted(set(values)))


@dataclass(frozen=True, slots=True)
class CodingWorkerHistoryCheckpointV1:
    journal_revision: int
    scope_id: str
    store_id: str
    attempt_id: str
    receipt_fingerprint: str
    previous_digest: str
    gc_reservation_revision: int
    backup_topology_revision: str
    stream_snapshots: tuple[CodingWorkerHistoryStreamSnapshotV1, ...]
    new_opt_in_operation_ids: tuple[str, ...]
    new_attempt_ids: tuple[str, ...]
    new_receipt_fingerprints: tuple[str, ...]
    opt_in_generation_high_water: tuple[tuple[str, int, int, str, str], ...]
    supervisor_epoch_high_water: tuple[tuple[str, int], ...]
    record_digest: str
    record_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.journal_revision) is not int
            or self.journal_revision < 1
            or type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.store_id) is not str
            or not self.store_id
            or len(self.store_id) > 128
            or type(self.attempt_id) is not str
            or _ATTEMPT.fullmatch(self.attempt_id) is None
            or type(self.receipt_fingerprint) is not str
            or _DIGEST.fullmatch(self.receipt_fingerprint) is None
            or type(self.previous_digest) is not str
            or (
                self.previous_digest and _DIGEST.fullmatch(self.previous_digest) is None
            )
            or type(self.gc_reservation_revision) is not int
            or self.gc_reservation_revision < 0
            or type(self.backup_topology_revision) is not str
            or not self.backup_topology_revision.startswith(
                "coding-product-backup-types:"
            )
            or type(self.stream_snapshots) is not tuple
            or any(
                type(item) is not CodingWorkerHistoryStreamSnapshotV1
                for item in self.stream_snapshots
            )
            or tuple(item.stem for item in self.stream_snapshots)
            != CODING_WORKER_HISTORY_STREAM_STEMS
            or not _sorted_unique(self.new_opt_in_operation_ids)
            or not _sorted_unique(self.new_attempt_ids)
            or not _sorted_unique(self.new_receipt_fingerprints)
            or any(
                type(item) is not str or not item or len(item) > 128
                for item in self.new_opt_in_operation_ids
            )
            or any(_ATTEMPT.fullmatch(item) is None for item in self.new_attempt_ids)
            or any(
                _DIGEST.fullmatch(item) is None
                for item in self.new_receipt_fingerprints
            )
            or type(self.opt_in_generation_high_water) is not tuple
            or self.opt_in_generation_high_water
            != tuple(sorted(self.opt_in_generation_high_water))
            or type(self.supervisor_epoch_high_water) is not tuple
            or self.supervisor_epoch_high_water
            != tuple(sorted(self.supervisor_epoch_high_water))
            or type(self.record_version) is not int
            or self.record_version != 1
            or type(self.record_digest) is not str
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Coding Worker history checkpoint is invalid")
        for (
            plugin_id,
            generation,
            kill_generation,
            action,
            digest,
        ) in self.opt_in_generation_high_water:
            if (
                type(plugin_id) is not str
                or not plugin_id
                or type(generation) is not int
                or generation < 1
                or type(kill_generation) is not int
                or kill_generation < 0
                or action not in {"allow", "revoke"}
                or type(digest) is not str
                or _DIGEST.fullmatch(digest) is None
            ):
                raise ValueError(
                    "Coding Worker checkpoint opt-in high water is invalid"
                )
        if len({item[0] for item in self.opt_in_generation_high_water}) != len(
            self.opt_in_generation_high_water
        ):
            raise ValueError("Coding Worker checkpoint opt-in keys repeat")
        for key, epoch in self.supervisor_epoch_high_water:
            if type(key) is not str or not key or type(epoch) is not int or epoch < 1:
                raise ValueError(
                    "Coding Worker checkpoint Supervisor high water is invalid"
                )
        if len({item[0] for item in self.supervisor_epoch_high_water}) != len(
            self.supervisor_epoch_high_water
        ):
            raise ValueError("Coding Worker checkpoint Supervisor keys repeat")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "attemptId": self.attempt_id,
            "backupTopologyRevision": self.backup_topology_revision,
            "gcReservationRevision": self.gc_reservation_revision,
            "journalRevision": self.journal_revision,
            "newAttemptIds": list(self.new_attempt_ids),
            "newOptInOperationIds": list(self.new_opt_in_operation_ids),
            "newReceiptFingerprints": list(self.new_receipt_fingerprints),
            "optInGenerationHighWater": [
                list(item) for item in self.opt_in_generation_high_water
            ],
            "previousDigest": self.previous_digest,
            "receiptFingerprint": self.receipt_fingerprint,
            "recordVersion": self.record_version,
            "scopeId": self.scope_id,
            "storeId": self.store_id,
            "streamSnapshots": [item.to_dict() for item in self.stream_snapshots],
            "supervisorEpochHighWater": [
                list(item) for item in self.supervisor_epoch_high_water
            ],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "recordDigest": self.record_digest}

    @classmethod
    def create(
        cls,
        *,
        journal_revision: int,
        scope_id: str,
        store_id: str,
        attempt_id: str,
        receipt_fingerprint: str,
        previous_digest: str,
        gc_reservation_revision: int,
        backup_topology_revision: str,
        stream_snapshots: tuple[CodingWorkerHistoryStreamSnapshotV1, ...],
        new_opt_in_operation_ids: tuple[str, ...],
        new_attempt_ids: tuple[str, ...],
        new_receipt_fingerprints: tuple[str, ...],
        opt_in_generation_high_water: tuple[tuple[str, int, int, str, str], ...],
        supervisor_epoch_high_water: tuple[tuple[str, int], ...],
    ) -> CodingWorkerHistoryCheckpointV1:
        unsigned = {
            "attemptId": attempt_id,
            "backupTopologyRevision": backup_topology_revision,
            "gcReservationRevision": gc_reservation_revision,
            "journalRevision": journal_revision,
            "newAttemptIds": list(new_attempt_ids),
            "newOptInOperationIds": list(new_opt_in_operation_ids),
            "newReceiptFingerprints": list(new_receipt_fingerprints),
            "optInGenerationHighWater": [
                list(item) for item in opt_in_generation_high_water
            ],
            "previousDigest": previous_digest,
            "receiptFingerprint": receipt_fingerprint,
            "recordVersion": 1,
            "scopeId": scope_id,
            "storeId": store_id,
            "streamSnapshots": [item.to_dict() for item in stream_snapshots],
            "supervisorEpochHighWater": [
                list(item) for item in supervisor_epoch_high_water
            ],
        }
        return cls(
            journal_revision=journal_revision,
            scope_id=scope_id,
            store_id=store_id,
            attempt_id=attempt_id,
            receipt_fingerprint=receipt_fingerprint,
            previous_digest=previous_digest,
            gc_reservation_revision=gc_reservation_revision,
            backup_topology_revision=backup_topology_revision,
            stream_snapshots=stream_snapshots,
            new_opt_in_operation_ids=new_opt_in_operation_ids,
            new_attempt_ids=new_attempt_ids,
            new_receipt_fingerprints=new_receipt_fingerprints,
            opt_in_generation_high_water=opt_in_generation_high_water,
            supervisor_epoch_high_water=supervisor_epoch_high_water,
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )

    @classmethod
    def from_dict(cls, value: object) -> CodingWorkerHistoryCheckpointV1:
        if type(value) is not dict or set(value) != {
            "attemptId",
            "backupTopologyRevision",
            "gcReservationRevision",
            "journalRevision",
            "newAttemptIds",
            "newOptInOperationIds",
            "newReceiptFingerprints",
            "optInGenerationHighWater",
            "previousDigest",
            "receiptFingerprint",
            "recordDigest",
            "recordVersion",
            "scopeId",
            "storeId",
            "streamSnapshots",
            "supervisorEpochHighWater",
        }:
            raise ValueError("Coding Worker checkpoint record shape is invalid")
        for name in (
            "newAttemptIds",
            "newOptInOperationIds",
            "newReceiptFingerprints",
            "optInGenerationHighWater",
            "streamSnapshots",
            "supervisorEpochHighWater",
        ):
            if type(value[name]) is not list:
                raise ValueError("Coding Worker checkpoint list shape is invalid")
        return cls(
            journal_revision=value["journalRevision"],
            scope_id=value["scopeId"],
            store_id=value["storeId"],
            attempt_id=value["attemptId"],
            receipt_fingerprint=value["receiptFingerprint"],
            previous_digest=value["previousDigest"],
            gc_reservation_revision=value["gcReservationRevision"],
            backup_topology_revision=value["backupTopologyRevision"],
            stream_snapshots=tuple(
                CodingWorkerHistoryStreamSnapshotV1.from_dict(item)
                for item in value["streamSnapshots"]
            ),
            new_opt_in_operation_ids=tuple(value["newOptInOperationIds"]),
            new_attempt_ids=tuple(value["newAttemptIds"]),
            new_receipt_fingerprints=tuple(value["newReceiptFingerprints"]),
            opt_in_generation_high_water=tuple(
                tuple(item) for item in value["optInGenerationHighWater"]
            ),
            supervisor_epoch_high_water=tuple(
                tuple(item) for item in value["supervisorEpochHighWater"]
            ),
            record_digest=value["recordDigest"],
            record_version=value["recordVersion"],
        )


def _read_records(
    rooted: RootedFile,
    *,
    scope_id: str,
    store_id: str,
    history: CodingWorkerSegmentedHistoryV1 | None = None,
) -> tuple[tuple[CodingWorkerHistoryCheckpointV1, ...], CodingWorkerSegmentedHistoryV1]:
    if history is None:
        history = read_coding_worker_segmented_history(
            rooted, stem=_STEM, stream_id=_STEM, max_segment_bytes=_MAX_SEGMENT_BYTES
        )
    if history.manifest is not None and any(
        segment.count(b"\n") != seal.last_revision - seal.first_revision + 1
        for segment, seal in zip(
            history.segments[:-1], history.manifest.sealed, strict=True
        )
    ):
        raise CodingWorkerHistoryCheckpointError("coding_worker_checkpoint_corrupt")
    records: list[CodingWorkerHistoryCheckpointV1] = []
    seen_operations: set[str] = set()
    seen_attempts: set[str] = set()
    seen_receipts: set[str] = set()
    for segment in history.segments:
        if segment and not segment.endswith(b"\n"):
            raise CodingWorkerHistoryCheckpointError("coding_worker_checkpoint_corrupt")
        for line in segment.splitlines(keepends=True):
            if not line.endswith(b"\n") or len(line) > _MAX_RECORD_BYTES:
                raise CodingWorkerHistoryCheckpointError(
                    "coding_worker_checkpoint_corrupt"
                )
            try:
                value = json.loads(line)
                record = CodingWorkerHistoryCheckpointV1.from_dict(value)
            except (TypeError, ValueError, UnicodeError) as exc:
                raise CodingWorkerHistoryCheckpointError(
                    "coding_worker_checkpoint_corrupt"
                ) from exc
            if (
                canonical_json_bytes(record.to_dict()) + b"\n" != line
                or record.journal_revision != len(records) + 1
                or record.scope_id != scope_id
                or record.store_id != store_id
                or record.previous_digest
                != ("" if not records else records[-1].record_digest)
            ):
                raise CodingWorkerHistoryCheckpointError(
                    "coding_worker_checkpoint_corrupt"
                )
            if (
                seen_operations.intersection(record.new_opt_in_operation_ids)
                or seen_attempts.intersection(record.new_attempt_ids)
                or seen_receipts.intersection(record.new_receipt_fingerprints)
            ):
                raise CodingWorkerHistoryCheckpointError(
                    "coding_worker_checkpoint_id_reused"
                )
            seen_operations.update(record.new_opt_in_operation_ids)
            seen_attempts.update(record.new_attempt_ids)
            seen_receipts.update(record.new_receipt_fingerprints)
            if (
                record.attempt_id not in seen_attempts
                or record.receipt_fingerprint not in seen_receipts
            ):
                raise CodingWorkerHistoryCheckpointError(
                    "coding_worker_checkpoint_reference_absent"
                )
            if records:
                previous = records[-1]
                if (
                    record.gc_reservation_revision < previous.gc_reservation_revision
                    or record.backup_topology_revision
                    != previous.backup_topology_revision
                    or any(
                        current.total_revision < old.total_revision
                        or current.active_generation < old.active_generation
                        or current.last_sealed_revision < old.last_sealed_revision
                        or (
                            current.total_revision == old.total_revision
                            and current.fingerprint != old.fingerprint
                        )
                        for old, current in zip(
                            previous.stream_snapshots,
                            record.stream_snapshots,
                            strict=True,
                        )
                    )
                ):
                    raise CodingWorkerHistoryCheckpointError(
                        "coding_worker_checkpoint_high_water_regressed"
                    )
                previous_opt_in = {
                    item[0]: item for item in previous.opt_in_generation_high_water
                }
                current_opt_in = {
                    item[0]: item for item in record.opt_in_generation_high_water
                }
                if any(
                    plugin_id not in current_opt_in
                    or current_opt_in[plugin_id][1] < item[1]
                    or current_opt_in[plugin_id][2] < item[2]
                    or (
                        current_opt_in[plugin_id][1] == item[1]
                        and current_opt_in[plugin_id] != item
                    )
                    for plugin_id, item in previous_opt_in.items()
                ):
                    raise CodingWorkerHistoryCheckpointError(
                        "coding_worker_checkpoint_opt_in_regressed"
                    )
                previous_epochs = dict(previous.supervisor_epoch_high_water)
                current_epochs = dict(record.supervisor_epoch_high_water)
                if any(
                    key not in current_epochs or current_epochs[key] < epoch
                    for key, epoch in previous_epochs.items()
                ):
                    raise CodingWorkerHistoryCheckpointError(
                        "coding_worker_checkpoint_supervisor_regressed"
                    )
            records.append(record)
    if (
        history.last_sealed_revision > len(records)
        or len(records) - history.last_sealed_revision > _MAX_ACTIVE_RECORDS
    ):
        raise CodingWorkerHistoryCheckpointError("coding_worker_checkpoint_corrupt")
    return tuple(records), history


def _candidate_for_review(
    product: PosixLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    review: CodingWorkerHistoryRetentionReviewV1,
    records: tuple[CodingWorkerHistoryCheckpointV1, ...],
) -> CodingWorkerHistoryCheckpointV1:
    if review.receipt_record is None or review.worker_backup_references is None:
        raise CodingWorkerHistoryCheckpointError(
            "coding_worker_checkpoint_closure_unproven"
        )
    seen_operations = {
        item for record in records for item in record.new_opt_in_operation_ids
    }
    seen_attempts = {item for record in records for item in record.new_attempt_ids}
    seen_receipts = {
        item for record in records for item in record.new_receipt_fingerprints
    }
    return CodingWorkerHistoryCheckpointV1.create(
        journal_revision=len(records) + 1,
        scope_id=product.policy.project_scope_id,
        store_id=product.epoch_runtime.registry.store_id,
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
def _bound_checkpoint(
    product: PosixLocalWheelProductSessionOwner,
) -> Iterator[RootedFile]:
    product.assert_root_gc_authority_current()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    root_fd = os.open(product.state_root, flags)
    try:
        opened = os.fstat(root_fd)
        visible = product.state_root.lstat()
        if (
            not stat.S_ISDIR(opened.st_mode)
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) & 0o077
            or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
        ):
            raise CodingWorkerHistoryCheckpointError(
                "coding_worker_checkpoint_root_changed"
            )
        file_io = RootedFileIO(product.state_root, root_fd)
        try:
            with file_io.bind(
                product.state_root / f"{_STEM}.jsonl", durable=True
            ) as rooted:
                yield rooted
        finally:
            file_io.cleanup()
        product.assert_root_gc_authority_current()
    finally:
        os.close(root_fd)


def read_coding_product_worker_history_checkpoints_under_gc_guard(
    product: PosixLocalWheelProductSessionOwner,
) -> tuple[CodingWorkerHistoryCheckpointV1, ...]:
    """Strictly replay Product checkpoints; this grants no pruning authority."""

    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding Worker checkpoint requires its Product")
    with _bound_checkpoint(product) as rooted:
        records, _history = _read_records(
            rooted,
            scope_id=product.policy.project_scope_id,
            store_id=product.epoch_runtime.registry.store_id,
        )
        return records


def publish_coding_product_worker_history_checkpoint(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerHistoryCheckpointV1:
    """Publish a closed Product snapshot under runtime and GC writer custody."""

    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(attempt_id) is not str
        or _ATTEMPT.fullmatch(attempt_id) is None
    ):
        raise ValueError("Coding Worker checkpoint requires one exact attempt")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        with product.gc_gate.guard(require_write=True):
            review = _review_coding_product_worker_history_under_guard(
                product,
                attempt_id=attempt_id,
                active_runtime_lease_ids=quiescence.active_runtime_lease_ids,
                gc_snapshot=product.gc_gate.snapshot(),
            )
            if (
                review.missing_proofs
                or review.receipt_record is None
                or review.worker_backup_references is None
            ):
                raise CodingWorkerHistoryCheckpointError(
                    "coding_worker_checkpoint_closure_unproven"
                )
            with _bound_checkpoint(product) as rooted:
                records, history = _read_records(
                    rooted,
                    scope_id=product.policy.project_scope_id,
                    store_id=registry.store_id,
                )
                if records:
                    prior = records[-1]
                    if (
                        prior.attempt_id == attempt_id
                        and prior.receipt_fingerprint
                        == review.receipt_record.receipt.fingerprint
                        and prior.gc_reservation_revision
                        == review.gc_reservation_revision
                        and prior.backup_topology_revision
                        == review.worker_backup_references.owner_revision
                        and prior.stream_snapshots == review.history_stream_snapshots
                        and prior.opt_in_generation_high_water
                        == review.opt_in_generation_high_water
                        and prior.supervisor_epoch_high_water
                        == review.supervisor_epoch_high_water
                    ):
                        return prior
                candidate = _candidate_for_review(
                    product,
                    attempt_id=attempt_id,
                    review=review,
                    records=records,
                )
                line = canonical_json_bytes(candidate.to_dict()) + b"\n"
                if len(line) > _MAX_RECORD_BYTES:
                    raise CodingWorkerHistoryCheckpointError(
                        "coding_worker_checkpoint_capacity"
                    )
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
                            max_segment_bytes=_MAX_SEGMENT_BYTES,
                        )
                if (
                    len(records) - history.last_sealed_revision >= _MAX_ACTIVE_RECORDS
                    or len(history.active_raw) + len(line) > _MAX_SEGMENT_BYTES
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
                        raise CodingWorkerHistoryCheckpointError(exc.code) from exc
                    generation = history.active_generation + 1
                    previous_raw = b""
                else:
                    generation = history.active_generation
                    previous_raw = history.active_raw
                target = rooted.sibling(
                    f"{_STEM}.jsonl"
                    if generation == 0
                    else f"{_STEM}.g{generation:08d}.jsonl"
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
                return candidate


def repair_coding_product_worker_history_checkpoint_append(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerHistoryCheckpointV1:
    """Commit one complete interrupted append only if its Product inputs still match."""

    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(attempt_id) is not str
        or _ATTEMPT.fullmatch(attempt_id) is None
    ):
        raise ValueError("Coding Worker checkpoint repair requires one exact attempt")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        with product.gc_gate.guard(require_write=True):
            review = _review_coding_product_worker_history_under_guard(
                product,
                attempt_id=attempt_id,
                active_runtime_lease_ids=quiescence.active_runtime_lease_ids,
                gc_snapshot=product.gc_gate.snapshot(),
            )
            if review.missing_proofs:
                raise CodingWorkerHistoryCheckpointError(
                    "coding_worker_checkpoint_closure_unproven"
                )
            with _bound_checkpoint(product) as rooted:
                pending = read_coding_worker_uncommitted_active_append(
                    rooted,
                    stem=_STEM,
                    stream_id=_STEM,
                    max_segment_bytes=_MAX_SEGMENT_BYTES,
                )
                records, history = _read_records(
                    rooted,
                    scope_id=product.policy.project_scope_id,
                    store_id=registry.store_id,
                    history=pending.committed_history,
                )
                candidate = _candidate_for_review(
                    product,
                    attempt_id=attempt_id,
                    review=review,
                    records=records,
                )
                if pending.appended_line != canonical_json_bytes(candidate.to_dict()) + b"\n":
                    raise CodingWorkerHistoryCheckpointError(
                        "coding_worker_checkpoint_repair_mismatch"
                    )
                commit_coding_worker_active_segment(
                    rooted,
                    stem=_STEM,
                    stream_id=_STEM,
                    generation=history.active_generation,
                    previous_raw=history.active_raw,
                    appended_line=pending.appended_line,
                )
                repaired, _ = _read_records(
                    rooted,
                    scope_id=product.policy.project_scope_id,
                    store_id=registry.store_id,
                )
                if repaired != (*records, candidate):
                    raise CodingWorkerHistoryCheckpointError(
                        "coding_worker_checkpoint_repair_mismatch"
                    )
                return candidate


__all__ = [
    "CodingWorkerHistoryCheckpointError",
    "CodingWorkerHistoryCheckpointV1",
    "publish_coding_product_worker_history_checkpoint",
    "read_coding_product_worker_history_checkpoints_under_gc_guard",
    "repair_coding_product_worker_history_checkpoint_append",
]
