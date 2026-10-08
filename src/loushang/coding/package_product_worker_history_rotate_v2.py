"""Seal low-volume V1 Worker streams under Product custody for V2 cutover.

This only creates durable empty successor generations. A later Product
checkpoint and cutover preflight still decide whether any source may retire.
"""

from __future__ import annotations

import sys

from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)

from .package_product_worker_history_segments import (
    CodingWorkerSegmentedHistoryV1,
    read_coding_worker_segmented_history,
    rollback_coding_worker_unpublished_successor,
    seal_coding_worker_active_segment,
)
from .package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
)
from .package_product_worker_history_v2_names import (
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


def _seal_under_guard(rooted: RootedFile) -> tuple[int, ...]:
    for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
        try:
            rooted.sibling(stem + ".jsonl.lock").acquire_lock(
                exclusive=True, suffix="", create=False
            )
        except FileNotFoundError as exc:
            raise CodingWorkerV2SealError(
                "coding_worker_v2_stream_lock_missing"
            ) from exc
    if _present(rooted, PRODUCT_OWNER_INDEX_NAME):
        raise CodingWorkerV2SealError("coding_worker_v2_owner_present")
    if _present(rooted, PREPARATION_INTENT_NAME):
        raise CodingWorkerV2SealError("coding_worker_v2_preparation_present")
    if any(_present(rooted, name) for name in PREPARATION_ARTIFACT_NAMES):
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
                raise CodingWorkerV2SealError("coding_worker_v2_stream_empty")
            if not history.active_raw.endswith(b"\n"):
                raise CodingWorkerV2SealError("coding_worker_v2_stream_incomplete")
        histories.append(history)

    for stem, history in zip(
        CODING_WORKER_HISTORY_STREAM_STEMS, histories, strict=True
    ):
        if history.active_generation == 0:
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
    if any(generation < 1 for generation in generations):
        raise CodingWorkerV2SealError("coding_worker_v2_stream_unsealed")
    return (1,) * len(CODING_WORKER_HISTORY_STREAM_STEMS)


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
            with product.pinned_state_root_gc_read() as root_fd:
                file_io = RootedFileIO(product.state_root, root_fd)
                try:
                    with file_io.bind(
                        product.state_root / PRODUCT_OWNER_INDEX_NAME, durable=True
                    ) as rooted:
                        result = _seal_under_guard(rooted)
                finally:
                    file_io.cleanup()
            product.assert_root_gc_authority_current()
            return result


__all__ = [
    "CodingWorkerV2SealError",
    "seal_coding_product_worker_v1_history_for_v2",
]
