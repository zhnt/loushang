"""Authenticated Linux Product Worker snapshots for retention checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_product_worker_history_segments import (
    CodingWorkerSegmentedHistoryV1,
    CodingWorkerSegmentManifestV1,
    _segment_name,
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
_MAX_MANIFEST_BYTES = 1024 * 1024


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

    def is_exact_prefix_of(
        self,
        current: CodingWorkerHistoryStreamSnapshotV1,
        *,
        current_segments: tuple[bytes, ...],
    ) -> bool:
        """Prove every byte previously captured still precedes new records."""

        if (
            type(current) is not CodingWorkerHistoryStreamSnapshotV1
            or self.stem != current.stem
            or self.active_generation > current.active_generation
            or self.total_revision > current.total_revision
            or self.last_sealed_revision > current.last_sealed_revision
            or len(current_segments) != current.active_generation + 1
            or CodingWorkerHistoryStreamSnapshotV1.capture(
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


def read_coding_worker_histories_under_gc_guard(
    product: PosixLocalWheelProductSessionOwner,
) -> tuple[CodingWorkerSegmentedHistoryV1, ...]:
    """Read all five strict V1 streams under Product GC admission."""

    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding Worker history streams require their Product")
    product.assert_root_gc_authority_current()
    with product.pinned_state_root_gc_read() as root_fd:
        file_io = RootedFileIO(product.state_root, root_fd)
        try:
            histories: list[CodingWorkerSegmentedHistoryV1] = []
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
                histories.append(history)
            return tuple(histories)
        finally:
            file_io.cleanup()


def _v2_owner_exists(rooted: RootedFile) -> bool:
    try:
        rooted.stat()
    except FileNotFoundError:
        return False
    return True


def _read_v2_snapshot(
    rooted: RootedFile, *, stem: str
) -> tuple[CodingWorkerHistoryStreamSnapshotV1, bytes]:
    """Reconstruct a full snapshot only after V2 proves deleted generations."""

    from .package_product_worker_history_read_v2 import (
        read_coding_worker_v2_retained_history,
    )

    rooted.sibling(stem + ".jsonl.lock").acquire_lock(
        exclusive=False, suffix="", create=False
    )
    retained = read_coding_worker_v2_retained_history(rooted, stem=stem)
    manifest = CodingWorkerSegmentManifestV1.from_bytes(
        rooted.sibling(stem + ".segments.json").read_bytes(
            max_bytes=_MAX_MANIFEST_BYTES
        ),
        stream_id=stem,
    )
    active = rooted.sibling(_segment_name(stem, manifest.active_generation)).read_bytes(
        max_bytes=_MAX_SEGMENT_BYTES
    )
    if manifest.active_generation != retained.active_generation:
        raise ValueError("Coding Worker V2 snapshot generation changed")
    counts = (*(seal.byte_count for seal in manifest.sealed), len(active))
    digests = (*(seal.digest for seal in manifest.sealed), sha256(active).hexdigest())
    snapshot = CodingWorkerHistoryStreamSnapshotV1(
        stem=stem,
        active_generation=manifest.active_generation,
        last_sealed_revision=manifest.last_sealed_revision,
        total_revision=retained.last_revision,
        segment_byte_counts=counts,
        segment_digests=digests,
        fingerprint=_stream_fingerprint(
            stem=stem,
            active_generation=manifest.active_generation,
            last_sealed_revision=manifest.last_sealed_revision,
            total_revision=retained.last_revision,
            counts=counts,
            digests=digests,
        ),
    )
    return snapshot, active


def _read_v2_product_snapshots(
    product: PosixLocalWheelProductSessionOwner,
) -> tuple[tuple[CodingWorkerHistoryStreamSnapshotV1, bytes], ...] | None:
    from .package_product_worker_history_v2_names import PRODUCT_OWNER_INDEX_NAME

    product.assert_root_gc_authority_current()
    with product.pinned_state_root_gc_read() as root_fd:
        file_io = RootedFileIO(product.state_root, root_fd)
        try:
            with file_io.bind(
                product.state_root / PRODUCT_OWNER_INDEX_NAME, durable=False
            ) as rooted:
                if not _v2_owner_exists(rooted):
                    return None
            snapshots: list[tuple[CodingWorkerHistoryStreamSnapshotV1, bytes]] = []
            for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
                with file_io.bind(
                    product.state_root / f"{stem}.jsonl", durable=False
                ) as rooted:
                    snapshots.append(_read_v2_snapshot(rooted, stem=stem))
            return tuple(snapshots)
        finally:
            file_io.cleanup()


def _is_v2_authenticated_prefix(
    old: CodingWorkerHistoryStreamSnapshotV1,
    now: CodingWorkerHistoryStreamSnapshotV1,
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


def capture_coding_worker_history_streams_under_gc_guard(
    product: PosixLocalWheelProductSessionOwner,
) -> tuple[CodingWorkerHistoryStreamSnapshotV1, ...]:
    """Capture all five strict streams while Product GC admission is held."""

    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding Worker history streams require their Product")
    v2_snapshots = _read_v2_product_snapshots(product)
    if v2_snapshots is not None:
        return tuple(snapshot for snapshot, _active in v2_snapshots)
    histories = read_coding_worker_histories_under_gc_guard(product)
    return tuple(
        CodingWorkerHistoryStreamSnapshotV1.capture(
            stem=stem,
            active_generation=history.active_generation,
            last_sealed_revision=history.last_sealed_revision,
            segments=history.segments,
        )
        for stem, history in zip(
            CODING_WORKER_HISTORY_STREAM_STEMS, histories, strict=True
        )
    )


def verify_coding_worker_history_stream_extensions_under_gc_guard(
    product: PosixLocalWheelProductSessionOwner,
    *,
    previous: tuple[CodingWorkerHistoryStreamSnapshotV1, ...],
    current: tuple[CodingWorkerHistoryStreamSnapshotV1, ...],
) -> bool:
    """Reopen all five exact streams and prove their checkpointed byte prefixes."""

    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or tuple(item.stem for item in previous) != CODING_WORKER_HISTORY_STREAM_STEMS
        or tuple(item.stem for item in current) != CODING_WORKER_HISTORY_STREAM_STEMS
    ):
        raise ValueError("Coding Worker stream extension requires its Product")
    v2_snapshots = _read_v2_product_snapshots(product)
    if v2_snapshots is not None:
        return all(
            snapshot == now and _is_v2_authenticated_prefix(old, now, active=active)
            for old, now, (snapshot, active) in zip(
                previous, current, v2_snapshots, strict=True
            )
        )
    product.assert_root_gc_authority_current()
    with product.pinned_state_root_gc_read() as root_fd:
        file_io = RootedFileIO(product.state_root, root_fd)
        try:
            for old, now in zip(previous, current, strict=True):
                with file_io.bind(
                    product.state_root / f"{now.stem}.jsonl", durable=False
                ) as rooted:
                    history = read_coding_worker_segmented_history(
                        rooted,
                        stem=now.stem,
                        stream_id=now.stem,
                        max_segment_bytes=_MAX_SEGMENT_BYTES,
                    )
                if not old.is_exact_prefix_of(now, current_segments=history.segments):
                    return False
            return True
        finally:
            file_io.cleanup()


__all__ = [
    "CODING_WORKER_HISTORY_STREAM_STEMS",
    "CodingWorkerHistoryStreamSnapshotV1",
    "capture_coding_worker_history_streams_under_gc_guard",
    "read_coding_worker_histories_under_gc_guard",
    "verify_coding_worker_history_stream_extensions_under_gc_guard",
]
