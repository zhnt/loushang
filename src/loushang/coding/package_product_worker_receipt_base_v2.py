"""Coding public receipt bases; decoding remains a pure value-codec binding."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.worker.history._receipts import (
    _ReceiptBaseMethods,
    _ReceiptReplayFields,
)

from .package_product_worker_receipt import (
    CodingWorkerReceiptRecordV1,
)
from .package_product_worker_receipt import (
    _parse_receipt_segment as _parse_receipt_segment,
)


@dataclass(frozen=True, slots=True)
class CodingWorkerReceiptReplayV2(_ReceiptReplayFields):
    last_issue_sequence: int
    retained_records: tuple[CodingWorkerReceiptRecordV1, ...]
    receipt_fingerprints: frozenset[str]


@dataclass(frozen=True, slots=True)
class CodingWorkerReceiptSemanticBaseV2(_ReceiptBaseMethods):
    scope_id: str
    first_retained_generation: int
    last_issue_sequence: int
    retired_sealed_digest: str
    retired_receipt_fingerprints: tuple[str, ...]
    version: int = 2

    _replay_type = CodingWorkerReceiptReplayV2
    _decode_segment = staticmethod(_parse_receipt_segment)


CodingWorkerReceiptSemanticBaseV2._wire_schema = (
    CodingWorkerReceiptSemanticBaseV2._make_wire_schema()
)

__all__ = ["CodingWorkerReceiptReplayV2", "CodingWorkerReceiptSemanticBaseV2"]
