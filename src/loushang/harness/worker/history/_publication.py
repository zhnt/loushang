"""Rooted owner publication and deletion debt under caller-held Product custody."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.journal._rooted_io import RootedFile

from .._segmented_history import _head_name, _segment_name
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
from ._v2_names import DELETION_LEDGER_NAME, PRODUCT_OWNER_INDEX_NAME


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
    def _lock_streams(rooted: RootedFile, error_type: type[RuntimeError]) -> None:
        for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
            try:
                rooted.sibling(stem + ".jsonl.lock").acquire_lock(
                    exclusive=True,
                    suffix="",
                    create=False,
                )
            except FileNotFoundError as exc:
                raise error_type("coding_worker_v2_stream_lock_missing") from exc

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
