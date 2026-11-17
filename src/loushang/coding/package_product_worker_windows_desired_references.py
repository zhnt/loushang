"""Read-only Desired State reference join for Windows Worker history cutover.

The Product must supply the Desired capture behind its GC guard. This review
binds historical receipts to selected Package revisions but cannot commit a
checkpoint, switch readers, or retire source bytes.
"""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.package_product._windows_worker_references import (
    _WindowsDesiredReferenceMethods,
)

from .package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
)
from .package_product_worker_windows_receipt_base import (
    CodingWindowsWorkerReceiptSemanticBaseV1,
)


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerDesiredReferenceReviewV1(_WindowsDesiredReferenceMethods):
    """Exact selected-revision references from one retained Desired history."""

    _product_id = "coding"
    _installation_scope = "workspace"

    scope_id: str
    store_id: str
    source_snapshot_digest: str
    desired_history_digest: str
    desired_inventory_revision: int
    receipt_base_digest: str
    historical_package_revisions: tuple[tuple[str, str], ...]
    current_package_revisions: tuple[tuple[str, str], ...]
    retained_receipt_revisions: tuple[tuple[str, str, str], ...]
    review_digest: str

    @classmethod
    def from_semantic_read(
        cls,
        prepared: CodingWindowsWorkerHistoryPreparationV1,
        semantic: CodingWindowsWorkerHistorySemanticReadV1,
    ) -> CodingWindowsWorkerDesiredReferenceReviewV1:
        if type(prepared) is not CodingWindowsWorkerHistoryPreparationV1:
            raise ValueError("Windows Worker Desired preparation is invalid")
        prepared.require_semantic_read(semantic)
        receipt_base = CodingWindowsWorkerReceiptSemanticBaseV1.from_semantic_read(
            prepared, semantic
        )
        return cls._from_captured_desired(semantic, receipt_base)


__all__ = ["CodingWindowsWorkerDesiredReferenceReviewV1"]
