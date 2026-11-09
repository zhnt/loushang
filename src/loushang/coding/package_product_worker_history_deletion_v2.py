"""Exact V2 source-deletion debt bound to one committed Product owner index.

The ledger allows a V2 reader to tolerate only named retired segments being
absent. Its presence does not by itself delete a file or authorize Package GC.
"""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.worker.history._deletion import _DeletionLedgerMethods

from .package_product_worker_history_prepared_v2 import (
    CodingWorkerPreparedProductCutoverV2,
)


@dataclass(frozen=True, slots=True)
class CodingWorkerV2DeletionLedger(_DeletionLedgerMethods):
    scope_id: str
    store_id: str
    owner_index_digest: str
    retired_seals: tuple[tuple[str, int, int, int, int, str], ...]
    record_digest: str
    version: int = 2
    _prepared_type = CodingWorkerPreparedProductCutoverV2


CodingWorkerV2DeletionLedger._wire_schema = (
    CodingWorkerV2DeletionLedger._make_wire_schema()
)


__all__ = ["CodingWorkerV2DeletionLedger"]
