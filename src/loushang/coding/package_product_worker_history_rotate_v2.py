"""Seal low-volume V1 Worker streams under Product custody for V2 cutover.

This only creates durable empty successor generations. A later Product
checkpoint and cutover preflight still decide whether any source may retire.
"""

from __future__ import annotations

import sys
from hashlib import sha256

from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)

from .package_product_worker_history_checkpoint import (
    read_coding_product_worker_history_checkpoints_under_gc_guard,
)
from .package_product_worker_history_segments import (
    CodingWorkerSegmentedHistoryV1,
    CodingWorkerSegmentManifestV1,
    initialize_coding_worker_active_head,
    read_coding_worker_segmented_history,
    rollback_coding_worker_unpublished_successor,
    seal_coding_worker_active_segment,
)
from .package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
)
from .package_product_worker_history_v2_names import (
    NO_EFFECT_ARCHIVE_NAME,
    PREPARATION_ARTIFACT_NAMES,
    PREPARATION_INTENT_NAME,
    PRODUCT_OWNER_INDEX_NAME,
)

_MAX_SEGMENT_BYTES = 32 * 1024 * 1024


class CodingWorkerV2SealError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _present(rooted: RootedFile, name: str) -> bool:
    try:
        rooted.sibling(name).stat()
    except FileNotFoundError:
        return False
    return True


def _seal_under_guard(
    rooted: RootedFile, *, empty_supervisor_checkpointed: bool
) -> tuple[int, ...]:
    for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
        lock = rooted.sibling(stem + ".jsonl.lock")
        try:
            lock.acquire_lock(exclusive=True, suffix="", create=False)
        except FileNotFoundError as exc:
            if stem == "worker-supervisor" and empty_supervisor_checkpointed:
                names, complete = rooted.scan_sibling_names(limit=131072)
                if not complete or any(
                    name.casefold().startswith((stem + ".", "." + stem + "."))
                    for name in names
                ):
                    raise CodingWorkerV2SealError(
                        "coding_worker_v2_empty_supervisor_changed"
                    ) from exc
                active = rooted.sibling(stem + ".jsonl")
                if not active.acquire_lock(
                    exclusive=True,
                    suffix=".lock",
                    initialize_empty_target_if_new=True,
                ):
                    raise CodingWorkerV2SealError(
                        "coding_worker_v2_empty_supervisor_changed"
                    ) from exc
                initialize_coding_worker_active_head(rooted, stem=stem, stream_id=stem)
                continue
            raise CodingWorkerV2SealError(
                "coding_worker_v2_stream_lock_missing"
            ) from exc
    if _present(rooted, PRODUCT_OWNER_INDEX_NAME):
        raise CodingWorkerV2SealError("coding_worker_v2_owner_present")
    if _present(rooted, PREPARATION_INTENT_NAME):
        raise CodingWorkerV2SealError("coding_worker_v2_preparation_present")
    if any(
        _present(rooted, name)
        for name in (*PREPARATION_ARTIFACT_NAMES, NO_EFFECT_ARCHIVE_NAME)
    ):
        raise CodingWorkerV2SealError("coding_worker_v2_preparation_artifact_present")

    histories: list[CodingWorkerSegmentedHistoryV1] = []
    for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
        rollback_coding_worker_unpublished_successor(
            rooted,
            stem=stem,
            stream_id=stem,
            max_segment_bytes=_MAX_SEGMENT_BYTES,
        )
        history = read_coding_worker_segmented_history(
            rooted,
            stem=stem,
            stream_id=stem,
            max_segment_bytes=_MAX_SEGMENT_BYTES,
        )
        if history.active_generation == 0:
            if not history.active_raw:
                if stem != "worker-supervisor" or not empty_supervisor_checkpointed:
                    raise CodingWorkerV2SealError("coding_worker_v2_stream_empty")
                if history.manifest is None:
                    rooted.sibling(stem + ".segments.json").create_new(
                        CodingWorkerSegmentManifestV1(
                            stream_id=stem, active_generation=0, sealed=()
                        ).to_bytes()
                    )
                    history = read_coding_worker_segmented_history(
                        rooted,
                        stem=stem,
                        stream_id=stem,
                        max_segment_bytes=_MAX_SEGMENT_BYTES,
                    )
            if history.active_raw and not history.active_raw.endswith(b"\n"):
                raise CodingWorkerV2SealError("coding_worker_v2_stream_incomplete")
        histories.append(history)

    for stem, history in zip(
        CODING_WORKER_HISTORY_STREAM_STEMS, histories, strict=True
    ):
        if history.active_generation == 0 and history.active_raw:
            seal_coding_worker_active_segment(
                rooted,
                stem=stem,
                stream_id=stem,
                history=history,
                last_revision=history.active_raw.count(b"\n"),
            )
    generations = tuple(
        read_coding_worker_segmented_history(
            rooted,
            stem=stem,
            stream_id=stem,
            max_segment_bytes=_MAX_SEGMENT_BYTES,
        ).active_generation
        for stem in CODING_WORKER_HISTORY_STREAM_STEMS
    )
    if any(
        generation < (0 if stem == "worker-supervisor" else 1)
        for stem, generation in zip(
            CODING_WORKER_HISTORY_STREAM_STEMS, generations, strict=True
        )
    ):
        raise CodingWorkerV2SealError("coding_worker_v2_stream_unsealed")
    return tuple(
        0 if stem == "worker-supervisor" and generation == 0 else 1
        for stem, generation in zip(
            CODING_WORKER_HISTORY_STREAM_STEMS, generations, strict=True
        )
    )


def seal_coding_product_worker_v1_history_for_v2(
    product: PosixLocalWheelProductSessionOwner,
) -> tuple[int, ...]:
    """Seal five V1 streams and return their minimal first-retained cutoffs."""

    if (
        not sys.platform.startswith("linux")
        or type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding Worker V2 sealing requires its Linux Product")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise CodingWorkerV2SealError("coding_worker_v2_runtime_active")
        with product.gc_gate.guard(require_write=True):
            product.assert_root_gc_authority_current()
            checkpoints = read_coding_product_worker_history_checkpoints_under_gc_guard(
                product
            )
            supervisor_snapshot = (
                None if not checkpoints else checkpoints[-1].stream_snapshots[4]
            )
            empty_supervisor_checkpointed = bool(
                supervisor_snapshot is not None
                and supervisor_snapshot.stem == "worker-supervisor"
                and supervisor_snapshot.total_revision == 0
                and supervisor_snapshot.active_generation == 0
                and supervisor_snapshot.segment_byte_counts == (0,)
                and supervisor_snapshot.segment_digests == (sha256(b"").hexdigest(),)
            )
            with product.pinned_state_root_gc_read() as root_fd:
                file_io = RootedFileIO(product.state_root, root_fd)
                try:
                    with file_io.bind(
                        product.state_root / PRODUCT_OWNER_INDEX_NAME, durable=True
                    ) as rooted:
                        result = _seal_under_guard(
                            rooted,
                            empty_supervisor_checkpointed=empty_supervisor_checkpointed,
                        )
                finally:
                    file_io.cleanup()
            product.assert_root_gc_authority_current()
            return result


__all__ = [
    "CodingWorkerV2SealError",
    "seal_coding_product_worker_v1_history_for_v2",
]
