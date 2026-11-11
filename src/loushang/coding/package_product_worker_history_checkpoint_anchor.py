"""Durable Product anchor for the Worker checkpoint journal's committed tip."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.worker.history._anchor import (
    ANCHOR_NAME,
    _AnchorMethods,
    read_checkpoint_anchor,
    write_checkpoint_anchor,
)


class CodingWorkerCheckpointAnchorError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerCheckpointAnchorV1(_AnchorMethods):
    scope_id: str
    store_id: str
    latest_revision: int
    latest_digest: str
    record_digest: str
    record_version: int = 1

    _error_type = CodingWorkerCheckpointAnchorError


def read_coding_worker_checkpoint_anchor(
    rooted: RootedFile, *, scope_id: str, store_id: str
) -> CodingWorkerCheckpointAnchorV1 | None:
    return read_checkpoint_anchor(
        rooted=rooted,
        scope_id=scope_id,
        store_id=store_id,
        anchor_type=CodingWorkerCheckpointAnchorV1,
        error_type=CodingWorkerCheckpointAnchorError,
    )


def write_coding_worker_checkpoint_anchor(
    rooted: RootedFile,
    *,
    expected: CodingWorkerCheckpointAnchorV1 | None,
    current: CodingWorkerCheckpointAnchorV1,
) -> None:
    return write_checkpoint_anchor(
        rooted=rooted,
        expected=expected,
        current=current,
        error_type=CodingWorkerCheckpointAnchorError,
    )


__all__ = [
    "ANCHOR_NAME",
    "CodingWorkerCheckpointAnchorError",
    "CodingWorkerCheckpointAnchorV1",
    "read_coding_worker_checkpoint_anchor",
    "write_coding_worker_checkpoint_anchor",
]
