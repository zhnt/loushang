"""Start-gate queries and physical history under existing Product custody."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Generic, Literal, TypeVar, cast

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    JournalCodecError,
    JournalFormatProfile,
    JournalLoadPolicy,
    JournalRecordCodec,
    append_jsonl_record,
    decode_jsonl,
)
from loushang.harness.journal._rooted_io import RootedFile, bind_private_journal
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .._segmented_history import (
    CodingWorkerHistorySegmentError,
    CodingWorkerSegmentedHistoryV1,
    append_coding_worker_active_record,
    initialize_coding_worker_active_head,
    read_coding_worker_segmented_history,
)
from ..gated_start import WorkerNativeProcessIdentityV1
from ._checkpoint import _CheckpointMethods
from ._checkpoint_history import _CodedFailure
from ._read_v2 import RetainedHistoryReader
from ._rooted_supervisor import WorkerHistoryAccess
from ._start_gate import (
    _ATTEMPT,
    _MAX_BYTES,
    _MAX_EVENTS,
    _StartGateRecordMethods,
    _StartGateReplayFields,
    fold_start_gate_records,
)
from ._v2_names import PRODUCT_OWNER_INDEX_NAME

_RecordT = TypeVar("_RecordT", bound=_StartGateRecordMethods)


@dataclass(frozen=True, slots=True)
class _GateAppendPosition:
    rooted: RootedFile
    history: CodingWorkerSegmentedHistoryV1
    last_revision: int
    checkpoint_revision: int
    has_records: bool


def assert_checkpoint_attempt_available(
    checkpoints: tuple[_CheckpointMethods, ...],
    attempt_id: str,
    *,
    error_type: type[RuntimeError],
) -> None:
    if any(attempt_id in item.new_attempt_ids for item in checkpoints):
        raise error_type("coding_worker_start_gate_attempt_retired")


class StartGateHistory(Generic[_RecordT]):
    """Read and bind the same gate stream; admission remains with its caller."""

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
    def _record_codec(self) -> JournalRecordCodec[_RecordT]:
        raise NotImplementedError("the original value codec is required")

    def _max_history_bytes(self) -> int:
        return _MAX_BYTES

    def _max_history_records(self) -> int:
        return _MAX_EVENTS

    @property
    def _record_type(self) -> type[_RecordT]:
        raise NotImplementedError("the original value type is required")

    @property
    def _record_format(self) -> JournalFormatProfile:
        raise NotImplementedError("the original format is required")

    @contextmanager
    def _append_position(
        self,
        *,
        phase: Literal["intent", "bound"],
        attempt_id: str,
        worker_identity_fingerprint: str,
        receipt_fingerprint: str,
        policy_fingerprint: str,
        scope_id: str,
        native_closure_digest: str,
    ) -> Iterator[_GateAppendPosition]:
        with self._access.guard(require_write=True):
            self._access.assert_current()
            with self._bound_journal() as rooted:
                checkpoints = self._checkpoint_writer_fence(rooted)
                if self._v2_owner_exists(rooted):
                    history, replay = self._load_v2_state(rooted)
                    records = cast(tuple[_RecordT, ...], replay.current_records)
                    last_revision = replay.last_revision
                    checkpoint_revision = (
                        0
                        if not checkpoints
                        else checkpoints[-1].stream_snapshots[3].total_revision
                    )
                    if checkpoint_revision > last_revision:
                        raise self._error_type(
                            "coding_worker_start_gate_checkpoint_source_changed"
                        )
                    if attempt_id in replay.retired_attempt_ids:
                        raise self._error_type(
                            "coding_worker_start_gate_attempt_retired"
                        )
                else:
                    records, history = self._load_history(rooted)
                    checkpoint_revision = (
                        self._history_reader.checkpoints.verify_source_revision(
                            checkpoints,
                            history,
                            stream_index=3,
                            error_type=self._error_type,
                            code="coding_worker_start_gate_checkpoint_source_changed",
                        )
                    )
                    last_revision = 0 if not records else records[-1].journal_revision
                assert_checkpoint_attempt_available(
                    checkpoints, attempt_id, error_type=self._error_type
                )
                previous = next(
                    (
                        record
                        for record in reversed(records)
                        if record.attempt_id == attempt_id
                    ),
                    None,
                )
                if (phase == "intent" and previous is not None) or (
                    phase == "bound"
                    and (previous is None or previous.phase != "intent")
                ):
                    raise self._error_type("coding_worker_start_gate_attempt_conflict")
                if previous is not None and (
                    previous.receipt_fingerprint != receipt_fingerprint
                    or previous.worker_identity_fingerprint
                    != worker_identity_fingerprint
                    or previous.policy_fingerprint != policy_fingerprint
                    or previous.scope_id != scope_id
                    or previous.native_closure_digest != native_closure_digest
                ):
                    raise self._error_type("coding_worker_start_gate_binding_changed")
                yield _GateAppendPosition(
                    rooted, history, last_revision, checkpoint_revision, bool(records)
                )

    def _append_record(
        self,
        position: _GateAppendPosition,
        *,
        phase: Literal["intent", "bound"],
        attempt_id: str,
        worker_identity_fingerprint: str,
        receipt_fingerprint: str,
        policy_fingerprint: str,
        scope_id: str,
        native_closure_digest: str,
        identity: WorkerNativeProcessIdentityV1 | None = None,
    ) -> _RecordT:
        rooted = position.rooted
        history = position.history
        last_revision = position.last_revision
        checkpoint_revision = position.checkpoint_revision
        next_revision = max(last_revision, checkpoint_revision) + 1
        record = self._record_type.create(
            journal_revision=next_revision,
            phase=phase,
            attempt_id=attempt_id,
            worker_identity_fingerprint=worker_identity_fingerprint,
            receipt_fingerprint=receipt_fingerprint,
            policy_fingerprint=policy_fingerprint,
            scope_id=scope_id,
            native_closure_digest=native_closure_digest,
            identity=identity,
        )
        active_records = last_revision - history.last_sealed_revision
        record_bytes = canonical_json_bytes(record.to_dict()) + b"\n"
        if len(record_bytes) > self._max_history_bytes():
            raise self._error_type("coding_worker_start_gate_capacity")

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
            stem="worker-start-gates",
            stream_id="worker-start-gates",
            history=history,
            last_revision=last_revision,
            line=record_bytes,
            seal_required=active_records >= self._max_history_records()
            or len(history.active_raw) + len(record_bytes) > self._max_history_bytes(),
            seal_error=lambda exc: self._error_type(exc.code),
            append=append,
            base_name=self._path.name,
        )
        return record

    def current(self, attempt_id: str) -> _RecordT | None:
        if type(attempt_id) is not str or _ATTEMPT.fullmatch(attempt_id) is None:
            raise ValueError("Worker gate attempt ID is invalid")
        with self._access.guard(require_write=False):
            self._access.assert_current()
            with self._bound_journal(create_lock=False) as rooted:
                if self._v2_owner_exists(rooted):
                    _history, replay = self._load_v2_state(rooted)
                    prepared = self._history_reader.preparation.read(rooted)
                    if prepared is None:
                        raise self._error_type(
                            "coding_worker_gate_v2_preparation_absent"
                        )
                    archive = prepared.no_effect_archive
                    records = cast(
                        tuple[_RecordT, ...],
                        (
                            *replay.current_records,
                            *(
                                ()
                                if archive is None
                                else (item.gate for item in archive.proofs)
                            ),
                        ),
                    )
                else:
                    records = self._load(rooted)
                return next(
                    (
                        record
                        for record in reversed(records)
                        if record.attempt_id == attempt_id
                    ),
                    None,
                )

    def attempts(self) -> tuple[_RecordT, ...]:
        """Inventory every retained attempt without granting recovery authority."""

        with self._access.guard(require_write=False):
            self._access.assert_current()
            with self._bound_journal(create_lock=False) as rooted:
                latest: dict[str, _RecordT]
                if self._v2_owner_exists(rooted):
                    _history, replay = self._load_v2_state(rooted)
                    prepared = self._history_reader.preparation.read(rooted)
                    if prepared is None:
                        raise self._error_type(
                            "coding_worker_gate_v2_preparation_absent"
                        )
                    latest = {
                        record.attempt_id: cast(_RecordT, record)
                        for record in replay.current_records
                    }
                    archive = prepared.no_effect_archive
                    if archive is not None:
                        latest.update(
                            (item.attempt_id, cast(_RecordT, item.gate))
                            for item in archive.proofs
                        )
                else:
                    latest = {}
                    for record in self._load(rooted):
                        latest[record.attempt_id] = record
                self._access.assert_current()
                return tuple(
                    sorted(latest.values(), key=lambda record: record.journal_revision)
                )

    def _checkpoint_writer_fence(
        self, rooted: RootedFile
    ) -> tuple[_CheckpointMethods, ...]:
        with self._history_reader.checkpoints.translated_errors(self._error_type):
            return self._history_reader.checkpoints.read_writer_fence(
                rooted, scope_id=self._access.scope_id, store_id=self._access.store_id
            )

    @contextmanager
    def _bound_journal(self, *, create_lock: bool = True) -> Iterator[RootedFile]:
        with bind_private_journal(
            self._path,
            error_type=self._error_type,
            label="coding_worker_start_gate_root",
            durable=True,
            reject_open=True,
        ) as rooted:
            if self._v2_owner_exists(rooted):
                try:
                    rooted.sibling(self._path.name + ".lock").acquire_lock(
                        exclusive=create_lock, suffix="", create=False
                    )
                except FileNotFoundError as exc:
                    raise self._error_type(
                        "coding_worker_start_gate_lock_missing"
                    ) from exc
            elif create_lock:
                created = rooted.acquire_lock(
                    exclusive=True,
                    suffix=".lock",
                    initialize_empty_target_if_new=True,
                )
                if created:
                    initialize_coding_worker_active_head(
                        rooted,
                        stem="worker-start-gates",
                        stream_id="worker-start-gates",
                    )
            else:
                try:
                    rooted.stat()
                except FileNotFoundError:
                    try:
                        rooted.sibling(self._path.name + ".lock").stat()
                    except FileNotFoundError:
                        pass
                    else:
                        raise self._error_type(
                            "coding_worker_start_gate_orphan_lock"
                        ) from None
                else:
                    try:
                        rooted.acquire_lock(
                            exclusive=False, suffix=".lock", create=False
                        )
                    except FileNotFoundError as exc:
                        raise self._error_type(
                            "coding_worker_start_gate_lock_missing"
                        ) from exc
            yield rooted

    def _load(self, rooted: RootedFile) -> tuple[_RecordT, ...]:
        records, _history = self._load_history(rooted)
        return records

    _v2_owner_exists = staticmethod(RetainedHistoryReader.owner_exists)

    def _load_v2_state(
        self, rooted: RootedFile
    ) -> tuple[CodingWorkerSegmentedHistoryV1, _StartGateReplayFields]:
        """Read a committed base and retained physical Start Gate generations."""

        stem = "worker-start-gates"
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
                raise self._error_type("coding_worker_start_gate_v2_owner_changed")
            retained = self._history_reader.read(rooted, stem=stem)
            replay = retained.replay
            if not isinstance(
                replay,
                self._history_reader.preparation.prepared_type._gate_type._replay_type,
            ):
                raise self._error_type("coding_worker_start_gate_v2_owner_changed")
            return (
                self._history_reader.history_from_retained(
                    rooted,
                    retained,
                    stem=stem,
                    manifest_changed=lambda: self._error_type(
                        "coding_worker_start_gate_v2_manifest_changed"
                    ),
                ),
                cast(_StartGateReplayFields, replay),
            )
        except (
            self._history_reader.error_type,
            CodingWorkerHistorySegmentError,
        ) as exc:
            raise self._error_type(cast(_CodedFailure, exc).code) from exc
        except (OSError, ValueError) as exc:
            raise self._error_type("coding_worker_start_gate_v2_corrupt") from exc

    def _load_history(
        self, rooted: RootedFile
    ) -> tuple[tuple[_RecordT, ...], CodingWorkerSegmentedHistoryV1]:
        try:
            history = read_coding_worker_segmented_history(
                rooted,
                stem="worker-start-gates",
                stream_id="worker-start-gates",
                max_segment_bytes=self._max_history_bytes(),
            )
        except CodingWorkerHistorySegmentError as exc:
            raise self._error_type(cast(_CodedFailure, exc).code) from exc
        try:
            all_records: list[_RecordT] = []
            for generation, raw in enumerate(history.segments):
                segment_records: tuple[_RecordT, ...] = decode_jsonl(
                    raw.decode("utf-8"),
                    target=self._path,
                    record_codec=self._record_codec,
                    load_policy=self._load_policy,
                ).records
                lines = raw.splitlines(keepends=True)
                first_revision = len(all_records) + 1
                if (
                    len(segment_records) > self._max_history_records()
                    or len(lines) != len(segment_records)
                    or any(
                        record.journal_revision != index
                        or line != canonical_json_bytes(record.to_dict()) + b"\n"
                        for index, (record, line) in enumerate(
                            zip(segment_records, lines, strict=True), first_revision
                        )
                    )
                ):
                    raise ValueError("Worker gate history changed")
                all_records.extend(segment_records)
                if (
                    history.manifest is not None
                    and generation < history.active_generation
                    and len(all_records)
                    != history.manifest.sealed[generation].last_revision
                ):
                    raise ValueError("Worker gate sealed revision changed")
            records = tuple(all_records)
            fold_start_gate_records(records)
            return records, history
        except (JournalCodecError, UnicodeError, ValueError) as exc:
            raise self._error_type("coding_worker_start_gate_corrupt") from exc
