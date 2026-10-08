"""Read-only structural preview for a first Worker history stream cutover.

This does not provide a semantic base, publish a manifest, or delete bytes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

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
    CODING_WORKER_HISTORY_STREAM_STEMS,
    CodingWorkerHistoryStreamSnapshotV1,
)


class CodingWorkerRetirementPreviewError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class CodingWorkerStreamRetirementPreviewV2:
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
            or type(self.retired_sealed_digest) is not str
            or _DIGEST.fullmatch(self.retired_sealed_digest) is None
            or type(self.retired_generations) is not tuple
            or self.retired_generations != tuple(range(self.first_retained_generation))
            or type(self.retained_generations) is not tuple
            or not self.retained_generations
            or self.retained_generations
            != tuple(
                range(
                    self.first_retained_generation,
                    self.first_retained_generation + len(self.retained_generations),
                )
            )
            or self.deletion_authorized is not False
        ):
            raise ValueError("Coding Worker retirement preview is invalid")


def preview_first_coding_worker_stream_retirement_v2(
    *,
    checkpoint: CodingWorkerHistoryCheckpointV1,
    anchor: CodingWorkerCheckpointAnchorV1,
    history: CodingWorkerSegmentedHistoryV1,
    stem: str,
    first_retained_generation: int,
) -> CodingWorkerStreamRetirementPreviewV2:
    """Bind one sealed V1 prefix to an anchored checkpoint without mutation."""

    if (
        type(checkpoint) is not CodingWorkerHistoryCheckpointV1
        or type(anchor) is not CodingWorkerCheckpointAnchorV1
        or type(history) is not CodingWorkerSegmentedHistoryV1
        or type(stem) is not str
        or stem not in CODING_WORKER_HISTORY_STREAM_STEMS
        or type(first_retained_generation) is not int
        or checkpoint.scope_id != anchor.scope_id
        or checkpoint.store_id != anchor.store_id
        or checkpoint.journal_revision != anchor.latest_revision
        or checkpoint.record_digest != anchor.latest_digest
    ):
        raise CodingWorkerRetirementPreviewError(
            "coding_worker_retirement_checkpoint_unanchored"
        )
    manifest = history.manifest
    if (
        manifest is None
        or manifest.stream_id != stem
        or not 1 <= first_retained_generation <= manifest.active_generation
        or len(history.segments) != manifest.active_generation + 1
    ):
        raise CodingWorkerRetirementPreviewError(
            "coding_worker_retirement_cutoff_unavailable"
        )
    matching = tuple(
        snapshot for snapshot in checkpoint.stream_snapshots if snapshot.stem == stem
    )
    if len(matching) != 1:
        raise CodingWorkerRetirementPreviewError(
            "coding_worker_retirement_source_unproven"
        )
    snapshot = CodingWorkerHistoryStreamSnapshotV1.capture(
        stem=stem,
        active_generation=history.active_generation,
        last_sealed_revision=history.last_sealed_revision,
        segments=history.segments,
    )
    if snapshot != matching[0] or any(
        len(raw) != seal.byte_count or sha256(raw).hexdigest() != seal.digest
        for raw, seal in zip(history.segments[:-1], manifest.sealed, strict=True)
    ):
        raise CodingWorkerRetirementPreviewError(
            "coding_worker_retirement_source_unproven"
        )
    retired = manifest.sealed[:first_retained_generation]
    return CodingWorkerStreamRetirementPreviewV2(
        stem=stem,
        checkpoint_revision=checkpoint.journal_revision,
        checkpoint_digest=checkpoint.record_digest,
        source_fingerprint=snapshot.fingerprint,
        first_retained_generation=first_retained_generation,
        first_retained_revision=retired[-1].last_revision + 1,
        retired_sealed_digest=sha256(
            canonical_json_bytes([item.to_dict() for item in retired])
        ).hexdigest(),
        retired_generations=tuple(item.generation for item in retired),
        retained_generations=tuple(
            range(first_retained_generation, history.active_generation + 1)
        ),
    )


__all__ = [
    "CodingWorkerRetirementPreviewError",
    "CodingWorkerStreamRetirementPreviewV2",
    "preview_first_coding_worker_stream_retirement_v2",
]
