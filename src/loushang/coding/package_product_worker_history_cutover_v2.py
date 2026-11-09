"""Inert V2 Worker history cutover records; no publication or deletion authority.

The Product cutover index commits all five stream records together. These
types validate candidate bytes only. V1 readers and writers remain authoritative
until all five typed semantic bases and a durable cutover protocol exist.
"""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.worker.history._cutover import (
    _IndexMethods,
    _StreamCutoverMethods,
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
)
from .package_product_worker_history_stream_snapshot import (
    CodingWorkerHistoryStreamSnapshotV1,
)
from .package_product_worker_no_effect_archive_v2 import (
    CodingWorkerNoEffectArchiveV2,
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


@dataclass(frozen=True, slots=True)
class CodingWorkerStreamCutoverV2(_StreamCutoverMethods):
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
    _activation_type = CodingWorkerActivationSemanticBaseV2
    _checkpoint_type = CodingWorkerHistoryCheckpointV1
    _snapshot_type = CodingWorkerHistoryStreamSnapshotV1
    _opt_in_type = CodingWorkerOptInSemanticBaseV2
    _receipt_type = CodingWorkerReceiptSemanticBaseV2
    _gate_type = CodingWorkerStartGateSemanticBaseV2
    _preview_type = CodingWorkerStreamRetirementPreviewV2
    _supervisor_type = CodingWorkerSupervisorSemanticBaseV2


@dataclass(frozen=True, slots=True)
class CodingWorkerProductCutoverIndexV2(_IndexMethods):
    scope_id: str
    store_id: str
    checkpoint_revision: int
    checkpoint_digest: str
    stream_digests: tuple[tuple[str, str], ...]
    record_digest: str
    no_effect_archive_digest: str | None = None
    version: int = 2
    _anchor_type = CodingWorkerCheckpointAnchorV1
    _checkpoint_type = CodingWorkerHistoryCheckpointV1
    _archive_type = CodingWorkerNoEffectArchiveV2
    _stream_type = CodingWorkerStreamCutoverV2


CodingWorkerStreamCutoverV2._wire_schema = (
    CodingWorkerStreamCutoverV2._make_wire_schema()
)


__all__ = ["CodingWorkerProductCutoverIndexV2", "CodingWorkerStreamCutoverV2"]
