"""Prepare all five typed Worker history cutovers from one anchored V1 view.

Preparation is read-only. Product publication must reopen the sources under
its runtime and GC gates before making the cutover index authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.worker.history._prepared import (
    _PreparedMethods,
    require_retained_reference_closure,
)

from .package_product_worker_activation_base_v2 import (
    CodingWorkerActivationSemanticBaseV2,
)
from .package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from .package_product_worker_history_checkpoint import (
    CodingWorkerHistoryCheckpointV1,
)
from .package_product_worker_history_checkpoint_anchor import (
    CodingWorkerCheckpointAnchorV1,
)
from .package_product_worker_history_cutover_v2 import (
    CodingWorkerProductCutoverIndexV2,
    CodingWorkerStreamCutoverV2,
)
from .package_product_worker_history_retirement_preview import (
    CodingWorkerStreamRetirementPreviewV2,
)
from .package_product_worker_history_segments import (
    CodingWorkerSegmentedHistoryV1 as CodingWorkerSegmentedHistoryV1,
)
from .package_product_worker_no_effect_archive_v2 import (
    CodingWorkerNoEffectArchiveV2,
)
from .package_product_worker_opt_in_base_v2 import (
    CodingWorkerOptInSemanticBaseV2,
)
from .package_product_worker_receipt import (
    CodingWorkerReceiptRecordV1 as CodingWorkerReceiptRecordV1,
)
from .package_product_worker_receipt_base_v2 import (
    CodingWorkerReceiptSemanticBaseV2,
)
from .package_product_worker_start_gate_base_v2 import (
    CodingWorkerStartGateSemanticBaseV2,
)
from .package_product_worker_supervisor_base_v2 import (
    CodingWorkerSupervisorSemanticBaseV2,
)

CodingWorkerTypedBasesV2 = tuple[
    CodingWorkerOptInSemanticBaseV2,
    CodingWorkerReceiptSemanticBaseV2,
    CodingWorkerActivationSemanticBaseV2,
    CodingWorkerStartGateSemanticBaseV2,
    CodingWorkerSupervisorSemanticBaseV2,
]


require_coding_worker_v2_retained_reference_closure = require_retained_reference_closure


@dataclass(frozen=True, slots=True)
class CodingWorkerPreparedProductCutoverV2(_PreparedMethods):
    index: CodingWorkerProductCutoverIndexV2
    streams: tuple[CodingWorkerStreamCutoverV2, ...]
    semantic_bases: CodingWorkerTypedBasesV2
    no_effect_archive: CodingWorkerNoEffectArchiveV2 | None = None
    _retained_type = CodingProductWorkerRetainedAttemptV1
    _activation_type = CodingWorkerActivationSemanticBaseV2
    _anchor_type = CodingWorkerCheckpointAnchorV1
    _checkpoint_type = CodingWorkerHistoryCheckpointV1
    _archive_type = CodingWorkerNoEffectArchiveV2
    _opt_in_type = CodingWorkerOptInSemanticBaseV2
    _index_type = CodingWorkerProductCutoverIndexV2
    _receipt_type = CodingWorkerReceiptSemanticBaseV2
    _gate_type = CodingWorkerStartGateSemanticBaseV2
    _stream_type = CodingWorkerStreamCutoverV2
    _preview_type = CodingWorkerStreamRetirementPreviewV2
    _supervisor_type = CodingWorkerSupervisorSemanticBaseV2


require_coding_worker_no_effect_archive_sources = (
    CodingWorkerPreparedProductCutoverV2._require_archive_sources
)


__all__ = [
    "CodingWorkerPreparedProductCutoverV2",
    "CodingWorkerTypedBasesV2",
    "require_coding_worker_v2_retained_reference_closure",
]
