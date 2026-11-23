"""Read-only cross-check of frozen old management operations and Desired state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loushang.harness.package_product._legacy_management_evidence import (
    classify_management_members,
)
from loushang.harness.plugin_management.retirement_sets import (
    RetirementCaptureFields,
)
from loushang.harness.plugin_management.service import (
    inspect_settled_management_capture,
)

from .legacy_desired_evidence import CodingLegacyDesiredEvidenceV1

_MAX_OPERATION_BYTES = 2 * 1024 * 1024


class CodingLegacyOperationEvidenceError(ValueError):
    """The old operation journal cannot prove settled Desired history."""


def classify_coding_legacy_management_members(
    *,
    desired_members: tuple[str, ...],
    instance_members: tuple[str, ...],
    lock_members: tuple[str, ...],
    has_binding: bool = True,
    allow_retirement: bool = False,
    allow_retired_runtime: bool = False,
) -> bool:
    """Identify only the simple or exact Service shape without retirement rows."""

    return classify_management_members(
        desired_members=desired_members,
        instance_members=instance_members,
        lock_members=lock_members,
        has_binding=has_binding,
        allow_retirement=allow_retirement,
        allow_retired_runtime=allow_retired_runtime,
        error_type=CodingLegacyOperationEvidenceError,
        label="Coding old",
    )


@dataclass(frozen=True, slots=True)
class CodingLegacyOperationEvidenceV1:
    journal_digest: str
    update_operation_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CodingLegacyRetirementCaptureV1(RetirementCaptureFields):
    intents_raw: bytes
    sets_raw: bytes
    intents_path: Path
    sets_path: Path


def parse_coding_legacy_operation_evidence(
    raw: bytes,
    *,
    desired: CodingLegacyDesiredEvidenceV1,
    path: Path,
    retirements: CodingLegacyRetirementCaptureV1 | None = None,
) -> CodingLegacyOperationEvidenceV1:
    """Verify settled operations against one complete old Desired capture."""

    if (
        not isinstance(raw, bytes)
        or len(raw) > _MAX_OPERATION_BYTES
        or not isinstance(desired, CodingLegacyDesiredEvidenceV1)
        or not isinstance(path, Path)
        or (
            retirements is not None
            and not isinstance(retirements, CodingLegacyRetirementCaptureV1)
        )
    ):
        raise CodingLegacyOperationEvidenceError(
            "Coding old management operation evidence is invalid"
        )
    return CodingLegacyOperationEvidenceV1(
        *inspect_settled_management_capture(
            raw,
            path=path,
            desired_transitions=desired.transitions,
            retirements=retirements,
            maximum_bytes=_MAX_OPERATION_BYTES,
            error_type=CodingLegacyOperationEvidenceError,
            label="Coding old",
        )
    )


__all__ = [
    "CodingLegacyOperationEvidenceError",
    "CodingLegacyOperationEvidenceV1",
    "CodingLegacyRetirementCaptureV1",
    "classify_coding_legacy_management_members",
    "parse_coding_legacy_operation_evidence",
]
