"""Strict physical V2 Worker history reader after a Product owner commit.

The V1 segment manifest remains the generation metadata. The Product owner
index selects V2; missing retired files require an exact deletion ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_product_worker_activation_base_v2 import CodingWorkerActivationReplayV2
from .package_product_worker_history_checkpoint import (
    read_coding_worker_checkpoint_writer_fence,
)
from .package_product_worker_history_cutover_v2 import (
    CodingWorkerProductCutoverIndexV2,
    CodingWorkerStreamCutoverV2,
)
from .package_product_worker_history_deletion_v2 import (
    CodingWorkerV2DeletionLedger,
)
from .package_product_worker_history_segments import (
    CodingWorkerSealedSegmentV1,
    CodingWorkerSegmentManifestV1,
    _head_bytes,
    _head_name,
    _segment_name,
)
from .package_product_worker_history_stage_v2 import (
    read_coding_worker_v2_preparation,
)
from .package_product_worker_history_v2_names import (
    DELETION_LEDGER_NAME,
    PRODUCT_OWNER_INDEX_NAME,
)
from .package_product_worker_opt_in_base_v2 import CodingWorkerOptInReplayV2
from .package_product_worker_receipt_base_v2 import CodingWorkerReceiptReplayV2
from .package_product_worker_start_gate_base_v2 import (
    CodingWorkerStartGateReplayV2,
)
from .package_product_worker_supervisor_base_v2 import (
    CodingWorkerSupervisorReplayV2,
)

_MAX_SEGMENT_BYTES = 32 * 1024 * 1024
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_INDEX_BYTES = 4096
_MAX_LEDGER_BYTES = 1024 * 1024
_MAX_HEAD_BYTES = 512
_MAX_DIRECTORY_ENTRIES = 131072

CodingWorkerV2Replay = (
    CodingWorkerOptInReplayV2
    | CodingWorkerReceiptReplayV2
    | CodingWorkerActivationReplayV2
    | CodingWorkerStartGateReplayV2
    | CodingWorkerSupervisorReplayV2
)


class CodingWorkerV2ReadError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerV2RetainedHistory:
    stem: str
    first_retained_generation: int
    active_generation: int
    segments: tuple[bytes, ...]
    last_revision: int
    replay: CodingWorkerV2Replay


def _optional(rooted: RootedFile, name: str, *, limit: int) -> bytes | None:
    try:
        return rooted.sibling(name).read_bytes(max_bytes=limit)
    except FileNotFoundError:
        return None


def _seal_head(stem: str, seal: CodingWorkerSealedSegmentV1) -> bytes:
    return canonical_json_bytes(
        {
            "byteCount": seal.byte_count,
            "digest": seal.digest,
            "generation": seal.generation,
            "streamId": stem,
            "version": 1,
        }
    )


def _read_sealed(
    rooted: RootedFile,
    *,
    stem: str,
    seal: CodingWorkerSealedSegmentV1,
    may_be_absent: bool,
) -> bytes | None:
    raw = _optional(
        rooted, _segment_name(stem, seal.generation), limit=_MAX_SEGMENT_BYTES
    )
    head = _optional(rooted, _head_name(stem, seal.generation), limit=_MAX_HEAD_BYTES)
    if raw is None and not may_be_absent:
        raise CodingWorkerV2ReadError("coding_worker_v2_retained_segment_missing")
    if head is None and not may_be_absent:
        raise CodingWorkerV2ReadError("coding_worker_v2_retained_head_missing")
    if raw is not None and (
        len(raw) != seal.byte_count or sha256(raw).hexdigest() != seal.digest
    ):
        raise CodingWorkerV2ReadError("coding_worker_v2_sealed_segment_changed")
    if head is not None and head != _seal_head(stem, seal):
        raise CodingWorkerV2ReadError("coding_worker_v2_sealed_head_changed")
    return raw


def read_coding_worker_v2_retained_history(
    rooted: RootedFile, *, stem: str
) -> CodingWorkerV2RetainedHistory:
    """Verify owner, checkpoint, ledger, manifest, heads, and typed replay."""

    owner_raw = _optional(rooted, PRODUCT_OWNER_INDEX_NAME, limit=_MAX_INDEX_BYTES)
    if owner_raw is None:
        raise CodingWorkerV2ReadError("coding_worker_v2_owner_absent")
    owner = CodingWorkerProductCutoverIndexV2.from_bytes(owner_raw)
    prepared = read_coding_worker_v2_preparation(rooted)
    if prepared is None or prepared.index != owner:
        raise CodingWorkerV2ReadError("coding_worker_v2_preparation_unbound")
    streams = {item.stem: item for item in prepared.streams}
    if stem not in streams:
        raise ValueError("Coding Worker V2 stream name is invalid")
    stream: CodingWorkerStreamCutoverV2 = streams[stem]
    index = tuple(streams).index(stem)
    base = prepared.semantic_bases[index]
    checkpoints = read_coding_worker_checkpoint_writer_fence(
        rooted, scope_id=owner.scope_id, store_id=owner.store_id
    )
    if (
        len(checkpoints) < stream.checkpoint_revision
        or checkpoints[stream.checkpoint_revision - 1].record_digest
        != stream.checkpoint_digest
    ):
        raise CodingWorkerV2ReadError("coding_worker_v2_checkpoint_unanchored")
    raw_ledger = _optional(rooted, DELETION_LEDGER_NAME, limit=_MAX_LEDGER_BYTES)
    if raw_ledger is None:
        allowed_missing: frozenset[int] = frozenset()
    else:
        ledger = CodingWorkerV2DeletionLedger.from_bytes(raw_ledger)
        if ledger != CodingWorkerV2DeletionLedger.from_prepared(prepared):
            raise CodingWorkerV2ReadError("coding_worker_v2_deletion_ledger_changed")
        allowed_missing = frozenset(
            generation
            for named_stem, generation, *_ in ledger.retired_seals
            if named_stem == stem
        )
    manifest_raw = _optional(rooted, stem + ".segments.json", limit=_MAX_MANIFEST_BYTES)
    if manifest_raw is None:
        raise CodingWorkerV2ReadError("coding_worker_v2_manifest_missing")
    manifest = CodingWorkerSegmentManifestV1.from_bytes(manifest_raw, stream_id=stem)
    old_sealed = (*stream.retired_sealed, *stream.retained_sealed)
    if (
        manifest.active_generation < stream.active_generation
        or manifest.sealed[: stream.active_generation] != old_sealed
    ):
        raise CodingWorkerV2ReadError("coding_worker_v2_manifest_changed")
    names, complete = rooted.scan_sibling_names(limit=_MAX_DIRECTORY_ENTRIES)
    if not complete:
        raise CodingWorkerV2ReadError("coding_worker_v2_inventory_capacity")
    expected = {stem + ".segments.json", stem + ".jsonl.lock"}
    expected.update(
        _segment_name(stem, n) for n in range(manifest.active_generation + 1)
    )
    expected.update(_head_name(stem, n) for n in range(manifest.active_generation + 1))
    actual = {
        name
        for name in names
        if name.casefold().startswith((stem + ".", "." + stem + "."))
    }
    if not actual <= expected:
        raise CodingWorkerV2ReadError("coding_worker_v2_segment_orphan")
    retained: list[bytes] = []
    cutover_active_raw: bytes | None = None
    for seal in manifest.sealed:
        raw = _read_sealed(
            rooted,
            stem=stem,
            seal=seal,
            may_be_absent=seal.generation in allowed_missing,
        )
        if seal.generation >= stream.first_retained_generation:
            if raw is None:
                raise CodingWorkerV2ReadError(
                    "coding_worker_v2_retained_segment_missing"
                )
            retained.append(raw)
        if seal.generation == stream.active_generation:
            cutover_active_raw = raw
    active = _optional(
        rooted,
        _segment_name(stem, manifest.active_generation),
        limit=_MAX_SEGMENT_BYTES,
    )
    if active is None:
        raise CodingWorkerV2ReadError("coding_worker_v2_active_missing")
    active_head = _optional(
        rooted,
        _head_name(stem, manifest.active_generation),
        limit=_MAX_HEAD_BYTES,
    )
    if active_head != _head_bytes(stem, manifest.active_generation, active):
        raise CodingWorkerV2ReadError("coding_worker_v2_active_head_changed")
    if manifest.active_generation == stream.active_generation:
        cutover_active_raw = active
    if (
        cutover_active_raw is None
        or len(cutover_active_raw) < stream.active_byte_count
        or sha256(cutover_active_raw[: stream.active_byte_count]).hexdigest()
        != stream.active_digest
    ):
        raise CodingWorkerV2ReadError("coding_worker_v2_cutover_prefix_changed")
    retained.append(active)
    total_revision = manifest.last_sealed_revision + active.count(b"\n")
    if total_revision < stream.total_revision:
        raise CodingWorkerV2ReadError("coding_worker_v2_revision_rolled_back")
    replay = base.replay_retained(tuple(retained))
    replay_revision = (
        replay.last_issue_sequence
        if isinstance(replay, CodingWorkerReceiptReplayV2)
        else (
            replay.last_record.journal_revision
            if isinstance(replay, CodingWorkerActivationReplayV2)
            else replay.last_revision
        )
    )
    if replay_revision != total_revision:
        raise CodingWorkerV2ReadError("coding_worker_v2_semantic_revision_changed")
    return CodingWorkerV2RetainedHistory(
        stem=stem,
        first_retained_generation=stream.first_retained_generation,
        active_generation=manifest.active_generation,
        segments=tuple(retained),
        last_revision=total_revision,
        replay=replay,
    )


__all__ = [
    "CodingWorkerV2ReadError",
    "CodingWorkerV2Replay",
    "CodingWorkerV2RetainedHistory",
    "read_coding_worker_v2_retained_history",
]
