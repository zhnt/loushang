"""Typed cutover metadata over the existing five Worker stream projections."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from hashlib import sha256
from typing import ClassVar, Self, cast

from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .._segmented_history import (
    CodingWorkerSealedSegmentV1,
    CodingWorkerSegmentedHistoryV1,
)
from ._activation_base import _ActivationBaseMethods
from ._anchor import _AnchorMethods
from ._base_codec import _BaseWireMethods, _unchanged
from ._checkpoint import _CheckpointMethods, checkpoint_chain_matches
from ._no_effect import _NoEffectArchiveMethods
from ._opt_in import _OptInBaseMethods
from ._preview import _PreviewMethods
from ._receipts import _ReceiptBaseMethods
from ._snapshot import CODING_WORKER_HISTORY_STREAM_STEMS, _SnapshotMethods
from ._start_gate import _StartGateBaseMethods
from ._supervisor import _SupervisorBaseMethods

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_STREAM_BYTES = 1024 * 1024
_MAX_INDEX_BYTES = 4096
_MAX_GENERATIONS = 65536


class _StreamCutoverMethods(_BaseWireMethods):
    __slots__ = ()

    stem: str
    checkpoint_revision: int
    checkpoint_digest: str
    source_fingerprint: str
    first_retained_generation: int
    first_retained_revision: int
    active_generation: int
    retired_sealed: tuple[CodingWorkerSealedSegmentV1, ...]
    retained_sealed: tuple[CodingWorkerSealedSegmentV1, ...]
    active_byte_count: int
    active_digest: str
    total_revision: int
    semantic_base_digest: str
    version: int = 2

    _activation_type: ClassVar[type[_ActivationBaseMethods]]
    _checkpoint_type: ClassVar[type[_CheckpointMethods]]
    _snapshot_type: ClassVar[type[_SnapshotMethods]]
    _opt_in_type: ClassVar[type[_OptInBaseMethods]]
    _receipt_type: ClassVar[type[_ReceiptBaseMethods]]
    _gate_type: ClassVar[type[_StartGateBaseMethods]]
    _preview_type: ClassVar[type[_PreviewMethods]]
    _supervisor_type: ClassVar[type[_SupervisorBaseMethods]]

    _wire_label = "Coding Worker V2 stream cutover"
    _wire_lists = ("retiredSealed", "retainedSealed")
    _wire_max_bytes = _MAX_STREAM_BYTES
    # The original stream encoder was unbounded; only its reader had this limit.
    _wire_bound_output = False

    @classmethod
    def _make_wire_schema(cls) -> RecordSchema:
        return RecordSchema.for_dataclass(
            cls,
            _unchanged,
            RecordField(
                "retired_sealed",
                encoder=lambda xs: [x.to_dict() for x in xs],
                decoder=lambda xs: tuple(
                    CodingWorkerSealedSegmentV1.from_dict(x) for x in xs
                ),
            ),
            RecordField(
                "retained_sealed",
                encoder=lambda xs: [x.to_dict() for x in xs],
                decoder=lambda xs: tuple(
                    CodingWorkerSealedSegmentV1.from_dict(x) for x in xs
                ),
            ),
        )

    def __post_init__(self) -> None:
        if (
            type(self.stem) is not str
            or self.stem not in CODING_WORKER_HISTORY_STREAM_STEMS
            or type(self.checkpoint_revision) is not int
            or self.checkpoint_revision < 1
            or type(self.checkpoint_digest) is not str
            or _DIGEST.fullmatch(self.checkpoint_digest) is None
            or type(self.source_fingerprint) is not str
            or _DIGEST.fullmatch(self.source_fingerprint) is None
            or type(self.first_retained_generation) is not int
            or self.first_retained_generation < 0
            or type(self.first_retained_revision) is not int
            or self.first_retained_revision
            < (1 if self.first_retained_generation == 0 else 2)
            or (
                self.first_retained_generation == 0
                and (
                    self.stem != "worker-supervisor"
                    or self.first_retained_revision != 1
                )
            )
            or type(self.active_generation) is not int
            or not self.first_retained_generation
            <= self.active_generation
            <= _MAX_GENERATIONS
            or type(self.retired_sealed) is not tuple
            or len(self.retired_sealed) != self.first_retained_generation
            or type(self.retained_sealed) is not tuple
            or len(self.retained_sealed)
            != self.active_generation - self.first_retained_generation
            or type(self.active_byte_count) is not int
            or self.active_byte_count < 0
            or type(self.active_digest) is not str
            or _DIGEST.fullmatch(self.active_digest) is None
            or type(self.total_revision) is not int
            or self.total_revision < self.first_retained_revision - 1
            or type(self.semantic_base_digest) is not str
            or _DIGEST.fullmatch(self.semantic_base_digest) is None
            or type(self.version) is not int
            or self.version != 2
        ):
            raise ValueError("Coding Worker V2 stream cutover is invalid")
        expected_revision = 1
        for generation, seal in enumerate(
            (*self.retired_sealed, *self.retained_sealed)
        ):
            if (
                type(seal) is not CodingWorkerSealedSegmentV1
                or seal.generation != generation
                or seal.first_revision != expected_revision
            ):
                raise ValueError("Coding Worker V2 segment chain is invalid")
            expected_revision = seal.last_revision + 1
        if (
            (0 if not self.retired_sealed else self.retired_sealed[-1].last_revision)
            + 1
            != self.first_retained_revision
            or self.total_revision < expected_revision - 1
            or (self.active_byte_count == 0)
            != (self.total_revision == expected_revision - 1)
        ):
            raise ValueError("Coding Worker V2 revision boundary is invalid")
        cast(Callable[..., _SnapshotMethods], self._snapshot_type)(
            stem=self.stem,
            active_generation=self.active_generation,
            last_sealed_revision=expected_revision - 1,
            total_revision=self.total_revision,
            segment_byte_counts=(
                *(seal.byte_count for seal in self.retired_sealed),
                *(seal.byte_count for seal in self.retained_sealed),
                self.active_byte_count,
            ),
            segment_digests=(
                *(seal.digest for seal in self.retired_sealed),
                *(seal.digest for seal in self.retained_sealed),
                self.active_digest,
            ),
            fingerprint=self.source_fingerprint,
        )

    @classmethod
    def from_preview(
        cls,
        *,
        preview: _PreviewMethods,
        history: CodingWorkerSegmentedHistoryV1,
        semantic_base_digest: str,
    ) -> Self:
        """Prepare candidate metadata from exact V1 bytes, without publishing."""

        if (
            type(preview) is not cls._preview_type
            or type(history) is not CodingWorkerSegmentedHistoryV1
            or history.manifest is None
            or history.manifest.stream_id != preview.stem
            or history.active_generation != preview.retained_generations[-1]
            or len(history.segments) != history.active_generation + 1
        ):
            raise ValueError("Coding Worker V2 preview source is invalid")
        snapshot = cls._snapshot_type.capture(
            stem=preview.stem,
            active_generation=history.active_generation,
            last_sealed_revision=history.last_sealed_revision,
            segments=history.segments,
        )
        if (
            snapshot.fingerprint != preview.source_fingerprint
            or sha256(
                canonical_json_bytes(
                    [
                        seal.to_dict()
                        for seal in history.manifest.sealed[
                            : preview.first_retained_generation
                        ]
                    ]
                )
            ).hexdigest()
            != preview.retired_sealed_digest
        ):
            raise ValueError("Coding Worker V2 preview source changed")
        return cast(Callable[..., Self], cls)(
            stem=preview.stem,
            checkpoint_revision=preview.checkpoint_revision,
            checkpoint_digest=preview.checkpoint_digest,
            source_fingerprint=preview.source_fingerprint,
            first_retained_generation=preview.first_retained_generation,
            first_retained_revision=preview.first_retained_revision,
            active_generation=history.active_generation,
            retired_sealed=history.manifest.sealed[: preview.first_retained_generation],
            retained_sealed=history.manifest.sealed[
                preview.first_retained_generation :
            ],
            active_byte_count=len(history.active_raw),
            active_digest=sha256(history.active_raw).hexdigest(),
            total_revision=snapshot.total_revision,
            semantic_base_digest=semantic_base_digest,
        )

    @classmethod
    def from_opt_in_base(
        cls,
        *,
        checkpoint: _CheckpointMethods,
        preview: _PreviewMethods,
        history: CodingWorkerSegmentedHistoryV1,
        semantic_base: _OptInBaseMethods,
    ) -> Self:
        """Bind the opt-in projection to its exact retired prefix."""
        return cls._from_projected_base(
            checkpoint=checkpoint,
            preview=preview,
            history=history,
            semantic_base=semantic_base,
            base_type=cls._opt_in_type,
            stream_index=0,
            stem="worker-opt-in",
            revision_name="cutoff_revision",
            error="Coding Worker V2 opt-in semantic base differs",
        )

    @classmethod
    def from_receipt_base(
        cls,
        *,
        checkpoint: _CheckpointMethods,
        preview: _PreviewMethods,
        history: CodingWorkerSegmentedHistoryV1,
        semantic_base: _ReceiptBaseMethods,
    ) -> Self:
        """Bind a receipt waterline and tombstones to their exact prefix."""
        return cls._from_projected_base(
            checkpoint=checkpoint,
            preview=preview,
            history=history,
            semantic_base=semantic_base,
            base_type=cls._receipt_type,
            stream_index=1,
            stem="worker-activation-receipts",
            revision_name="last_issue_sequence",
            error="Coding Worker V2 receipt semantic base differs",
        )

    @classmethod
    def from_activation_base(
        cls,
        *,
        checkpoint: _CheckpointMethods,
        preview: _PreviewMethods,
        history: CodingWorkerSegmentedHistoryV1,
        semantic_base: _ActivationBaseMethods,
    ) -> Self:
        """Bind the C5 snapshot and retired IDs to their exact prefix."""
        return cls._from_projected_base(
            checkpoint=checkpoint,
            preview=preview,
            history=history,
            semantic_base=semantic_base,
            base_type=cls._activation_type,
            stream_index=2,
            stem="worker-activation-state",
            revision_name="cutoff_revision",
            error="Coding Worker V2 C5 semantic base differs",
        )

    @classmethod
    def _from_projected_base(
        cls,
        *,
        checkpoint: _CheckpointMethods,
        preview: _PreviewMethods,
        history: CodingWorkerSegmentedHistoryV1,
        semantic_base: _OptInBaseMethods | _ReceiptBaseMethods | _ActivationBaseMethods,
        base_type: type[_OptInBaseMethods]
        | type[_ReceiptBaseMethods]
        | type[_ActivationBaseMethods],
        stream_index: int,
        stem: str,
        revision_name: str,
        error: str,
    ) -> Self:
        if (
            type(checkpoint) is not cls._checkpoint_type
            or type(preview) is not cls._preview_type
            or type(semantic_base) is not base_type
            or preview.stem != stem
            or preview.checkpoint_revision != checkpoint.journal_revision
            or preview.checkpoint_digest != checkpoint.record_digest
            or preview.source_fingerprint
            != checkpoint.stream_snapshots[stream_index].fingerprint
            or semantic_base.scope_id != checkpoint.scope_id
            or semantic_base.first_retained_generation
            != preview.first_retained_generation
            or getattr(semantic_base, revision_name) + 1
            != preview.first_retained_revision
            or semantic_base.retired_sealed_digest != preview.retired_sealed_digest
        ):
            raise ValueError(error)
        projected = base_type.from_v1_history(
            history=history,
            scope_id=checkpoint.scope_id,
            first_retained_generation=preview.first_retained_generation,
        )
        if semantic_base != projected:
            raise ValueError(error)
        semantic_base.replay_retained(
            history.segments[preview.first_retained_generation :]
        )
        return cls.from_preview(
            preview=preview,
            history=history,
            semantic_base_digest=sha256(semantic_base.to_bytes()).hexdigest(),
        )

    @classmethod
    def from_start_gate_base(
        cls,
        *,
        checkpoints: tuple[_CheckpointMethods, ...],
        preview: _PreviewMethods,
        history: CodingWorkerSegmentedHistoryV1,
        semantic_base: _StartGateBaseMethods,
    ) -> Self:
        """Bind current gates and the full checkpoint attempt tombstone set."""

        if (
            type(checkpoints) is not tuple
            or not checkpoints
            or any(type(item) is not cls._checkpoint_type for item in checkpoints)
            or type(preview) is not cls._preview_type
            or type(semantic_base) is not cls._gate_type
        ):
            raise ValueError("Coding Worker V2 Start Gate semantic base differs")
        checkpoint = checkpoints[-1]
        if not checkpoint_chain_matches(checkpoints, checkpoint):
            raise ValueError("Coding Worker V2 Start Gate checkpoint chain differs")
        retired_ids = tuple(
            sorted(
                {
                    attempt_id
                    for item in checkpoints
                    for attempt_id in item.new_attempt_ids
                }
            )
        )
        if len(retired_ids) != sum(
            len(item.new_attempt_ids) for item in checkpoints
        ) or (
            preview.stem != "worker-start-gates"
            or preview.checkpoint_revision != checkpoint.journal_revision
            or preview.checkpoint_digest != checkpoint.record_digest
            or preview.source_fingerprint != checkpoint.stream_snapshots[3].fingerprint
            or semantic_base.scope_id != checkpoint.scope_id
            or semantic_base.first_retained_generation
            != preview.first_retained_generation
            or semantic_base.cutoff_revision + 1 != preview.first_retained_revision
            or semantic_base.retired_sealed_digest != preview.retired_sealed_digest
            or semantic_base.retired_attempt_ids != retired_ids
        ):
            raise ValueError("Coding Worker V2 Start Gate semantic base differs")
        projected = cls._gate_type.from_v1_history(
            history=history,
            scope_id=checkpoint.scope_id,
            first_retained_generation=preview.first_retained_generation,
            retired_attempt_ids=retired_ids,
        )
        if semantic_base != projected:
            raise ValueError("Coding Worker V2 Start Gate semantic base differs")
        semantic_base.replay_retained(
            history.segments[preview.first_retained_generation :]
        )
        return cls.from_preview(
            preview=preview,
            history=history,
            semantic_base_digest=sha256(semantic_base.to_bytes()).hexdigest(),
        )

    @classmethod
    def from_supervisor_base(
        cls,
        *,
        checkpoints: tuple[_CheckpointMethods, ...],
        preview: _PreviewMethods,
        history: CodingWorkerSegmentedHistoryV1,
        semantic_base: _SupervisorBaseMethods,
        no_effect_attempt_ids: tuple[str, ...] = (),
    ) -> Self:
        """Bind per-key epoch/retry state to the complete checkpoint chain."""

        if (
            type(checkpoints) is not tuple
            or not checkpoints
            or any(type(item) is not cls._checkpoint_type for item in checkpoints)
            or type(preview) is not cls._preview_type
            or type(semantic_base) is not cls._supervisor_type
            or type(no_effect_attempt_ids) is not tuple
            or any(type(item) is not str for item in no_effect_attempt_ids)
            or no_effect_attempt_ids != tuple(sorted(set(no_effect_attempt_ids)))
        ):
            raise ValueError("Coding Worker V2 Supervisor semantic base differs")
        checkpoint = checkpoints[-1]
        if not checkpoint_chain_matches(checkpoints, checkpoint):
            raise ValueError("Coding Worker V2 Supervisor checkpoint chain differs")
        checkpoint_ids = tuple(
            sorted(
                {
                    attempt_id
                    for item in checkpoints
                    for attempt_id in item.new_attempt_ids
                }
            )
        )
        retired_ids = tuple(
            item for item in checkpoint_ids if item not in no_effect_attempt_ids
        )
        if (
            not set(no_effect_attempt_ids) <= set(checkpoint_ids)
            or len(checkpoint_ids)
            != sum(len(item.new_attempt_ids) for item in checkpoints)
        ) or (
            preview.stem != "worker-supervisor"
            or preview.checkpoint_revision != checkpoint.journal_revision
            or preview.checkpoint_digest != checkpoint.record_digest
            or preview.source_fingerprint != checkpoint.stream_snapshots[4].fingerprint
            or semantic_base.scope_id != checkpoint.scope_id
            or semantic_base.first_retained_generation
            != preview.first_retained_generation
            or semantic_base.cutoff_revision + 1 != preview.first_retained_revision
            or semantic_base.retired_sealed_digest != preview.retired_sealed_digest
            or semantic_base.retired_attempt_ids != retired_ids
        ):
            raise ValueError("Coding Worker V2 Supervisor semantic base differs")
        projected = cls._supervisor_type.from_v1_history(
            history=history,
            scope_id=checkpoint.scope_id,
            first_retained_generation=preview.first_retained_generation,
            retired_attempt_ids=retired_ids,
        )
        if semantic_base != projected:
            raise ValueError("Coding Worker V2 Supervisor semantic base differs")
        replay = semantic_base.replay_retained(
            history.segments[preview.first_retained_generation :]
        )
        if (
            tuple(
                (item.supervisor_key, item.last_record.supervisor_epoch)
                for item in replay.key_states
            )
            != checkpoint.supervisor_epoch_high_water
        ):
            raise ValueError("Coding Worker V2 Supervisor epoch waterline differs")
        return cls.from_preview(
            preview=preview,
            history=history,
            semantic_base_digest=sha256(semantic_base.to_bytes()).hexdigest(),
        )


class _IndexMethods:
    __slots__ = ()

    scope_id: str
    store_id: str
    checkpoint_revision: int
    checkpoint_digest: str
    stream_digests: tuple[tuple[str, str], ...]
    record_digest: str
    no_effect_archive_digest: str | None = None
    version: int = 2

    _anchor_type: ClassVar[type[_AnchorMethods]]
    _checkpoint_type: ClassVar[type[_CheckpointMethods]]
    _archive_type: ClassVar[type[_NoEffectArchiveMethods]]
    _stream_type: ClassVar[type[_StreamCutoverMethods]]

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.store_id) is not str
            or not self.store_id
            or len(self.store_id) > 128
            or type(self.checkpoint_revision) is not int
            or self.checkpoint_revision < 1
            or type(self.checkpoint_digest) is not str
            or _DIGEST.fullmatch(self.checkpoint_digest) is None
            or type(self.stream_digests) is not tuple
            or tuple(stem for stem, _digest in self.stream_digests)
            != CODING_WORKER_HISTORY_STREAM_STEMS
            or any(
                type(digest) is not str or _DIGEST.fullmatch(digest) is None
                for _stem, digest in self.stream_digests
            )
            or (
                self.no_effect_archive_digest is not None
                and (
                    type(self.no_effect_archive_digest) is not str
                    or _DIGEST.fullmatch(self.no_effect_archive_digest) is None
                )
            )
            or type(self.version) is not int
            or self.version != 2
            or type(self.record_digest) is not str
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Coding Worker V2 Product cutover index is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "checkpointDigest": self.checkpoint_digest,
            "checkpointRevision": self.checkpoint_revision,
            "scopeId": self.scope_id,
            "storeId": self.store_id,
            "streamDigests": [list(item) for item in self.stream_digests],
            "version": self.version,
        }
        if self.no_effect_archive_digest is not None:
            result["noEffectArchiveDigest"] = self.no_effect_archive_digest
        return result

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(
            {**self._unsigned_dict(), "recordDigest": self.record_digest}
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_INDEX_BYTES:
            raise ValueError("Coding Worker V2 Product cutover index bytes are invalid")
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                not in (
                    {
                        "checkpointDigest",
                        "checkpointRevision",
                        "recordDigest",
                        "scopeId",
                        "storeId",
                        "streamDigests",
                        "version",
                    },
                    {
                        "checkpointDigest",
                        "checkpointRevision",
                        "noEffectArchiveDigest",
                        "recordDigest",
                        "scopeId",
                        "storeId",
                        "streamDigests",
                        "version",
                    },
                )
                or type(value["streamDigests"]) is not list
            ):
                raise ValueError(
                    "Coding Worker V2 Product cutover index fields changed"
                )
            record = cast(Callable[..., Self], cls)(
                scope_id=value["scopeId"],
                store_id=value["storeId"],
                checkpoint_revision=value["checkpointRevision"],
                checkpoint_digest=value["checkpointDigest"],
                stream_digests=tuple(
                    tuple(item) if type(item) is list else item
                    for item in value["streamDigests"]
                ),
                record_digest=value["recordDigest"],
                no_effect_archive_digest=value.get("noEffectArchiveDigest"),
                version=value["version"],
            )
            if record.to_bytes() != raw:
                raise ValueError(
                    "Coding Worker V2 Product cutover index encoding changed"
                )
            return record
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise ValueError(
                "Coding Worker V2 Product cutover index bytes are invalid"
            ) from exc

    @classmethod
    def from_streams(
        cls,
        *,
        checkpoint: _CheckpointMethods,
        anchor: _AnchorMethods,
        streams: tuple[_StreamCutoverMethods, ...],
        no_effect_archive: _NoEffectArchiveMethods | None = None,
    ) -> Self:
        """Bind five prepared stream records to one committed checkpoint tip."""

        if (
            type(checkpoint) is not cls._checkpoint_type
            or type(anchor) is not cls._anchor_type
            or type(streams) is not tuple
            or tuple(type(item) for item in streams)
            != (cls._stream_type,) * len(CODING_WORKER_HISTORY_STREAM_STEMS)
            or tuple(item.stem for item in streams)
            != CODING_WORKER_HISTORY_STREAM_STEMS
            or (
                no_effect_archive is not None
                and (
                    type(no_effect_archive) is not cls._archive_type
                    or not no_effect_archive.proofs
                    or no_effect_archive.scope_id != checkpoint.scope_id
                    or no_effect_archive.store_id != checkpoint.store_id
                    or no_effect_archive.checkpoint_digest != checkpoint.record_digest
                )
            )
            or checkpoint.scope_id != anchor.scope_id
            or checkpoint.store_id != anchor.store_id
            or checkpoint.journal_revision != anchor.latest_revision
            or checkpoint.record_digest != anchor.latest_digest
            or any(
                item.checkpoint_revision != checkpoint.journal_revision
                or item.checkpoint_digest != checkpoint.record_digest
                or item.source_fingerprint != snapshot.fingerprint
                for item, snapshot in zip(
                    streams, checkpoint.stream_snapshots, strict=True
                )
            )
        ):
            raise ValueError("Coding Worker V2 Product cutover sources differ")
        unsigned = {
            "checkpointDigest": checkpoint.record_digest,
            "checkpointRevision": checkpoint.journal_revision,
            "scopeId": checkpoint.scope_id,
            "storeId": checkpoint.store_id,
            "streamDigests": [
                [item.stem, sha256(item.to_bytes()).hexdigest()] for item in streams
            ],
            "version": 2,
        }
        archive_digest = (
            None
            if no_effect_archive is None
            else sha256(no_effect_archive.to_bytes()).hexdigest()
        )
        if archive_digest is not None:
            unsigned["noEffectArchiveDigest"] = archive_digest
        return cast(Callable[..., Self], cls)(
            scope_id=checkpoint.scope_id,
            store_id=checkpoint.store_id,
            checkpoint_revision=checkpoint.journal_revision,
            checkpoint_digest=checkpoint.record_digest,
            stream_digests=tuple(
                (item.stem, sha256(item.to_bytes()).hexdigest()) for item in streams
            ),
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
            no_effect_archive_digest=archive_digest,
        )
