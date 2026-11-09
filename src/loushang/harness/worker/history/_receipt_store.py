"""Receipt history under existing custody, without issuing Product authority."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Generic, TypeVar, cast

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    JournalFormatProfile,
    JournalLoadPolicy,
    JournalRecordCodec,
    append_jsonl_record,
)
from loushang.harness.journal._rooted_io import RootedFile, bind_private_journal

from .._segmented_history import (
    CodingWorkerHistorySegmentError,
    CodingWorkerSegmentedHistoryV1,
    append_coding_worker_active_record,
    initialize_coding_worker_active_head,
    read_coding_worker_segmented_history,
)
from ..product_activation import ProductWorkerActivationReceiptV1
from ._checkpoint import _CheckpointMethods
from ._checkpoint_history import _CodedFailure
from ._opt_in import _OptInDecisionMethods
from ._read_v2 import RetainedHistoryReader
from ._receipts import (
    _MAX_RECEIPT_SEGMENT_BYTES,
    _MAX_RECEIPTS,
    _ReceiptRecordMethods,
    _ReceiptReplayFields,
    decode_receipt_history,
    receipt_line,
)
from ._rooted_supervisor import WorkerHistoryAccess
from ._v2_names import PRODUCT_OWNER_INDEX_NAME

_RecordT = TypeVar("_RecordT", bound=_ReceiptRecordMethods)


@dataclass(frozen=True, slots=True)
class _ReceiptAppendPosition(Generic[_RecordT]):
    rooted: RootedFile
    history: CodingWorkerSegmentedHistoryV1
    checkpoints: tuple[_CheckpointMethods, ...]
    records: tuple[_RecordT, ...]
    replay: _ReceiptReplayFields | None
    last_revision: int
    checkpoint_revision: int


def assert_checkpoint_fingerprint_fresh(
    checkpoints: tuple[_CheckpointMethods, ...],
    fingerprint: str,
    *,
    error_type: type[RuntimeError],
) -> None:
    if any(fingerprint in item.new_receipt_fingerprints for item in checkpoints):
        raise error_type("coding_worker_receipt_fingerprint_retired")


class ReceiptHistory(Generic[_RecordT]):
    """Bound history mechanics, composed inside the caller's admission scope."""

    def __init__(
        self,
        path: Path,
        *,
        access: WorkerHistoryAccess,
        history_reader: RetainedHistoryReader,
        error_type: type[RuntimeError],
    ) -> None:
        self._path = path
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="raise", create_lock=False)
        self._access = access
        self._history_reader = history_reader
        self._error_type = error_type

    @property
    def path(self) -> Path:
        return self._path

    @property
    def _record_type(self) -> type[_RecordT]:
        raise NotImplementedError("the original value type is required")

    @property
    def _record_codec(self) -> JournalRecordCodec[_RecordT]:
        raise NotImplementedError("the original value codec is required")

    @property
    def _record_format(self) -> JournalFormatProfile:
        raise NotImplementedError("the original format is required")

    def _max_history_bytes(self) -> int:
        return _MAX_RECEIPT_SEGMENT_BYTES

    def _max_history_records(self) -> int:
        return _MAX_RECEIPTS

    @contextmanager
    def _append_position(self) -> Iterator[_ReceiptAppendPosition[_RecordT]]:
        with self._bound_journal() as rooted:
            checkpoints = self._checkpoint_writer_fence(rooted)
            if self._v2_owner_exists(rooted):
                history, replay = self._read_v2_state(
                    rooted,
                    scope_id=self._access.scope_id,
                    store_id=self._access.store_id,
                )
                records = cast(tuple[_RecordT, ...], replay.retained_records)
                last_revision = replay.last_issue_sequence
                checkpoint_revision = (
                    0
                    if not checkpoints
                    else checkpoints[-1].stream_snapshots[1].total_revision
                )
                if checkpoint_revision > last_revision:
                    raise self._error_type(
                        "coding_worker_receipt_checkpoint_source_changed"
                    )
            else:
                records, history = self._read_history(
                    rooted,
                    path=self._path,
                    scope_id=self._access.scope_id,
                    load_policy=self._load_policy,
                )
                replay = None
                last_revision = 0 if not records else records[-1].journal_revision
                checkpoint_revision = (
                    self._history_reader.checkpoints.verify_source_revision(
                        checkpoints,
                        history,
                        stream_index=1,
                        error_type=self._error_type,
                        code="coding_worker_receipt_checkpoint_source_changed",
                    )
                )
            yield _ReceiptAppendPosition(
                rooted,
                history,
                checkpoints,
                records,
                replay,
                last_revision,
                checkpoint_revision,
            )

    def _append_record(
        self,
        position: _ReceiptAppendPosition[_RecordT],
        *,
        next_revision: int,
        receipt: ProductWorkerActivationReceiptV1,
        decision: _OptInDecisionMethods,
    ) -> _RecordT:
        rooted = position.rooted
        history = position.history
        checkpoints = position.checkpoints
        replay = position.replay
        last_revision = position.last_revision
        assert_checkpoint_fingerprint_fresh(
            checkpoints, receipt.fingerprint, error_type=self._error_type
        )
        if replay is not None and receipt.fingerprint in replay.receipt_fingerprints:
            raise self._error_type("coding_worker_receipt_fingerprint_retired")
        record = self._record_type.create(
            journal_revision=next_revision,
            scope_id=self._access.scope_id,
            opt_in_decision_digest=decision.decision_digest,
            receipt=receipt,
        )
        record_bytes = receipt_line(record)
        if len(record_bytes) > self._max_history_bytes():
            raise self._error_type("coding_worker_receipt_capacity")

        def append(name: str) -> None:
            target = rooted.sibling(name)
            append_jsonl_record(
                self._path,
                record,
                record_codec=self._record_codec,
                format_profile=self._record_format,
                durability=self._durability,
                bound_file=target,
            )

        append_coding_worker_active_record(
            rooted,
            stem="worker-activation-receipts",
            stream_id="worker-activation-receipts",
            history=history,
            last_revision=last_revision,
            line=record_bytes,
            seal_required=last_revision - history.last_sealed_revision
            >= self._max_history_records()
            or len(history.active_raw) + len(record_bytes) > self._max_history_bytes(),
            seal_error=lambda exc: self._error_type(cast(_CodedFailure, exc).code),
            append=append,
            base_name=self._path.name,
        )
        return record

    def _checkpoint_writer_fence(
        self, rooted: RootedFile
    ) -> tuple[_CheckpointMethods, ...]:
        with self._history_reader.checkpoints.translated_errors(self._error_type):
            return self._history_reader.checkpoints.read_writer_fence(
                rooted,
                scope_id=self._access.scope_id,
                store_id=self._access.store_id,
            )

    @contextmanager
    def _bound_journal(self) -> Iterator[RootedFile]:
        with bind_private_journal(
            self._path,
            error_type=self._error_type,
            label="coding_worker_receipt_state_root",
            durable=True,
        ) as rooted:
            if self._v2_owner_exists(rooted):
                try:
                    rooted.sibling(self._path.name + ".lock").acquire_lock(
                        exclusive=True, suffix="", create=False
                    )
                except FileNotFoundError as exc:
                    raise self._error_type(
                        "coding_worker_receipt_lock_missing"
                    ) from exc
            else:
                created = rooted.acquire_lock(
                    exclusive=True,
                    suffix=".lock",
                    initialize_empty_target_if_new=True,
                )
                if created:
                    initialize_coding_worker_active_head(
                        rooted,
                        stem="worker-activation-receipts",
                        stream_id="worker-activation-receipts",
                    )
            yield rooted

    def _load(self, rooted: RootedFile) -> tuple[_RecordT, ...]:
        if self._v2_owner_exists(rooted):
            _history, replay = self._read_v2_state(
                rooted,
                scope_id=self._access.scope_id,
                store_id=self._access.store_id,
            )
            return cast(tuple[_RecordT, ...], replay.retained_records)
        return self._records_from(
            rooted,
            path=self._path,
            scope_id=self._access.scope_id,
            load_policy=self._load_policy,
        )

    def read_records(self, *, retained_only: bool = False) -> tuple[_RecordT, ...]:
        with self._access.guard(require_write=False):
            self._access.assert_current()
            with bind_private_journal(
                self._path,
                error_type=self._error_type,
                label="coding_worker_receipt_state_root",
                durable=False,
            ) as rooted:
                if self._v2_owner_exists(rooted):
                    if not retained_only:
                        raise self._error_type(
                            "coding_worker_receipt_v2_full_history_unavailable"
                        )
                    _history, replay = self._read_v2_state(
                        rooted,
                        scope_id=self._access.scope_id,
                        store_id=self._access.store_id,
                    )
                    prepared = self._history_reader.preparation.read(rooted)
                    if prepared is None:
                        raise self._error_type(
                            "coding_worker_receipt_v2_preparation_absent"
                        )
                    archive = prepared.no_effect_archive
                    records = cast(
                        tuple[_RecordT, ...],
                        tuple(
                            sorted(
                                (
                                    *replay.retained_records,
                                    *(
                                        ()
                                        if archive is None
                                        else (item.receipt for item in archive.proofs)
                                    ),
                                ),
                                key=lambda item: item.journal_revision,
                            )
                        ),
                    )
                else:
                    records = self._records_from(
                        rooted,
                        path=self._path,
                        scope_id=self._access.scope_id,
                        load_policy=JournalLoadPolicy(
                            partial_tail="raise", create_lock=False
                        ),
                    )
            return records

    _v2_owner_exists = staticmethod(RetainedHistoryReader.owner_exists)

    def _read_v2_state(
        self, rooted: RootedFile, *, scope_id: str, store_id: str
    ) -> tuple[CodingWorkerSegmentedHistoryV1, _ReceiptReplayFields]:
        """Verify the V2 owner and reconstruct only retained receipt generations."""

        stem = "worker-activation-receipts"
        try:
            owner = (
                self._history_reader.preparation.prepared_type._index_type.from_bytes(
                    rooted.sibling(PRODUCT_OWNER_INDEX_NAME).read_bytes(max_bytes=4096)
                )
            )
            if owner.scope_id != scope_id or owner.store_id != store_id:
                raise self._error_type("coding_worker_receipt_v2_owner_changed")
            retained = self._history_reader.read(rooted, stem=stem)
            replay = retained.replay
            if not isinstance(
                replay,
                self._history_reader.preparation.prepared_type._receipt_type._replay_type,
            ):
                raise self._error_type("coding_worker_receipt_v2_owner_changed")
            return (
                self._history_reader.history_from_retained(
                    rooted,
                    retained,
                    stem=stem,
                    manifest_changed=lambda: self._error_type(
                        "coding_worker_receipt_v2_manifest_changed"
                    ),
                ),
                cast(_ReceiptReplayFields, replay),
            )
        except (
            self._history_reader.error_type,
            CodingWorkerHistorySegmentError,
        ) as exc:
            raise self._error_type(cast(_CodedFailure, exc).code) from exc
        except (OSError, ValueError) as exc:
            raise self._error_type("coding_worker_receipt_v2_corrupt") from exc

    def _records_from(
        self,
        rooted: RootedFile,
        *,
        path: Path,
        scope_id: str,
        load_policy: JournalLoadPolicy,
    ) -> tuple[_RecordT, ...]:
        records, _history = self._read_history(
            rooted,
            path=path,
            scope_id=scope_id,
            load_policy=load_policy,
        )
        return records

    def _read_history(
        self,
        rooted: RootedFile,
        *,
        path: Path,
        scope_id: str,
        load_policy: JournalLoadPolicy,
    ) -> tuple[tuple[_RecordT, ...], CodingWorkerSegmentedHistoryV1]:
        try:
            history = read_coding_worker_segmented_history(
                rooted,
                stem="worker-activation-receipts",
                stream_id="worker-activation-receipts",
                max_segment_bytes=self._max_history_bytes(),
            )
        except CodingWorkerHistorySegmentError as exc:
            raise self._error_type(cast(_CodedFailure, exc).code) from exc
        records: list[_RecordT] = []
        seen_receipts: set[str] = set()
        for generation, raw in enumerate(history.segments):
            segment_records = decode_receipt_history(
                raw,
                path=path,
                scope_id=scope_id,
                load_policy=load_policy,
                first_revision=len(records) + 1,
                record_codec=self._record_codec,
                error_type=self._error_type,
                max_receipts=self._max_history_records(),
                max_segment_bytes=self._max_history_bytes(),
            )
            lines = raw.splitlines(keepends=True)
            if len(lines) != len(segment_records) or any(
                line != receipt_line(record)
                for record, line in zip(segment_records, lines, strict=True)
            ):
                raise self._error_type("coding_worker_receipt_corrupt")
            for record in segment_records:
                if record.receipt.fingerprint in seen_receipts:
                    raise self._error_type("coding_worker_receipt_corrupt")
                seen_receipts.add(record.receipt.fingerprint)
            records.extend(segment_records)
            if (
                history.manifest is not None
                and generation < history.active_generation
                and len(records) != history.manifest.sealed[generation].last_revision
            ):
                raise self._error_type("coding_worker_receipt_corrupt")
        return tuple(records), history
