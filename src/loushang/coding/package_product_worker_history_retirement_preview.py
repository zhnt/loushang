"""Read-only structural preview for a first Worker history stream cutover.

This does not provide a semantic base, publish a manifest, or delete bytes.
"""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.worker.history._preview import _PreviewMethods

from .package_product_worker_history_checkpoint import (
    CodingWorkerHistoryCheckpointV1,
)
from .package_product_worker_history_checkpoint_anchor import (
    CodingWorkerCheckpointAnchorV1,
)
from .package_product_worker_history_segments import (
    CodingWorkerSegmentedHistoryV1,
)
from .package_product_worker_history_stream_snapshot import (
    CodingWorkerHistoryStreamSnapshotV1,
)


class CodingWorkerRetirementPreviewError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerStreamRetirementPreviewV2(_PreviewMethods):
    stem: str
    checkpoint_revision: int
    checkpoint_digest: str
    source_fingerprint: str
    first_retained_generation: int
    first_retained_revision: int
    retired_sealed_digest: str
    retired_generations: tuple[int, ...]
    retained_generations: tuple[int, ...]
    deletion_authorized: bool = False
    _anchor_type = CodingWorkerCheckpointAnchorV1
    _checkpoint_type = CodingWorkerHistoryCheckpointV1
    _snapshot_type = CodingWorkerHistoryStreamSnapshotV1
    _error_type = CodingWorkerRetirementPreviewError


def preview_first_coding_worker_stream_retirement_v2(
    *,
    checkpoint: CodingWorkerHistoryCheckpointV1,
    anchor: CodingWorkerCheckpointAnchorV1,
    history: CodingWorkerSegmentedHistoryV1,
    stem: str,
    first_retained_generation: int,
) -> CodingWorkerStreamRetirementPreviewV2:
    return CodingWorkerStreamRetirementPreviewV2._from_sources(
        checkpoint=checkpoint,
        anchor=anchor,
        history=history,
        stem=stem,
        first_retained_generation=first_retained_generation,
    )


__all__ = [
    "CodingWorkerRetirementPreviewError",
    "CodingWorkerStreamRetirementPreviewV2",
    "preview_first_coding_worker_stream_retirement_v2",
]
