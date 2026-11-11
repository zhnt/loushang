"""Strict V2 retained reads over the same preparation, checkpoint and journal owners."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Generic, TypeAlias, TypeVar, cast

from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .._segmented_history import (
    CodingWorkerSealedSegmentV1,
    CodingWorkerSegmentedHistoryV1,
    CodingWorkerSegmentManifestV1,
    _head_bytes,
    _head_name,
    _segment_name,
)
from ._activation_base import _ActivationReplayFields
from ._checkpoint_history import CheckpointHistory
from ._cutover import _StreamCutoverMethods
from ._deletion import _DeletionLedgerMethods
from ._opt_in import _OptInReplayFields
from ._preparation import PreparationHistory
from ._preparation import _optional_bytes as _optional
from ._prepared import _PreparedMethods
from ._receipts import _ReceiptReplayFields
from ._start_gate import _StartGateReplayFields
from ._supervisor import _SupervisorReplayFields
from ._v2_names import DELETION_LEDGER_NAME, PRODUCT_OWNER_INDEX_NAME

_MAX_SEGMENT_BYTES = 32 * 1024 * 1024
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_INDEX_BYTES = 4096
_MAX_LEDGER_BYTES = 1024 * 1024
_MAX_HEAD_BYTES = 512
_MAX_DIRECTORY_ENTRIES = 131072

_V2Replay: TypeAlias = (
    _OptInReplayFields
    | _ReceiptReplayFields
    | _ActivationReplayFields
    | _StartGateReplayFields
    | _SupervisorReplayFields
)


class _RetainedHistoryFields:
    __slots__ = ()

    stem: str
    first_retained_generation: int
    active_generation: int
    segments: tuple[bytes, ...]
    last_revision: int
    replay: _V2Replay


_HistoryT = TypeVar("_HistoryT", bound=_RetainedHistoryFields)


def _seal_head(stem: str, seal: CodingWorkerSealedSegmentV1) -> bytes:
    return canonical_json_bytes(
        {
            "byteCount": seal.byte_count,
            "digest": seal.digest,
            "generation": seal.generation,
            "streamId": stem,
            "version": 1,
        }
    )


@dataclass(frozen=True, slots=True)
class RetainedHistoryReader(Generic[_HistoryT]):
    """Compose fixed five-stream value bindings with the existing bound readers."""

    preparation: PreparationHistory
    checkpoints: CheckpointHistory
    ledger_type: type[_DeletionLedgerMethods]
    history_type: type[_HistoryT]
    error_type: type[RuntimeError]

    @staticmethod
    def owner_exists(rooted: RootedFile) -> bool:
        try:
            rooted.sibling(PRODUCT_OWNER_INDEX_NAME).stat()
        except FileNotFoundError:
            return False
        return True

    @staticmethod
    def history_from_retained(
        rooted: RootedFile,
        retained: _RetainedHistoryFields,
        *,
        stem: str,
        manifest_changed: Callable[[], Exception],
    ) -> CodingWorkerSegmentedHistoryV1:
        """Reconstruct physical generations after the caller checked its replay."""
        manifest = CodingWorkerSegmentManifestV1.from_bytes(
            rooted.sibling(stem + ".segments.json").read_bytes(max_bytes=1024 * 1024),
            stream_id=stem,
        )
        if manifest.active_generation != retained.active_generation:
            raise manifest_changed()
        return CodingWorkerSegmentedHistoryV1(
            manifest=manifest,
            segments=(b"",) * retained.first_retained_generation + retained.segments,
        )

    def read_sealed(
        self,
        rooted: RootedFile,
        *,
        stem: str,
        seal: CodingWorkerSealedSegmentV1,
        may_be_absent: bool,
    ) -> bytes | None:
        raw = _optional(
            rooted, _segment_name(stem, seal.generation), limit=_MAX_SEGMENT_BYTES
        )
        head = _optional(
            rooted, _head_name(stem, seal.generation), limit=_MAX_HEAD_BYTES
        )
        if raw is None and not may_be_absent:
            raise self.error_type("coding_worker_v2_retained_segment_missing")
        if head is None and not may_be_absent:
            raise self.error_type("coding_worker_v2_retained_head_missing")
        if raw is not None and (
            len(raw) != seal.byte_count or sha256(raw).hexdigest() != seal.digest
        ):
            raise self.error_type("coding_worker_v2_sealed_segment_changed")
        if head is not None and head != _seal_head(stem, seal):
            raise self.error_type("coding_worker_v2_sealed_head_changed")
        return raw

    def read(self, rooted: RootedFile, *, stem: str) -> _HistoryT:
        """Verify owner, checkpoint, ledger, manifest, heads, and typed replay."""

        owner_raw = _optional(rooted, PRODUCT_OWNER_INDEX_NAME, limit=_MAX_INDEX_BYTES)
        if owner_raw is None:
            raise self.error_type("coding_worker_v2_owner_absent")
        owner = self.preparation.prepared_type._index_type.from_bytes(owner_raw)
        prepared = self.preparation.read(rooted)
        if prepared is None or prepared.index != owner:
            raise self.error_type("coding_worker_v2_preparation_unbound")
        return self.read_with_index(
            rooted, stem=stem, prepared=prepared, allow_ledger=True
        )

    def verify_precommit(
        self,
        rooted: RootedFile,
        *,
        stem: str,
        prepared: _PreparedMethods,
    ) -> _HistoryT:
        """Run the Product reader before publication; caller owns cutover locks."""

        if type(prepared) is not self.preparation.prepared_type:
            raise ValueError("Coding Worker V2 prepared history is invalid")
        if (
            _optional(rooted, PRODUCT_OWNER_INDEX_NAME, limit=_MAX_INDEX_BYTES)
            is not None
        ):
            raise self.error_type("coding_worker_v2_owner_already_present")
        if self.preparation.read(rooted) != prepared:
            raise self.error_type("coding_worker_v2_preparation_changed")
        return self.read_with_index(
            rooted, stem=stem, prepared=prepared, allow_ledger=False
        )

    def read_with_index(
        self,
        rooted: RootedFile,
        *,
        stem: str,
        prepared: _PreparedMethods,
        allow_ledger: bool,
    ) -> _HistoryT:
        owner = prepared.index
        streams = {item.stem: item for item in prepared.streams}
        if stem not in streams:
            raise ValueError("Coding Worker V2 stream name is invalid")
        stream: _StreamCutoverMethods = streams[stem]
        index = tuple(streams).index(stem)
        base = prepared.semantic_bases[index]
        checkpoints = self.checkpoints.read_writer_fence(
            rooted, scope_id=owner.scope_id, store_id=owner.store_id
        )
        if (
            len(checkpoints) < stream.checkpoint_revision
            or checkpoints[stream.checkpoint_revision - 1].record_digest
            != stream.checkpoint_digest
        ):
            raise self.error_type("coding_worker_v2_checkpoint_unanchored")
        raw_ledger = _optional(rooted, DELETION_LEDGER_NAME, limit=_MAX_LEDGER_BYTES)
        if raw_ledger is None:
            allowed_missing: frozenset[int] = frozenset()
        else:
            if not allow_ledger:
                raise self.error_type("coding_worker_v2_precommit_deletion_debt")
            ledger = self.ledger_type.from_bytes(raw_ledger)
            if ledger != self.ledger_type.from_prepared(prepared):
                raise self.error_type("coding_worker_v2_deletion_ledger_changed")
            allowed_missing = frozenset(
                generation
                for named_stem, generation, *_ in ledger.retired_seals
                if named_stem == stem
            )
        manifest_raw = _optional(
            rooted, stem + ".segments.json", limit=_MAX_MANIFEST_BYTES
        )
        if manifest_raw is None:
            raise self.error_type("coding_worker_v2_manifest_missing")
        manifest = CodingWorkerSegmentManifestV1.from_bytes(
            manifest_raw, stream_id=stem
        )
        old_sealed = (*stream.retired_sealed, *stream.retained_sealed)
        if (
            manifest.active_generation < stream.active_generation
            or manifest.sealed[: stream.active_generation] != old_sealed
        ):
            raise self.error_type("coding_worker_v2_manifest_changed")
        names, complete = rooted.scan_sibling_names(limit=_MAX_DIRECTORY_ENTRIES)
        if not complete:
            raise self.error_type("coding_worker_v2_inventory_capacity")
        expected = {stem + ".segments.json", stem + ".jsonl.lock"}
        expected.update(
            _segment_name(stem, n) for n in range(manifest.active_generation + 1)
        )
        expected.update(
            _head_name(stem, n) for n in range(manifest.active_generation + 1)
        )
        actual = {
            name
            for name in names
            if name.casefold().startswith((stem + ".", "." + stem + "."))
        }
        if not actual <= expected:
            raise self.error_type("coding_worker_v2_segment_orphan")
        retained: list[bytes] = []
        cutover_active_raw: bytes | None = None
        for seal in manifest.sealed:
            raw = self.read_sealed(
                rooted,
                stem=stem,
                seal=seal,
                may_be_absent=seal.generation in allowed_missing,
            )
            if seal.generation >= stream.first_retained_generation:
                if raw is None:
                    raise self.error_type("coding_worker_v2_retained_segment_missing")
                retained.append(raw)
            if seal.generation == stream.active_generation:
                cutover_active_raw = raw
        active = _optional(
            rooted,
            _segment_name(stem, manifest.active_generation),
            limit=_MAX_SEGMENT_BYTES,
        )
        if active is None:
            raise self.error_type("coding_worker_v2_active_missing")
        active_head = _optional(
            rooted,
            _head_name(stem, manifest.active_generation),
            limit=_MAX_HEAD_BYTES,
        )
        if active_head != _head_bytes(stem, manifest.active_generation, active):
            raise self.error_type("coding_worker_v2_active_head_changed")
        if manifest.active_generation == stream.active_generation:
            cutover_active_raw = active
        if (
            cutover_active_raw is None
            or len(cutover_active_raw) < stream.active_byte_count
            or sha256(cutover_active_raw[: stream.active_byte_count]).hexdigest()
            != stream.active_digest
        ):
            raise self.error_type("coding_worker_v2_cutover_prefix_changed")
        retained.append(active)
        total_revision = manifest.last_sealed_revision + active.count(b"\n")
        if total_revision < stream.total_revision:
            raise self.error_type("coding_worker_v2_revision_rolled_back")
        replay = base.replay_retained(tuple(retained))
        replay_revision = (
            cast(_ReceiptReplayFields, replay).last_issue_sequence
            if isinstance(
                replay, self.preparation.prepared_type._receipt_type._replay_type
            )
            else (
                cast(_ActivationReplayFields, replay).last_record.journal_revision
                if isinstance(
                    replay, self.preparation.prepared_type._activation_type._replay_type
                )
                else cast(
                    _OptInReplayFields
                    | _StartGateReplayFields
                    | _SupervisorReplayFields,
                    replay,
                ).last_revision
            )
        )
        if replay_revision != total_revision:
            raise self.error_type("coding_worker_v2_semantic_revision_changed")
        return cast(Callable[..., _HistoryT], self.history_type)(
            stem=stem,
            first_retained_generation=stream.first_retained_generation,
            active_generation=manifest.active_generation,
            segments=tuple(retained),
            last_revision=total_revision,
            replay=replay,
        )
