"""Commit the single Product Worker V2 owner after physical cutover proof.

The caller must hold Product runtime quiescence, the GC write gate, and a
pinned state root. This primitive additionally locks the five existing stream
locks in fixed order. The owner file is the only authority transition.
"""

from __future__ import annotations

from loushang.harness.journal._rooted_io import RootedFile

from .package_product_worker_history_cutover_v2 import (
    CodingWorkerProductCutoverIndexV2,
)
from .package_product_worker_history_prepared_v2 import (
    CodingWorkerPreparedProductCutoverV2,
)
from .package_product_worker_history_read_v2 import (
    read_coding_worker_v2_retained_history,
    verify_coding_worker_v2_precommit_history,
)
from .package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
)
from .package_product_worker_history_v2_names import PRODUCT_OWNER_INDEX_NAME

_MAX_INDEX_BYTES = 4096


class CodingWorkerV2OwnerCommitError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _owner_bytes(rooted: RootedFile) -> bytes | None:
    try:
        return rooted.sibling(PRODUCT_OWNER_INDEX_NAME).read_bytes(
            max_bytes=_MAX_INDEX_BYTES
        )
    except FileNotFoundError:
        return None


def commit_coding_worker_v2_owner_under_guard(
    rooted: RootedFile, *, prepared: CodingWorkerPreparedProductCutoverV2
) -> CodingWorkerProductCutoverIndexV2:
    """Publish one durable owner; a retry may only accept that exact owner."""

    if type(prepared) is not CodingWorkerPreparedProductCutoverV2:
        raise ValueError("Coding Worker V2 prepared history is invalid")
    for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
        try:
            rooted.sibling(stem + ".jsonl.lock").acquire_lock(
                exclusive=True, suffix="", create=False
            )
        except FileNotFoundError as exc:
            raise CodingWorkerV2OwnerCommitError(
                "coding_worker_v2_stream_lock_missing"
            ) from exc

    expected = prepared.index.to_bytes()
    existing = _owner_bytes(rooted)
    if existing is not None:
        if existing != expected:
            raise CodingWorkerV2OwnerCommitError("coding_worker_v2_owner_changed")
    else:
        for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
            verify_coding_worker_v2_precommit_history(
                rooted, stem=stem, prepared=prepared
            )
        rooted.sibling(PRODUCT_OWNER_INDEX_NAME).create_new(expected)

    for stem in CODING_WORKER_HISTORY_STREAM_STEMS:
        read_coding_worker_v2_retained_history(rooted, stem=stem)
    return prepared.index


__all__ = [
    "CodingWorkerV2OwnerCommitError",
    "commit_coding_worker_v2_owner_under_guard",
]
