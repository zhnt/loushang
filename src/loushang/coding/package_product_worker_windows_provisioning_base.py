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
    _Record,
)

_MAX_BASE_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerNativeProvisioningRetainedAttemptV1(
    _WindowsProvisioningRetainedMethods
):
    attempt_id: str
    identity: dict[str, object]
    cutoff_revision: int
    last_record: _Record
    phase_history: tuple[str, ...]
    witness_present_history: tuple[bool, ...]
    last_witness_state: str | None
    settlement_fingerprint: str | None

    @classmethod
    def from_dict(
        cls, value: object
    ) -> CodingWindowsWorkerNativeProvisioningRetainedAttemptV1:
        return cls._from_dict(value)


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerNativeProvisioningSemanticBaseV1(
    _WindowsProvisioningBaseMethods
):
    _retained_type = CodingWindowsWorkerNativeProvisioningRetainedAttemptV1

    scope_id: str
    store_id: str
    source_snapshot_digest: str
    retained_attempts: tuple[
        CodingWindowsWorkerNativeProvisioningRetainedAttemptV1, ...
    ]
    attempt_ids: tuple[str, ...]
    record_digest: str
    version: int = 1

    @classmethod
    def from_semantic_read(
        cls,
        prepared: CodingWindowsWorkerHistoryPreparationV1,
        semantic: CodingWindowsWorkerHistorySemanticReadV1,
    ) -> CodingWindowsWorkerNativeProvisioningSemanticBaseV1:
        if type(prepared) is not CodingWindowsWorkerHistoryPreparationV1:
            raise ValueError(
                "Windows Worker native provisioning preparation is invalid"
            )
        prepared.require_semantic_read(semantic)
        return cls._from_source_read(
            semantic.source_snapshot, semantic.offline_recovery
        )

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
