"""Exact Linux Product Worker stream bytes for a later retention checkpoint."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.journal._rooted_io import RootedFileIO
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_product_worker_history_segments import (
    read_coding_worker_segmented_history,
)

CODING_WORKER_HISTORY_STREAM_STEMS = (
    "worker-opt-in",
    "worker-activation-receipts",
    "worker-activation-state",
    "worker-start-gates",
    "worker-supervisor",
)
_MAX_SEGMENT_BYTES = 32 * 1024 * 1024


def _stream_fingerprint(
    *,
    stem: str,
    active_generation: int,
    last_sealed_revision: int,
    total_revision: int,
    counts: tuple[int, ...],
    digests: tuple[str, ...],
) -> str:
    return sha256(
        canonical_json_bytes(
            {
                "activeGeneration": active_generation,
                "lastSealedRevision": last_sealed_revision,
                "totalRevision": total_revision,
                "segmentByteCounts": list(counts),
                "segmentDigests": list(digests),
                "stem": stem,
                "version": 1,
            }
        )
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class CodingWorkerHistoryStreamSnapshotV1:
    stem: str
    active_generation: int
    last_sealed_revision: int
    total_revision: int
    segment_byte_counts: tuple[int, ...]
    segment_digests: tuple[str, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, object]:
        return {
            "activeGeneration": self.active_generation,
            "fingerprint": self.fingerprint,
            "lastSealedRevision": self.last_sealed_revision,
            "segmentByteCounts": list(self.segment_byte_counts),
            "segmentDigests": list(self.segment_digests),
            "stem": self.stem,
            "totalRevision": self.total_revision,
            "version": 1,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingWorkerHistoryStreamSnapshotV1:
        if type(value) is not dict or set(value) != {
            "activeGeneration",
            "fingerprint",
            "lastSealedRevision",
            "segmentByteCounts",
            "segmentDigests",
            "stem",
            "totalRevision",
            "version",
        }:
            raise ValueError("Coding Worker history stream snapshot shape is invalid")
        if (
            value["version"] != 1
            or type(value["segmentByteCounts"]) is not list
            or type(value["segmentDigests"]) is not list
        ):
            raise ValueError("Coding Worker history stream snapshot version is invalid")
        return cls(
            stem=value["stem"],
            active_generation=value["activeGeneration"],
            last_sealed_revision=value["lastSealedRevision"],
            total_revision=value["totalRevision"],
            segment_byte_counts=tuple(value["segmentByteCounts"]),
            segment_digests=tuple(value["segmentDigests"]),
            fingerprint=value["fingerprint"],
        )

    def __post_init__(self) -> None:
        if (
            type(self.stem) is not str
            or self.stem not in CODING_WORKER_HISTORY_STREAM_STEMS
            or type(self.active_generation) is not int
            or self.active_generation < 0
            or type(self.last_sealed_revision) is not int
            or self.last_sealed_revision < 0
            or type(self.total_revision) is not int
            or self.total_revision < self.last_sealed_revision
            or (self.active_generation == 0) != (self.last_sealed_revision == 0)
            or type(self.segment_byte_counts) is not tuple
            or type(self.segment_digests) is not tuple
            or len(self.segment_byte_counts) != self.active_generation + 1
            or len(self.segment_digests) != self.active_generation + 1
            or any(
                type(count) is not int or count < 0
                for count in self.segment_byte_counts
            )
            or any(count == 0 for count in self.segment_byte_counts[:-1])
            or any(
                type(digest) is not str
                or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
                for digest in self.segment_digests
            )
            or type(self.fingerprint) is not str
            or self.fingerprint
            != _stream_fingerprint(
                stem=self.stem,
                active_generation=self.active_generation,
                last_sealed_revision=self.last_sealed_revision,
                total_revision=self.total_revision,
                counts=self.segment_byte_counts,
                digests=self.segment_digests,
            )
        ):
            raise ValueError("Coding Worker history stream snapshot is invalid")

    @classmethod
    def capture(
        cls,
        *,
        stem: str,
        active_generation: int,
        last_sealed_revision: int,
        segments: tuple[bytes, ...],
    ) -> CodingWorkerHistoryStreamSnapshotV1:
        counts = tuple(len(segment) for segment in segments)
        digests = tuple(sha256(segment).hexdigest() for segment in segments)
        total_revision = sum(segment.count(b"\n") for segment in segments)
        return cls(
            stem=stem,
            active_generation=active_generation,
            last_sealed_revision=last_sealed_revision,
            total_revision=total_revision,
            segment_byte_counts=counts,
            segment_digests=digests,
            fingerprint=_stream_fingerprint(
                stem=stem,
                active_generation=active_generation,
                last_sealed_revision=last_sealed_revision,
                total_revision=total_revision,
                counts=counts,
                digests=digests,
            ),
        )


def capture_coding_worker_history_streams_under_gc_guard(
    product: PosixLocalWheelProductSessionOwner,
) -> tuple[CodingWorkerHistoryStreamSnapshotV1, ...]:
    """Capture all five strict streams while Product GC admission is held."""

    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding Worker history streams require their Product")
    product.assert_root_gc_authority_current()
    with product.pinned_state_root_gc_read() as root_fd:
        file_io = RootedFileIO(product.state_root, root_fd)
        try:
            snapshots: list[CodingWorkerHistoryStreamSnapshotV1] = []
            for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
                with file_io.bind(
                    product.state_root / f"{stem}.jsonl", durable=False
                ) as rooted:
                    history = read_coding_worker_segmented_history(
                        rooted,
                        stem=stem,
                        stream_id=stem,
                        max_segment_bytes=_MAX_SEGMENT_BYTES,
                    )
                snapshots.append(
                    CodingWorkerHistoryStreamSnapshotV1.capture(
                        stem=stem,
                        active_generation=history.active_generation,
                        last_sealed_revision=history.last_sealed_revision,
                        segments=history.segments,
                    )
                )
            return tuple(snapshots)
        finally:
            file_io.cleanup()


__all__ = [
    "CODING_WORKER_HISTORY_STREAM_STEMS",
    "CodingWorkerHistoryStreamSnapshotV1",
    "capture_coding_worker_history_streams_under_gc_guard",
]
