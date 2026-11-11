"""Rooted owner publication and deletion debt under caller-held Product custody."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO

from .._segmented_history import (
    CodingWorkerSegmentedHistoryV1,
    CodingWorkerSegmentManifestV1,
    _head_name,
    _segment_name,
    initialize_coding_worker_active_head,
    read_coding_worker_segmented_history,
    rollback_coding_worker_unpublished_successor,
    seal_coding_worker_active_segment,
)
from ._cutover import _IndexMethods
from ._preparation import (
    _MAX_BASE_BYTES,
    _MAX_INTENT_BYTES,
    _MAX_STREAM_BYTES,
    _optional_bytes,
)
from ._prepared import _PreparedMethods, require_retained_reference_closure
from ._read_v2 import (
    _MAX_HEAD_BYTES,
    _MAX_INDEX_BYTES,
    _MAX_LEDGER_BYTES,
    _MAX_SEGMENT_BYTES,
    RetainedHistoryReader,
    _seal_head,
)
from ._snapshot import CODING_WORKER_HISTORY_STREAM_STEMS
from ._snapshot_io import HistorySnapshotAccess
from ._v2_names import (
    DELETION_LEDGER_NAME,
    NO_EFFECT_ARCHIVE_NAME,
    PREPARATION_ARTIFACT_NAMES,
    PREPARATION_INTENT_NAME,
    PRODUCT_OWNER_INDEX_NAME,
)


def _history_entry_present(rooted: RootedFile, name: str) -> bool:
    try:
        rooted.sibling(name).stat()
    except FileNotFoundError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class HistoryPublication:
    """Borrow RootedFile only for a command; do not own Product authority."""

    reader: RetainedHistoryReader

    @staticmethod
    def owner_bytes(
        rooted: RootedFile, *, max_index_bytes: int = _MAX_INDEX_BYTES
    ) -> bytes | None:
        return _optional_bytes(rooted, PRODUCT_OWNER_INDEX_NAME, limit=max_index_bytes)

    @staticmethod
    def _lock_streams(
        rooted: RootedFile,
        error_type: type[RuntimeError],
        *,
        empty_supervisor_checkpointed: bool = False,
    ) -> None:
        for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
            try:
                rooted.sibling(stem + ".jsonl.lock").acquire_lock(
                    exclusive=True,
                    suffix="",
                    create=False,
                )
            except FileNotFoundError as exc:
                if stem == "worker-supervisor" and empty_supervisor_checkpointed:
                    names, complete = rooted.scan_sibling_names(limit=131072)
                    if not complete or any(
                        name.casefold().startswith((stem + ".", "." + stem + "."))
                        for name in names
                    ):
                        raise error_type(
                            "coding_worker_v2_empty_supervisor_changed"
                        ) from exc
                    active = rooted.sibling(stem + ".jsonl")
                    if not active.acquire_lock(
                        exclusive=True,
                        suffix=".lock",
                        initialize_empty_target_if_new=True,
                    ):
                        raise error_type(
                            "coding_worker_v2_empty_supervisor_changed"
                        ) from exc
                    initialize_coding_worker_active_head(rooted, stem=stem, stream_id=stem)
                    continue
                raise error_type("coding_worker_v2_stream_lock_missing") from exc

    @staticmethod
    def seal_v1_under_guard(
        rooted: RootedFile,
        *,
        empty_supervisor_checkpointed: bool,
        error_type: type[RuntimeError],
        max_segment_bytes: int,
    ) -> tuple[int, ...]:
        HistoryPublication._lock_streams(
            rooted,
            error_type,
            empty_supervisor_checkpointed=empty_supervisor_checkpointed,
        )
        if _history_entry_present(rooted, PRODUCT_OWNER_INDEX_NAME):
            raise error_type("coding_worker_v2_owner_present")
        if _history_entry_present(rooted, PREPARATION_INTENT_NAME):
            raise error_type("coding_worker_v2_preparation_present")
        if any(
            _history_entry_present(rooted, name)
            for name in (*PREPARATION_ARTIFACT_NAMES, NO_EFFECT_ARCHIVE_NAME)
        ):
            raise error_type("coding_worker_v2_preparation_artifact_present")

        histories: list[CodingWorkerSegmentedHistoryV1] = []
        for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
            rollback_coding_worker_unpublished_successor(
                rooted,
                stem=stem,
                stream_id=stem,
                max_segment_bytes=max_segment_bytes,
            )
            history = read_coding_worker_segmented_history(
                rooted,
                stem=stem,
                stream_id=stem,
                max_segment_bytes=max_segment_bytes,
            )
            if history.active_generation == 0:
                if not history.active_raw:
                    if stem != "worker-supervisor" or not empty_supervisor_checkpointed:
                        raise error_type("coding_worker_v2_stream_empty")
                    if history.manifest is None:
                        rooted.sibling(stem + ".segments.json").create_new(
                            CodingWorkerSegmentManifestV1(
                                stream_id=stem, active_generation=0, sealed=()
                            ).to_bytes()
                        )
                        history = read_coding_worker_segmented_history(
                            rooted,
                            stem=stem,
                            stream_id=stem,
                            max_segment_bytes=max_segment_bytes,
                        )
                if history.active_raw and not history.active_raw.endswith(b"\n"):
                    raise error_type("coding_worker_v2_stream_incomplete")
            histories.append(history)

        for stem, history in zip(
            CODING_WORKER_HISTORY_STREAM_STEMS, histories, strict=True
        ):
            if history.active_generation == 0 and history.active_raw:
                seal_coding_worker_active_segment(
                    rooted,
                    stem=stem,
                    stream_id=stem,
                    history=history,
                    last_revision=history.active_raw.count(b"\n"),
                )
        generations = tuple(
            read_coding_worker_segmented_history(
                rooted,
                stem=stem,
                stream_id=stem,
                max_segment_bytes=max_segment_bytes,
            ).active_generation
            for stem in CODING_WORKER_HISTORY_STREAM_STEMS
        )
        if any(
            generation < (0 if stem == "worker-supervisor" else 1)
            for stem, generation in zip(
                CODING_WORKER_HISTORY_STREAM_STEMS, generations, strict=True
            )
        ):
            raise error_type("coding_worker_v2_stream_unsealed")
        return tuple(
            0 if stem == "worker-supervisor" and generation == 0 else 1
            for stem, generation in zip(
                CODING_WORKER_HISTORY_STREAM_STEMS, generations, strict=True
            )
        )

    @staticmethod
    def seal_v1(
        access: HistorySnapshotAccess,
        *,
        empty_supervisor_checkpointed: bool,
        error_type: type[RuntimeError],
        max_segment_bytes: int,
    ) -> tuple[int, ...]:
        """Borrow the original pinned root; caller retains runtime/GC custody."""
        with access.pin_state_read() as root_fd:
            with RootedFileIO(access.state_root, root_fd) as file_io:
                with file_io.bind(
                    access.state_root / PRODUCT_OWNER_INDEX_NAME,
                    durable=True,
                ) as rooted:
                    result = HistoryPublication.seal_v1_under_guard(
                        rooted,
                        empty_supervisor_checkpointed=empty_supervisor_checkpointed,
                        error_type=error_type,
                        max_segment_bytes=max_segment_bytes,
                    )
        access.assert_current()
        return result

    def commit_under_guard(
        self,
        rooted: RootedFile,
        *,
        prepared: _PreparedMethods,
        error_type: type[RuntimeError],
        max_index_bytes: int = _MAX_INDEX_BYTES,
    ) -> _IndexMethods:
        if type(prepared) is not self.reader.preparation.prepared_type:
            raise ValueError("Coding Worker V2 prepared history is invalid")
        self._lock_streams(rooted, error_type)
        expected = prepared.index.to_bytes()
        existing = self.owner_bytes(rooted, max_index_bytes=max_index_bytes)
        if existing is not None:
            if existing != expected:
                raise error_type("coding_worker_v2_owner_changed")
        else:
            verified = tuple(
                self.reader.verify_precommit(rooted, stem=stem, prepared=prepared)
                for stem in CODING_WORKER_HISTORY_STREAM_STEMS
            )
            receipt_replay = verified[1].replay
            if not isinstance(
                receipt_replay,
                self.reader.preparation.prepared_type._receipt_type._replay_type,
            ):
                raise error_type("coding_worker_v2_receipt_replay_changed")
            require_retained_reference_closure(
                opt_in_base=prepared.semantic_bases[0],
                opt_in_segments=verified[0].segments,
                retained_receipts=receipt_replay.retained_records,
            )
            rooted.sibling(PRODUCT_OWNER_INDEX_NAME).create_new(expected)

        for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
            self.reader.read(rooted, stem=stem)
        return prepared.index

    def retire_under_guard(
        self,
        rooted: RootedFile,
        *,
        error_type: type[RuntimeError],
        max_segment_bytes: int = _MAX_SEGMENT_BYTES,
        max_head_bytes: int = _MAX_HEAD_BYTES,
        max_ledger_bytes: int = _MAX_LEDGER_BYTES,
        max_intent_bytes: int = _MAX_INTENT_BYTES,
        max_base_bytes: int = _MAX_BASE_BYTES,
        max_stream_bytes: int = _MAX_STREAM_BYTES,
        max_index_bytes: int = _MAX_INDEX_BYTES,
    ) -> bool:
        self._lock_streams(rooted, error_type)
        before = tuple(
            self.reader.read(rooted, stem=stem)
            for stem in CODING_WORKER_HISTORY_STREAM_STEMS
        )
        prepared = self.reader.preparation.read(
            rooted,
            max_intent_bytes=max_intent_bytes,
            max_base_bytes=max_base_bytes,
            max_stream_bytes=max_stream_bytes,
            max_index_bytes=max_index_bytes,
        )
        if prepared is None:
            raise error_type("coding_worker_v2_preparation_absent")
        ledger = self.reader.ledger_type.from_prepared(prepared)
        current = _optional_bytes(rooted, DELETION_LEDGER_NAME, limit=max_ledger_bytes)
        if current is None:
            rooted.sibling(DELETION_LEDGER_NAME).create_new(ledger.to_bytes())
        elif current != ledger.to_bytes():
            raise error_type("coding_worker_v2_deletion_ledger_changed")

        removed = False
        for stream in prepared.streams:
            for seal in stream.retired_sealed:
                name = _segment_name(stream.stem, seal.generation)
                raw = _optional_bytes(rooted, name, limit=max_segment_bytes)
                if raw is not None:
                    if (
                        len(raw) != seal.byte_count
                        or sha256(raw).hexdigest() != seal.digest
                    ):
                        raise error_type("coding_worker_v2_retired_bytes_changed")
                    self._unlink_matching(
                        rooted,
                        name=name,
                        expected=raw,
                        limit=max_segment_bytes,
                        error_type=error_type,
                    )
                    removed = True
                head_name = _head_name(stream.stem, seal.generation)
                if _optional_bytes(rooted, head_name, limit=max_head_bytes) is not None:
                    self._unlink_matching(
                        rooted,
                        name=head_name,
                        expected=_seal_head(stream.stem, seal),
                        limit=max_head_bytes,
                        error_type=error_type,
                    )
                    removed = True
        after = tuple(
            self.reader.read(rooted, stem=stem)
            for stem in CODING_WORKER_HISTORY_STREAM_STEMS
        )
        if after != before:
            raise error_type("coding_worker_v2_retained_history_changed")
        return removed

    @staticmethod
    def _unlink_matching(
        rooted: RootedFile,
        *,
        name: str,
        expected: bytes,
        limit: int,
        error_type: type[RuntimeError],
    ) -> None:
        file = rooted.sibling(name)
        raw = _optional_bytes(rooted, name, limit=limit)
        if raw is None:
            return
        if raw != expected:
            raise error_type("coding_worker_v2_retired_bytes_changed")
        observed = file.stat()
        file.unlink_owned((observed.st_dev, observed.st_ino))
