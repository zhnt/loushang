"""Read-only exact sealed-prefix previews; no deletion authority."""

from __future__ import annotations

import re
from collections.abc import Callable
from hashlib import sha256
from typing import ClassVar, Self, cast

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .._segmented_history import (
    CodingWorkerSegmentedHistoryV1,
)
from ._anchor import _AnchorMethods
from ._checkpoint import _CheckpointMethods
from ._snapshot import CODING_WORKER_HISTORY_STREAM_STEMS, _SnapshotMethods

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class _PreviewMethods:
    __slots__ = ()

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

    _anchor_type: ClassVar[type[_AnchorMethods]]
    _checkpoint_type: ClassVar[type[_CheckpointMethods]]
    _snapshot_type: ClassVar[type[_SnapshotMethods]]
    _error_type: ClassVar[type[RuntimeError]]

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

    @classmethod
    def _from_sources(
        cls,
        *,
        checkpoint: _CheckpointMethods,
        anchor: _AnchorMethods,
        history: CodingWorkerSegmentedHistoryV1,
        stem: str,
        first_retained_generation: int,
    ) -> Self:
        """Bind one sealed V1 prefix to an anchored checkpoint without mutation."""

        if (
            type(checkpoint) is not cls._checkpoint_type
            or type(anchor) is not cls._anchor_type
            or type(history) is not CodingWorkerSegmentedHistoryV1
            or type(stem) is not str
            or stem not in CODING_WORKER_HISTORY_STREAM_STEMS
            or type(first_retained_generation) is not int
            or checkpoint.scope_id != anchor.scope_id
            or checkpoint.store_id != anchor.store_id
            or checkpoint.journal_revision != anchor.latest_revision
            or checkpoint.record_digest != anchor.latest_digest
        ):
            raise cls._error_type("coding_worker_retirement_checkpoint_unanchored")
        manifest = history.manifest
        if (
            manifest is None
            or manifest.stream_id != stem
            or not 0 <= first_retained_generation <= manifest.active_generation
            or (
                first_retained_generation == 0
                and (stem != "worker-supervisor" or manifest.active_generation != 0)
            )
            or len(history.segments) != manifest.active_generation + 1
        ):
            raise cls._error_type("coding_worker_retirement_cutoff_unavailable")
        matching = tuple(
            snapshot
            for snapshot in checkpoint.stream_snapshots
            if snapshot.stem == stem
        )
        if len(matching) != 1:
            raise cls._error_type("coding_worker_retirement_source_unproven")
        snapshot = cls._snapshot_type.capture(
            stem=stem,
            active_generation=history.active_generation,
            last_sealed_revision=history.last_sealed_revision,
            segments=history.segments,
        )
        if snapshot != matching[0] or any(
            len(raw) != seal.byte_count or sha256(raw).hexdigest() != seal.digest
            for raw, seal in zip(history.segments[:-1], manifest.sealed, strict=True)
        ):
            raise cls._error_type("coding_worker_retirement_source_unproven")
        retired = manifest.sealed[:first_retained_generation]
        return cast(Callable[..., Self], cls)(
            stem=stem,
            checkpoint_revision=checkpoint.journal_revision,
            checkpoint_digest=checkpoint.record_digest,
            source_fingerprint=snapshot.fingerprint,
            first_retained_generation=first_retained_generation,
            first_retained_revision=(
                1 if not retired else retired[-1].last_revision + 1
            ),
            retired_sealed_digest=sha256(
                canonical_json_bytes([item.to_dict() for item in retired])
            ).hexdigest(),
            retired_generations=tuple(item.generation for item in retired),
            retained_generations=tuple(
                range(first_retained_generation, history.active_generation + 1)
            ),
        )
