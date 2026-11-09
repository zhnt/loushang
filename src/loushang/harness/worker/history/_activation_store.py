"""Segmented C5 storage over the existing activation engine and bound V2 reader."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import cast

from loushang.harness.journal import (
    JournalCodecError,
    JournalFormatProfile,
    JournalRecordCodec,
    append_jsonl_record,
    decode_jsonl,
)
from loushang.harness.journal._rooted_io import RootedFile

from .._segmented_history import (
    CodingWorkerHistorySegmentError,
    CodingWorkerSegmentedHistoryV1,
    append_coding_worker_active_record,
    initialize_coding_worker_active_head,
    read_coding_worker_segmented_history,
)
from ..activation_state_journal import _MAX_JOURNAL_BYTES as _MAX_BYTES
from ..activation_state_journal import _MAX_REVISIONS as _MAX_REVISIONS
from ..activation_state_journal import (
    WorkerActivationStateJournal,
    WorkerActivationStateJournalError,
    _canonical_json_bytes,
    _StateRecord,
)
from ._activation import (
    _RetainedAttemptFields,
    fold_activation_attempt_history,
    project_retained_attempts,
    validate_activation_attempt_history,
)
from ._activation_base import _ActivationReplayFields, _parse_c5_segment
from ._checkpoint import _CheckpointMethods
from ._read_v2 import RetainedHistoryReader
from ._v2_names import PRODUCT_OWNER_INDEX_NAME

_STEM = "worker-activation-state"


class SegmentedActivationJournal(WorkerActivationStateJournal):
    """Keep every CAS revision across immutable Product-owned generations."""

    def __init__(
        self,
        path: Path,
        *,
        scope_id: str | None = None,
        store_id: str | None = None,
        history_reader: RetainedHistoryReader,
    ) -> None:
        super().__init__(path)
        if (scope_id is None) != (store_id is None) or any(
            type(value) is not str or not value or len(value) > 128
            for value in (scope_id, store_id)
            if value is not None
        ):
            raise ValueError("Coding Worker C5 checkpoint owner is invalid")
        self._checkpoint_scope_id = scope_id
        self._checkpoint_store_id = store_id
        self._history_reader = history_reader

    def _acquire_journal_lock(self, rooted: RootedFile) -> None:
        if self._v2_owner_exists(rooted):
            try:
                rooted.sibling(self.path.name + ".lock").acquire_lock(
                    exclusive=True, suffix="", create=False
                )
            except FileNotFoundError as exc:
                raise WorkerActivationStateJournalError(
                    "worker_activation_state_lock_missing"
                ) from exc
            return
        created = rooted.acquire_lock(
            exclusive=True,
            suffix=".lock",
            initialize_empty_target_if_new=True,
        )
        if created:
            initialize_coding_worker_active_head(rooted, stem=_STEM, stream_id=_STEM)

    def _read_only_replacement_owner_exists(self, rooted: RootedFile) -> bool:
        return self._v2_owner_exists(rooted)

    def load(self) -> Mapping[str, object] | None:
        with self._bound_journal() as rooted:
            if self._v2_owner_exists(rooted):
                _history, replay = self._load_v2_state(rooted)
                return dict(replay.last_record.document)
            records, _history = self._load_segments(rooted)
            return None if not records else dict(records[-1].document)

    def load_read_only(self) -> Mapping[str, object] | None:
        with self._bound_journal_read_only() as rooted:
            if self._v2_owner_exists(rooted):
                _history, replay = self._load_v2_state(rooted)
                return dict(replay.last_record.document)
            records, _history = self._load_segments(rooted)
            return None if not records else dict(records[-1].document)

    def load_with_presence_read_only(
        self,
    ) -> tuple[bool, Mapping[str, object] | None]:
        """Read the latest state and durable owner presence under one lock."""

        with self._bound_journal_read_only() as rooted:
            if self._v2_owner_exists(rooted):
                _history, replay = self._load_v2_state(rooted)
                return True, dict(replay.last_record.document)
            records, _history = self._load_segments(rooted)
            try:
                rooted.stat()
            except FileNotFoundError:
                return False, None
            return True, None if not records else dict(records[-1].document)

    def initialized_read_only(self) -> bool:
        """Distinguish a durable empty history from an absent C5 owner."""

        initialized, _state = self.load_with_presence_read_only()
        return initialized

    def retained_attempts_read_only(
        self,
    ) -> tuple[_RetainedAttemptFields, ...]:
        """Inventory every C5 attempt without creating or pruning history."""

        with self._bound_journal_read_only() as rooted:
            if self._v2_owner_exists(rooted):
                history, replay = self._load_v2_state(rooted)
                try:
                    prepared = self._history_reader.preparation.read(rooted)
                    if prepared is None:
                        raise ValueError("Coding Worker V2 preparation is absent")
                    activation_base = prepared.semantic_bases[2]
                    retired_ids = frozenset(
                        prepared.semantic_bases[3].retired_attempt_ids
                    )
                    if not set(activation_base.retired_attempt_ids) <= retired_ids:
                        raise ValueError("Retired C5 attempt lacks a gate tombstone")
                    revision = activation_base.cutoff_revision
                    retained_records = [activation_base.last_record]
                    for raw in history.segments[
                        activation_base.first_retained_generation :
                    ]:
                        segment = _parse_c5_segment(raw, first_revision=revision + 1)
                        retained_records.extend(segment)
                        revision += len(segment)
                    attempts = self._project_attempts(tuple(retained_records))
                    if any(
                        item.attempt_id in retired_ids and item.phase != "settled"
                        for item in attempts
                    ):
                        raise ValueError("Retired C5 attempt is unsettled")
                    archive = prepared.no_effect_archive
                    current_attempts = cast(
                        dict[str, dict[str, object]],
                        replay.last_record.document["attempts"],
                    )
                    current_ids = {
                        cast(str, item["attemptId"])
                        for item in current_attempts.values()
                    }
                    return tuple(
                        sorted(
                            (
                                *(
                                    item
                                    for item in attempts
                                    if item.attempt_id not in retired_ids
                                ),
                                *(
                                    ()
                                    if archive is None
                                    else (
                                        replace(
                                            item.activation,
                                            current=item.attempt_id in current_ids,
                                        )
                                        for item in archive.proofs
                                    )
                                ),
                            ),
                            key=lambda item: (item.last_seen_revision, item.attempt_id),
                        )
                    )
                except (OSError, ValueError) as exc:
                    raise WorkerActivationStateJournalError(
                        "worker_activation_state_v2_inventory_corrupt"
                    ) from exc
            records, _history = self._load_segments(rooted)
            return self._project_attempts(records)

    def compare_and_swap(
        self, *, expected_revision: int, document: Mapping[str, object]
    ) -> bool:
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("Worker activation expected revision is invalid")
        record = _StateRecord.create(document)
        if record.journal_revision != expected_revision + 1:
            raise ValueError("Worker activation state revision must advance by one")
        line = _canonical_json_bytes(record.to_dict()) + b"\n"
        if len(line) > self._max_history_bytes():
            raise WorkerActivationStateJournalError("worker_activation_state_capacity")
        with self._bound_journal() as rooted:
            checkpoints = self._checkpoint_writer_fence(rooted)
            records: tuple[_StateRecord, ...]
            if self._v2_owner_exists(rooted):
                history, replay = self._load_v2_state(rooted)
                records = (replay.last_record,)
                current_revision = replay.last_record.journal_revision
                checkpoint_revision = (
                    0
                    if not checkpoints
                    else checkpoints[-1].stream_snapshots[2].total_revision
                )
                if checkpoint_revision > current_revision:
                    raise WorkerActivationStateJournalError(
                        "worker_activation_state_checkpoint_source_changed"
                    )
            else:
                records, history = self._load_segments(rooted)
                replay = None
                checkpoint_revision = self._source_revision(checkpoints, history)
                current_revision = max(
                    0 if not records else records[-1].journal_revision,
                    checkpoint_revision,
                )
            if current_revision != expected_revision:
                return False
            self._assert_checkpoint_attempts_fresh(checkpoints, records, record)
            try:
                if replay is None:
                    validate_activation_attempt_history((*records, record))
                else:
                    fold_activation_attempt_history(
                        (record,),
                        previous_record=replay.last_record,
                        retired_attempt_ids=replay.retired_attempt_ids,
                    )
            except ValueError as exc:
                raise WorkerActivationStateJournalError(
                    "worker_activation_state_history_conflict"
                ) from exc
            active_records = current_revision - history.last_sealed_revision

            def append(name: str) -> None:
                append_jsonl_record(
                    self.path,
                    record,
                    record_codec=self._record_codec,
                    format_profile=self._record_format,
                    durability=self._durability,
                    bound_file=rooted.sibling(name),
                )

            append_coding_worker_active_record(
                rooted,
                stem=_STEM,
                stream_id=_STEM,
                history=history,
                last_revision=current_revision,
                line=line,
                seal_required=active_records >= self._max_history_records()
                or len(history.active_raw) + len(line) > self._max_history_bytes(),
                seal_error=lambda exc: WorkerActivationStateJournalError(
                    "worker_activation_state_capacity"
                    if exc.code == "coding_worker_segment_capacity"
                    else "worker_activation_state_corrupt"
                ),
                append=append,
            )
            return True

    _v2_owner_exists = staticmethod(RetainedHistoryReader.owner_exists)

    def _load_v2_state(
        self, rooted: RootedFile
    ) -> tuple[CodingWorkerSegmentedHistoryV1, _ActivationReplayFields]:
        """Read typed C5 state while its retired source generation may be absent."""

        try:
            owner = (
                self._history_reader.preparation.prepared_type._index_type.from_bytes(
                    rooted.sibling(PRODUCT_OWNER_INDEX_NAME).read_bytes(max_bytes=4096)
                )
            )
            if (
                self._checkpoint_scope_id is not None
                and self._checkpoint_scope_id != owner.scope_id
            ) or (
                self._checkpoint_store_id is not None
                and self._checkpoint_store_id != owner.store_id
            ):
                raise WorkerActivationStateJournalError(
                    "worker_activation_state_v2_owner_changed"
                )
            retained = self._history_reader.read(rooted, stem=_STEM)
            replay = retained.replay
            if not isinstance(
                replay,
                self._history_reader.preparation.prepared_type._activation_type._replay_type,
            ):
                raise WorkerActivationStateJournalError(
                    "worker_activation_state_v2_owner_changed"
                )
            return (
                self._history_reader.history_from_retained(
                    rooted,
                    retained,
                    stem=_STEM,
                    manifest_changed=lambda: WorkerActivationStateJournalError(
                        "worker_activation_state_v2_manifest_changed"
                    ),
                ),
                cast(_ActivationReplayFields, replay),
            )
        except (
            self._history_reader.error_type,
            CodingWorkerHistorySegmentError,
        ) as exc:
            raise WorkerActivationStateJournalError(
                "worker_activation_state_corrupt"
            ) from exc
        except (OSError, ValueError) as exc:
            raise WorkerActivationStateJournalError(
                "worker_activation_state_corrupt"
            ) from exc

    def _checkpoint_writer_fence(
        self, rooted: RootedFile
    ) -> tuple[_CheckpointMethods, ...]:
        if self._checkpoint_scope_id is None or self._checkpoint_store_id is None:
            self._history_reader.checkpoints.require_unowned_absence(
                rooted,
                error_type=WorkerActivationStateJournalError,
                code="worker_activation_state_checkpoint_owner_required",
            )
            return ()
        with self._history_reader.checkpoints.translated_errors(
            WorkerActivationStateJournalError
        ):
            return self._history_reader.checkpoints.read_writer_fence(
                rooted,
                scope_id=self._checkpoint_scope_id,
                store_id=self._checkpoint_store_id,
            )

    def _source_revision(
        self,
        checkpoints: tuple[_CheckpointMethods, ...],
        history: CodingWorkerSegmentedHistoryV1,
    ) -> int:
        return self._history_reader.checkpoints.verify_source_revision(
            checkpoints,
            history,
            stream_index=2,
            error_type=WorkerActivationStateJournalError,
            code="worker_activation_state_checkpoint_source_changed",
        )

    @staticmethod
    def _assert_checkpoint_attempts_fresh(
        checkpoints: tuple[_CheckpointMethods, ...],
        records: tuple[_StateRecord, ...],
        candidate: _StateRecord,
    ) -> None:
        if not checkpoints:
            return
        prior = (
            {}
            if not records
            else cast(dict[str, dict[str, object]], records[-1].document["attempts"])
        )
        retained_ids = {cast(str, attempt["attemptId"]) for attempt in prior.values()}
        candidate_attempts = cast(
            dict[str, dict[str, object]], candidate.document["attempts"]
        )
        retired_ids = {
            attempt_id
            for checkpoint in checkpoints
            for attempt_id in checkpoint.new_attempt_ids
        }
        if any(
            cast(str, attempt["attemptId"]) in retired_ids
            for attempt in candidate_attempts.values()
            if cast(str, attempt["attemptId"]) not in retained_ids
        ):
            raise WorkerActivationStateJournalError(
                "worker_activation_state_attempt_retired"
            )

    def _load_segments(
        self, rooted: RootedFile
    ) -> tuple[tuple[_StateRecord, ...], CodingWorkerSegmentedHistoryV1]:
        try:
            history = read_coding_worker_segmented_history(
                rooted,
                stem=_STEM,
                stream_id=_STEM,
                max_segment_bytes=self._max_history_bytes(),
            )
            records: list[_StateRecord] = []
            for generation, raw in enumerate(history.segments):
                segment = decode_jsonl(
                    raw.decode("utf-8"),
                    target=self.path,
                    record_codec=self._record_codec,
                    load_policy=self._load_policy,
                ).records
                lines = raw.splitlines(keepends=True)
                if (
                    len(segment) > self._max_history_records()
                    or len(segment) != len(lines)
                    or any(
                        record.journal_revision != revision
                        or line != _canonical_json_bytes(record.to_dict()) + b"\n"
                        for revision, (record, line) in enumerate(
                            zip(segment, lines, strict=True), len(records) + 1
                        )
                    )
                ):
                    raise ValueError("Worker activation state segment changed")
                records.extend(segment)
                if (
                    history.manifest is not None
                    and generation < history.active_generation
                    and len(records)
                    != history.manifest.sealed[generation].last_revision
                ):
                    raise ValueError("Worker activation state sealed revision changed")
            result = tuple(records)
            validate_activation_attempt_history(result)
            return result, history
        except (
            CodingWorkerHistorySegmentError,
            JournalCodecError,
            OSError,
            RecursionError,
            TypeError,
            UnicodeError,
            ValueError,
        ) as exc:
            raise WorkerActivationStateJournalError(
                "worker_activation_state_corrupt"
            ) from exc

    def _project_attempts(
        self, records: tuple[_StateRecord, ...]
    ) -> tuple[_RetainedAttemptFields, ...]:
        return project_retained_attempts(
            records,
            record_type=self._history_reader.preparation.prepared_type._retained_type,
        )

    @property
    def _record_codec(self) -> JournalRecordCodec[_StateRecord]:
        raise NotImplementedError("the original value codec is required")

    @property
    def _record_format(self) -> JournalFormatProfile:
        raise NotImplementedError("the original format is required")

    def _max_history_bytes(self) -> int:
        return _MAX_BYTES

    def _max_history_records(self) -> int:
        return _MAX_REVISIONS
