"""Source-bound Windows Worker native provisioning cutover projection.

This typed base preserves old attempt identities and terminal observations.
It cannot commit a Product cutover, authorize cleanup, or delete old files.
"""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.worker.history._windows_provisioning_base import (
    _WindowsProvisioningBaseMethods,
    _WindowsProvisioningRetainedMethods,
)

from .product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1 as CodingWindowsWorkerHistorySemanticReadV1,
)
from .product_worker_windows_provisioning_journal import _Record as _Record


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


__all__ = [
    "CodingWindowsWorkerNativeProvisioningRetainedAttemptV1",
    "CodingWindowsWorkerNativeProvisioningSemanticBaseV1",
]


CodingWindowsWorkerNativeProvisioningSemanticBaseV1._bind_record_schema(
    lambda value: CodingWindowsWorkerNativeProvisioningRetainedAttemptV1.from_dict(
        value
    )
)
