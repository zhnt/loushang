"""Inert V2 Worker history cutover records; no publication or deletion authority.

The Product cutover index commits all five stream records together. These
types validate candidate bytes only. V1 readers and writers remain authoritative
until all five typed semantic bases and a durable cutover protocol exist.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_product_worker_activation_base_v2 import (
    CodingWorkerActivationSemanticBaseV2,
)
from .package_product_worker_history_checkpoint import (
    CodingWorkerHistoryCheckpointV1,
)
from .package_product_worker_history_checkpoint_anchor import (
    CodingWorkerCheckpointAnchorV1,
)
from .package_product_worker_history_retirement_preview import (
    CodingWorkerStreamRetirementPreviewV2,
)
from .package_product_worker_history_segments import (
    CodingWorkerSealedSegmentV1,
    CodingWorkerSegmentedHistoryV1,
)
from .package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
    CodingWorkerHistoryStreamSnapshotV1,
)
from .package_product_worker_opt_in_base_v2 import (
    CodingWorkerOptInSemanticBaseV2,
)
from .package_product_worker_receipt_base_v2 import (
    CodingWorkerReceiptSemanticBaseV2,
)
from .package_product_worker_start_gate_base_v2 import (
    CodingWorkerStartGateSemanticBaseV2,
)
from .package_product_worker_supervisor_base_v2 import (
    CodingWorkerSupervisorSemanticBaseV2,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_STREAM_BYTES = 1024 * 1024
_MAX_INDEX_BYTES = 4096
_MAX_GENERATIONS = 65536


@dataclass(frozen=True, slots=True)
class CodingWorkerStreamCutoverV2:
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
            or self.first_retained_generation < 1
            or type(self.first_retained_revision) is not int
            or self.first_retained_revision < 2
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
            self.retired_sealed[-1].last_revision + 1 != self.first_retained_revision
            or self.total_revision < expected_revision - 1
            or (self.active_byte_count == 0)
            != (self.total_revision == expected_revision - 1)
        ):
            raise ValueError("Coding Worker V2 revision boundary is invalid")
        CodingWorkerHistoryStreamSnapshotV1(
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

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "activeByteCount": self.active_byte_count,
                "activeDigest": self.active_digest,
                "activeGeneration": self.active_generation,
                "checkpointDigest": self.checkpoint_digest,
                "checkpointRevision": self.checkpoint_revision,
                "firstRetainedGeneration": self.first_retained_generation,
                "firstRetainedRevision": self.first_retained_revision,
                "retainedSealed": [item.to_dict() for item in self.retained_sealed],
                "retiredSealed": [item.to_dict() for item in self.retired_sealed],
                "semanticBaseDigest": self.semantic_base_digest,
                "sourceFingerprint": self.source_fingerprint,
                "stem": self.stem,
                "totalRevision": self.total_revision,
                "version": self.version,
            }
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWorkerStreamCutoverV2:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_STREAM_BYTES:
            raise ValueError("Coding Worker V2 stream cutover bytes are invalid")
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "activeByteCount",
                    "activeDigest",
                    "activeGeneration",
                    "checkpointDigest",
                    "checkpointRevision",
                    "firstRetainedGeneration",
                    "firstRetainedRevision",
                    "retainedSealed",
                    "retiredSealed",
                    "semanticBaseDigest",
                    "sourceFingerprint",
                    "stem",
                    "totalRevision",
                    "version",
                }
                or type(value["retiredSealed"]) is not list
                or type(value["retainedSealed"]) is not list
            ):
                raise ValueError("Coding Worker V2 stream cutover fields changed")
            record = cls(
                stem=value["stem"],
                checkpoint_revision=value["checkpointRevision"],
                checkpoint_digest=value["checkpointDigest"],
                source_fingerprint=value["sourceFingerprint"],
                first_retained_generation=value["firstRetainedGeneration"],
                first_retained_revision=value["firstRetainedRevision"],
                active_generation=value["activeGeneration"],
                retired_sealed=tuple(
                    CodingWorkerSealedSegmentV1.from_dict(item)
                    for item in value["retiredSealed"]
                ),
                retained_sealed=tuple(
                    CodingWorkerSealedSegmentV1.from_dict(item)
                    for item in value["retainedSealed"]
                ),
                active_byte_count=value["activeByteCount"],
                active_digest=value["activeDigest"],
                total_revision=value["totalRevision"],
                semantic_base_digest=value["semanticBaseDigest"],
                version=value["version"],
            )
            if record.to_bytes() != raw:
                raise ValueError("Coding Worker V2 stream cutover encoding changed")
            return record
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise ValueError(
                "Coding Worker V2 stream cutover bytes are invalid"
            ) from exc

    @classmethod
    def from_preview(
        cls,
        *,
        preview: CodingWorkerStreamRetirementPreviewV2,
        history: CodingWorkerSegmentedHistoryV1,
        semantic_base_digest: str,
    ) -> CodingWorkerStreamCutoverV2:
        """Prepare candidate metadata from exact V1 bytes, without publishing."""

        if (
            type(preview) is not CodingWorkerStreamRetirementPreviewV2
            or type(history) is not CodingWorkerSegmentedHistoryV1
            or history.manifest is None
            or history.manifest.stream_id != preview.stem
            or history.active_generation != preview.retained_generations[-1]
            or len(history.segments) != history.active_generation + 1
        ):
            raise ValueError("Coding Worker V2 preview source is invalid")
        snapshot = CodingWorkerHistoryStreamSnapshotV1.capture(
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
        return cls(
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
        checkpoint: CodingWorkerHistoryCheckpointV1,
        preview: CodingWorkerStreamRetirementPreviewV2,
        history: CodingWorkerSegmentedHistoryV1,
        semantic_base: CodingWorkerOptInSemanticBaseV2,
    ) -> CodingWorkerStreamCutoverV2:
        """Bind the typed opt-in projection to the exact retired prefix."""

        if (
            type(checkpoint) is not CodingWorkerHistoryCheckpointV1
            or type(preview) is not CodingWorkerStreamRetirementPreviewV2
            or type(semantic_base) is not CodingWorkerOptInSemanticBaseV2
            or preview.stem != "worker-opt-in"
            or preview.checkpoint_revision != checkpoint.journal_revision
            or preview.checkpoint_digest != checkpoint.record_digest
            or preview.source_fingerprint != checkpoint.stream_snapshots[0].fingerprint
            or semantic_base.scope_id != checkpoint.scope_id
            or semantic_base.first_retained_generation
            != preview.first_retained_generation
            or semantic_base.cutoff_revision + 1 != preview.first_retained_revision
            or semantic_base.retired_sealed_digest != preview.retired_sealed_digest
        ):
            raise ValueError("Coding Worker V2 opt-in semantic base differs")
        projected = CodingWorkerOptInSemanticBaseV2.from_v1_history(
            history=history,
            scope_id=checkpoint.scope_id,
            first_retained_generation=preview.first_retained_generation,
        )
        if semantic_base != projected:
            raise ValueError("Coding Worker V2 opt-in semantic base differs")
        semantic_base.replay_retained(
            history.segments[preview.first_retained_generation :]
        )
        return cls.from_preview(
            preview=preview,
            history=history,
            semantic_base_digest=sha256(semantic_base.to_bytes()).hexdigest(),
        )

    @classmethod
    def from_receipt_base(
        cls,
        *,
        checkpoint: CodingWorkerHistoryCheckpointV1,
        preview: CodingWorkerStreamRetirementPreviewV2,
        history: CodingWorkerSegmentedHistoryV1,
        semantic_base: CodingWorkerReceiptSemanticBaseV2,
    ) -> CodingWorkerStreamCutoverV2:
        """Bind a projected receipt waterline and tombstones to one prefix."""

        if (
            type(checkpoint) is not CodingWorkerHistoryCheckpointV1
            or type(preview) is not CodingWorkerStreamRetirementPreviewV2
            or type(semantic_base) is not CodingWorkerReceiptSemanticBaseV2
            or preview.stem != "worker-activation-receipts"
            or preview.checkpoint_revision != checkpoint.journal_revision
            or preview.checkpoint_digest != checkpoint.record_digest
            or preview.source_fingerprint != checkpoint.stream_snapshots[1].fingerprint
            or semantic_base.scope_id != checkpoint.scope_id
            or semantic_base.first_retained_generation
            != preview.first_retained_generation
            or semantic_base.last_issue_sequence + 1 != preview.first_retained_revision
            or semantic_base.retired_sealed_digest != preview.retired_sealed_digest
        ):
            raise ValueError("Coding Worker V2 receipt semantic base differs")
        projected = CodingWorkerReceiptSemanticBaseV2.from_v1_history(
            history=history,
            scope_id=checkpoint.scope_id,
            first_retained_generation=preview.first_retained_generation,
        )
        if semantic_base != projected:
            raise ValueError("Coding Worker V2 receipt semantic base differs")
        semantic_base.replay_retained(
            history.segments[preview.first_retained_generation :]
        )
        return cls.from_preview(
            preview=preview,
            history=history,
            semantic_base_digest=sha256(semantic_base.to_bytes()).hexdigest(),
        )

    @classmethod
    def from_activation_base(
        cls,
        *,
        checkpoint: CodingWorkerHistoryCheckpointV1,
        preview: CodingWorkerStreamRetirementPreviewV2,
        history: CodingWorkerSegmentedHistoryV1,
        semantic_base: CodingWorkerActivationSemanticBaseV2,
    ) -> CodingWorkerStreamCutoverV2:
        """Bind an exact C5 snapshot and retired IDs to its sealed prefix."""

        if (
            type(checkpoint) is not CodingWorkerHistoryCheckpointV1
            or type(preview) is not CodingWorkerStreamRetirementPreviewV2
            or type(semantic_base) is not CodingWorkerActivationSemanticBaseV2
            or preview.stem != "worker-activation-state"
            or preview.checkpoint_revision != checkpoint.journal_revision
            or preview.checkpoint_digest != checkpoint.record_digest
            or preview.source_fingerprint != checkpoint.stream_snapshots[2].fingerprint
            or semantic_base.scope_id != checkpoint.scope_id
            or semantic_base.first_retained_generation
            != preview.first_retained_generation
            or semantic_base.cutoff_revision + 1 != preview.first_retained_revision
            or semantic_base.retired_sealed_digest != preview.retired_sealed_digest
        ):
            raise ValueError("Coding Worker V2 C5 semantic base differs")
        projected = CodingWorkerActivationSemanticBaseV2.from_v1_history(
            history=history,
            scope_id=checkpoint.scope_id,
            first_retained_generation=preview.first_retained_generation,
        )
        if semantic_base != projected:
            raise ValueError("Coding Worker V2 C5 semantic base differs")
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
        checkpoints: tuple[CodingWorkerHistoryCheckpointV1, ...],
        preview: CodingWorkerStreamRetirementPreviewV2,
        history: CodingWorkerSegmentedHistoryV1,
        semantic_base: CodingWorkerStartGateSemanticBaseV2,
    ) -> CodingWorkerStreamCutoverV2:
        """Bind current gates and the full checkpoint attempt tombstone set."""

        if (
            type(checkpoints) is not tuple
            or not checkpoints
            or any(
                type(item) is not CodingWorkerHistoryCheckpointV1
                for item in checkpoints
            )
            or type(preview) is not CodingWorkerStreamRetirementPreviewV2
            or type(semantic_base) is not CodingWorkerStartGateSemanticBaseV2
        ):
            raise ValueError("Coding Worker V2 Start Gate semantic base differs")
        checkpoint = checkpoints[-1]
        if any(
            item.journal_revision != ordinal
            or item.scope_id != checkpoint.scope_id
            or item.store_id != checkpoint.store_id
            or item.previous_digest
            != ("" if ordinal == 1 else checkpoints[ordinal - 2].record_digest)
            for ordinal, item in enumerate(checkpoints, 1)
        ):
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
        projected = CodingWorkerStartGateSemanticBaseV2.from_v1_history(
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
        checkpoints: tuple[CodingWorkerHistoryCheckpointV1, ...],
        preview: CodingWorkerStreamRetirementPreviewV2,
        history: CodingWorkerSegmentedHistoryV1,
        semantic_base: CodingWorkerSupervisorSemanticBaseV2,
    ) -> CodingWorkerStreamCutoverV2:
        """Bind per-key epoch/retry state to the complete checkpoint chain."""

        if (
            type(checkpoints) is not tuple
            or not checkpoints
            or any(
                type(item) is not CodingWorkerHistoryCheckpointV1
                for item in checkpoints
            )
            or type(preview) is not CodingWorkerStreamRetirementPreviewV2
            or type(semantic_base) is not CodingWorkerSupervisorSemanticBaseV2
        ):
            raise ValueError("Coding Worker V2 Supervisor semantic base differs")
        checkpoint = checkpoints[-1]
        if any(
            item.journal_revision != ordinal
            or item.scope_id != checkpoint.scope_id
            or item.store_id != checkpoint.store_id
            or item.previous_digest
            != ("" if ordinal == 1 else checkpoints[ordinal - 2].record_digest)
            for ordinal, item in enumerate(checkpoints, 1)
        ):
            raise ValueError("Coding Worker V2 Supervisor checkpoint chain differs")
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
        projected = CodingWorkerSupervisorSemanticBaseV2.from_v1_history(
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


@dataclass(frozen=True, slots=True)
class CodingWorkerProductCutoverIndexV2:
    scope_id: str
    store_id: str
    checkpoint_revision: int
    checkpoint_digest: str
    stream_digests: tuple[tuple[str, str], ...]
    record_digest: str
    version: int = 2

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
            or type(self.version) is not int
            or self.version != 2
            or type(self.record_digest) is not str
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Coding Worker V2 Product cutover index is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "checkpointDigest": self.checkpoint_digest,
            "checkpointRevision": self.checkpoint_revision,
            "scopeId": self.scope_id,
            "storeId": self.store_id,
            "streamDigests": [list(item) for item in self.stream_digests],
            "version": self.version,
        }

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(
            {**self._unsigned_dict(), "recordDigest": self.record_digest}
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWorkerProductCutoverIndexV2:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_INDEX_BYTES:
            raise ValueError("Coding Worker V2 Product cutover index bytes are invalid")
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "checkpointDigest",
                    "checkpointRevision",
                    "recordDigest",
                    "scopeId",
                    "storeId",
                    "streamDigests",
                    "version",
                }
                or type(value["streamDigests"]) is not list
            ):
                raise ValueError(
                    "Coding Worker V2 Product cutover index fields changed"
                )
            record = cls(
                scope_id=value["scopeId"],
                store_id=value["storeId"],
                checkpoint_revision=value["checkpointRevision"],
                checkpoint_digest=value["checkpointDigest"],
                stream_digests=tuple(
                    tuple(item) if type(item) is list else item
                    for item in value["streamDigests"]
                ),
                record_digest=value["recordDigest"],
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
        checkpoint: CodingWorkerHistoryCheckpointV1,
        anchor: CodingWorkerCheckpointAnchorV1,
        streams: tuple[CodingWorkerStreamCutoverV2, ...],
    ) -> CodingWorkerProductCutoverIndexV2:
        """Bind five prepared stream records to one committed checkpoint tip."""

        if (
            type(checkpoint) is not CodingWorkerHistoryCheckpointV1
            or type(anchor) is not CodingWorkerCheckpointAnchorV1
            or type(streams) is not tuple
            or tuple(type(item) for item in streams)
            != (CodingWorkerStreamCutoverV2,) * len(CODING_WORKER_HISTORY_STREAM_STEMS)
            or tuple(item.stem for item in streams)
            != CODING_WORKER_HISTORY_STREAM_STEMS
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
        return cls(
            scope_id=checkpoint.scope_id,
            store_id=checkpoint.store_id,
            checkpoint_revision=checkpoint.journal_revision,
            checkpoint_digest=checkpoint.record_digest,
            stream_digests=tuple(
                (item.stem, sha256(item.to_bytes()).hexdigest()) for item in streams
            ),
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )


__all__ = ["CodingWorkerProductCutoverIndexV2", "CodingWorkerStreamCutoverV2"]
