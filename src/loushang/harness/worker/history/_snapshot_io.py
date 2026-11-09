"""Five-stream snapshot IO over original caller root custody and retained reader."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol, cast

from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO

from .._segmented_history import (
    CodingWorkerSegmentedHistoryV1,
    CodingWorkerSegmentManifestV1,
    _segment_name,
    read_coding_worker_segmented_history,
)
from ._read_v2 import RetainedHistoryReader, _RetainedHistoryFields
from ._snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
    _is_v2_authenticated_prefix,
    _SnapshotMethods,
    _stream_fingerprint,
)
from ._v2_names import PRODUCT_OWNER_INDEX_NAME


class HistorySnapshotAccess(Protocol):
    @property
    def state_root(self) -> Path: ...
    def assert_current(self) -> None: ...
    def pin_state_read(self) -> AbstractContextManager[int]: ...


class RetainedSnapshotReader(Protocol):
    def read(self, rooted: RootedFile, *, stem: str) -> _RetainedHistoryFields: ...


@dataclass(frozen=True, slots=True)
class SnapshotHistory:
    snapshot_type: type[_SnapshotMethods]
    reader: Callable[[], RetainedSnapshotReader]
    max_segment_bytes: int
    max_manifest_bytes: int

    def read_histories(
        self, access: HistorySnapshotAccess
    ) -> tuple[CodingWorkerSegmentedHistoryV1, ...]:
        """Read all five strict V1 streams under Product GC admission."""
        access.assert_current()
        with access.pin_state_read() as root_fd:
            with RootedFileIO(access.state_root, root_fd) as file_io:
                histories: list[CodingWorkerSegmentedHistoryV1] = []
                for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
                    with file_io.bind(
                        access.state_root / f"{stem}.jsonl", durable=False
                    ) as rooted:
                        history = read_coding_worker_segmented_history(
                            rooted,
                            stem=stem,
                            stream_id=stem,
                            max_segment_bytes=self.max_segment_bytes,
                        )
                    histories.append(history)
                return tuple(histories)

    def read_v2_snapshot(
        self, rooted: RootedFile, *, stem: str
    ) -> tuple[_SnapshotMethods, bytes]:
        """Reconstruct a full snapshot only after V2 proves deleted generations."""
        reader = self.reader()
        rooted.sibling(stem + ".jsonl.lock").acquire_lock(
            exclusive=False, suffix="", create=False
        )
        retained = reader.read(rooted, stem=stem)
        manifest = CodingWorkerSegmentManifestV1.from_bytes(
            rooted.sibling(stem + ".segments.json").read_bytes(
                max_bytes=self.max_manifest_bytes
            ),
            stream_id=stem,
        )
        active = rooted.sibling(
            _segment_name(stem, manifest.active_generation)
        ).read_bytes(max_bytes=self.max_segment_bytes)
        if manifest.active_generation != retained.active_generation:
            raise ValueError("Coding Worker V2 snapshot generation changed")
        counts = (*(seal.byte_count for seal in manifest.sealed), len(active))
        digests = (
            *(seal.digest for seal in manifest.sealed),
            sha256(active).hexdigest(),
        )
        snapshot = cast(Callable[..., _SnapshotMethods], self.snapshot_type)(
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
        return (snapshot, active)

    def read_v2_snapshots(
        self, access: HistorySnapshotAccess
    ) -> tuple[tuple[_SnapshotMethods, bytes], ...] | None:
        access.assert_current()
        with access.pin_state_read() as root_fd:
            with RootedFileIO(access.state_root, root_fd) as file_io:
                with file_io.bind(
                    access.state_root / PRODUCT_OWNER_INDEX_NAME, durable=False
                ) as rooted:
                    if not RetainedHistoryReader.owner_exists(rooted):
                        return None
                snapshots: list[tuple[_SnapshotMethods, bytes]] = []
                for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
                    with file_io.bind(
                        access.state_root / f"{stem}.jsonl", durable=False
                    ) as rooted:
                        snapshots.append(self.read_v2_snapshot(rooted, stem=stem))
                return tuple(snapshots)

    def capture(self, access: HistorySnapshotAccess) -> tuple[_SnapshotMethods, ...]:
        """Capture all five strict streams while Product GC admission is held."""
        v2_snapshots = self.read_v2_snapshots(access)
        if v2_snapshots is not None:
            return tuple((snapshot for snapshot, _active in v2_snapshots))
        histories = self.read_histories(access)
        return tuple(
            (
                self.snapshot_type.capture(
                    stem=stem,
                    active_generation=history.active_generation,
                    last_sealed_revision=history.last_sealed_revision,
                    segments=history.segments,
                )
                for stem, history in zip(
                    CODING_WORKER_HISTORY_STREAM_STEMS, histories, strict=True
                )
            )
        )

    def verify_extensions(
        self,
        access: HistorySnapshotAccess,
        *,
        previous: tuple[_SnapshotMethods, ...],
        current: tuple[_SnapshotMethods, ...],
    ) -> bool:
        """Reopen all five exact streams and prove their checkpointed byte prefixes."""
        v2_snapshots = self.read_v2_snapshots(access)
        if v2_snapshots is not None:
            return all(
                (
                    snapshot == now
                    and _is_v2_authenticated_prefix(old, now, active=active)
                    for old, now, (snapshot, active) in zip(
                        previous, current, v2_snapshots, strict=True
                    )
                )
            )
        access.assert_current()
        with access.pin_state_read() as root_fd:
            with RootedFileIO(access.state_root, root_fd) as file_io:
                for old, now in zip(previous, current, strict=True):
                    with file_io.bind(
                        access.state_root / f"{now.stem}.jsonl", durable=False
                    ) as rooted:
                        history = read_coding_worker_segmented_history(
                            rooted,
                            stem=now.stem,
                            stream_id=now.stem,
                            max_segment_bytes=self.max_segment_bytes,
                        )
                    if not old.is_exact_prefix_of(
                        now, current_segments=history.segments
                    ):
                        return False
                return True
