"""Exact Worker stream snapshots and authenticated byte-prefix comparisons."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from typing import ClassVar, Self, cast

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

CODING_WORKER_HISTORY_STREAM_STEMS = (
    "worker-opt-in",
    "worker-activation-receipts",
    "worker-activation-state",
    "worker-start-gates",
    "worker-supervisor",
)


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


class _SnapshotMethods:
    __slots__ = ()

    stem: str
    active_generation: int
    last_sealed_revision: int
    total_revision: int
    segment_byte_counts: tuple[int, ...]
    segment_digests: tuple[str, ...]
    fingerprint: str

    _snapshot_type: ClassVar[type[_SnapshotMethods]]

    def is_exact_prefix_of(
        self,
        current: _SnapshotMethods,
        *,
        current_segments: tuple[bytes, ...],
    ) -> bool:
        """Prove every byte previously captured still precedes new records."""

        if (
            type(current) is not self._snapshot_type
            or self.stem != current.stem
            or self.active_generation > current.active_generation
            or self.total_revision > current.total_revision
            or self.last_sealed_revision > current.last_sealed_revision
            or len(current_segments) != current.active_generation + 1
            or self._snapshot_type.capture(
                stem=current.stem,
                active_generation=current.active_generation,
                last_sealed_revision=current.last_sealed_revision,
                segments=current_segments,
            )
            != current
        ):
            return False
        for generation in range(self.active_generation + 1):
            count = self.segment_byte_counts[generation]
            if (
                count > len(current_segments[generation])
                or sha256(current_segments[generation][:count]).hexdigest()
                != self.segment_digests[generation]
                or (
                    generation < self.active_generation
                    and count != len(current_segments[generation])
                )
            ):
                return False
        return True

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
    def from_dict(cls, value: object) -> Self:
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
        return cast(Callable[..., Self], cls)(
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
    ) -> Self:
        counts = tuple(len(segment) for segment in segments)
        digests = tuple(sha256(segment).hexdigest() for segment in segments)
        total_revision = sum(segment.count(b"\n") for segment in segments)
        return cast(Callable[..., Self], cls)(
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


def _is_v2_authenticated_prefix(
    old: _SnapshotMethods,
    now: _SnapshotMethods,
    *,
    active: bytes,
) -> bool:
    if (
        old.stem != now.stem
        or old.active_generation > now.active_generation
        or old.total_revision > now.total_revision
        or old.last_sealed_revision > now.last_sealed_revision
    ):
        return False
    for generation in range(old.active_generation):
        if (
            old.segment_byte_counts[generation] != now.segment_byte_counts[generation]
            or old.segment_digests[generation] != now.segment_digests[generation]
        ):
            return False
    generation = old.active_generation
    count = old.segment_byte_counts[generation]
    if generation < now.active_generation:
        return (
            count == now.segment_byte_counts[generation]
            and old.segment_digests[generation] == now.segment_digests[generation]
        )
    return (
        count <= len(active)
        and sha256(active[:count]).hexdigest() == (old.segment_digests[generation])
    )
