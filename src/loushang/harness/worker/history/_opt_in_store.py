"""Opt-in history and CAS mechanics under the original GC and Journal owners."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Generic, Literal, TypeVar, cast

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    JournalFormatProfile,
    JournalLoadPolicy,
    JournalRecordCodec,
    append_jsonl_record,
    decode_jsonl,
)
from loushang.harness.journal._rooted_io import RootedFile, bind_private_journal
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)

from .._segmented_history import (
    CodingWorkerHistorySegmentError,
    CodingWorkerSegmentedHistoryV1,
    append_coding_worker_active_record,
    initialize_coding_worker_active_head,
    read_coding_worker_segmented_history,
)
from ._checkpoint import _CheckpointMethods
from ._checkpoint_history import _CodedFailure
from ._opt_in import (
    _IDENTIFIER,
    _MAX_EVENTS,
    _MAX_SEGMENT_BYTES,
    _OPAQUE,
    _OptInDecisionMethods,
    _OptInReplayFields,
    _OptInValue,
    fold_opt_in_events,
    opt_in_line,
    parse_opt_in_segment,
)
from ._read_v2 import RetainedHistoryReader
from ._v2_names import PRODUCT_OWNER_INDEX_NAME

_STEM = "worker-opt-in"
_DecisionT = TypeVar("_DecisionT", bound=_OptInDecisionMethods)
_ProjectionT = TypeVar("_ProjectionT")
_PolicyT = TypeVar("_PolicyT", bound=_OptInValue)


class OptInJournal(Generic[_DecisionT, _ProjectionT, _PolicyT]):
    """Product-private CAS journal serialized with Desired State and GC."""

    def __init__(
        self,
        path: Path,
        *,
        scope_id: str,
        gc_gate: PluginPackageGcReservationJournal,
        store_id: str | None = None,
        history_reader: RetainedHistoryReader,
        projection_type: type[_ProjectionT],
        error_type: type[RuntimeError],
    ) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("Coding Worker opt-in journal path is invalid")
        if (
            not isinstance(scope_id, str)
            or len(scope_id) > 128
            or _OPAQUE.fullmatch(scope_id) is None
        ):
            raise ValueError("Coding Worker opt-in scope is invalid")
        if not isinstance(gc_gate, PluginPackageGcReservationJournal):
            raise TypeError("Product GC gate is required")
        if store_id is not None and (
            type(store_id) is not str or not store_id or len(store_id) > 128
        ):
            raise ValueError("Coding Worker opt-in store is invalid")
        if path != gc_gate.path.parent / "worker-opt-in.jsonl":
            raise ValueError("Coding Worker opt-in journal is outside Product state")
        self._path = path
        self._scope_id = scope_id
        self._gc_gate = gc_gate
        self._store_id = store_id
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._history_reader = history_reader
        self._projection_type = projection_type
        self._error_type = error_type

    @property
    def path(self) -> Path:
        return self._path

    @property
    def scope_id(self) -> str:
        return self._scope_id

    @property
    def gc_gate(self) -> PluginPackageGcReservationJournal:
        return self._gc_gate

    def current(self, plugin_id: str) -> _DecisionT | None:
        """Read the latest Product decision under the shared selection gate."""

        self._require_plugin_id(plugin_id)
        with self._gc_gate.guard(), self._bound_journal(create_lock=False) as rooted:
            if self._v2_owner_exists(rooted):
                _events, _history, replay = self._load_v2_state(rooted)
                return self._latest(
                    cast(tuple[_DecisionT, ...], replay.latest_decisions), plugin_id
                )
            events, _history = self._load_history(rooted)
            return self._latest(events, plugin_id)

    def current_read_only(self, plugin_id: str) -> _DecisionT | None:
        """Inspect an existing Product decision without creating owner state."""

        self._require_plugin_id(plugin_id)
        with (
            self._gc_gate.read_guard(),
            self._bound_journal(create_lock=False) as rooted,
        ):
            if self._v2_owner_exists(rooted):
                _events, _history, replay = self._load_v2_state(rooted)
                return self._latest(
                    cast(tuple[_DecisionT, ...], replay.latest_decisions), plugin_id
                )
            events, _history = self._load_history(rooted)
            return self._latest(events, plugin_id)

    def history_read_only(self) -> tuple[_DecisionT, ...]:
        """Inventory every retained operation under the Product GC read gate."""

        with self._gc_gate.read_guard():
            return self._history_under_gc_guard()

    def _history_under_gc_guard(self) -> tuple[_DecisionT, ...]:
        """Read while the Product reviewer already holds its GC snapshot."""

        with self._bound_journal(create_lock=False) as rooted:
            if self._v2_owner_exists(rooted):
                raise self._error_type(
                    "coding_worker_opt_in_v2_full_history_unavailable"
                )
            events, _history = self._load_history(rooted)
            return events

    def retention_projection_under_gc_guard(
        self,
    ) -> _ProjectionT:
        """Join retained decisions while the Product reviewer owns the GC gate.

        The V2 semantic base keeps each plugin's decision at cutover. Combined
        with retained events, that proves later receipts even after revocation.
        Older decisions that were superseded before cutover have no retained
        receipt authority and are intentionally unavailable here.
        """

        with self._bound_journal(create_lock=False) as rooted:
            if self._v2_owner_exists(rooted):
                events, _history, replay = self._load_v2_state(rooted)
                prepared = self._history_reader.preparation.read(rooted)
                if prepared is None:
                    raise self._error_type("coding_worker_opt_in_v2_preparation_absent")
                base = prepared.semantic_bases[0]
                if not isinstance(
                    base, self._history_reader.preparation.prepared_type._opt_in_type
                ):
                    raise self._error_type("coding_worker_opt_in_v2_base_changed")
                archive = prepared.no_effect_archive
                references = {
                    item.decision_digest: item
                    for item in (*base.latest_decisions, *events)
                }
                if archive is not None:
                    references.update(
                        (item.historical_allow.decision_digest, item.historical_allow)
                        for item in archive.proofs
                    )
                return cast(Callable[..., _ProjectionT], self._projection_type)(
                    reference_decisions=tuple(references.values()),
                    latest_decisions=replay.latest_decisions,
                    operation_ids=tuple(sorted(replay.operation_ids)),
                    revision=replay.last_revision,
                )
            events, _history = self._load_history(rooted)
            latest, _operations = fold_opt_in_events(
                events, scope_id=self._scope_id, error_type=self._error_type
            )
            return cast(Callable[..., _ProjectionT], self._projection_type)(
                reference_decisions=events,
                latest_decisions=tuple(latest[key] for key in sorted(latest)),
                operation_ids=tuple(item.operation_id for item in events),
                revision=len(events),
            )

    def change(
        self,
        *,
        plugin_id: str,
        operation_id: str,
        expected_generation: int,
        action: Literal["allow", "revoke"],
        opt_in: _PolicyT | None,
    ) -> _DecisionT:
        """Persist one explicit decision; replay the same operation exactly."""

        self._require_plugin_id(plugin_id)
        if (
            not isinstance(operation_id, str)
            or len(operation_id) > 128
            or _OPAQUE.fullmatch(operation_id) is None
            or type(expected_generation) is not int
            or expected_generation < 0
            or action not in {"allow", "revoke"}
            or (
                action == "allow"
                and not isinstance(opt_in, self._decision_type._opt_in_type)
            )
            or (action == "revoke" and opt_in is not None)
        ):
            raise ValueError("Coding Worker opt-in command is invalid")
        with self._gc_gate.guard(require_write=True), self._bound_journal() as rooted:
            checkpoints = self._checkpoint_writer_fence(rooted)
            if self._v2_owner_exists(rooted):
                events, history, v2_replay = self._load_v2_state(rooted)
                revision = v2_replay.last_revision
                self._assert_checkpoint_high_water(
                    checkpoints,
                    events,
                    initial_latest=cast(
                        tuple[_DecisionT, ...], v2_replay.latest_decisions
                    ),
                )
            else:
                events, history = self._load_history(rooted)
                v2_replay = None
                revision = len(events)
                self._assert_checkpoint_source(checkpoints, history)
                self._assert_checkpoint_high_water(checkpoints, events)
            replay = next(
                (event for event in events if event.operation_id == operation_id), None
            )
            if replay is not None:
                if (
                    replay.plugin_id != plugin_id
                    or replay.action != action
                    or replay.opt_in != opt_in
                    or replay.generation != expected_generation + 1
                ):
                    raise self._error_type("coding_worker_opt_in_operation_conflict")
                return replay
            if any(
                operation_id in record.new_opt_in_operation_ids
                for record in checkpoints
            ) or (v2_replay is not None and operation_id in v2_replay.operation_ids):
                raise self._error_type("coding_worker_opt_in_operation_retired")
            previous = self._latest(
                events
                if v2_replay is None
                else cast(tuple[_DecisionT, ...], v2_replay.latest_decisions),
                plugin_id,
            )
            generation = 0 if previous is None else previous.generation
            if generation != expected_generation:
                raise self._error_type("coding_worker_opt_in_stale")
            if action == "revoke" and previous is None:
                raise self._error_type("coding_worker_opt_in_absent")
            kill = 0 if previous is None else previous.kill_switch_generation
            if action == "revoke":
                kill += 1
            if action == "allow" and (
                opt_in is None
                or opt_in.plugin_id != plugin_id
                or opt_in.owner_selection_generation != generation + 1
                or opt_in.kill_switch_generation != kill
            ):
                raise self._error_type("coding_worker_opt_in_generation_invalid")
            decision = self._decision_type.create(
                journal_revision=revision + 1,
                scope_id=self._scope_id,
                plugin_id=plugin_id,
                operation_id=operation_id,
                generation=generation + 1,
                kill_switch_generation=kill,
                action=action,
                opt_in=opt_in,
            )
            line = opt_in_line(decision)
            if len(line) > self._max_history_bytes():
                raise self._error_type("coding_worker_opt_in_capacity")

            def append(name: str) -> None:
                target = rooted.sibling(name)
                append_jsonl_record(
                    self._path,
                    decision,
                    record_codec=self._record_codec,
                    format_profile=self._record_format,
                    durability=self._durability,
                    bound_file=target,
                )

            append_coding_worker_active_record(
                rooted,
                stem=_STEM,
                stream_id=_STEM,
                history=history,
                last_revision=revision,
                line=line,
                seal_required=revision - history.last_sealed_revision
                >= self._max_history_records()
                or len(history.active_raw) + len(line) > self._max_history_bytes(),
                seal_error=lambda exc: self._error_type(exc.code),
                append=append,
            )
            return decision

    def _checkpoint_writer_fence(
        self, rooted: RootedFile
    ) -> tuple[_CheckpointMethods, ...]:
        if self._store_id is None:
            self._history_reader.checkpoints.require_unowned_absence(
                rooted,
                error_type=self._error_type,
                code="coding_worker_opt_in_checkpoint_owner_required",
            )
            return ()
        with self._history_reader.checkpoints.translated_errors(self._error_type):
            return self._history_reader.checkpoints.read_writer_fence(
                rooted, scope_id=self._scope_id, store_id=self._store_id
            )

    def _assert_checkpoint_source(
        self,
        checkpoints: tuple[_CheckpointMethods, ...],
        history: CodingWorkerSegmentedHistoryV1,
    ) -> None:
        self._history_reader.checkpoints.verify_source_revision(
            checkpoints,
            history,
            stream_index=0,
            error_type=self._error_type,
            code="coding_worker_opt_in_checkpoint_source_changed",
        )

    def _assert_checkpoint_high_water(
        self,
        checkpoints: tuple[_CheckpointMethods, ...],
        events: tuple[_DecisionT, ...],
        *,
        initial_latest: tuple[_DecisionT, ...] = (),
    ) -> None:
        if not checkpoints:
            return
        latest_checkpoint = checkpoints[-1]
        latest: dict[str, _DecisionT] = {
            item.plugin_id: item for item in initial_latest
        }
        for event in events:
            latest[event.plugin_id] = event
        for (
            plugin_id,
            generation,
            kill_generation,
            action,
            digest,
        ) in latest_checkpoint.opt_in_generation_high_water:
            current = latest.get(plugin_id)
            if (
                current is None
                or current.generation < generation
                or current.kill_switch_generation < kill_generation
                or (
                    current.generation == generation
                    and (current.action != action or current.decision_digest != digest)
                )
            ):
                raise self._error_type(
                    "coding_worker_opt_in_checkpoint_high_water_changed"
                )

    @contextmanager
    def _bound_journal(self, *, create_lock: bool = True) -> Iterator[RootedFile]:
        with bind_private_journal(
            self._path,
            error_type=self._error_type,
            label="coding_worker_opt_in_state_root",
            durable=True,
        ) as rooted:
            v2_owner = self._v2_owner_exists(rooted)
            if v2_owner:
                try:
                    rooted.sibling(self._path.name + ".lock").acquire_lock(
                        exclusive=create_lock, suffix="", create=False
                    )
                except FileNotFoundError as exc:
                    raise self._error_type("coding_worker_opt_in_lock_missing") from exc
            elif create_lock:
                try:
                    rooted.stat()
                except FileNotFoundError:
                    try:
                        rooted.sibling(self._path.name + ".lock").stat()
                    except FileNotFoundError:
                        pass
                    else:
                        raise self._error_type(
                            "coding_worker_opt_in_orphan_lock"
                        ) from None
                else:
                    try:
                        rooted.sibling(self._path.name + ".lock").stat()
                    except FileNotFoundError as exc:
                        raise self._error_type(
                            "coding_worker_opt_in_lock_missing"
                        ) from exc
                created = rooted.acquire_lock(
                    exclusive=True,
                    suffix=".lock",
                    initialize_empty_target_if_new=True,
                )
                if created:
                    initialize_coding_worker_active_head(
                        rooted, stem=_STEM, stream_id=_STEM
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
                            "coding_worker_opt_in_orphan_lock"
                        ) from None
                else:
                    try:
                        rooted.acquire_lock(
                            exclusive=False, suffix=".lock", create=False
                        )
                    except FileNotFoundError as exc:
                        raise self._error_type(
                            "coding_worker_opt_in_lock_missing"
                        ) from exc
            yield rooted

    def _load(self, rooted: RootedFile) -> tuple[_DecisionT, ...]:
        events, _history = self._load_history(rooted)
        return events

    _v2_owner_exists = staticmethod(RetainedHistoryReader.owner_exists)

    def _load_v2_state(
        self, rooted: RootedFile
    ) -> tuple[
        tuple[_DecisionT, ...],
        CodingWorkerSegmentedHistoryV1,
        _OptInReplayFields,
    ]:
        """Use the committed Product base and retained bytes after V2 ownership."""

        try:
            owner = (
                self._history_reader.preparation.prepared_type._index_type.from_bytes(
                    rooted.sibling(PRODUCT_OWNER_INDEX_NAME).read_bytes(max_bytes=4096)
                )
            )
            if owner.scope_id != self._scope_id or owner.store_id != self._store_id:
                raise self._error_type("coding_worker_opt_in_v2_owner_changed")
            retained = self._history_reader.read(rooted, stem=_STEM)
            replay = retained.replay
            if not isinstance(
                replay,
                self._history_reader.preparation.prepared_type._opt_in_type._replay_type,
            ) or any(
                item.scope_id != self._scope_id for item in replay.latest_decisions
            ):
                raise self._error_type("coding_worker_opt_in_v2_owner_changed")
            history = self._history_reader.history_from_retained(
                rooted,
                retained,
                stem=_STEM,
                manifest_changed=lambda: self._error_type(
                    "coding_worker_opt_in_v2_manifest_changed"
                ),
            )
            events = tuple(
                event
                for raw in retained.segments
                for event in parse_opt_in_segment(
                    raw, decision_type=self._decision_type
                )
            )
            return (
                cast(tuple[_DecisionT, ...], events),
                history,
                cast(_OptInReplayFields, replay),
            )
        except (
            self._history_reader.error_type,
            CodingWorkerHistorySegmentError,
        ) as exc:
            raise self._error_type(cast(_CodedFailure, exc).code) from exc
        except (OSError, ValueError) as exc:
            raise self._error_type("coding_worker_opt_in_v2_corrupt") from exc

    def _load_history(
        self, rooted: RootedFile
    ) -> tuple[tuple[_DecisionT, ...], CodingWorkerSegmentedHistoryV1]:
        try:
            history = read_coding_worker_segmented_history(
                rooted,
                stem=_STEM,
                stream_id=_STEM,
                max_segment_bytes=self._max_history_bytes(),
            )
        except CodingWorkerHistorySegmentError as exc:
            raise self._error_type(cast(_CodedFailure, exc).code) from exc
        events: list[_DecisionT] = []
        for generation, raw in enumerate(history.segments):
            segment = decode_jsonl(
                raw.decode("utf-8"),
                target=self._path,
                record_codec=self._record_codec,
                load_policy=JournalLoadPolicy(partial_tail="raise", create_lock=False),
            ).records
            lines = raw.splitlines(keepends=True)
            if (
                len(segment) > self._max_history_records()
                or len(segment) != len(lines)
                or any(
                    event.journal_revision != revision or line != opt_in_line(event)
                    for revision, (event, line) in enumerate(
                        zip(segment, lines, strict=True), len(events) + 1
                    )
                )
            ):
                raise self._error_type("coding_worker_opt_in_corrupt")
            events.extend(segment)
            if (
                history.manifest is not None
                and generation < history.active_generation
                and len(events) != history.manifest.sealed[generation].last_revision
            ):
                raise self._error_type("coding_worker_opt_in_corrupt")
        result = tuple(events)
        fold_opt_in_events(result, scope_id=self._scope_id, error_type=self._error_type)
        return result, history

    @staticmethod
    def _latest(events: tuple[_DecisionT, ...], plugin_id: str) -> _DecisionT | None:
        return next(
            (event for event in reversed(events) if event.plugin_id == plugin_id),
            None,
        )

    @staticmethod
    def _require_plugin_id(plugin_id: str) -> None:
        if (
            not isinstance(plugin_id, str)
            or len(plugin_id) > 128
            or _IDENTIFIER.fullmatch(plugin_id) is None
        ):
            raise ValueError("Coding Worker opt-in Plugin id is invalid")

    @property
    def _decision_type(self) -> type[_DecisionT]:
        return cast(
            type[_DecisionT],
            self._history_reader.preparation.prepared_type._opt_in_type._decision_type,
        )

    @property
    def _record_codec(self) -> JournalRecordCodec[_DecisionT]:
        raise NotImplementedError("the original value codec is required")

    @property
    def _record_format(self) -> JournalFormatProfile:
        raise NotImplementedError("the original format is required")

    def _max_history_bytes(self) -> int:
        return _MAX_SEGMENT_BYTES

    def _max_history_records(self) -> int:
        return _MAX_EVENTS
