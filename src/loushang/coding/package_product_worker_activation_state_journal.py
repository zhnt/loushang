"""Segmented Product custody for the durable C5 Worker activation state."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, cast

from loushang.harness.journal import (
    JournalCodecError,
    append_jsonl_record,
    decode_jsonl,
)
from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.worker.activation_state_journal import (
    _CODEC,
    _FORMAT,
    WorkerActivationStateJournal,
    WorkerActivationStateJournalError,
    _canonical_json_bytes,
    _StateRecord,
)
from loushang.harness.worker.activation_state_journal import (
    _MAX_JOURNAL_BYTES as _DEFAULT_MAX_BYTES,
)
from loushang.harness.worker.activation_state_journal import (
    _MAX_REVISIONS as _DEFAULT_MAX_REVISIONS,
)

from .package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
    _fold_coding_worker_activation_attempt_history,
    project_coding_worker_retained_attempts,
    validate_coding_worker_activation_attempt_history,
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
    from .package_product_worker_activation_base_v2 import (
        CodingWorkerActivationReplayV2,
    )
    from .package_product_worker_history_checkpoint import (
        CodingWorkerHistoryCheckpointV1,
    )

_STEM = "worker-activation-state"
_MAX_REVISIONS = _DEFAULT_MAX_REVISIONS
_MAX_BYTES = _DEFAULT_MAX_BYTES


class CodingProductWorkerActivationStateJournal(WorkerActivationStateJournal):
    """Keep every CAS revision across immutable Product-owned generations."""

    def __init__(
        self,
        path: Path,
        *,
        scope_id: str | None = None,
        store_id: str | None = None,
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
    ) -> tuple[CodingProductWorkerRetainedAttemptV1, ...]:
        """Inventory every C5 attempt without creating or pruning history."""

        with self._bound_journal_read_only() as rooted:
            if self._v2_owner_exists(rooted):
                from .package_product_worker_activation_base_v2 import (
                    _parse_c5_segment,
                )
                from .package_product_worker_history_stage_v2 import (
                    read_coding_worker_v2_preparation,
                )

                history, _replay = self._load_v2_state(rooted)
                try:
                    prepared = read_coding_worker_v2_preparation(rooted)
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
                    attempts = project_coding_worker_retained_attempts(
                        tuple(retained_records)
                    )
                    if any(
                        item.attempt_id in retired_ids and item.phase != "settled"
                        for item in attempts
                    ):
                        raise ValueError("Retired C5 attempt is unsettled")
                    return tuple(
                        item
                        for item in attempts
                        if item.attempt_id not in retired_ids
                    )
                except (OSError, ValueError) as exc:
                    raise WorkerActivationStateJournalError(
                        "worker_activation_state_v2_inventory_corrupt"
                    ) from exc
            records, _history = self._load_segments(rooted)
            return project_coding_worker_retained_attempts(records)

    def compare_and_swap(
        self, *, expected_revision: int, document: Mapping[str, object]
    ) -> bool:
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("Worker activation expected revision is invalid")
        record = _StateRecord.create(document)
        if record.journal_revision != expected_revision + 1:
            raise ValueError("Worker activation state revision must advance by one")
        line = _canonical_json_bytes(record.to_dict()) + b"\n"
        if len(line) > _MAX_BYTES:
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
                checkpoint_revision = self._assert_checkpoint_source(
                    checkpoints, history
                )
                current_revision = max(
                    0 if not records else records[-1].journal_revision,
                    checkpoint_revision,
                )
            if current_revision != expected_revision:
                return False
            self._assert_checkpoint_attempts_fresh(checkpoints, records, record)
            try:
                if replay is None:
                    validate_coding_worker_activation_attempt_history(
                        (*records, record)
                    )
                else:
                    _fold_coding_worker_activation_attempt_history(
                        (record,),
                        previous_record=replay.last_record,
                        retired_attempt_ids=replay.retired_attempt_ids,
                    )
            except ValueError as exc:
                raise WorkerActivationStateJournalError(
                    "worker_activation_state_history_conflict"
                ) from exc
            active_records = current_revision - history.last_sealed_revision
            if (
                active_records >= _MAX_REVISIONS
                or len(history.active_raw) + len(line) > _MAX_BYTES
            ):
                try:
                    seal_coding_worker_active_segment(
                        rooted,
                        stem=_STEM,
                        stream_id=_STEM,
                        history=history,
                        last_revision=current_revision,
                    )
                except CodingWorkerHistorySegmentError as exc:
                    raise WorkerActivationStateJournalError(
                        "worker_activation_state_capacity"
                        if exc.code == "coding_worker_segment_capacity"
                        else "worker_activation_state_corrupt"
                    ) from exc
                generation = history.active_generation + 1
            else:
                generation = history.active_generation
            name = (
                f"{_STEM}.jsonl"
                if generation == 0
                else f"{_STEM}.g{generation:08d}.jsonl"
            )
            append_jsonl_record(
                self.path,
                record,
                record_codec=_CODEC,
                format_profile=_FORMAT,
                durability=self._durability,
                bound_file=rooted.sibling(name),
            )
            commit_coding_worker_active_segment(
                rooted,
                stem=_STEM,
                stream_id=_STEM,
                generation=generation,
                previous_raw=(
                    b""
                    if generation != history.active_generation
                    else history.active_raw
                ),
                appended_line=line,
            )
            return True

    @staticmethod
    def _v2_owner_exists(rooted: RootedFile) -> bool:
        try:
            rooted.sibling(PRODUCT_OWNER_INDEX_NAME).stat()
        except FileNotFoundError:
            return False
        return True

    def _load_v2_state(
        self, rooted: RootedFile
    ) -> tuple[CodingWorkerSegmentedHistoryV1, CodingWorkerActivationReplayV2]:
        """Read typed C5 state while its retired source generation may be absent."""

        from .package_product_worker_activation_base_v2 import (
            CodingWorkerActivationReplayV2,
        )
        from .package_product_worker_history_cutover_v2 import (
            CodingWorkerProductCutoverIndexV2,
        )
        from .package_product_worker_history_read_v2 import (
            CodingWorkerV2ReadError,
            read_coding_worker_v2_retained_history,
        )

        try:
            owner = CodingWorkerProductCutoverIndexV2.from_bytes(
                rooted.sibling(PRODUCT_OWNER_INDEX_NAME).read_bytes(max_bytes=4096)
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
            retained = read_coding_worker_v2_retained_history(rooted, stem=_STEM)
            replay = retained.replay
            if not isinstance(replay, CodingWorkerActivationReplayV2):
                raise WorkerActivationStateJournalError(
                    "worker_activation_state_v2_owner_changed"
                )
            manifest = CodingWorkerSegmentManifestV1.from_bytes(
                rooted.sibling(_STEM + ".segments.json").read_bytes(
                    max_bytes=1024 * 1024
                ),
                stream_id=_STEM,
            )
            if manifest.active_generation != retained.active_generation:
                raise WorkerActivationStateJournalError(
                    "worker_activation_state_v2_manifest_changed"
                )
            return (
                CodingWorkerSegmentedHistoryV1(
                    manifest=manifest,
                    segments=(b"",) * retained.first_retained_generation
                    + retained.segments,
                ),
                replay,
            )
        except (CodingWorkerV2ReadError, CodingWorkerHistorySegmentError) as exc:
            raise WorkerActivationStateJournalError(
                "worker_activation_state_corrupt"
            ) from exc
        except (OSError, ValueError) as exc:
            raise WorkerActivationStateJournalError(
                "worker_activation_state_corrupt"
            ) from exc

    def _checkpoint_writer_fence(
        self, rooted: RootedFile
    ) -> tuple[CodingWorkerHistoryCheckpointV1, ...]:
        from .package_product_worker_history_checkpoint import (
            CodingWorkerHistoryCheckpointError,
            read_coding_worker_checkpoint_writer_fence,
        )
        from .package_product_worker_history_checkpoint_anchor import (
            ANCHOR_NAME,
            CodingWorkerCheckpointAnchorError,
        )

        if self._checkpoint_scope_id is None or self._checkpoint_store_id is None:
            for name in (
                ANCHOR_NAME,
                "worker-history-checkpoints.jsonl",
                "worker-history-checkpoints.jsonl.lock",
                "worker-history-checkpoints.head.json",
                "worker-history-checkpoints.segments.json",
            ):
                try:
                    rooted.sibling(name).stat()
                except FileNotFoundError:
                    continue
                raise WorkerActivationStateJournalError(
                    "worker_activation_state_checkpoint_owner_required"
                ) from None
            return ()
        try:
            return read_coding_worker_checkpoint_writer_fence(
                rooted,
                scope_id=self._checkpoint_scope_id,
                store_id=self._checkpoint_store_id,
            )
        except (
            CodingWorkerHistoryCheckpointError,
            CodingWorkerCheckpointAnchorError,
            CodingWorkerHistorySegmentError,
        ) as exc:
            raise WorkerActivationStateJournalError(exc.code) from exc

    @staticmethod
    def _assert_checkpoint_source(
        checkpoints: tuple[CodingWorkerHistoryCheckpointV1, ...],
        history: CodingWorkerSegmentedHistoryV1,
    ) -> int:
        if not checkpoints:
            return 0
        prior = checkpoints[-1].stream_snapshots[2]
        current = CodingWorkerHistoryStreamSnapshotV1.capture(
            stem=_STEM,
            active_generation=history.active_generation,
            last_sealed_revision=history.last_sealed_revision,
            segments=history.segments,
        )
        if not prior.is_exact_prefix_of(current, current_segments=history.segments):
            raise WorkerActivationStateJournalError(
                "worker_activation_state_checkpoint_source_changed"
            )
        return prior.total_revision

    @staticmethod
    def _assert_checkpoint_attempts_fresh(
        checkpoints: tuple[CodingWorkerHistoryCheckpointV1, ...],
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
                max_segment_bytes=_MAX_BYTES,
            )
            records: list[_StateRecord] = []
            for generation, raw in enumerate(history.segments):
                segment = decode_jsonl(
                    raw.decode("utf-8"),
                    target=self.path,
                    record_codec=_CODEC,
                    load_policy=self._load_policy,
                ).records
                lines = raw.splitlines(keepends=True)
                if (
                    len(segment) > _MAX_REVISIONS
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
            validate_coding_worker_activation_attempt_history(result)
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


__all__ = [
    "CodingProductWorkerActivationStateJournal",
    "CodingProductWorkerRetainedAttemptV1",
]
