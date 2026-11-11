"""Typed Product proof for a Worker settled before native effect.

The Product cutover must bind this archive to its owner index before retiring
V1 segments. It carries the cross-stream records which the individual stream
bases otherwise discard. Construction alone never authorizes a cutover.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.worker.history._no_effect import (
    _NoEffectArchiveMethods,
    _NoEffectProofMethods,
)

from .package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from .package_product_worker_opt_in import CodingWorkerOptInDecisionV1
from .package_product_worker_receipt import CodingWorkerReceiptRecordV1
from .package_product_worker_start_gate_journal import (
    CodingWorkerStartGateRecordV1,
)


@dataclass(frozen=True, slots=True)
class CodingWorkerNoEffectProofV2(_NoEffectProofMethods):
    gate: CodingWorkerStartGateRecordV1
    receipt: CodingWorkerReceiptRecordV1
    activation: CodingProductWorkerRetainedAttemptV1
    historical_allow: CodingWorkerOptInDecisionV1
    repair_intent_digest: str
    _retained_type = CodingProductWorkerRetainedAttemptV1
    _decision_type = CodingWorkerOptInDecisionV1
    _receipt_record_type = CodingWorkerReceiptRecordV1
    _gate_record_type = CodingWorkerStartGateRecordV1
    _product_id = "coding"


@dataclass(frozen=True, slots=True)
class CodingWorkerNoEffectArchiveV2(_NoEffectArchiveMethods):
    scope_id: str
    store_id: str
    checkpoint_digest: str
    proofs: tuple[CodingWorkerNoEffectProofV2, ...]
    version: int = 2
    _proof_type = CodingWorkerNoEffectProofV2


def read_bound_coding_worker_no_effect_archive_v2(
    rooted: RootedFile,
) -> CodingWorkerNoEffectArchiveV2 | None:
    """Read only the archive selected by the committed Product owner index."""
    from .package_product_worker_history_stage_v2 import _PREPARATION_HISTORY

    return cast(
        CodingWorkerNoEffectArchiveV2 | None,
        _PREPARATION_HISTORY.read_bound_archive(rooted),
    )


CodingWorkerNoEffectArchiveV2._wire_schema = (
    CodingWorkerNoEffectArchiveV2._make_wire_schema()
)


__all__ = [
    "CodingWorkerNoEffectArchiveV2",
    "CodingWorkerNoEffectProofV2",
    "read_bound_coding_worker_no_effect_archive_v2",
]
