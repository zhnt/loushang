"""Strict physical V2 Worker history reader after a Product owner commit.

The V1 segment manifest remains the generation metadata. The Product owner
index selects V2; missing retired files require an exact deletion ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.worker.history._read_v2 import (
    RetainedHistoryReader,
    _RetainedHistoryFields,
)
from loushang.harness.worker.history._read_v2 import _seal_head as _seal_head

from .package_product_worker_activation_base_v2 import CodingWorkerActivationReplayV2
from .package_product_worker_history_checkpoint import (
    _CHECKPOINT_HISTORY,
)
from .package_product_worker_history_deletion_v2 import (
    CodingWorkerV2DeletionLedger,
)
from .package_product_worker_history_prepared_v2 import (
    CodingWorkerPreparedProductCutoverV2,
)
from .package_product_worker_history_stage_v2 import (
    _PREPARATION_HISTORY,
)
from .package_product_worker_opt_in_base_v2 import CodingWorkerOptInReplayV2
from .package_product_worker_receipt_base_v2 import CodingWorkerReceiptReplayV2
from .package_product_worker_start_gate_base_v2 import (
    CodingWorkerStartGateReplayV2,
)
from .package_product_worker_supervisor_base_v2 import (
    CodingWorkerSupervisorReplayV2,
)

CodingWorkerV2Replay: TypeAlias = (
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
class CodingWorkerV2RetainedHistory(_RetainedHistoryFields):
    stem: str
    first_retained_generation: int
    active_generation: int
    segments: tuple[bytes, ...]
    last_revision: int
    replay: CodingWorkerV2Replay


_HISTORY_READER = RetainedHistoryReader(
    preparation=_PREPARATION_HISTORY,
    checkpoints=_CHECKPOINT_HISTORY,
    ledger_type=CodingWorkerV2DeletionLedger,
    history_type=CodingWorkerV2RetainedHistory,
    error_type=CodingWorkerV2ReadError,
)


def read_coding_worker_v2_retained_history(
    rooted: RootedFile, *, stem: str
) -> CodingWorkerV2RetainedHistory:
    "Verify owner, checkpoint, ledger, manifest, heads, and typed replay."
    return _HISTORY_READER.read(rooted, stem=stem)


def verify_coding_worker_v2_precommit_history(
    rooted: RootedFile,
    *,
    stem: str,
    prepared: CodingWorkerPreparedProductCutoverV2,
) -> CodingWorkerV2RetainedHistory:
    "Run the Product reader before publication; caller owns cutover locks."
    return _HISTORY_READER.verify_precommit(rooted, stem=stem, prepared=prepared)


__all__ = [
    "CodingWorkerV2ReadError",
    "CodingWorkerV2Replay",
    "CodingWorkerV2RetainedHistory",
    "read_coding_worker_v2_retained_history",
    "verify_coding_worker_v2_precommit_history",
]
