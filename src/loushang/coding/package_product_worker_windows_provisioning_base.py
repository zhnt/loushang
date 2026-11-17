"""Source-bound Windows Worker native provisioning cutover projection.

This typed base preserves old attempt identities and terminal observations.
It cannot commit a Product cutover, authorize cleanup, or delete old files.
"""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.worker.history._base_codec import (
    _unchanged,
)
from loushang.harness.worker.history._windows_provisioning_base import (
    _WindowsProvisioningBaseMethods,
    _WindowsProvisioningRetainedMethods,
)

from .package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
)
from .package_product_worker_windows_provisioning_journal import (
    _Record as _Record,
)

_MAX_BASE_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerNativeProvisioningRetainedAttemptV1(
    _WindowsProvisioningRetainedMethods
):
    @classmethod
    def from_dict(
        cls, value: object
    ) -> CodingWindowsWorkerNativeProvisioningRetainedAttemptV1:
        return cls._from_dict(value)


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerNativeProvisioningSemanticBaseV1(
    _WindowsProvisioningBaseMethods
):
    _preparation_type = CodingWindowsWorkerHistoryPreparationV1
    _preparation_label = "native provisioning"
    _retained_type = CodingWindowsWorkerNativeProvisioningRetainedAttemptV1

    retained_attempts: tuple[
        CodingWindowsWorkerNativeProvisioningRetainedAttemptV1, ...
    ]

    @classmethod
    def from_semantic_read(
        cls,
        prepared: CodingWindowsWorkerHistoryPreparationV1,
        semantic: CodingWindowsWorkerHistorySemanticReadV1,
    ) -> CodingWindowsWorkerNativeProvisioningSemanticBaseV1:
        return cls._from_prepared_history(prepared, semantic)

    _wire_label = "Windows Worker native provisioning semantic base"
    _wire_lists = ("attemptIds", "retainedAttempts")
    _wire_errors = (KeyError, RecursionError, TypeError, UnicodeError, ValueError)
    _wire_capacity_label = "Windows Worker native provisioning base"

    @classmethod
    def _wire_maximum(cls) -> int:
        return _MAX_BASE_BYTES


__all__ = [
    "CodingWindowsWorkerNativeProvisioningRetainedAttemptV1",
    "CodingWindowsWorkerNativeProvisioningSemanticBaseV1",
]


CodingWindowsWorkerNativeProvisioningSemanticBaseV1._bind_wire_schema(
    RecordSchema.for_dataclass(
        CodingWindowsWorkerNativeProvisioningSemanticBaseV1,
        _unchanged,
        RecordField(
            "retained_attempts",
            decoder=lambda xs: tuple(
                (
                    CodingWindowsWorkerNativeProvisioningRetainedAttemptV1.from_dict(
                        item
                    )
                    for item in xs
                )
            ),
            encoder=lambda values: [value.to_dict() for value in values],
        ),
        RecordField("attempt_ids", decoder=tuple, encoder=list),
    )
)
