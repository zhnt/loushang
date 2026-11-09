"""Read-only cross-ledger review before a Windows Worker history checkpoint.

The Product source reader has already proved runtime quiescence, GC guard, and
settlement. This review binds each independently typed base to that same read.
It is not a cutover owner, a writer switch, or deletion authority.
"""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.worker.history._windows_history_join import (
    _WindowsHistoryJoinMethods,
)

from .package_product_worker_windows_c5_base import (
    CodingWindowsWorkerC5SemanticBaseV1,
)
from .package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
)
from .package_product_worker_windows_launch_intent_base import (
    CodingWindowsWorkerLaunchIntentSemanticBaseV1,
)
from .package_product_worker_windows_opt_in_base import (
    CodingWindowsWorkerOptInSemanticBaseV1,
)
from .package_product_worker_windows_provisioning_base import (
    CodingWindowsWorkerNativeProvisioningSemanticBaseV1,
)
from .package_product_worker_windows_receipt_base import (
    CodingWindowsWorkerReceiptSemanticBaseV1,
)
from .package_product_worker_windows_supervisor_base import (
    CodingWindowsWorkerSupervisorSemanticBaseV1,
)


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerHistorySemanticJoinV1(_WindowsHistoryJoinMethods):
    """One source-bound, no-effect agreement of the six retained ledgers."""

    _opt_in_type = CodingWindowsWorkerOptInSemanticBaseV1
    _receipt_type = CodingWindowsWorkerReceiptSemanticBaseV1
    _supervisor_type = CodingWindowsWorkerSupervisorSemanticBaseV1
    _c5_type = CodingWindowsWorkerC5SemanticBaseV1
    _launch_intent_type = CodingWindowsWorkerLaunchIntentSemanticBaseV1
    _provisioning_type = CodingWindowsWorkerNativeProvisioningSemanticBaseV1

    scope_id: str
    store_id: str
    source_snapshot_digest: str
    opt_in: CodingWindowsWorkerOptInSemanticBaseV1
    receipt: CodingWindowsWorkerReceiptSemanticBaseV1
    supervisor: CodingWindowsWorkerSupervisorSemanticBaseV1
    c5: CodingWindowsWorkerC5SemanticBaseV1
    launch_intent: CodingWindowsWorkerLaunchIntentSemanticBaseV1
    native_provisioning: CodingWindowsWorkerNativeProvisioningSemanticBaseV1
    observed_attempt_ids: tuple[str, ...]
    effect_attempt_ids: tuple[str, ...]
    launched_attempt_ids: tuple[str, ...]
    review_digest: str

    @classmethod
    def from_semantic_read(
        cls,
        prepared: CodingWindowsWorkerHistoryPreparationV1,
        semantic: CodingWindowsWorkerHistorySemanticReadV1,
    ) -> CodingWindowsWorkerHistorySemanticJoinV1:
        if type(prepared) is not CodingWindowsWorkerHistoryPreparationV1:
            raise ValueError("Windows Worker history join preparation is invalid")
        prepared.require_semantic_read(semantic)
        source = semantic.source_snapshot
        recovery = semantic.offline_recovery
        observed = cls._observed_attempt_ids(recovery)
        opt_in = CodingWindowsWorkerOptInSemanticBaseV1.from_semantic_read(
            prepared, semantic
        )
        receipt = CodingWindowsWorkerReceiptSemanticBaseV1.from_semantic_read(
            prepared, semantic
        )
        supervisor = CodingWindowsWorkerSupervisorSemanticBaseV1.from_semantic_read(
            prepared, semantic
        )
        c5 = CodingWindowsWorkerC5SemanticBaseV1.from_semantic_read(prepared, semantic)
        launch = CodingWindowsWorkerLaunchIntentSemanticBaseV1.from_semantic_read(
            prepared, semantic
        )
        native = CodingWindowsWorkerNativeProvisioningSemanticBaseV1.from_semantic_read(
            prepared, semantic
        )
        return cls._from_source_bases(
            source, recovery, observed, opt_in, receipt, supervisor, c5, launch, native
        )


__all__ = ["CodingWindowsWorkerHistorySemanticJoinV1"]
